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


@pytest.mark.parametrize("value", [True, "2"])
def test_score_sicq_rejects_non_integer_scale_values(value):
    with pytest.raises(TypeError, match="SICQ.*integer"):
        score_sicq([0, 0, 0, 0, 0, 0, value])


def test_score_sicq_rejects_out_of_range_scale_values():
    with pytest.raises(ValueError, match="SICQ.*0.*4"):
        score_sicq([0, 0, 0, 0, 0, 0, 5])


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


def test_daily_metrics_keep_missing_behavior_controller_and_total_missing():
    metrics = daily_derived_metrics({})
    assert metrics["nssi_any_24h"] is None
    assert metrics["nssi_total_count_24h"] is None


def test_daily_metrics_discard_stale_counts_when_behavior_explicitly_absent():
    answers = {"nssi_behavior_present_24h": False}
    answers.update({field: 9 for field in COUNT_FIELDS})
    metrics = daily_derived_metrics(answers)
    assert metrics["nssi_any_24h"] is False
    assert metrics["nssi_total_count_24h"] == 0


@pytest.mark.parametrize("missing_count", ["nssi_scratch_count_24h", None])
def test_daily_metrics_keep_total_missing_when_behavior_counts_are_partial(
    missing_count,
):
    answers = {"nssi_behavior_present_24h": True}
    answers.update({field: 0 for field in COUNT_FIELDS})
    if missing_count is None:
        answers.pop("nssi_scratch_count_24h")
    else:
        answers[missing_count] = None
    metrics = daily_derived_metrics(answers)
    assert metrics["nssi_any_24h"] is True
    assert metrics["nssi_total_count_24h"] is None


def test_daily_metrics_sum_complete_zero_counts_normally():
    answers = {"nssi_behavior_present_24h": True}
    answers.update({field: 0 for field in COUNT_FIELDS})
    metrics = daily_derived_metrics(answers)
    assert metrics["nssi_any_24h"] is True
    assert metrics["nssi_total_count_24h"] == 0


@pytest.mark.parametrize("controller", [1, "yes"])
def test_daily_metrics_reject_non_boolean_behavior_controller(controller):
    with pytest.raises(TypeError, match="nssi_behavior_present_24h.*boolean"):
        daily_derived_metrics({"nssi_behavior_present_24h": controller})


@pytest.mark.parametrize(
    ("value", "exception"),
    [(True, TypeError), ("1", TypeError), (-1, ValueError)],
)
def test_daily_metrics_validate_present_behavior_counts(value, exception):
    answers = {"nssi_behavior_present_24h": True}
    answers.update({field: 0 for field in COUNT_FIELDS})
    answers["nssi_cut_count_24h"] = value
    with pytest.raises(exception):
        daily_derived_metrics(answers)


def test_score_formal_instrument_sums_complete_dshi_12m_and_lifetime():
    assert score_formal_instrument(
        "dshi_12m", {f"dshi_12m_{index}": 1 for index in range(1, 7)}
    ) == {"total": 6, "complete": True}
    assert score_formal_instrument(
        "dshi_lifetime", {f"dshi_lifetime_{index}": 5 for index in range(1, 7)}
    ) == {"total": 30, "complete": True}


def test_score_formal_instrument_keeps_incomplete_dshi_total_missing():
    answers = {f"dshi_lifetime_{index}": 1 for index in range(1, 7)}
    answers["dshi_lifetime_3"] = None
    assert score_formal_instrument("dshi_lifetime", answers) == {
        "total": None,
        "complete": False,
    }


@pytest.mark.parametrize(
    ("instrument_id", "answers", "exception"),
    [
        ("dshi_12m", {"dshi_12m_1": 0}, ValueError),
        ("dshi_lifetime", {"dshi_lifetime_1": True}, TypeError),
        ("fasm", {"fasm_1": 4}, ValueError),
        ("readiness", {"readiness_1": 11}, ValueError),
        ("siss", {"siss_1": "3"}, TypeError),
    ],
)
def test_score_formal_instrument_validates_ordinal_scale_values(
    instrument_id, answers, exception
):
    with pytest.raises(exception):
        score_formal_instrument(instrument_id, answers)


def test_score_formal_instrument_keeps_readiness_items_separate():
    result = score_formal_instrument(
        "readiness", {"readiness_1": 4, "readiness_2": 5, "readiness_3": 6}
    )
    assert result == {
        "importance": 4,
        "ready": 5,
        "confidence": 6,
        "complete": True,
    }
    assert "total" not in result


def test_score_formal_instrument_keeps_incomplete_readiness_items_separate():
    assert score_formal_instrument(
        "readiness", {"readiness_1": 4, "readiness_2": None, "readiness_3": 6}
    ) == {
        "importance": 4,
        "ready": None,
        "confidence": 6,
        "complete": False,
    }


def test_score_formal_instrument_scores_fasm_subscales_and_missing_values():
    answers = {f"fasm_{index}": index % 4 for index in range(1, 16)}
    assert score_formal_instrument("fasm", answers) == {
        "total": 24,
        "emotion": 9,
        "attention": 11,
        "avoidance": 4,
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


def test_score_formal_instrument_scores_complete_and_incomplete_siss():
    answers = {f"siss_{index}": 1 for index in range(1, 14)}
    assert score_formal_instrument("siss", answers) == {"total": 13, "complete": True}
    answers["siss_10"] = None
    assert score_formal_instrument("siss", answers) == {
        "total": None,
        "complete": False,
    }


def test_score_formal_instrument_wraps_sicq_result():
    assert score_formal_instrument(
        "sicq", {f"sicq_{index}": 0 for index in range(1, 8)}
    ) == {
        "total": 4,
        "complete": True,
        "scored_items": (0, 0, 0, 0, 0, 0, 4),
    }


def test_score_formal_instrument_scores_pss_booleans_and_keeps_missing_total_empty():
    assert score_formal_instrument(
        "pss",
        {"pss_1": True, "pss_2": False, "pss_3": True, "pss_4": False, "pss_5": True},
    ) == {"total": 3, "complete": True}
    assert score_formal_instrument(
        "pss",
        {"pss_1": True, "pss_2": None, "pss_3": True, "pss_4": False, "pss_5": True},
    ) == {"total": None, "complete": False}


def test_score_formal_instrument_rejects_non_boolean_pss_values():
    with pytest.raises(TypeError, match="PSS.*boolean"):
        score_formal_instrument("pss", {"pss_1": "yes"})


def test_score_formal_instrument_rejects_undefined_aggregate_rule():
    with pytest.raises(KeyError, match="No aggregate scoring rule for nssi_ideation"):
        score_formal_instrument("nssi_ideation", {})
