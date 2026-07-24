import os
import sys
from datetime import date
from pathlib import Path

import streamlit as st

from app_workflow import (
    mark_questionnaire_visit_complete,
    persist_daily_questionnaire,
    persist_formal_questionnaire,
    questionnaire_answers,
    questionnaire_visit_complete,
)
from questionnaire_ui import questionnaire_state_keys, render_questionnaire
from record_store import DailyRecordStore


FIXTURE_DIR = Path(__file__).resolve().parent
if str(FIXTURE_DIR) not in sys.path:
    sys.path.insert(0, str(FIXTURE_DIR))

from questionnaire_fixture_storage import (  # noqa: E402
    resolve_run_token,
    resolve_store_root,
    run_store_root,
)


SCENARIOS = {
    "day1": ("daily", 1),
    "day7": ("daily", 7),
    "V5": ("V5", 7),
}


scenario = st.query_params.get("scenario")
raw_run_token = st.query_params.get("run")
run_token = resolve_run_token(raw_run_token)
if raw_run_token != run_token:
    st.query_params["run"] = run_token
if scenario in SCENARIOS:
    selected_visit, selected_day = SCENARIOS[scenario]
    st.session_state["fixture_scenario"] = scenario
    st.session_state["fixture_visit"] = selected_visit
    st.session_state["fixture_day"] = selected_day

visit = st.session_state.setdefault("fixture_visit", "daily")
intervention_day = st.session_state.setdefault("fixture_day", 7)
base_root = resolve_store_root(os.environ.get("QUESTIONNAIRE_FIXTURE_STORE"))
scenario_name = scenario if scenario in SCENARIOS else "default"
store_root = run_store_root(base_root, run_token, scenario_name)

record_store = DailyRecordStore(store_root)
record = record_store.get_or_create(
    "sub-001", date(2026, 7, 24), intervention_day=intervention_day
)
if not record["recording"]:
    record["recording"] = {
        "video_filename": f"{record['record_id']}.mp4",
        "started_at_iso": "2026-07-24T08:00:00+00:00",
        "ended_at_iso": "2026-07-24T08:01:00+00:00",
        "format": "mp4",
    }
    record_store.save(record)

persisted_completion = record["completion"]
if scenario in SCENARIOS:
    answers = questionnaire_answers(record, visit)
    initial_answered = persisted_completion["answered_field_ids"].get(visit, [])
    initial_step = persisted_completion["current_step"].get(visit, 0)
    state_namespace = f"{record['record_id']}:r{record['revision']}"
    st.session_state["fixture_answers"] = dict(answers)
    st.session_state["fixture_initial_answered"] = list(initial_answered)
    st.session_state["fixture_initial_step"] = initial_step
    st.session_state["fixture_namespace"] = state_namespace
else:
    answers = st.session_state.setdefault(
        "fixture_answers", questionnaire_answers(record, visit)
    )
    initial_answered = st.session_state.get(
        "fixture_initial_answered",
        persisted_completion["answered_field_ids"].get(visit, []),
    )
    initial_step = st.session_state.get(
        "fixture_initial_step", persisted_completion["current_step"].get(visit, 0)
    )
    state_namespace = st.session_state.setdefault("fixture_namespace", "fixture-record")

st.session_state.setdefault("fixture_save_calls", 0)
st.session_state["fixture_record"] = record
st.session_state["fixture_sensitive_sentinel"] = os.environ.get(
    "QUESTIONNAIRE_FIXTURE_SENTINEL", ""
)
state_keys = questionnaire_state_keys(state_namespace, visit)


def save_draft(updated, answered):
    st.session_state["fixture_save_attempts"] = (
        st.session_state.get("fixture_save_attempts", 0) + 1
    )
    if st.session_state.get("fixture_fail_save", False) or (
        st.session_state.get("fixture_fail_on_save_attempt")
        == st.session_state["fixture_save_attempts"]
    ):
        raise RuntimeError("sensitive backend detail")
    st.session_state["fixture_answers"] = dict(updated)
    st.session_state["fixture_answered"] = sorted(answered)
    st.session_state["fixture_saved_step"] = st.session_state[state_keys.step]
    if visit == "daily":
        persist_daily_questionnaire(
            record,
            updated,
            set(answered),
            current_step=st.session_state[state_keys.step],
        )
    else:
        persist_formal_questionnaire(
            record,
            visit,
            updated,
            set(answered),
            current_step=st.session_state[state_keys.step],
        )
    record_store.save(record)
    st.session_state["fixture_record"] = record
    st.session_state["fixture_save_calls"] += 1


rendered_answers, completed = render_questionnaire(
    subject_id="sub-001",
    intervention_day=intervention_day,
    answers=answers,
    save_draft=save_draft,
    visit=visit,
    state_namespace=state_namespace,
    initial_answered_field_ids=initial_answered,
    initial_step=initial_step,
)
if completed and not questionnaire_visit_complete(record, visit):
    mark_questionnaire_visit_complete(record, visit)
    record_store.save(record)
st.session_state["fixture_rendered_answers"] = dict(rendered_answers)
st.session_state["fixture_completed"] = completed
st.session_state["fixture_participant_result"] = {
    "record_id": record["record_id"],
    "status": record["completion"]["status"],
}
