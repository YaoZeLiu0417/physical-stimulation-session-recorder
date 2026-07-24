import streamlit as st

from questionnaire_ui import render_questionnaire


answers = st.session_state.setdefault("fixture_answers", {})
st.session_state.setdefault("fixture_save_calls", 0)


def save_draft(updated, answered):
    st.session_state["fixture_answers"] = dict(updated)
    st.session_state["fixture_answered"] = sorted(answered)
    st.session_state["fixture_save_calls"] += 1


_, completed = render_questionnaire(
    subject_id="sub-001",
    intervention_day=7,
    answers=answers,
    save_draft=save_draft,
)
st.session_state["fixture_completed"] = completed
