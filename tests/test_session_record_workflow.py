import ast
from collections.abc import Iterator, Mapping, MutableMapping
from copy import deepcopy
from datetime import date, datetime, timezone
from itertools import product
from pathlib import Path

import pytest

import session_record_workflow
from session_record_workflow import (
    DAILY_CONTEXT_DEFAULTS,
    build_daily_field_status,
    build_formal_field_status,
    clear_owned_session_state,
    create_session_record,
    mark_questionnaire_visit_complete,
    persist_daily_questionnaire,
    persist_formal_questionnaire,
    questionnaire_answers,
    questionnaire_visit_complete,
    session_record_matches,
)
from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_INSTRUMENTS,
)
from questionnaire_ui import (
    build_field_status as ui_build_field_status,
    build_formal_field_status as ui_build_formal_field_status,
    formal_flow,
)


WORKFLOW_SOURCE = Path(__file__).resolve().parents[1] / "session_record_workflow.py"
VALID_CONTEXT = {
    "subject_id": "sub-001",
    "record_date": date(2026, 7, 24),
    "intervention_day": 7,
    "visit": "daily",
}
VALID_CREATION = {
    **VALID_CONTEXT,
    "token": "01abcdef",
    "now_iso": "2026-07-24T08:09:10+00:00",
}
REQUIRED_TOP_LEVEL_KEYS = {
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
MUTABLE_SECTION_KEYS = {
    "daily_context",
    "daily_core",
    "conditional_details",
    "weekly_extension",
    "formal_visits",
    "field_status",
    "recording",
}
PROTECTED_SESSION_KEYS = {"authed", "auth_source", "subject_id", "visit"}
PROHIBITED_RECORD_KEYS = {
    "safety_signals",
    "derived_metrics",
    "upload",
    "local_cleanup",
    "path",
    "filename",
    "file_name",
    "media",
    "media_bytes",
    "server_storage",
}


def _session_record(*, day: int = 7, visit: str = "daily") -> dict[str, object]:
    return create_session_record(
        **{
            **VALID_CREATION,
            "intervention_day": day,
            "visit": visit,
        }
    )


def _raw_value(question: object) -> object:
    kind = question.kind
    if kind == "boolean":
        return False
    if kind in {"slider", "integer"}:
        return question.min_value
    if kind == "multiselect":
        return []
    if kind == "text":
        return ""
    raise AssertionError(f"unsupported question kind: {kind}")


def _formal_answers(visit: str) -> dict[str, object]:
    return {
        question.id: _raw_value(question)
        for question in formal_flow(visit, {})
    }


def _literal_record_keys(tree: ast.AST) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys.update(
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
        elif (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id.endswith("_KEYS")
                for target in node.targets
            )
            and isinstance(node.value, (ast.List, ast.Set, ast.Tuple))
        ):
            keys.update(
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "pop", "setdefault"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return keys


def test_create_session_record_returns_exact_session_only_schema() -> None:
    record = create_session_record(**VALID_CREATION)

    assert record == {
        "schema_version": 5,
        "record_id": "sub-001_20260724_01abcdef",
        "subject_id": "sub-001",
        "record_date": "2026-07-24",
        "intervention_day": 7,
        "visit": "daily",
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
        "created_at_iso": "2026-07-24T08:09:10+00:00",
        "updated_at_iso": "2026-07-24T08:09:10+00:00",
    }
    assert set(record) == REQUIRED_TOP_LEVEL_KEYS
    assert set(record["completion"]) == {
        "status",
        "answered_field_ids",
        "current_step",
        "questionnaire_visits",
    }
    assert set(record).isdisjoint(
        {
            "safety_signals",
            "derived_metrics",
            "upload",
            "local_cleanup",
            "path",
            "filename",
            "media",
            "server_storage",
        }
    )


def test_create_session_record_uses_fresh_independent_mutable_containers() -> None:
    first = create_session_record(**VALID_CREATION)
    second = create_session_record(**VALID_CREATION)

    mutable_keys = {
        "instrument_versions",
        "daily_context",
        "daily_core",
        "conditional_details",
        "weekly_extension",
        "formal_visits",
        "field_status",
        "recording",
        "completion",
    }
    assert all(first[key] is not second[key] for key in mutable_keys)
    assert all(
        first["completion"][key] is not second["completion"][key]
        for key in (
            "answered_field_ids",
            "current_step",
            "questionnaire_visits",
        )
    )

    first["daily_core"]["nssi_urge"] = 3
    first["completion"]["answered_field_ids"]["daily"] = ["nssi_urge"]

    assert second["daily_core"] == {}
    assert second["completion"]["answered_field_ids"] == {}


def test_create_session_record_delegates_subject_id_validation(monkeypatch) -> None:
    observed: list[object] = []

    def validate_subject_id(value: object) -> str:
        observed.append(value)
        return "validated-subject"

    monkeypatch.setattr(
        session_record_workflow.participant_identity,
        "validate_subject_id",
        validate_subject_id,
    )

    record = create_session_record(**VALID_CREATION)

    assert observed == ["sub-001"]
    assert record["subject_id"] == "validated-subject"
    assert record["record_id"] == "validated-subject_20260724_01abcdef"


@pytest.mark.parametrize(
    "subject_id",
    ["", " sub-001", "sub/001", False, 0, None],
)
def test_create_session_record_rejects_invalid_subject_ids(subject_id: object) -> None:
    with pytest.raises(ValueError, match="participant identifier is invalid"):
        create_session_record(**{**VALID_CREATION, "subject_id": subject_id})


@pytest.mark.parametrize(
    "record_date",
    ["2026-07-24", datetime(2026, 7, 24), False, 0, None],
)
def test_create_session_record_requires_an_actual_date(record_date: object) -> None:
    with pytest.raises(ValueError, match="record date is invalid"):
        create_session_record(**{**VALID_CREATION, "record_date": record_date})


@pytest.mark.parametrize("intervention_day", [False, True, 0, 29, 1.0, "1", None])
def test_create_session_record_rejects_invalid_intervention_days(
    intervention_day: object,
) -> None:
    with pytest.raises(ValueError, match="intervention day is invalid"):
        create_session_record(
            **{**VALID_CREATION, "intervention_day": intervention_day}
        )


@pytest.mark.parametrize("intervention_day", [1, 28])
def test_create_session_record_accepts_intervention_day_boundaries(
    intervention_day: int,
) -> None:
    record = create_session_record(
        **{**VALID_CREATION, "intervention_day": intervention_day}
    )

    assert record["intervention_day"] == intervention_day


@pytest.mark.parametrize("visit", ["", "V2", "v1", "daily ", False, 0, None])
def test_create_session_record_rejects_unknown_visits(visit: object) -> None:
    with pytest.raises(ValueError, match="visit is invalid"):
        create_session_record(**{**VALID_CREATION, "visit": visit})


@pytest.mark.parametrize("visit", ["daily", "V1", "V3", "V4", "V5", "V6"])
def test_create_session_record_accepts_each_approved_visit(visit: str) -> None:
    record = create_session_record(**{**VALID_CREATION, "visit": visit})

    assert record["visit"] == visit


@pytest.mark.parametrize(
    "token",
    ["", "abcdefg", "abcdef123", "ABCDEF12", "abcdeg12", False, 0, None],
)
def test_create_session_record_rejects_invalid_tokens(token: object) -> None:
    with pytest.raises(ValueError, match="token is invalid"):
        create_session_record(**{**VALID_CREATION, "token": token})


@pytest.mark.parametrize("token", ["00000000", "deadbeef", "1234abcd"])
def test_create_session_record_accepts_exact_lowercase_hex_tokens(token: str) -> None:
    record = create_session_record(**{**VALID_CREATION, "token": token})

    assert record["record_id"].endswith(f"_{token}")


@pytest.mark.parametrize(
    "now_iso",
    ["2026-07-24T08:09:10Z", "2026-07-24T08:09:10+00:00"],
)
def test_create_session_record_preserves_approved_utc_timestamp_form(
    now_iso: str,
) -> None:
    record = create_session_record(**{**VALID_CREATION, "now_iso": now_iso})

    assert record["created_at_iso"] == now_iso
    assert record["updated_at_iso"] == now_iso


@pytest.mark.parametrize(
    "now_iso",
    [
        "2026-07-24",
        "2026-07-24T08:09+00:00",
        "2026-07-24T08:09:10",
        "2026-07-24T08:09:10.000000+00:00",
        "2026-07-24T08:09:10+08:00",
        "2026-02-30T08:09:10+00:00",
        "2026-07-24 08:09:10+00:00",
        "not-a-timestamp",
        False,
        0,
        None,
    ],
)
def test_create_session_record_rejects_noncanonical_or_non_utc_timestamps(
    now_iso: object,
) -> None:
    with pytest.raises(ValueError, match="timestamp is invalid"):
        create_session_record(**{**VALID_CREATION, "now_iso": now_iso})


def test_session_record_matches_approved_identity_and_context() -> None:
    record = create_session_record(**VALID_CREATION)

    assert session_record_matches(record, **VALID_CONTEXT) is True


def test_session_record_matches_rejects_identity_only_partial_record() -> None:
    partial_record = {
        "schema_version": 5,
        "subject_id": "sub-001",
        "record_date": "2026-07-24",
        "intervention_day": 7,
        "visit": "daily",
    }

    assert session_record_matches(partial_record, **VALID_CONTEXT) is False


@pytest.mark.parametrize("missing_key", sorted(REQUIRED_TOP_LEVEL_KEYS))
def test_session_record_matches_rejects_each_missing_top_level_section(
    missing_key: str,
) -> None:
    record = create_session_record(**VALID_CREATION)
    del record[missing_key]

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    "extra_key",
    [
        "upload",
        "derived_metrics",
        "safety_signals",
        "local_cleanup",
        "path",
        "filename",
        "media",
        "media_bytes",
        "server_storage",
    ],
)
def test_session_record_matches_rejects_forbidden_extra_top_level_fields(
    extra_key: str,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record[extra_key] = {}

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize("section", sorted(MUTABLE_SECTION_KEYS))
@pytest.mark.parametrize("malformed", [None, False, [], "mapping"])
def test_session_record_matches_rejects_malformed_mutable_sections(
    section: str,
    malformed: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record[section] = malformed

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    "instrument_versions",
    [
        None,
        [],
        {},
        {
            "daily_nssi_ema": "1.0",
            "weekly_nssi": "1.0",
            "formal_nssi_crf": "2.0",
        },
        {
            "daily_nssi_ema": "1.0",
            "weekly_nssi": "1.0",
            "formal_nssi_crf": "1.0",
            "extra": "1.0",
        },
    ],
)
def test_session_record_matches_requires_exact_instrument_versions(
    instrument_versions: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["instrument_versions"] = instrument_versions

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize("revision", [False, 0, 2, "1", None])
def test_session_record_matches_requires_initial_integer_revision(
    revision: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["revision"] = revision

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    "record_id",
    [
        "sub-002_20260724_01abcdef",
        "sub-001_20260725_01abcdef",
        "sub-001_20260724_ABCDEF12",
        "sub-001_20260724_short",
        False,
        None,
    ],
)
def test_session_record_matches_requires_context_consistent_record_id(
    record_id: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["record_id"] = record_id

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize("timestamp_key", ["created_at_iso", "updated_at_iso"])
@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-07-24T08:09:10",
        "2026-07-24T08:09:10.123+00:00",
        "2026-07-24T08:09:10+08:00",
        "2026-02-30T08:09:10+00:00",
        False,
        None,
    ],
)
def test_session_record_matches_requires_utc_second_precision_timestamps(
    timestamp_key: str,
    timestamp: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record[timestamp_key] = timestamp

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    ("created_at_iso", "updated_at_iso"),
    [
        ("2026-07-24T08:09:10Z", "2026-07-24T08:09:09+00:00"),
        ("2026-07-24T08:09:10+00:00", "2026-07-24T08:09:09Z"),
    ],
)
def test_session_record_matches_rejects_update_before_creation(
    created_at_iso: str,
    updated_at_iso: str,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["created_at_iso"] = created_at_iso
    record["updated_at_iso"] = updated_at_iso

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    ("created_at_iso", "updated_at_iso"),
    [
        ("2026-07-24T08:09:10Z", "2026-07-24T08:09:10+00:00"),
        ("2026-07-24T08:09:10+00:00", "2026-07-24T08:09:11Z"),
    ],
)
def test_session_record_matches_accepts_equal_or_later_update(
    created_at_iso: str,
    updated_at_iso: str,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["created_at_iso"] = created_at_iso
    record["updated_at_iso"] = updated_at_iso

    assert session_record_matches(record, **VALID_CONTEXT) is True


@pytest.mark.parametrize("completion", [None, False, [], "mapping"])
def test_session_record_matches_rejects_malformed_completion(
    completion: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["completion"] = completion

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    "missing_key",
    ["status", "answered_field_ids", "current_step", "questionnaire_visits"],
)
def test_session_record_matches_rejects_incomplete_completion_shape(
    missing_key: str,
) -> None:
    record = create_session_record(**VALID_CREATION)
    del record["completion"][missing_key]

    assert session_record_matches(record, **VALID_CONTEXT) is False


def test_session_record_matches_rejects_extra_completion_field() -> None:
    record = create_session_record(**VALID_CREATION)
    record["completion"]["extra"] = {}

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    "nested_key",
    ["answered_field_ids", "current_step", "questionnaire_visits"],
)
@pytest.mark.parametrize("malformed", [None, False, [], "mapping"])
def test_session_record_matches_rejects_malformed_completion_containers(
    nested_key: str,
    malformed: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["completion"][nested_key] = malformed

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    ("nested_key", "value"),
    [
        ("answered_field_ids", ["field"]),
        ("current_step", 0),
        ("questionnaire_visits", {"status": "complete", "revision": 1}),
    ],
)
def test_session_record_matches_rejects_unknown_completion_visit_keys(
    nested_key: str,
    value: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["completion"][nested_key] = {"V2": value}

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    "answered_field_ids",
    [
        None,
        False,
        "nssi_urge",
        b"nssi_urge",
        {"nssi_urge"},
        {"field": "nssi_urge"},
        [1],
        ("nssi_urge", False),
    ],
)
def test_session_record_matches_rejects_invalid_answered_field_id_sequences(
    answered_field_ids: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["completion"]["answered_field_ids"] = {
        "daily": answered_field_ids
    }

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize("current_step", [False, True, -1, 1.0, "1", None])
def test_session_record_matches_rejects_invalid_current_steps(
    current_step: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["completion"]["current_step"] = {"daily": current_step}

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    "questionnaire_visit",
    [
        None,
        False,
        [],
        {},
        {"status": "draft", "revision": 1},
        {"status": "complete", "revision": False},
        {"status": "complete", "revision": 0},
        {"status": "complete", "revision": 2},
        {
            "status": "complete",
            "revision": 1,
            "completed_at_iso": "2026-07-24T08:09:10",
        },
        {"status": "complete", "revision": 1, "extra": True},
        {
            "status": "complete",
            "revision": 1,
            "completed_at_iso": "2026-07-24T08:09:10Z",
            "extra": True,
        },
    ],
)
def test_session_record_matches_rejects_invalid_questionnaire_visit_metadata(
    questionnaire_visit: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["completion"]["questionnaire_visits"] = {
        "daily": questionnaire_visit
    }

    assert session_record_matches(record, **VALID_CONTEXT) is False


def test_session_record_matches_accepts_legacy_and_timestamped_visit_metadata() -> None:
    record = create_session_record(**VALID_CREATION)
    record["completion"] = {
        "status": "in_progress",
        "answered_field_ids": {
            "daily": ["nssi_urge"],
            "V1": ("pss_1", "pss_2"),
        },
        "current_step": {"daily": 0, "V1": 2},
        "questionnaire_visits": {
            "daily": {"status": "complete", "revision": 1},
            "V1": {
                "status": "complete",
                "revision": 1,
                "completed_at_iso": "2026-07-24T08:09:10+00:00",
            },
        },
    }

    assert session_record_matches(record, **VALID_CONTEXT) is True


@pytest.mark.parametrize("status", [None, False, "", "finished"])
def test_session_record_matches_rejects_invalid_completion_status(
    status: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record["completion"]["status"] = status

    assert session_record_matches(record, **VALID_CONTEXT) is False


def test_session_record_matches_allows_legitimate_nonempty_mutable_state() -> None:
    record = create_session_record(**VALID_CREATION)
    record["daily_context"]["setting"] = "home"
    record["daily_core"]["nssi_urge"] = 2
    record["conditional_details"]["nssi_method"] = "other"
    record["weekly_extension"]["weekly_frequency"] = 1
    record["formal_visits"]["V1"] = {"raw_answers": {"pss_1": False}}
    record["field_status"]["daily"] = {"nssi_urge": "answered"}
    record["recording"]["status"] = "saved"
    record["completion"] = {
        "status": "complete",
        "answered_field_ids": {"daily": ["nssi_urge"]},
        "current_step": {"daily": 1},
        "questionnaire_visits": {
            "daily": {"status": "complete", "revision": 1}
        },
    }
    record["updated_at_iso"] = "2026-07-24T09:10:11Z"

    assert session_record_matches(record, **VALID_CONTEXT) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 4),
        ("schema_version", "5"),
        ("subject_id", "sub-002"),
        ("record_date", "2026-07-25"),
        ("intervention_day", True),
        ("intervention_day", 8),
        ("visit", "V1"),
    ],
)
def test_session_record_matches_rejects_mismatched_or_mistyped_record_fields(
    field: str,
    value: object,
) -> None:
    record = create_session_record(**VALID_CREATION)
    record[field] = value

    assert session_record_matches(record, **VALID_CONTEXT) is False


@pytest.mark.parametrize("record", [None, False, 0, "record", [], object()])
def test_session_record_matches_fails_closed_for_non_mappings(record: object) -> None:
    assert session_record_matches(record, **VALID_CONTEXT) is False


class RaisingMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise RuntimeError("untrusted mapping")

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("untrusted mapping")

    def __len__(self) -> int:
        raise RuntimeError("untrusted mapping")


def test_session_record_matches_fails_closed_for_malformed_mappings() -> None:
    assert session_record_matches(RaisingMapping(), **VALID_CONTEXT) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subject_id", "bad/id"),
        ("subject_id", False),
        ("record_date", "2026-07-24"),
        ("record_date", datetime(2026, 7, 24, tzinfo=timezone.utc)),
        ("intervention_day", False),
        ("intervention_day", 0),
        ("intervention_day", 29),
        ("visit", "V2"),
        ("visit", False),
    ],
)
def test_session_record_matches_fails_closed_for_invalid_requested_context(
    field: str,
    value: object,
) -> None:
    record = create_session_record(**VALID_CREATION)

    assert (
        session_record_matches(record, **{**VALID_CONTEXT, field: value}) is False
    )


