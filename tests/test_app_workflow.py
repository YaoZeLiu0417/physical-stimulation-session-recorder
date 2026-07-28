"""Contracts for operational session-stage and context confirmation helpers."""

from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest

from app_workflow import (
    build_daily_context_confirmation,
    daily_context_confirmation_matches,
    resolve_operational_stage,
)
from session_record_workflow import create_session_record


def _record() -> dict[str, object]:
    return create_session_record(
        "sub-001",
        date(2026, 7, 29),
        6,
        "daily",
        token="deadbeef",
        now_iso="2026-07-29T08:00:00+00:00",
    )


@pytest.mark.parametrize(
    ("access_granted", "context_confirmed", "recording_complete", "questionnaire_complete", "session_complete", "expected_stage"),
    [
        (False, False, False, False, False, 1),
        (True, False, False, False, False, 2),
        (True, True, False, False, False, 3),
        (True, True, True, False, False, 4),
        (True, True, True, True, False, 5),
        (True, False, False, False, True, 6),
    ],
)
def test_resolve_operational_stage_follows_gate_order(
    access_granted: bool,
    context_confirmed: bool,
    recording_complete: bool,
    questionnaire_complete: bool,
    session_complete: bool,
    expected_stage: int,
) -> None:
    assert resolve_operational_stage(
        access_granted=access_granted,
        context_confirmed=context_confirmed,
        recording_complete=recording_complete,
        questionnaire_complete=questionnaire_complete,
        session_complete=session_complete,
    ) == expected_stage


class BoolLike:
    def __bool__(self) -> bool:
        return True


@pytest.mark.parametrize("invalid_value", [1, None, BoolLike()])
@pytest.mark.parametrize(
    "invalid_flag",
    [
        "access_granted",
        "context_confirmed",
        "recording_complete",
        "questionnaire_complete",
        "session_complete",
    ],
)
def test_resolve_operational_stage_rejects_non_boolean_flags(
    invalid_flag: str, invalid_value: object
) -> None:
    flags: dict[str, object] = {
        "access_granted": True,
        "context_confirmed": True,
        "recording_complete": True,
        "questionnaire_complete": True,
        "session_complete": False,
    }
    flags[invalid_flag] = invalid_value

    with pytest.raises(ValueError, match="boolean"):
        resolve_operational_stage(**flags)  # type: ignore[arg-type]


def test_build_daily_context_confirmation_returns_exact_identity_mapping() -> None:
    record = _record()

    assert build_daily_context_confirmation(record, auth_source="admin") == {
        "auth_source": "admin",
        "record_id": "sub-001_20260729_deadbeef",
        "subject_id": "sub-001",
        "record_date": "2026-07-29",
        "intervention_day": 6,
        "visit": "daily",
    }


def test_daily_context_confirmation_matches_only_the_exact_mapping() -> None:
    record = _record()
    confirmation = build_daily_context_confirmation(record, auth_source="signed_link")

    assert daily_context_confirmation_matches(
        confirmation, record, auth_source="signed_link"
    )


@pytest.mark.parametrize(
    "changed_key",
    [
        "auth_source",
        "record_id",
        "subject_id",
        "record_date",
        "intervention_day",
        "visit",
    ],
)
def test_daily_context_confirmation_rejects_each_changed_identity_value(
    changed_key: str,
) -> None:
    record = _record()
    confirmation = build_daily_context_confirmation(record, auth_source="admin")
    confirmation[changed_key] = "changed"

    assert not daily_context_confirmation_matches(
        confirmation, record, auth_source="admin"
    )


def test_daily_context_confirmation_rejects_extra_and_missing_keys() -> None:
    record = _record()
    confirmation = build_daily_context_confirmation(record, auth_source="admin")
    extra = {**confirmation, "daily_context": {}}
    missing = dict(confirmation)
    del missing["visit"]

    assert not daily_context_confirmation_matches(extra, record, auth_source="admin")
    assert not daily_context_confirmation_matches(missing, record, auth_source="admin")


class DictSubclass(dict[str, object]):
    pass


@pytest.mark.parametrize(
    "value",
    [None, True, [], {"auth_source": "admin"}, DictSubclass()],
)
def test_daily_context_confirmation_rejects_non_exact_dict_values(value: object) -> None:
    assert not daily_context_confirmation_matches(value, _record(), auth_source="admin")


def test_confirmation_builder_rejects_invalid_auth_and_missing_identity() -> None:
    record = _record()
    missing_identity = dict(record)
    del missing_identity["record_id"]

    with pytest.raises(ValueError, match="auth source"):
        build_daily_context_confirmation(record, auth_source="participant")
    with pytest.raises(ValueError, match="daily context identity"):
        build_daily_context_confirmation(missing_identity, auth_source="admin")


def test_confirmation_matcher_returns_false_for_invalid_auth_and_missing_identity() -> None:
    record = _record()
    missing_identity = dict(record)
    del missing_identity["record_id"]

    assert not daily_context_confirmation_matches({}, record, auth_source="participant")
    assert not daily_context_confirmation_matches({}, missing_identity, auth_source="admin")


def test_confirmation_helpers_do_not_mutate_the_record() -> None:
    record = _record()
    original = deepcopy(record)
    confirmation = build_daily_context_confirmation(record, auth_source="admin")

    assert daily_context_confirmation_matches(confirmation, record, auth_source="admin")
    assert record == original
