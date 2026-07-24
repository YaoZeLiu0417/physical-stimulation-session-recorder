import json
import os
import re
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


SUBJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_LOCKS: dict[tuple[str, str], threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class RecordConflictError(RuntimeError):
    """Raised when a caller attempts to save or revise a stale record."""


class RecordCorruptionError(RuntimeError):
    """Raised when an on-disk state file fails record integrity validation."""


class RecordLockError(RuntimeError):
    """Raised when a lock path is unsafe or cannot be securely acquired."""


class RecordArchivedError(RuntimeError):
    """Raised when a lifecycle index proves the latest state is unavailable."""

    def __init__(self, index: Mapping[str, Any]) -> None:
        self.record_id = index["record_id"]
        self.intervention_day = index["intervention_day"]
        self.latest_revision = index["latest_revision"]
        self.lifecycle = index["lifecycle"]
        self.completion_status = index["completion_status"]
        self.completed_visits = tuple(index["completed_visits"])
        self.upload = dict(index["upload"])
        super().__init__(f"记录 {self.record_id} 的最新状态不可用。")


_INDEX_VERSION = 1
_COMPLETION_STATUSES = {"draft", "complete"}
_UPLOAD_STATUSES = {"pending", "uploaded", "failed"}
_LIFECYCLES = {"draft", "complete", "uploaded"}


def validate_subject_id(subject_id: str) -> str:
    if not isinstance(subject_id, str):
        raise ValueError("受试者编号仅允许字母、数字、下划线和连字符，长度为 1-64 个字符。")
    safe_subject_id = subject_id.strip()
    if not SUBJECT_ID_RE.fullmatch(safe_subject_id):
        raise ValueError("受试者编号仅允许字母、数字、下划线和连字符，长度为 1-64 个字符。")
    return safe_subject_id


def validate_record_id(record_id: str, subject_id: str, date_key: str) -> str:
    safe_subject_id = validate_subject_id(subject_id)
    if not isinstance(date_key, str) or not re.fullmatch(r"\d{8}", date_key):
        raise ValueError("记录日期必须是有效的 YYYYMMDD 日期。")
    try:
        datetime.strptime(date_key, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("记录日期必须是有效的 YYYYMMDD 日期。") from exc
    expected_pattern = rf"{re.escape(safe_subject_id)}_{date_key}_[0-9a-f]{{8}}"
    if not isinstance(record_id, str) or not re.fullmatch(expected_pattern, record_id):
        raise ValueError("记录编号必须匹配受试者、日期和 8 位小写十六进制后缀。")
    return record_id


def can_cleanup(upload: Mapping[str, str]) -> bool:
    return upload.get("json") == "uploaded" and upload.get("video") == "uploaded"


def remote_record_dir(
    save_dir: str, subject_id: str, record_date: str, record_id: str
) -> str:
    safe_subject_id = validate_subject_id(subject_id)
    validate_record_id(record_id, safe_subject_id, record_date)
    return "/".join((save_dir.rstrip("/"), safe_subject_id, record_date, record_id))


class DailyRecordStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks_root = self.root / ".locks"
        self._locks_root.mkdir(parents=True, exist_ok=True)
        self._root_resolved = self.root.resolve()
        self._validate_locks_root()

    def _validate_locks_root(self) -> None:
        expected = self._root_resolved / ".locks"
        try:
            locks_stat = os.lstat(self._locks_root)
        except OSError as exc:
            raise RecordLockError("无法验证记录锁目录。") from exc
        if (
            not stat.S_ISDIR(locks_stat.st_mode)
            or stat.S_ISLNK(locks_stat.st_mode)
            or self._locks_root.resolve() != expected
        ):
            raise RecordLockError("记录锁目录不是受信任的根目录子目录。")

    @contextmanager
    def _lock(self, token: str) -> Iterator[None]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError("锁名称包含不安全字符。")
        self._validate_locks_root()
        key = (str(self.root.resolve()), token)
        with _LOCKS_GUARD:
            local_lock = _LOCKS.setdefault(key, threading.RLock())
        lock_path = self._locks_root / f"{token}.lock"

        with local_lock:
            lock_fd: int | None = None
            lock_file = None
            locked = False
            try:
                flags = os.O_RDWR | os.O_CREAT
                flags |= getattr(os, "O_NOFOLLOW", 0)
                lock_fd = os.open(lock_path, flags, 0o600)
                path_stat = os.lstat(lock_path)
                fd_stat = os.fstat(lock_fd)
                same_inode = (
                    path_stat.st_dev == fd_stat.st_dev
                    and path_stat.st_ino == fd_stat.st_ino
                )
                inode_is_meaningful = path_stat.st_ino != 0 and fd_stat.st_ino != 0
                if (
                    stat.S_ISLNK(path_stat.st_mode)
                    or not stat.S_ISREG(fd_stat.st_mode)
                    or path_stat.st_nlink != 1
                    or fd_stat.st_nlink != 1
                    or (inode_is_meaningful and not same_inode)
                ):
                    raise RecordLockError("记录锁文件不是安全的单链接常规文件。")

                lock_file = os.fdopen(lock_fd, "r+b")
                lock_fd = None
                if fd_stat.st_size == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                    os.fsync(lock_file.fileno())
                elif fd_stat.st_size != 1:
                    raise RecordLockError("记录锁文件大小无效。")
                lock_file.seek(0)

                if os.name == "nt":
                    import msvcrt

                    while True:
                        try:
                            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            time.sleep(0.01)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                locked = True
                yield
            except OSError as exc:
                if not locked:
                    raise RecordLockError(
                        f"无法安全获取记录锁: {lock_path.name}"
                    ) from exc
                raise
            finally:
                if locked and lock_file is not None:
                    try:
                        lock_file.seek(0)
                        if os.name == "nt":
                            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
                if lock_file is not None:
                    lock_file.close()
                elif lock_fd is not None:
                    os.close(lock_fd)

    def _matching_paths(self, subject_id: str, record_date: date) -> list[Path]:
        safe_subject_id = validate_subject_id(subject_id)
        date_key = record_date.strftime("%Y%m%d")
        return sorted(self.root.glob(f"{safe_subject_id}_{date_key}_*_r*_state.json"))

    def _identity_path(self, subject_id: str, record_date: date) -> Path:
        token = self._day_lock_token(subject_id, record_date)
        path = self.root / f".{token}_identity.json"
        if path.parent.resolve() != self._root_resolved:
            raise ValueError("记录身份索引必须保存在记录根目录中。")
        return path

    def _generation_path(self, subject_id: str, record_date: date) -> Path:
        token = self._day_lock_token(subject_id, record_date)
        path = self.root / f".{token}_generation.json"
        if path.parent.resolve() != self._root_resolved:
            raise ValueError("generation index must stay inside record root")
        return path

    @staticmethod
    def _day_lock_token(subject_id: str, record_date: date) -> str:
        safe_subject_id = validate_subject_id(subject_id)
        if not isinstance(record_date, date):
            raise ValueError("记录日期必须是 date 对象。")
        return f"{safe_subject_id}_{record_date:%Y%m%d}"

    def _new_record(
        self, subject_id: str, record_date: date, intervention_day: int
    ) -> dict[str, Any]:
        safe_subject_id = validate_subject_id(subject_id)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {
            "schema_version": 4,
            "record_id": f"{safe_subject_id}_{record_date:%Y%m%d}_{uuid.uuid4().hex[:8]}",
            "subject_id": safe_subject_id,
            "record_date": record_date.isoformat(),
            "intervention_day": intervention_day,
            "revision": 1,
            "instrument_versions": {
                "daily_nssi_ema": "1.0",
                "weekly_nssi": "1.0",
                "formal_nssi_crf": "1.0",
            },
            "daily_core": {},
            "conditional_details": {},
            "weekly_extension": {},
            "formal_visits": {},
            "field_status": {},
            "derived_metrics": {},
            "safety_signals": {},
            "recording": {},
            "completion": {
                "status": "draft",
                "answered_field_ids": {},
                "current_step": {},
                "questionnaire_visits": {},
            },
            "upload": {"json": "pending", "video": "pending"},
            "local_cleanup": {"requested": False, "status": "idle"},
            "created_at_iso": now,
            "updated_at_iso": now,
        }

    @staticmethod
    def _validate_revision(revision: Any) -> int:
        if type(revision) is not int or revision < 1:
            raise ValueError("记录修订号必须是大于等于 1 的整数。")
        return revision

    @staticmethod
    def _parse_timestamp(timestamp: Any) -> datetime:
        if not isinstance(timestamp, str) or "T" not in timestamp:
            raise ValueError("更新时间必须是秒精度 ISO 日期时间。")
        parsed = datetime.fromisoformat(timestamp)
        if parsed.microsecond != 0 or timestamp != parsed.isoformat(timespec="seconds"):
            raise ValueError("更新时间必须是秒精度 ISO 日期时间。")
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

    @staticmethod
    def _validate_intervention_day(value: Any) -> int:
        if type(value) is not int or not 1 <= value <= 28:
            raise ValueError("干预日必须是 1 到 28 的整数。")
        return value

    @staticmethod
    def _validate_upload(upload: Any) -> dict[str, str]:
        if not isinstance(upload, Mapping) or set(upload) != {"json", "video"}:
            raise ValueError("上传状态无效。")
        validated = {key: upload[key] for key in ("json", "video")}
        if any(value not in _UPLOAD_STATUSES for value in validated.values()):
            raise ValueError("上传状态无效。")
        return validated

    def _identity_from_record(self, record: Mapping[str, Any]) -> tuple[str, date, str, int]:
        try:
            safe_subject_id = validate_subject_id(record["subject_id"])
            record_date = record["record_date"]
            if not isinstance(record_date, str):
                raise ValueError("记录日期必须是 ISO YYYY-MM-DD 格式。")
            parsed_date = date.fromisoformat(record_date)
            if parsed_date.isoformat() != record_date:
                raise ValueError("记录日期必须是 ISO YYYY-MM-DD 格式。")
            date_key = parsed_date.strftime("%Y%m%d")
            record_id = validate_record_id(record["record_id"], safe_subject_id, date_key)
            revision = self._validate_revision(record["revision"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("记录身份或修订号无效。") from exc
        return safe_subject_id, parsed_date, record_id, revision

    def _target_for_identity(
        self, record_id: str, revision: int, record: Mapping[str, Any]
    ) -> Path:
        target = self.root / f"{record_id}_r{revision}_state.json"
        if target.parent.resolve() != self.root.resolve():
            raise ValueError("记录文件必须保存在记录根目录中。")
        return target

    def path_for(self, record: Mapping[str, Any]) -> Path:
        _, _, record_id, revision = self._identity_from_record(record)
        return self._target_for_identity(record_id, revision, record)

    def _load_candidate(
        self, path: Path, subject_id: str, record_date: date
    ) -> dict[str, Any]:
        try:
            path_stat = os.lstat(path)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or stat.S_ISLNK(path_stat.st_mode)
                or path_stat.st_nlink != 1
                or getattr(path_stat, "st_file_attributes", 0) & reparse_flag
                or path.parent.resolve() != self._root_resolved
            ):
                raise ValueError("record candidate path is unsafe")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(path, flags), "r", encoding="utf-8") as handle:
                fd_stat = os.fstat(handle.fileno())
                current_stat = os.lstat(path)
                inode_is_meaningful = (
                    path_stat.st_ino != 0
                    and fd_stat.st_ino != 0
                    and current_stat.st_ino != 0
                )
                same_open_file = (
                    path_stat.st_dev == fd_stat.st_dev
                    and path_stat.st_ino == fd_stat.st_ino
                    and current_stat.st_dev == fd_stat.st_dev
                    and current_stat.st_ino == fd_stat.st_ino
                )
                if (
                    not stat.S_ISREG(fd_stat.st_mode)
                    or fd_stat.st_nlink != 1
                    or getattr(fd_stat, "st_file_attributes", 0) & reparse_flag
                    or not stat.S_ISREG(current_stat.st_mode)
                    or stat.S_ISLNK(current_stat.st_mode)
                    or current_stat.st_nlink != 1
                    or getattr(current_stat, "st_file_attributes", 0) & reparse_flag
                    or (inode_is_meaningful and not same_open_file)
                ):
                    raise ValueError("record candidate changed during open")
                record = json.load(handle)
            if not isinstance(record, dict):
                raise ValueError("记录 JSON 顶层必须是对象。")
            actual_subject, actual_date, record_id, revision = self._identity_from_record(record)
            if actual_subject != subject_id or actual_date != record_date:
                raise ValueError("记录身份与请求不匹配。")
            expected_name = f"{record_id}_r{revision}_state.json"
            if path.name != expected_name:
                raise ValueError("记录文件名与 JSON 内容不匹配。")
            self._parse_timestamp(record["updated_at_iso"])
            return record
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RecordCorruptionError(f"记录文件损坏或无效: {path.name}") from exc

    def _index_from_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        subject_id, record_date, record_id, revision = self._identity_from_record(record)
        intervention_day = self._validate_intervention_day(record["intervention_day"])
        updated_at_iso = record["updated_at_iso"]
        self._parse_timestamp(updated_at_iso)
        completion = record.get("completion", {})
        if not isinstance(completion, Mapping):
            raise ValueError("完成状态无效。")
        stored_completion_status = completion.get("status", "draft")
        if stored_completion_status not in {"draft", "in_progress", "complete"}:
            raise ValueError("完成状态无效。")
        completion_status = (
            "complete" if stored_completion_status == "complete" else "draft"
        )
        visits = completion.get("questionnaire_visits", {})
        if not isinstance(visits, Mapping):
            raise ValueError("问卷完成状态无效。")
        completed_visits = sorted(
            visit
            for visit, status in visits.items()
            if isinstance(visit, str)
            and isinstance(status, Mapping)
            and status.get("status") == "complete"
            and status.get("revision") == revision
        )
        upload = self._validate_upload(record.get("upload", {}))
        lifecycle = (
            "uploaded"
            if can_cleanup(upload)
            else "complete"
            if completion_status == "complete"
            else "draft"
        )
        return {
            "index_version": _INDEX_VERSION,
            "subject_id": subject_id,
            "record_date": record_date.isoformat(),
            "record_id": record_id,
            "intervention_day": intervention_day,
            "latest_revision": revision,
            "record_updated_at_iso": updated_at_iso,
            "completion_status": completion_status,
            "completed_visits": completed_visits,
            "upload": upload,
            "lifecycle": lifecycle,
        }

    def _load_secure_json_unlocked(self, path: Path) -> Any | None:
        try:
            path_stat = os.lstat(path)
        except FileNotFoundError:
            return None
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or path_stat.st_nlink != 1
            or getattr(path_stat, "st_file_attributes", 0) & reparse_flag
            or path.parent.resolve() != self._root_resolved
        ):
            raise ValueError("lifecycle index path is unsafe")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "r", encoding="utf-8") as handle:
            descriptor_stat = os.fstat(handle.fileno())
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
                raise ValueError("lifecycle index changed during open")
            return json.load(handle)

    def _load_identity_unlocked(
        self, subject_id: str, record_date: date
    ) -> dict[str, Any] | None:
        path = self._identity_path(subject_id, record_date)
        try:
            identity = self._load_secure_json_unlocked(path)
            if identity is None:
                return None
            if not isinstance(identity, dict):
                raise ValueError("记录身份索引必须是对象。")
            if set(identity) != {
                "index_version", "subject_id", "record_date", "record_id",
                "intervention_day", "latest_revision", "record_updated_at_iso",
                "completion_status", "completed_visits", "upload", "lifecycle",
            } or identity["index_version"] != _INDEX_VERSION:
                raise ValueError("记录身份索引版本或结构无效。")
            actual_subject = validate_subject_id(identity["subject_id"])
            actual_date = date.fromisoformat(identity["record_date"])
            if actual_date.isoformat() != identity["record_date"]:
                raise ValueError("记录身份索引日期无效。")
            record_id = validate_record_id(
                identity["record_id"], actual_subject, actual_date.strftime("%Y%m%d")
            )
            if actual_subject != subject_id or actual_date != record_date:
                raise ValueError("记录身份索引与请求不匹配。")
            intervention_day = self._validate_intervention_day(identity["intervention_day"])
            latest_revision = self._validate_revision(identity["latest_revision"])
            self._parse_timestamp(identity["record_updated_at_iso"])
            completion_status = identity["completion_status"]
            completed_visits = identity["completed_visits"]
            upload = self._validate_upload(identity["upload"])
            lifecycle = identity["lifecycle"]
            if (
                completion_status not in _COMPLETION_STATUSES
                or not isinstance(completed_visits, list)
                or any(not isinstance(visit, str) or not visit for visit in completed_visits)
                or completed_visits != sorted(set(completed_visits))
                or lifecycle not in _LIFECYCLES
            ):
                raise ValueError("记录身份索引摘要无效。")
            expected_lifecycle = (
                "uploaded" if can_cleanup(upload)
                else "complete" if completion_status == "complete" else "draft"
            )
            if lifecycle != expected_lifecycle:
                raise ValueError("记录身份索引生命周期无效。")
            return {
                "index_version": _INDEX_VERSION,
                "subject_id": actual_subject,
                "record_date": actual_date.isoformat(),
                "record_id": record_id,
                "intervention_day": intervention_day,
                "latest_revision": latest_revision,
                "record_updated_at_iso": identity["record_updated_at_iso"],
                "completion_status": completion_status,
                "completed_visits": completed_visits,
                "upload": upload,
                "lifecycle": lifecycle,
            }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RecordCorruptionError(f"记录身份索引损坏或无效: {path.name}") from exc

    def _write_identity_unlocked(self, record: Mapping[str, Any]) -> None:
        subject_id, record_date, _, _ = self._identity_from_record(record)
        path = self._identity_path(subject_id, record_date)
        identity = self._index_from_record(record)
        serialized = json.dumps(identity, ensure_ascii=False, indent=2)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _load_generation_unlocked(
        self, subject_id: str, record_date: date
    ) -> dict[str, Any] | None:
        path = self._generation_path(subject_id, record_date)
        try:
            generation = self._load_secure_json_unlocked(path)
            if generation is None:
                return None
            expected_keys = {
                "generation_version", "subject_id", "record_date", "record_id",
                "intervention_day", "highest_revision", "record_updated_at_iso",
                "completion_status", "completed_visits", "upload", "lifecycle",
            }
            if not isinstance(generation, dict) or set(generation) != expected_keys:
                raise ValueError("generation marker structure is invalid")
            if generation["generation_version"] != _INDEX_VERSION:
                raise ValueError("generation marker version is invalid")
            actual_subject = validate_subject_id(generation["subject_id"])
            actual_date = date.fromisoformat(generation["record_date"])
            if actual_date.isoformat() != generation["record_date"]:
                raise ValueError("generation marker date is invalid")
            record_id = validate_record_id(
                generation["record_id"], actual_subject, actual_date.strftime("%Y%m%d")
            )
            if actual_subject != subject_id or actual_date != record_date:
                raise ValueError("generation marker identity does not match request")
            intervention_day = self._validate_intervention_day(generation["intervention_day"])
            highest_revision = self._validate_revision(generation["highest_revision"])
            self._parse_timestamp(generation["record_updated_at_iso"])
            completion_status = generation["completion_status"]
            completed_visits = generation["completed_visits"]
            upload = self._validate_upload(generation["upload"])
            lifecycle = generation["lifecycle"]
            if (
                completion_status not in _COMPLETION_STATUSES
                or not isinstance(completed_visits, list)
                or any(not isinstance(visit, str) or not visit for visit in completed_visits)
                or completed_visits != sorted(set(completed_visits))
                or lifecycle not in _LIFECYCLES
            ):
                raise ValueError("generation marker summary is invalid")
            expected_lifecycle = (
                "uploaded" if can_cleanup(upload)
                else "complete" if completion_status == "complete" else "draft"
            )
            if lifecycle != expected_lifecycle:
                raise ValueError("generation marker lifecycle is invalid")
            return {
                "index_version": _INDEX_VERSION,
                "generation_version": _INDEX_VERSION,
                "subject_id": actual_subject,
                "record_date": actual_date.isoformat(),
                "record_id": record_id,
                "intervention_day": intervention_day,
                "latest_revision": highest_revision,
                "highest_revision": highest_revision,
                "record_updated_at_iso": generation["record_updated_at_iso"],
                "completion_status": completion_status,
                "completed_visits": completed_visits,
                "upload": upload,
                "lifecycle": lifecycle,
            }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RecordCorruptionError(f"generation marker corrupt: {path.name}") from exc

    def _write_generation_unlocked(self, record: Mapping[str, Any]) -> None:
        self._write_generation_index_unlocked(self._index_from_record(record))

    def _write_generation_index_unlocked(self, index: Mapping[str, Any]) -> None:
        subject_id = index["subject_id"]
        record_date = date.fromisoformat(index["record_date"])
        path = self._generation_path(subject_id, record_date)
        generation = {
            "generation_version": _INDEX_VERSION,
            "subject_id": index["subject_id"],
            "record_date": index["record_date"],
            "record_id": index["record_id"],
            "intervention_day": index["intervention_day"],
            "highest_revision": index["latest_revision"],
            "record_updated_at_iso": index["record_updated_at_iso"],
            "completion_status": index["completion_status"],
            "completed_visits": index["completed_visits"],
            "upload": index["upload"],
            "lifecycle": index["lifecycle"],
        }
        serialized = json.dumps(generation, ensure_ascii=False, indent=2)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _validate_index_for_write_unlocked(self, record: Mapping[str, Any]) -> None:
        subject_id, record_date, record_id, revision = self._identity_from_record(record)
        index = self._load_identity_unlocked(subject_id, record_date)
        if index is None:
            return
        if index["record_id"] != record_id or index["latest_revision"] > revision:
            raise RecordCorruptionError("记录身份索引与状态文件冲突。")

    def _latest_unlocked(self, subject_id: str, record_date: date) -> dict[str, Any] | None:
        candidates = [
            self._load_candidate(path, subject_id, record_date)
            for path in self._matching_paths(subject_id, record_date)
        ]
        if not candidates:
            return None
        record_ids = {record["record_id"] for record in candidates}
        if len(record_ids) != 1:
            raise RecordCorruptionError("同一日期的状态文件包含冲突的记录身份。")
        return max(candidates, key=lambda record: record["revision"])

    def _reconcile_unlocked(
        self, subject_id: str, record_date: date
    ) -> dict[str, Any] | None:
        index = self._load_identity_unlocked(subject_id, record_date)
        generation = self._load_generation_unlocked(subject_id, record_date)
        latest = self._latest_unlocked(subject_id, record_date)
        summary_keys = (
            "subject_id", "record_date", "record_id", "intervention_day",
            "latest_revision", "record_updated_at_iso", "completion_status",
            "completed_visits", "upload", "lifecycle",
        )
        if generation is None and index is not None:
            self._write_generation_index_unlocked(index)
            generation = self._load_generation_unlocked(subject_id, record_date)
        elif generation is None and latest is not None:
            self._write_generation_unlocked(latest)
            generation = self._load_generation_unlocked(subject_id, record_date)
        if generation is not None:
            if index is not None and index["record_id"] != generation["record_id"]:
                raise RecordCorruptionError("lifecycle indexes contain conflicting record identities")
            if latest is not None and latest["record_id"] != generation["record_id"]:
                raise RecordCorruptionError("generation marker conflicts with state file")
            if latest is not None and latest["revision"] < generation["highest_revision"]:
                raise RecordArchivedError(generation)
            if latest is not None:
                latest_updated = self._parse_timestamp(latest["updated_at_iso"])
                generation_updated = self._parse_timestamp(generation["record_updated_at_iso"])
                if latest["revision"] == generation["highest_revision"]:
                    if generation_updated > latest_updated:
                        raise RecordArchivedError(generation)
                    if generation_updated == latest_updated:
                        try:
                            latest_summary = self._index_from_record(latest)
                        except (KeyError, TypeError, ValueError) as exc:
                            raise RecordCorruptionError(
                                "generation marker conflicts with state summary"
                            ) from exc
                        if any(
                            latest_summary[key] != generation[key]
                            for key in summary_keys
                        ):
                            raise RecordCorruptionError(
                                "generation marker conflicts with state summary"
                            )
                if (
                    latest["revision"] > generation["highest_revision"]
                    or latest_updated > generation_updated
                ):
                    self._write_generation_unlocked(latest)
                    generation = self._load_generation_unlocked(subject_id, record_date)
            elif index is None:
                raise RecordArchivedError(generation)
        if index is None:
            if latest is not None:
                self._write_identity_unlocked(latest)
            return latest
        if latest is None:
            raise RecordArchivedError(generation or index)
        if index["record_id"] != latest["record_id"]:
            raise RecordCorruptionError("记录身份索引与状态文件冲突。")
        latest_revision = latest["revision"]
        index_revision = index["latest_revision"]
        if index_revision > latest_revision:
            raise RecordArchivedError(index)
        latest_updated = self._parse_timestamp(latest["updated_at_iso"])
        index_updated = self._parse_timestamp(index["record_updated_at_iso"])
        if latest_revision > index_revision or latest_updated > index_updated:
            self._write_identity_unlocked(latest)
            return latest
        if latest_revision == index_revision and latest["updated_at_iso"] == index["record_updated_at_iso"]:
            return latest
        raise RecordCorruptionError("记录身份索引的修订时间与状态文件冲突。")

    def get_or_create(
        self, subject_id: str, record_date: date, intervention_day: int
    ) -> dict[str, Any]:
        safe_subject_id = validate_subject_id(subject_id)
        if not isinstance(record_date, date):
            raise ValueError("记录日期必须是 date 对象。")
        with self._lock(self._day_lock_token(safe_subject_id, record_date)):
            latest = self._reconcile_unlocked(safe_subject_id, record_date)
            if latest is not None:
                return latest
            record = self._new_record(safe_subject_id, record_date, intervention_day)
            self._write_unlocked(record, previous_updated_at=None, require_absent=True)
            return record

    @staticmethod
    def _next_updated_at(previous_updated_at: str | None) -> str:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if previous_updated_at is not None:
            previous = DailyRecordStore._parse_timestamp(previous_updated_at)
            if now <= previous:
                now = previous + timedelta(seconds=1)
        return now.isoformat(timespec="seconds")

    def _write_unlocked(
        self,
        record: dict[str, Any],
        previous_updated_at: str | None,
        require_absent: bool,
    ) -> Path:
        target = self.path_for(record)
        self._validate_index_for_write_unlocked(record)
        subject_id, record_date, record_id, revision = self._identity_from_record(record)
        generation = self._load_generation_unlocked(subject_id, record_date)
        if generation is not None:
            if generation["record_id"] != record_id or generation["highest_revision"] > revision:
                raise RecordCorruptionError("generation marker conflicts with state file")
        if require_absent and target.exists():
            raise RecordConflictError(f"修订文件已存在: {target.name}")
        payload = deepcopy(record)
        payload["updated_at_iso"] = self._next_updated_at(previous_updated_at)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        record["updated_at_iso"] = payload["updated_at_iso"]
        if (
            generation is None
            or generation["highest_revision"] < revision
            or self._parse_timestamp(payload["updated_at_iso"])
            > self._parse_timestamp(generation["record_updated_at_iso"])
        ):
            self._write_generation_unlocked(record)
        self._write_identity_unlocked(record)
        return target

    def save(self, record: dict[str, Any]) -> Path:
        subject_id, record_date, record_id, revision = self._identity_from_record(record)
        with self._lock(self._day_lock_token(subject_id, record_date)):
            latest = self._reconcile_unlocked(subject_id, record_date)
            if latest is None:
                if revision != 1:
                    raise RecordConflictError("无法创建非初始修订。")
                return self._write_unlocked(record, None, require_absent=True)
            if latest["record_id"] != record_id or latest["revision"] != revision:
                raise RecordConflictError("尝试保存的记录不是最新修订。")
            if record.get("updated_at_iso") != latest.get("updated_at_iso"):
                raise RecordConflictError("记录已被其他调用者更新。")
            return self._write_unlocked(
                record, latest["updated_at_iso"], require_absent=False
            )

    def revise(self, record: Mapping[str, Any]) -> dict[str, Any]:
        subject_id, record_date, record_id, revision = self._identity_from_record(record)
        with self._lock(self._day_lock_token(subject_id, record_date)):
            latest = self._reconcile_unlocked(subject_id, record_date)
            if latest is None:
                raise RecordConflictError("找不到要修订的记录。")
            if latest["record_id"] != record_id or latest["revision"] != revision:
                raise RecordConflictError("尝试修订的记录不是最新修订。")
            if record.get("updated_at_iso") != latest.get("updated_at_iso"):
                raise RecordConflictError("记录已被其他调用者更新。")

            revised = deepcopy(record)
            revised["supersedes_revision"] = revision
            revised["revision"] = revision + 1
            revised["completion"] = {
                "status": "draft",
                "answered_field_ids": {},
                "current_step": {},
                "questionnaire_visits": {},
            }
            prior_upload = revised.get("upload", {})
            video_status = prior_upload.get("video", "pending")
            revised["upload"] = {"json": "pending", "video": video_status}
            self._write_unlocked(
                revised, latest["updated_at_iso"], require_absent=True
            )
            return revised
