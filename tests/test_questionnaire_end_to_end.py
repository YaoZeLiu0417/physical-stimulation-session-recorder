import json
import importlib
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event

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


def _unique_element(elements, *, key, label):
    matches = [
        element
        for element in elements
        if element.key == key and element.label == label
    ]
    assert len(matches) == 1
    return matches[0]


def _answer_and_continue(app, question, namespace, visit, value):
    keys = questionnaire_state_keys(namespace, visit)
    controls = app.radio if question.kind == "boolean" else app.slider
    _unique_element(
        controls, key=keys.widget(question.id), label=question.prompt
    ).set_value(value).run()
    matches = [button for button in app.button if button.key == keys.next_button]
    assert len(matches) == 1
    return matches[0].click().run()


def _visible_text(app) -> str:
    values = [str(app.main), str(app.sidebar)]
    collection_names = (
        "title",
        "header",
        "subheader",
        "caption",
        "markdown",
        "text",
        "info",
        "warning",
        "error",
        "success",
        "json",
        "metric",
        "code",
        "dataframe",
        "table",
        "button",
        "radio",
        "slider",
        "number_input",
        "text_area",
        "multiselect",
        "selectbox",
    )
    for collection_name in collection_names:
        for element in getattr(app, collection_name):
            for attribute in ("value", "label", "help", "placeholder"):
                value = getattr(element, attribute, None)
                if value is not None:
                    values.append(str(value))
    return "\n".join(values)


def _query_value(app, key):
    value = app.query_params[key]
    if isinstance(value, list):
        assert len(value) == 1
        return value[0]
    return value


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
    core_ids = {question.id for question in DAILY_CORE}
    assert all(
        record["field_status"]["daily"][field_id] == "answered"
        for field_id in core_ids
    )
    assert record["completion"]["answered_field_ids"]["daily"] == sorted(core_ids)
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
    assert re.fullmatch(r"sub-001_20260724_[0-9a-f]{8}", record["record_id"])
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


def test_browser_fixture_hard_refresh_recovers_two_answers_and_step_from_store(
    tmp_path, monkeypatch
):
    store_root = tmp_path / "browser-fixture-store"
    monkeypatch.setenv("QUESTIONNAIRE_FIXTURE_STORE", str(store_root))
    first_session = AppTest.from_file(str(FIXTURE), default_timeout=10)
    first_session.query_params["scenario"] = "day1"
    first_session.run()

    run_token = _query_value(first_session, "run")
    _answer_and_continue(
        first_session,
        DAILY_CORE[0],
        first_session.session_state["fixture_namespace"],
        "daily",
        False,
    )
    _answer_and_continue(
        first_session,
        DAILY_CORE[1],
        first_session.session_state["fixture_namespace"],
        "daily",
        False,
    )
    original_id = first_session.session_state["fixture_record"]["record_id"]
    original_namespace = first_session.session_state["fixture_namespace"]

    isolated_session = AppTest.from_file(str(FIXTURE), default_timeout=10)
    isolated_session.query_params["scenario"] = "day1"
    isolated_session.run()
    assert _query_value(isolated_session, "run") != run_token
    assert isolated_session.session_state["fixture_record"]["record_id"] != original_id
    assert questionnaire_answers(
        isolated_session.session_state["fixture_record"], "daily"
    ) == {}

    refreshed_session = AppTest.from_file(str(FIXTURE), default_timeout=10)
    refreshed_session.query_params["scenario"] = "day1"
    refreshed_session.query_params["run"] = run_token
    refreshed_session.run()

    refreshed_record = refreshed_session.session_state["fixture_record"]
    refreshed_keys = questionnaire_state_keys(
        refreshed_session.session_state["fixture_namespace"], "daily"
    )
    assert refreshed_record["record_id"] == original_id
    assert refreshed_session.session_state["fixture_namespace"] == original_namespace
    assert questionnaire_answers(refreshed_record, "daily") == {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
    }
    assert refreshed_record["completion"]["answered_field_ids"]["daily"] == [
        "nssi_behavior_present_24h",
        "nssi_thought_present_24h",
    ]
    assert refreshed_record["completion"]["current_step"]["daily"] == 2
    assert refreshed_session.session_state[refreshed_keys.step] == 2


