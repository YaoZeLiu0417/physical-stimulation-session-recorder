from dataclasses import dataclass
from typing import Literal, Mapping


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
    show_if: tuple[str, object] | None = None


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

_BEHAVIOR_PRESENT = ("nssi_behavior_present_24h", True)

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
    QuestionSpec("nssi_cut_count_24h", "割伤皮肤的实际次数", "integer", min_value=0, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_burn_count_24h", "烧伤或烫伤皮肤的实际次数", "integer", min_value=0, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_scratch_count_24h", "严重抓挠至留下伤痕或流血的实际次数", "integer", min_value=0, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_bite_count_24h", "咬伤自己至皮肤破损的实际次数", "integer", min_value=0, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_hit_object_count_24h", "撞击头部或其他身体部位至出现瘀伤的实际次数", "integer", min_value=0, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_hit_self_count_24h", "捶打自己至出现瘀伤的实际次数", "integer", min_value=0, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_other_description_24h", "其他 NSSI 行为", "text", required=False, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_other_count_24h", "其他 NSSI 行为的实际次数", "integer", min_value=0, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_medical_care_24h", "是否因本次行为需要医疗处理？", "boolean", show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_motives_24h", "这次行为与哪些原因有关？", "multiselect", required=False, options=FASM_MOTIVES, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_trigger_24h", "触发情境", "text", required=False, show_if=_BEHAVIOR_PRESENT),
    QuestionSpec("nssi_coping_24h", "你采用了哪些应对方式？", "text", required=False, show_if=_BEHAVIOR_PRESENT),
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

WEEKLY_INSTRUMENTS = (
    InstrumentSpec(
        "nssi_impulse_weekly",
        "自伤冲动",
        "过去一周",
        (
            QuestionSpec(
                "nssi_impulse_time",
                "过去一周里，你多长时间想过伤害自己？",
                "slider",
                min_value=1,
                max_value=100,
                low_label="从不",
                high_label="几乎所有时间",
            ),
            QuestionSpec(
                "nssi_impulse_resistance",
                "过去一周里，抵制伤害自己有多难？",
                "slider",
                min_value=1,
                max_value=7,
                low_label="完全不难",
                high_label="无法抵制",
            ),
        ),
    ),
    InstrumentSpec(
        "nssi_future_weekly",
        "未来 NSSI 可能性",
        "当前",
        (
            QuestionSpec(
                "nssi_future_likelihood",
                "你认为未来发生 NSSI 的可能性有多大？",
                "slider",
                min_value=0,
                max_value=4,
                low_label="完全不会",
                high_label="极其",
            ),
        ),
    ),
    InstrumentSpec(
        "nssi_stop_weekly",
        "停止未来 NSSI 的愿望",
        "当前",
        (
            QuestionSpec(
                "nssi_stop_desire",
                "你有多想停止 NSSI？",
                "slider",
                min_value=0,
                max_value=4,
                low_label="我根本不想停止",
                high_label="我绝对想停止",
            ),
        ),
    ),
    InstrumentSpec(
        "sicq_weekly",
        "自伤渴望问卷",
        "当前",
        tuple(
            QuestionSpec(
                f"sicq_{index}",
                prompt,
                "slider",
                min_value=0,
                max_value=4,
                low_label="非常不同意",
                high_label="非常同意",
            )
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
            QuestionSpec(
                "readiness_importance",
                "采取措施停止自我伤害对我来说很重要。",
                "slider",
                min_value=1,
                max_value=10,
                low_label="完全不符合",
                high_label="完全符合",
            ),
            QuestionSpec(
                "readiness_ready",
                "我已经准备好采取措施停止自我伤害。",
                "slider",
                min_value=1,
                max_value=10,
                low_label="完全不符合",
                high_label="完全符合",
            ),
            QuestionSpec(
                "readiness_confidence",
                "我相信我可以采取措施停止自我伤害。",
                "slider",
                min_value=1,
                max_value=10,
                low_label="完全不符合",
                high_label="完全符合",
            ),
        ),
    ),
)


