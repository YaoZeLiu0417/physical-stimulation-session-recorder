"""Shared presentation primitives for the local-first session flow."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

import streamlit as st


PALETTE = {
    "navy": "#000035",
    "violet": "#2D2674",
    "rose": "#DD1D86",
    "cyan": "#33B0E4",
    "peach": "#FFBC7D",
    "mist": "#F4F5F7",
    "white": "#FFFFFF",
}


@dataclass(frozen=True)
class OperationalStage:
    number: int
    english: str
    chinese: str


STAGES = (
    OperationalStage(1, "Controlled access", "受控进入"),
    OperationalStage(2, "Daily context", "当日状态"),
    OperationalStage(3, "Browser-local recording", "本地音视频"),
    OperationalStage(4, "Stepwise questionnaire", "分步结构化作答"),
    OperationalStage(5, "Local response package", "本地资料包"),
    OperationalStage(6, "Completion confirmation", "完成确认"),
)


OPERATIONAL_CSS = """<style>
:root {
  --operational-navy: #000035;
  --operational-violet: #2D2674;
  --operational-rose: #DD1D86;
  --operational-cyan: #33B0E4;
  --operational-peach: #FFBC7D;
  --operational-mist: #F4F5F7;
  --operational-white: #FFFFFF;
}
.stApp { background: var(--operational-mist); color: var(--operational-navy); }
.operational-rail {
  box-sizing: border-box; position: fixed; inset: 0 auto 0 0; width: 252px; padding: 28px 22px;
  background: var(--operational-navy); color: var(--operational-white); z-index: 10;
}
.block-container {
  margin-left: 252px; width: calc(100% - 252px); max-width: none; box-sizing: border-box;
}
.operational-brand { margin: 0 0 32px; font-size: 12px; font-weight: 700; letter-spacing: 0; line-height: 1.5; }
.operational-brand span { display: block; color: var(--operational-cyan); }
.operational-stages { display: grid; gap: 8px; }
.operational-stage { display: grid; grid-template-columns: 32px 1fr; gap: 10px; align-items: center; padding: 8px; border-radius: 6px; color: var(--operational-white); }
.operational-stage__number { color: var(--operational-violet); font-weight: 700; }
.operational-stage__label { display: block; font-size: 13px; line-height: 1.25; }
.operational-stage__label small { display: block; color: inherit; font-size: 12px; }
.operational-stage--completed { color: var(--operational-cyan); }
.operational-stage--completed .operational-stage__number { color: var(--operational-cyan); }
.operational-stage--active { background: var(--operational-rose); color: var(--operational-white); }
.operational-stage--active .operational-stage__number { background: var(--operational-rose); border: 2px solid var(--operational-rose); color: var(--operational-white); outline: 2px solid var(--operational-white); outline-offset: 2px; }
.operational-heading { display: grid; gap: 8px; max-width: 960px; margin: 0 auto 24px; }
.operational-heading__counter { color: var(--operational-violet); font-size: 13px; font-weight: 700; letter-spacing: 0; }
.operational-heading h1 { margin: 0; color: var(--operational-navy); font-size: 28px; letter-spacing: 0; }
.operational-heading p { margin: 0; color: var(--operational-violet); }
.questionnaire-context, .questionnaire-endpoints { display: flex; flex-wrap: wrap; gap: 8px; color: var(--operational-violet); }
.operational-status { display: inline-block; padding: 8px 12px; border-radius: 6px; background: var(--operational-violet); color: var(--operational-white); }
.operational-status--ready { background: var(--operational-cyan); color: var(--operational-navy); }
.operational-status--checkpoint { background: var(--operational-peach); color: var(--operational-navy); }
.operational-status--blocking { background: var(--operational-rose); color: var(--operational-white); }
.stButton > button { border-radius: 6px; background: var(--operational-rose); color: var(--operational-white); white-space: normal; }
.stButton > button:focus-visible, button:focus-visible, input:focus-visible, textarea:focus-visible, select:focus-visible { outline: 3px solid var(--operational-cyan); outline-offset: 2px; }
.stTextInput input, .stTextArea textarea, .stSelectbox select, .stNumberInput input { border-radius: 6px; }
iframe { aspect-ratio: 16 / 9; max-width: 100%; }
.operational-mobile, .operational-progress { display: none; }
@media (max-width: 840px) {
  .operational-rail { display: none; }
  .operational-mobile { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; background: var(--operational-navy); color: var(--operational-white); }
  .operational-progress { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 4px; padding: 10px 16px; background: var(--operational-white); }
  .operational-progress__segment { height: 6px; border-radius: 6px; background: var(--operational-violet); }
  .operational-progress__segment--completed { background: var(--operational-cyan); }
  .operational-progress__segment--active { background: var(--operational-rose); }
  .block-container { margin-left: 0; width: auto; }
  [data-testid="stHorizontalBlock"] { flex-direction: column; }
  [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
  .stButton > button, .stTextInput, .stTextArea, .stSelectbox, .stNumberInput { width: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; scroll-behavior: auto !important; }
}
</style>"""


def _escape(value: object) -> str:
    return escape(str(value), quote=True)


def _stage(active_stage: int) -> OperationalStage:
    if isinstance(active_stage, bool) or not isinstance(active_stage, int) or not 1 <= active_stage <= len(STAGES):
        raise ValueError("active stage must be an integer from 1 to 6")
    return STAGES[active_stage - 1]


def _stage_row(stage: OperationalStage, active_stage: int) -> str:
    state = "active" if stage.number == active_stage else "completed" if stage.number < active_stage else "future"
    current = ' aria-current="step"' if state == "active" else ""
    return (
        f'<div class="operational-stage operational-stage--{_escape(state)}"{current}>'
        f'<span class="operational-stage__number">{_escape(f"{stage.number:02d}")}</span>'
        f'<span class="operational-stage__label">{_escape(stage.english)}<small>{_escape(stage.chinese)}</small></span>'
        "</div>"
    )


def _progress_segment(stage: OperationalStage, active_stage: int) -> str:
    state = "active" if stage.number == active_stage else "completed" if stage.number < active_stage else "future"
    current = ' aria-current="step"' if state == "active" else ""
    return f'<span class="operational-progress__segment operational-progress__segment--{_escape(state)}"{current}></span>'


def stage_shell_markup(
    active_stage: int, *, subject_id: object | None = None, intervention_day: object | None = None
) -> str:
    current_stage = _stage(active_stage)
    context = ""
    if subject_id is not None or intervention_day is not None:
        values = []
        if subject_id is not None:
            values.append(f"<span>{_escape(subject_id)}</span>")
        if intervention_day is not None:
            values.append(f"<span>第 {_escape(intervention_day)} 天</span>")
        context = f'<div class="questionnaire-context">{"".join(values)}</div>'
    rows = "".join(_stage_row(stage, active_stage) for stage in STAGES)
    progress = "".join(_progress_segment(stage, active_stage) for stage in STAGES)
    return f'''<aside class="operational-rail" aria-label="Session flow">
<p class="operational-brand">SESSION COMPANION<span>GUIDED LOCAL-FIRST FLOW</span></p>
<div class="operational-stages">{rows}</div>
</aside>
<header class="operational-mobile"><span>SESSION COMPANION</span><span>{_escape(f"{active_stage:02d}")} / 06</span></header>
<div class="operational-progress" aria-label="Session progress">{progress}</div>
<section class="operational-heading"><span class="operational-heading__counter">{_escape(f"{active_stage:02d}")} / 06</span><h1>{_escape(current_stage.english)}</h1><p>{_escape(current_stage.chinese)}</p>{context}</section>'''


def operational_status_markup(kind: str, message: object) -> str:
    if not isinstance(kind, str) or kind not in {"neutral", "ready", "checkpoint", "blocking"}:
        raise ValueError("status kind must be neutral, ready, checkpoint, or blocking")
    return f'<div class="operational-status operational-status--{_escape(kind)}" role="status">{_escape(message)}</div>'


def render_operational_stage(
    active_stage: int, *, subject_id: object | None = None, intervention_day: object | None = None
) -> None:
    st.markdown(OPERATIONAL_CSS, unsafe_allow_html=True)
    st.markdown(
        stage_shell_markup(active_stage, subject_id=subject_id, intervention_day=intervention_day),
        unsafe_allow_html=True,
    )


def render_operational_status(kind: str, message: object) -> None:
    st.markdown(operational_status_markup(kind, message), unsafe_allow_html=True)