def test_browser_fixture_scenario_switches_use_isolated_records_and_ui_state(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "QUESTIONNAIRE_FIXTURE_STORE", str(tmp_path / "browser-fixture-store")
    )
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.query_params["scenario"] = "day1"
    app.run()
    run_token = _query_value(app, "run")
    _answer_and_continue(
        app,
        DAILY_CORE[0],
        app.session_state["fixture_namespace"],
        "daily",
        False,
    )
    day1_id = app.session_state["fixture_record"]["record_id"]

    app.query_params["scenario"] = "day7"
    app.run()
    assert _query_value(app, "run") == run_token
    day7_record = app.session_state["fixture_record"]
    day7_keys = questionnaire_state_keys(
        app.session_state["fixture_namespace"], "daily"
    )
    assert day7_record["record_id"] != day1_id
    assert questionnaire_answers(day7_record, "daily") == {}
    assert app.session_state[day7_keys.step] == 0

    app.query_params["scenario"] = "V5"
    app.run()
    first_formal = formal_flow("V5", {})[0]
    _answer_and_continue(
        app,
        first_formal,
        app.session_state["fixture_namespace"],
        "V5",
        2,
    )
    v5_id = app.session_state["fixture_record"]["record_id"]
    assert app.session_state["fixture_record"]["formal_visits"]["V5"][
        "raw_answers"
    ] == {first_formal.id: 2}

    app.query_params["scenario"] = "day1"
    app.run()
    day1_record = app.session_state["fixture_record"]
    day1_keys = questionnaire_state_keys(
        app.session_state["fixture_namespace"], "daily"
    )
    assert len({day1_id, day7_record["record_id"], v5_id}) == 3
    assert day1_record["record_id"] == day1_id
    assert questionnaire_answers(day1_record, "daily") == {
        "nssi_thought_present_24h": False
    }
    assert "V5" not in day1_record["formal_visits"]
    assert app.session_state[day1_keys.step] == 1


@pytest.mark.parametrize(
    "invalid_token", ["../escape", "abc/def", "A" * 16, "0" * 15]
)
def test_browser_fixture_replaces_invalid_run_token_with_safe_value(
    tmp_path, monkeypatch, invalid_token
):
    store_root = tmp_path / "browser-fixture-store"
    monkeypatch.setenv("QUESTIONNAIRE_FIXTURE_STORE", str(store_root))
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.query_params["scenario"] = "day1"
    app.query_params["run"] = invalid_token
    app.run()

    safe_token = _query_value(app, "run")
    assert safe_token != invalid_token
    assert re.fullmatch(r"[0-9a-f]{16}", safe_token)
    assert (store_root / safe_token / "day1").is_dir()


def test_browser_fixture_visible_tree_omits_sensitive_operational_text(
    tmp_path, monkeypatch
):
    store_root = tmp_path / "browser-fixture-store"
    sentinel = "RAW-UPLOAD-RESPONSE-SENTINEL-7F31"
    monkeypatch.setenv("QUESTIONNAIRE_FIXTURE_STORE", str(store_root))
    monkeypatch.setenv("QUESTIONNAIRE_FIXTURE_SENTINEL", sentinel)
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.query_params["scenario"] = "day7"
    app.run()

    payload = app.session_state["fixture_sensitive_payload"]
    assert payload["record"]["derived_metrics"]["participant_score"] == (
        f"{sentinel}:score"
    )
    assert payload["record"]["safety_signals"]["risk_level"] == (
        f"{sentinel}:risk"
    )
    assert payload["remote_path"] == f"/remote/{sentinel}"
    assert payload["local_path"].startswith(str(store_root.resolve()))
    assert payload["raw_upload_response"]["request_id"] == f"{sentinel}:response"
    assert payload["upload_history"] == [f"{sentinel}:history"]
    assert payload["operations"] == f"{sentinel}:operations"
    visible = _visible_text(app)
    forbidden = (
        "score",
        "分数",
        "risk",
        "风险等级",
        "远端",
        str(store_root.resolve()),
        sentinel,
        "原始上传响应",
        "历史上传",
        "运维信息",
    )
    assert all(value.casefold() not in visible.casefold() for value in forbidden)