def _likert(
    id_: str,
    prompt: str,
    minimum: int,
    maximum: int,
    show_if: tuple[str, object] | None = None,
    *,
    low_label: str = "",
    high_label: str = "",
) -> QuestionSpec:
    return QuestionSpec(
        id_,
        prompt,
        "slider",
        min_value=minimum,
        max_value=maximum,
        low_label=low_label,
        high_label=high_label,
        show_if=show_if,
    )


def _instrument(
    id_: str,
    label: str,
    time_window: str,
    questions: tuple[QuestionSpec, ...],
) -> InstrumentSpec:
    return InstrumentSpec(id_, label, time_window, questions)


def _weekly_questions(instrument_id: str) -> tuple[QuestionSpec, ...]:
    return next(
        instrument.questions
        for instrument in WEEKLY_INSTRUMENTS
        if instrument.id == instrument_id
    )


def _weekly_question(question_id: str) -> QuestionSpec:
    return next(
        question
        for instrument in WEEKLY_INSTRUMENTS
        for question in instrument.questions
        if question.id == question_id
    )


def _likert_like_weekly(
    id_: str, prompt: str, source_id: str | None = None
) -> QuestionSpec:
    source = _weekly_question(source_id or id_)
    return _likert(
        id_,
        prompt,
        source.min_value,
        source.max_value,
        low_label=source.low_label,
        high_label=source.high_label,
    )


DSHI_BEHAVIORS = (
    "故意用玻璃、小刀等划伤自己的皮肤",
    "故意用烟头、打火机或其他东西烧伤或烫伤自己的皮肤",
    "故意猛烈抓挠自己，达到留下伤痕或流血的程度",
    "故意咬自己以致皮肤破损",
    "故意用头撞击某物，以致出现瘀伤",
    "故意捶打自己以致出现瘀伤",
)

FASM_ITEMS = FASM_MOTIVES
SICQ_ITEMS = tuple(question.prompt for question in _weekly_questions("sicq_weekly"))
READINESS_ITEMS = tuple(
    question.prompt for question in _weekly_questions("readiness_weekly")
)

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

_NSSI_IDEATION_6M_PRESENT = "nssi_ideation_6m_present"
_NSSI_IDEATION_1M_PRESENT = "nssi_ideation_1m_present"

