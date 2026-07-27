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
        "instrument_versions": {
            "daily_nssi_ema": "1.0",
            "weekly_nssi": "1.0",
            "formal_nssi_crf": "1.0",
        },
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
            type(record.get("schema_version")) is int
            and record.get("schema_version") == 5
            and type(record.get("subject_id")) is str
            and record.get("subject_id") == safe_subject_id
            and type(record.get("record_date")) is str
            and record.get("record_date") == record_date.isoformat()
            and type(record.get("intervention_day")) is int
            and record.get("intervention_day") == intervention_day
            and type(record.get("visit")) is str
            and record.get("visit") == visit
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
        if isinstance(key, str) and (
            key in owned_exact_keys
            or any(key.startswith(prefix) for prefix in owned_prefixes)
        ):
            del state[key]
