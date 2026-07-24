"""Pure record mutation helpers used by the Streamlit recorder."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from questionnaire_scoring import daily_derived_metrics, score_formal_instrument, score_sicq
from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_INSTRUMENTS,
    weekly_due,
)
from questionnaire_ui import build_field_status, build_formal_field_status
from record_store import RecordArchivedError, validate_subject_id
from upload_workflow import (
    LocalCleanupError,
    UnsafeUploadSourceError,
    upload_private_snapshot,
)


DAILY_CONTEXT_DEFAULTS: dict[str, Any] = {
    "sleep_hours": 7.0,
    "mood_1to9": 5,
    "stress_1to9": 4,
    "pain_0to10": 1,
    "nssi_urge_0to10": 0,
    "coping_effect_1to5": 3,
    "caffeine": "少量",
    "exercise": "少量",
    "tags": [],
    "coping_used": [],
    "narrative": "",
    "triggers": "",
}


@dataclass(frozen=True)
class CompletedRecording:
    path: Path
    started_at_iso: str
    ended_at_iso: str
    format: str


@dataclass(frozen=True)
class UploadedCleanupRecovery:
    json_path: Path
    video_path: Path
    cleanup_paths: tuple[Path, ...]


class UnsafeRecordingPathError(ValueError):
    """Raised without exposing a rejected local path."""


@dataclass(frozen=True)
class AdminInterventionStateKeys:
    selection: str
    confirmation: str


def validate_intervention_day(value: object) -> int:
    if type(value) is not int:
        raise ValueError("intervention day must be an integer from 1 to 28")
    day = value
    if not 1 <= day <= 28:
        raise ValueError("intervention day must be an integer from 1 to 28")
    return day


def confirm_admin_intervention_day(value: object, *, confirmed: bool) -> int | None:
    """Return a day only after the subject-scoped admin confirmation."""

    day = validate_intervention_day(value)
    return day if confirmed else None


def admin_intervention_state_keys(
    subject_id: str, record_date: date
) -> AdminInterventionStateKeys:
    safe_subject_id = validate_subject_id(subject_id)
    if not isinstance(record_date, date):
        raise ValueError("record date must be a date")
    namespace = f"{safe_subject_id}::{record_date.isoformat()}"
    return AdminInterventionStateKeys(
        selection=f"admin_intervention_day::{namespace}",
        confirmation=f"admin_intervention_day_confirmed::{namespace}",
    )


def ensure_record_intervention_day(record: Mapping[str, Any], expected_day: object) -> int:
    expected = validate_intervention_day(expected_day)
    actual = validate_intervention_day(record.get("intervention_day"))
    if actual != expected:
        raise ValueError("stored intervention day does not match trusted selection")
    return actual


def daily_context_values(record: Mapping[str, Any]) -> dict[str, Any]:
    stored = record.get("daily_context", {})
    if not isinstance(stored, Mapping):
        stored = {}
    values: dict[str, Any] = {}
    for field_id, default in DAILY_CONTEXT_DEFAULTS.items():
        value = stored.get(field_id, default)
        values[field_id] = list(value) if isinstance(value, list) else value
    return values


def recording_context(values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only stable daily context fields when persisting a recorder gate."""

    return {
        field_id: values[field_id]
        for field_id in DAILY_CONTEXT_DEFAULTS
        if field_id in values
    }


def daily_context_state_keys(record: Mapping[str, Any]) -> dict[str, str]:
    return {
        field_id: f"daily_context::{record['record_id']}:r{record['revision']}::{field_id}"
        for field_id in DAILY_CONTEXT_DEFAULTS
    }


def _parse_recording_times(
    started_at_iso: object, ended_at_iso: object
) -> tuple[str, str] | None:
    if not isinstance(started_at_iso, str) or not isinstance(ended_at_iso, str):
        return None
    if not started_at_iso or not ended_at_iso:
        return None
    if "T" not in started_at_iso or "T" not in ended_at_iso:
        return None
    try:
        started = datetime.fromisoformat(started_at_iso)
        ended = datetime.fromisoformat(ended_at_iso)
    except (TypeError, ValueError):
        return None
    if started.tzinfo is None or ended.tzinfo is None:
        return None
    try:
        valid_order = started < ended
    except TypeError:
        return None
    if not valid_order:
        return None
    return (
        started.astimezone(timezone.utc).isoformat(timespec="seconds"),
        ended.astimezone(timezone.utc).isoformat(timespec="seconds"),
    )


