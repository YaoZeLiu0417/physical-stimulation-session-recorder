from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import questionnaire_ui
from questionnaire_scoring import COUNT_FIELDS
from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_INSTRUMENTS,
    QuestionSpec,
)
from questionnaire_ui import (
    QuestionnaireStateKeys,
    build_field_status,
    build_formal_field_status,
    build_flow,
    formal_flow,
    question_context_label,
    questionnaire_state_keys,
    render_question,
    render_question_context,
    validate_formal_submission,
    validate_submission,
)


FIXTURE = Path(__file__).parent / "fixtures" / "questionnaire_app.py"
FIXTURE_NAMESPACE = "fixture-record"


def _negative_daily_answers():
    return {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
    }


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def _fixture_keys(visit="daily", namespace=FIXTURE_NAMESPACE):
    return questionnaire_state_keys(namespace, visit)


def _answer_no_and_continue(app):
    app.radio[0].set_value(False).run()
    return _button(app, "继续").click().run()


def test_negative_daily_flow_contains_only_five_core_questions():
    assert [
        step.id for step in build_flow(_negative_daily_answers(), intervention_day=6)
    ] == [
        "nssi_thought_present_24h",
        "nssi_behavior_present_24h",
        "suicide_thought_present_24h",
        "nssi_urge_now",
        "nssi_resistance_confidence_now",
    ]


def test_daily_conditionals_follow_their_controller_immediately():
    answers = {
        "nssi_thought_present_24h": True,
        "nssi_behavior_present_24h": True,
        "suicide_thought_present_24h": True,
    }
    ids = [question.id for question in build_flow(answers, intervention_day=6)]

    for core in DAILY_CORE:
        expected = [
            question.id
            for question in DAILY_CONDITIONAL
            if question.show_if == (core.id, answers.get(core.id))
        ]
        core_index = ids.index(core.id)
        assert ids[core_index + 1 : core_index + 1 + len(expected)] == expected


def test_positive_behavior_requires_all_active_fields_and_a_nonzero_count():
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": True,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
        **{field: 0 for field in COUNT_FIELDS},
        "nssi_medical_care_24h": False,
    }
    flow = build_flow(answers, intervention_day=6)
    answered = {question.id for question in flow}

    assert validate_submission(answers, answered, intervention_day=6) == [
        "至少记录一类 NSSI 行为的实际次数"
    ]

    missing = next(question for question in flow if question.id == COUNT_FIELDS[0])
    assert validate_submission(answers, answered - {missing.id}, intervention_day=6) == [
        f"未完成：{missing.prompt}",
        "至少记录一类 NSSI 行为的实际次数",
    ]


def test_weekly_questions_are_appended_only_when_due():
    weekly_ids = [
        question.id
        for instrument in WEEKLY_INSTRUMENTS
        for question in instrument.questions
    ]

    assert [question.id for question in build_flow(_negative_daily_answers(), 7)][
        -len(weekly_ids) :
    ] == weekly_ids
    assert not set(weekly_ids) & {
        question.id for question in build_flow(_negative_daily_answers(), 6)
    }


def test_formal_validation_requires_every_active_question_and_skips_inactive_branches():
    answers = {
        "nssi_ideation_6m_present": False,
        "nssi_ideation_1m_present": False,
    }
    flow = formal_flow("V1", answers)
    ids = {question.id for question in flow}
    assert "nssi_ideation_6m_frequency" not in ids
    assert "nssi_ideation_6m_intensity" not in ids
    assert "nssi_ideation_1m_frequency" not in ids
    assert "nssi_ideation_1m_intensity" not in ids

    for question in flow:
        answers.setdefault(
            question.id,
            question.min_value if question.kind == "slider" else False,
        )
    assert validate_formal_submission("V1", answers, ids) == []

    missing = flow[0]
    assert validate_formal_submission("V1", answers, ids - {missing.id}) == [
        f"未完成：{missing.prompt}"
    ]


def test_formal_flow_preserves_visit_and_instrument_order():
    expected = [
        question.id
        for instrument_id in VISIT_INSTRUMENT_IDS["V4"]
        for question in FORMAL_INSTRUMENTS[instrument_id].questions
        if question.show_if is None
    ]
    actual = [question.id for question in formal_flow("V4", {})]
    assert actual == expected