def test_session_record_matches_does_not_mutate_the_record() -> None:
    record = create_session_record(**VALID_CREATION)
    record["daily_core"]["nssi_urge"] = 2
    before = deepcopy(record)

    assert session_record_matches(record, **VALID_CONTEXT) is True
    assert record == before

    assert (
        session_record_matches(
            record,
            **{**VALID_CONTEXT, "subject_id": "sub-002"},
        )
        is False
    )
    assert record == before


def test_daily_persistence_preserves_answered_falsy_values_and_raw_context() -> None:
    record = _session_record(day=6)
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": True,
        "nssi_other_description_24h": "",
        "nssi_motives_24h": [],
        "nssi_other_count_24h": 0,
        "nssi_trigger_24h": "unanswered stale value",
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }
    answered = set(answers) - {"nssi_trigger_24h"}
    context = {"sleep_hours": 0.0, "tags": [], "narrative": ""}

    persisted = persist_daily_questionnaire(
        record,
        answers,
        answered,
        current_step=8,
        daily_context=context,
    )

    assert persisted == {
        field_id: answers[field_id]
        for field_id in answered
    }
    assert record["daily_context"] == context
    assert record["daily_core"] == {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": True,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }
    assert record["conditional_details"] == {
        "nssi_other_description_24h": "",
        "nssi_motives_24h": [],
        "nssi_other_count_24h": 0,
    }
    assert record["weekly_extension"] == {}
    assert record["field_status"]["daily"]["nssi_trigger_24h"] == "missing"
    assert record["completion"]["answered_field_ids"]["daily"] == sorted(answered)
    assert record["completion"]["current_step"]["daily"] == 8
    assert set(record).isdisjoint({"derived_metrics", "safety_signals"})


def test_daily_context_preserves_every_allowlisted_field() -> None:
    record = _session_record(day=6)
    context = {
        "sleep_hours": 0.0,
        "mood_1to9": 1,
        "stress_1to9": 9,
        "pain_0to10": 0,
        "nssi_urge_0to10": 10,
        "coping_effect_1to5": 1,
        "caffeine": "none",
        "exercise": "none",
        "tags": [],
        "coping_used": [],
        "narrative": "",
        "triggers": "",
    }

    persist_daily_questionnaire(
        record,
        {},
        set(),
        current_step=0,
        daily_context=context,
    )

    assert tuple(DAILY_CONTEXT_DEFAULTS) == tuple(context)
    assert record["daily_context"] == context


def test_daily_context_allowlists_keys_and_recursively_scrubs_non_raw_data() -> None:
    record = _session_record(day=6)
    context = {
        "sleep_hours": 7.0,
        "tags": [
            {
                "label": "kept raw metadata",
                "score": 99,
                "nested": {
                    "note": "kept",
                    "risk_level": "high",
                    "safety_signals": {"urgent": True},
                    "thresholds": {"urgent": 1},
                },
            }
        ],
        "score": 99,
        "risk": {"level": "high"},
        "safety_signals": {"urgent": True},
        "thresholds": {"urgent": 1},
        "unknown_context": {"score": 100},
    }

    persist_daily_questionnaire(
        record,
        {},
        set(),
        current_step=0,
        daily_context=context,
    )

    assert record["daily_context"] == {
        "sleep_hours": 7.0,
        "tags": [
            {
                "label": "kept raw metadata",
                "nested": {"note": "kept"},
            }
        ],
    }
    serialized = repr(record["daily_context"])
    assert all(
        key not in serialized
        for key in (
            "score",
            "risk",
            "risk_level",
            "safety_signals",
            "thresholds",
            "unknown_context",
        )
    )


@pytest.mark.parametrize(
    ("day", "field_id", "value"),
    [
        (6, "nssi_urge_now", 0.5),
        (6, "nssi_urge_now", float("nan")),
        (6, "nssi_urge_now", float("inf")),
        (6, "nssi_urge_now", -1),
        (6, "nssi_urge_now", 11),
        (7, "sicq_1", 0.5),
        (7, "sicq_1", float("nan")),
        (7, "sicq_1", float("inf")),
        (7, "sicq_1", -1),
        (7, "sicq_1", 5),
    ],
)
def test_daily_and_weekly_sliders_reject_non_integer_or_out_of_range_values(
    day: int, field_id: str, value: object
) -> None:
    record = _session_record(day=day)
    before = deepcopy(record)

    with pytest.raises(ValueError, match="answers are invalid"):
        persist_daily_questionnaire(
            record,
            {field_id: value},
            {field_id},
            current_step=0,
        )

    assert record == before


@pytest.mark.parametrize("value", [1.5, float("nan"), float("inf"), 0, 6])
def test_formal_sliders_reject_non_integer_or_out_of_range_values(
    value: object,
) -> None:
    record = _session_record(visit="V1")
    before = deepcopy(record)

    with pytest.raises(ValueError, match="answers are invalid"):
        persist_formal_questionnaire(
            record,
            "V1",
            {"dshi_lifetime_1": value},
            {"dshi_lifetime_1"},
            current_step=0,
        )

    assert record == before


@pytest.mark.parametrize(
    ("section", "field_id", "value"),
    [
        ("daily_core", "nssi_thought_present_24h", "false"),
        ("daily_core", "nssi_urge_now", 0.5),
        ("daily_core", "nssi_urge_now", float("nan")),
        ("daily_core", "nssi_urge_now", float("inf")),
        ("daily_core", "nssi_urge_now", -1),
        ("conditional_details", "nssi_motives_24h", ()),
        ("conditional_details", "nssi_motives_24h", [1]),
    ],
)
def test_daily_answer_restoration_fails_closed_for_corrupted_values(
    section: str, field_id: str, value: object
) -> None:
    record = _session_record(day=6)
    record["daily_core"]["nssi_behavior_present_24h"] = True
    record[section][field_id] = value

    assert questionnaire_answers(record, "daily") == {}


@pytest.mark.parametrize(
    ("field_id", "value"),
    [
        ("pss_1", 1),
        ("dshi_lifetime_1", 1.5),
        ("dshi_lifetime_1", float("nan")),
        ("dshi_lifetime_1", float("inf")),
        ("dshi_lifetime_1", 0),
        ("dshi_lifetime_1", 6),
    ],
)
def test_formal_answer_restoration_fails_closed_for_corrupted_values(
    field_id: str, value: object
) -> None:
    record = _session_record(visit="V1")
    record["formal_visits"]["V1"] = {"raw_answers": {field_id: value}}

    assert questionnaire_answers(record, "V1") == {}


def test_public_daily_status_matches_locked_ui_helper_exhaustively() -> None:
    daily_ids = {
        question.id for question in (*DAILY_CORE, *DAILY_CONDITIONAL)
    }
    weekly_ids = {
        question.id
        for instrument in WEEKLY_INSTRUMENTS
        for question in instrument.questions
    }
    for day, thought, behavior, suicide in product(
        (6, 7), (False, True), (False, True), (False, True)
    ):
        answers = {
            "nssi_thought_present_24h": thought,
            "nssi_behavior_present_24h": behavior,
            "suicide_thought_present_24h": suicide,
        }
        answered = daily_ids | weekly_ids
        assert build_daily_field_status(answers, answered, day) == (
            ui_build_field_status(answers, answered, day)
        )


@pytest.mark.parametrize("visit", tuple(VISIT_INSTRUMENT_IDS))
def test_public_formal_status_matches_locked_ui_helper_exhaustively(
    visit: str,
) -> None:
    questions = [
        question
        for instrument_id in VISIT_INSTRUMENT_IDS[visit]
        for question in FORMAL_INSTRUMENTS[instrument_id].questions
    ]
    controller_ids = tuple(
        dict.fromkeys(
            question.show_if[0]
            for question in questions
            if question.show_if is not None
        )
    )
    answered = {question.id for question in questions}
    for controller_values in product((False, True), repeat=len(controller_ids)):
        answers = dict(zip(controller_ids, controller_values, strict=True))
        assert build_formal_field_status(visit, answers, answered) == (
            ui_build_formal_field_status(visit, answers, answered)
        )


_NON_RAW_TEST_KEYS = (
    "score",
    "scored_answers",
    "derived",
    "derived_metrics",
    "risk",
    "risk_level",
    "safety",
    "safety_signals",
    "classification",
    "threshold",
    "thresholds",
)


def _hostile_nested_payload() -> dict[str, object]:
    return {
        "kept": "raw",
        **{
            key: {"nested": {"score": 99}}
            for key in _NON_RAW_TEST_KEYS
        },
    }


def _record_with_hostile_retained_sections() -> dict[str, object]:
    record = _session_record(day=7)
    hostile = _hostile_nested_payload()
    record["daily_context"] = {
        "sleep_hours": 7.0,
        "tags": [deepcopy(hostile)],
    }
    record["daily_core"] = {
        "nssi_urge_now": 0,
        "legacy_payload": deepcopy(hostile),
    }
    record["conditional_details"] = {
        "nssi_trigger_24h": "kept",
        "legacy_payload": deepcopy(hostile),
    }
    record["weekly_extension"] = {
        "sicq_1": 0,
        "legacy_payload": deepcopy(hostile),
    }
    record["formal_visits"] = {
        "V3": {
            "raw_answers": {"pss_1": False},
            "legacy_payload": deepcopy(hostile),
        }
    }
    record["field_status"] = {
        "V3": {
            "pss_1": "answered",
            "legacy_payload": deepcopy(hostile),
        }
    }
    record["recording"] = {
        "status": "saved",
        "legacy_payload": deepcopy(hostile),
    }
    record.update({key: deepcopy(hostile) for key in _NON_RAW_TEST_KEYS})
    return record


def _mutate_daily(record: dict[str, object]) -> None:
    persist_daily_questionnaire(
        record,
        {"nssi_urge_now": 0},
        {"nssi_urge_now"},
        current_step=0,
    )


def _mutate_formal(record: dict[str, object]) -> None:
    persist_formal_questionnaire(
        record,
        "V1",
        {"pss_1": False},
        {"pss_1"},
        current_step=0,
    )


def _mutate_completion(record: dict[str, object]) -> None:
    mark_questionnaire_visit_complete(
        record,
        "daily",
        completed_at_iso="2026-07-24T08:10:11Z",
    )


@pytest.mark.parametrize(
    "mutator", [_mutate_daily, _mutate_formal, _mutate_completion]
)
def test_public_mutators_scrub_every_retained_exportable_section(mutator) -> None:
    record = _record_with_hostile_retained_sections()

    mutator(record)

    for section in (
        "daily_context",
        "daily_core",
        "conditional_details",
        "weekly_extension",
        "formal_visits",
        "field_status",
        "recording",
    ):
        serialized = repr(record[section])
        assert all(key not in serialized for key in _NON_RAW_TEST_KEYS)
    assert record["daily_context"]["sleep_hours"] == 7.0
    assert record["recording"]["status"] == "saved"
    assert record["formal_visits"]["V3"]["raw_answers"] == {"pss_1": False}
    assert set(record).isdisjoint(_NON_RAW_TEST_KEYS)


@pytest.mark.parametrize(
    "mutator", [_mutate_daily, _mutate_formal, _mutate_completion]
)
def test_public_mutators_fail_atomically_when_retained_state_cannot_be_copied(
    mutator,
) -> None:
    record = _session_record(day=7)
    record["recording"] = {"status": "saved", "bad": ("invalid",)}
    before = deepcopy(record)

    with pytest.raises(ValueError, match="record is invalid"):
        mutator(record)

    assert record == before


def test_daily_negative_branch_removes_stale_hidden_answers() -> None:
    record = _session_record(day=6)
    record["conditional_details"] = {
        "nssi_thought_frequency_24h": 4,
        "nssi_medical_care_24h": True,
    }
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 0,
        "nssi_thought_frequency_24h": 4,
        "nssi_medical_care_24h": True,
    }

    persisted = persist_daily_questionnaire(
        record, answers, set(answers), current_step=4
    )

    expected = {
        field_id: answers[field_id]
        for field_id in {question.id for question in DAILY_CORE}
    }
    assert persisted == expected
    assert record["conditional_details"] == {}
    assert all(
        record["field_status"]["daily"][question.id] == "not_applicable"
        for question in DAILY_CONDITIONAL
    )


