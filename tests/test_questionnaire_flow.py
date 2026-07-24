from pathlib import Path

from streamlit.testing.v1 import AppTest

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
    ALTO_COLORS,
    ALTO_CSS,
    build_field_status,
    build_formal_field_status,
    build_flow,
    formal_flow,
    inject_alto_theme,
    render_question,
    validate_formal_submission,
    validate_submission,
)


FIXTURE = Path(__file__).parent / "fixtures" / "questionnaire_app.py"


def _negative_daily_answers():
    return {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
    }


def _button(app, label):
    return next(button for button in app.button if button.label == label)


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


def test_alto_palette_and_css_follow_visual_constraints():
    assert ALTO_COLORS == {
        "black": "#050505",
        "purple": "#2D2674",
        "blue": "#33B0E4",
        "magenta": "#DD1D86",
        "orange": "#FF8D2A",
    }
    assert all(color in ALTO_CSS for color in ALTO_COLORS.values())
    assert "gradient" not in ALTO_CSS.lower()
    assert "letter-spacing: 0" in ALTO_CSS
    assert "overflow-wrap: anywhere" in ALTO_CSS
    assert "vw" not in ALTO_CSS.lower()


def test_unsafe_header_values_are_html_escaped(monkeypatch):
    rendered = []

    def capture(body, **kwargs):
        rendered.append((body, kwargs))

    monkeypatch.setattr("questionnaire_ui.st.markdown", capture)
    inject_alto_theme('<script id="subject">bad()</script>', 7, 1, 5)

    body = "".join(item[0] for item in rendered)
    assert '<script id="subject">' not in body
    assert "&lt;script id=&quot;subject&quot;&gt;" in body
    assert all(item[1].get("unsafe_allow_html") for item in rendered)


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

    assert render_question(question) == 0
    body = "".join(rendered)
    assert "<script>" not in body
    assert "<img" not in body
    assert "&lt;script&gt;" in body
    assert "&lt;img" in body


def test_participant_fixture_hides_score_and_risk_labels():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10).run()
    assert not app.exception
    visible = str(app)
    assert "总分" not in visible
    assert "高风险" not in visible


def test_required_boolean_must_be_actively_answered_before_continuing():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10).run()
    assert app.radio[0].value is None

    app = _button(app, "继续").click().run()
    assert [error.value for error in app.error] == ["请先确认当前答案。"]
    assert app.session_state["question_step_daily"] == 0


def test_untouched_slider_cannot_continue_from_its_default_position():
    app = AppTest.from_file(str(FIXTURE), default_timeout=10).run()
    for _ in range(3):
        app = _answer_no_and_continue(app)

    assert app.slider[0].value == DAILY_CORE[3].min_value
    app = _button(app, "继续").click().run()
    assert [error.value for error in app.error] == ["请先确认当前答案。"]
    assert DAILY_CORE[3].id not in set(app.session_state["answered_field_ids"])


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
    assert app.session_state["question_step_daily"] == 1
