"""Adaptive participant-facing questionnaire flow and Streamlit rendering."""

from __future__ import annotations

import html
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
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


logger = logging.getLogger(__name__)
SAVE_ERROR_MESSAGE = "暂时无法保存，请重试。"
BEHAVIOR_COUNT_ERROR = "至少记录一类 NSSI 行为的实际次数"


@dataclass(frozen=True)
class QuestionnaireStateKeys:
    """All Streamlit state keys owned by one record and visit."""

    answered: str
    values: str
    step: str
    error: str
    back_button: str
    next_button: str
    widget_prefix: str

    def widget(self, field_id: str) -> str:
        return f"{self.widget_prefix}{field_id}"


def questionnaire_state_keys(
    state_namespace: str, visit: str
) -> QuestionnaireStateKeys:
    namespace = str(state_namespace)
    visit_name = str(visit)
    prefix = (
        f"questionnaire::{len(namespace)}:{namespace}::"
        f"{len(visit_name)}:{visit_name}"
    )
    return QuestionnaireStateKeys(
        answered=f"{prefix}::answered",
        values=f"{prefix}::values",
        step=f"{prefix}::step",
        error=f"{prefix}::error",
        back_button=f"{prefix}::back",
        next_button=f"{prefix}::next",
        widget_prefix=f"{prefix}::widget::",
    )


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
        errors.append(BEHAVIOR_COUNT_ERROR)
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


def render_question_context(
    context_label: object, *, current: int, total: int
) -> None:
    """Render escaped context for the currently visible question."""

    safe_context = html.escape(str(context_label), quote=True)
    safe_current = html.escape(str(current), quote=True)
    safe_total = html.escape(str(total), quote=True)
    st.markdown(
        '<div class="questionnaire-context">'
        f"{safe_context} · {safe_current} / {safe_total}"
        "</div>",
        unsafe_allow_html=True,
    )


def _answered_field_ids(state_keys: QuestionnaireStateKeys) -> set[str]:
    values = st.session_state.get(state_keys.answered, [])
    return {value for value in values if isinstance(value, str)}


def _mark_answered(state_keys: QuestionnaireStateKeys, field_id: str) -> None:
    answered = _answered_field_ids(state_keys)
    answered.add(field_id)
    st.session_state[state_keys.answered] = sorted(answered)
    values = dict(st.session_state.get(state_keys.values, {}))
    widget_key = state_keys.widget(field_id)
    if widget_key in st.session_state:
        values[field_id] = st.session_state[widget_key]
    st.session_state[state_keys.values] = values


def render_question(
    question: QuestionSpec, state_keys: QuestionnaireStateKeys
) -> Any:
    """Render one question using only native Streamlit input controls."""

    key = state_keys.widget(question.id)
    change_args = {
        "on_change": _mark_answered,
        "args": (state_keys, question.id),
    }
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
            '<div class="questionnaire-endpoints">'
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


def _restore_scoped_values(
    answers: dict[str, Any], state_keys: QuestionnaireStateKeys
) -> None:
    values = dict(st.session_state.get(state_keys.values, {}))
    answers.clear()
    answers.update(values)


def _show_pending_errors(state_keys: QuestionnaireStateKeys) -> None:
    pending = st.session_state.pop(state_keys.error, None)
    if pending is None:
        return
    errors = pending if isinstance(pending, (list, tuple)) else [pending]
    for error in errors:
        st.error(str(error))


def _save_draft_at_step(
    save_draft: Callable[[dict[str, Any], set[str]], None],
    answers: dict[str, Any],
    answered: set[str],
    state_keys: QuestionnaireStateKeys,
    *,
    previous_step: int,
    target_step: int,
) -> bool:
    st.session_state[state_keys.step] = target_step
    try:
        save_draft(answers, answered)
    except Exception:
        st.session_state[state_keys.step] = previous_step
        logger.exception("Unable to save questionnaire draft")
        st.error(SAVE_ERROR_MESSAGE)
        return False
    return True