def _safe_recording_path(
    record_id: str,
    candidate: object,
    recordings_dir: Path,
    *,
    allowed_names: set[str] | None = None,
) -> Path | None:
    if not isinstance(candidate, Path):
        return None
    allowed_names = allowed_names or {f"{record_id}.flv", f"{record_id}.mp4"}
    if candidate.name not in allowed_names:
        return None
    try:
        root_stat = os.lstat(recordings_dir)
        path_stat = os.lstat(candidate)
        target_stat = os.stat(candidate)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        root_reparse = getattr(root_stat, "st_file_attributes", 0) & reparse_flag
        path_reparse = getattr(path_stat, "st_file_attributes", 0) & reparse_flag
        same_inode = (
            path_stat.st_dev == target_stat.st_dev
            and path_stat.st_ino == target_stat.st_ino
        )
        inode_is_meaningful = path_stat.st_ino != 0 and target_stat.st_ino != 0
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_ISLNK(root_stat.st_mode)
            or root_reparse
            or candidate.parent.resolve() != recordings_dir.resolve()
            or candidate.resolve().parent != recordings_dir.resolve()
            or not stat.S_ISREG(path_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or path_reparse
            or path_stat.st_nlink != 1
            or target_stat.st_nlink != 1
            or (inode_is_meaningful and not same_inode)
        ):
            return None
    except OSError:
        return None
    return candidate


def trusted_recording_path(candidate: object, recordings_dir: Path) -> Path | None:
    """Validate a historical recording under the trusted recordings root."""

    if not isinstance(candidate, Path) or candidate.suffix.lower() not in {".mp4", ".flv"}:
        return None
    return _safe_recording_path(
        "historical",
        candidate,
        recordings_dir,
        allowed_names={candidate.name},
    )