def test_visible_text_collector_captures_structured_render_channels(tmp_path):
    sentinel = "VISIBLE-COLLECTOR-SENTINEL-93C2"
    app_path = tmp_path / "visible_channels.py"
    app_path.write_text(
        "\n".join(
            (
                "import streamlit as st",
                f"sentinel = {sentinel!r}",
                'st.json({"value": sentinel + ":json"})',
                'st.metric(sentinel + ":metric-label", sentinel + ":metric-value")',
                'st.code(sentinel + ":code")',
                'st.dataframe([{"value": sentinel + ":dataframe"}])',
                'st.table([{"value": sentinel + ":table"}])',
            )
        ),
        encoding="utf-8",
    )
    app = AppTest.from_file(str(app_path), default_timeout=10).run()

    visible = _visible_text(app)
    for suffix in (
        ":json",
        ":metric-label",
        ":metric-value",
        ":code",
        ":dataframe",
        ":table",
    ):
        assert f"{sentinel}{suffix}" in visible


def test_browser_fixture_does_not_publish_internal_store_in_environment(monkeypatch):
    monkeypatch.delenv("QUESTIONNAIRE_FIXTURE_STORE", raising=False)
    monkeypatch.delenv("_QUESTIONNAIRE_FIXTURE_PROCESS_STORE", raising=False)
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.query_params["scenario"] = "day1"
    app.run()

    assert "_QUESTIONNAIRE_FIXTURE_PROCESS_STORE" not in os.environ


def test_fixture_storage_registers_internal_cleanup_but_not_explicit_root(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(FIXTURE.parent))
    storage = importlib.import_module("questionnaire_fixture_storage")
    internal = tmp_path / "internal"
    internal.mkdir()
    (internal / "state.json").write_text("{}", encoding="utf-8")
    registrations = []

    storage.register_process_cleanup(
        internal, register=lambda *args, **kwargs: registrations.append((args, kwargs))
    )

    assert len(registrations) == 1
    args, kwargs = registrations[0]
    cleanup, registered_root = args
    assert registered_root == internal
    assert kwargs == {"ignore_errors": True}
    cleanup(registered_root, **kwargs)
    assert not internal.exists()

    automatic = tmp_path / "automatic"
    automatic.mkdir()
    automatic_registrations = []
    monkeypatch.setattr(storage, "_internal_root", None)
    monkeypatch.setattr(
        storage.tempfile, "mkdtemp", lambda **kwargs: str(automatic)
    )
    monkeypatch.setattr(
        storage,
        "register_process_cleanup",
        lambda root: automatic_registrations.append(root),
    )
    assert storage.resolve_store_root(None) == automatic
    assert automatic_registrations == [automatic]

    explicit = tmp_path / "caller-owned"
    explicit.mkdir()
    assert storage.resolve_store_root(str(explicit)) == explicit
    assert automatic_registrations == [automatic]
    assert explicit.is_dir()


def test_fixture_store_initializes_once_under_concurrent_first_access(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(FIXTURE.parent))
    storage = importlib.import_module("questionnaire_fixture_storage")
    monkeypatch.setattr(storage, "_internal_root", None)
    first_entered = Event()
    second_entered = Event()
    release_creation = Event()
    second_started = Event()
    created_roots = []
    registrations = []

    def controlled_mkdtemp(**kwargs):
        index = len(created_roots)
        root = tmp_path / f"internal-{index}"
        created_roots.append(root)
        (first_entered if index == 0 else second_entered).set()
        assert release_creation.wait(timeout=2)
        root.mkdir()
        return str(root)

    monkeypatch.setattr(storage.tempfile, "mkdtemp", controlled_mkdtemp)
    monkeypatch.setattr(
        storage,
        "register_process_cleanup",
        lambda root: registrations.append(root),
    )

    def second_resolve():
        second_started.set()
        return storage.resolve_store_root(None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(storage.resolve_store_root, None)
        assert first_entered.wait(timeout=2)
        second = executor.submit(second_resolve)
        assert second_started.wait(timeout=2)
        second_initialized = second_entered.wait(timeout=0.5)
        release_creation.set()
        results = [first.result(timeout=2), second.result(timeout=2)]

    assert second_initialized is False
    assert created_roots == [tmp_path / "internal-0"]
    assert registrations == created_roots
    assert results == [created_roots[0], created_roots[0]]

    class FailingLock:
        def __enter__(self):
            raise AssertionError("explicit roots must not acquire the internal lock")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(storage, "_internal_root_lock", FailingLock(), raising=False)
    explicit = tmp_path / "caller-owned-concurrent"
    assert storage.resolve_store_root(str(explicit)) == explicit