def test_field_status_distinguishes_answered_missing_and_not_applicable():
    answers = _negative_daily_answers()
    statuses = build_field_status(
        answers, {"nssi_thought_present_24h"}, intervention_day=6
    )
    assert statuses["nssi_thought_present_24h"] == "answered"
    assert statuses["nssi_urge_now"] == "missing"
    assert statuses["nssi_cut_count_24h"] == "not_applicable"
    assert set(statuses.values()) == {"answered", "missing", "not_applicable"}

    formal_answers = {
        "nssi_ideation_6m_present": False,
        "nssi_ideation_1m_present": False,
    }
    formal_statuses = build_formal_field_status(
        "V1", formal_answers, set(formal_answers)
    )
    assert formal_statuses["nssi_ideation_6m_present"] == "answered"
    assert formal_statuses["nssi_ideation_6m_frequency"] == "not_applicable"
    assert formal_statuses["dshi_lifetime_1"] == "missing"
    assert set(formal_statuses.values()) == {
        "answered",
        "missing",
        "not_applicable",
    }


def test_questionnaire_progress_markup_is_escaped_and_accessible():
    markup = questionnaire_ui.questionnaire_progress_markup(
        '<img src=x onerror="bad()">',
        current=3,
        total=8,
    )

    assert "<img" not in markup
    assert "&lt;img src=x onerror=&quot;bad()&quot;&gt;" in markup
    assert 'class="questionnaire-progress"' in markup
    assert 'role="progressbar"' in markup
    assert 'aria-valuemin="1"' in markup
    assert 'aria-valuemax="8"' in markup
    assert 'aria-valuenow="3"' in markup
    assert 'style="width: 37.5%"' in markup
    assert "03" in markup
    assert "08" in markup


@pytest.mark.parametrize(
    ("current", "total"),
    ((0, 1), (2, 1), (1, 0), (-1, 3), (True, 3), (1, False)),
)
def test_questionnaire_progress_markup_rejects_invalid_bounds(current, total):
    with pytest.raises(ValueError):
        questionnaire_ui.questionnaire_progress_markup(
            "context", current=current, total=total
        )


def test_question_context_renders_only_the_validated_progress_markup(monkeypatch):
    rendered = []
    monkeypatch.setattr(
        "questionnaire_ui.st.markdown",
        lambda body, **kwargs: rendered.append((body, kwargs)),
    )

    render_question_context("过去 24 小时", current=1, total=5)

    assert rendered == [
        (
            questionnaire_ui.questionnaire_progress_markup(
                "过去 24 小时", current=1, total=5
            ),
            {"unsafe_allow_html": True},
        )
    ]


def test_questionnaire_source_has_no_competing_global_shell():
    source = (
        Path(__file__).resolve().parents[1] / "questionnaire_ui.py"
    ).read_text(encoding="utf-8")

    for token in (
        "ALTO_CSS",
        "ALTO_COLORS",
        "YMH",
        "NEUROSCIENCE LAB",
        "alto-top",
        "alto-progress",
    ):
        assert token not in source


def test_question_context_uses_current_question_time_window():
    assert question_context_label(DAILY_CORE[0], "daily") == "过去 24 小时"
    assert question_context_label(DAILY_CORE[3], "daily") == "此时此刻"

    weekly = WEEKLY_INSTRUMENTS[0]
    assert question_context_label(weekly.questions[0], "daily") == (
        f"{weekly.label} · {weekly.time_window}"
    )

    formal = FORMAL_INSTRUMENTS["dshi_lifetime"]
    assert question_context_label(formal.questions[0], "V1") == (
        f"{formal.label} · {formal.time_window}"
    )


def test_slider_endpoint_labels_are_html_escaped(monkeypatch):
    rendered = []
    monkeypatch.setattr("questionnaire_ui.st.slider", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        "questionnaire_ui.st.markdown",
        lambda body, **kwargs: rendered.append(body),
    )
    question = QuestionSpec(
        "unsafe_slider",
        "A safe native label",
        "slider",
        min_value=0,
        max_value=10,
        low_label="<img src=x onerror=bad()>",
        high_label="<script>bad()</script>",
    )

    assert render_question(question, _fixture_keys()) == 0
    body = "".join(rendered)
    assert "<script>" not in body
    assert "<img" not in body
    assert "&lt;script&gt;" in body
    assert "&lt;img" in body
    assert 'class="questionnaire-endpoints"' in body
    assert "alto-endpoints" not in body