def test_weekly_answers_are_kept_only_on_protocol_weekly_days() -> None:
    weekly_questions = [
        question
        for instrument in WEEKLY_INSTRUMENTS
        for question in instrument.questions
    ]
    weekly = {question.id: _raw_value(question) for question in weekly_questions}
    core = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 0,
    }
    weekly_record = _session_record(day=7)
    persist_daily_questionnaire(
        weekly_record,
        {**core, **weekly},
        set(core) | set(weekly),
        current_step=len(core) + len(weekly) - 1,
    )
    assert weekly_record["weekly_extension"] == weekly
    assert weekly_record["weekly_extension"]["sicq_7"] == weekly["sicq_7"]

    ordinary_record = _session_record(day=6)
    ordinary_record["weekly_extension"] = dict(weekly)
    persist_daily_questionnaire(
        ordinary_record,
        {**core, **weekly},
        set(core) | set(weekly),
        current_step=4,
    )
    assert ordinary_record["weekly_extension"] == {}
    assert set(ordinary_record["field_status"]["daily"]).isdisjoint(weekly)


@pytest.mark.parametrize("visit", tuple(VISIT_INSTRUMENT_IDS))
def test_formal_persistence_uses_protocol_order_and_raw_metadata(visit: str) -> None:
    record = _session_record(visit=visit)
    answers = _formal_answers(visit)
    answers["sicq_7"] = 4

    persisted = persist_formal_questionnaire(
        record,
        visit,
        answers,
        set(answers),
        current_step=max(0, len(answers) - 1),
    )

    visit_payload = record["formal_visits"][visit]
    assert persisted == answers
    assert visit_payload["raw_answers"] == answers
    assert tuple(visit_payload["instruments"]) == VISIT_INSTRUMENT_IDS[visit]
    assert visit_payload["complete"] is True
    for instrument_id, payload in visit_payload["instruments"].items():
        spec = FORMAL_INSTRUMENTS[instrument_id]
        assert set(payload) == {
            "instrument_id",
            "instrument_version",
            "label",
            "time_window",
            "raw_answers",
            "completeness",
            "complete",
        }
        assert payload["instrument_id"] == instrument_id
        assert payload["instrument_version"] == "1.0"
        assert payload["label"] == spec.label
        assert payload["time_window"] == spec.time_window
    if "sicq" in visit_payload["instruments"]:
        assert visit_payload["instruments"]["sicq"]["raw_answers"]["sicq_7"] == 4
    assert set(record).isdisjoint({"derived_metrics", "safety_signals"})
    assert "score" not in repr(visit_payload)
    assert "scored_answers" not in repr(visit_payload)


