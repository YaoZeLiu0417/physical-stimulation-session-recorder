import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any


UploadState = dict[str, str]
UploadCallbackResult = bool | Mapping[str, object] | None
_MISSING_CLEANUP_PATH = object()
_UNKNOWN_CLEANUP_PATH = object()


class UploadResultError(RuntimeError):
    """Raised when an upload callback does not explicitly report success."""


class UnsafeUploadSourceError(OSError):
    """Raised when an upload source cannot be bound to one safe file."""


class LocalCleanupError(RuntimeError):
    """Raised after successful uploads when local cleanup cannot finish."""

    uploads_completed = True

    def __init__(self, failed_path: Path, remaining_paths: Iterable[Path]):
        super().__init__("Upload completed, but local cleanup is incomplete.")
        self.failed_path = failed_path
        self.remaining_paths = tuple(remaining_paths)


def _require_upload_success(result: object) -> None:
    if result is None or result is True:
        return
    if isinstance(result, Mapping) and result.get("ok") is True:
        return
    raise UploadResultError("Upload callback did not report success.")


def _open_upload_source(path: Path) -> tuple[int, os.stat_result]:
    descriptor: int | None = None
    try:
        path_stat = os.lstat(path)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or path_stat.st_nlink != 1
            or getattr(path_stat, "st_file_attributes", 0) & reparse_flag
        ):
            raise OSError("upload source path is unsafe")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        descriptor_stat = os.fstat(descriptor)
        current_stat = os.lstat(path)
        inode_is_meaningful = (
            path_stat.st_ino != 0
            and descriptor_stat.st_ino != 0
            and current_stat.st_ino != 0
        )
        same_open_file = (
            path_stat.st_dev == descriptor_stat.st_dev
            and path_stat.st_ino == descriptor_stat.st_ino
            and current_stat.st_dev == descriptor_stat.st_dev
            and current_stat.st_ino == descriptor_stat.st_ino
        )
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or descriptor_stat.st_nlink != 1
            or getattr(descriptor_stat, "st_file_attributes", 0) & reparse_flag
            or not stat.S_ISREG(current_stat.st_mode)
            or stat.S_ISLNK(current_stat.st_mode)
            or current_stat.st_nlink != 1
            or getattr(current_stat, "st_file_attributes", 0) & reparse_flag
            or (inode_is_meaningful and not same_open_file)
        ):
            raise OSError("upload source changed during secure open")
        opened_descriptor = descriptor
        descriptor = None
        return opened_descriptor, descriptor_stat
    except OSError as exc:
        raise UnsafeUploadSourceError("upload source is unsafe") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _upload_private_snapshot(
    source_path: Path,
    remote_path: str,
    upload_fn: Callable[..., UploadCallbackResult],
    *,
    progress_cb: Any,
) -> tuple[UploadCallbackResult, os.stat_result]:
    source_descriptor, source_stat = _open_upload_source(source_path)
    try:
        with tempfile.TemporaryDirectory(prefix="bundle-upload-") as temporary_dir:
            snapshot = Path(temporary_dir) / source_path.name
            snapshot_descriptor = os.open(
                snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            try:
                with os.fdopen(source_descriptor, "rb") as source:
                    source_descriptor = -1
                    with os.fdopen(snapshot_descriptor, "wb") as target:
                        snapshot_descriptor = -1
                        shutil.copyfileobj(source, target)
                        target.flush()
                        os.fsync(target.fileno())
            finally:
                if snapshot_descriptor >= 0:
                    os.close(snapshot_descriptor)
            os.chmod(snapshot, 0o600)
            return (
                upload_fn(snapshot, remote_path, progress_cb=progress_cb),
                source_stat,
            )
    finally:
        if source_descriptor >= 0:
            os.close(source_descriptor)


def upload_private_snapshot(
    source_path: Path,
    remote_path: str,
    upload_fn: Callable[..., UploadCallbackResult],
    *,
    progress_cb: Any = None,
    delete_after_upload: bool = False,
    after_upload_success: Callable[[UploadCallbackResult], None] | None = None,
) -> UploadCallbackResult:
    """Upload one descriptor-backed snapshot and optionally delete its source."""

    result, source_stat = _upload_private_snapshot(
        source_path, remote_path, upload_fn, progress_cb=progress_cb
    )
    _require_upload_success(result)
    if after_upload_success is not None:
        after_upload_success(result)
    if delete_after_upload:
        _cleanup_local_files(
            (source_path,), expected_stats={source_path: source_stat}
        )
    return result


def upload_generated_json(
    payload: Mapping[str, Any],
    *,
    filename: str,
    remote_path: str,
    upload_fn: Callable[..., UploadCallbackResult],
    progress_cb: Any = None,
) -> UploadCallbackResult:
    """Upload generated JSON without creating a predictable application file."""

    if not filename or Path(filename).name != filename:
        raise ValueError("generated JSON filename must be a basename")
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    with tempfile.TemporaryDirectory(prefix="generated-json-upload-") as temporary_dir:
        snapshot = Path(temporary_dir) / filename
        descriptor = os.open(
            snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        os.chmod(snapshot, 0o600)
        result = upload_fn(snapshot, remote_path, progress_cb=progress_cb)
        _require_upload_success(result)
        return result


def _cleanup_candidates(
    json_path: Path, video_path: Path, cleanup_paths: Iterable[Path]
) -> tuple[Path, ...]:
    extras = []
    seen = set()
    for path in cleanup_paths:
        if path == json_path or path == video_path or path in seen:
            continue
        seen.add(path)
        extras.append(path)

    candidates = list(extras)
    for path in (video_path, json_path):
        if path in seen:
            continue
        seen.add(path)
        candidates.append(path)
    return tuple(candidates)


def _same_file(before: os.stat_result, current: os.stat_result) -> bool:
    inode_is_meaningful = before.st_ino != 0 and current.st_ino != 0
    if inode_is_meaningful:
        return before.st_dev == current.st_dev and before.st_ino == current.st_ino
    return (
        before.st_dev == current.st_dev
        and before.st_size == current.st_size
        and before.st_mtime_ns == current.st_mtime_ns
    )


def _validate_cleanup_stat(target_stat: os.stat_result) -> None:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        not stat.S_ISREG(target_stat.st_mode)
        or stat.S_ISLNK(target_stat.st_mode)
        or target_stat.st_nlink != 1
        or getattr(target_stat, "st_file_attributes", 0) & reparse_flag
    ):
        raise OSError("Local cleanup target is unsafe.")


def _capture_cleanup_expectations(paths: Iterable[Path]) -> dict[Path, object]:
    expectations: dict[Path, object] = {}
    for path in paths:
        try:
            target_stat = path.lstat()
            _validate_cleanup_stat(target_stat)
        except FileNotFoundError:
            expectations[path] = _MISSING_CLEANUP_PATH
        except OSError:
            expectations[path] = _UNKNOWN_CLEANUP_PATH
        else:
            expectations[path] = target_stat
    return expectations


def _cleanup_local_files(
    paths: tuple[Path, ...],
    *,
    expected_stats: Mapping[Path, object] | None = None,
) -> None:
    expected_stats = expected_stats or {}
    preflight_stats: dict[Path, object | None] = {}
    preflight_failure: tuple[Path, OSError] | None = None
    for path in paths:
        try:
            target_stat = path.lstat()
        except FileNotFoundError:
            preflight_stats[path] = None
            continue
        except OSError as exc:
            preflight_stats[path] = _UNKNOWN_CLEANUP_PATH
            if preflight_failure is None:
                preflight_failure = (path, exc)
            continue
        try:
            _validate_cleanup_stat(target_stat)
            if path in expected_stats:
                expected_stat = expected_stats[path]
                if expected_stat is _MISSING_CLEANUP_PATH:
                    raise OSError("Local cleanup target appeared after upload started.")
                if expected_stat is _UNKNOWN_CLEANUP_PATH:
                    raise OSError("Local cleanup target was not safely observable.")
                if not isinstance(expected_stat, os.stat_result) or not _same_file(
                    expected_stat, target_stat
                ):
                    raise OSError("Local cleanup target changed after upload.")
        except OSError as exc:
            if preflight_failure is None:
                preflight_failure = (path, exc)
        preflight_stats[path] = target_stat

    active_paths = tuple(
        path for path in paths if preflight_stats[path] is not None
    )
    if preflight_failure is not None:
        failed_path, failure = preflight_failure
        raise LocalCleanupError(failed_path, active_paths) from failure

    for path in paths:
        preflight_stat = preflight_stats[path]
        remaining_paths = tuple(
            candidate
            for candidate in paths[paths.index(path):]
            if preflight_stats[candidate] is not None or candidate == path
        )
        try:
            current_stat = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LocalCleanupError(path, remaining_paths) from exc
        try:
            _validate_cleanup_stat(current_stat)
            if (
                preflight_stat is None
                or not isinstance(preflight_stat, os.stat_result)
                or not _same_file(preflight_stat, current_stat)
            ):
                raise OSError("Local cleanup target changed before deletion.")
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise LocalCleanupError(path, remaining_paths) from exc


def cleanup_uploaded_bundle(
    json_path: Path,
    video_path: Path,
    *,
    cleanup_paths: Iterable[Path] = (),
) -> None:
    """Retry local deletion after a bundle is already durably uploaded."""

    _cleanup_local_files(_cleanup_candidates(json_path, video_path, cleanup_paths))


def upload_record_bundle(
    json_path: Path,
    video_path: Path,
    remote_dir: str,
    upload_fn: Callable[..., UploadCallbackResult],
    *,
    persist_state: Callable[[UploadState], None],
    delete_after_upload: bool,
    cleanup_paths: Iterable[Path] = (),
    json_progress: Any = None,
    video_progress: Any = None,
    confirm_final_sync: Callable[[], None] | None = None,
) -> UploadState:
    """Upload the initial record, video, and finalized record in order.

    The callback succeeds only by returning ``None``, literal ``True``, or a
    mapping whose ``ok`` value is literal ``True``.
    """
    state = {"json": "pending", "video": "pending"}
    cleanup_paths = tuple(cleanup_paths)
    cleanup_candidates = _cleanup_candidates(json_path, video_path, cleanup_paths)
    extra_cleanup_expectations = {}
    if delete_after_upload:
        extra_cleanup_expectations = _capture_cleanup_expectations(
            path
            for path in cleanup_candidates
            if path != json_path and path != video_path
        )
    remote_json_path = f"{remote_dir}/{json_path.name}"
    remote_video_path = f"{remote_dir}/{video_path.name}"

    try:
        result, _ = _upload_private_snapshot(
            json_path, remote_json_path, upload_fn, progress_cb=json_progress
        )
        _require_upload_success(result)
    except Exception:
        state["json"] = "failed"
        persist_state(dict(state))
        raise
    state["json"] = "uploaded"

    try:
        result, video_source_stat = _upload_private_snapshot(
            video_path, remote_video_path, upload_fn, progress_cb=video_progress
        )
        _require_upload_success(result)
    except Exception:
        state["video"] = "failed"
        persist_state(dict(state))
        raise
    state["video"] = "uploaded"

    persist_state(dict(state))
    try:
        result, final_json_source_stat = _upload_private_snapshot(
            json_path, remote_json_path, upload_fn, progress_cb=json_progress
        )
        _require_upload_success(result)
    except Exception:
        state["json"] = "failed"
        persist_state(dict(state))
        raise

    if confirm_final_sync is not None:
        confirm_final_sync()

    if delete_after_upload:
        _cleanup_local_files(
            cleanup_candidates,
            expected_stats={
                **extra_cleanup_expectations,
                json_path: final_json_source_stat,
                video_path: video_source_stat,
            },
        )

    return dict(state)