def test_participant_fixture_hides_score_and_risk_labels():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10).run()
    assert not app.exception
    visible = str(app)
    assert "总分" not in visible
    assert "高风险" not in visible


def test_daily_now_and_weekly_steps_render_accurate_context_titles():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_day"] = 7
    app.session_state["fixture_answers"] = _negative_daily_answers()
    app.session_state["fixture_initial_step"] = 3
    app = app.run()
    markup = "\n".join(item.value for item in app.markdown)
    total = len(build_flow(_negative_daily_answers(), 7))
    assert "此时此刻" in markup
    assert "过去 24 小时" not in markup
    assert f'>04 <span>/ {total:02d}</span>' in markup

    app.session_state[_fixture_keys().step] = 5
    app = app.run()
    weekly = WEEKLY_INSTRUMENTS[0]
    markup = "\n".join(item.value for item in app.markdown)
    assert f"{weekly.label} · {weekly.time_window}" in markup
    assert f'>06 <span>/ {total:02d}</span>' in markup


def test_formal_first_item_renders_instrument_context_and_crf_endpoints():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_visit"] = "V1"
    app = app.run()
    markup = "\n".join(item.value for item in app.markdown)
    formal = FORMAL_INSTRUMENTS["dshi_lifetime"]
    total = len(formal_flow("V1", {}))

    assert f"{formal.label} · {formal.time_window}" in markup
    assert f'>01 <span>/ {total:02d}</span>' in markup
    assert "过去 24 小时" not in markup
    assert "1 我从未这样做过" in markup
    assert "5 做过超过10次" in markup


def test_required_boolean_must_be_actively_answered_before_continuing():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10).run()
    assert app.radio[0].value is None

    app = _button(app, "继续").click().run()
    assert [error.value for error in app.error] == ["请先确认当前答案。"]
    assert app.session_state[_fixture_keys().step] == 0


def test_untouched_slider_cannot_continue_from_its_default_position():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10).run()
    for _ in range(3):
        app = _answer_no_and_continue(app)

    assert app.slider[0].value == DAILY_CORE[3].min_value
    app = _button(app, "继续").click().run()
    assert [error.value for error in app.error] == ["请先确认当前答案。"]
    assert DAILY_CORE[3].id not in set(app.session_state[_fixture_keys().answered])


def test_boolean_branch_rebuilds_steps_and_navigation_saves_drafts():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10).run()
    app.radio[0].set_value(True).run()
    app = _button(app, "继续").click().run()
    assert app.slider[0].label == DAILY_CONDITIONAL[0].prompt
    save_calls = app.session_state["fixture_save_calls"]

    app = _button(app, "←").click().run()
    assert app.radio[0].label == DAILY_CORE[0].prompt
    assert app.session_state["fixture_save_calls"] == save_calls + 1

    app.radio[0].set_value(False).run()
    app = _button(app, "继续").click().run()
    assert app.radio[0].label == DAILY_CORE[1].prompt
    assert app.session_state[_fixture_keys().step] == 1


def test_questionnaire_state_keys_isolate_namespace_and_visit():
    a_daily = questionnaire_state_keys("record-A", "daily")
    a_formal = questionnaire_state_keys("record-A", "V1")
    b_daily = questionnaire_state_keys("record-B", "daily")

    assert isinstance(a_daily, QuestionnaireStateKeys)
    for attribute in (
        "answered",
        "values",
        "step",
        "error",
        "back_button",
        "next_button",
    ):
        assert len(
            {
                getattr(a_daily, attribute),
                getattr(a_formal, attribute),
                getattr(b_daily, attribute),
            }
        ) == 3
    assert len(
        {
            a_daily.widget("nssi_impulse_time"),
            a_formal.widget("nssi_impulse_time"),
            b_daily.widget("nssi_impulse_time"),
        }
    ) == 3


