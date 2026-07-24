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
                high_label="极其可能",
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
                low_label="根本不想停止",
                high_label="绝对想停止",
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
