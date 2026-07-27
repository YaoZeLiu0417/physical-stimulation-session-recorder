import re
from collections.abc import Iterable, Mapping, MutableMapping
from datetime import date, datetime, timedelta

import participant_identity
from questionnaire_specs import VISIT_INSTRUMENT_IDS


_ALLOWED_VISITS = ("daily", *VISIT_INSTRUMENT_IDS)
_TOKEN_RE = re.compile(r"[0-9a-f]{8}")
_UTC_SECOND_ISO_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|\+00:00)"
)
_INSTRUMENT_VERSIONS = {
    "daily_nssi_ema": "1.0",
    "weekly_nssi": "1.0",
    "formal_nssi_crf": "1.0",
}
_SESSION_RECORD_KEYS = {
    "schema_version",
    "record_id",
    "subject_id",
    "record_date",
    "intervention_day",
    "visit",
    "revision",
    "instrument_versions",
    "daily_context",
    "daily_core",
    "conditional_details",
    "weekly_extension",
    "formal_visits",
    "field_status",
    "recording",
    "completion",
    "created_at_iso",
    "updated_at_iso",
}
_MUTABLE_SECTION_KEYS = {
    "daily_context",
    "daily_core",
    "conditional_details",
    "weekly_extension",
    "formal_visits",
    "field_status",
    "recording",
}
_COMPLETION_KEYS = {
    "status",
    "answered_field_ids",
    "current_step",
    "questionnaire_visits",
}
_COMPLETION_MAPPING_KEYS = {
    "answered_field_ids",
    "current_step",
    "questionnaire_visits",
}
_COMPLETION_STATUSES = {"draft", "in_progress", "complete"}
_PROTECTED_SESSION_KEYS = {"authed", "auth_source", "subject_id", "visit"}


def _validated_context(
    subject_id: str,
    record_date: date,
    intervention_day: int,
    visit: str,
) -> tuple[str, date, int, str]:
    safe_subject_id = participant_identity.validate_subject_id(subject_id)
    if type(record_date) is not date:
        raise ValueError("record date is invalid")
    if type(intervention_day) is not int or not 1 <= intervention_day <= 28:
        raise ValueError("intervention day is invalid")
    if not isinstance(visit, str) or visit not in _ALLOWED_VISITS:
        raise ValueError("visit is invalid")
    return safe_subject_id, record_date, intervention_day, visit


def _validate_timestamp(now_iso: str) -> None:
    if not isinstance(now_iso, str) or _UTC_SECOND_ISO_RE.fullmatch(now_iso) is None:
        raise ValueError("timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("timestamp is invalid") from error
    if parsed.utcoffset() != timedelta(0) or parsed.microsecond != 0:
        raise ValueError("timestamp is invalid")


def _record_structure_is_valid(
    record: Mapping[str, object],
    safe_subject_id: str,
    record_date: date,
) -> bool:
    if set(record) != _SESSION_RECORD_KEYS:
        return False

    expected_record_id_prefix = f"{safe_subject_id}_{record_date:%Y%m%d}_"
    record_id = record["record_id"]
    if type(record_id) is not str or not record_id.startswith(
        expected_record_id_prefix
    ):
        return False
    token = record_id[len(expected_record_id_prefix) :]
    if _TOKEN_RE.fullmatch(token) is None:
        return False

    if type(record["revision"]) is not int or record["revision"] != 1:
        return False
    instrument_versions = record["instrument_versions"]
    if (
        not isinstance(instrument_versions, Mapping)
        or dict(instrument_versions) != _INSTRUMENT_VERSIONS
    ):
        return False
    if any(
        not isinstance(record[key], Mapping) for key in _MUTABLE_SECTION_KEYS
    ):
        return False

    completion = record["completion"]
    if not isinstance(completion, Mapping) or set(completion) != _COMPLETION_KEYS:
        return False
    if completion["status"] not in _COMPLETION_STATUSES:
        return False
    if any(
        not isinstance(completion[key], Mapping)
        for key in _COMPLETION_MAPPING_KEYS
    ):
        return False

    _validate_timestamp(record["created_at_iso"])
    _validate_timestamp(record["updated_at_iso"])
    return True


def create_session_record(
    subject_id: str,
    record_date: date,
    intervention_day: int,
    visit: str,
    *,
    token: str,
    now_iso: str,
) -> dict[str, object]:
    safe_subject_id, record_date, intervention_day, visit = _validated_context(
        subject_id,
        record_date,
        intervention_day,
        visit,
    )
    if not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None:
        raise ValueError("token is invalid")
    _validate_timestamp(now_iso)

    return {
        "schema_version": 5,
        "record_id": f"{safe_subject_id}_{record_date:%Y%m%d}_{token}",
        "subject_id": safe_subject_id,
        "record_date": record_date.isoformat(),
        "intervention_day": intervention_day,
        "visit": visit,
        "revision": 1,
        "instrument_versions": dict(_INSTRUMENT_VERSIONS),
        "daily_context": {},
        "daily_core": {},
        "conditional_details": {},
        "weekly_extension": {},
        "formal_visits": {},
        "field_status": {},
        "recording": {},
        "completion": {
            "status": "draft",
            "answered_field_ids": {},
            "current_step": {},
            "questionnaire_visits": {},
        },
        "created_at_iso": now_iso,
        "updated_at_iso": now_iso,
    }


def session_record_matches(
    record: object,
    *,
    subject_id: str,
    record_date: date,
    intervention_day: int,
    visit: str,
) -> bool:
    try:
        safe_subject_id, record_date, intervention_day, visit = _validated_context(
            subject_id,
            record_date,
            intervention_day,
            visit,
        )
        if not isinstance(record, Mapping):
            return False
        return (
            type(record["schema_version"]) is int
            and record["schema_version"] == 5
            and type(record["subject_id"]) is str
            and record["subject_id"] == safe_subject_id
            and type(record["record_date"]) is str
            and record["record_date"] == record_date.isoformat()
            and type(record["intervention_day"]) is int
            and record["intervention_day"] == intervention_day
            and type(record["visit"]) is str
            and record["visit"] == visit
            and _record_structure_is_valid(
                record,
                safe_subject_id,
                record_date,
            )
        )
    except Exception:
        return False


def clear_owned_session_state(
    state: MutableMapping[str, object],
    *,
    exact_keys: Iterable[str],
    prefixes: Iterable[str],
) -> None:
    owned_exact_keys = {
        key for key in exact_keys if isinstance(key, str)
    }
    owned_prefixes = tuple(
        prefix for prefix in prefixes if isinstance(prefix, str) and prefix
    )

    for key in tuple(state):
        if key in _PROTECTED_SESSION_KEYS:
            continue
        if isinstance(key, str) and (
            key in owned_exact_keys
            or any(key.startswith(prefix) for prefix in owned_prefixes)
        ):
            state.pop(key, None)
