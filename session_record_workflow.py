import re
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from datetime import date, datetime, timedelta

import participant_identity
from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_INSTRUMENTS,
    QuestionSpec,
    weekly_due,
)


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
_QUESTIONNAIRE_VISIT_KEYS = frozenset({"status", "revision"})
_TIMESTAMPED_QUESTIONNAIRE_VISIT_KEYS = frozenset({
    "status",
    "revision",
    "completed_at_iso",
})
_PROTECTED_SESSION_KEYS = {"authed", "auth_source", "subject_id", "visit"}
_RAW_ONLY_REMOVED_KEYS = frozenset({
    "classification",
    "derived_metrics",
    "hidden_classification",
    "risk",
    "risk_level",
    "safety_signals",
    "score",
    "scored_answers",
    "threshold",
    "thresholds",
})
_DAILY_CORE_IDS = frozenset(question.id for question in DAILY_CORE)
_DAILY_CONDITIONAL_IDS = frozenset(
    question.id for question in DAILY_CONDITIONAL
)
_WEEKLY_IDS = frozenset(
    question.id
    for instrument in WEEKLY_INSTRUMENTS
    for question in instrument.questions
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


def _validate_timestamp(now_iso: str) -> datetime:
    if not isinstance(now_iso, str) or _UTC_SECOND_ISO_RE.fullmatch(now_iso) is None:
        raise ValueError("timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("timestamp is invalid") from error
    if parsed.utcoffset() != timedelta(0) or parsed.microsecond != 0:
        raise ValueError("timestamp is invalid")
    return parsed


def _has_only_allowed_visits(values: Mapping[object, object]) -> bool:
    return all(
        isinstance(visit, str) and visit in _ALLOWED_VISITS for visit in values
    )


def _completion_metadata_is_valid(
    completion: Mapping[str, object],
    revision: int,
) -> bool:
    answered_field_ids = completion["answered_field_ids"]
    current_step = completion["current_step"]
    questionnaire_visits = completion["questionnaire_visits"]
    if not all(
        _has_only_allowed_visits(values)
        for values in (answered_field_ids, current_step, questionnaire_visits)
    ):
        return False

    if any(
        isinstance(field_ids, (str, bytes, bytearray))
        or not isinstance(field_ids, Sequence)
        or any(not isinstance(field_id, str) for field_id in field_ids)
        for field_ids in answered_field_ids.values()
    ):
        return False
    if any(
        type(step) is not int or step < 0 for step in current_step.values()
    ):
        return False

    for metadata in questionnaire_visits.values():
        if not isinstance(metadata, Mapping):
            return False
        metadata_keys = set(metadata)
        if metadata_keys not in (
            _QUESTIONNAIRE_VISIT_KEYS,
            _TIMESTAMPED_QUESTIONNAIRE_VISIT_KEYS,
        ):
            return False
        metadata_revision = metadata["revision"]
        if (
            metadata["status"] != "complete"
            or type(metadata_revision) is not int
            or metadata_revision <= 0
            or metadata_revision != revision
        ):
            return False
        if "completed_at_iso" in metadata:
            _validate_timestamp(metadata["completed_at_iso"])
    return True


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
    if not _completion_metadata_is_valid(completion, record["revision"]):
        return False

    created_at = _validate_timestamp(record["created_at_iso"])
    updated_at = _validate_timestamp(record["updated_at_iso"])
    return updated_at >= created_at


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


def _validate_visit(visit: object, *, allow_daily: bool = True) -> str:
    allowed = _ALLOWED_VISITS if allow_daily else tuple(VISIT_INSTRUMENT_IDS)
    if not isinstance(visit, str) or visit not in allowed:
        raise ValueError("visit is invalid")
    return visit


def _validate_questionnaire_record(record: object) -> dict[str, object]:
    if not isinstance(record, dict):
        raise ValueError("record is invalid")
    revision = record.get("revision")
    intervention_day = record.get("intervention_day")
    instrument_versions = record.get("instrument_versions")
    if type(revision) is not int or revision < 1:
        raise ValueError("record is invalid")
    if type(intervention_day) is not int or not 1 <= intervention_day <= 28:
        raise ValueError("record is invalid")
    if not isinstance(instrument_versions, Mapping):
        raise ValueError("record is invalid")
    for key in (
        "daily_core",
        "conditional_details",
        "weekly_extension",
        "formal_visits",
        "field_status",
    ):
        if not isinstance(record.get(key), Mapping):
            raise ValueError("record is invalid")
    completion = record.get("completion")
    if (
        not isinstance(completion, Mapping)
        or set(completion) != _COMPLETION_KEYS
        or completion.get("status") not in _COMPLETION_STATUSES
    ):
        raise ValueError("record is invalid")
    try:
        if not _completion_metadata_is_valid(completion, revision):
            raise ValueError("record is invalid")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("record is invalid") from error
    return record


def _completion_copy(record: Mapping[str, object]) -> dict[str, object]:
    completion = record.get("completion")
    if not isinstance(completion, Mapping):
        raise ValueError("record is invalid")
    answered_field_ids = completion.get("answered_field_ids")
    current_step = completion.get("current_step")
    questionnaire_visits = completion.get("questionnaire_visits")
    if not all(
        isinstance(value, Mapping)
        for value in (answered_field_ids, current_step, questionnaire_visits)
    ):
        raise ValueError("record is invalid")
    return {
        **completion,
        "answered_field_ids": dict(answered_field_ids),
        "current_step": dict(current_step),
        "questionnaire_visits": dict(questionnaire_visits),
    }


def _validate_persistence_inputs(
    answers: object,
    answered_field_ids: object,
    current_step: object,
) -> tuple[Mapping[str, object], set[str], int]:
    if not isinstance(answers, Mapping) or any(
        not isinstance(field_id, str) for field_id in answers
    ):
        raise ValueError("answers are invalid")
    if not isinstance(answered_field_ids, set) or any(
        not isinstance(field_id, str) for field_id in answered_field_ids
    ):
        raise ValueError("answered field ids are invalid")
    if type(current_step) is not int or current_step < 0:
        raise ValueError("current step is invalid")
    return answers, set(answered_field_ids), current_step


def _copy_raw_value(value: object) -> object:
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, list):
        return [_copy_raw_value(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("answers are invalid")
        return {
            key: _copy_raw_value(item)
            for key, item in value.items()
        }
    raise ValueError("answers are invalid")


def _question_value_is_valid(question: QuestionSpec, value: object) -> bool:
    if question.kind == "boolean":
        return type(value) is bool
    if question.kind in {"slider", "integer"}:
        if type(value) not in {int, float}:
            return False
        if question.kind == "integer" and type(value) is not int:
            return False
        return (
            (question.min_value is None or value >= question.min_value)
            and (question.max_value is None or value <= question.max_value)
        )
    if question.kind == "text":
        return isinstance(value, str)
    if question.kind == "multiselect":
        return isinstance(value, list) and all(
            isinstance(item, str) for item in value
        )
    return False


def _daily_questions(intervention_day: int) -> tuple[QuestionSpec, ...]:
    weekly = (
        tuple(
            question
            for instrument in WEEKLY_INSTRUMENTS
            for question in instrument.questions
        )
        if weekly_due(intervention_day)
        else ()
    )
    return (*DAILY_CORE, *DAILY_CONDITIONAL, *weekly)


def _daily_field_status(
    answers: Mapping[str, object],
    answered_field_ids: set[str],
    intervention_day: int,
) -> dict[str, str]:
    active_ids = set(_DAILY_CORE_IDS)
    active_ids.update(
        question.id
        for question in DAILY_CONDITIONAL
        if question.show_if is not None
        and answers.get(question.show_if[0]) == question.show_if[1]
    )
    if weekly_due(intervention_day):
        active_ids.update(_WEEKLY_IDS)
    return {
        question.id: (
            "not_applicable"
            if question.id not in active_ids
            else "answered"
            if question.id in answered_field_ids
            else "missing"
        )
        for question in _daily_questions(intervention_day)
    }


def _formal_questions(visit: str) -> tuple[QuestionSpec, ...]:
    return tuple(
        question
        for instrument_id in VISIT_INSTRUMENT_IDS[visit]
        for question in FORMAL_INSTRUMENTS[instrument_id].questions
    )


def _formal_field_status(
    visit: str,
    answers: Mapping[str, object],
    answered_field_ids: set[str],
) -> dict[str, str]:
    questions = _formal_questions(visit)
    active_ids = {
        question.id
        for question in questions
        if question.show_if is None
        or answers.get(question.show_if[0]) == question.show_if[1]
    }
    return {
        question.id: (
            "not_applicable"
            if question.id not in active_ids
            else "answered"
            if question.id in answered_field_ids
            else "missing"
        )
        for question in questions
    }


def _answered_values(
    questions: Sequence[QuestionSpec],
    answers: Mapping[str, object],
    statuses: Mapping[str, str],
) -> dict[str, object]:
    values: dict[str, object] = {}
    for question in questions:
        if statuses[question.id] != "answered":
            continue
        if question.id not in answers or not _question_value_is_valid(
            question, answers[question.id]
        ):
            raise ValueError("answers are invalid")
        values[question.id] = _copy_raw_value(answers[question.id])
    return values


def _store_questionnaire_progress(
    completion: dict[str, object],
    visit: str,
    filtered: Mapping[str, object],
    current_step: int,
) -> None:
    answered_by_visit = completion["answered_field_ids"]
    current_step_by_visit = completion["current_step"]
    assert isinstance(answered_by_visit, dict)
    assert isinstance(current_step_by_visit, dict)
    answered_by_visit[visit] = sorted(filtered)
    current_step_by_visit[visit] = current_step


def _remove_non_raw_sections(record: dict[str, object]) -> None:
    for key in _RAW_ONLY_REMOVED_KEYS:
        record.pop(key, None)


def _raw_payload_copy(value: object) -> object:
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, list):
        return [_raw_payload_copy(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("record is invalid")
        return {
            key: _raw_payload_copy(item)
            for key, item in value.items()
            if key not in _RAW_ONLY_REMOVED_KEYS
        }
    raise ValueError("record is invalid")


def questionnaire_answers(
    record: Mapping[str, object], visit: str
) -> dict[str, object]:
    try:
        safe_visit = _validate_visit(visit)
        if safe_visit == "daily":
            day = record.get("intervention_day")
            if type(day) is not int or not 1 <= day <= 28:
                return {}
            section_specs = (
                ("daily_core", _DAILY_CORE_IDS),
                ("conditional_details", _DAILY_CONDITIONAL_IDS),
                ("weekly_extension", _WEEKLY_IDS if weekly_due(day) else ()),
            )
            restored: dict[str, object] = {}
            for section_name, allowed_ids in section_specs:
                section = record.get(section_name)
                if not isinstance(section, Mapping):
                    return {}
                restored.update(
                    {
                        field_id: _copy_raw_value(value)
                        for field_id, value in section.items()
                        if isinstance(field_id, str) and field_id in allowed_ids
                    }
                )
            statuses = _daily_field_status(restored, set(restored), day)
            return {
                field_id: value
                for field_id, value in restored.items()
                if statuses.get(field_id) == "answered"
            }

        formal_visits = record.get("formal_visits")
        if not isinstance(formal_visits, Mapping):
            return {}
        visit_payload = formal_visits.get(safe_visit)
        if not isinstance(visit_payload, Mapping):
            return {}
        raw_answers = visit_payload.get("raw_answers")
        if not isinstance(raw_answers, Mapping):
            return {}
        allowed_ids = {question.id for question in _formal_questions(safe_visit)}
        restored = {
            field_id: _copy_raw_value(value)
            for field_id, value in raw_answers.items()
            if isinstance(field_id, str) and field_id in allowed_ids
        }
        statuses = _formal_field_status(safe_visit, restored, set(restored))
        return {
            field_id: value
            for field_id, value in restored.items()
            if statuses.get(field_id) == "answered"
        }
    except Exception:
        return {}


def questionnaire_visit_complete(
    record: Mapping[str, object], visit: str
) -> bool:
    try:
        safe_visit = _validate_visit(visit)
        revision = record["revision"]
        if type(revision) is not int or revision < 1:
            return False
        completion = record["completion"]
        if not isinstance(completion, Mapping):
            return False
        questionnaire_visits = completion["questionnaire_visits"]
        if not isinstance(questionnaire_visits, Mapping):
            return False
        metadata = questionnaire_visits.get(safe_visit)
        if not isinstance(metadata, Mapping):
            return False
        keys = set(metadata)
        if keys not in (
            _QUESTIONNAIRE_VISIT_KEYS,
            _TIMESTAMPED_QUESTIONNAIRE_VISIT_KEYS,
        ):
            return False
        if (
            metadata.get("status") != "complete"
            or metadata.get("revision") != revision
        ):
            return False
        if "completed_at_iso" in metadata:
            completed_at = _validate_timestamp(metadata["completed_at_iso"])
            created_at = _validate_timestamp(record["created_at_iso"])
            updated_at = _validate_timestamp(record["updated_at_iso"])
            if not created_at <= completed_at <= updated_at:
                return False
        return True
    except Exception:
        return False


def mark_questionnaire_visit_complete(
    record: dict[str, object],
    visit: str,
    *,
    completed_at_iso: str,
) -> None:
    safe_record = _validate_questionnaire_record(record)
    safe_visit = _validate_visit(visit)
    completed_at = _validate_timestamp(completed_at_iso)
    created_at = _validate_timestamp(safe_record.get("created_at_iso"))
    updated_at = _validate_timestamp(safe_record.get("updated_at_iso"))
    if completed_at < created_at or completed_at < updated_at:
        raise ValueError("timestamp chronology is invalid")

    completion = _completion_copy(safe_record)
    questionnaire_visits = completion["questionnaire_visits"]
    assert isinstance(questionnaire_visits, dict)
    questionnaire_visits[safe_visit] = {
        "status": "complete",
        "revision": safe_record["revision"],
        "completed_at_iso": completed_at_iso,
    }
    completion["status"] = "complete"

    safe_record["completion"] = completion
    safe_record["updated_at_iso"] = completed_at_iso
    _remove_non_raw_sections(safe_record)


def persist_daily_questionnaire(
    record: dict[str, object],
    answers: Mapping[str, object],
    answered_field_ids: set[str],
    *,
    current_step: int,
    daily_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    safe_record = _validate_questionnaire_record(record)
    safe_answers, safe_answered_ids, safe_step = _validate_persistence_inputs(
        answers, answered_field_ids, current_step
    )
    if daily_context is not None and (
        not isinstance(daily_context, Mapping)
        or any(not isinstance(key, str) for key in daily_context)
    ):
        raise ValueError("daily context is invalid")

    day = safe_record["intervention_day"]
    assert isinstance(day, int)
    questions = _daily_questions(day)
    statuses = _daily_field_status(safe_answers, safe_answered_ids, day)
    filtered = _answered_values(questions, safe_answers, statuses)
    completion = _completion_copy(safe_record)
    _store_questionnaire_progress(completion, "daily", filtered, safe_step)
    field_status = dict(safe_record["field_status"])
    field_status["daily"] = statuses
    formal_visits = _raw_payload_copy(safe_record["formal_visits"])
    assert isinstance(formal_visits, dict)
    context = (
        {
            key: _copy_raw_value(value)
            for key, value in daily_context.items()
        }
        if daily_context is not None
        else None
    )

    if context is not None:
        safe_record["daily_context"] = context
    safe_record["daily_core"] = {
        field_id: value
        for field_id, value in filtered.items()
        if field_id in _DAILY_CORE_IDS
    }
    safe_record["conditional_details"] = {
        field_id: value
        for field_id, value in filtered.items()
        if field_id in _DAILY_CONDITIONAL_IDS
    }
    safe_record["weekly_extension"] = {
        field_id: value
        for field_id, value in filtered.items()
        if field_id in _WEEKLY_IDS
    }
    safe_record["formal_visits"] = formal_visits
    safe_record["field_status"] = field_status
    safe_record["completion"] = completion
    _remove_non_raw_sections(safe_record)
    return dict(filtered)


def persist_formal_questionnaire(
    record: dict[str, object],
    visit: str,
    answers: Mapping[str, object],
    answered_field_ids: set[str],
    *,
    current_step: int,
) -> dict[str, object]:
    safe_record = _validate_questionnaire_record(record)
    safe_visit = _validate_visit(visit, allow_daily=False)
    safe_answers, safe_answered_ids, safe_step = _validate_persistence_inputs(
        answers, answered_field_ids, current_step
    )
    version = safe_record["instrument_versions"].get("formal_nssi_crf")
    if not isinstance(version, str) or not version:
        raise ValueError("record is invalid")

    questions = _formal_questions(safe_visit)
    statuses = _formal_field_status(
        safe_visit, safe_answers, safe_answered_ids
    )
    filtered = _answered_values(questions, safe_answers, statuses)
    instruments: dict[str, dict[str, object]] = {}
    for instrument_id in VISIT_INSTRUMENT_IDS[safe_visit]:
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
            if question.required and statuses[question.id] != "not_applicable"
        }
        answered_required = required_active_ids & set(instrument_answers)
        instruments[instrument_id] = {
            "instrument_id": instrument_id,
            "instrument_version": version,
            "label": spec.label,
            "time_window": spec.time_window,
            "raw_answers": instrument_answers,
            "completeness": {
                "answered": len(answered_required),
                "required": len(required_active_ids),
            },
            "complete": answered_required == required_active_ids,
        }

    formal_visits = _raw_payload_copy(safe_record["formal_visits"])
    assert isinstance(formal_visits, dict)
    formal_visits[safe_visit] = {
        "raw_answers": dict(filtered),
        "instruments": instruments,
        "complete": all(
            payload["complete"] is True for payload in instruments.values()
        ),
    }
    field_status = dict(safe_record["field_status"])
    field_status[safe_visit] = statuses
    completion = _completion_copy(safe_record)
    _store_questionnaire_progress(
        completion, safe_visit, filtered, safe_step
    )

    safe_record["formal_visits"] = formal_visits
    safe_record["field_status"] = field_status
    safe_record["completion"] = completion
    _remove_non_raw_sections(safe_record)
    return dict(filtered)


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
