import streamlit as st

from questionnaire_ui import questionnaire_state_keys, render_questionnaire


answers = st.session_state.setdefault("fixture_answers", {})
st.session_state.setdefault("fixture_save_calls", 0)
visit = st.session_state.setdefault("fixture_visit", "daily")
intervention_day = st.session_state.setdefault("fixture_day", 7)
state_namespace = st.session_state.setdefault("fixture_namespace", "fixture-record")
initial_answered = st.session_state.get("fixture_initial_answered", [])
initial_step = st.session_state.get("fixture_initial_step", 0)
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
st.session_state["fixture_rendered_answers"] = dict(rendered_answers)
st.session_state["fixture_completed"] = completed
