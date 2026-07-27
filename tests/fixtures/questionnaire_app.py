from copy import deepcopy
from datetime import date, datetime, timezone

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from questionnaire_export import build_participant_export
from questionnaire_specs import VISIT_INSTRUMENT_IDS
from questionnaire_ui import questionnaire_state_keys, render_questionnaire
from session_record_workflow import (
    create_session_record,
    mark_questionnaire_visit_complete,
    persist_daily_questionnaire,
    persist_formal_questionnaire,
    questionnaire_answers,
    questionnaire_visit_complete,
)


SCENARIOS = {
    "day1": ("daily", 1),
    "day7": ("daily", 7),
    **{visit: (visit, 7) for visit in VISIT_INSTRUMENT_IDS},
}
RECORDER_STATES = frozenset({"saved", "skipped", "failed"})
RECORD_KEY = "session_record"
EXPORT_KEY = "session_export"
COMPLETE_KEY = "session_complete"
SAVED_LOCALLY_KEY = "session_saved_locally"
STATE_NAMESPACE = "fixture-record"
SUBJECT_ID = "sub-001"
RECORD_DATE = date(2026, 7, 27)
TOKEN = "01abcdef"
CREATED_AT_ISO = "2026-07-27T10:00:00+00:00"
COMPLETED_AT_ISO = "2026-07-27T10:15:00+00:00"
EXPORTED_AT = datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc)


def recorder_metadata(status):
    saved = status == "saved"
    return {
        "version": 2,
        "storage": "browser_local",
        "status": status,
        "mode": "long" if saved else "demo",
        "duration_seconds": 60 if saved else 0,
        "camera_ready": saved,
        "microphone_ready": saved,
        "saved_confirmed": saved,
    }


def create_record(visit, intervention_day, recorder_state):
    session_record = create_session_record(
        SUBJECT_ID,
        RECORD_DATE,
        intervention_day,
        visit,
        token=TOKEN,
        now_iso=CREATED_AT_ISO,
    )
    session_record["recording"] = recorder_metadata(recorder_state)
    return session_record


def support_needed(visit, answers, answered):
    if visit == "daily":
        return (
            "suicide_thought_present_24h" in answered
            and answers.get("suicide_thought_present_24h") is True
        )
    return any(
        field_id.startswith("pss_")
        and field_id in answered
        and answers.get(field_id) is True
        for field_id in answered
    )


def finish_session():
    for key in tuple(st.session_state):
        st.session_state.pop(key, None)
    st.session_state[COMPLETE_KEY] = True


scenario_values = st.query_params.get_all("scenario")
if scenario_values and (
    len(scenario_values) != 1 or scenario_values[0] not in SCENARIOS
):
    st.error("This questionnaire scenario is unavailable.")
    st.stop()
scenario = scenario_values[0] if scenario_values else None
harness_mode = scenario is None


if st.session_state.get(COMPLETE_KEY) is True:
    st.success("This session is complete.")
    st.stop()

record = st.session_state.get(RECORD_KEY)
if record is None:
    if not harness_mode:
        selected_visit, selected_day = SCENARIOS[scenario]
    else:
        selected_visit = st.session_state.get("fixture_visit", "daily")
        selected_day = st.session_state.get("fixture_day", 7)
    selected_recorder_state = st.query_params.get("recording", "saved")
    if selected_recorder_state not in RECORDER_STATES:
        selected_recorder_state = "saved"
    record = create_record(
        selected_visit,
        selected_day,
        selected_recorder_state,
    )
    st.session_state[RECORD_KEY] = record
elif harness_mode:
    selected_visit = st.session_state.get("fixture_visit", record["visit"])
    selected_day = st.session_state.get(
        "fixture_day", record["intervention_day"]
    )
    if (
        selected_visit != record["visit"]
        or selected_day != record["intervention_day"]
    ):
        record = create_record(
            selected_visit,
            selected_day,
            "saved",
        )
        st.session_state[RECORD_KEY] = record

