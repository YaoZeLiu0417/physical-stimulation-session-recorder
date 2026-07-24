import pytest

from questionnaire_specs import (
    DAILY_CORE,
    FASM_MOTIVES,
    WEEKLY_INSTRUMENTS,
    active_daily_question_ids,
    weekly_due,
)


def test_daily_core_ids_and_required_fields():
    assert [question.id for question in DAILY_CORE] == [
        "nssi_thought_present_24h",
        "nssi_behavior_present_24h",
        "suicide_thought_present_24h",
        "nssi_urge_now",
        "nssi_resistance_confidence_now",
    ]
    assert all(question.required for question in DAILY_CORE)


@pytest.mark.parametrize(
    ("answers", "expected_ids"),
    [
        ({}, [
            "nssi_thought_present_24h",
            "nssi_behavior_present_24h",
            "suicide_thought_present_24h",
            "nssi_urge_now",
            "nssi_resistance_confidence_now",
        ]),
        ({"nssi_thought_present_24h": True}, [
            "nssi_thought_present_24h",
            "nssi_behavior_present_24h",
            "suicide_thought_present_24h",
            "nssi_urge_now",
            "nssi_resistance_confidence_now",
            "nssi_thought_frequency_24h",
            "nssi_thought_intensity_24h",
        ]),
        ({"nssi_behavior_present_24h": True}, [
            "nssi_thought_present_24h",
            "nssi_behavior_present_24h",
            "suicide_thought_present_24h",
            "nssi_urge_now",
            "nssi_resistance_confidence_now",
            "nssi_cut_count_24h",
            "nssi_burn_count_24h",
            "nssi_scratch_count_24h",
            "nssi_bite_count_24h",
            "nssi_hit_object_count_24h",
            "nssi_hit_self_count_24h",
            "nssi_other_description_24h",
            "nssi_other_count_24h",
            "nssi_medical_care_24h",
            "nssi_motives_24h",
            "nssi_trigger_24h",
            "nssi_coping_24h",
        ]),
        ({"suicide_thought_present_24h": True}, [
            "nssi_thought_present_24h",
            "nssi_behavior_present_24h",
            "suicide_thought_present_24h",
            "nssi_urge_now",
            "nssi_resistance_confidence_now",
            "suicide_thought_frequency_24h",
        ]),
    ],
)
def test_active_daily_questions_follow_each_controller(answers, expected_ids):
    assert active_daily_question_ids(answers) == tuple(expected_ids)


def test_weekly_due_only_on_scheduled_intervention_days():
    assert [day for day in range(1, 29) if weekly_due(day)] == [7, 14, 21, 28]


def test_weekly_instruments_have_expected_item_counts_and_motives():
    assert {instrument.id: len(instrument.questions) for instrument in WEEKLY_INSTRUMENTS} == {
        "nssi_impulse_weekly": 2,
        "nssi_future_weekly": 1,
        "nssi_stop_weekly": 1,
        "sicq_weekly": 7,
        "readiness_weekly": 3,
    }
    assert len(FASM_MOTIVES) == 15
