"""Adaptive participant-facing questionnaire flow and Streamlit rendering."""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping
from typing import Any

import streamlit as st

from questionnaire_scoring import COUNT_FIELDS
from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_INSTRUMENTS,
    QuestionSpec,
    weekly_due,
)


ALTO_COLORS = {
    "black": "#050505",
    "purple": "#2D2674",
    "blue": "#33B0E4",
    "magenta": "#DD1D86",
    "orange": "#FF8D2A",
}


ALTO_CSS = """
<style>
:root {
  --alto-black: #050505;
  --alto-purple: #2D2674;
  --alto-blue: #33B0E4;
  --alto-magenta: #DD1D86;
  --alto-orange: #FF8D2A;
}

.stApp {
  background: #FFFFFF;
  color: #050505;
  letter-spacing: 0;
}

[data-testid="stHeader"],
[data-testid="stDecoration"] {
  background: #050505;
}

[data-testid="stAppViewContainer"] > .main {
  background: #FFFFFF;
}

.block-container {
  max-width: 780px;
  padding-top: 2.5rem;
  padding-bottom: 3rem;
}

.alto-top {
  align-items: center;
  background: #050505;
  color: #FFFFFF;
  display: flex;
  justify-content: space-between;
  margin: -1rem -1rem 0;
  padding: 18px 24px;
}

.alto-mark {
  font-size: 1.28rem;
  font-weight: 750;
  letter-spacing: 0;
  line-height: 1.15;
}

.alto-mark small {
  display: block;
  font-size: .66rem;
  font-weight: 550;
  letter-spacing: 0;
  margin-top: 3px;
}

.alto-context {
  color: #FFFFFF;
  font-size: .88rem;
  font-weight: 550;
  max-width: 48%;
  overflow-wrap: anywhere;
  text-align: right;
}

.alto-progress {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  height: 8px;
  margin: 0 -1rem 2rem;
}

.alto-progress span:nth-child(1) { background: #2D2674; }
.alto-progress span:nth-child(2) { background: #33B0E4; }
.alto-progress span:nth-child(3) { background: #DD1D86; }
.alto-progress span:nth-child(4) { background: #FF8D2A; }

.alto-kicker {
  color: #DD1D86;
  font-size: .82rem;
  font-weight: 750;
  letter-spacing: 0;
  margin-bottom: .75rem;
  text-transform: uppercase;
}

.alto-endpoints {
  color: #42424C;
  display: flex;
  font-size: .82rem;
  gap: 1rem;
  justify-content: space-between;
  letter-spacing: 0;
  margin: -.35rem 0 1rem;
}

.alto-endpoints span {
  max-width: 48%;
  overflow-wrap: anywhere;
}

.alto-endpoints span:last-child {
  text-align: right;
}

div[data-testid="stRadio"] div[role="radiogroup"] {
  gap: .65rem;
}

div[data-testid="stRadio"] div[role="radiogroup"] label {
  border: 1px solid #050505;
  border-radius: 6px;
  padding: .55rem .85rem;
}

div[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
  background-color: #DD1D86 !important;
  border-color: #DD1D86 !important;
}

div[data-testid="stSlider"] [data-baseweb="slider"] > div > div:nth-child(2) {
  background-color: #DD1D86 !important;
}

div[data-testid="stSlider"] [data-testid="stThumbValue"] {
  color: #DD1D86 !important;
}

.stButton > button {
  border-color: #050505;
  border-radius: 6px;
  min-height: 2.75rem;
  white-space: normal;
}

.stButton > button[kind="primary"] {
  background: #050505;
  border: 0;
  border-bottom: 4px solid #DD1D86;
  color: #FFFFFF;
}

div[data-testid="stNumberInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stMultiSelect"] > div {
  border-radius: 6px;
}

@media (max-width: 720px) {
  .block-container {
    padding-left: 1rem;
    padding-right: 1rem;
    padding-top: 2rem;
  }

  .alto-top {
    align-items: flex-start;
    gap: .75rem;
    padding: 14px 16px;
  }

  .alto-mark {
    font-size: 1.12rem;
  }

  .alto-context {
    font-size: .78rem;
  }

  .alto-endpoints {
    font-size: .76rem;
  }
}
</style>
"""


def _is_active(question: QuestionSpec, answers: Mapping[str, Any]) -> bool:
    if question.show_if is None:
        return True
    field_id, expected = question.show_if
    return answers.get(field_id) == expected


def build_flow(
    answers: Mapping[str, Any], intervention_day: int
) -> list[QuestionSpec]:
    """Build the active daily flow with each branch beside its controller."""

    flow: list[QuestionSpec] = []
    for core in DAILY_CORE:
        flow.append(core)
        flow.extend(
            question
            for question in DAILY_CONDITIONAL
            if question.show_if is not None
            and question.show_if[0] == core.id
            and _is_active(question, answers)
        )
    if weekly_due(intervention_day):
        flow.extend(
            question
            for instrument in WEEKLY_INSTRUMENTS
            for question in instrument.questions
        )
    return flow