def test_daily_and_formal_shared_field_ids_do_not_share_widget_or_answered_state():
    daily_answers = _negative_daily_answers()
    daily_answers["nssi_impulse_time"] = 88
    daily_flow = build_flow(daily_answers, 7)
    daily_step = next(
        index
        for index, question in enumerate(daily_flow)
        if question.id == "nssi_impulse_time"
    )
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_answers"] = daily_answers
    app.session_state["fixture_initial_answered"] = ["nssi_impulse_time"]
    app.session_state["fixture_initial_step"] = daily_step
    app = app.run()
    assert app.slider[0].value == 88

    formal_step = next(
        index
        for index, question in enumerate(formal_flow("V1", {}))
        if question.id == "nssi_impulse_time"
    )
    app.session_state["fixture_visit"] = "V1"
    app.session_state["fixture_answers"] = {}
    app.session_state["fixture_initial_answered"] = []
    app.session_state["fixture_initial_step"] = formal_step
    app = app.run()

    assert app.slider[0].value == 1
    assert "nssi_impulse_time" not in set(
        app.session_state[_fixture_keys("V1").answered]
    )
    assert app.session_state[_fixture_keys().values]["nssi_impulse_time"] == 88


def test_record_namespace_switches_restore_only_their_own_state():
    answers_a = {
        **_negative_daily_answers(),
        "nssi_urge_now": 7,
    }
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_namespace"] = "record-A"
    app.session_state["fixture_day"] = 6
    app.session_state["fixture_answers"] = answers_a
    app.session_state["fixture_initial_answered"] = [
        "nssi_thought_present_24h",
        "nssi_behavior_present_24h",
        "suicide_thought_present_24h",
        "nssi_urge_now",
    ]
    app.session_state["fixture_initial_step"] = 3
    app = app.run()
    assert app.slider[0].value == 7

    app.session_state["fixture_namespace"] = "record-B"
    app.session_state["fixture_answers"] = {}
    app.session_state["fixture_initial_answered"] = []
    app.session_state["fixture_initial_step"] = 0
    app = app.run()
    assert app.radio[0].value is None
    assert app.session_state[_fixture_keys(namespace="record-B").step] == 0

    app.session_state["fixture_namespace"] = "record-A"
    app.session_state["fixture_answers"] = {}
    app = app.run()
    keys_a = _fixture_keys(namespace="record-A")
    assert app.slider[0].value == 7
    assert app.session_state[keys_a.step] == 3
    assert "nssi_urge_now" in set(app.session_state[keys_a.answered])


def test_unanswered_preloaded_controller_restores_its_conditional_flow():
    keys_a = _fixture_keys(namespace="record-A")
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_namespace"] = "record-A"
    app.session_state["fixture_day"] = 6
    app.session_state["fixture_answers"] = {
        "nssi_thought_present_24h": True,
    }
    app.session_state["fixture_initial_answered"] = []
    app.session_state["fixture_initial_step"] = 1
    app = app.run()

    assert app.slider[0].label == DAILY_CONDITIONAL[0].prompt
    assert app.session_state[keys_a.step] == 1
    assert not app.session_state[keys_a.answered]
    assert DAILY_CONDITIONAL[0].id not in app.session_state[keys_a.values]
    markup = "\n".join(item.value for item in app.markdown)
    assert '>02 <span>/ 07</span>' in markup

    app.session_state["fixture_namespace"] = "record-B"
    app.session_state["fixture_answers"] = {}
    app.session_state["fixture_initial_step"] = 0
    app = app.run()
    assert app.radio[0].value is None

    app.session_state["fixture_namespace"] = "record-A"
    app.session_state["fixture_answers"] = {}
    app = app.run()
    assert app.slider[0].label == DAILY_CONDITIONAL[0].prompt
    assert app.session_state[keys_a.step] == 1
    assert app.session_state[keys_a.values] == {
        "nssi_thought_present_24h": True
    }
    markup = "\n".join(item.value for item in app.markdown)
    assert '>02 <span>/ 07</span>' in markup

    app = _button(app, "←").click().run()
    assert app.radio[0].value is True
    app = _button(app, "继续").click().run()
    assert [error.value for error in app.error] == ["请先确认当前答案。"]
    assert app.session_state[keys_a.step] == 0
    assert "nssi_thought_present_24h" not in set(
        app.session_state[keys_a.answered]
    )


