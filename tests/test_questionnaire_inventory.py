import hashlib
import json
from pathlib import Path

from questionnaire_scoring import COUNT_FIELDS
from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_DAYS,
    WEEKLY_INSTRUMENTS,
    InstrumentSpec,
    QuestionSpec,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "questionnaire_inventory.json"
SOURCE_FILES = (
    "questionnaire_specs.py",
    "questionnaire_ui.py",
    "questionnaire_scoring.py",
)

EXPECTED = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _question_inventory(question: QuestionSpec) -> dict[str, object]:
    return {
        "id": question.id,
        "prompt": question.prompt,
        "kind": question.kind,
        "required": question.required,
        "range": {
            "minimum": question.min_value,
            "maximum": question.max_value,
        },
        "labels": {
            "low": question.low_label,
            "high": question.high_label,
        },
        "options": list(question.options),
        "show_if": list(question.show_if) if question.show_if is not None else None,
    }


def _instrument_inventory(instrument: InstrumentSpec) -> dict[str, object]:
    return {
        "id": instrument.id,
        "label": instrument.label,
        "time_window": instrument.time_window,
        "item_order": [question.id for question in instrument.questions],
        "items": [_question_inventory(question) for question in instrument.questions],
    }


def _daily_protocol_items() -> tuple[QuestionSpec, ...]:
    items: list[QuestionSpec] = []
    for core in DAILY_CORE:
        items.append(core)
        items.extend(
            question
            for question in DAILY_CONDITIONAL
            if question.show_if is not None and question.show_if[0] == core.id
        )
    return tuple(items)


def _source_sha256(filename: str) -> str:
    source = (PROJECT_ROOT / filename).read_text(encoding="utf-8")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_current_inventory() -> dict[str, object]:
    daily_protocol_items = _daily_protocol_items()
    daily_scoring_ids = {
        "nssi_thought_present_24h",
        "nssi_behavior_present_24h",
        *COUNT_FIELDS,
        "suicide_thought_present_24h",
        "nssi_urge_now",
        "nssi_resistance_confidence_now",
    }
    pss_support_trigger_ids = [
        question.id
        for question in FORMAL_INSTRUMENTS["pss"].questions
        if question.id.startswith("pss_")
    ]

    return {
        "source_sha256": {
            filename: _source_sha256(filename) for filename in SOURCE_FILES
        },
        "daily": {
            "protocol_item_order": [question.id for question in daily_protocol_items],
            "core": {
                "item_order": [question.id for question in DAILY_CORE],
                "items": [_question_inventory(question) for question in DAILY_CORE],
            },
            "conditional": {
                "item_order": [question.id for question in DAILY_CONDITIONAL],
                "items": [
                    _question_inventory(question) for question in DAILY_CONDITIONAL
                ],
            },
        },
        "weekly": {
            "schedule_days": sorted(WEEKLY_DAYS),
            "instrument_order": [
                instrument.id for instrument in WEEKLY_INSTRUMENTS
            ],
            "instruments": [
                _instrument_inventory(instrument)
                for instrument in WEEKLY_INSTRUMENTS
            ],
        },
        "formal": {
            "instrument_order": list(FORMAL_INSTRUMENTS),
            "instruments": [
                _instrument_inventory(instrument)
                for instrument in FORMAL_INSTRUMENTS.values()
            ],
            "visit_order": list(VISIT_INSTRUMENT_IDS),
            "visits": [
                {
                    "visit": visit,
                    "instrument_order": list(instrument_ids),
                }
                for visit, instrument_ids in VISIT_INSTRUMENT_IDS.items()
            ],
        },
        "scoring_inputs": {
            "daily": {
                "count_input_ids": list(COUNT_FIELDS),
                "input_ids": [
                    question.id
                    for question in daily_protocol_items
                    if question.id in daily_scoring_ids
                ],
            },
            "weekly": [
                {
                    "instrument_id": "sicq_weekly",
                    "input_ids": [
                        question.id
                        for instrument in WEEKLY_INSTRUMENTS
                        if instrument.id == "sicq_weekly"
                        for question in instrument.questions
                    ],
                }
            ],
            "formal": [
                {
                    "instrument_id": instrument.id,
                    "input_ids": [question.id for question in instrument.questions],
                }
                for instrument in FORMAL_INSTRUMENTS.values()
            ],
            "sicq_reverse_scored_raw_input_id": "sicq_7",
        },
        "support_trigger_ids": {
            "daily": ["suicide_thought_present_24h"],
            "formal": pss_support_trigger_ids,
        },
    }


def test_current_questionnaire_contract_matches_approved_inventory():
    assert build_current_inventory() == EXPECTED
