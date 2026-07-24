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


def _validate_integer_scale(
    values: Sequence[Any], scale_name: str, minimum: int, maximum: int
) -> tuple[int | None, ...]:
    validated = []
    for value in values:
        if value is None:
            validated.append(None)
        elif isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{scale_name} values must be integers or None")
        elif not minimum <= value <= maximum:
            raise ValueError(
                f"{scale_name} values must be between {minimum} and {maximum}"
            )
        else:
            validated.append(value)
    return tuple(validated)


def score_sicq(values: Sequence[int | None]) -> ScoreResult:
    if len(values) != 7:
        raise ValueError("SICQ requires exactly 7 items")

    validated = _validate_integer_scale(values, "SICQ", 0, 4)
    scored_items = validated[:6] + (
        None if validated[6] is None else 4 - validated[6],
    )
    complete = all(value is not None for value in scored_items)
    return ScoreResult(
        total=sum(scored_items) if complete else None,
        complete=complete,
        scored_items=scored_items,
    )


def daily_derived_metrics(answers: Mapping[str, Any]) -> dict[str, Any]:
    present = answers.get("nssi_behavior_present_24h")
    if present is not None and not isinstance(present, bool):
        raise TypeError("nssi_behavior_present_24h must be a boolean or None")

    if present is True:
        counts = []
        for field in COUNT_FIELDS:
            value = answers.get(field)
            if value is None:
                counts.append(None)
            elif isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field} must be a nonnegative integer or None")
            elif value < 0:
                raise ValueError(f"{field} must be a nonnegative integer or None")
            else:
                counts.append(value)
        total = sum(counts) if all(value is not None for value in counts) else None
    elif present is False:
        total = 0
    else:
        total = None
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
        values = _validate_integer_scale(
            _required_values(answers, instrument_id, 6), "DSHI", 1, 5
        )
        return _sum_result(values)

    if instrument_id == "fasm":
        values = _validate_integer_scale(
            _required_values(answers, "fasm", 15), "FASM", 0, 3
        )
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
        importance, ready, confidence = _validate_integer_scale(
            _required_values(answers, "readiness", 3), "readiness", 1, 10
        )
        return {
            "importance": importance,
            "ready": ready,
            "confidence": confidence,
            "complete": all(value is not None for value in (importance, ready, confidence)),
        }

    if instrument_id == "siss":
        values = _validate_integer_scale(
            _required_values(answers, "siss", 13), "SISS", 1, 5
        )
        return _sum_result(values)

    if instrument_id == "pss":
        raw_values = _required_values(answers, "pss", 5)
        if any(value is not None and not isinstance(value, bool) for value in raw_values):
            raise TypeError("PSS values must be booleans or None")
        values = tuple(None if value is None else int(value) for value in raw_values)
        return _sum_result(values)

    raise KeyError(f"No aggregate scoring rule for {instrument_id}")