def trusted_recording_files(recordings_dir: Path) -> tuple[Path, ...]:
    """Return validated recordings ordered by a race-checked captured mtime."""

    try:
        candidates = tuple(recordings_dir.iterdir())
    except OSError:
        return ()
    ranked: list[tuple[float, Path]] = []
    for candidate in candidates:
        try:
            before = os.lstat(candidate)
            trusted = trusted_recording_path(candidate, recordings_dir)
            if trusted is None:
                continue
            after = os.lstat(trusted)
        except OSError:
            continue
        inode_is_meaningful = before.st_ino != 0 and after.st_ino != 0
        same_file = before.st_dev == after.st_dev and before.st_ino == after.st_ino
        if (
            (inode_is_meaningful and not same_file)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            continue
        ranked.append((after.st_mtime, trusted))
    return tuple(path for _, path in sorted(ranked, key=lambda item: item[0], reverse=True))


def upload_trusted_recording(
    candidate: object,
    *,
    recordings_dir: Path,
    remote_path: str,
    upload_fn: Callable[..., Any],
    progress_cb: Any = None,
    delete_after_upload: bool = False,
    after_upload_success: Callable[[Any], None] | None = None,
) -> Any:
    """Revalidate a historical recording immediately before invoking upload."""

    trusted_path = trusted_recording_path(candidate, recordings_dir)
    if trusted_path is None:
        raise UnsafeRecordingPathError("Selected recording is unavailable or unsafe.")
    try:
        return upload_private_snapshot(
            trusted_path,
            remote_path,
            upload_fn,
            progress_cb=progress_cb,
            delete_after_upload=delete_after_upload,
            after_upload_success=after_upload_success,
        )
    except UnsafeUploadSourceError as exc:
        raise UnsafeRecordingPathError(
            "Selected recording is unavailable or unsafe."
        ) from exc


def resolve_completed_recording(
    record_id: str,
    completion_marker: object,
    selected_path: object,
    started_at_iso: object,
    ended_at_iso: object,
    *,
    recordings_dir: Path,
    persisted_recording: Mapping[str, Any] | None,
    suppress_persisted_resume: bool = False,
) -> CompletedRecording | None:
    """Return only a current completed recording or a safe persisted resume file."""

    path = _safe_recording_path(record_id, selected_path, recordings_dir)
    times = _parse_recording_times(started_at_iso, ended_at_iso)
    if completion_marker == record_id and path is not None and times is not None:
        return CompletedRecording(path, *times, path.suffix.lstrip(".").lower())

    if (
        completion_marker is not None
        or suppress_persisted_resume
        or not isinstance(persisted_recording, Mapping)
    ):
        return None
    filename = persisted_recording.get("video_filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        return None
    persisted_path = _safe_recording_path(record_id, recordings_dir / filename, recordings_dir)
    times = _parse_recording_times(
        persisted_recording.get("started_at_iso"), persisted_recording.get("ended_at_iso")
    )
    if persisted_path is None or times is None:
        return None
    return CompletedRecording(
        persisted_path, *times, persisted_path.suffix.lstrip(".").lower()
    )


def uploaded_cleanup_recovery(
    record: Mapping[str, Any], *, json_path: Path, recordings_dir: Path
) -> UploadedCleanupRecovery | None:
    """Identify an uploaded bundle whose local deletion already removed its video."""

    upload = record.get("upload")
    recording = record.get("recording")
    record_id = record.get("record_id")
    if (
        not isinstance(upload, Mapping)
        or upload.get("json") != "uploaded"
        or upload.get("video") != "uploaded"
        or not isinstance(recording, Mapping)
        or not isinstance(record_id, str)
    ):
        return None
    filename = recording.get("video_filename")
    allowed_names = {f"{record_id}.flv", f"{record_id}.mp4"}
    if not isinstance(filename, str) or filename not in allowed_names:
        return None
    cleanup_intent = record.get("local_cleanup")
    requested = (
        cleanup_intent.get("requested")
        if isinstance(cleanup_intent, Mapping)
        else None
    )
    if requested is False:
        return None
    video_path = recordings_dir / filename
    try:
        root = recordings_dir.resolve()
        if json_path.parent.resolve() != root:
            return None
        json_stat = os.lstat(json_path)
    except (OSError, TypeError):
        return None
    if requested is not True:
        try:
            os.lstat(video_path)
        except FileNotFoundError:
            pass
        except OSError:
            return None
        else:
            return None
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        not stat.S_ISREG(json_stat.st_mode)
        or stat.S_ISLNK(json_stat.st_mode)
        or json_stat.st_nlink != 1
        or getattr(json_stat, "st_file_attributes", 0) & reparse_flag
    ):
        return None
    cleanup_paths = tuple(
        recordings_dir / candidate
        for candidate in sorted(allowed_names - {filename})
    )
    return UploadedCleanupRecovery(json_path, video_path, cleanup_paths)


def set_local_cleanup_intent(
    record: dict[str, Any], *, requested: bool
) -> dict[str, Any]:
    if type(requested) is not bool:
        raise ValueError("cleanup intent must be a boolean")
    intent = {
        "requested": requested,
        "status": "pending" if requested else "retained",
    }
    record["local_cleanup"] = intent
    return dict(intent)


def resolve_trusted_intervention_day(config: object, subject_id: str) -> int:
    """Resolve a signed participant's day from a server-controlled mapping."""

    safe_subject_id = validate_subject_id(subject_id)
    parsed = config
    if isinstance(config, str):
        try:
            parsed = json.loads(config)
        except json.JSONDecodeError as exc:
            raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。") from exc
    if not isinstance(parsed, Mapping) or safe_subject_id not in parsed:
        raise ValueError("可信干预日配置缺少当前受试者；干预日必须为 1 到 28。")

    value = parsed[safe_subject_id]
    if isinstance(value, bool):
        raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。")
    try:
        day = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。")
    if not 1 <= day <= 28:
        raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。")
    return day


def questionnaire_answers(record: Mapping[str, Any], visit: str) -> dict[str, Any]:
    if visit == "daily":
        return {
            **record.get("daily_core", {}),
            **record.get("conditional_details", {}),
            **record.get("weekly_extension", {}),
        }
    return dict(record.get("formal_visits", {}).get(visit, {}).get("raw_answers", {}))


def _answered_values(
    answers: Mapping[str, Any], statuses: Mapping[str, str]
) -> dict[str, Any]:
    return {
        field_id: answers[field_id]
        for field_id, status in statuses.items()
        if status == "answered" and field_id in answers
    }


def _store_completion(
    record: dict[str, Any], visit: str, filtered: Mapping[str, Any], current_step: int
) -> None:
    completion = record.setdefault("completion", {})
    completion.setdefault("status", "draft")
    completion.setdefault("answered_field_ids", {})[visit] = sorted(filtered)
    completion.setdefault("current_step", {})[visit] = int(current_step)


def questionnaire_visit_complete(record: Mapping[str, Any], visit: str) -> bool:
    completion = record.get("completion", {})
    if not isinstance(completion, Mapping):
        return False
    visits = completion.get("questionnaire_visits", {})
    if not isinstance(visits, Mapping):
        return False
    status = visits.get(visit)
    return (
        isinstance(status, Mapping)
        and status.get("status") == "complete"
        and status.get("revision") == record.get("revision")
    )


def mark_questionnaire_visit_complete(record: dict[str, Any], visit: str) -> None:
    completion = record.setdefault("completion", {})
    completion["status"] = "complete"
    completion.setdefault("questionnaire_visits", {})[visit] = {
        "status": "complete",
        "revision": record["revision"],
    }


def upload_ready_for_visit(record: Mapping[str, Any], visit: str) -> bool:
    """Return whether this record/revision has a completed questionnaire visit."""

    return questionnaire_visit_complete(record, visit)


def persisted_support_needed(record: Mapping[str, Any], visit: str) -> bool:
    completion = record.get("completion", {})
    answered_by_visit = (
        completion.get("answered_field_ids", {})
        if isinstance(completion, Mapping)
        else {}
    )
    answered = answered_by_visit.get(visit, []) if isinstance(answered_by_visit, Mapping) else []
    return support_needed(
        visit,
        questionnaire_answers(record, visit),
        set(answered) if isinstance(answered, list) else set(),
        int(record["intervention_day"]),
    )


def archived_record_is_completed(
    error: RecordArchivedError,
    expected_intervention_day: object,
    expected_visit: object,
) -> bool:
    return (
        type(expected_intervention_day) is int
        and isinstance(expected_visit, str)
        and expected_visit in {"daily", *VISIT_INSTRUMENT_IDS}
        and error.intervention_day == expected_intervention_day
        and error.completion_status == "complete"
        and error.lifecycle in {"complete", "uploaded"}
        and expected_visit in error.completed_visits
    )


def archived_record_success_message(
    error: RecordArchivedError,
    expected_intervention_day: object,
    expected_visit: object,
) -> str | None:
    if not archived_record_is_completed(
        error, expected_intervention_day, expected_visit
    ):
        return None
    return f"本次记录已完成（记录编号：{error.record_id}）。"


def persist_daily_questionnaire(
    record: dict[str, Any],
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
    *,
    current_step: int,
    daily_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if daily_context is not None:
        record["daily_context"] = {
            field_id: daily_context[field_id]
            for field_id in DAILY_CONTEXT_DEFAULTS
            if field_id in daily_context
        }
    day = int(record["intervention_day"])
    statuses = build_field_status(answers, set(answered_field_ids), day)
    filtered = _answered_values(answers, statuses)

    core_ids = {question.id for question in DAILY_CORE}
    conditional_ids = {question.id for question in DAILY_CONDITIONAL}
    weekly_ids = {
        question.id
        for instrument in WEEKLY_INSTRUMENTS
        for question in instrument.questions
    }
    record["daily_core"] = {
        field_id: value for field_id, value in filtered.items() if field_id in core_ids
    }
    record["conditional_details"] = {
        field_id: value
        for field_id, value in filtered.items()
        if field_id in conditional_ids
    }
    record["weekly_extension"] = {
        field_id: value
        for field_id, value in filtered.items()
        if field_id in weekly_ids
    }
    record.setdefault("field_status", {})["daily"] = statuses
    record.setdefault("derived_metrics", {})["daily"] = daily_derived_metrics(filtered)

    if weekly_due(day):
        sicq_values = tuple(filtered.get(f"sicq_{index}") for index in range(1, 8))
        sicq = score_sicq(sicq_values)
        record["derived_metrics"]["sicq_weekly"] = {
            "total": sicq.total,
            "complete": sicq.complete,
            "scored_items": list(sicq.scored_items),
        }
    else:
        record["derived_metrics"].pop("sicq_weekly", None)
    record["derived_metrics"].pop("weekly_sicq", None)

    safety_signals = record.setdefault("safety_signals", {})
    daily_safety_keys = {
        "suicide_thought_present_24h",
        "suicide_thought_frequency_24h",
        "medical_care_required_24h",
        "nssi_medical_care_24h",
    }
    safety_signals.pop("daily", None)
    for field_id in daily_safety_keys:
        safety_signals.pop(field_id, None)
    for field_id in (
        "suicide_thought_present_24h",
        "suicide_thought_frequency_24h",
    ):
        if field_id in filtered:
            safety_signals[field_id] = filtered[field_id]
    if "nssi_medical_care_24h" in filtered:
        safety_signals["medical_care_required_24h"] = filtered[
            "nssi_medical_care_24h"
        ]

    _store_completion(record, "daily", filtered, current_step)
    return filtered


def _formal_scored_answers(
    instrument_id: str, raw_answers: Mapping[str, Any]
) -> dict[str, Any]:
    scored = dict(raw_answers)
    if instrument_id == "sicq" and "sicq_7" in scored:
        scored["sicq_7"] = 4 - scored["sicq_7"]
    return scored


def persist_formal_questionnaire(
    record: dict[str, Any],
    visit: str,
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
    *,
    current_step: int,
) -> dict[str, Any]:
    statuses = build_formal_field_status(visit, answers, set(answered_field_ids))
    filtered = _answered_values(answers, statuses)
    version = record["instrument_versions"]["formal_nssi_crf"]
    instruments: dict[str, dict[str, Any]] = {}

    for instrument_id in VISIT_INSTRUMENT_IDS[visit]:
        spec = FORMAL_INSTRUMENTS[instrument_id]
        question_ids = {question.id for question in spec.questions}
        instrument_answers = {
            field_id: value
            for field_id, value in filtered.items()
            if field_id in question_ids
        }
        required_active_ids = {
            question.id
            for question in spec.questions
            if question.required and statuses.get(question.id) != "not_applicable"
        }
        complete = required_active_ids <= set(instrument_answers)
        try:
            score = score_formal_instrument(instrument_id, instrument_answers)
        except KeyError:
            score = {"complete": complete}
        instruments[instrument_id] = {
            "instrument_id": instrument_id,
            "instrument_version": version,
            "time_window": spec.time_window,
            "raw_answers": instrument_answers,
            "scored_answers": _formal_scored_answers(
                instrument_id, instrument_answers
            ),
            "completeness": {
                "answered": len(required_active_ids & set(instrument_answers)),
                "required": len(required_active_ids),
            },
            "score": score,
            "complete": complete,
        }

    record.setdefault("formal_visits", {})[visit] = {
        "raw_answers": filtered,
        "instruments": instruments,
        "complete": all(payload["complete"] for payload in instruments.values()),
    }
    record.setdefault("field_status", {})[visit] = statuses

    pss_values = [
        value
        for field_id, value in filtered.items()
        if field_id.startswith("pss_")
    ]
    safety_signals = record.setdefault("safety_signals", {})
    safety_signals.pop(visit, None)
    formal_safety_key = f"{visit}_pss_positive"
    if pss_values:
        safety_signals[formal_safety_key] = any(value is True for value in pss_values)
    else:
        safety_signals.pop(formal_safety_key, None)

    _store_completion(record, visit, filtered, current_step)
    return filtered


def support_needed(
    visit: str,
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
    intervention_day: int,
) -> bool:
    if visit == "daily":
        statuses = build_field_status(
            answers, set(answered_field_ids), intervention_day
        )
        filtered = _answered_values(answers, statuses)
        return filtered.get("suicide_thought_present_24h") is True

    statuses = build_formal_field_status(visit, answers, set(answered_field_ids))
    filtered = _answered_values(answers, statuses)
    return any(
        field_id.startswith("pss_") and value is True
        for field_id, value in filtered.items()
    )


def upload_failure_message(record_id: str, *, participant: bool) -> str:
    del participant
    return f"上传暂未完成，请稍后重试。记录编号：{record_id}"


def cleanup_pending_message(error: LocalCleanupError, *, participant: bool) -> str:
    if participant:
        return "上传已完成，本地清理仍在处理中。"
    filenames = ", ".join(path.name for path in error.remaining_paths)
    return f"上传已完成，但本地清理未完成。剩余文件：{filenames}"
