from copy import deepcopy
from datetime import date, datetime
import json
import re
import threading

import pytest

import record_store
from record_store import (
    DailyRecordStore,
    RecordConflictError,
    RecordCorruptionError,
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

    assert set(record) == {
        "schema_version",
        "record_id",
        "subject_id",
        "record_date",
        "intervention_day",
        "revision",
        "instrument_versions",
        "daily_core",
        "conditional_details",
        "weekly_extension",
        "formal_visits",
        "field_status",
        "derived_metrics",
        "safety_signals",
        "recording",
        "completion",
        "upload",
        "created_at_iso",
        "updated_at_iso",
    }
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
    for timestamp in (record["created_at_iso"], record["updated_at_iso"]):
        assert "T" in timestamp
        parsed = datetime.fromisoformat(timestamp)
        assert timestamp == parsed.isoformat(timespec="seconds")
        assert parsed.microsecond == 0


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


def test_save_persists_literal_chinese_utf8_and_reloads_it(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    record["daily_core"]["context"] = "触发情境：和家人争吵"
    saved_path = store.save(record)

    contents = saved_path.read_text(encoding="utf-8")
    assert "触发情境：和家人争吵" in contents
    assert "\\u" not in contents
    resumed = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    assert resumed["daily_core"]["context"] == "触发情境：和家人争吵"


def test_revise_deep_copies_preserved_nested_content(tmp_path):
    store = DailyRecordStore(tmp_path)
    original = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    original["daily_core"] = {"nested": {"items": [1]}}

    revised = store.revise(original)
    revised["daily_core"]["nested"]["items"].append(2)
    assert original["daily_core"]["nested"]["items"] == [1]

    original["daily_core"]["nested"]["items"].append(3)
    assert revised["daily_core"]["nested"]["items"] == [1, 2]


def test_get_or_create_selects_highest_numeric_revision_not_filename_order(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    revision_nine = deepcopy(record)
    revision_nine["revision"] = 9
    revision_ten = deepcopy(record)
    revision_ten["revision"] = 10
    for candidate in (revision_nine, revision_ten):
        store.path_for(candidate).write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    resumed = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    assert resumed["revision"] == 10


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


@pytest.mark.parametrize(
    "record_id",
    [
        "../escaped",
        "sub-001_20260724_zzzzzzzz",
        "sub-002_20260724_deadbeef",
        "sub-001_20260725_deadbeef",
        "sub-001_20260724_deadbeef/extra",
        "sub-001_20260724_deadbeef\\extra",
    ],
)
def test_local_paths_reject_hostile_or_mismatched_record_ids(tmp_path, record_id):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    record["record_id"] = record_id

    with pytest.raises(ValueError):
        store.save(record)
    assert not (tmp_path.parent / "escaped_r1_state.json").exists()


@pytest.mark.parametrize(
    "record_id",
    [
        "../escaped",
        "sub-001_20260724_zzzzzzzz",
        "sub-002_20260724_deadbeef",
        "sub-001_20260725_deadbeef",
        "sub-001_20260724_deadbeef/extra",
        "sub-001_20260724_deadbeef\\extra",
    ],
)
def test_remote_paths_reject_hostile_or_mismatched_record_ids(record_id):
    with pytest.raises(ValueError):
        remote_record_dir("/apps/collector", "sub-001", "20260724", record_id)


@pytest.mark.parametrize("date_key", ["20260229", "2026072", "202607240"])
def test_remote_paths_require_a_real_eight_digit_calendar_date(date_key):
    with pytest.raises(ValueError):
        remote_record_dir(
            "/apps/collector", "sub-001", date_key, f"sub-001_{date_key}_deadbeef"
        )


def test_concurrent_get_or_create_returns_one_record_and_one_initial_file(tmp_path):
    barrier = threading.Barrier(2)
    record_ids = []
    errors = []

    def create_record():
        try:
            store = DailyRecordStore(tmp_path)
            barrier.wait()
            record_ids.append(
                store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)[
                    "record_id"
                ]
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=create_record) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert record_ids[0] == record_ids[1]
    assert len(list(tmp_path.glob("*_r1_state.json"))) == 1


def test_concurrent_initial_saves_for_one_day_allow_only_one_record(tmp_path, monkeypatch):
    store = DailyRecordStore(tmp_path)
    seed_store = DailyRecordStore(tmp_path / "seed")
    first = seed_store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    second = deepcopy(first)
    second["record_id"] = "sub-001_20260724_deadbeef"
    scanned_empty = threading.Event()
    release_first = threading.Event()
    calls = 0
    calls_lock = threading.Lock()
    original_latest = store._latest_unlocked

    def pause_first_empty_scan(subject_id, record_date):
        nonlocal calls
        result = original_latest(subject_id, record_date)
        with calls_lock:
            calls += 1
            is_first = calls == 1
        if is_first:
            scanned_empty.set()
            assert release_first.wait(timeout=2)
        return result

    monkeypatch.setattr(store, "_latest_unlocked", pause_first_empty_scan)
    outcomes = []

    def save_candidate(record):
        try:
            store.save(record)
            outcomes.append("saved")
        except RecordConflictError:
            outcomes.append("conflict")

    first_thread = threading.Thread(target=save_candidate, args=(first,))
    second_thread = threading.Thread(target=save_candidate, args=(second,))
    first_thread.start()
    assert scanned_empty.wait(timeout=2)
    second_thread.start()
    release_first.set()
    first_thread.join()
    second_thread.join()

    assert sorted(outcomes) == ["conflict", "saved"]
    assert len(list(tmp_path.glob("*_r1_state.json"))) == 1


def test_get_or_create_and_initial_save_share_one_day_lock(tmp_path, monkeypatch):
    store = DailyRecordStore(tmp_path)
    seed_store = DailyRecordStore(tmp_path / "seed")
    candidate = seed_store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    scanned_empty = threading.Event()
    release_first = threading.Event()
    original_latest = store._latest_unlocked
    calls = 0

    def pause_first_empty_scan(subject_id, record_date):
        nonlocal calls
        result = original_latest(subject_id, record_date)
        calls += 1
        if calls == 1:
            scanned_empty.set()
            assert release_first.wait(timeout=2)
        return result

    monkeypatch.setattr(store, "_latest_unlocked", pause_first_empty_scan)
    outcomes = []

    def create():
        outcomes.append(store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7))

    def save():
        try:
            store.save(candidate)
            outcomes.append("saved")
        except RecordConflictError:
            outcomes.append("conflict")

    creator = threading.Thread(target=create)
    saver = threading.Thread(target=save)
    creator.start()
    assert scanned_empty.wait(timeout=2)
    saver.start()
    release_first.set()
    creator.join()
    saver.join()

    assert "conflict" in outcomes
    assert len(list(tmp_path.glob("*_r1_state.json"))) == 1


def test_stale_competing_draft_cannot_overwrite_newer_save(tmp_path):
    store = DailyRecordStore(tmp_path)
    base = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    first = deepcopy(base)
    stale = deepcopy(base)
    first["daily_core"]["nssi_urge_now"] = 4
    stale["daily_core"]["nssi_urge_now"] = 1

    store.save(first)
    with pytest.raises(RecordConflictError):
        store.save(stale)

    resumed = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    assert resumed["daily_core"]["nssi_urge_now"] == 4


def test_stale_competing_revision_cannot_overwrite_created_revision(tmp_path):
    store = DailyRecordStore(tmp_path)
    base = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    base["daily_core"]["nssi_urge_now"] = 4
    store.save(base)
    stale = deepcopy(base)

    first_revision = store.revise(base)
    first_revision["daily_core"]["nssi_urge_now"] = 2
    store.save(first_revision)
    with pytest.raises(RecordConflictError):
        store.revise(stale)

    resumed = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    assert resumed["revision"] == 2
    assert resumed["daily_core"]["nssi_urge_now"] == 2


@pytest.mark.parametrize("invalid_revision", [True, "1", 1.0, 0, -1])
def test_save_rejects_invalid_revision_values(tmp_path, invalid_revision):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    record["revision"] = invalid_revision

    with pytest.raises(ValueError):
        store.save(record)


def test_loaded_invalid_revision_is_reported_as_corruption(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    path = store.path_for(record)
    record["revision"] = "1"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(RecordCorruptionError, match=re.escape(path.name)):
        store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)


def test_corrupt_json_candidate_is_reported_instead_of_replaced(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    path = store.path_for(record)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RecordCorruptionError, match=re.escape(path.name)):
        store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)