def test_formal_persistence_filters_hidden_and_unanswered_values() -> None:
    record = _session_record(visit="V1")
    answers = {
        "nssi_ideation_6m_present": False,
        "nssi_ideation_6m_frequency": 6,
        "pss_1": False,
        "pss_2": True,
    }

    persisted = persist_formal_questionnaire(
        record,
        "V1",
        answers,
        {
            "nssi_ideation_6m_present",
            "nssi_ideation_6m_frequency",
            "pss_1",
        },
        current_step=3,
    )

    assert persisted == {"nssi_ideation_6m_present": False, "pss_1": False}
    assert record["field_status"]["V1"]["nssi_ideation_6m_frequency"] == (
        "not_applicable"
    )
    assert record["field_status"]["V1"]["pss_2"] == "missing"


def test_questionnaire_answer_restoration_is_scoped_and_fails_closed() -> None:
    record = _session_record()
    record["daily_core"] = {"nssi_urge_now": 0}
    record["conditional_details"] = {"nssi_trigger_24h": ""}
    record["weekly_extension"] = {"sicq_1": 0}
    record["formal_visits"] = {
        "V3": {"raw_answers": {"pss_1": False}}
    }

    assert questionnaire_answers(record, "daily") == {
        "nssi_urge_now": 0,
        "sicq_1": 0,
    }
    assert questionnaire_answers(record, "V3") == {"pss_1": False}
    assert questionnaire_answers(record, "V1") == {}
    assert questionnaire_answers(record, "V2") == {}
    record["formal_visits"] = []
    assert questionnaire_answers(record, "V3") == {}