def validate_submission(
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
    intervention_day: int,
) -> list[str]:
    """Return participant-facing daily validation errors in flow order."""

    errors = [
        f"未完成：{question.prompt}"
        for question in build_flow(answers, intervention_day)
        if question.required and question.id not in answered_field_ids
    ]
    if answers.get("nssi_behavior_present_24h") is True and sum(
        int(answers.get(field, 0) or 0) for field in COUNT_FIELDS
    ) == 0:
        errors.append("至少记录一类 NSSI 行为的实际次数")
    return errors


def formal_flow(visit: str, answers: Mapping[str, Any]) -> list[QuestionSpec]:
    """Build a formal visit flow in protocol instrument and item order."""

    return [
        question
        for instrument_id in VISIT_INSTRUMENT_IDS[visit]
        for question in FORMAL_INSTRUMENTS[instrument_id].questions
        if _is_active(question, answers)
    ]


def validate_formal_submission(
    visit: str,
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
) -> list[str]:
    """Return missing required formal items in active flow order."""

    return [
        f"未完成：{question.prompt}"
        for question in formal_flow(visit, answers)
        if question.required and question.id not in answered_field_ids
    ]


def _field_status(
    questions: list[QuestionSpec], active_ids: set[str], answered_ids: set[str]
) -> dict[str, str]:
    return {
        question.id: (
            "not_applicable"
            if question.id not in active_ids
            else "answered"
            if question.id in answered_ids
            else "missing"
        )
        for question in questions
    }


def build_field_status(
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
    intervention_day: int,
) -> dict[str, str]:
    """Classify every daily field relevant to this calendar day."""

    active_ids = {
        question.id for question in build_flow(answers, intervention_day)
    }
    questions = [*DAILY_CORE, *DAILY_CONDITIONAL]
    if weekly_due(intervention_day):
        questions.extend(
            question
            for instrument in WEEKLY_INSTRUMENTS
            for question in instrument.questions
        )
    return _field_status(questions, active_ids, answered_field_ids)


def build_formal_field_status(
    visit: str,
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
) -> dict[str, str]:
    """Classify every field configured for a formal visit."""

    active_ids = {question.id for question in formal_flow(visit, answers)}
    questions = [
        question
        for instrument_id in VISIT_INSTRUMENT_IDS[visit]
        for question in FORMAL_INSTRUMENTS[instrument_id].questions
    ]
    return _field_status(questions, active_ids, answered_field_ids)


def question_context_label(question: QuestionSpec, visit: str) -> str:
    """Return the protocol time context for the currently visible question."""

    if visit == "daily":
        if question.id.endswith("_24h"):
            return "过去 24 小时"
        if question.id.endswith("_now"):
            return "此时此刻"
        instruments = WEEKLY_INSTRUMENTS
    else:
        instruments = tuple(
            FORMAL_INSTRUMENTS[instrument_id]
            for instrument_id in VISIT_INSTRUMENT_IDS[visit]
        )

    for instrument in instruments:
        if any(item.id == question.id for item in instrument.questions):
            return f"{instrument.label} · {instrument.time_window}"
    raise KeyError(f"No questionnaire context for {visit}:{question.id}")


def inject_alto_theme(
    subject_id: str,
    intervention_day: int,
    context_label: str,
    current: int,
    total: int,
) -> None:
    """Render the static theme and escaped participant context header."""

    safe_subject = html.escape(str(subject_id), quote=True)
    safe_day = html.escape(str(intervention_day), quote=True)
    safe_context = html.escape(str(context_label), quote=True)
    safe_current = html.escape(str(current), quote=True)
    safe_total = html.escape(str(total), quote=True)
    st.markdown(ALTO_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="alto-top">'
        '<div class="alto-mark">YMH <small>NEUROSCIENCE LAB</small></div>'
        f'<div class="alto-context">{safe_subject}<br>第 {safe_day} 天</div>'
        "</div>"
        '<div class="alto-progress" aria-hidden="true">'
        "<span></span><span></span><span></span><span></span>"
        "</div>"
        f'<div class="alto-kicker">{safe_context} · {safe_current} / {safe_total}</div>',
        unsafe_allow_html=True,
    )


def _answered_field_ids() -> set[str]:
    values = st.session_state.get("answered_field_ids", [])
    return {value for value in values if isinstance(value, str)}


def _mark_answered(field_id: str) -> None:
    answered = _answered_field_ids()
    answered.add(field_id)
    st.session_state["answered_field_ids"] = sorted(answered)


