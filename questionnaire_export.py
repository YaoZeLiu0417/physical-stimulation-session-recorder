from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import math
import re
from typing import cast

from local_export_bundle import LocalExportBundle, build_local_export_bundle
from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_INSTRUMENTS,
    QuestionSpec,
    weekly_due,
)
from session_record_workflow import (
    DAILY_CONTEXT_DEFAULTS,
    build_daily_field_status,
    build_formal_field_status,
    questionnaire_answers,
    questionnaire_visit_complete,
    session_record_matches,
)


RawExportValue = str | int | float | bool | tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ResponseSnapshot:
    visit: str
    instrument_id: str
    instrument_version: str
    field_id: str
    question_text: str
    question_kind: str
    answered: bool
    applicability: str
    raw_value: RawExportValue
    display_value: str


@dataclass(frozen=True, slots=True)
class VisitSnapshot:
    visit: str
    visit_status: str
    completed_at_iso: str
    instrument_id: str
    instrument_version: str
    instrument_status: str
    answered_field_ids: tuple[str, ...]
    field_status: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ParticipantSnapshot:
    export_schema_version: int
    participant_id: str
    record_date: str
    intervention_day: int
    visit: str
    exported_at_iso: str
    daily_context: tuple[tuple[str, RawExportValue], ...]
    recording: tuple[tuple[str, RawExportValue], ...]
    answered_field_ids: tuple[str, ...]
    field_status: tuple[tuple[str, str], ...]
    responses: tuple[ResponseSnapshot, ...]
    visits: tuple[VisitSnapshot, ...]


@dataclass(frozen=True, slots=True)
class _QuestionEntry:
    instrument_id: str
    instrument_version: str
    question: QuestionSpec


_EXPORT_SCHEMA_VERSION = 1
_UTC_SECOND_ISO_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|\+00:00)"
)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_OOXML_ESCAPE_RE = re.compile(r"_x[0-9a-f]{4}_", re.IGNORECASE)
_MAX_EXCEL_TEXT_LENGTH = 32_767
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_SESSION_KEYS = (
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
)
_COMPLETION_KEYS = (
    "status",
    "answered_field_ids",
    "current_step",
    "questionnaire_visits",
)
_RECORDING_KEYS = (
    "version",
    "storage",
    "status",
    "mode",
    "duration_seconds",
    "camera_ready",
    "microphone_ready",
    "saved_confirmed",
)
_TERMINAL_RECORDING_STATES = frozenset({"saved", "skipped", "failed"})
_RECORDING_MODES = frozenset({"demo", "long"})
_FIELD_STATES = frozenset({"answered", "missing", "not_applicable"})
_NEUTRAL_ERROR_MESSAGES = frozenset(
    {"record is invalid", "timestamp is invalid", "visit is invalid"}
)
_FORMAL_VERSION_KEY = "formal_nssi_crf"
_DAILY_VERSION_KEY = "daily_nssi_ema"
_WEEKLY_VERSION_KEY = "weekly_nssi"


def _invalid_record() -> ValueError:
    return ValueError("record is invalid")


