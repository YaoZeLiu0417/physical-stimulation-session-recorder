import ast
from collections.abc import Iterator, Mapping, MutableMapping
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import session_record_workflow
from session_record_workflow import (
    clear_owned_session_state,
    create_session_record,
    session_record_matches,
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


def test_session_record_workflow_has_no_external_capability_calls_or_source() -> None:
    source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_names = {
        "DailyRecordStore",
        "Path",
        "open",
        "requests",
        "socket",
        "streamlit",
        "tempfile",
    }
    referenced_names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    referenced_attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    normalized_source = source.lower()

    assert referenced_names.isdisjoint(forbidden_names)
    assert referenced_attributes.isdisjoint(forbidden_names)
    assert all(
        fragment not in normalized_source
        for fragment in (
            "dailyrecordstore",
            "filename",
            "file_name",
            "filesystem",
            "media",
            "media_bytes",
            "network",
            "path",
            "pathlib",
            "requests",
            "server_storage",
            "socket",
            "storage",
            "streamlit",
            "tempfile",
            "upload",
        )
    )