@pytest.mark.parametrize(
    ("call", "expected_message"),
    [
        (
            lambda record: persist_daily_questionnaire(
                record, [], set(), current_step=0
            ),
            "answers are invalid",
        ),
        (
            lambda record: persist_daily_questionnaire(
                record, {}, {False}, current_step=0
            ),
            "answered field ids are invalid",
        ),
        (
            lambda record: persist_daily_questionnaire(
                record, {}, set(), current_step=False
            ),
            "current step is invalid",
        ),
        (
            lambda record: persist_daily_questionnaire(
                record, {}, set(), current_step=0, daily_context=[]
            ),
            "daily context is invalid",
        ),
        (
            lambda record: persist_formal_questionnaire(
                record, "V2", {}, set(), current_step=0
            ),
            "visit is invalid",
        ),
    ],
)
def test_questionnaire_persistence_rejects_malformed_inputs_atomically(
    call, expected_message: str
) -> None:
    record = _session_record()
    before = deepcopy(record)

    with pytest.raises(ValueError, match=expected_message):
        call(record)

    assert record == before


def test_questionnaire_persistence_rejects_malformed_record_state_atomically() -> None:
    record = _session_record()
    record["completion"]["current_step"] = {"daily": False}
    before = deepcopy(record)

    with pytest.raises(ValueError, match="record is invalid"):
        persist_daily_questionnaire(record, {}, set(), current_step=0)

    assert record == before


