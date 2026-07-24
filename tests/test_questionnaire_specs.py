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
    full = (
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
    )
    follow_up = tuple(instrument_id for instrument_id in full if instrument_id != "fasm")

    assert questionnaire_specs.VISIT_INSTRUMENT_IDS == {
        "V1": full,
        "V3": full,
        "V4": follow_up,
        "V5": follow_up,
        "V6": full,
    }


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


def test_formal_nssi_impulse_prompts_are_exact_and_ordered():
    impulse = questionnaire_specs.FORMAL_INSTRUMENTS["nssi_impulse"]

    assert [question.prompt for question in impulse.questions] == [
        "过去一周里，你多长时间想过伤害自己？",
        "过去一周里，抵制伤害自己有多难？",
    ]


def test_formal_question_ids_are_exact_ordered_and_unique():
    assert {
        instrument_id: tuple(question.id for question in instrument.questions)
        for instrument_id, instrument in questionnaire_specs.FORMAL_INSTRUMENTS.items()
    } == {
        "dshi_lifetime": tuple(f"dshi_lifetime_{index}" for index in range(1, 7)),
        "dshi_12m": tuple(f"dshi_12m_{index}" for index in range(1, 7)),
        "fasm": tuple(f"fasm_{index}" for index in range(1, 16)),
        "nssi_ideation": (
            "nssi_ideation_6m_present",
            "nssi_ideation_6m_frequency",
            "nssi_ideation_6m_intensity",
            "nssi_ideation_1m_present",
            "nssi_ideation_1m_frequency",
            "nssi_ideation_1m_intensity",
        ),
        "nssi_impulse": ("nssi_impulse_time", "nssi_impulse_resistance"),
        "nssi_future": ("nssi_future_likelihood",),
        "nssi_stop": ("nssi_stop_desire",),
        "sicq": tuple(f"sicq_{index}" for index in range(1, 8)),
        "readiness": tuple(f"readiness_{index}" for index in range(1, 4)),
        "siss": tuple(f"siss_{index}" for index in range(1, 14)),
        "pss": tuple(f"pss_{index}" for index in range(1, 6)),
    }
    ids = tuple(
        question.id
        for instrument in questionnaire_specs.FORMAL_INSTRUMENTS.values()
        for question in instrument.questions
    )
    assert len(ids) == len(set(ids))