FORMAL_INSTRUMENTS = {
    "dshi_lifetime": _instrument(
        "dshi_lifetime",
        "故意自伤量表-青少年版（终生）",
        "从有记忆到目前",
        tuple(
            _likert(
                f"dshi_lifetime_{index}",
                prompt,
                1,
                5,
                low_label="我从未这样做过",
                high_label="做过超过10次",
            )
            for index, prompt in enumerate(DSHI_BEHAVIORS, start=1)
        ),
    ),
    "dshi_12m": _instrument(
        "dshi_12m",
        "故意自伤量表-青少年版（过去一年）",
        "过去一年",
        tuple(
            _likert(
                f"dshi_12m_{index}",
                prompt,
                1,
                5,
                low_label="我从未这样做过",
                high_label="做过超过10次",
            )
            for index, prompt in enumerate(DSHI_BEHAVIORS, start=1)
        ),
    ),
    "fasm": _instrument(
        "fasm",
        "中文版自伤功能评估量表",
        "根据已报告的自伤行为",
        tuple(
            _likert(
                f"fasm_{index}",
                prompt,
                0,
                3,
                low_label="从不",
                high_label="经常",
            )
            for index, prompt in enumerate(FASM_ITEMS, start=1)
        ),
    ),
    "nssi_ideation": _instrument(
        "nssi_ideation",
        "自伤意念",
        "过去六个月及过去一个月",
        (
            QuestionSpec(
                _NSSI_IDEATION_6M_PRESENT,
                "过去六个月中，是否有过想故意伤害自己但并不想死的想法？",
                "boolean",
            ),
            _likert(
                "nssi_ideation_6m_frequency",
                "过去六个月中，自伤想法出现的频率",
                1,
                6,
                (_NSSI_IDEATION_6M_PRESENT, True),
                low_label="1月1次",
                high_label="几乎每天",
            ),
            _likert(
                "nssi_ideation_6m_intensity",
                "过去六个月中，自伤想法的强度",
                1,
                5,
                (_NSSI_IDEATION_6M_PRESENT, True),
                low_label="很弱",
                high_label="很强",
            ),
            QuestionSpec(
                _NSSI_IDEATION_1M_PRESENT,
                "过去一个月中，是否有过自伤想法？",
                "boolean",
            ),
            _likert(
                "nssi_ideation_1m_frequency",
                "过去一个月中，自伤想法出现的频率",
                1,
                6,
                (_NSSI_IDEATION_1M_PRESENT, True),
                low_label="只有1次/很少",
                high_label="很多",
            ),
            _likert(
                "nssi_ideation_1m_intensity",
                "过去一个月中，自伤想法的强度",
                1,
                5,
                (_NSSI_IDEATION_1M_PRESENT, True),
                low_label="很弱",
                high_label="很强",
            ),
        ),
    ),
    "nssi_impulse": _instrument(
        "nssi_impulse",
        "自伤冲动",
        "过去一周",
        (
            _likert_like_weekly(
                "nssi_impulse_time", "过去一周里，你多长时间想过伤害自己？"
            ),
            _likert_like_weekly(
                "nssi_impulse_resistance", "过去一周里，抵制伤害自己有多难？"
            ),
        ),
    ),
    "nssi_future": _instrument(
        "nssi_future",
        "未来 NSSI 可能性",
        "当前",
        (
            _likert_like_weekly(
                "nssi_future_likelihood", "你认为未来发生 NSSI 的可能性有多大？"
            ),
        ),
    ),
    "nssi_stop": _instrument(
        "nssi_stop",
        "停止未来 NSSI 的愿望",
        "当前",
        (_likert_like_weekly("nssi_stop_desire", "你有多想停止 NSSI？"),),
    ),
    "sicq": _instrument(
        "sicq",
        "自伤渴望问卷",
        "当前",
        tuple(
            _likert_like_weekly(f"sicq_{index}", prompt)
            for index, prompt in enumerate(SICQ_ITEMS, start=1)
        ),
    ),
    "readiness": _instrument(
        "readiness",
        "准备改变自伤",
        "当前",
        tuple(
            _likert_like_weekly(f"readiness_{index}", prompt, source_id)
            for index, (prompt, source_id) in enumerate(
                zip(
                    READINESS_ITEMS,
                    (
                        "readiness_importance",
                        "readiness_ready",
                        "readiness_confidence",
                    ),
                    strict=True,
                ),
                start=1,
            )
        ),
    ),
    "siss": _instrument(
        "siss",
        "自伤耻感量表",
        "当前",
        tuple(
            _likert(
                f"siss_{index}",
                prompt,
                1,
                5,
                low_label="非常不同意",
                high_label="非常同意",
            )
            for index, prompt in enumerate(SISS_ITEMS, start=1)
        ),
    ),
    "pss": _instrument(
        "pss",
        "Paykel 自杀量表",
        "过去一年",
        tuple(
            QuestionSpec(f"pss_{index}", prompt, "boolean")
            for index, prompt in enumerate(PSS_ITEMS, start=1)
        ),
    ),
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
_FOLLOW_UP_WITHOUT_FASM = tuple(
    instrument_id for instrument_id in _FULL_FORMAL if instrument_id != "fasm"
)
VISIT_INSTRUMENT_IDS = {
    "V1": _FULL_FORMAL,
    "V3": _FULL_FORMAL,
    "V4": _FOLLOW_UP_WITHOUT_FASM,
    "V5": _FOLLOW_UP_WITHOUT_FASM,
    "V6": _FULL_FORMAL,
}

WEEKLY_DAYS = frozenset({7, 14, 21, 28})


def weekly_due(intervention_day: int) -> bool:
    return intervention_day in WEEKLY_DAYS


def active_daily_question_ids(answers: Mapping[str, object]) -> tuple[str, ...]:
    active = [question.id for question in DAILY_CORE]
    for question in DAILY_CONDITIONAL:
        if question.show_if is not None:
            answer_id, expected_value = question.show_if
            if answers.get(answer_id) == expected_value:
                active.append(question.id)
    return tuple(active)