def test_questionnaire_persistence_scrubs_hostile_legacy_non_raw_fields() -> None:
    record = _session_record()
    record.update(
        {
            "derived_metrics": {"participant_score": 99},
            "safety_signals": {"risk_level": "high"},
            "score": 99,
            "risk_level": "high",
            "thresholds": {"urgent": 1},
        }
    )
    record["formal_visits"]["V3"] = {
        "raw_answers": {"pss_1": False},
        "instruments": {
            "pss": {
                "instrument_id": "pss",
                "raw_answers": {"pss_1": False},
                "scored_answers": {"pss_1": False},
                "score": {"risk": "hidden"},
            }
        },
        "complete": False,
        "hidden_classification": "legacy",
    }

    persist_daily_questionnaire(record, {}, set(), current_step=0)

    serialized = repr(record)
    for key in (
        "derived_metrics",
        "safety_signals",
        "scored_answers",
        "score",
        "risk",
        "risk_level",
        "thresholds",
        "hidden_classification",
    ):
        assert key not in serialized


def test_questionnaire_completion_records_timestamp_revision_and_chronology() -> None:
    record = _session_record()

    mark_questionnaire_visit_complete(
        record,
        "daily",
        completed_at_iso="2026-07-24T08:10:11Z",
    )

    assert record["completion"]["status"] == "complete"
    assert record["completion"]["questionnaire_visits"]["daily"] == {
        "status": "complete",
        "revision": 1,
        "completed_at_iso": "2026-07-24T08:10:11Z",
    }
    assert record["updated_at_iso"] == "2026-07-24T08:10:11Z"
    assert questionnaire_visit_complete(record, "daily") is True
    record["revision"] = 2
    assert questionnaire_visit_complete(record, "daily") is False