def render_question(question: QuestionSpec) -> Any:
    """Render one question using only native Streamlit input controls."""

    key = f"q_{question.id}"
    change_args = {"on_change": _mark_answered, "args": (question.id,)}
    if question.kind == "boolean":
        return st.radio(
            question.prompt,
            (False, True),
            format_func=lambda value: "有" if value else "没有",
            index=None,
            horizontal=True,
            key=key,
            **change_args,
        )
    if question.kind == "slider":
        if question.min_value is None or question.max_value is None:
            raise ValueError(f"Slider {question.id} requires both endpoints")
        value = st.slider(
            question.prompt,
            question.min_value,
            question.max_value,
            key=key,
            **change_args,
        )
        low_label = html.escape(question.low_label, quote=True)
        high_label = html.escape(question.high_label, quote=True)
        st.markdown(
            '<div class="alto-endpoints">'
            f"<span>{question.min_value} {low_label}</span>"
            f"<span>{question.max_value} {high_label}</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        return value
    if question.kind == "integer":
        minimum = question.min_value if question.min_value is not None else 0
        return st.number_input(
            question.prompt,
            min_value=minimum,
            max_value=question.max_value,
            value=None,
            step=1,
            placeholder="请输入次数",
            key=key,
            **change_args,
        )
    if question.kind == "multiselect":
        return st.multiselect(
            question.prompt,
            question.options,
            key=key,
            **change_args,
        )
    if question.kind == "text":
        return st.text_area(question.prompt, key=key, **change_args)
    raise ValueError(f"Unsupported question kind: {question.kind}")


def _sync_answered_widget_values(
    answers: dict[str, Any], answered_field_ids: set[str]
) -> None:
    for field_id in answered_field_ids:
        key = f"q_{field_id}"
        if key in st.session_state:
            answers[field_id] = st.session_state[key]


def _show_pending_errors(visit: str) -> None:
    pending = st.session_state.pop(f"questionnaire_error_{visit}", None)
    if pending is None:
        return
    errors = pending if isinstance(pending, (list, tuple)) else [pending]
    for error in errors:
        st.error(str(error))


def render_questionnaire(
    *,
    subject_id: str,
    intervention_day: int,
    answers: dict[str, Any],
    save_draft: Callable[[dict[str, Any], set[str]], None],
    visit: str = "daily",
) -> tuple[dict[str, Any], bool]:
    """Render one active question and persist each successful navigation."""

    answered = _answered_field_ids()
    _sync_answered_widget_values(answers, answered)
    flow = (
        build_flow(answers, intervention_day)
        if visit == "daily"
        else formal_flow(visit, answers)
    )
    step_key = f"question_step_{visit}"
    try:
        requested_step = int(st.session_state.get(step_key, 0))
    except (TypeError, ValueError):
        requested_step = 0
    step = min(max(requested_step, 0), max(len(flow) - 1, 0))
    st.session_state[step_key] = step

    inject_alto_theme(
        subject_id,
        intervention_day,
        question_context_label(flow[step], visit) if flow else "当前",
        step + 1 if flow else 0,
        len(flow),
    )
    _show_pending_errors(visit)

    if not flow:
        return answers, True

    question = flow[step]
    widget_key = f"q_{question.id}"
    if widget_key not in st.session_state and question.id in answers:
        st.session_state[widget_key] = answers[question.id]
    value = render_question(question)
    answered = _answered_field_ids()
    if question.id in answered:
        answers[question.id] = value

    back_column, primary_column = st.columns([1, 3])
    if back_column.button(
        "←",
        disabled=step == 0,
        help="返回上一题",
        key=f"question_back_{visit}",
    ):
        st.session_state[step_key] = step - 1
        save_draft(answers, answered)
        st.rerun()

    primary_label = "继续" if step < len(flow) - 1 else "检查并提交"
    if primary_column.button(
        primary_label,
        type="primary",
        key=f"question_next_{visit}",
    ):
        answered = _answered_field_ids()
        if question.required and question.id not in answered:
            st.error("请先确认当前答案。")
            return answers, False

        if step < len(flow) - 1:
            st.session_state[step_key] = step + 1
            save_draft(answers, answered)
            st.rerun()

        save_draft(answers, answered)
        errors = (
            validate_submission(answers, answered, intervention_day)
            if visit == "daily"
            else validate_formal_submission(visit, answers, answered)
        )
        if errors:
            missing_indices = [
                index
                for index, item in enumerate(flow)
                if item.required and item.id not in answered
            ]
            if missing_indices:
                st.session_state[step_key] = missing_indices[0]
                st.session_state[f"questionnaire_error_{visit}"] = list(errors)
                st.rerun()
            for error in errors:
                st.error(error)
            return answers, False
        return answers, True

    return answers, False
