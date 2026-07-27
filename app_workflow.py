"""Pure record mutation helpers used by the Streamlit recorder."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from participant_identity import validate_subject_id
from session_record_workflow import (
    DAILY_CONTEXT_DEFAULTS,
    build_daily_field_status,
    build_formal_field_status,
)


def validate_intervention_day(value: object) -> int:
    if type(value) is not int:
        raise ValueError("intervention day must be an integer from 1 to 28")
    day = value
    if not 1 <= day <= 28:
        raise ValueError("intervention day must be an integer from 1 to 28")
    return day


def confirm_admin_intervention_day(value: object, *, confirmed: bool) -> int | None:
    """Return a day only after the subject-scoped admin confirmation."""

    day = validate_intervention_day(value)
    return day if confirmed else None


def daily_context_values(record: Mapping[str, Any]) -> dict[str, Any]:
    stored = record.get("daily_context", {})
    if not isinstance(stored, Mapping):
        stored = {}
    values: dict[str, Any] = {}
    for field_id, default in DAILY_CONTEXT_DEFAULTS.items():
        value = stored.get(field_id, default)
        values[field_id] = list(value) if isinstance(value, list) else value
    return values


def resolve_trusted_intervention_day(config: object, subject_id: str) -> int:
    """Resolve a signed participant's day from a server-controlled mapping."""

    safe_subject_id = validate_subject_id(subject_id)
    parsed = config
    if isinstance(config, str):
        try:
            parsed = json.loads(config)
        except json.JSONDecodeError as exc:
            raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。") from exc
    if not isinstance(parsed, Mapping) or safe_subject_id not in parsed:
        raise ValueError("可信干预日配置缺少当前受试者；干预日必须为 1 到 28。")

    value = parsed[safe_subject_id]
    if isinstance(value, bool):
        raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。")
    try:
        day = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。")
    if not 1 <= day <= 28:
        raise ValueError("可信干预日配置无效；干预日必须为 1 到 28。")
    return day


def support_needed(
    visit: str,
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
    intervention_day: int,
) -> bool:
    if visit == "daily":
        statuses = build_daily_field_status(
            answers, set(answered_field_ids), intervention_day
        )
        return (
            statuses.get("suicide_thought_present_24h") == "answered"
            and answers.get("suicide_thought_present_24h") is True
        )

    statuses = build_formal_field_status(
        visit, answers, set(answered_field_ids)
    )
    return any(
        field_id.startswith("pss_")
        and status == "answered"
        and answers.get(field_id) is True
        for field_id, status in statuses.items()
    )
