import streamlit as st

from app_workflow import (
    mark_questionnaire_visit_complete,
    persist_daily_questionnaire,
    persist_formal_questionnaire,
)
from questionnaire_ui import questionnaire_state_keys, render_questionnaire


SCENARIOS = {
    "day1": ("daily", 1),
    "day7": ("daily", 7),
    "V5": ("V5", 7),
}


scenario = st.query_params.get("scenario")
if scenario in SCENARIOS:
    selected_visit, selected_day = SCENARIOS[scenario]
    st.session_state["fixture_scenario"] = scenario
    st.session_state["fixture_visit"] = selected_visit
    st.session_state["fixture_day"] = selected_day
    st.session_state["fixture_namespace"] = f"fixture-record::{scenario}"

answers = st.session_state.setdefault("fixture_answers", {})
st.session_state.setdefault("fixture_save_calls", 0)
visit = st.session_state.setdefault("fixture_visit", "daily")
intervention_day = st.session_state.setdefault("fixture_day", 7)
state_namespace = st.session_state.setdefault("fixture_namespace", "fixture-record")
initial_answered = st.session_state.get("fixture_initial_answered", [])
initial_step = st.session_state.get("fixture_initial_step", 0)
state_keys = questionnaire_state_keys(state_namespace, visit)
record = st.session_state.setdefault(
    "fixture_record",
    {
        "schema_version": 4,
        "record_id": "sub-001_20260724_faceb00c",
        "subject_id": "sub-001",
        "record_date": "2026-07-24",
        "intervention_day": intervention_day,
        "revision": 1,
        "instrument_versions": {
            "daily_nssi_ema": "1.0",
            "weekly_nssi": "1.0",
            "formal_nssi_crf": "1.0",
        },
        "daily_core": {},
        "conditional_details": {},
        "weekly_extension": {},
        "formal_visits": {},
        "field_status": {},
        "derived_metrics": {},
        "safety_signals": {},
        "recording": {
            "video_filename": "sub-001_20260724_faceb00c.mp4",
            "started_at_iso": "2026-07-24T08:00:00+00:00",
            "ended_at_iso": "2026-07-24T08:01:00+00:00",
            "format": "mp4",
        },
        "completion": {
            "status": "draft",
            "answered_field_ids": {},
            "current_step": {},
            "questionnaire_visits": {},
        },
        "upload": {"json": "pending", "video": "pending"},
        "created_at_iso": "2026-07-24T08:00:00+00:00",
        "updated_at_iso": "2026-07-24T08:00:00+00:00",
    },
)
record["intervention_day"] = intervention_day


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
if completed:
    mark_questionnaire_visit_complete(record, visit)
st.session_state["fixture_rendered_answers"] = dict(rendered_answers)
st.session_state["fixture_completed"] = completed
st.session_state["fixture_participant_result"] = {
    "record_id": record["record_id"],
    "status": record["completion"]["status"],
}
