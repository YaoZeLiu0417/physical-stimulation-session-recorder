# taVNS NSSI Dense Questionnaire Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add protocol-aligned daily, weekly, and formal-visit NSSI questionnaires to the Streamlit intervention recorder, with hidden scoring, resumable records, stable video/JSON linkage, and an Alto Neuroscience-inspired participant UI.

**Architecture:** Keep `app.py` as the recording and upload orchestrator while moving questionnaire definitions, scoring, persistence, link authentication, and rendering into focused Python modules. All measurement and storage rules are implemented as pure functions first, then integrated into Streamlit; JSON is atomically saved before upload and shares a stable `record_id` with the video.

**Tech Stack:** Python 3.10+, Streamlit 1.37+, streamlit-webrtc, standard-library dataclasses/JSON/pathlib/uuid, requests, pytest 8

---

## File Map

- Create `questionnaire_specs.py`: immutable question/instrument definitions, daily branches, weekly schedule, and formal visit mapping.
- Create `questionnaire_scoring.py`: pure scoring and completeness functions.
- Create `record_store.py`: subject validation, stable record identity, atomic drafts, revisions, and upload-state rules.
- Create `link_auth.py`: daily/formal visit link signing and verification with legacy daily-link compatibility.
- Create `questionnaire_ui.py`: Alto-inspired CSS, one-question flow, active-answer tracking, and participant-only completion UI.
- Create `upload_workflow.py`: upload initial JSON, upload video, re-sync finalized JSON state, and clean up all media sources only after full success.
- Modify `app.py`: use the new identity, questionnaire, persistence, and upload workflow after recording.
- Modify `make_links.py`: generate signed daily or formal-visit links through `link_auth.py`.
- Modify `.gitignore`: ignore visual-companion artifacts.
- Create `requirements-dev.txt`: pin the test runner separately from production dependencies.
- Create `tests/`: unit, flow, storage, link, upload, and Streamlit fixture tests.

## Task 1: Establish the questionnaire specification model and daily/weekly definitions

**Files:**
- Create: `requirements-dev.txt`
- Modify: `.gitignore`
- Create: `tests/test_questionnaire_specs.py`
- Create: `questionnaire_specs.py`

- [ ] **Step 1: Add the test-only dependency and ignore local design artifacts**

Add to `requirements-dev.txt`:

```text
pytest>=8.3,<9
```

Add to `.gitignore`:

```text

# Local visual-design companion
.superpowers/
```

- [ ] **Step 2: Write failing tests for the daily and weekly specification**

Create `tests/test_questionnaire_specs.py`:

```python
from questionnaire_specs import (
    DAILY_CORE,
    FASM_MOTIVES,
    WEEKLY_INSTRUMENTS,
    active_daily_question_ids,
    weekly_due,
)


def test_daily_core_has_five_required_questions():
    assert [q.id for q in DAILY_CORE] == [
        "nssi_thought_present_24h",
        "nssi_behavior_present_24h",
        "suicide_thought_present_24h",
        "nssi_urge_now",
        "nssi_resistance_confidence_now",
    ]
    assert all(q.required for q in DAILY_CORE)


def test_daily_positive_answers_activate_only_relevant_branches():
    answers = {
        "nssi_thought_present_24h": True,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
    }
    ids = active_daily_question_ids(answers)
    assert "nssi_thought_frequency_24h" in ids
    assert "nssi_thought_intensity_24h" in ids
    assert "nssi_cut_count_24h" not in ids
    assert "suicide_thought_frequency_24h" not in ids


def test_weekly_schedule_uses_calendar_intervention_days():
    assert [day for day in range(1, 29) if weekly_due(day)] == [7, 14, 21, 28]


def test_weekly_instruments_have_expected_item_counts():
    counts = {instrument.id: len(instrument.questions) for instrument in WEEKLY_INSTRUMENTS}
    assert counts == {
        "nssi_impulse_weekly": 2,
        "nssi_future_weekly": 1,
        "nssi_stop_weekly": 1,
        "sicq_weekly": 7,
        "readiness_weekly": 3,
    }
    assert len(FASM_MOTIVES) == 15
```

- [ ] **Step 3: Run the specification tests and verify the import failure**

Run:

```powershell
python -m pytest tests/test_questionnaire_specs.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'questionnaire_specs'`.

- [ ] **Step 4: Implement the immutable specification types and daily/weekly content**

Create `questionnaire_specs.py` with these public types and constants:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

QuestionKind = Literal["boolean", "slider", "integer", "multiselect", "text"]


@dataclass(frozen=True)
class QuestionSpec:
    id: str
    prompt: str
    kind: QuestionKind
    required: bool = True
    min_value: int | None = None
    max_value: int | None = None
    low_label: str = ""
    high_label: str = ""
    options: tuple[str, ...] = ()
    show_if: tuple[str, Any] | None = None


@dataclass(frozen=True)
class InstrumentSpec:
    id: str
    label: str
    time_window: str
    questions: tuple[QuestionSpec, ...]


DAILY_CORE = (
    QuestionSpec(
        "nssi_thought_present_24h",
        "过去 24 小时，是否出现过不想死但想故意伤害自己的想法？",
        "boolean",
    ),
    QuestionSpec(
        "nssi_behavior_present_24h",
        "过去 24 小时，是否发生过不想死但故意伤害自己的行为？",
        "boolean",
    ),
    QuestionSpec(
        "suicide_thought_present_24h",
        "过去 24 小时，是否出现过自杀想法？",
        "boolean",
    ),
    QuestionSpec(
        "nssi_urge_now",
        "此时此刻，你想要伤害自己的冲动有多强烈？",
        "slider",
        min_value=0,
        max_value=10,
        low_label="没有冲动",
        high_label="极强",
    ),
    QuestionSpec(
        "nssi_resistance_confidence_now",
        "此时此刻，你对自己能抵抗住自伤冲动有多大信心？",
        "slider",
        min_value=0,
        max_value=7,
        low_label="一点信心也没有",
        high_label="非常有信心",
    ),
)

FASM_MOTIVES = (
    "为了逃避上学、工作或其他活动",
    "为了缓解麻木感或空虚感",
    "为了引起注意",
    "为了有一些感觉，哪怕是疼痛",
    "为了逃避自己不想做的讨厌事",
    "为了获得别人的回应，哪怕是负面回应",
    "为了从父母或朋友那里获得更多的关注",
    "为了避免跟人待在一起",
    "为了惩罚自己",
    "为了逃避惩罚或承担后果",
    "为了停止不好的感受",
    "为了让他人知道自己有多绝望",
    "为了让父母理解或注意自己",
    "为了获得帮助",
    "为了放松",
)

