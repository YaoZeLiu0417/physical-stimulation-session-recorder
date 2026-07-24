"""Pure aggregate scoring for questionnaire responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ScoreResult:
    total: int | None
    complete: bool
    scored_items: tuple[int | None, ...]


COUNT_FIELDS = (
    "nssi_cut_count_24h",
    "nssi_burn_count_24h",
    "nssi_scratch_count_24h",
    "nssi_bite_count_24h",
    "nssi_hit_object_count_24h",
    "nssi_hit_self_count_24h",
    "nssi_other_count_24h",
)


def score_sicq(values: Sequence[int | None]) -> ScoreResult:
    if len(values) != 7:
        raise ValueError("SICQ requires exactly 7 items")

    scored_items = tuple(values[:6]) + (
        None if values[6] is None else 4 - values[6],
    )
    complete = all(value is not None for value in scored_items)
    return ScoreResult(
        total=sum(scored_items) if complete else None,
        complete=complete,
        scored_items=scored_items,
    )


def daily_derived_metrics(answers: Mapping[str, Any]) -> dict[str, Any]:
    present = answers.get("nssi_behavior_present_24h") is True
    total = sum((answers.get(field) or 0) for field in COUNT_FIELDS) if present else 0
    return {
        "nssi_any_24h": present,
        "nssi_total_count_24h": total,
        "nssi_thought_present_24h": answers.get("nssi_thought_present_24h"),
        "suicide_thought_present_24h": answers.get("suicide_thought_present_24h"),
        "nssi_urge_now": answers.get("nssi_urge_now"),
        "nssi_resistance_confidence_now": answers.get(
            "nssi_resistance_confidence_now"
        ),
    }


def _required_values(answers: Mapping[str, Any], prefix: str, count: int) -> tuple[Any, ...]:
    return tuple(answers.get(f"{prefix}_{index}") for index in range(1, count + 1))


def _sum_result(values: Sequence[int | None]) -> dict[str, int | bool | None]:
    complete = all(value is not None for value in values)
    return {"total": sum(values) if complete else None, "complete": complete}


def score_formal_instrument(
    instrument_id: str, answers: Mapping[str, Any]
) -> dict[str, Any]:
    if instrument_id in {"dshi_lifetime", "dshi_12m"}:
        return _sum_result(_required_values(answers, instrument_id, 6))

    if instrument_id == "fasm":
        values = _required_values(answers, "fasm", 15)
        if not all(value is not None for value in values):
            return {
                "total": None,
                "emotion": None,
                "attention": None,
                "avoidance": None,
                "complete": False,
            }
        return {
            "total": sum(values),
            "emotion": sum(values[index - 1] for index in (2, 4, 9, 11, 15)),
            "attention": sum(values[index - 1] for index in (3, 6, 7, 12, 13, 14)),
            "avoidance": sum(values[index - 1] for index in (1, 5, 8, 10)),
            "complete": True,
        }

    if instrument_id == "sicq":
        result = score_sicq(_required_values(answers, "sicq", 7))
        return {
            "total": result.total,
            "complete": result.complete,
            "scored_items": result.scored_items,
        }

    if instrument_id == "readiness":
        importance, ready, confidence = _required_values(answers, "readiness", 3)
        return {
            "importance": importance,
            "ready": ready,
            "confidence": confidence,
            "complete": all(value is not None for value in (importance, ready, confidence)),
        }

    if instrument_id == "siss":
        return _sum_result(_required_values(answers, "siss", 13))

    if instrument_id == "pss":
        values = tuple(
            None if value is None else int(bool(value))
            for value in _required_values(answers, "pss", 5)
        )
        return _sum_result(values)

    raise KeyError(f"No aggregate scoring rule for {instrument_id}")