@pytest.mark.parametrize(
    ("visit", "timestamp"),
    [
        ("V2", "2026-07-24T08:10:11Z"),
        ("daily", "2026-07-24T08:10:11"),
        ("daily", "2026-07-24T08:10:11.001+00:00"),
        ("daily", "2026-07-24T16:10:11+08:00"),
        ("daily", "2026-07-24T08:09:09Z"),
    ],
)
def test_questionnaire_completion_rejects_invalid_metadata_atomically(
    visit: str, timestamp: str
) -> None:
    record = _session_record()
    before = deepcopy(record)

    with pytest.raises(ValueError):
        mark_questionnaire_visit_complete(
            record,
            visit,
            completed_at_iso=timestamp,
        )

    assert record == before


def test_questionnaire_visit_complete_fails_closed_on_malformed_state() -> None:
    record = _session_record()
    record["completion"]["questionnaire_visits"] = {
        "daily": {
            "status": "complete",
            "revision": 1,
            "completed_at_iso": "not-a-time",
        }
    }
    assert questionnaire_visit_complete(record, "daily") is False
    assert questionnaire_visit_complete(record, "V2") is False


def test_raw_workflow_source_has_no_scoring_imports_or_calls() -> None:
    source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "questionnaire_scoring",
        "daily_derived_metrics",
        "score_sicq",
        "_formal_scored_answers",
        "score_formal_instrument",
    }
    referenced = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert forbidden.isdisjoint(referenced | imported)