def test_saved_answers_restore_widget_but_only_initial_ids_count_as_answered():
    answers = {**_negative_daily_answers(), "nssi_urge_now": 5}
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_day"] = 6
    app.session_state["fixture_answers"] = answers
    app.session_state["fixture_initial_answered"] = list(_negative_daily_answers())
    app.session_state["fixture_initial_step"] = 3
    app = app.run()

    keys = _fixture_keys()
    assert app.slider[0].value == 5
    assert app.session_state[keys.step] == 3
    assert "nssi_urge_now" not in set(app.session_state[keys.answered])
    app = _button(app, "继续").click().run()
    assert [error.value for error in app.error] == ["请先确认当前答案。"]


def test_initial_answered_ids_require_a_scoped_value_before_branch_activation():
    controller_id = "nssi_thought_present_24h"
    hidden_id = "nssi_thought_frequency_24h"
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_day"] = 6
    app.session_state["fixture_answers"] = {controller_id: False}
    app.session_state["fixture_initial_answered"] = [controller_id, hidden_id]
    app = app.run()
    keys = _fixture_keys()

    assert app.radio[0].value is False
    assert controller_id in set(app.session_state[keys.answered])
    assert hidden_id not in set(app.session_state[keys.answered])

    app.radio[0].set_value(True).run()
    app = _button(app, "继续").click().run()
    assert app.slider[0].label == DAILY_CONDITIONAL[0].prompt
    assert app.slider[0].value == 0
    assert hidden_id not in set(app.session_state[keys.answered])
    app = _button(app, "继续").click().run()
    assert [error.value for error in app.error] == ["请先确认当前答案。"]
    assert app.session_state[keys.step] == 1


def test_daily_callback_is_active_only_while_hidden_branch_answers_restore():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_day"] = 6
    app = app.run()
    app.radio[0].set_value(True).run()
    app = _button(app, "继续").click().run()
    app.slider[0].set_value(2).run()
    app = _button(app, "继续").click().run()
    app.slider[0].set_value(3).run()

    app = _button(app, "←").click().run()
    app = _button(app, "←").click().run()
    app.radio[0].set_value(False).run()
    app = _button(app, "继续").click().run()

    hidden_ids = {
        "nssi_thought_frequency_24h",
        "nssi_thought_intensity_24h",
    }
    saved_answers = dict(app.session_state["fixture_answers"])
    saved_answered = set(app.session_state["fixture_answered"])
    assert hidden_ids.isdisjoint(saved_answers)
    assert hidden_ids.isdisjoint(saved_answered)
    assert hidden_ids.isdisjoint(app.session_state["fixture_rendered_answers"])
    statuses = build_field_status(saved_answers, saved_answered, 6)
    assert {statuses[field_id] for field_id in hidden_ids} == {"not_applicable"}

    app = _button(app, "←").click().run()
    app.radio[0].set_value(True).run()
    app = _button(app, "继续").click().run()
    assert app.slider[0].label == DAILY_CONDITIONAL[0].prompt
    assert app.slider[0].value == 2
    app = _button(app, "继续").click().run()
    assert not app.error
    assert app.slider[0].label == DAILY_CONDITIONAL[1].prompt
    assert app.slider[0].value == 3


def test_formal_callback_excludes_inactive_conditional_values_and_answered_ids():
    controller_id = "nssi_ideation_6m_present"
    hidden_ids = {
        "nssi_ideation_6m_frequency",
        "nssi_ideation_6m_intensity",
    }
    answers = {
        controller_id: False,
        "nssi_ideation_6m_frequency": 4,
        "nssi_ideation_6m_intensity": 3,
    }
    flow = formal_flow("V1", answers)
    controller_step = next(
        index for index, question in enumerate(flow) if question.id == controller_id
    )
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_visit"] = "V1"
    app.session_state["fixture_answers"] = answers
    app.session_state["fixture_initial_answered"] = [controller_id, *hidden_ids]
    app.session_state["fixture_initial_step"] = controller_step
    app = app.run()
    app = _button(app, "继续").click().run()

    saved_answers = dict(app.session_state["fixture_answers"])
    saved_answered = set(app.session_state["fixture_answered"])
    assert hidden_ids.isdisjoint(saved_answers)
    assert hidden_ids.isdisjoint(saved_answered)
    assert hidden_ids.isdisjoint(app.session_state["fixture_rendered_answers"])
    statuses = build_formal_field_status("V1", saved_answers, saved_answered)
    assert {statuses[field_id] for field_id in hidden_ids} == {"not_applicable"}