def test_filename_and_json_identity_mismatch_is_reported_as_corruption(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    path = store.path_for(record)
    record["record_id"] = "sub-001_20260724_deadbeef"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(RecordCorruptionError, match=re.escape(path.name)):
        store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)


def test_symlink_candidate_is_reported_as_corruption_when_supported(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    source = store.path_for(record)
    candidate = tmp_path / "sub-001_20260724_deadbeef_r2_state.json"
    try:
        candidate.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation is not permitted in this environment")

    with pytest.raises(RecordCorruptionError, match=re.escape(candidate.name)):
        store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)


def test_serialization_failure_leaves_existing_target_and_no_temp_file(tmp_path, monkeypatch):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    target = store.path_for(record)
    original = target.read_text(encoding="utf-8")
    record["daily_core"]["value"] = 1

    def fail_dumps(*args, **kwargs):
        raise TypeError("not serializable")

    monkeypatch.setattr(record_store.json, "dumps", fail_dumps)
    with pytest.raises(TypeError, match="not serializable"):
        store.save(record)

    assert target.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("*.tmp"))


def test_replace_failure_leaves_existing_target_and_no_temp_file(tmp_path, monkeypatch):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    target = store.path_for(record)
    original = target.read_text(encoding="utf-8")
    record["daily_core"]["value"] = 1

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(record_store.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.save(record)

    assert target.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("*.tmp"))
