from datetime import date
import json
import re

import pytest

from record_store import (
    DailyRecordStore,
    can_cleanup,
    remote_record_dir,
    validate_subject_id,
)


def test_validate_subject_id_accepts_safe_identifier_and_trims_whitespace():
    assert validate_subject_id(" sub-001 ") == "sub-001"


@pytest.mark.parametrize(
    "subject_id",
    ["../other", "sub/001", "sub\\001", "", "   ", "a" * 65, ".sub", "sub.name", "sub?001"],
)
def test_validate_subject_id_rejects_unsafe_identifiers(subject_id):
    with pytest.raises(ValueError):
        validate_subject_id(subject_id)


def test_get_or_create_uses_one_record_per_subject_and_calendar_date(tmp_path):
    store = DailyRecordStore(tmp_path / "records")
    first = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    resumed = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    next_day = store.get_or_create("sub-001", date(2026, 7, 25), intervention_day=8)

    assert store.root.is_dir()
    assert first["schema_version"] == 4
    assert resumed["record_id"] == first["record_id"]
    assert next_day["record_id"] != first["record_id"]


def test_initial_record_has_exact_structural_contract(tmp_path):
    record = DailyRecordStore(tmp_path).get_or_create(
        "sub-001", date(2026, 7, 24), intervention_day=7
    )

    assert record["schema_version"] == 4
    assert re.fullmatch(r"sub-001_20260724_[0-9a-f]{8}", record["record_id"])
    assert record["subject_id"] == "sub-001"
    assert record["record_date"] == "2026-07-24"
    assert record["intervention_day"] == 7
    assert record["revision"] == 1
    assert record["instrument_versions"] == {
        "daily_nssi_ema": "1.0",
        "weekly_nssi": "1.0",
        "formal_nssi_crf": "1.0",
    }
    for key in (
        "daily_core",
        "conditional_details",
        "weekly_extension",
        "formal_visits",
        "field_status",
        "derived_metrics",
        "safety_signals",
        "recording",
    ):
        assert record[key] == {}
    assert record["completion"] == {
        "status": "draft",
        "answered_field_ids": {},
        "current_step": {},
    }
    assert record["upload"] == {"json": "pending", "video": "pending"}
    assert record["created_at_iso"]
    assert record["updated_at_iso"]


def test_save_resume_and_revise_preserve_history_and_reset_draft_state(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    record["daily_core"]["nssi_urge_now"] = 4
    record["completion"] = {
        "status": "in_progress",
        "answered_field_ids": {"daily": ["nssi_urge_now"]},
        "current_step": {"daily": 3},
    }
    record["upload"]["video"] = "uploaded"
    original_path = store.save(record)

    with original_path.open(encoding="utf-8") as handle:
        assert json.load(handle)["daily_core"]["nssi_urge_now"] == 4

    resumed = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    assert resumed["daily_core"] == {"nssi_urge_now": 4}
    assert resumed["completion"] == record["completion"]

    revised = store.revise(resumed)
    assert revised["record_id"] == record["record_id"]
    assert revised["revision"] == 2
    assert revised["supersedes_revision"] == 1
    assert resumed["revision"] == 1
    assert original_path.is_file()
    assert revised["completion"] == {
        "status": "draft",
        "answered_field_ids": {},
        "current_step": {},
    }
    assert revised["upload"] == {"json": "pending", "video": "uploaded"}
    assert store.path_for(revised).is_file()


@pytest.mark.parametrize(
    ("upload", "expected"),
    [
        ({"json": "uploaded", "video": "uploaded"}, True),
        ({"json": "failed", "video": "uploaded"}, False),
        ({"json": "uploaded", "video": "pending"}, False),
        ({"json": "uploaded"}, False),
    ],
)
def test_can_cleanup_requires_both_json_and_video_uploaded(upload, expected):
    assert can_cleanup(upload) is expected


def test_remote_record_dir_uses_stable_segments_without_double_slash():
    assert remote_record_dir(
        "/apps/collector/", "sub-001", "20260724", "sub-001_20260724_a1b2c3d4"
    ) == "/apps/collector/sub-001/20260724/sub-001_20260724_a1b2c3d4"


def test_remote_record_dir_validates_subject():
    with pytest.raises(ValueError):
        remote_record_dir("/apps/collector", "../other", "20260724", "record")