visit = record["visit"]
intervention_day = record["intervention_day"]
completion = record["completion"]
answered_by_visit = completion["answered_field_ids"]
step_by_visit = completion["current_step"]
if harness_mode:
    st.session_state["fixture_visit"] = visit
    st.session_state["fixture_day"] = intervention_day
    state_namespace = st.session_state.setdefault(
        "fixture_namespace", STATE_NAMESPACE
    )
    answers = st.session_state.setdefault(
        "fixture_answers", questionnaire_answers(record, visit)
    )
    initial_answered = st.session_state.get(
        "fixture_initial_answered", answered_by_visit.get(visit, [])
    )
    initial_step = st.session_state.get(
        "fixture_initial_step", step_by_visit.get(visit, 0)
    )
    st.session_state.setdefault("fixture_save_calls", 0)
else:
    state_namespace = STATE_NAMESPACE
    answers = questionnaire_answers(record, visit)
    initial_answered = answered_by_visit.get(visit, [])
    initial_step = step_by_visit.get(visit, 0)
state_keys = questionnaire_state_keys(state_namespace, visit)


def save_draft(updated, answered):
    if harness_mode:
        st.session_state["fixture_save_attempts"] = (
            st.session_state.get("fixture_save_attempts", 0) + 1
        )
        if st.session_state.get("fixture_fail_save", False) or (
            st.session_state.get("fixture_fail_on_save_attempt")
            == st.session_state["fixture_save_attempts"]
        ):
            raise RuntimeError("sensitive backend detail")
    current_step = int(st.session_state.get(state_keys.step, 0))
    if harness_mode:
        st.session_state["fixture_answers"] = dict(updated)
        st.session_state["fixture_answered"] = sorted(answered)
        st.session_state["fixture_saved_step"] = current_step
    if visit == "daily":
        persist_daily_questionnaire(
            record,
            updated,
            set(answered),
            current_step=current_step,
        )
    else:
        persist_formal_questionnaire(
            record,
            visit,
            updated,
            set(answered),
            current_step=current_step,
        )
    if harness_mode:
        st.session_state["fixture_save_calls"] += 1


if not questionnaire_visit_complete(record, visit):
    rendered_answers, completed = render_questionnaire(
        subject_id=SUBJECT_ID,
        intervention_day=intervention_day,
        answers=answers,
        save_draft=save_draft,
        visit=visit,
        state_namespace=state_namespace,
        initial_answered_field_ids=initial_answered,
        initial_step=initial_step,
    )
    if harness_mode:
        st.session_state["fixture_rendered_answers"] = dict(rendered_answers)
        st.session_state["fixture_completed"] = completed
    current_answered = set(st.session_state.get(state_keys.answered, []))
    if support_needed(visit, rendered_answers, current_answered):
        st.warning(
            "Your safety matters. Please contact the study support team or "
            "local emergency services now."
        )
    if not completed:
        st.stop()
    save_draft(rendered_answers, current_answered)
    mark_questionnaire_visit_complete(
        record,
        visit,
        completed_at_iso=COMPLETED_AT_ISO,
    )

def render_export(record, visit):
    bundle = st.session_state.get(EXPORT_KEY)
    if bundle is None:
        bundle = build_participant_export(
            deepcopy(record),
            visit=visit,
            exported_at=EXPORTED_AT,
        )
        st.session_state[EXPORT_KEY] = bundle

    st.download_button(
        "Download questionnaire record (JSON + Excel)",
        data=bundle.data,
        file_name=bundle.filename,
        mime=bundle.mime_type,
    )
    saved_locally = st.checkbox(
        "I confirm the questionnaire ZIP is saved locally",
        key=SAVED_LOCALLY_KEY,
    )
    st.button(
        "Finish this session",
        key="session_finish",
        disabled=not saved_locally,
        on_click=finish_session,
    )


if get_script_run_ctx(suppress_warning=True) is not None:
    render_export(record, visit)