def render_questionnaire(
    *,
    subject_id: str,
    intervention_day: int,
    answers: dict[str, Any],
    save_draft: Callable[[dict[str, Any], set[str]], None],
    visit: str = "daily",
    state_namespace: str | None = None,
    initial_answered_field_ids: Iterable[str] | None = None,
    initial_step: int = 0,
) -> tuple[dict[str, Any], bool]:
    """Render one active question and persist each successful navigation."""

    namespace = (
        state_namespace
        if state_namespace is not None
        else f"{subject_id}:{intervention_day}"
    )
    state_keys = questionnaire_state_keys(namespace, visit)
    if state_keys.values not in st.session_state:
        st.session_state[state_keys.values] = dict(answers)
    if state_keys.answered not in st.session_state:
        value_ids = set(st.session_state[state_keys.values])
        st.session_state[state_keys.answered] = sorted(
            {
                field_id
                for field_id in (initial_answered_field_ids or ())
                if isinstance(field_id, str) and field_id in value_ids
            }
        )
    if state_keys.step not in st.session_state:
        st.session_state[state_keys.step] = initial_step

    answered = _answered_field_ids(state_keys) & set(
        st.session_state[state_keys.values]
    )
    st.session_state[state_keys.answered] = sorted(answered)
    _restore_scoped_values(answers, state_keys)
    flow = (
        build_flow(answers, intervention_day)
        if visit == "daily"
        else formal_flow(visit, answers)
    )
    active_ids = {question.id for question in flow}
    scoped_values = st.session_state[state_keys.values]
    answers.clear()
    answers.update(
        {
            field_id: value
            for field_id, value in scoped_values.items()
            if field_id in active_ids
        }
    )
    try:
        requested_step = int(st.session_state.get(state_keys.step, 0))
    except (TypeError, ValueError):
        requested_step = 0
    step = min(max(requested_step, 0), max(len(flow) - 1, 0))
    st.session_state[state_keys.step] = step

    render_question_context(
        question_context_label(flow[step], visit) if flow else "当前",
        current=step + 1 if flow else 0,
        total=len(flow),
    )
    _show_pending_errors(state_keys)

    if not flow:
        return answers, True

    question = flow[step]
    widget_key = state_keys.widget(question.id)
    if widget_key not in st.session_state and question.id in scoped_values:
        st.session_state[widget_key] = scoped_values[question.id]
    value = render_question(question, state_keys)
    answered = _answered_field_ids(state_keys)
    active_answered = answered & active_ids
    if question.id in answered:
        answers[question.id] = value

    back_column, primary_column = st.columns([1, 3])
    if back_column.button(
        "←",
        disabled=step == 0,
        help="返回上一题",
        key=state_keys.back_button,
    ):
        if not _save_draft_at_step(
            save_draft,
            answers,
            active_answered,
            state_keys,
            previous_step=step,
            target_step=step - 1,
        ):
            return answers, False
        st.rerun()

    primary_label = "继续" if step < len(flow) - 1 else "检查并提交"
    if primary_column.button(
        primary_label,
        type="primary",
        key=state_keys.next_button,
    ):
        answered = _answered_field_ids(state_keys)
        active_answered = answered & active_ids
        if question.required and question.id not in active_answered:
            st.error("请先确认当前答案。")
            return answers, False

        if step < len(flow) - 1:
            if not _save_draft_at_step(
                save_draft,
                answers,
                active_answered,
                state_keys,
                previous_step=step,
                target_step=step + 1,
            ):
                return answers, False
            st.rerun()

        if not _save_draft_at_step(
            save_draft,
            answers,
            active_answered,
            state_keys,
            previous_step=step,
            target_step=step,
        ):
            return answers, False
        errors = (
            validate_submission(answers, active_answered, intervention_day)
            if visit == "daily"
            else validate_formal_submission(visit, answers, active_answered)
        )
        if errors:
            missing_indices = [
                index
                for index, item in enumerate(flow)
                if item.required and item.id not in active_answered
            ]
            target_step = missing_indices[0] if missing_indices else None
            if target_step is None and BEHAVIOR_COUNT_ERROR in errors:
                target_step = next(
                    (
                        index
                        for index, item in enumerate(flow)
                        if item.id in COUNT_FIELDS
                    ),
                    None,
                )
            if target_step is not None:
                if not _save_draft_at_step(
                    save_draft,
                    answers,
                    active_answered,
                    state_keys,
                    previous_step=step,
                    target_step=target_step,
                ):
                    return answers, False
                st.session_state[state_keys.error] = list(errors)
                st.rerun()
            for error in errors:
                st.error(error)
            return answers, False
        return answers, True

    return answers, False