def test_pending_errors_are_scoped_to_record_namespace():
    keys_a = _fixture_keys(namespace="record-A")
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_namespace"] = "record-B"
    app.session_state[keys_a.error] = ["record-A only"]
    app = app.run()
    assert not app.error
    assert app.session_state[keys_a.error] == ["record-A only"]

    app.session_state["fixture_namespace"] = "record-A"
    app = app.run()
    assert [error.value for error in app.error] == ["record-A only"]


def test_save_failure_on_forward_rolls_back_step_and_hides_technical_error():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10).run()
    app.radio[0].set_value(False).run()
    app.session_state["fixture_fail_save"] = True
    app = _button(app, "继续").click().run()

    assert not app.exception
    assert app.session_state[_fixture_keys().step] == 0
    assert [error.value for error in app.error] == ["暂时无法保存，请重试。"]
    assert "sensitive backend detail" not in str(app)


def test_save_failure_on_back_rolls_back_step():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_day"] = 6
    app.session_state["fixture_answers"] = {
        "nssi_thought_present_24h": False,
    }
    app.session_state["fixture_initial_answered"] = [
        "nssi_thought_present_24h"
    ]
    app.session_state["fixture_initial_step"] = 1
    app.session_state["fixture_fail_save"] = True
    app = app.run()
    app = _button(app, "←").click().run()

    assert not app.exception
    assert app.session_state[_fixture_keys().step] == 1
    assert [error.value for error in app.error] == ["暂时无法保存，请重试。"]


def test_save_failure_on_final_submission_keeps_final_step():
    answers = {
        **_negative_daily_answers(),
        "nssi_urge_now": 1,
        "nssi_resistance_confidence_now": 7,
    }
    answered = [question.id for question in build_flow(answers, 6)]
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_day"] = 6
    app.session_state["fixture_answers"] = answers
    app.session_state["fixture_initial_answered"] = answered
    app.session_state["fixture_initial_step"] = 4
    app.session_state["fixture_fail_save"] = True
    app = app.run()
    app = _button(app, "检查并提交").click().run()

    assert not app.exception
    assert app.session_state[_fixture_keys().step] == 4
    assert [error.value for error in app.error] == ["暂时无法保存，请重试。"]


def test_second_save_failure_during_missing_relocation_restores_final_step():
    answers = {
        **_negative_daily_answers(),
        "nssi_urge_now": 1,
        "nssi_resistance_confidence_now": 7,
    }
    flow = build_flow(answers, 6)
    answered = [
        question.id
        for question in flow
        if question.id != "nssi_thought_present_24h"
    ]
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_day"] = 6
    app.session_state["fixture_answers"] = answers
    app.session_state["fixture_initial_answered"] = answered
    app.session_state["fixture_initial_step"] = len(flow) - 1
    app.session_state["fixture_fail_on_save_attempt"] = 2
    app = app.run()
    app = _button(app, "检查并提交").click().run()

    assert not app.exception
    assert app.session_state[_fixture_keys().step] == len(flow) - 1
    assert app.session_state["fixture_save_attempts"] == 2
    assert app.session_state["fixture_save_calls"] == 1
    assert [error.value for error in app.error] == ["暂时无法保存，请重试。"]


def test_zero_behavior_counts_relocate_to_first_count_with_error_visible():
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": True,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
        **{field: 0 for field in COUNT_FIELDS},
        "nssi_medical_care_24h": False,
    }
    flow = build_flow(answers, 6)
    answered = [question.id for question in flow if question.required]
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.session_state["fixture_day"] = 6
    app.session_state["fixture_answers"] = answers
    app.session_state["fixture_initial_answered"] = answered
    app.session_state["fixture_initial_step"] = len(flow) - 1
    app = app.run()
    app = _button(app, "检查并提交").click().run()

    first_count = next(
        question for question in flow if question.id == COUNT_FIELDS[0]
    )
    assert not app.exception
    assert app.number_input[0].label == first_count.prompt
    assert app.session_state[_fixture_keys().step] == flow.index(first_count)
    assert [error.value for error in app.error] == [
        "至少记录一类 NSSI 行为的实际次数"
    ]
    assert app.session_state["fixture_saved_step"] == flow.index(first_count)
