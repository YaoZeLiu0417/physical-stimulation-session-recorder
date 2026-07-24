import json
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app_workflow import (
    mark_questionnaire_visit_complete,
    persist_daily_questionnaire,
    persist_formal_questionnaire,
    questionnaire_answers,
    upload_ready_for_visit,
)
from questionnaire_scoring import COUNT_FIELDS
from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_INSTRUMENTS,
)
from questionnaire_ui import build_flow, formal_flow, questionnaire_state_keys
from record_store import DailyRecordStore, RecordArchivedError, remote_record_dir
from upload_workflow import upload_record_bundle


FIXTURE = Path(__file__).parent / "fixtures" / "questionnaire_app.py"
RECORD_DATE = date(2026, 7, 24)
SUBJECT_ID = "sub-001"


def _negative_daily_answers() -> dict[str, object]:
    return {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 0,
    }


def _value_for_question(question) -> object:
    if question.kind == "boolean":
        return False
    if question.kind in {"slider", "integer"}:
        return question.min_value
    if question.kind == "multiselect":
        return []
    if question.kind == "text":
        return ""
    raise AssertionError(f"unhandled question kind: {question.kind}")


def _complete_answers(questions) -> dict[str, object]:
    return {question.id: _value_for_question(question) for question in questions}


def _recording_metadata(record_id: str) -> dict[str, str]:
    return {
        "video_filename": f"{record_id}.mp4",
        "started_at_iso": "2026-07-24T08:00:00+00:00",
        "ended_at_iso": "2026-07-24T08:01:00+00:00",
        "format": "mp4",
    }


def _persist_upload_state(store, record):
    def persist(state):
        record["upload"] = dict(state)
        store.save(record)

    return persist


def _completed_bundle(tmp_path, *, suffix: str):
    root = tmp_path / suffix
    store = DailyRecordStore(root)
    record = store.get_or_create(SUBJECT_ID, RECORD_DATE, intervention_day=6)
    record["recording"] = _recording_metadata(record["record_id"])
    persist_daily_questionnaire(
        record,
        _negative_daily_answers(),
        set(_negative_daily_answers()),
        current_step=4,
    )
    mark_questionnaire_visit_complete(record, "daily")
    json_path = store.save(record)
    video_path = root / record["recording"]["video_filename"]
    raw_path = root / f"{record['record_id']}.flv"
    video_path.write_bytes(b"selected mp4")
    raw_path.write_bytes(b"source flv")
    return store, record, json_path, video_path, raw_path


def test_negative_daily_record_round_trip_preserves_false_zero_and_upload_readiness(
    tmp_path,
):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create(SUBJECT_ID, RECORD_DATE, intervention_day=6)
    stable_id = record["record_id"]
    recording = _recording_metadata(stable_id)
    context = {"sleep_hours": 0.0, "tags": [], "narrative": ""}
    record["recording"] = recording

    stale_answers = {
        **_negative_daily_answers(),
        "nssi_cut_count_24h": 9,
        "nssi_medical_care_24h": True,
        "suicide_thought_frequency_24h": 4,
    }
    filtered = persist_daily_questionnaire(
        record,
        stale_answers,
        set(stale_answers),
        current_step=4,
        daily_context=context,
    )

    assert filtered == _negative_daily_answers()
    assert record["daily_core"] == _negative_daily_answers()
    assert record["conditional_details"] == {}
    assert all(
        record["field_status"]["daily"][question.id] == "not_applicable"
        for question in DAILY_CONDITIONAL
    )
    assert record["safety_signals"] == {"suicide_thought_present_24h": False}

    mark_questionnaire_visit_complete(record, "daily")
    store.save(record)
    reloaded = DailyRecordStore(tmp_path).get_or_create(
        SUBJECT_ID, RECORD_DATE, intervention_day=6
    )

    assert reloaded["schema_version"] == 4
    assert reloaded["record_id"] == stable_id
    assert reloaded["revision"] == 1
    assert reloaded["recording"] == recording
    assert reloaded["daily_context"] == context
    assert questionnaire_answers(reloaded, "daily") == _negative_daily_answers()
    assert upload_ready_for_visit(reloaded, "daily") is True