def _export_text(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _invalid_record() from None
    rendered_length = len(value) + int(value.startswith(_FORMULA_PREFIXES))
    if (
        rendered_length > _MAX_EXCEL_TEXT_LENGTH
        or any(
            ord(character) < 32 and character not in {"\t", "\n"}
            for character in value
        )
        or any(character in {"\ufffe", "\uffff"} for character in value)
        or _OOXML_ESCAPE_RE.search(value) is not None
    ):
        raise _invalid_record()
    return value


def _export_number(value: object) -> int | float:
    """Match the public export delegate's exact .16G typed round-trip."""
    if type(value) not in {int, float}:
        raise _invalid_record()
    if isinstance(value, float) and not math.isfinite(value):
        raise _invalid_record()
    try:
        serialized = f"{value:.16G}"
        try:
            round_tripped: int | float = int(serialized)
        except ValueError:
            round_tripped = float(serialized)
    except (OverflowError, ValueError):
        raise _invalid_record() from None
    if (
        type(round_tripped) is not type(value)
        or round_tripped != value
        or isinstance(round_tripped, float)
        and not math.isfinite(round_tripped)
        or isinstance(value, float)
        and value == 0
        and math.copysign(1.0, round_tripped) != math.copysign(1.0, value)
    ):
        raise _invalid_record()
    return value


def _sleep_hours(value: object) -> int | float:
    if type(value) not in {int, float} or not 0 <= value <= 24:
        raise _invalid_record()
    if isinstance(value, float) and (
        not math.isfinite(value)
        or value == 0
        and math.copysign(1.0, value) < 0
    ):
        raise _invalid_record()
    doubled = value * 2
    if doubled != int(doubled):
        raise _invalid_record()
    # Streamlit emits floats; integral half-hour values become typed Excel ints.
    canonical = (
        int(value)
        if isinstance(value, float) and value.is_integer()
        else value
    )
    return _export_number(canonical)


def _utc_second(value: object) -> datetime:
    if not isinstance(value, str) or _UTC_SECOND_ISO_RE.fullmatch(value) is None:
        raise ValueError("timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("timestamp is invalid") from None
    if parsed.utcoffset() != timedelta(0) or parsed.microsecond != 0:
        raise ValueError("timestamp is invalid")
    return parsed


def _export_datetime_iso(exported_at: object) -> str:
    if not isinstance(exported_at, datetime):
        raise TypeError("exported_at must be a datetime")
    try:
        offset = exported_at.utcoffset()
    except Exception:
        raise ValueError("exported_at must be timezone-aware UTC") from None
    if exported_at.tzinfo is None or offset != timedelta(0):
        raise ValueError("exported_at must be timezone-aware UTC")
    if exported_at.microsecond != 0:
        raise ValueError("exported_at must use second precision")
    return exported_at.astimezone(timezone.utc).isoformat()


def _record_date(value: object) -> date:
    if not isinstance(value, str) or _DATE_RE.fullmatch(value) is None:
        raise _invalid_record()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _invalid_record() from None
    if parsed.isoformat() != value:
        raise _invalid_record()
    return parsed


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise _invalid_record()
    return value


def _visit_mapping(
    value: object,
    *,
    visit: str,
) -> Mapping[str, object]:
    values = _mapping(value)
    if any(key in {"daily", *VISIT_INSTRUMENT_IDS} and key != visit for key in values):
        raise _invalid_record()
    return values


def _completion_projection(
    record: Mapping[str, object],
    *,
    visit: str,
) -> tuple[dict[str, object], tuple[str, ...], str]:
    completion = _mapping(record.get("completion"))
    answered_by_visit = _visit_mapping(
        completion.get("answered_field_ids"), visit=visit
    )
    current_step_by_visit = _visit_mapping(
        completion.get("current_step"), visit=visit
    )
    visits = _visit_mapping(completion.get("questionnaire_visits"), visit=visit)
    raw_answered = answered_by_visit.get(visit)
    if (
        completion.get("status") != "complete"
        or isinstance(raw_answered, (str, bytes, bytearray))
        or not isinstance(raw_answered, Sequence)
        or any(not isinstance(field_id, str) for field_id in raw_answered)
        or len(set(raw_answered)) != len(raw_answered)
        or list(raw_answered) != sorted(raw_answered)
    ):
        raise _invalid_record()
    current_step = current_step_by_visit.get(visit)
    metadata = visits.get(visit)
    if type(current_step) is not int or current_step < 0:
        raise _invalid_record()
    metadata = _mapping(metadata)
    completed_at_iso = metadata.get("completed_at_iso")
    try:
        _utc_second(completed_at_iso)
    except ValueError:
        raise _invalid_record() from None
    revision = record.get("revision")
    if (
        metadata.get("status") != "complete"
        or type(revision) is not int
        or revision < 1
        or metadata.get("revision") != revision
    ):
        raise _invalid_record()
    projected = {
        "status": "complete",
        "answered_field_ids": {visit: list(raw_answered)},
        "current_step": {visit: current_step},
        "questionnaire_visits": {
            visit: {
                "status": "complete",
                "revision": revision,
                "completed_at_iso": completed_at_iso,
            }
        },
    }
    return projected, tuple(raw_answered), completed_at_iso


def _record_projection(
    record: Mapping[str, object],
    *,
    visit: str,
) -> tuple[dict[str, object], tuple[str, ...], str, date]:
    record_visit = record.get("visit")
    if not isinstance(visit, str) or visit not in {"daily", *VISIT_INSTRUMENT_IDS}:
        raise ValueError("visit is invalid")
    if record_visit != visit:
        raise ValueError("visit is invalid")
    parsed_date = _record_date(record.get("record_date"))
    completion, answered_ids, completed_at_iso = _completion_projection(
        record, visit=visit
    )
    try:
        projected = {key: record[key] for key in _SESSION_KEYS}
    except (KeyError, TypeError):
        raise _invalid_record() from None
    projected["completion"] = completion
    subject_id = projected.get("subject_id")
    intervention_day = projected.get("intervention_day")
    if (
        not isinstance(subject_id, str)
        or type(intervention_day) is not int
        or not 1 <= intervention_day <= 28
    ):
        raise _invalid_record()
    if not session_record_matches(
        projected,
        subject_id=subject_id,
        record_date=parsed_date,
        intervention_day=intervention_day,
        visit=visit,
    ):
        raise _invalid_record()
    if not questionnaire_visit_complete(projected, visit):
        raise _invalid_record()
    return projected, answered_ids, completed_at_iso, parsed_date


def _question_entries(
    record: Mapping[str, object], *, visit: str
) -> tuple[_QuestionEntry, ...]:
    versions = cast(Mapping[str, object], record["instrument_versions"])
    if visit == "daily":
        day = record["intervention_day"]
        assert isinstance(day, int)
        entries = [
            _QuestionEntry(
                "daily_nssi_ema",
                str(versions[_DAILY_VERSION_KEY]),
                question,
            )
            for question in (*DAILY_CORE, *DAILY_CONDITIONAL)
        ]
        if weekly_due(day):
            entries.extend(
                _QuestionEntry(
                    instrument.id,
                    str(versions[_WEEKLY_VERSION_KEY]),
                    question,
                )
                for instrument in WEEKLY_INSTRUMENTS
                for question in instrument.questions
            )
        return tuple(entries)
    return tuple(
        _QuestionEntry(
            instrument_id,
            str(versions[_FORMAL_VERSION_KEY]),
            question,
        )
        for instrument_id in VISIT_INSTRUMENT_IDS[visit]
        for question in FORMAL_INSTRUMENTS[instrument_id].questions
    )


def _freeze_answer(question: QuestionSpec, value: object) -> RawExportValue:
    if question.kind == "boolean":
        if type(value) is not bool:
            raise _invalid_record()
        return value
    if question.kind in {"slider", "integer"}:
        if type(value) is not int:
            raise _invalid_record()
        if (
            question.min_value is not None
            and value < question.min_value
            or question.max_value is not None
            and value > question.max_value
        ):
            raise _invalid_record()
        return _export_number(value)
    if question.kind == "text":
        if not isinstance(value, str):
            raise _invalid_record()
        return _export_text(value)
    if question.kind == "multiselect":
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
            or len(set(value)) != len(value)
            or any(item not in question.options for item in value)
        ):
            raise _invalid_record()
        return tuple(_export_text(item) for item in value)
    raise _invalid_record()


def _context_value(key: str, value: object) -> RawExportValue:
    integer_ranges = {
        "mood_1to9": (1, 9),
        "stress_1to9": (1, 9),
        "pain_0to10": (0, 10),
        "nssi_urge_0to10": (0, 10),
        "coping_effect_1to5": (1, 5),
    }
    if key == "sleep_hours":
        return _sleep_hours(value)
    if key in integer_ranges:
        lower, upper = integer_ranges[key]
        if type(value) is not int or not lower <= value <= upper:
            raise _invalid_record()
        return _export_number(value)
    if key in {"tags", "coping_used"}:
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise _invalid_record()
        return tuple(_export_text(item) for item in value)
    if not isinstance(value, str):
        raise _invalid_record()
    return _export_text(value)


def _daily_context(record: Mapping[str, object]) -> tuple[tuple[str, RawExportValue], ...]:
    context = _mapping(record.get("daily_context"))
    return tuple(
        (key, _context_value(key, context[key]))
        for key in DAILY_CONTEXT_DEFAULTS
        if key in context
    )


def _recording(record: Mapping[str, object]) -> tuple[tuple[str, RawExportValue], ...]:
    source = _mapping(record.get("recording"))
    if any(key not in source for key in _RECORDING_KEYS):
        raise _invalid_record()
    version = source["version"]
    storage = source["storage"]
    status = source["status"]
    mode = source["mode"]
    duration = source["duration_seconds"]
    camera_ready = source["camera_ready"]
    microphone_ready = source["microphone_ready"]
    saved_confirmed = source["saved_confirmed"]
    if (
        type(version) is not int
        or version != 2
        or storage != "browser_local"
        or not isinstance(status, str)
        or status not in _TERMINAL_RECORDING_STATES
        or not isinstance(mode, str)
        or mode not in _RECORDING_MODES
        or type(duration) is not int
        or not 0 <= duration <= 2700
        or type(camera_ready) is not bool
        or type(microphone_ready) is not bool
        or type(saved_confirmed) is not bool
        or status == "saved"
        and not (saved_confirmed and camera_ready and microphone_ready)
        or status != "saved"
        and saved_confirmed
    ):
        raise _invalid_record()
    _export_number(version)
    _export_number(duration)
    return tuple((key, source[key]) for key in _RECORDING_KEYS)  # type: ignore[misc]


def _status_inventory(
    record: Mapping[str, object],
    *,
    visit: str,
    entries: tuple[_QuestionEntry, ...],
    answers: Mapping[str, object],
) -> tuple[tuple[str, str], ...]:
    field_status = _visit_mapping(record.get("field_status"), visit=visit)
    stored = _mapping(field_status.get(visit))
    question_ids = tuple(entry.question.id for entry in entries)
    if visit == "daily":
        day = record["intervention_day"]
        assert isinstance(day, int)
        expected = build_daily_field_status(answers, set(answers), day)
    else:
        expected = build_formal_field_status(visit, answers, set(answers))
    if any(
        field_id not in stored
        or stored[field_id] not in _FIELD_STATES
        or stored[field_id] != expected[field_id]
        for field_id in question_ids
    ):
        raise _invalid_record()
    return tuple((field_id, expected[field_id]) for field_id in question_ids)


def _validate_formal_payload(
    record: Mapping[str, object],
    *,
    visit: str,
    answers: Mapping[str, object],
    statuses: Mapping[str, str],
) -> None:
    if visit == "daily":
        return
    formal_visits = _visit_mapping(record.get("formal_visits"), visit=visit)
    visit_payload = _mapping(formal_visits.get(visit))
    instruments = _mapping(visit_payload.get("instruments"))
    if visit_payload.get("complete") is not True or tuple(
        key for key in instruments if key in FORMAL_INSTRUMENTS
    ) != VISIT_INSTRUMENT_IDS[visit]:
        raise _invalid_record()
    for instrument_id in VISIT_INSTRUMENT_IDS[visit]:
        spec = FORMAL_INSTRUMENTS[instrument_id]
        payload = _mapping(instruments.get(instrument_id))
        payload_answers = _mapping(payload.get("raw_answers"))
        expected_answers = {
            question.id: answers[question.id]
            for question in spec.questions
            if statuses[question.id] == "answered"
        }
        active_required = {
            question.id
            for question in spec.questions
            if question.required and statuses[question.id] != "not_applicable"
        }
        completeness = _mapping(payload.get("completeness"))
        if (
            payload.get("instrument_id") != instrument_id
            or payload.get("instrument_version") != "1.0"
            or payload.get("label") != spec.label
            or payload.get("time_window") != spec.time_window
            or {
                key: value
                for key, value in payload_answers.items()
                if key in {question.id for question in spec.questions}
            }
            != expected_answers
            or completeness.get("answered") != len(active_required)
            or completeness.get("required") != len(active_required)
            or payload.get("complete") is not True
        ):
            raise _invalid_record()


def _display_value(question: QuestionSpec, value: RawExportValue) -> str:
    if value is None:
        return ""
    if question.kind == "boolean":
        return "有" if value else "没有"
    if question.kind == "multiselect":
        assert isinstance(value, tuple)
        return "、".join(value)
    if question.kind == "slider":
        if value == question.min_value and question.low_label:
            return _export_text(question.low_label)
        if value == question.max_value and question.high_label:
            return _export_text(question.high_label)
    return str(value)


def _responses(
    *,
    visit: str,
    entries: tuple[_QuestionEntry, ...],
    answers: Mapping[str, object],
    statuses: tuple[tuple[str, str], ...],
) -> tuple[ResponseSnapshot, ...]:
    status_by_id = dict(statuses)
    result: list[ResponseSnapshot] = []
    for entry in entries:
        question = entry.question
        status = status_by_id[question.id]
        answered = status == "answered"
        if answered and question.id not in answers:
            raise _invalid_record()
        raw_value = (
            _freeze_answer(question, answers[question.id]) if answered else None
        )
        result.append(
            ResponseSnapshot(
                visit=visit,
                instrument_id=entry.instrument_id,
                instrument_version=entry.instrument_version,
                field_id=question.id,
                question_text=_export_text(question.prompt),
                question_kind=question.kind,
                answered=answered,
                applicability=(
                    "not_applicable" if status == "not_applicable" else "applicable"
                ),
                raw_value=raw_value,
                display_value=_display_value(question, raw_value),
            )
        )
    return tuple(result)


def _visit_snapshots(
    *,
    visit: str,
    completed_at_iso: str,
    entries: tuple[_QuestionEntry, ...],
    statuses: tuple[tuple[str, str], ...],
) -> tuple[VisitSnapshot, ...]:
    status_by_id = dict(statuses)
    instrument_order = tuple(dict.fromkeys(entry.instrument_id for entry in entries))
    snapshots: list[VisitSnapshot] = []
    for instrument_id in instrument_order:
        instrument_entries = tuple(
            entry for entry in entries if entry.instrument_id == instrument_id
        )
        instrument_statuses = tuple(
            (entry.question.id, status_by_id[entry.question.id])
            for entry in instrument_entries
        )
        if any(
            entry.question.required
            and status_by_id[entry.question.id] == "missing"
            for entry in instrument_entries
        ):
            raise _invalid_record()
        snapshots.append(
            VisitSnapshot(
                visit=visit,
                visit_status="complete",
                completed_at_iso=completed_at_iso,
                instrument_id=instrument_id,
                instrument_version=instrument_entries[0].instrument_version,
                instrument_status="complete",
                answered_field_ids=tuple(
                    field_id
                    for field_id, status in instrument_statuses
                    if status == "answered"
                ),
                field_status=instrument_statuses,
            )
        )
    return tuple(snapshots)


def _build_participant_snapshot(
    record: Mapping[str, object],
    *,
    visit: str,
    exported_at_iso: str,
) -> ParticipantSnapshot:
    exported_at = _utc_second(exported_at_iso)
    projected, stored_answered, completed_at_iso, parsed_date = _record_projection(
        record, visit=visit
    )
    if exported_at < _utc_second(completed_at_iso):
        raise ValueError("timestamp is invalid")
    entries = _question_entries(projected, visit=visit)
    answers = questionnaire_answers(projected, visit)
    statuses = _status_inventory(
        projected,
        visit=visit,
        entries=entries,
        answers=answers,
    )
    ordered_answered = tuple(
        entry.question.id
        for entry in entries
        if dict(statuses)[entry.question.id] == "answered"
    )
    if set(stored_answered) != set(ordered_answered):
        raise _invalid_record()
    _validate_formal_payload(
        projected,
        visit=visit,
        answers=answers,
        statuses=dict(statuses),
    )
    responses = _responses(
        visit=visit,
        entries=entries,
        answers=answers,
        statuses=statuses,
    )
    visits = _visit_snapshots(
        visit=visit,
        completed_at_iso=completed_at_iso,
        entries=entries,
        statuses=statuses,
    )
    return ParticipantSnapshot(
        export_schema_version=_EXPORT_SCHEMA_VERSION,
        participant_id=str(projected["subject_id"]),
        record_date=parsed_date.isoformat(),
        intervention_day=int(projected["intervention_day"]),
        visit=visit,
        exported_at_iso=exported_at_iso,
        daily_context=_daily_context(projected),
        recording=_recording(projected),
        answered_field_ids=ordered_answered,
        field_status=statuses,
        responses=responses,
        visits=visits,
    )


def build_participant_snapshot(
    record: Mapping[str, object],
    *,
    visit: str,
    exported_at_iso: str,
) -> ParticipantSnapshot:
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    error_message = "record is invalid"
    try:
        return _build_participant_snapshot(
            record,
            visit=visit,
            exported_at_iso=exported_at_iso,
        )
    except Exception as error:
        if (
            type(error) is ValueError
            and len(error.args) == 1
            and type(error.args[0]) is str
            and error.args[0] in _NEUTRAL_ERROR_MESSAGES
        ):
            error_message = error.args[0]
    raise ValueError(error_message) from None


def _json_raw(value: RawExportValue) -> object:
    return list(value) if isinstance(value, tuple) else value


def _snapshot(snapshot: object) -> ParticipantSnapshot:
    if type(snapshot) is not ParticipantSnapshot:
        raise TypeError("snapshot must be a ParticipantSnapshot")
    return snapshot


def participant_snapshot_json(snapshot: ParticipantSnapshot) -> dict[str, object]:
    safe = _snapshot(snapshot)
    return {
        "export_schema_version": safe.export_schema_version,
        "participant_id": safe.participant_id,
        "record_date": safe.record_date,
        "intervention_day": safe.intervention_day,
        "visit": safe.visit,
        "exported_at_iso": safe.exported_at_iso,
        "daily_context": {
            key: _json_raw(value) for key, value in safe.daily_context
        },
        "recording": {key: _json_raw(value) for key, value in safe.recording},
        "answered_field_ids": list(safe.answered_field_ids),
        "field_status": dict(safe.field_status),
        "responses": [
            {
                "visit": response.visit,
                "instrument_id": response.instrument_id,
                "instrument_version": response.instrument_version,
                "field_id": response.field_id,
                "question_text": response.question_text,
                "question_kind": response.question_kind,
                "answered": response.answered,
                "applicability": response.applicability,
                "raw_value": _json_raw(response.raw_value),
                "display_value": response.display_value,
            }
            for response in safe.responses
        ],
        "visits": [
            {
                "visit": item.visit,
                "visit_status": item.visit_status,
                "completed_at_iso": item.completed_at_iso,
                "instrument_id": item.instrument_id,
                "instrument_version": item.instrument_version,
                "instrument_status": item.instrument_status,
                "answered_field_ids": list(item.answered_field_ids),
                "field_status": dict(item.field_status),
            }
            for item in safe.visits
        ],
    }


def _cell_json(value: object) -> str:
    return _export_text(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def questionnaire_export_sheets(
    snapshot: ParticipantSnapshot,
) -> dict[str, tuple[dict[str, object], ...]]:
    safe = _snapshot(snapshot)
    session_rows = (
        {
            "export_schema_version": safe.export_schema_version,
            "participant_id": safe.participant_id,
            "record_date": safe.record_date,
            "intervention_day": safe.intervention_day,
            "visit": safe.visit,
            "exported_at_iso": safe.exported_at_iso,
            "daily_context": _cell_json(
                {key: _json_raw(value) for key, value in safe.daily_context}
            ),
            "answered_field_ids": _cell_json(list(safe.answered_field_ids)),
            "field_status": _cell_json(dict(safe.field_status)),
        },
    )
    response_rows = tuple(
        {
            "visit": response.visit,
            "instrument_id": response.instrument_id,
            "field_id": response.field_id,
            "question_text": response.question_text,
            "question_kind": response.question_kind,
            "answered": response.answered,
            "applicability": response.applicability,
            "raw_value": (
                _cell_json(list(response.raw_value))
                if isinstance(response.raw_value, tuple)
                else response.raw_value
            ),
            "display_value": response.display_value,
        }
        for response in safe.responses
    )
    visit_rows = tuple(
        {
            "visit": item.visit,
            "visit_status": item.visit_status,
            "completed_at_iso": item.completed_at_iso,
            "instrument_id": item.instrument_id,
            "instrument_version": item.instrument_version,
            "instrument_status": item.instrument_status,
            "answered_field_ids": _cell_json(list(item.answered_field_ids)),
            "field_status": _cell_json(dict(item.field_status)),
        }
        for item in safe.visits
    )
    recording_rows = ({key: value for key, value in safe.recording},)
    return {
        "Session": session_rows,
        "Responses": response_rows,
        "Visits": visit_rows,
        "Recording": recording_rows,
    }


def build_participant_export(
    record: Mapping[str, object],
    *,
    visit: str,
    exported_at: datetime,
) -> LocalExportBundle:
    exported_at_iso = _export_datetime_iso(exported_at)
    snapshot = build_participant_snapshot(
        record,
        visit=visit,
        exported_at_iso=exported_at_iso,
    )
    return build_local_export_bundle(
        snapshot=participant_snapshot_json(snapshot),
        sheets=questionnaire_export_sheets(snapshot),
        exported_at=exported_at,
        filename_prefix="session",
    )
