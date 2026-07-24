import stat
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any


UploadState = dict[str, str]
UploadCallbackResult = bool | Mapping[str, object] | None


class UploadResultError(RuntimeError):
    """Raised when an upload callback does not explicitly report success."""


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


def _cleanup_local_files(paths: tuple[Path, ...]) -> None:
    for path in paths:
        try:
            target_stat = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LocalCleanupError(path, paths) from exc
        if not stat.S_ISREG(target_stat.st_mode):
            exc = OSError("Local cleanup target is not a regular file.")
            raise LocalCleanupError(path, paths) from exc

    for index, path in enumerate(paths):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise LocalCleanupError(path, paths[index:]) from exc


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
) -> UploadState:
    """Upload the initial record, video, and finalized record in order.

    The callback succeeds only by returning ``None``, literal ``True``, or a
    mapping whose ``ok`` value is literal ``True``.
    """
    state = {"json": "pending", "video": "pending"}
    remote_json_path = f"{remote_dir}/{json_path.name}"
    remote_video_path = f"{remote_dir}/{video_path.name}"

    try:
        result = upload_fn(json_path, remote_json_path, progress_cb=json_progress)
        _require_upload_success(result)
    except Exception:
        state["json"] = "failed"
        persist_state(dict(state))
        raise
    state["json"] = "uploaded"

    try:
        result = upload_fn(video_path, remote_video_path, progress_cb=video_progress)
        _require_upload_success(result)
    except Exception:
        state["video"] = "failed"
        persist_state(dict(state))
        raise
    state["video"] = "uploaded"

    persist_state(dict(state))
    try:
        result = upload_fn(json_path, remote_json_path, progress_cb=json_progress)
        _require_upload_success(result)
    except Exception:
        state["json"] = "failed"
        persist_state(dict(state))
        raise

    if delete_after_upload:
        paths = _cleanup_candidates(json_path, video_path, cleanup_paths)
        _cleanup_local_files(paths)

    return dict(state)