def test_positive_daily_branches_persist_then_drop_stale_values_and_safety(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create(SUBJECT_ID, RECORD_DATE, intervention_day=6)
    counts = {field_id: index for index, field_id in enumerate(COUNT_FIELDS)}
    positive = {
        "nssi_thought_present_24h": True,
        "nssi_thought_frequency_24h": 2,
        "nssi_thought_intensity_24h": 8,
        "nssi_behavior_present_24h": True,
        **counts,
        "nssi_other_description_24h": "other behavior",
        "nssi_medical_care_24h": True,
        "nssi_motives_24h": ["motive"],
        "nssi_trigger_24h": "trigger",
        "nssi_coping_24h": "coping",
        "suicide_thought_present_24h": True,
        "suicide_thought_frequency_24h": 3,
        "nssi_urge_now": 4,
        "nssi_resistance_confidence_now": 5,
    }
    persisted = persist_daily_questionnaire(
        record, positive, set(positive), current_step=20
    )

    assert set(COUNT_FIELDS) <= persisted.keys()
    assert record["conditional_details"] == {
        key: value
        for key, value in positive.items()
        if key not in {question.id for question in DAILY_CORE}
    }
    assert record["safety_signals"] == {
        "suicide_thought_present_24h": True,
        "suicide_thought_frequency_24h": 3,
        "medical_care_required_24h": True,
    }

    stale_after_controller_change = dict(positive)
    stale_after_controller_change.update(
        {
            "nssi_thought_present_24h": False,
            "nssi_behavior_present_24h": False,
            "suicide_thought_present_24h": False,
        }
    )
    persist_daily_questionnaire(
        record,
        stale_after_controller_change,
        set(stale_after_controller_change),
        current_step=4,
    )

    assert record["conditional_details"] == {}
    assert record["safety_signals"] == {"suicide_thought_present_24h": False}
    assert record["derived_metrics"]["daily"]["nssi_total_count_24h"] == 0

    active_false_safety = {
        **positive,
        "nssi_medical_care_24h": False,
        "suicide_thought_present_24h": False,
    }
    persist_daily_questionnaire(
        record, active_false_safety, set(active_false_safety), current_step=19
    )
    assert record["safety_signals"] == {
        "suicide_thought_present_24h": False,
        "medical_care_required_24h": False,
    }


def test_day7_keeps_daily_and_weekly_sections_distinct_and_scores_sicq_once(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create(SUBJECT_ID, RECORD_DATE, intervention_day=7)
    daily = {
        **_negative_daily_answers(),
        "nssi_behavior_present_24h": True,
        **{field_id: 0 for field_id in COUNT_FIELDS},
        "nssi_cut_count_24h": 3,
        "nssi_medical_care_24h": False,
    }
    weekly_questions = [
        question
        for instrument in WEEKLY_INSTRUMENTS
        for question in instrument.questions
    ]
    weekly = _complete_answers(weekly_questions)
    weekly.update({f"sicq_{index}": index % 5 for index in range(1, 8)})
    weekly["sicq_7"] = 4
    answers = {**daily, **weekly}
    flow_ids = [question.id for question in build_flow(answers, 7)]

    persist_daily_questionnaire(
        record, answers, set(answers), current_step=len(flow_ids) - 1
    )

    assert all(flow_ids.count(question.id) == 1 for question in weekly_questions)
    assert set(record["daily_core"]) == {question.id for question in DAILY_CORE}
    assert set(record["weekly_extension"]) == {q.id for q in weekly_questions}
    assert not set(record["daily_core"]) & set(record["weekly_extension"])
    assert record["weekly_extension"]["sicq_7"] == 4
    expected_scored = [weekly[f"sicq_{index}"] for index in range(1, 7)] + [0]
    assert record["derived_metrics"]["sicq_weekly"] == {
        "total": sum(expected_scored),
        "complete": True,
        "scored_items": expected_scored,
    }
    assert record["derived_metrics"]["daily"]["nssi_total_count_24h"] == 3


def test_formal_v5_matches_v4_metadata_scoring_and_pss_safety_boundary(tmp_path):
    assert VISIT_INSTRUMENT_IDS["V5"] == VISIT_INSTRUMENT_IDS["V4"]
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create(SUBJECT_ID, RECORD_DATE, intervention_day=7)
    answers = _complete_answers(formal_flow("V5", {}))
    answers["pss_1"] = True
    persist_formal_questionnaire(
        record, "V5", answers, set(answers), current_step=len(answers) - 1
    )

    visit = record["formal_visits"]["V5"]
    assert tuple(visit["instruments"]) == VISIT_INSTRUMENT_IDS["V5"]
    for instrument_id, payload in visit["instruments"].items():
        assert {
            "instrument_id",
            "instrument_version",
            "time_window",
            "raw_answers",
            "scored_answers",
            "completeness",
            "score",
            "complete",
        } == set(payload)
        assert payload["instrument_id"] == instrument_id
        assert payload["instrument_version"] == "1.0"
        assert payload["time_window"] == FORMAL_INSTRUMENTS[instrument_id].time_window

    dshi_score = visit["instruments"]["dshi_lifetime"]["score"]
    assert dshi_score["complete"] is True
    assert dshi_score["total"] == 6
    assert "nssi_total_count_24h" not in record["derived_metrics"].get("daily", {})
    assert record["safety_signals"] == {"V5_pss_positive": True}

    persist_formal_questionnaire(
        record, "V5", {"pss_1": True}, set(), current_step=0
    )
    assert "V5_pss_positive" not in record["safety_signals"]


def test_fresh_store_resumes_partial_and_completed_visits_without_sibling_leak(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create(SUBJECT_ID, RECORD_DATE, intervention_day=6)
    partial = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
    }
    persist_daily_questionnaire(record, partial, set(partial), current_step=1)
    store.save(record)

    resumed = DailyRecordStore(tmp_path).get_or_create(
        SUBJECT_ID, RECORD_DATE, intervention_day=6
    )
    assert (resumed["record_id"], resumed["revision"]) == (
        record["record_id"],
        record["revision"],
    )
    assert questionnaire_answers(resumed, "daily") == partial
    assert resumed["completion"]["answered_field_ids"]["daily"] == sorted(partial)
    assert resumed["completion"]["current_step"]["daily"] == 1

    persist_daily_questionnaire(
        resumed,
        _negative_daily_answers(),
        set(_negative_daily_answers()),
        current_step=4,
    )
    mark_questionnaire_visit_complete(resumed, "daily")
    DailyRecordStore(tmp_path).save(resumed)
    completed = DailyRecordStore(tmp_path).get_or_create(
        SUBJECT_ID, RECORD_DATE, intervention_day=6
    )
    assert upload_ready_for_visit(completed, "daily") is True
    assert upload_ready_for_visit(completed, "V5") is False

    completed["upload"] = {"json": "uploaded", "video": "uploaded"}
    state_path = DailyRecordStore(tmp_path).save(completed)
    state_path.unlink()
    with pytest.raises(RecordArchivedError) as captured:
        DailyRecordStore(tmp_path).get_or_create(
            SUBJECT_ID, RECORD_DATE, intervention_day=6
        )
    assert captured.value.record_id == completed["record_id"]
    assert captured.value.completed_visits == ("daily",)


@pytest.mark.parametrize("failed_call", [2, 3], ids=["video", "final-json-sync"])
def test_fake_upload_failure_keeps_json_selected_video_and_source_flv(
    tmp_path, failed_call
):
    store, record, json_path, video_path, raw_path = _completed_bundle(
        tmp_path, suffix=f"failure-{failed_call}"
    )
    calls = []

    def fake_upload(local_path, remote_path, *, progress_cb):
        calls.append((local_path, remote_path, progress_cb))
        if len(calls) == failed_call:
            raise RuntimeError("test upload failure")

    with pytest.raises(RuntimeError, match="test upload failure"):
        upload_record_bundle(
            json_path,
            video_path,
            remote_record_dir(
                "/apps/collector", SUBJECT_ID, "20260724", record["record_id"]
            ),
            fake_upload,
            persist_state=_persist_upload_state(store, record),
            delete_after_upload=True,
            cleanup_paths=(raw_path,),
        )

    assert json_path.is_file()
    assert video_path.read_bytes() == b"selected mp4"
    assert raw_path.read_bytes() == b"source flv"
    assert all("baidu" not in remote_path.lower() for _, remote_path, _ in calls)


def test_fake_upload_success_cleans_bundle_but_durable_index_keeps_stable_id(tmp_path):
    store, record, json_path, video_path, raw_path = _completed_bundle(
        tmp_path, suffix="success"
    )
    stable_id = record["record_id"]
    remote_dir = remote_record_dir(
        "/apps/collector", SUBJECT_ID, "20260724", stable_id
    )
    uploads = []

    upload_record_bundle(
        json_path,
        video_path,
        remote_dir,
        lambda local, remote, *, progress_cb: uploads.append((local, remote)),
        persist_state=_persist_upload_state(store, record),
        delete_after_upload=True,
        cleanup_paths=(raw_path,),
    )

    assert not json_path.exists()
    assert not video_path.exists()
    assert not raw_path.exists()
    identity_paths = list(json_path.parent.glob(".*_identity.json"))
    assert len(identity_paths) == 1
    identity = json.loads(identity_paths[0].read_text(encoding="utf-8"))
    assert identity["record_id"] == stable_id
    assert identity["lifecycle"] == "uploaded"
    with pytest.raises(RecordArchivedError) as captured:
        DailyRecordStore(json_path.parent).get_or_create(
            SUBJECT_ID, RECORD_DATE, intervention_day=6
        )
    assert captured.value.record_id == stable_id
    assert [remote for _, remote in uploads] == [
        f"{remote_dir}/{json_path.name}",
        f"{remote_dir}/{video_path.name}",
        f"{remote_dir}/{json_path.name}",
    ]


def test_remote_directory_uses_stable_record_id_and_compact_calendar_date(tmp_path):
    record = DailyRecordStore(tmp_path).get_or_create(
        SUBJECT_ID, RECORD_DATE, intervention_day=6
    )
    remote = remote_record_dir(
        "/apps/collector", SUBJECT_ID, "20260724", record["record_id"]
    )
    assert remote == f"/apps/collector/{SUBJECT_ID}/20260724/{record['record_id']}"


@pytest.mark.parametrize(
    ("scenario", "expected_visit", "expected_day"),
    [("day1", "daily", 1), ("day7", "daily", 7), ("V5", "V5", 7)],
)
def test_browser_fixture_selects_real_scenarios_and_exposes_sanitized_result(
    scenario, expected_visit, expected_day
):
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.query_params["scenario"] = scenario
    app.run()

    assert not app.exception
    assert app.session_state["fixture_scenario"] == scenario
    assert app.session_state["fixture_visit"] == expected_visit
    assert app.session_state["fixture_day"] == expected_day
    record = app.session_state["fixture_record"]
    assert record["schema_version"] == 4
    assert record["record_id"] == "sub-001_20260724_faceb00c"
    assert record["recording"]["video_filename"] == f"{record['record_id']}.mp4"
    participant_result = app.session_state["fixture_participant_result"]
    assert participant_result == {
        "record_id": record["record_id"],
        "status": record["completion"]["status"],
    }
    assert not (
        {"score", "scores", "risk", "remote_path", "upload"}
        & set(participant_result)
    )
    state_keys = questionnaire_state_keys(
        app.session_state["fixture_namespace"], expected_visit
    )
    assert state_keys.step in app.session_state
    if expected_visit == "daily":
        assert app.radio
    else:
        assert expected_visit in VISIT_INSTRUMENT_IDS
        assert app.slider