DAILY_CONDITIONAL = (
    QuestionSpec(
        "nssi_thought_frequency_24h",
        "过去 24 小时，这些想法出现得有多频繁？",
        "slider",
        min_value=0,
        max_value=4,
        low_label="只有一次",
        high_label="几乎一直",
        show_if=("nssi_thought_present_24h", True),
    ),
    QuestionSpec(
        "nssi_thought_intensity_24h",
        "过去 24 小时，这些想法最强时有多强烈？",
        "slider",
        min_value=0,
        max_value=10,
        low_label="很弱",
        high_label="极强",
        show_if=("nssi_thought_present_24h", True),
    ),
    QuestionSpec("nssi_cut_count_24h", "割伤皮肤的实际次数", "integer", min_value=0, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_burn_count_24h", "烧伤或烫伤皮肤的实际次数", "integer", min_value=0, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_scratch_count_24h", "严重抓挠至留下伤痕或流血的实际次数", "integer", min_value=0, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_bite_count_24h", "咬伤自己至皮肤破损的实际次数", "integer", min_value=0, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_hit_object_count_24h", "撞击头部或其他身体部位至出现瘀伤的实际次数", "integer", min_value=0, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_hit_self_count_24h", "捶打自己至出现瘀伤的实际次数", "integer", min_value=0, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_other_description_24h", "其他 NSSI 行为", "text", required=False, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_other_count_24h", "其他 NSSI 行为的实际次数", "integer", min_value=0, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_medical_care_24h", "是否因本次行为需要医疗处理？", "boolean", show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_motives_24h", "这次行为与哪些原因有关？", "multiselect", required=False, options=FASM_MOTIVES, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_trigger_24h", "触发情境", "text", required=False, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec("nssi_coping_24h", "你采用了哪些应对方式？", "text", required=False, show_if=("nssi_behavior_present_24h", True)),
    QuestionSpec(
        "suicide_thought_frequency_24h",
        "过去 24 小时，自杀想法出现得有多频繁？",
        "slider",
        min_value=0,
        max_value=4,
        low_label="只有一次",
        high_label="几乎一直",
        show_if=("suicide_thought_present_24h", True),
    ),
)


def _slider(id_: str, prompt: str, minimum: int, maximum: int, low: str, high: str) -> QuestionSpec:
    return QuestionSpec(id_, prompt, "slider", min_value=minimum, max_value=maximum, low_label=low, high_label=high)


WEEKLY_INSTRUMENTS = (
    InstrumentSpec(
        "nssi_impulse_weekly",
        "自伤冲动",
        "过去一周",
        (
            _slider("nssi_impulse_time", "过去一周里，你多长时间想过伤害自己？", 1, 100, "从不", "几乎所有时间"),
            _slider("nssi_impulse_resistance", "过去一周里，抵制伤害自己有多难？", 1, 7, "完全不难", "无法抵制"),
        ),
    ),
    InstrumentSpec("nssi_future_weekly", "未来 NSSI 可能性", "当前", (_slider("nssi_future_likelihood", "你认为未来发生 NSSI 的可能性有多大？", 0, 4, "完全不会", "极其可能"),)),
    InstrumentSpec("nssi_stop_weekly", "停止未来 NSSI 的愿望", "当前", (_slider("nssi_stop_desire", "你有多想停止 NSSI？", 0, 4, "根本不想停止", "绝对想停止"),)),
    InstrumentSpec(
        "sicq_weekly",
        "自伤渴望问卷",
        "当前",
        tuple(
            _slider(f"sicq_{index}", prompt, 0, 4, "非常不同意", "非常同意")
            for index, prompt in enumerate(
                (
                    "不管我今天过得好还是不好，我都会想自伤。",
                    "有些时候，我满脑子都是自伤的欲望。",
                    "只要一想到自伤，我就会渴望它。",
                    "我经常花时间计划下一次什么时候可以自伤。",
                    "心情好的时候，我经常想自伤。",
                    "即使事情进展顺利，我也很难控制自伤的冲动。",
                    "即使我有能力，也很容易放弃自伤的机会。",
                ),
                start=1,
            )
        ),
    ),
    InstrumentSpec(
        "readiness_weekly",
        "准备改变自伤",
        "当前",
        (
            _slider("readiness_importance", "采取措施停止自我伤害对我来说很重要。", 1, 10, "完全不符合", "完全符合"),
            _slider("readiness_ready", "我已经准备好采取措施停止自我伤害。", 1, 10, "完全不符合", "完全符合"),
            _slider("readiness_confidence", "我相信我可以采取措施停止自我伤害。", 1, 10, "完全不符合", "完全符合"),
        ),
    ),
)

WEEKLY_DAYS = frozenset({7, 14, 21, 28})


def weekly_due(intervention_day: int) -> bool:
    return intervention_day in WEEKLY_DAYS


def active_daily_question_ids(answers: Mapping[str, Any]) -> list[str]:
    ids = [q.id for q in DAILY_CORE]
    ids.extend(
        q.id
        for q in DAILY_CONDITIONAL
        if q.show_if is not None and answers.get(q.show_if[0]) == q.show_if[1]
    )
    return ids
```

- [ ] **Step 5: Run the specification tests**

Run:

```powershell
python -m pytest tests/test_questionnaire_specs.py -v
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit the specification foundation**

```powershell
git add .gitignore requirements-dev.txt questionnaire_specs.py tests/test_questionnaire_specs.py
git commit -m "feat: define daily and weekly NSSI questionnaires"
```

## Task 2: Add complete formal-visit NSSI instruments and visit mapping

**Files:**
- Modify: `questionnaire_specs.py`
- Modify: `tests/test_questionnaire_specs.py`

- [ ] **Step 1: Add failing formal-visit mapping tests**

Append to `tests/test_questionnaire_specs.py`:

```python
from questionnaire_specs import FORMAL_INSTRUMENTS, VISIT_INSTRUMENT_IDS


def test_formal_instrument_set_is_complete():
    assert set(FORMAL_INSTRUMENTS) == {
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


def test_visit_mapping_matches_crf_follow_up_structure():
    assert "fasm" in VISIT_INSTRUMENT_IDS["V1"]
    assert "fasm" in VISIT_INSTRUMENT_IDS["V3"]
    assert "fasm" not in VISIT_INSTRUMENT_IDS["V4"]
    assert VISIT_INSTRUMENT_IDS["V5"] == VISIT_INSTRUMENT_IDS["V4"]
    assert "fasm" in VISIT_INSTRUMENT_IDS["V6"]
    assert "dshi_12m" in VISIT_INSTRUMENT_IDS["V5"]


def test_formal_item_counts_match_crf():
    expected = {
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
    assert {key: len(value.questions) for key, value in FORMAL_INSTRUMENTS.items()} == expected


def test_formal_instrument_ids_match_their_mapping_keys():
    assert {key: instrument.id for key, instrument in FORMAL_INSTRUMENTS.items()} == {
        key: key for key in FORMAL_INSTRUMENTS
    }
```

- [ ] **Step 2: Run the new tests and verify the missing constants**

Run:

```powershell
python -m pytest tests/test_questionnaire_specs.py::test_formal_instrument_set_is_complete -v
```

Expected: collection fails because `FORMAL_INSTRUMENTS` is not defined.

- [ ] **Step 3: Add formal question helpers and exact CRF item text**

Append to `questionnaire_specs.py`. Use `_likert()` for fixed-option formal items and keep the following exact lists in the file:

```python
def _likert(id_: str, prompt: str, minimum: int, maximum: int, show_if: tuple[str, Any] | None = None) -> QuestionSpec:
    return QuestionSpec(id_, prompt, "slider", min_value=minimum, max_value=maximum, show_if=show_if)


DSHI_BEHAVIORS = (
    "故意用玻璃、小刀等划伤自己的皮肤",
    "故意用烟头、打火机或其他东西烧伤或烫伤自己的皮肤",
    "故意猛烈抓挠自己，达到留下伤痕或流血的程度",
    "故意咬自己以致皮肤破损",
    "故意用头撞击某物，以致出现瘀伤",
    "故意捶打自己以致出现瘀伤",
)

FASM_ITEMS = FASM_MOTIVES

SICQ_ITEMS = tuple(q.prompt for q in WEEKLY_INSTRUMENTS[3].questions)
READINESS_ITEMS = tuple(q.prompt for q in WEEKLY_INSTRUMENTS[4].questions)

SISS_ITEMS = (
    "因为我曾经自伤，所以我认为我是寻求关注的人。",
    "因为我曾经自伤，所以我认为我是变化无常的人。",
    "因为我曾经自伤，所以我认为我是自寻烦恼的人。",
    "因为我曾经自伤，所以我认为我是疯狂的人。",
    "因为我曾经自伤，所以我认为我是不值得被爱的人。",
    "因为我曾经自伤，所以我认为我是软弱的人。",
    "因为我曾经自伤，所以我是不负责任的人。",
    "因为我曾经自伤，所以我是不完美的人。",
    "因为我曾经自伤，所以我是有控制欲的人。",
    "因为我曾经自伤，所以我是有自杀倾向的人。",
    "因为我曾经自伤，所以我是不理智的人。",
    "因为我曾经自伤，所以我是不堪重负的人。",
    "因为我曾经自伤，所以我是自私的人。",
)

PSS_ITEMS = (
    "你有没有觉得生活不值得过？",
    "你有没有希望自己死掉，例如睡觉时希望自己醒不过来？",
    "你有没有想过结束自己的生命，即使你真的不打算这样做？",
    "你是否已经到了真正考虑结束自己的生命或为如何结束生命制定计划的地步？",
    "你有没有试图结束自己的生命？",
)


def _instrument(id_: str, label: str, time_window: str, questions: tuple[QuestionSpec, ...]) -> InstrumentSpec:
    return InstrumentSpec(id_, label, time_window, questions)


FORMAL_INSTRUMENTS = {
    "dshi_lifetime": _instrument(
        "dshi_lifetime",
        "故意自伤量表-青少年版（终生）",
        "从有记忆到目前",
        tuple(_likert(f"dshi_lifetime_{i}", text, 1, 5) for i, text in enumerate(DSHI_BEHAVIORS, 1)),
    ),
    "dshi_12m": _instrument(
        "dshi_12m",
        "故意自伤量表-青少年版（过去一年）",
        "过去一年",
        tuple(_likert(f"dshi_12m_{i}", text, 1, 5) for i, text in enumerate(DSHI_BEHAVIORS, 1)),
    ),
    "fasm": _instrument(
        "fasm",
        "中文版自伤功能评估量表",
        "根据已报告的自伤行为",
        tuple(_likert(f"fasm_{i}", text, 0, 3) for i, text in enumerate(FASM_ITEMS, 1)),
    ),
    "nssi_ideation": _instrument(
        "nssi_ideation",
        "自伤意念",
        "过去六个月及过去一个月",
        (
            QuestionSpec("nssi_ideation_6m_present", "过去六个月中，是否有过想故意伤害自己但并不想死的想法？", "boolean"),
            _likert("nssi_ideation_6m_frequency", "过去六个月中，自伤想法出现的频率", 1, 6, ("nssi_ideation_6m_present", True)),
            _likert("nssi_ideation_6m_intensity", "过去六个月中，自伤想法的强度", 1, 5, ("nssi_ideation_6m_present", True)),
            QuestionSpec("nssi_ideation_1m_present", "过去一个月中，是否有过自伤想法？", "boolean"),
            _likert("nssi_ideation_1m_frequency", "过去一个月中，自伤想法出现的频率", 1, 6, ("nssi_ideation_1m_present", True)),
            _likert("nssi_ideation_1m_intensity", "过去一个月中，自伤想法的强度", 1, 5, ("nssi_ideation_1m_present", True)),
        ),
    ),
    "nssi_impulse": _instrument(
        "nssi_impulse",
        "自伤冲动",
        "过去一周",
        (
            _likert("nssi_impulse_time", "过去一周里，你多长时间想过伤害自己？", 1, 100),
            _likert("nssi_impulse_resistance", "过去一周里，抵制伤害自己的冲动有多难？", 1, 7),
        ),
    ),
    "nssi_future": _instrument(
        "nssi_future",
        "未来 NSSI 可能性",
        "当前",
        (_likert("nssi_future_likelihood", "你认为未来发生 NSSI 的可能性有多大？", 0, 4),),
    ),
    "nssi_stop": _instrument(
        "nssi_stop",
        "停止未来 NSSI 的愿望",
        "当前",
        (_likert("nssi_stop_desire", "你有多想停止 NSSI？", 0, 4),),
    ),
    "sicq": _instrument("sicq", "自伤渴望问卷", "当前", tuple(_likert(f"sicq_{i}", text, 0, 4) for i, text in enumerate(SICQ_ITEMS, 1))),
    "readiness": _instrument("readiness", "准备改变自伤", "当前", tuple(_likert(f"readiness_{i}", text, 1, 10) for i, text in enumerate(READINESS_ITEMS, 1))),
    "siss": _instrument("siss", "自伤耻感量表", "当前", tuple(_likert(f"siss_{i}", text, 1, 5) for i, text in enumerate(SISS_ITEMS, 1))),
    "pss": _instrument("pss", "Paykel 自杀量表", "过去一年", tuple(QuestionSpec(f"pss_{i}", text, "boolean") for i, text in enumerate(PSS_ITEMS, 1))),
}

_FULL_FORMAL = (
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
_FOLLOW_UP_WITHOUT_FASM = tuple(item for item in _FULL_FORMAL if item != "fasm")

VISIT_INSTRUMENT_IDS = {
    "V1": _FULL_FORMAL,
    "V3": _FULL_FORMAL,
    "V4": _FOLLOW_UP_WITHOUT_FASM,
    "V5": _FOLLOW_UP_WITHOUT_FASM,
    "V6": _FULL_FORMAL,
}
```

- [ ] **Step 4: Run all specification tests**

Run:

```powershell
python -m pytest tests/test_questionnaire_specs.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit formal visit definitions**

```powershell
git add questionnaire_specs.py tests/test_questionnaire_specs.py
git commit -m "feat: define formal NSSI visit instruments"
```

## Task 3: Implement scoring, completeness, and derived metrics

**Files:**
- Create: `tests/test_questionnaire_scoring.py`
- Create: `questionnaire_scoring.py`

- [ ] **Step 1: Write failing scoring tests**

Create `tests/test_questionnaire_scoring.py`:

```python
from questionnaire_scoring import (
    ScoreResult,
    daily_derived_metrics,
    score_formal_instrument,
    score_sicq,
)


def test_sicq_reverses_item_seven_and_respects_boundaries():
    minimum = score_sicq([0, 0, 0, 0, 0, 0, 4])
    maximum = score_sicq([4, 4, 4, 4, 4, 4, 0])
    assert minimum == ScoreResult(total=0, complete=True, scored_items=(0, 0, 0, 0, 0, 0, 0))
    assert maximum.total == 28
    assert maximum.scored_items[-1] == 4


def test_sicq_missing_item_is_incomplete_and_has_no_total():
    result = score_sicq([0, 1, 2, None, 3, 4, 4])
    assert result.complete is False
    assert result.total is None


def test_daily_counts_and_safety_signals_are_separate():
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
    assert metrics["nssi_total_count_24h"] == 4
    assert metrics["nssi_any_24h"] is True
    assert metrics["suicide_thought_present_24h"] is True


def test_formal_scales_keep_defined_aggregation_only():
    assert score_formal_instrument("dshi_12m", {f"dshi_12m_{i}": 1 for i in range(1, 7)})["total"] == 6
    readiness = score_formal_instrument("readiness", {"readiness_1": 4, "readiness_2": 5, "readiness_3": 6})
    assert readiness == {"importance": 4, "ready": 5, "confidence": 6, "complete": True}
    assert "total" not in readiness
```

- [ ] **Step 2: Verify the tests fail before implementation**

Run:

```powershell
python -m pytest tests/test_questionnaire_scoring.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'questionnaire_scoring'`.

- [ ] **Step 3: Implement pure scoring functions**

Create `questionnaire_scoring.py`:

```python
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
    scored = tuple(value if index < 6 or value is None else 4 - value for index, value in enumerate(values))
    complete = all(value is not None for value in scored)
    return ScoreResult(sum(value for value in scored if value is not None) if complete else None, complete, scored)


def daily_derived_metrics(answers: Mapping[str, Any]) -> dict[str, Any]:
    present = answers.get("nssi_behavior_present_24h") is True
    total = sum(int(answers.get(field, 0) or 0) for field in COUNT_FIELDS) if present else 0
    return {
        "nssi_any_24h": present,
        "nssi_total_count_24h": total,
        "nssi_thought_present_24h": answers.get("nssi_thought_present_24h"),
        "suicide_thought_present_24h": answers.get("suicide_thought_present_24h"),
        "nssi_urge_now": answers.get("nssi_urge_now"),
        "nssi_resistance_confidence_now": answers.get("nssi_resistance_confidence_now"),
    }


def _required_values(answers: Mapping[str, Any], prefix: str, count: int) -> list[int | None]:
    return [answers.get(f"{prefix}_{index}") for index in range(1, count + 1)]


def _sum_result(values: Sequence[int | None]) -> dict[str, Any]:
    complete = all(value is not None for value in values)
    return {"total": sum(values) if complete else None, "complete": complete}


def score_formal_instrument(instrument_id: str, answers: Mapping[str, Any]) -> dict[str, Any]:
    if instrument_id in {"dshi_lifetime", "dshi_12m"}:
        return _sum_result(_required_values(answers, instrument_id, 6))
    if instrument_id == "fasm":
        values = _required_values(answers, "fasm", 15)
        complete = all(value is not None for value in values)
        if not complete:
            return {"total": None, "emotion": None, "attention": None, "avoidance": None, "complete": False}
        return {
            "total": sum(values),
            "emotion": sum(values[index - 1] for index in (2, 4, 9, 11, 15)),
            "attention": sum(values[index - 1] for index in (3, 6, 7, 12, 13, 14)),
            "avoidance": sum(values[index - 1] for index in (1, 5, 8, 10)),
            "complete": True,
        }
    if instrument_id == "sicq":
        result = score_sicq(_required_values(answers, "sicq", 7))
        return {"total": result.total, "complete": result.complete, "scored_items": result.scored_items}
    if instrument_id == "readiness":
        values = _required_values(answers, "readiness", 3)
        return {"importance": values[0], "ready": values[1], "confidence": values[2], "complete": all(value is not None for value in values)}
    if instrument_id == "siss":
        return _sum_result(_required_values(answers, "siss", 13))
    if instrument_id == "pss":
        values = _required_values(answers, "pss", 5)
        numeric = [None if value is None else int(bool(value)) for value in values]
        return _sum_result(numeric)
    raise KeyError(f"No aggregate scoring rule for {instrument_id}")
```

- [ ] **Step 4: Run scoring tests and the existing specification tests**

Run:

```powershell
python -m pytest tests/test_questionnaire_scoring.py tests/test_questionnaire_specs.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit scoring behavior**

```powershell
git add questionnaire_scoring.py tests/test_questionnaire_scoring.py
git commit -m "feat: score NSSI questionnaire responses"
```

## Task 4: Build resumable, revision-aware record storage

**Files:**
- Create: `tests/test_record_store.py`
- Create: `record_store.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_record_store.py`:

```python
import json
from datetime import date

import pytest

from record_store import DailyRecordStore, can_cleanup, remote_record_dir, validate_subject_id


def test_subject_id_rejects_path_and_separator_characters():
    assert validate_subject_id("sub-001") == "sub-001"
    for invalid in ("../other", "sub/001", "sub\\001", "", "a" * 65):
        with pytest.raises(ValueError):
            validate_subject_id(invalid)


def test_store_resumes_one_record_per_subject_and_day(tmp_path):
    store = DailyRecordStore(tmp_path)
    first = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    second = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    assert first["record_id"] == second["record_id"]
    assert first["schema_version"] == 4


def test_atomic_draft_round_trip_and_revision(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    record["daily_core"] = {"nssi_urge_now": 4}
    record["completion"]["answered_field_ids"]["daily"] = ["nssi_urge_now"]
    record["completion"]["current_step"]["daily"] = 3
    path = store.save(record)
    assert json.loads(path.read_text(encoding="utf-8"))["daily_core"]["nssi_urge_now"] == 4
    restored = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=7)
    assert restored["completion"]["answered_field_ids"]["daily"] == ["nssi_urge_now"]
    assert restored["completion"]["current_step"]["daily"] == 3
    revised = store.revise(record)
    assert revised["record_id"] == record["record_id"]
    assert revised["revision"] == 2
    assert revised["supersedes_revision"] == 1


def test_cleanup_requires_both_remote_objects():
    assert can_cleanup({"json": "uploaded", "video": "uploaded"}) is True
    assert can_cleanup({"json": "uploaded", "video": "failed"}) is False
    assert can_cleanup({"json": "failed", "video": "uploaded"}) is False


def test_remote_path_is_record_scoped():
    assert remote_record_dir("/apps/collector", "sub-001", "20260724", "sub-001_20260724_a1b2c3d4") == "/apps/collector/sub-001/20260724/sub-001_20260724_a1b2c3d4"
```

- [ ] **Step 2: Run storage tests and verify the missing module**

Run:

```powershell
python -m pytest tests/test_record_store.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'record_store'`.

- [ ] **Step 3: Implement subject validation and the daily record repository**

Create `record_store.py`:

```python
from __future__ import annotations

import json
import os
import re
import uuid
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

SUBJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_subject_id(value: str) -> str:
    value = value.strip()
    if not SUBJECT_ID_RE.fullmatch(value):
        raise ValueError("受试者编号只能包含字母、数字、连字符和下划线，且长度为 1-64 个字符")
    return value


def can_cleanup(upload: Mapping[str, str]) -> bool:
    return upload.get("json") == "uploaded" and upload.get("video") == "uploaded"


def remote_record_dir(save_dir: str, subject_id: str, date_key: str, record_id: str) -> str:
    safe_subject = validate_subject_id(subject_id)
    return f"{save_dir.rstrip('/')}/{safe_subject}/{date_key}/{record_id}"


class DailyRecordStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _matching_paths(self, subject_id: str, record_date: date) -> list[Path]:
        prefix = f"{validate_subject_id(subject_id)}_{record_date:%Y%m%d}_"
        return sorted(self.root.glob(f"{prefix}*_r*_state.json"))

    def _new_record(self, subject_id: str, record_date: date, intervention_day: int) -> dict[str, Any]:
        safe_subject = validate_subject_id(subject_id)
        record_id = f"{safe_subject}_{record_date:%Y%m%d}_{uuid.uuid4().hex[:8]}"
        return {
            "schema_version": 4,
            "record_id": record_id,
            "subject_id": safe_subject,
            "record_date": record_date.isoformat(),
            "intervention_day": intervention_day,
            "revision": 1,
            "instrument_versions": {
                "daily_nssi_ema": "1.0",
                "weekly_nssi": "1.0",
                "formal_nssi_crf": "1.0",
            },
            "daily_core": {},
            "conditional_details": {},
            "weekly_extension": {},
            "formal_visits": {},
            "field_status": {},
            "derived_metrics": {},
            "completion": {
                "status": "draft",
                "answered_field_ids": {},
                "current_step": {},
            },
            "safety_signals": {},
            "recording": {},
            "upload": {"json": "pending", "video": "pending"},
            "created_at_iso": datetime.now().isoformat(timespec="seconds"),
            "updated_at_iso": datetime.now().isoformat(timespec="seconds"),
        }

    def get_or_create(self, subject_id: str, record_date: date, intervention_day: int) -> dict[str, Any]:
        paths = self._matching_paths(subject_id, record_date)
        if paths:
            latest = max(paths, key=lambda path: json.loads(path.read_text(encoding="utf-8"))["revision"])
            return json.loads(latest.read_text(encoding="utf-8"))
        record = self._new_record(subject_id, record_date, intervention_day)
        self.save(record)
        return record

    def path_for(self, record: Mapping[str, Any]) -> Path:
        return self.root / f"{record['record_id']}_r{int(record['revision'])}_state.json"

    def save(self, record: dict[str, Any]) -> Path:
        record["updated_at_iso"] = datetime.now().isoformat(timespec="seconds")
        target = self.path_for(record)
        temporary = target.with_suffix(target.suffix + f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
        return target

    def revise(self, record: Mapping[str, Any]) -> dict[str, Any]:
        revised = deepcopy(dict(record))
        revised["supersedes_revision"] = int(record["revision"])
        revised["revision"] = int(record["revision"]) + 1
        revised["completion"] = {
            "status": "draft",
            "answered_field_ids": {},
            "current_step": {},
        }
        revised["upload"] = {"json": "pending", "video": record.get("upload", {}).get("video", "pending")}
        self.save(revised)
        return revised
```

- [ ] **Step 4: Run storage tests**

Run:

```powershell
python -m pytest tests/test_record_store.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit record storage**

```powershell
git add record_store.py tests/test_record_store.py
git commit -m "feat: persist resumable questionnaire records"
```

## Task 5: Make signed links carry an authenticated visit mode

**Files:**
- Create: `tests/test_link_auth.py`
- Create: `link_auth.py`
- Modify: `make_links.py:16-104`
- Modify: `app.py:75-142`

- [ ] **Step 1: Write failing signing and tamper tests**

Create `tests/test_link_auth.py`:

```python
from link_auth import sign_subject_link, verify_subject_link


def test_legacy_daily_signature_remains_valid():
    signature = sign_subject_link("secret", "sub-001", 2_000_000_000, "daily")
    verified = verify_subject_link("secret", "sub-001", 2_000_000_000, signature, "daily", now=1_900_000_000)
    assert verified.subject_id == "sub-001"
    assert verified.visit == "daily"


def test_formal_visit_is_covered_by_signature():
    signature = sign_subject_link("secret", "sub-001", 2_000_000_000, "V5")
    assert verify_subject_link("secret", "sub-001", 2_000_000_000, signature, "V5", now=1_900_000_000).visit == "V5"
    assert verify_subject_link("secret", "sub-001", 2_000_000_000, signature, "V6", now=1_900_000_000) is None


def test_expired_or_unknown_visit_is_rejected():
    signature = sign_subject_link("secret", "sub-001", 2_000_000_000, "V5")
    assert verify_subject_link("secret", "sub-001", 2_000_000_000, signature, "V5", now=2_000_000_001) is None
    assert verify_subject_link("secret", "sub-001", 2_000_000_000, signature, "V2", now=1_900_000_000) is None
```

- [ ] **Step 2: Verify the link tests fail**

Run:

```powershell
python -m pytest tests/test_link_auth.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'link_auth'`.

- [ ] **Step 3: Implement link signing with daily backward compatibility**

Create `link_auth.py`:

```python
from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

from record_store import validate_subject_id

ALLOWED_VISITS = frozenset({"daily", "V1", "V3", "V4", "V5", "V6"})


@dataclass(frozen=True)
class VerifiedLink:
    subject_id: str
    visit: str


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _message(subject_id: str, exp_ts: int, visit: str) -> bytes:
    safe_subject = validate_subject_id(subject_id)
    if visit not in ALLOWED_VISITS:
        raise ValueError(f"unsupported visit: {visit}")
    text = f"{safe_subject}|{exp_ts}" if visit == "daily" else f"{safe_subject}|{exp_ts}|{visit}"
    return text.encode("utf-8")


def sign_subject_link(key: str, subject_id: str, exp_ts: int, visit: str = "daily") -> str:
    return _b64url(hmac.new(key.encode("utf-8"), _message(subject_id, exp_ts, visit), hashlib.sha256).digest())


def verify_subject_link(key: str, subject_id: str, exp_ts: int, signature: str, visit: str = "daily", *, now: int) -> VerifiedLink | None:
    if not key or now > exp_ts or visit not in ALLOWED_VISITS:
        return None
    try:
        expected = sign_subject_link(key, subject_id, exp_ts, visit)
    except ValueError:
        return None
    if not hmac.compare_digest(expected, signature):
        return None
    return VerifiedLink(validate_subject_id(subject_id), visit)
```

- [ ] **Step 4: Run the link tests**

Run:

```powershell
python -m pytest tests/test_link_auth.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Update the link generator and app verification**

In `make_links.py`, replace local signing with `sign_subject_link`, add:

```python
parser.add_argument("--visit", choices=["daily", "V1", "V3", "V4", "V5", "V6"], default="daily")
```

Generate query parameters with `visit` only for formal links:

```python
sig = sign_subject_link(args.key, sid, exp_ts, args.visit)
query = {"sid": sid, "exp": exp_ts, "sig": sig}
if args.visit != "daily":
    query["visit"] = args.visit
link = f"{base}/?{urlencode(query)}"
```

In `app.py`, replace `_b64url`, `_sign_sid`, and `verify_link_params` internals with `verify_subject_link`. Store both verified values:

```python
verified = verify_subject_link(
    LINK_SIGNING_KEY,
    sid,
    exp,
    sig,
    q.get("visit", "daily"),
    now=int(datetime.now(timezone.utc).timestamp()),
)
if verified:
    st.session_state["subject_id"] = verified.subject_id
    st.session_state["visit"] = verified.visit
```

- [ ] **Step 6: Run link, generator, and syntax tests**

Run:

```powershell
python -m pytest tests/test_link_auth.py -v
python -m compileall -q app.py make_links.py link_auth.py
```

Expected: tests pass and compileall exits 0.

- [ ] **Step 7: Commit visit-aware links**

```powershell
git add link_auth.py make_links.py app.py tests/test_link_auth.py
git commit -m "feat: authenticate questionnaire visit links"
```

## Task 6: Implement the Alto-inspired questionnaire UI and flow controller

**Files:**
- Create: `tests/test_questionnaire_flow.py`
- Create: `tests/fixtures/questionnaire_app.py`
- Create: `questionnaire_ui.py`

- [ ] **Step 1: Write failing pure flow tests**

Create `tests/test_questionnaire_flow.py`:

```python
from questionnaire_ui import (
    build_field_status,
    build_formal_field_status,
    build_flow,
    formal_flow,
    validate_formal_submission,
    validate_submission,
)


def test_negative_daily_flow_contains_only_five_core_questions():
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
    }
    assert [step.id for step in build_flow(answers, intervention_day=6)] == [
        "nssi_thought_present_24h",
        "nssi_behavior_present_24h",
        "suicide_thought_present_24h",
        "nssi_urge_now",
        "nssi_resistance_confidence_now",
    ]


def test_positive_behavior_requires_a_nonzero_count():
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": True,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
        "nssi_cut_count_24h": 0,
        "nssi_burn_count_24h": 0,
        "nssi_scratch_count_24h": 0,
        "nssi_bite_count_24h": 0,
        "nssi_hit_object_count_24h": 0,
        "nssi_hit_self_count_24h": 0,
        "nssi_other_count_24h": 0,
        "nssi_medical_care_24h": False,
    }
    errors = validate_submission(answers, answered_field_ids=set(build_flow_ids := [step.id for step in build_flow(answers, 6)]), intervention_day=6)
    assert build_flow_ids
    assert "至少记录一类 NSSI 行为的实际次数" in errors


def test_weekly_questions_are_appended_only_when_due():
    base = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
    }
    assert len(build_flow(base, 7)) > len(build_flow(base, 6))


def test_formal_validation_requires_every_active_question_and_skips_inactive_branches():
    answers = {
        "nssi_ideation_6m_present": False,
        "nssi_ideation_1m_present": False,
    }
    flow = formal_flow("V1", answers)
    ids = {question.id for question in flow}
    assert "nssi_ideation_6m_frequency" not in ids
    assert "nssi_ideation_1m_intensity" not in ids
    answers.update({question.id: question.min_value if question.kind == "slider" else False for question in flow})
    answered = set(ids)
    assert validate_formal_submission("V1", answers, answered) == []
    missing_id = flow[0].id
    assert validate_formal_submission("V1", answers, answered - {missing_id}) == [f"未完成：{flow[0].prompt}"]


def test_field_status_distinguishes_missing_from_not_applicable():
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
    }
    statuses = build_field_status(answers, {"nssi_thought_present_24h"}, intervention_day=6)
    assert statuses["nssi_thought_present_24h"] == "answered"
    assert statuses["nssi_urge_now"] == "missing"
    assert statuses["nssi_cut_count_24h"] == "not_applicable"

    formal_answers = {
        "nssi_ideation_6m_present": False,
        "nssi_ideation_1m_present": False,
    }
    formal_statuses = build_formal_field_status("V1", formal_answers, set(formal_answers))
    assert formal_statuses["nssi_ideation_6m_present"] == "answered"
    assert formal_statuses["nssi_ideation_6m_frequency"] == "not_applicable"
    assert formal_statuses["dshi_lifetime_1"] == "missing"
```

- [ ] **Step 2: Verify the UI module is missing**

Run:

```powershell
python -m pytest tests/test_questionnaire_flow.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'questionnaire_ui'`.

- [ ] **Step 3: Implement pure flow construction and validation**

Create `questionnaire_ui.py` with these public functions before adding Streamlit rendering:

```python
from __future__ import annotations

from typing import Any, Mapping, Sequence

import streamlit as st

from questionnaire_specs import DAILY_CONDITIONAL, DAILY_CORE, FORMAL_INSTRUMENTS, VISIT_INSTRUMENT_IDS, WEEKLY_INSTRUMENTS, QuestionSpec, weekly_due
from questionnaire_scoring import COUNT_FIELDS

ALTO_COLORS = {
    "black": "#050505",
    "purple": "#2D2674",
    "blue": "#33B0E4",
    "magenta": "#DD1D86",
    "orange": "#FF8D2A",
}


def build_flow(answers: Mapping[str, Any], intervention_day: int) -> list[QuestionSpec]:
    flow: list[QuestionSpec] = []
    for core in DAILY_CORE:
        flow.append(core)
        flow.extend(q for q in DAILY_CONDITIONAL if q.show_if == (core.id, answers.get(core.id)))
    if weekly_due(intervention_day):
        flow.extend(question for instrument in WEEKLY_INSTRUMENTS for question in instrument.questions)
    return flow


def validate_submission(answers: Mapping[str, Any], answered_field_ids: set[str], intervention_day: int) -> list[str]:
    flow = build_flow(answers, intervention_day)
    errors = [f"未完成：{question.prompt}" for question in flow if question.required and question.id not in answered_field_ids]
    if answers.get("nssi_behavior_present_24h") is True and sum(int(answers.get(field, 0) or 0) for field in COUNT_FIELDS) == 0:
        errors.append("至少记录一类 NSSI 行为的实际次数")
    return errors


def formal_flow(visit: str, answers: Mapping[str, Any]) -> list[QuestionSpec]:
    flow: list[QuestionSpec] = []
    for instrument_id in VISIT_INSTRUMENT_IDS[visit]:
        for question in FORMAL_INSTRUMENTS[instrument_id].questions:
            if question.show_if is None or answers.get(question.show_if[0]) == question.show_if[1]:
                flow.append(question)
    return flow


def validate_formal_submission(visit: str, answers: Mapping[str, Any], answered_field_ids: set[str]) -> list[str]:
    return [
        f"未完成：{question.prompt}"
        for question in formal_flow(visit, answers)
        if question.required and question.id not in answered_field_ids
    ]


def build_field_status(
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
    intervention_day: int,
) -> dict[str, str]:
    active = {question.id for question in build_flow(answers, intervention_day)}
    all_questions = [*DAILY_CORE, *DAILY_CONDITIONAL]
    if weekly_due(intervention_day):
        all_questions.extend(question for instrument in WEEKLY_INSTRUMENTS for question in instrument.questions)
    return {
        question.id: (
            "not_applicable"
            if question.id not in active
            else "answered"
            if question.id in answered_field_ids
            else "missing"
        )
        for question in all_questions
    }


def build_formal_field_status(
    visit: str,
    answers: Mapping[str, Any],
    answered_field_ids: set[str],
) -> dict[str, str]:
    active = {question.id for question in formal_flow(visit, answers)}
    all_questions = [
        question
        for instrument_id in VISIT_INSTRUMENT_IDS[visit]
        for question in FORMAL_INSTRUMENTS[instrument_id].questions
    ]
    return {
        question.id: (
            "not_applicable"
            if question.id not in active
            else "answered"
            if question.id in answered_field_ids
            else "missing"
        )
        for question in all_questions
    }
```

- [ ] **Step 4: Run pure flow tests**

Run:

```powershell
python -m pytest tests/test_questionnaire_flow.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Add Alto CSS and active-answer rendering**

Add to `questionnaire_ui.py`:

```python
ALTO_CSS = """
<style>
:root { --alto-black:#050505; --alto-purple:#2D2674; --alto-blue:#33B0E4; --alto-magenta:#DD1D86; --alto-orange:#FF8D2A; }
.stApp { background:#FFFFFF; color:#050505; }
[data-testid="stHeader"] { background:#050505; }
[data-testid="stAppViewContainer"] > .main { background:#FFFFFF; }
.alto-top { background:#050505; color:#FFFFFF; padding:18px 24px; margin:-1rem -1rem 0; }
.alto-mark { font-size:1.35rem; font-weight:700; letter-spacing:0; }
.alto-progress { display:grid; grid-template-columns:repeat(4,1fr); height:8px; margin:0 -1rem 2rem; }
.alto-progress span:nth-child(1) { background:#2D2674; }
.alto-progress span:nth-child(2) { background:#33B0E4; }
.alto-progress span:nth-child(3) { background:#DD1D86; }
.alto-progress span:nth-child(4) { background:#FF8D2A; }
.alto-kicker { color:#DD1D86; font-size:.82rem; font-weight:700; text-transform:uppercase; }
.alto-endpoints { display:flex; justify-content:space-between; color:#42424C; font-size:.82rem; }
div[data-testid="stSlider"] [role="slider"] { border-color:#DD1D86; }
div[data-testid="stSlider"] > div > div > div { color:#DD1D86; }
.stButton > button[kind="primary"] { background:#050505; color:#FFFFFF; border:0; border-bottom:4px solid #DD1D86; border-radius:0; }
.stButton > button { border-radius:0; }
@media (max-width: 720px) { .alto-top { padding:14px 18px; } h1,h2,h3 { font-size:clamp(1.25rem,6vw,1.7rem)!important; } }
</style>
"""


def inject_alto_theme(subject_id: str, intervention_day: int, current: int, total: int) -> None:
    st.markdown(ALTO_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="alto-top"><div class="alto-mark">YMH <small>NEUROSCIENCE LAB</small></div><div>{subject_id} · 第 {intervention_day} 天</div></div>'
        '<div class="alto-progress"><span></span><span></span><span></span><span></span></div>'
        f'<div class="alto-kicker">过去 24 小时 · {current} / {total}</div>',
        unsafe_allow_html=True,
    )


def _mark_answered(field_id: str) -> None:
    answered = set(st.session_state.get("answered_field_ids", []))
    answered.add(field_id)
    st.session_state["answered_field_ids"] = sorted(answered)


def render_question(question: QuestionSpec) -> Any:
    key = f"q_{question.id}"
    if question.kind == "boolean":
        return st.radio(question.prompt, (False, True), format_func=lambda value: "有" if value else "没有", index=None, horizontal=True, key=key, on_change=_mark_answered, args=(question.id,))
    if question.kind == "slider":
        value = st.slider(question.prompt, question.min_value, question.max_value, key=key, on_change=_mark_answered, args=(question.id,))
        st.markdown(f'<div class="alto-endpoints"><span>{question.min_value} {question.low_label}</span><span>{question.max_value} {question.high_label}</span></div>', unsafe_allow_html=True)
        return value
    if question.kind == "integer":
        return st.number_input(question.prompt, min_value=question.min_value or 0, value=None, step=1, placeholder="请输入次数", key=key, on_change=_mark_answered, args=(question.id,))
    if question.kind == "multiselect":
        return st.multiselect(question.prompt, question.options, key=key, on_change=_mark_answered, args=(question.id,))
    return st.text_area(question.prompt, key=key, on_change=_mark_answered, args=(question.id,))
```

- [ ] **Step 6: Add the one-question controller and save callback**

Add to `questionnaire_ui.py`:

```python
def render_questionnaire(
    *,
    subject_id: str,
    intervention_day: int,
    answers: dict[str, Any],
    save_draft,
    visit: str = "daily",
) -> tuple[dict[str, Any], bool]:
    answered = set(st.session_state.get("answered_field_ids", []))
    flow = build_flow(answers, intervention_day) if visit == "daily" else formal_flow(visit, answers)
    step_key = f"question_step_{visit}"
    step = min(int(st.session_state.get(step_key, 0)), max(len(flow) - 1, 0))
    inject_alto_theme(subject_id, intervention_day, step + 1, len(flow))
    pending_error = st.session_state.pop(f"questionnaire_error_{visit}", None)
    if pending_error:
        st.error(pending_error)
    question = flow[step]
    value = render_question(question)
    if question.id in set(st.session_state.get("answered_field_ids", [])):
        answers[question.id] = value

    left, right = st.columns([1, 3])
    if left.button("←", disabled=step == 0, help="返回上一题"):
        st.session_state[step_key] = step - 1
        save_draft(answers, set(st.session_state.get("answered_field_ids", [])))
        st.rerun()
    if right.button("继续" if step < len(flow) - 1 else "检查并提交", type="primary"):
        answered = set(st.session_state.get("answered_field_ids", []))
        if question.required and question.id not in answered:
            st.error("请先确认当前答案。")
            return answers, False
        if step < len(flow) - 1:
            st.session_state[step_key] = step + 1
            save_draft(answers, answered)
            st.rerun()
        save_draft(answers, answered)
        errors = (
            validate_submission(answers, answered, intervention_day)
            if visit == "daily"
            else validate_formal_submission(visit, answers, answered)
        )
        if errors:
            missing_indices = [
                index
                for index, item in enumerate(flow)
                if item.required and item.id not in answered
            ]
            if missing_indices:
                st.session_state[step_key] = missing_indices[0]
                st.session_state[f"questionnaire_error_{visit}"] = errors[0]
                save_draft(answers, answered)
                st.rerun()
            for error in errors:
                st.error(error)
            return answers, False
        return answers, True
    return answers, False
```

- [ ] **Step 7: Create a Streamlit fixture and assert participant text does not expose scores**

Create `tests/fixtures/questionnaire_app.py`:

```python
import streamlit as st

from questionnaire_ui import render_questionnaire

answers = st.session_state.setdefault("fixture_answers", {})


def save_draft(updated, answered):
    st.session_state["fixture_answers"] = dict(updated)
    st.session_state["fixture_answered"] = sorted(answered)


render_questionnaire(subject_id="sub-001", intervention_day=7, answers=answers, save_draft=save_draft)
```

Append to `tests/test_questionnaire_flow.py`:

```python
from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_participant_fixture_hides_score_and_risk_labels():
    fixture = Path(__file__).parent / "fixtures" / "questionnaire_app.py"
    app = AppTest.from_file(str(fixture), default_timeout=10).run()
    assert not app.exception
    visible = str(app)
    assert "总分" not in visible
    assert "高风险" not in visible
```

- [ ] **Step 8: Run flow and Streamlit fixture tests**

Run:

```powershell
python -m pytest tests/test_questionnaire_flow.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit the questionnaire UI**

```powershell
git add questionnaire_ui.py tests/test_questionnaire_flow.py tests/fixtures/questionnaire_app.py
git commit -m "feat: add adaptive Alto-style questionnaire flow"
```

## Task 7: Make JSON/video upload ordering deterministic and deletion safe

**Files:**
- Create: `tests/test_upload_workflow.py`
- Create: `upload_workflow.py`

- [ ] **Step 1: Write failing upload-order and cleanup tests**

Create `tests/test_upload_workflow.py`:

```python
import json
from pathlib import Path

import pytest

from upload_workflow import upload_record_bundle


def test_json_is_resynced_after_video_and_cleanup_includes_original_flv(tmp_path):
    json_path = tmp_path / "record.json"
    video_path = tmp_path / "record.mp4"
    original_flv = tmp_path / "record.flv"
    json_path.write_text('{"upload": {"json": "pending", "video": "pending"}}', encoding="utf-8")
    video_path.write_bytes(b"video")
    original_flv.write_bytes(b"source")
    calls = []

    def upload(local_path, remote_path, progress_cb=None):
        calls.append((Path(local_path).suffix, remote_path))
        return {"ok": True}

    def persist_state(state):
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["upload"] = dict(state)
        json_path.write_text(json.dumps(payload), encoding="utf-8")

    result = upload_record_bundle(
        json_path,
        video_path,
        "/apps/collector/sub/date/id",
        upload,
        persist_state=persist_state,
        delete_after_upload=True,
        cleanup_paths=(original_flv,),
    )
    assert [suffix for suffix, _ in calls] == [".json", ".mp4", ".json"]
    assert result == {"json": "uploaded", "video": "uploaded"}
    assert not json_path.exists()
    assert not video_path.exists()
    assert not original_flv.exists()


def test_video_failure_preserves_both_local_files(tmp_path):
    json_path = tmp_path / "record.json"
    video_path = tmp_path / "record.flv"
    json_path.write_text("{}", encoding="utf-8")
    video_path.write_bytes(b"video")

    def upload(local_path, remote_path, progress_cb=None):
        if Path(local_path).suffix == ".flv":
            raise RuntimeError("video failed")
        return {"ok": True}

    def persist_state(state):
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["upload"] = dict(state)
        json_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="video failed"):
        upload_record_bundle(
            json_path,
            video_path,
            "/apps/collector/sub/date/id",
            upload,
            persist_state=persist_state,
            delete_after_upload=True,
        )
    assert json_path.exists()
    assert video_path.exists()


def test_final_json_sync_failure_preserves_json_video_and_original(tmp_path):
    json_path = tmp_path / "record.json"
    video_path = tmp_path / "record.mp4"
    original_flv = tmp_path / "record.flv"
    json_path.write_text('{"upload": {}}', encoding="utf-8")
    video_path.write_bytes(b"video")
    original_flv.write_bytes(b"source")
    json_upload_count = 0

    def upload(local_path, remote_path, progress_cb=None):
        nonlocal json_upload_count
        if Path(local_path).suffix == ".json":
            json_upload_count += 1
            if json_upload_count == 2:
                raise RuntimeError("final JSON sync failed")
        return {"ok": True}

    def persist_state(state):
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["upload"] = dict(state)
        json_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="final JSON sync failed"):
        upload_record_bundle(
            json_path,
            video_path,
            "/apps/collector/sub/date/id",
            upload,
            persist_state=persist_state,
            delete_after_upload=True,
            cleanup_paths=(original_flv,),
        )
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == {
        "json": "failed",
        "video": "uploaded",
    }
    assert json_path.exists()
    assert video_path.exists()
    assert original_flv.exists()
```

- [ ] **Step 2: Run upload tests and verify the missing module**

Run:

```powershell
python -m pytest tests/test_upload_workflow.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'upload_workflow'`.

- [ ] **Step 3: Implement upload sequencing**

Create `upload_workflow.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable


def upload_record_bundle(
    json_path: Path,
    video_path: Path,
    remote_dir: str,
    upload_fn: Callable,
    *,
    persist_state: Callable[[dict[str, str]], None],
    delete_after_upload: bool,
    cleanup_paths: Iterable[Path] = (),
    json_progress=None,
    video_progress=None,
) -> dict[str, str]:
    state = {"json": "pending", "video": "pending"}
    remote_json = f"{remote_dir}/{json_path.name}"
    try:
        upload_fn(json_path, remote_json, progress_cb=json_progress)
    except Exception:
        state["json"] = "failed"
        persist_state(state)
        raise
    state["json"] = "uploaded"
    try:
        upload_fn(video_path, f"{remote_dir}/{video_path.name}", progress_cb=video_progress)
        state["video"] = "uploaded"
    except Exception:
        state["video"] = "failed"
        persist_state(state)
        raise

    persist_state(state)
    try:
        upload_fn(json_path, remote_json, progress_cb=json_progress)
    except Exception:
        state["json"] = "failed"
        persist_state(state)
        raise

    if delete_after_upload and state == {"json": "uploaded", "video": "uploaded"}:
        for path in dict.fromkeys((json_path, video_path, *(Path(item) for item in cleanup_paths))):
            path.unlink(missing_ok=True)
    return state
```

- [ ] **Step 4: Run upload tests**

Run:

```powershell
python -m pytest tests/test_upload_workflow.py -v
```

Expected: 3 tests pass and the successful call order is JSON, video, finalized JSON.

- [ ] **Step 5: Commit upload workflow**

```powershell
git add upload_workflow.py tests/test_upload_workflow.py
git commit -m "feat: upload questionnaire records before video"
```

## Task 8: Integrate records, questionnaires, and upload into the recorder

**Files:**
- Modify: `app.py:12-32`
- Modify: `app.py:352-650`
- Create: `tests/test_app_integration.py`

- [ ] **Step 1: Write a failing integration contract test**

Create `tests/test_app_integration.py`:

```python
from pathlib import Path


def test_app_uses_record_scoped_questionnaire_and_upload_modules():
    source = Path("app.py").read_text(encoding="utf-8")
    assert "DailyRecordStore" in source
    assert "render_questionnaire" in source
    assert "upload_record_bundle" in source
    assert "remote_record_dir" in source
    assert "state_payload" in source


def test_app_does_not_silently_delete_after_partial_upload():
    source = Path("app.py").read_text(encoding="utf-8")
    upload_section = source[source.index("upload_record_bundle"):]
    assert "except Exception:\n                    pass" not in upload_section
    assert "persist_state=persist_upload_state" in upload_section
    assert "cleanup_paths=extra_cleanup_paths" in upload_section
```

- [ ] **Step 2: Verify the contract test fails against the current app**

Run:

```powershell
python -m pytest tests/test_app_integration.py -v
```

Expected: the first test fails because the new modules are not imported or used.

- [ ] **Step 3: Import the new modules and initialize one record per intervention day**

Add imports near `app.py:12-32`:

```python
from questionnaire_scoring import daily_derived_metrics, score_formal_instrument, score_sicq
from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_INSTRUMENTS,
    weekly_due,
)
from questionnaire_ui import build_field_status, build_formal_field_status, render_questionnaire
from record_store import DailyRecordStore, remote_record_dir, validate_subject_id
from upload_workflow import upload_record_bundle
```

After subject validation and before constructing the recorder path:

```python
try:
    subject_id = validate_subject_id(subject_id)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

record_date = datetime.now().date()
intervention_day = int(st.session_state.get("intervention_day", 1))
record_store = DailyRecordStore(REC_DIR)
record = record_store.get_or_create(subject_id, record_date, intervention_day)
st.session_state["record_id"] = record["record_id"]
base_name = record["record_id"]
flv_path = REC_DIR / f"{base_name}.flv"
```

Remove the rerun-dependent `ts` and `base_name = f"{subject_id}_{ts}"` construction.

- [ ] **Step 4: Preserve existing daily context and render NSSI questions only after recording**

Keep the existing sleep, mood, stress, pain, caffeine, exercise, narrative, trigger, and coping fields in `state_payload`.

After the recording has stopped and `final_play` exists, add:

```python
visit = st.session_state.get("visit", "daily")
if visit == "daily":
    questionnaire_answers = dict(record.get("daily_core", {}))
    questionnaire_answers.update(record.get("conditional_details", {}))
    questionnaire_answers.update(record.get("weekly_extension", {}))
else:
    formal_visit = record.setdefault("formal_visits", {}).setdefault(
        visit,
        {"raw_answers": {}, "instruments": {}},
    )
    questionnaire_answers = dict(formal_visit.get("raw_answers", {}))

completion = record.setdefault("completion", {})
answered_by_visit = completion.setdefault("answered_field_ids", {})
step_by_visit = completion.setdefault("current_step", {})
step_key = f"question_step_{visit}"
restore_key = f"questionnaire_restored_{record['record_id']}_{visit}"
if not st.session_state.get(restore_key):
    for key in [key for key in st.session_state if key.startswith("q_")]:
        del st.session_state[key]
    st.session_state["answered_field_ids"] = list(answered_by_visit.get(visit, []))
    st.session_state[step_key] = int(step_by_visit.get(visit, 0))
    for field_id, value in questionnaire_answers.items():
        st.session_state[f"q_{field_id}"] = value
    st.session_state[restore_key] = True

daily_core_ids = {question.id for question in DAILY_CORE}
conditional_ids = {question.id for question in DAILY_CONDITIONAL}
weekly_ids = {
    question.id
    for instrument in WEEKLY_INSTRUMENTS
    for question in instrument.questions
}
scored_formal_ids = {"dshi_lifetime", "dshi_12m", "fasm", "sicq", "readiness", "siss", "pss"}


def save_questionnaire_draft(updated, answered):
    answered_by_visit[visit] = sorted(answered)
    step_by_visit[visit] = int(st.session_state.get(step_key, 0))
    if visit == "daily":
        statuses = build_field_status(updated, set(answered), intervention_day)
        record["field_status"]["daily"] = statuses
        record["daily_core"] = {
            key: value for key, value in updated.items()
            if key in daily_core_ids and statuses.get(key) == "answered"
        }
        record["conditional_details"] = {
            key: value for key, value in updated.items()
            if key in conditional_ids and statuses.get(key) == "answered"
        }
        record["weekly_extension"] = {
            key: value for key, value in updated.items()
            if key in weekly_ids and statuses.get(key) == "answered"
        }
        record["derived_metrics"] = daily_derived_metrics(updated)
        if weekly_due(intervention_day):
            sicq_values = [updated.get(f"sicq_{index}") for index in range(1, 8)]
            sicq = score_sicq(sicq_values)
            record["derived_metrics"]["sicq_weekly"] = {
                "total": sicq.total,
                "complete": sicq.complete,
                "scored_items": sicq.scored_items,
            }
        record["safety_signals"] = {
            "suicide_thought_present_24h": updated.get("suicide_thought_present_24h"),
            "suicide_thought_frequency_24h": updated.get("suicide_thought_frequency_24h"),
            "medical_care_required_24h": updated.get("nssi_medical_care_24h"),
        }
    else:
        statuses = build_formal_field_status(visit, updated, set(answered))
        record["field_status"][visit] = statuses
        instruments = {}
        for instrument_id in VISIT_INSTRUMENT_IDS[visit]:
            spec = FORMAL_INSTRUMENTS[instrument_id]
            raw_answers = {
                question.id: updated[question.id]
                for question in spec.questions
                if statuses.get(question.id) == "answered" and question.id in updated
            }
            complete = all(statuses.get(question.id) != "missing" for question in spec.questions)
            score = (
                score_formal_instrument(instrument_id, updated)
                if instrument_id in scored_formal_ids
                else {"complete": complete}
            )
            scored_answers = dict(raw_answers)
            if instrument_id == "sicq" and "scored_items" in score:
                scored_answers = {
                    f"sicq_{index}": value
                    for index, value in enumerate(score["scored_items"], start=1)
                }
            instruments[instrument_id] = {
                "instrument_id": instrument_id,
                "instrument_version": record["instrument_versions"]["formal_nssi_crf"],
                "time_window": spec.time_window,
                "raw_answers": raw_answers,
                "scored_answers": scored_answers,
                "complete": complete,
                "score": score,
            }
        record["formal_visits"][visit] = {
            "raw_answers": dict(updated),
            "instruments": instruments,
        }
        record["safety_signals"][f"{visit}_pss_positive"] = any(
            updated.get(f"pss_{index}") is True for index in range(1, 6)
        )
    record_store.save(record)


questionnaire_answers, questionnaire_complete = render_questionnaire(
    subject_id=subject_id,
    intervention_day=intervention_day,
    answers=questionnaire_answers,
    save_draft=save_questionnaire_draft,
    visit=visit,
)
safety_signals = record.get("safety_signals", {})
safety_signal_present = (
    safety_signals.get("suicide_thought_present_24h") is True
    or any(key.endswith("_pss_positive") and value is True for key, value in safety_signals.items())
)
if safety_signal_present:
    st.warning("你的安全很重要。请立即联系研究团队或你信任的监护人；如果你正处于紧急危险中，请联系当地急救服务。")
    support_contact = str(_safe_secret("SAFETY_CONTACT", "")).strip()
    st.write(f"联系：{support_contact or '请使用知情同意书中提供的研究团队联系方式'}")
if not questionnaire_complete:
    st.stop()
```

Keep both daily and formal signed-link modes behind the approved recorder-first flow in this iteration: the questionnaire block renders only after a valid `final_play` exists. Do not add a separate baseline-without-recording route in this plan.

This keeps daily core, conditional, weekly, and formal answers in separate record sections. Inactive conditional fields are represented as `not_applicable` in `field_status`, while unanswered active fields remain `missing`. Formal instruments retain their ID, version, time window, raw answers, scored answers, completeness, and defined score without exposing those values to participants.

- [ ] **Step 5: Finalize JSON before upload and bind it to the video**

Replace the old metadata construction with:

```python
record["daily_context"] = st.session_state.get("state_payload", {})
record["recording"] = {
    "video_filename": final_play.name,
    "record_started_at_iso": st.session_state.get("record_started_at_iso", ""),
    "record_ended_at_iso": st.session_state.get("record_ended_at_iso", ""),
    "format": final_play.suffix.lower().lstrip("."),
}
record["completion"]["status"] = "complete"
meta_path = record_store.save(record)
remote_dir = remote_record_dir(SAVE_DIR, subject_id, record_date.strftime("%Y%m%d"), record["record_id"])
```

- [ ] **Step 6: Replace the upload button body with the safe bundle workflow**

Use two progress callbacks. The workflow uploads the draft JSON, uploads the selected video, persists the final upload state locally, then replaces the remote JSON with that finalized copy:

```python
def persist_upload_state(upload_state):
    record["upload"] = dict(upload_state)
    record_store.save(record)


extra_cleanup_paths = (flv_path,) if final_play != flv_path and flv_path.exists() else ()
state = upload_record_bundle(
    meta_path,
    final_play,
    remote_dir,
    upload_to_baidu,
    persist_state=persist_upload_state,
    delete_after_upload=delete_after_upload,
    cleanup_paths=extra_cleanup_paths,
    json_progress=on_prog_j,
    video_progress=on_prog_v,
)
st.success("今日记录和录像均已上传")
```

On an exception, preserve the JSON, selected upload video, and original FLV. Show a retry message containing the stable `record_id`, not the remote token response. Do not save again after successful cleanup because that would recreate the deleted JSON.

- [ ] **Step 7: Provide the minimum configured support block for a positive suicide item**

Place this block immediately after `render_questionnaire(...)` and before the incomplete-questionnaire `st.stop()`. This makes the support contact visible on the first rerun after a positive answer rather than waiting for final submission:

```python
safety_signals = record.get("safety_signals", {})
safety_signal_present = (
    safety_signals.get("suicide_thought_present_24h") is True
    or any(key.endswith("_pss_positive") and value is True for key, value in safety_signals.items())
)
if safety_signal_present:
    st.warning("你的安全很重要。请立即联系研究团队或你信任的监护人；如果你正处于紧急危险中，请联系当地急救服务。")
    support_contact = str(_safe_secret("SAFETY_CONTACT", "")).strip()
    st.write(f"联系：{support_contact or '请使用知情同意书中提供的研究团队联系方式'}")
```

Do not assign a risk level or trigger external notifications in this plan.

- [ ] **Step 8: Run integration, unit, and syntax tests**

Run:

```powershell
python -m pytest tests -v
python -m compileall -q app.py questionnaire_specs.py questionnaire_scoring.py questionnaire_ui.py record_store.py link_auth.py upload_workflow.py make_links.py
```

Expected: all tests pass and compileall exits 0.

- [ ] **Step 9: Commit the application integration**

```powershell
git add app.py tests/test_app_integration.py
git commit -m "feat: integrate NSSI questionnaires with recording"
```

## Task 9: Verify behavior, visuals, and recoverability end to end

**Files:**
- Create: `tests/test_questionnaire_end_to_end.py`
- Create: `docs/questionnaire-operations.md`

- [ ] **Step 1: Add an end-to-end record assembly test**

Create `tests/test_questionnaire_end_to_end.py`:

```python
from datetime import date

from questionnaire_scoring import daily_derived_metrics, score_sicq
from record_store import DailyRecordStore, remote_record_dir


def test_day_seven_record_contains_daily_weekly_video_and_upload_state(tmp_path):
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), 7)
    record["daily_core"] = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }
    record["weekly_extension"] = {f"sicq_{i}": value for i, value in enumerate((0, 0, 0, 0, 0, 0, 4), 1)}
    record["derived_metrics"] = daily_derived_metrics(record["daily_core"])
    record["derived_metrics"]["sicq_total"] = score_sicq([0, 0, 0, 0, 0, 0, 4]).total
    record["recording"] = {"video_filename": f"{record['record_id']}.flv", "format": "flv"}
    record["upload"] = {"json": "uploaded", "video": "uploaded"}
    path = store.save(record)
    loaded = store.get_or_create("sub-001", date(2026, 7, 24), 7)
    assert loaded["record_id"] == record["record_id"]
    assert loaded["derived_metrics"]["sicq_total"] == 0
    assert path.name.startswith(record["record_id"])
    assert remote_record_dir("/apps/collector", "sub-001", "20260724", record["record_id"]).endswith(record["record_id"])
```

- [ ] **Step 2: Run the full automated suite**

Run:

```powershell
python -m pytest tests -q
```

Expected: all tests pass with no warnings from project code.

- [ ] **Step 3: Start the local Streamlit server on an unused port**

Run:

```powershell
python -m streamlit run app.py --server.port 8502 --server.headless true --browser.gatherUsageStats false
```

Expected: Streamlit reports `Local URL: http://localhost:8502` and `/_stcore/health` returns `ok`.

- [ ] **Step 4: Exercise four browser scenarios**

Use the available browser-control surface against `http://localhost:8502` and capture desktop 1440x1000 plus mobile 390x844 screenshots for:

1. Negative daily path: five core questions, no condition branch, no visible score.
2. Positive NSSI behavior path: six behavior counts, other behavior, medical-care question, motives, trigger, and coping.
3. Day 7 path: weekly questions appended once; SICQ item 7 accepts raw 0-4 but no participant score appears.
4. Refresh path: answer two questions, refresh, and confirm the same `record_id`, step, and answers resume.

Expected for every screenshot: Alto black header, white body, purple/blue/magenta/orange progress, magenta slider, no overlap, no horizontal scroll, and no score/risk labels.

- [ ] **Step 5: Check slider accessibility and scaling**

For a 0-10 slider and a 1-100 slider:

- Move the thumb with arrow keys and confirm the value changes.
- Confirm endpoint labels remain visible at 390px width.
- Set browser zoom to 200% and complete one core question.
- Confirm an untouched default slider cannot advance.

Expected: all four checks pass.

- [ ] **Step 6: Verify upload failure recovery without calling production cloud APIs**

Run only the fake-upload tests:

```powershell
python -m pytest tests/test_upload_workflow.py tests/test_record_store.py -v
```

Expected: both suites pass; video failure and final-JSON-sync failure preserve every local file, while full success removes the JSON, uploaded video, and source FLV.

- [ ] **Step 7: Document the participant workflow and configuration**

Create `docs/questionnaire-operations.md` with:

```markdown
# NSSI Questionnaire Operations

## Link Modes

- Daily: signed links without a `visit` parameter remain compatible.
- Formal: generate links with `--visit V1`, `V3`, `V4`, `V5`, or `V6`.

## Required Configuration

- `LINK_SIGNING_KEY`: signs subject and formal-visit links.
- `SAFETY_CONTACT`: participant-visible research contact text.
- `[baidu]`: existing upload credentials and destination.

## Record Lifecycle

Each subject has one questionnaire record per intervention day. Drafts resume after refresh. The workflow uploads an initial questionnaire JSON, uploads the video, atomically saves final upload state, and re-uploads the finalized JSON. Local copies are deleted only after that final JSON sync succeeds.

## Measurement Boundary

Daily exact NSSI counts are dense longitudinal measures. Formal DSHI-Y scores remain separate and support the protocol outcome. The participant UI does not show scores or risk labels.
```

- [ ] **Step 8: Run final verification**

Run:

```powershell
python -m pytest tests -q
python -m compileall -q app.py questionnaire_specs.py questionnaire_scoring.py questionnaire_ui.py record_store.py link_auth.py upload_workflow.py make_links.py
git diff --check
git status --short
```

Expected: tests pass, compileall exits 0, `git diff --check` is silent, and status contains only intended code/docs changes or is clean after commits.

- [ ] **Step 9: Commit operations documentation and final verification fixes**

```powershell
git add docs/questionnaire-operations.md tests/test_questionnaire_end_to_end.py app.py questionnaire_specs.py questionnaire_scoring.py questionnaire_ui.py record_store.py link_auth.py upload_workflow.py make_links.py tests
git commit -m "test: verify NSSI questionnaire workflow"
```

## Completion Gate

Before claiming implementation complete, confirm all of the following in fresh command output:

- `python -m pytest tests -q` passes.
- `python -m compileall -q ...` exits 0.
- A negative daily path, a positive conditional path, a day-7 weekly path, and a refresh-resume path were exercised.
- Desktop and mobile screenshots show the approved Alto visual direction without overlap or clipping.
- The participant view contains no score, risk level, remote path, upload token response, or operations expander.
- JSON and video share one stable `record_id`.
- A partial upload or failed final JSON sync cannot trigger deletion; converted videos also retain the source FLV until full success.
- Formal V5 includes DSHI-Y and follows the V4 instrument mapping.
