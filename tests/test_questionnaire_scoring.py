import pytest

from questionnaire_scoring import (
    COUNT_FIELDS,
    ScoreResult,
    daily_derived_metrics,
    score_formal_instrument,
    score_sicq,
)


def test_score_sicq_reverses_final_item_and_scores_boundaries():
    assert score_sicq([0, 0, 0, 0, 0, 0, 4]) == ScoreResult(
        total=0,
        complete=True,
        scored_items=(0, 0, 0, 0, 0, 0, 0),
    )

    result = score_sicq([4, 4, 4, 4, 4, 4, 0])

    assert result.total == 28
    assert result.scored_items[-1] == 4


def test_score_sicq_missing_item_suppresses_total_and_retains_item():
    assert score_sicq([0, 1, 2, None, 3, 4, 4]) == ScoreResult(
        total=None,
        complete=False,
        scored_items=(0, 1, 2, None, 3, 4, 0),
    )


def test_score_sicq_requires_exactly_seven_items():
    with pytest.raises(ValueError, match="SICQ requires exactly 7 items"):
        score_sicq([0] * 6)


def test_daily_metrics_keep_counts_and_safety_signals_separate():
    answers = {
        "nssi_behavior_present_24h": True,
        "nssi_cut_count_24h": 2,
        "nssi_burn_count_24h": 0,
        "nssi_scratch_count_24h": 1,
        "nssi_bite_count_24h": 0,
        "nssi_hit_object_count_24h": 0,
        "nssi_hit_self_count_24h": 0,
        "nssi_other_count_24h": 1,
        "suicide_thought_present_24h": True,
    }

    metrics = daily_derived_metrics(answers)

    assert COUNT_FIELDS == (
        "nssi_cut_count_24h",
        "nssi_burn_count_24h",
        "nssi_scratch_count_24h",
        "nssi_bite_count_24h",
        "nssi_hit_object_count_24h",
        "nssi_hit_self_count_24h",
        "nssi_other_count_24h",
    )
    assert metrics["nssi_total_count_24h"] == 4
    assert metrics["nssi_any_24h"] is True
    assert metrics["suicide_thought_present_24h"] is True


def test_daily_metrics_discard_stale_counts_when_behavior_absent():
    answers = {"nssi_behavior_present_24h": False}
    answers.update({field: 9 for field in COUNT_FIELDS})

    metrics = daily_derived_metrics(answers)

    assert metrics["nssi_any_24h"] is False
    assert metrics["nssi_total_count_24h"] == 0


def test_score_formal_instrument_sums_dshi_12m():
    answers = {f"dshi_12m_{index}": 1 for index in range(1, 7)}

    assert score_formal_instrument("dshi_12m", answers) == {
        "total": 6,
        "complete": True,
    }


def test_score_formal_instrument_keeps_readiness_items_separate():
    result = score_formal_instrument(
        "readiness",
        {"readiness_1": 4, "readiness_2": 5, "readiness_3": 6},
    )

    assert result == {
        "importance": 4,
        "ready": 5,
        "confidence": 6,
        "complete": True,
    }
    assert "total" not in result


def test_score_formal_instrument_scores_fasm_subscales_and_missing_values():
    answers = {f"fasm_{index}": index for index in range(1, 16)}

    assert score_formal_instrument("fasm", answers) == {
        "total": 120,
        "emotion": 41,
        "attention": 55,
        "avoidance": 24,
        "complete": True,
    }

    answers["fasm_4"] = None
    assert score_formal_instrument("fasm", answers) == {
        "total": None,
        "emotion": None,
        "attention": None,
        "avoidance": None,
        "complete": False,
    }


def test_score_formal_instrument_normalizes_pss_booleans_and_rejects_undefined_rules():
    assert score_formal_instrument(
        "pss",
        {"pss_1": True, "pss_2": False, "pss_3": 1, "pss_4": 0, "pss_5": True},
    ) == {"total": 3, "complete": True}

    with pytest.raises(KeyError, match="No aggregate scoring rule for nssi_ideation"):
        score_formal_instrument("nssi_ideation", {})
