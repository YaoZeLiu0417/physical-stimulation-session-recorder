import pytest

import questionnaire_specs

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


def test_formal_instruments_have_expected_keys():
    assert set(questionnaire_specs.FORMAL_INSTRUMENTS) == {
        "dshi_lifetime",
        "dshi_12m",
        "fasm",
        "nssi_ideation",
        "nssi_impulse",
        "nssi_future",
        "nssi_stop",
        "sicq",
        "readiness",
        "siss",
        "pss",
    }


def test_formal_visit_mapping_matches_schedule_rules():
    visits = questionnaire_specs.VISIT_INSTRUMENT_IDS

    assert "fasm" in visits["V1"]
    assert "fasm" in visits["V3"]
    assert "fasm" not in visits["V4"]
    assert visits["V5"] == visits["V4"]
    assert "fasm" in visits["V6"]
    assert "dshi_12m" in visits["V5"]


def test_formal_instruments_have_expected_question_counts():
    assert {
        instrument_id: len(instrument.questions)
        for instrument_id, instrument in questionnaire_specs.FORMAL_INSTRUMENTS.items()
    } == {
        "dshi_lifetime": 6,
        "dshi_12m": 6,
        "fasm": 15,
        "nssi_ideation": 6,
        "nssi_impulse": 2,
        "nssi_future": 1,
        "nssi_stop": 1,
        "sicq": 7,
        "readiness": 3,
        "siss": 13,
        "pss": 5,
    }


def test_formal_instrument_mapping_keys_match_instrument_ids():
    assert all(
        instrument_id == instrument.id
        for instrument_id, instrument in questionnaire_specs.FORMAL_INSTRUMENTS.items()
    )