def test_clear_owned_session_state_deletes_only_owned_exact_and_prefix_keys() -> None:
    state = {
        "authed": True,
        "auth_source": "signed-link",
        "subject_id": "sub-001",
        "visit": "daily",
        "owned_exact": "remove",
        "flow:answer": 1,
        "flow:step": 2,
        "flow": "not-prefixed",
        "other": "preserve",
    }

    clear_owned_session_state(
        state,
        exact_keys=(key for key in ["owned_exact", "missing"]),
        prefixes=(prefix for prefix in ["flow:"]),
    )

    assert state == {
        "authed": True,
        "auth_source": "signed-link",
        "subject_id": "sub-001",
        "visit": "daily",
        "flow": "not-prefixed",
        "other": "preserve",
    }


def test_clear_owned_session_state_ignores_empty_prefix() -> None:
    state = {
        "authed": True,
        "subject_id": "sub-001",
        "owned_exact": "remove",
        "unrelated": "preserve",
    }

    clear_owned_session_state(
        state,
        exact_keys=["owned_exact"],
        prefixes=[""],
    )

    assert state == {
        "authed": True,
        "subject_id": "sub-001",
        "unrelated": "preserve",
    }


def test_clear_owned_session_state_preserves_protected_exact_keys() -> None:
    state = {
        "authed": True,
        "auth_source": "signed-link",
        "subject_id": "sub-001",
        "visit": "daily",
        "owned": "remove",
    }

    clear_owned_session_state(
        state,
        exact_keys=[*PROTECTED_SESSION_KEYS, "owned"],
        prefixes=[],
    )

    assert state == {
        "authed": True,
        "auth_source": "signed-link",
        "subject_id": "sub-001",
        "visit": "daily",
    }


def test_clear_owned_session_state_preserves_protected_prefix_matches() -> None:
    state = {
        "authed": True,
        "auth_source": "signed-link",
        "subject_id": "sub-001",
        "visit": "daily",
        "answer": "remove",
        "subject_answer": "remove",
        "visit_answer": "remove",
    }

    clear_owned_session_state(
        state,
        exact_keys=[],
        prefixes=["a", "subject", "visit"],
    )

    assert state == {
        "authed": True,
        "auth_source": "signed-link",
        "subject_id": "sub-001",
        "visit": "daily",
    }


class CascadingDeleteState(MutableMapping[str, object]):
    def __init__(self) -> None:
        self.data = {
            "owned:first": 1,
            "owned:second": 2,
            "unrelated": "preserve",
        }

    def __getitem__(self, key: str) -> object:
        return self.data[key]

    def __setitem__(self, key: str, value: object) -> None:
        self.data[key] = value

    def __delitem__(self, key: str) -> None:
        del self.data[key]
        if key == "owned:first":
            self.data.pop("owned:second", None)

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


def test_clear_owned_session_state_tolerates_selected_key_disappearing() -> None:
    state = CascadingDeleteState()

    clear_owned_session_state(state, exact_keys=[], prefixes=["owned:"])

    assert dict(state) == {"unrelated": "preserve"}


def test_session_record_workflow_has_only_pure_validation_dependencies() -> None:
    tree = ast.parse(WORKFLOW_SOURCE.read_text(encoding="utf-8"))
    imported_modules = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert imported_modules <= {
        "collections",
        "datetime",
        "participant_identity",
        "questionnaire_specs",
        "re",
    }
    assert imported_modules.isdisjoint(
        {
            "http",
            "io",
            "os",
            "pathlib",
            "requests",
            "shutil",
            "socket",
            "streamlit",
            "tempfile",
            "urllib",
        }
    )


def test_session_record_workflow_has_no_external_capability_calls_or_keys() -> None:
    source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_identifiers = {
        "DailyRecordStore",
        "Path",
        "file_name",
        "filename",
        "filesystem",
        "localStorage",
        "media",
        "media_bytes",
        "network",
        "open",
        "path",
        "pathlib",
        "requests",
        "server_storage",
        "sessionStorage",
        "socket",
        "streamlit",
        "tempfile",
        "upload",
        "uploads",
    }
    referenced_names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    referenced_attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    called_identifiers = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_identifiers.update(
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    )
    prohibited_calls = {
        "connect",
        "open",
        "read_bytes",
        "read_text",
        "recv",
        "send",
        "upload_file",
        "urlopen",
        "write_bytes",
        "write_text",
    }

    assert referenced_names.isdisjoint(forbidden_identifiers)
    assert referenced_attributes.isdisjoint(forbidden_identifiers)
    assert called_identifiers.isdisjoint(prohibited_calls)
    assert _literal_record_keys(tree).isdisjoint(
        PROHIBITED_RECORD_KEYS - {"derived_metrics", "safety_signals"}
    )


def test_capability_ast_is_precise_about_identifiers_and_record_keys() -> None:
    tree = ast.parse(
        'recording_storage = {"storage": "browser_local"}\n'
        'path_status = "local"\n'
        'forged = {"upload": {}}  # pathlib, open, media, network\n'
    )
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    record_keys = _literal_record_keys(tree)

    assert names == {"recording_storage", "path_status", "forged"}
    assert record_keys == {"storage", "upload"}
    assert record_keys & PROHIBITED_RECORD_KEYS == {"upload"}
