# README-Aligned Operational App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved README-aligned six-stage visual system to the protected Streamlit application while preserving its authentication, recording, questionnaire, export, and privacy behavior.

**Architecture:** Add a presentation-only `operational_ui.py` that owns the exact palette, responsive shell, stage vocabulary, and escaped markup. Keep state resolution and context-confirmation matching as pure helpers in `app_workflow.py`, while `app.py` remains the sole workflow owner and renders exactly one stage's controls per run. Remove the questionnaire's competing global shell but retain its escaped question context and counter.

**Tech Stack:** Python 3.13, Streamlit 1.37.1, Streamlit AppTest, pytest 8, HTML/CSS, the existing browser-local recorder custom component, Node 24 built-in test runner, Git, Streamlit Community Cloud, and in-app browser visual verification.

---

## Working Context

- Worktree: `D:\proj_taVNS\.worktrees\physical-stimulation-session-recorder\browser-local-recorder-operational`
- Branch: `feat/browser-local-recorder-operational`
- Approved design: `docs/superpowers/specs/2026-07-29-readme-aligned-operational-app-design.md`
- Baseline design commit: `84be9bc`
- Baseline focused verification: `202 passed` for `tests/test_questionnaire_flow.py tests/test_app_integration.py`; `44 passed` for `tests/js/test_recorder_core.mjs`.
- Do not edit the recorder JavaScript lifecycle, questionnaire wording/branching/scoring, export schemas, or local-only privacy boundary.
- Do not put visual-verification screenshots, passwords, signed links, or exported response packages in Git.

## File Structure

- Create `operational_ui.py`: immutable stage definitions, exact palette, shared static CSS, escaped rail/mobile/header markup, and Streamlit rendering boundary.
- Create `tests/test_operational_ui.py`: visual-token, stage-definition, escaping, responsive-shell, focus, and no-remote-asset contracts.
- Create `tests/test_app_workflow.py`: pure active-stage and daily-context confirmation matching tests.
- Modify `app_workflow.py`: pure stage resolver plus exact context-confirmation builder/matcher.
- Modify `app.py`: one-stage routing, daily-context gate, state clearing, shell calls, and rerun boundaries.
- Modify `tests/test_app_integration.py`: AppTest helpers and complete six-stage gate/regression coverage.
- Modify `questionnaire_ui.py`: remove the old global theme/header and retain only escaped question-local context markup.
- Modify `tests/test_questionnaire_flow.py`: replace obsolete black/orange shell contracts with question-local context tests.
- Modify `.streamlit/config.toml`: align Streamlit's native background surfaces with mist and white.

### Task 1: Add The Shared Six-Stage Presentation Module

**Files:**
- Create: `operational_ui.py`
- Create: `tests/test_operational_ui.py`
- Modify: `.streamlit/config.toml`

- [ ] **Step 1: Write the failing presentation contracts**

Create `tests/test_operational_ui.py` with these contracts:

```python
import re

import pytest

from operational_ui import (
    OPERATIONAL_CSS,
    PALETTE,
    STAGES,
    operational_status_markup,
    render_operational_stage,
    stage_shell_markup,
)


EXPECTED_STAGES = (
    (1, "Controlled access", "受控进入"),
    (2, "Daily context", "当日状态"),
    (3, "Browser-local recording", "本地音视频"),
    (4, "Stepwise questionnaire", "分步结构化作答"),
    (5, "Local response package", "本地资料包"),
    (6, "Completion confirmation", "完成确认"),
)


def test_palette_and_six_stage_vocabulary_match_the_readme():
    assert PALETTE == {
        "navy": "#000035",
        "violet": "#2D2674",
        "rose": "#DD1D86",
        "cyan": "#33B0E4",
        "peach": "#FFBC7D",
        "mist": "#F4F5F7",
        "white": "#FFFFFF",
    }
    assert tuple(
        (stage.number, stage.english, stage.chinese) for stage in STAGES
    ) == EXPECTED_STAGES


@pytest.mark.parametrize("active_stage", range(1, 7))
def test_shell_marks_one_active_stage_and_prior_stages_complete(active_stage):
    markup = stage_shell_markup(
        active_stage,
        subject_id="sub-001",
        intervention_day=6,
    )
    assert markup.count('aria-current="step"') == 2
    assert markup.count("operational-stage--active") == 1
    assert markup.count("operational-progress__segment--active") == 1
    assert markup.count("operational-stage--complete") == active_stage - 1
    assert markup.count("operational-progress__segment--complete") == active_stage - 1
    assert f"{active_stage:02d} / 06" in markup


def test_shell_escapes_every_dynamic_value():
    markup = stage_shell_markup(
        4,
        subject_id='<script id="subject">bad()</script>',
        intervention_day='<img src=x onerror="bad()">',
    )
    assert '<script id="subject">' not in markup
    assert "<img src=x" not in markup
    assert "&lt;script id=&quot;subject&quot;&gt;" in markup
    assert "&lt;img src=x onerror=&quot;bad()&quot;&gt;" in markup


def test_contextual_status_uses_approved_semantics_and_escapes_copy():
    assert operational_status_markup(
        "checkpoint",
        '<script id="status">bad()</script>',
    ) == (
        '<div class="operational-status operational-status--checkpoint" role="status">'
        "&lt;script id=&quot;status&quot;&gt;bad()&lt;/script&gt;"
        "</div>"
    )
    with pytest.raises(ValueError, match="status kind"):
        operational_status_markup("warning", "not an approved semantic")


@pytest.mark.parametrize("active_stage", (0, 7, True, "2"))
def test_shell_rejects_invalid_stage_indices(active_stage):
    with pytest.raises(ValueError, match="active stage"):
        stage_shell_markup(active_stage)


def test_css_has_exact_responsive_and_accessibility_contracts():
    assert all(value in OPERATIONAL_CSS for value in PALETTE.values())
    assert "@media (max-width: 840px)" in OPERATIONAL_CSS
    assert ".operational-rail" in OPERATIONAL_CSS
    assert ".operational-mobile" in OPERATIONAL_CSS
    assert ".operational-status--ready" in OPERATIONAL_CSS
    assert ".operational-status--checkpoint" in OPERATIONAL_CSS
    assert ".operational-status--blocking" in OPERATIONAL_CSS
    assert "grid-template-columns: repeat(6, minmax(0, 1fr))" in OPERATIONAL_CSS
    assert "aspect-ratio: 16 / 9" in OPERATIONAL_CSS
    assert ":focus-visible" in OPERATIONAL_CSS
    assert "letter-spacing: 0" in OPERATIONAL_CSS
    assert "white-space: normal" in OPERATIONAL_CSS
    assert "prefers-reduced-motion: reduce" in OPERATIONAL_CSS
    assert "gradient" not in OPERATIONAL_CSS.casefold()
    assert "vw" not in OPERATIONAL_CSS.casefold()
    assert not re.search(r"https?://|@import|url\s*\(", OPERATIONAL_CSS, re.I)


def test_renderer_emits_only_static_css_and_escaped_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "operational_ui.st.markdown",
        lambda body, **kwargs: calls.append((body, kwargs)),
    )
    render_operational_stage(
        3,
        subject_id='<script id="subject">bad()</script>',
        intervention_day=6,
    )
    assert calls == [
        (OPERATIONAL_CSS, {"unsafe_allow_html": True}),
        (
            stage_shell_markup(
                3,
                subject_id='<script id="subject">bad()</script>',
                intervention_day=6,
            ),
            {"unsafe_allow_html": True},
        ),
    ]
```

- [ ] **Step 2: Run the new contracts and verify the missing module failure**

Run:

```powershell
python -m pytest tests/test_operational_ui.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'operational_ui'`.

- [ ] **Step 3: Implement the immutable stage model and safe shell**

Create `operational_ui.py` with this public interface and behavior:

```python
"""README-aligned presentation primitives for the operational Streamlit app."""

from __future__ import annotations

import html
from dataclasses import dataclass

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


OPERATIONAL_CSS = """
<style>
:root {
  --session-navy: #000035;
  --session-violet: #2D2674;
  --session-rose: #DD1D86;
  --session-cyan: #33B0E4;
  --session-peach: #FFBC7D;
  --session-mist: #F4F5F7;
  --session-white: #FFFFFF;
  --session-line: #DDE1E8;
  --session-muted: #62647A;
}

html, body, [class*="css"] { letter-spacing: 0; }
.stApp { background: var(--session-mist); color: var(--session-navy); }
[data-testid="stHeader"], [data-testid="stDecoration"] { background: transparent; }
[data-testid="stAppViewContainer"] > .main { background: var(--session-mist); }
.block-container {
  box-sizing: border-box;
  margin-left: 252px;
  max-width: 1180px;
  min-height: 100vh;
  padding: 3rem 3.5rem 4rem;
  width: calc(100% - 252px);
}
.operational-rail {
  background: var(--session-navy);
  bottom: 0;
  box-sizing: border-box;
  color: var(--session-white);
  left: 0;
  overflow-y: auto;
  padding: 34px 24px;
  position: fixed;
  top: 0;
  width: 252px;
  z-index: 999;
}
.operational-brand { border-bottom: 1px solid #514B8B; padding-bottom: 24px; }
.operational-brand strong { display: block; font-size: 1rem; line-height: 1.25; }
.operational-brand span { color: #C9CAE0; display: block; font-size: .68rem; margin-top: 5px; }
.operational-stage-list { list-style: none; margin: 30px 0 0; padding: 0; }
.operational-stage {
  color: #D7D8E7;
  display: grid;
  gap: 12px;
  grid-template-columns: 32px minmax(0, 1fr);
  min-height: 70px;
  position: relative;
}
.operational-stage:not(:last-child)::after {
  background: #514B8B;
  content: "";
  height: 38px;
  left: 15px;
  position: absolute;
  top: 34px;
  width: 2px;
}
.operational-stage__number {
  align-items: center;
  border: 1px solid #7773A9;
  border-radius: 50%;
  display: flex;
  font-size: .72rem;
  height: 30px;
  justify-content: center;
  width: 30px;
}
.operational-stage__copy strong { display: block; font-size: .78rem; line-height: 1.25; }
.operational-stage__copy span { color: #AAACC4; display: block; font-size: .72rem; margin-top: 4px; }
.operational-stage--complete .operational-stage__number {
  background: var(--session-cyan);
  border-color: var(--session-cyan);
  color: var(--session-navy);
}
.operational-stage--future .operational-stage__number { border-color: var(--session-violet); }
.operational-stage--active { color: var(--session-white); }
.operational-stage--active .operational-stage__number {
  border: 3px solid var(--session-rose);
  color: var(--session-white);
}
.operational-stage--active .operational-stage__copy span { color: var(--session-white); }
.operational-mobile { display: none; }
.operational-heading { border-bottom: 1px solid var(--session-line); margin: 0 0 2rem; padding-bottom: 1.5rem; }
.operational-heading__chip { color: var(--session-rose); font-size: .75rem; font-weight: 750; text-transform: uppercase; }
.operational-heading h1 { color: var(--session-navy); font-size: 2rem; line-height: 1.18; margin: .55rem 0 0; }
.operational-heading h1 span { color: var(--session-violet); display: block; font-size: .95rem; font-weight: 600; margin-top: .45rem; }
.operational-heading__context { color: var(--session-muted); font-size: .82rem; margin-top: .8rem; overflow-wrap: anywhere; }
.operational-status {
  background: var(--session-white);
  border-left: 4px solid var(--session-violet);
  border-radius: 4px;
  color: var(--session-navy);
  margin: 1rem 0;
  padding: .8rem 1rem;
}
.operational-status--ready { background: #E7F7FD; border-left-color: var(--session-cyan); }
.operational-status--checkpoint { background: #FFF4E9; border-left-color: var(--session-peach); }
.operational-status--blocking { background: #FCEAF4; border-left-color: var(--session-rose); }
.questionnaire-context { color: var(--session-rose); font-size: .82rem; font-weight: 750; margin: 0 0 .8rem; }
.questionnaire-endpoints { color: var(--session-muted); display: flex; font-size: .82rem; gap: 1rem; justify-content: space-between; margin: -.35rem 0 1rem; }
.questionnaire-endpoints span { max-width: 48%; overflow-wrap: anywhere; }
.questionnaire-endpoints span:last-child { text-align: right; }
.stButton > button, .stDownloadButton > button { border-radius: 6px; min-height: 2.75rem; white-space: normal; }
.stButton > button[kind="primary"] { background: var(--session-rose); border-color: var(--session-rose); color: var(--session-white); }
.stButton > button:focus-visible, .stDownloadButton > button:focus-visible,
input:focus-visible, textarea:focus-visible, [role="slider"]:focus-visible,
[role="radio"]:focus-visible, [role="checkbox"]:focus-visible {
  outline: 3px solid var(--session-cyan) !important;
  outline-offset: 2px;
}
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 6px; }
iframe[title="browser_local_recorder.browser_local_recorder"] { aspect-ratio: 16 / 9; width: 100%; }

@media (max-width: 840px) {
  .operational-rail { display: none; }
  .operational-mobile {
    background: var(--session-navy);
    color: var(--session-white);
    display: block;
    margin: -1rem -1rem 1.75rem;
    padding: 16px;
  }
  .operational-mobile__row { align-items: flex-start; display: flex; gap: 16px; justify-content: space-between; }
  .operational-mobile__brand strong { display: block; font-size: .92rem; }
  .operational-mobile__brand span, .operational-mobile__current span { color: #C9CAE0; display: block; font-size: .68rem; margin-top: 3px; }
  .operational-mobile__current { max-width: 48%; text-align: right; }
  .operational-progress { display: grid; gap: 4px; grid-template-columns: repeat(6, minmax(0, 1fr)); margin-top: 14px; }
  .operational-progress__segment { background: #514B8B; height: 5px; }
  .operational-progress__segment--complete { background: var(--session-cyan); }
  .operational-progress__segment--active { background: var(--session-rose); }
  .block-container { margin-left: 0; max-width: none; padding: 1rem 1rem 3rem; width: 100%; }
  .operational-heading { margin-bottom: 1.5rem; }
  .operational-heading h1 { font-size: 1.55rem; }
  div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
  div[data-testid="column"] { flex: 1 1 100%; min-width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
}
</style>
"""


def _stage(active_stage: int) -> OperationalStage:
    if type(active_stage) is not int or not 1 <= active_stage <= len(STAGES):
        raise ValueError("active stage must be an integer from 1 to 6")
    return STAGES[active_stage - 1]


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def operational_status_markup(kind: str, message: object) -> str:
    if kind not in {"neutral", "ready", "checkpoint", "blocking"}:
        raise ValueError("status kind must be neutral, ready, checkpoint, or blocking")
    return (
        f'<div class="operational-status operational-status--{kind}" role="status">'
        f"{_escape(message)}</div>"
    )


def stage_shell_markup(
    active_stage: int,
    *,
    subject_id: object | None = None,
    intervention_day: object | None = None,
) -> str:
    current = _stage(active_stage)
    rail_rows = []
    progress_segments = []
    for item in STAGES:
        state = "complete" if item.number < active_stage else "active" if item.number == active_stage else "future"
        current_attribute = ' aria-current="step"' if state == "active" else ""
        rail_rows.append(
            f'<li class="operational-stage operational-stage--{state}"{current_attribute}>'
            f'<span class="operational-stage__number">{item.number:02d}</span>'
            '<span class="operational-stage__copy">'
            f'<strong>{_escape(item.english)}</strong><span>{_escape(item.chinese)}</span>'
            "</span></li>"
        )
        progress_segments.append(
            f'<span class="operational-progress__segment operational-progress__segment--{state}"{current_attribute}></span>'
        )
    context_parts = []
    if subject_id is not None:
        context_parts.append(_escape(subject_id))
    if intervention_day is not None:
        context_parts.append(f"第 {_escape(intervention_day)} 天")
    context_markup = (
        f'<div class="operational-heading__context">{" · ".join(context_parts)}</div>'
        if context_parts
        else ""
    )
    return (
        '<aside class="operational-rail" aria-label="Session stages">'
        '<div class="operational-brand"><strong>SESSION COMPANION</strong>'
        '<span>GUIDED LOCAL-FIRST FLOW</span></div>'
        f'<ol class="operational-stage-list">{"".join(rail_rows)}</ol></aside>'
        '<header class="operational-mobile">'
        '<div class="operational-mobile__row"><div class="operational-mobile__brand">'
        '<strong>SESSION COMPANION</strong><span>GUIDED LOCAL-FIRST FLOW</span></div>'
        '<div class="operational-mobile__current">'
        f'<strong>{_escape(current.chinese)}</strong><span>{active_stage:02d} / 06</span></div></div>'
        f'<div class="operational-progress" aria-label="Stage {active_stage} of 6">{"".join(progress_segments)}</div>'
        "</header>"
        '<section class="operational-heading">'
        f'<div class="operational-heading__chip">Stage {active_stage:02d} / 06</div>'
        f'<h1>{_escape(current.chinese)}<span>{_escape(current.english)}</span></h1>'
        f"{context_markup}</section>"
    )


def render_operational_stage(
    active_stage: int,
    *,
    subject_id: object | None = None,
    intervention_day: object | None = None,
) -> None:
    st.markdown(OPERATIONAL_CSS, unsafe_allow_html=True)
    st.markdown(
        stage_shell_markup(
            active_stage,
            subject_id=subject_id,
            intervention_day=intervention_day,
        ),
        unsafe_allow_html=True,
    )


def render_operational_status(kind: str, message: object) -> None:
    st.markdown(
        operational_status_markup(kind, message),
        unsafe_allow_html=True,
    )
```

Update `.streamlit/config.toml` to:

```toml
[theme]
primaryColor = "#DD1D86"
backgroundColor = "#F4F5F7"
secondaryBackgroundColor = "#FFFFFF"
textColor = "#000035"
font = "sans serif"
```

- [ ] **Step 4: Run the presentation contracts and compilation check**

Run:

```powershell
python -m pytest tests/test_operational_ui.py -q
python -m compileall -q operational_ui.py tests/test_operational_ui.py
```

Expected: all presentation tests pass and compilation exits `0`.

- [ ] **Step 5: Commit the shared presentation module**

```powershell
git add operational_ui.py tests/test_operational_ui.py .streamlit/config.toml
git commit -m "feat: add readme-aligned operational shell"
```

### Task 2: Add Pure Stage And Context-Confirmation Resolution

**Files:**
- Create: `tests/test_app_workflow.py`
- Modify: `app_workflow.py`

- [ ] **Step 1: Write failing stage and context-signature tests**

Create `tests/test_app_workflow.py`:

```python
from datetime import date

import pytest

from app_workflow import (
    build_daily_context_confirmation,
    daily_context_confirmation_matches,
    resolve_operational_stage,
)
from session_record_workflow import create_session_record


def _record():
    return create_session_record(
        "sub-001",
        date(2026, 7, 29),
        6,
        "daily",
        token="deadbeef",
        now_iso="2026-07-29T08:00:00+00:00",
    )


@pytest.mark.parametrize(
    ("flags", "expected"),
    (
        ((False, False, False, False, False), 1),
        ((True, False, False, False, False), 2),
        ((True, True, False, False, False), 3),
        ((True, True, True, False, False), 4),
        ((True, True, True, True, False), 5),
        ((True, False, False, False, True), 6),
    ),
)
def test_operational_stage_resolution_is_fail_closed_and_ordered(flags, expected):
    assert resolve_operational_stage(
        access_granted=flags[0],
        context_confirmed=flags[1],
        recording_complete=flags[2],
        questionnaire_complete=flags[3],
        session_complete=flags[4],
    ) == expected


def test_operational_stage_resolution_rejects_non_boolean_flags():
    with pytest.raises(ValueError, match="boolean"):
        resolve_operational_stage(
            access_granted=True,
            context_confirmed=1,
            recording_complete=False,
            questionnaire_complete=False,
            session_complete=False,
        )


def test_daily_context_confirmation_is_exact_and_record_scoped():
    record = _record()
    confirmation = build_daily_context_confirmation(record, auth_source="signed_link")
    assert confirmation == {
        "auth_source": "signed_link",
        "record_id": record["record_id"],
        "subject_id": "sub-001",
        "record_date": "2026-07-29",
        "intervention_day": 6,
        "visit": "daily",
    }
    assert daily_context_confirmation_matches(
        confirmation,
        record,
        auth_source="signed_link",
    ) is True

    for field, changed in (
        ("auth_source", "admin"),
        ("record_id", "different_record"),
        ("subject_id", "sub-002"),
        ("record_date", "2026-07-30"),
        ("intervention_day", 7),
        ("visit", "V1"),
    ):
        hostile = dict(confirmation)
        hostile[field] = changed
        assert daily_context_confirmation_matches(
            hostile,
            record,
            auth_source="signed_link",
        ) is False


@pytest.mark.parametrize("value", (None, True, [], {"record_id": "partial"}))
def test_daily_context_confirmation_rejects_partial_or_wrong_typed_state(value):
    assert daily_context_confirmation_matches(
        value,
        _record(),
        auth_source="signed_link",
    ) is False
```

- [ ] **Step 2: Run the pure workflow tests and verify missing symbols**

Run:

```powershell
python -m pytest tests/test_app_workflow.py -q
```

Expected: collection fails because the three new functions do not exist.

- [ ] **Step 3: Implement strict pure helpers in `app_workflow.py`**

Add these functions without importing Streamlit:

```python
def resolve_operational_stage(
    *,
    access_granted: bool,
    context_confirmed: bool,
    recording_complete: bool,
    questionnaire_complete: bool,
    session_complete: bool,
) -> int:
    flags = (
        access_granted,
        context_confirmed,
        recording_complete,
        questionnaire_complete,
        session_complete,
    )
    if any(type(flag) is not bool for flag in flags):
        raise ValueError("operational stage flags must be boolean")
    if not access_granted:
        return 1
    if session_complete:
        return 6
    if not context_confirmed:
        return 2
    if not recording_complete:
        return 3
    if not questionnaire_complete:
        return 4
    return 5


def build_daily_context_confirmation(
    record: Mapping[str, Any],
    *,
    auth_source: str,
) -> dict[str, Any]:
    if auth_source not in {"admin", "signed_link"}:
        raise ValueError("authentication source must be admin or signed_link")
    required = (
        "record_id",
        "subject_id",
        "record_date",
        "intervention_day",
        "visit",
    )
    if any(field not in record for field in required):
        raise ValueError("session record is missing daily context identity")
    return {
        "auth_source": auth_source,
        "record_id": record["record_id"],
        "subject_id": record["subject_id"],
        "record_date": record["record_date"],
        "intervention_day": record["intervention_day"],
        "visit": record["visit"],
    }


def daily_context_confirmation_matches(
    value: object,
    record: Mapping[str, Any],
    *,
    auth_source: str,
) -> bool:
    if type(value) is not dict:
        return False
    try:
        expected = build_daily_context_confirmation(
            record,
            auth_source=auth_source,
        )
    except (KeyError, TypeError, ValueError):
        return False
    return value == expected
```

- [ ] **Step 4: Run the pure workflow tests**

Run:

```powershell
python -m pytest tests/test_app_workflow.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the pure workflow model**

```powershell
git add app_workflow.py tests/test_app_workflow.py
git commit -m "feat: resolve operational session stages"
```

### Task 3: Enforce The Daily-Context Gate And Reset Semantics

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_integration.py`

- [ ] **Step 1: Add a failing AppTest for the new gate**

Update `SESSION_EXACT_KEYS` in `tests/test_app_integration.py` with `"operational_daily_context_confirmation"`. Add `confirm_daily_context: bool = True` to `_signed_app`; after its first `app.run()`, click `确认当日状态，进入本地录制` only when that flag is true and the button is present. Then add:

```python
def test_daily_context_is_a_separate_gate_before_the_recorder(monkeypatch):
    questionnaire_calls = []
    app, recorder_calls = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state="recording"),
        render_questionnaire=lambda **kwargs: questionnaire_calls.append(kwargs),
        confirm_daily_context=False,
    )

    assert not app.exception
    assert recorder_calls == []
    assert questionnaire_calls == []
    assert not app.get("download_button")
    assert "operational_daily_context_confirmation" not in app.session_state
    assert _element_by_label(
        app.button,
        "确认当日状态，进入本地录制",
    )

    _element_by_label(app.slider, "当前心境（1=很差，9=很好）").set_value(8)
    _element_by_label(
        app.button,
        "确认当日状态，进入本地录制",
    ).click().run()

    assert len(recorder_calls) == 1
    assert app.session_state["operational_record"]["daily_context"]["mood_1to9"] == 8
    confirmation = app.session_state["operational_daily_context_confirmation"]
    assert confirmation["record_id"] == app.session_state["operational_record"]["record_id"]
    assert confirmation["auth_source"] == "signed_link"
    assert not [button for button in app.button if button.label == "确认当日状态，进入本地录制"]
    assert not [slider for slider in app.slider if slider.label == "当前心境（1=很差，9=很好）"]


def test_context_confirmation_is_cleared_with_record_and_auth_changes(monkeypatch):
    app, _ = _signed_app(monkeypatch)
    original = copy.deepcopy(app.session_state["operational_record"])
    assert "operational_daily_context_confirmation" in app.session_state

    app.session_state["operational_record"]["visit"] = "V1"
    app.run()

    assert app.session_state["operational_record"]["record_id"] != original["record_id"]
    assert "operational_daily_context_confirmation" not in app.session_state
    assert _element_by_label(app.button, "确认当日状态，进入本地录制")
```

Also put a complete, hostile confirmation mapping in `_operational_phase_state()` and assert `_assert_stale_phase_state_cleared()` removes it.

- [ ] **Step 2: Run only the new gate tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_app_integration.py -k "daily_context_is_a_separate_gate or context_confirmation_is_cleared" -q
```

Expected: failures because the confirmation button/state gate does not exist and the recorder renders immediately.

- [ ] **Step 3: Add the owned confirmation key and gate in `app.py`**

Import `build_daily_context_confirmation`, `daily_context_confirmation_matches`, and `daily_context_values` from `app_workflow`. Add:

```python
_CONTEXT_CONFIRMED_KEY = "operational_daily_context_confirmation"
```

Include `_CONTEXT_CONFIRMED_KEY` in `_OWNED_EXACT_KEYS`, so `_clear_current_session()`, `_clear_operational_phase_state()`, auth changes, record changes, and finish all remove it.

After the record and `daily_context` mapping are established, enforce this exact gate:

```python
auth_source = str(st.session_state.get("auth_source") or "admin")
context_confirmed = daily_context_confirmation_matches(
    st.session_state.get(_CONTEXT_CONFIRMED_KEY),
    record,
    auth_source=auth_source,
)
if not context_confirmed:
    if st.button(
        "确认当日状态，进入本地录制",
        type="primary",
        key=f"operational_daily_context::confirm::{session_token}",
    ):
        record["daily_context"] = copy.deepcopy(daily_context)
        st.session_state[_CONTEXT_CONFIRMED_KEY] = (
            build_daily_context_confirmation(record, auth_source=auth_source)
        )
        st.rerun()
    st.stop()

daily_context = daily_context_values(record)
```

Before rendering daily-context widgets, validate any cached confirmation against the current auth source, record date, subject, intervention day, visit, and record ID. When it matches, use the already validated record values and do not render participant/day/visit or daily-context widgets again. When it does not match, render those existing controls, use the existing `session_record_matches()` replacement path, and keep the confirmation absent until the explicit button is clicked.

- [ ] **Step 4: Make test helpers cross the gate without weakening gate tests**

Use this shape in `_signed_app`:

```python
def _signed_app(
    monkeypatch,
    *,
    status: RecorderStatus = RecorderStatus(mode="long"),
    visit: str = "daily",
    subject_id: str = "sub-001",
    render_questionnaire=None,
    build_export=None,
    initial_state: dict[str, object] | None = None,
    confirm_daily_context: bool = True,
) -> tuple[AppTest, list[tuple[str, str]]]:
    recorder_calls: list[tuple[str, str]] = []

    def fake_recorder(*, key: str, initial_mode: str):
        recorder_calls.append((key, initial_mode))
        return status() if callable(status) else status

    monkeypatch.setattr(browser_recorder, "render_browser_recorder", fake_recorder)
    if render_questionnaire is not None:
        monkeypatch.setattr(
            questionnaire_ui,
            "render_questionnaire",
            render_questionnaire,
        )
    if build_export is not None:
        monkeypatch.setattr(
            questionnaire_export,
            "build_participant_export",
            build_export,
        )

    key = "operational-app-test-key"
    expiry = int(time.time()) + 3600
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.secrets["LINK_SIGNING_KEY"] = key
    app.secrets["TRUSTED_INTERVENTION_DAYS"] = {subject_id: 6}
    app.secrets["SAFETY_CONTACT"] = "请联系值班支持人员。"
    app.query_params["sid"] = subject_id
    app.query_params["exp"] = str(expiry)
    app.query_params["sig"] = sign_subject_link(
        key,
        subject_id,
        expiry,
        visit,
    )
    app.query_params["visit"] = visit
    for state_key, value in (initial_state or {}).items():
        app.session_state[state_key] = copy.deepcopy(value)
    app.run()
    confirmation_buttons = [
        button
        for button in app.button
        if button.label == "确认当日状态，进入本地录制"
    ]
    if confirm_daily_context and confirmation_buttons:
        confirmation_buttons[0].click().run()
    return app, recorder_calls
```

For admin tests that click `确认日期`, explicitly click `确认当日状态，进入本地录制` on the following run before expecting recorder, questionnaire, or export controls.

- [ ] **Step 5: Run context and existing flow regression tests**

Run:

```powershell
python -m pytest tests/test_app_workflow.py tests/test_app_integration.py -q
```

Expected: all tests pass; existing recording/export assertions retain their prior behavior after the helper crosses the new gate.

- [ ] **Step 6: Commit the daily-context boundary**

```powershell
git add app.py tests/test_app_integration.py
git commit -m "feat: gate recording on daily context confirmation"
```

### Task 4: Route The Real Application Through One Active Stage

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_integration.py`

- [ ] **Step 1: Write failing six-stage AppTest contracts**

Import `OPERATIONAL_CSS` and `STAGES` from `operational_ui` in the test. Add a helper that reads the rendered shell markup:

```python
def _operational_shell_markup(app: AppTest) -> str:
    return "\n".join(
        str(element.value)
        for element in app.markdown
        if "operational-heading__chip" in str(element.value)
    )


def _assert_active_stage(app: AppTest, stage: int) -> None:
    markup = _operational_shell_markup(app)
    assert markup.count("operational-stage--active") == 1
    assert f"Stage {stage:02d} / 06" in markup
    assert STAGES[stage - 1].chinese in markup
```

Add these focused tests:

```python
def test_password_gate_uses_stage_one_shell_and_hides_later_controls():
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.secrets["APP_PASSWORD_SHA256"] = hashlib.sha256(b"admin-password").hexdigest()
    app.run()
    _assert_active_stage(app, 1)
    assert _element_by_label(app.text_input, "访问密码")
    assert not [item for item in app.text_input if item.label == "来访者编号"]
    assert not app.get("download_button")


def test_each_operational_gate_renders_only_its_current_controls(monkeypatch):
    context_app, context_recorder_calls = _signed_app(
        monkeypatch,
        confirm_daily_context=False,
    )
    _assert_active_stage(context_app, 2)
    assert context_recorder_calls == []

    recording_app, recording_calls = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state="recording"),
    )
    _assert_active_stage(recording_app, 3)
    assert len(recording_calls) == 1
    assert not recording_app.radio
    assert not recording_app.get("download_button")

    questionnaire_app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=lambda **kwargs: (kwargs["answers"], False),
    )
    _assert_active_stage(questionnaire_app, 4)
    assert not [item for item in questionnaire_app.number_input if item.label == "昨夜睡眠（小时）"]
    assert not questionnaire_app.get("download_button")

    export_app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=_complete_renderer([]),
        build_export=lambda *args, **kwargs: _valid_bundle(),
    )
    _assert_active_stage(export_app, 5)
    assert len(export_app.get("download_button")) == 1
    assert not [item for item in export_app.number_input if item.label == "昨夜睡眠（小时）"]

    _element_by_label(
        export_app.checkbox,
        "我确认问卷 ZIP 已保存到本地",
    ).check().run()
    _element_by_label(export_app.button, "完成本次会话").click().run()
    _assert_active_stage(export_app, 6)
    assert "本次会话已完成。" in _visible_app_text(export_app)
    assert not export_app.get("download_button")
```

Add a static contract that `app.py` calls `render_operational_stage`, uses `layout="wide"`, and no longer contains `st.title("问卷会话")` or numbered `st.subheader` calls.

- [ ] **Step 2: Run the six-stage tests and verify stage-shell failures**

Run:

```powershell
python -m pytest tests/test_app_integration.py -k "password_gate_uses_stage_one or each_operational_gate or active_stage" -q
```

Expected: failures because `app.py` has not integrated `render_operational_stage` and still renders the long page.

- [ ] **Step 3: Integrate the shell at every gate**

In `app.py`:

1. Import `resolve_operational_stage` and `render_operational_stage`.
2. Change `st.set_page_config` to `page_title="Session Companion"`, `page_icon="📝"`, and `layout="wide"`.
3. Inside `require_app_password()`, render stage `1` before invalid-link/password status and controls.
4. For `_COMPLETE_KEY is True`, render stage `6`, then the existing completion success and `st.stop()`.
5. Render stage `2` before unconfirmed identity/day/visit/daily-context controls.
6. After context confirmation, compute existing recording and questionnaire gates before rendering. Use `resolve_operational_stage(...)` and render stage `3`, `4`, or `5` exactly once with the validated subject and intervention day.
7. If the recording gate is already satisfied, do not render the recorder or its prior-stage success copy; proceed directly to stage `4`.
8. If `render_questionnaire()` newly returns complete, save the draft, mark completion, and call `st.rerun()` so stage `5` appears on a clean run rather than below stage `4`.
9. Render stage `5` before cached-export finalization, export generation, export retry errors, download, local-save checkbox, and finish control.
10. Keep the existing fail-closed `st.stop()` boundaries after stages `1`, `2`, `3`, and incomplete stage `4`.

Import `render_operational_status` with the shell. Use its `checkpoint` role for existing non-error attention copy such as password/date confirmation prompts, recorder download verification, recording-gate reminders, questionnaire refresh reminders, and ZIP refresh reminders. Keep invalid access, invalid context, export generation failures, and other true errors in native `st.error`; keep the safety escalation in native `st.warning`. This preserves alert severity while making quiet checkpoints use the approved peach semantic.

The stage selection must use these exact validated booleans:

```python
active_stage = resolve_operational_stage(
    access_granted=True,
    context_confirmed=context_confirmed,
    recording_complete=recording_locked,
    questionnaire_complete=questionnaire_visit_complete(record, visit),
    session_complete=st.session_state.get(_COMPLETE_KEY) is True,
)
render_operational_stage(
    active_stage,
    subject_id=safe_subject_id,
    intervention_day=int(record["intervention_day"]),
)
```

Keep `_render_export_finalization()` as the only owner of ZIP download/acknowledgement/finish controls. Do not put a second shell call inside it.

- [ ] **Step 4: Update obsolete long-page assertions**

Change tests that expected `② 本地录制`, `③ 正式问卷`, or `录制已确认保存在本机，现已进入问卷。` to assert stage `3` or stage `4` via `_assert_active_stage`. Preserve all metadata, recorder call count, questionnaire call count, export snapshot, retry, and privacy assertions.

Update the admin completion test sequence to:

```python
_element_by_label(app.button, "确认日期").click().run()
_element_by_label(
    app.button,
    "确认当日状态，进入本地录制",
).click().run()
```

Then continue its existing ZIP confirmation and finish assertions unchanged.

Update `test_cached_export_enters_finalization_only_and_ignores_stale_widget_events` for the one-stage model: after stage `5` is reached, assert that the old daily-context and questionnaire controls are absent, mutate only their retained namespaced session-state keys, rerun, and prove the frozen record/export snapshot and single builder call are unchanged. Do not weaken its assertions that finalization contains only download, local-save acknowledgement, and finish controls.

Update the runtime import contracts so the required imports include `build_daily_context_confirmation`, `daily_context_confirmation_matches`, `daily_context_values`, `resolve_operational_stage`, `render_operational_stage`, and `render_operational_status`. Add `operational_ui` to the exact `_local_runtime_closure(APP_PATH)` module set; keep every existing prohibited dependency and privacy-capability assertion unchanged.

- [ ] **Step 5: Run all application integration tests**

Run:

```powershell
python -m pytest tests/test_operational_ui.py tests/test_app_workflow.py tests/test_app_integration.py -q
```

Expected: all tests pass, each stage has one active shell, and later controls remain absent until their gate is satisfied.

- [ ] **Step 6: Commit the six-stage route integration**

```powershell
git add app.py tests/test_app_integration.py
git commit -m "feat: render one operational stage at a time"
```

### Task 5: Remove The Competing Questionnaire Shell

**Files:**
- Modify: `questionnaire_ui.py`
- Modify: `tests/test_questionnaire_flow.py`
- Modify: `tests/test_app_integration.py`

- [ ] **Step 1: Replace obsolete theme tests with failing local-context tests**

Remove imports/assertions for `ALTO_COLORS`, `ALTO_CSS`, and `inject_alto_theme`. Import `render_question_context` and add:

```python
def test_question_context_renderer_is_local_and_html_escaped(monkeypatch):
    rendered = []
    monkeypatch.setattr(
        "questionnaire_ui.st.markdown",
        lambda body, **kwargs: rendered.append((body, kwargs)),
    )
    render_question_context(
        '<img src=x onerror="bad()">',
        current=1,
        total=5,
    )
    assert rendered == [
        (
            '<div class="questionnaire-context">'
            "&lt;img src=x onerror=&quot;bad()&quot;&gt; · 1 / 5"
            "</div>",
            {"unsafe_allow_html": True},
        )
    ]


def test_questionnaire_module_has_no_competing_global_shell():
    source = Path("questionnaire_ui.py").read_text(encoding="utf-8")
    assert "ALTO_CSS" not in source
    assert "ALTO_COLORS" not in source
    assert "YMH" not in source
    assert "NEUROSCIENCE LAB" not in source
    assert "alto-top" not in source
    assert "alto-progress" not in source
```

In `tests/test_app_integration.py`, replace the obsolete `test_alto_questionnaire_styling_contract_is_unchanged` with a shared-shell contract:

```python
def test_operational_styling_contract_matches_readme_and_has_no_remote_assets():
    assert all(color in OPERATIONAL_CSS for color in PALETTE.values())
    assert "gradient" not in OPERATIONAL_CSS.casefold()
    assert "letter-spacing: 0" in OPERATIONAL_CSS
    assert "overflow-wrap: anywhere" in OPERATIONAL_CSS
    assert "YMH" not in OPERATIONAL_CSS
```

- [ ] **Step 2: Run the focused questionnaire tests and verify missing/new contract failures**

Run:

```powershell
python -m pytest tests/test_questionnaire_flow.py -k "question_context_renderer or competing_global_shell" -q
```

Expected: failures because `render_question_context` does not exist and the old global shell remains.

- [ ] **Step 3: Keep only escaped question-local presentation**

In `questionnaire_ui.py`:

1. Delete `ALTO_COLORS`, `ALTO_CSS`, and `inject_alto_theme`.
2. Add this helper:

```python
def render_question_context(context_label: object, *, current: int, total: int) -> None:
    safe_context = html.escape(str(context_label), quote=True)
    safe_current = html.escape(str(current), quote=True)
    safe_total = html.escape(str(total), quote=True)
    st.markdown(
        '<div class="questionnaire-context">'
        f"{safe_context} · {safe_current} / {safe_total}"
        "</div>",
        unsafe_allow_html=True,
    )
```

3. In `render_questionnaire`, replace `inject_alto_theme(...)` with:

```python
render_question_context(
    question_context_label(flow[step], visit) if flow else "当前",
    current=step + 1 if flow else 0,
    total=len(flow),
)
```

4. Rename the endpoint markup class from `alto-endpoints` to `questionnaire-endpoints`; its styling now comes from `OPERATIONAL_CSS`.
5. Do not alter any widget label, state key, validation rule, navigation callback, branching rule, draft write, or support message.

- [ ] **Step 4: Run questionnaire and application regressions**

Run:

```powershell
python -m pytest tests/test_questionnaire_flow.py tests/test_questionnaire_end_to_end.py tests/test_app_integration.py tests/test_operational_ui.py -q
```

Expected: all tests pass; question context/counter remains visible, and no second branded header is rendered.

- [ ] **Step 5: Commit the unified questionnaire presentation**

```powershell
git add questionnaire_ui.py tests/test_questionnaire_flow.py tests/test_app_integration.py
git commit -m "refactor: unify questionnaire with operational shell"
```

### Task 6: Run Full Automated And Privacy Verification

**Files:**
- Modify only files required to fix failures caused by Tasks 1-5.

- [ ] **Step 1: Run formatting and source checks**

Run:

```powershell
git diff --check
python -m compileall -q app.py app_workflow.py operational_ui.py questionnaire_ui.py tests
```

Expected: both commands exit `0`; no trailing whitespace or compilation errors.

- [ ] **Step 2: Run the focused operational suite**

Run:

```powershell
python -m pytest tests/test_operational_ui.py tests/test_app_workflow.py tests/test_app_integration.py tests/test_questionnaire_flow.py tests/test_questionnaire_end_to_end.py tests/test_browser_recorder.py tests/test_local_recording_workflow.py tests/test_local_export_bundle.py tests/test_questionnaire_export.py tests/test_requirements_contract.py -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run the recorder Node suite unchanged**

Run:

```powershell
node --test tests/js/test_recorder_core.mjs
```

Expected: all `44` recorder tests pass. Any recorder lifecycle regression blocks completion.

- [ ] **Step 4: Run the full Python suite**

Run:

```powershell
python -m pytest -q
```

Expected: the entire suite passes with no warnings promoted to errors and no skipped gate tests.

- [ ] **Step 5: Audit runtime privacy and changed files**

Run:

```powershell
python -m pytest tests/test_app_integration.py -k "runtime_import_graph or participant_visible_tree or no_server or privacy" -q
git status --short
git diff --stat origin/main...HEAD
```

Expected: privacy tests pass; changes are limited to the approved design/plan, presentation module, application workflow, questionnaire presentation, Streamlit theme, and their tests. No recording, ZIP, secret, screenshot, or cache file is tracked.

- [ ] **Step 6: Commit any test-only compatibility fixes**

Only when Task 6 required a scoped correction:

```powershell
git add app.py app_workflow.py operational_ui.py questionnaire_ui.py .streamlit/config.toml tests
git commit -m "test: verify readme-aligned operational flow"
```

If no correction was required, do not create an empty commit.

### Task 7: Verify The Real Responsive Experience Locally

**Files:**
- Do not commit screenshots.
- Store temporary captures under `.superpowers/visual-verification/readme-aligned-operational-app/`.

- [ ] **Step 1: Start a protected local Streamlit server**

From the worktree, set a disposable local password hash and start the app on an unused port. On Windows PowerShell:

```powershell
$visualPassword = "session-visual-check"
$visualHash = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($visualPassword)
    )
).ToLowerInvariant()
$env:APP_PASSWORD_SHA256 = $visualHash
$process = Start-Process python -ArgumentList @(
    "-m", "streamlit", "run", "app.py",
    "--server.port", "8502",
    "--server.headless", "true",
    "--browser.gatherUsageStats", "false"
) -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru
$process.Id
```

Expected: a process ID is printed and `http://localhost:8502` becomes reachable. If `8502` is occupied, select another unused port and use it consistently.

- [ ] **Step 2: Exercise all six stages with synthetic values**

Use the in-app browser control surface and only synthetic participant ID `sub-visual-001`:

1. Stage 1: verify password access shell; enter `session-visual-check`.
2. Stage 2: enter `sub-visual-001`, confirm day `6`, keep visit `daily`, fill safe synthetic daily context, and confirm the daily state.
3. Stage 3: verify the fixed 16:9 recorder; use its explicit skip path and confirm continuing without a saved recording.
4. Stage 4: answer the five-question negative daily path and verify the question-local context/counter.
5. Stage 5: download the generated ZIP to a temporary browser location, confirm local save, and verify finish enables.
6. Stage 6: finish and verify completion does not claim that a recording file exists.

At each stage, confirm only current-stage controls are actionable and that the rail still shows all six stages as navigation context, not links.

- [ ] **Step 3: Capture and inspect the required viewports**

For every reachable stage, capture screenshots at:

- `1440 x 900`
- `1024 x 768`
- `390 x 844`

Save them only under `.superpowers/visual-verification/readme-aligned-operational-app/`. At each size verify:

- desktop rail or mobile header/progress appears at the correct breakpoint;
- no text clipping, control overlap, nested cards, or horizontal scroll;
- button labels wrap without changing adjacent layout;
- focus outlines are visible;
- participant context is escaped and does not leak into recorder component keys;
- recorder remains 16:9 and nonblank;
- only one shared shell exists; no `YMH NEUROSCIENCE LAB` header remains;
- palette and status semantics match the README assets.

Fix any visual issue in the smallest responsible selector, rerun Tasks 6.1-6.4, and repeat all affected screenshots.

- [ ] **Step 4: Stop the local server and remove downloaded test output**

```powershell
Stop-Process -Id $process.Id
```

Delete the synthetic ZIP through the browser download UI or move it to the OS recycle bin. Keep screenshots under ignored `.superpowers/` until final reporting; do not stage them.

- [ ] **Step 5: Commit any visually required CSS correction**

Only when Step 3 required a code correction:

```powershell
git add operational_ui.py tests/test_operational_ui.py app.py questionnaire_ui.py
git commit -m "fix: polish operational responsive layout"
```

Then rerun Task 6 in full. If no correction was required, do not create an empty commit.

### Task 8: Review, Publish, And Verify The Deployment

**Files:**
- No new files expected.

- [ ] **Step 1: Review the exact branch delta**

Run:

```powershell
git status --short --branch
git log --oneline --decorate origin/main..HEAD
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
```

Expected: the worktree is clean, the design/plan and implementation commits are visible, and `git diff --check` exits `0`.

- [ ] **Step 2: Request code review before publication**

Invoke `superpowers:requesting-code-review` against the complete `origin/main...HEAD` delta. Resolve every correctness, privacy, accessibility, stage-gating, and regression finding. Rerun Task 6 after any change and commit the correction with a scoped message.

- [ ] **Step 3: Confirm the remote baseline has not moved unexpectedly**

Run:

```powershell
git fetch origin
git log -1 --oneline origin/main
git merge-base --is-ancestor origin/main HEAD
```

Expected: `origin/main` is an ancestor of `HEAD`. If not, stop publication, inspect the remote commits, reconcile without rewriting unrelated work, and rerun the full suite.

- [ ] **Step 4: Publish the verified branch to the deployed main branch**

Run:

```powershell
git push origin HEAD:main
```

Expected: a normal fast-forward push succeeds. Do not force push.

- [ ] **Step 5: Inspect the deployed application**

Open:

`https://physical-stimulation-session-recorder-lqtdzyddneawgtmkzviryt.streamlit.app/`

Wait for Streamlit Community Cloud to load the new commit. Verify at minimum:

- the deployed page loads without a Python exception;
- the protected access stage uses the deep-navy rail on desktop and navy header/progress strip on mobile;
- the title is `SESSION COMPANION`, not the removed questionnaire-only brand;
- no remote font/image/script request was introduced;
- invalid access remains fail-closed;
- the deployed commit corresponds to the pushed `HEAD`.

Use the complete local six-stage screenshots as the behavioral/responsive proof; do not enter or expose production credentials, participant links, or real identifiers during deployment inspection.

- [ ] **Step 6: Run final repository and deployment sanity checks**

Run:

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Expected: the worktree is clean and `HEAD` equals `origin/main`. Record the final Python/Node test totals, screenshot viewport results, commit hash, and deployed URL in the completion report.

## Final Acceptance Checklist

- [ ] All six approved stages use one shared README-aligned shell.
- [ ] Exactly one stage's controls are rendered at a time.
- [ ] The explicit daily-context confirmation gate is session-local and reset on every approved context boundary.
- [ ] Authentication, recorder behavior, questionnaire semantics, ZIP bytes/schema, and support behavior remain unchanged.
- [ ] No media, answers, identifiers, screenshots, credentials, or exports are persisted or committed accidentally.
- [ ] Desktop `1440x900`, compact `1024x768`, and mobile `390x844` visual checks pass for every reachable stage.
- [ ] Focus, text wrapping, contrast, reduced motion, and 16:9 recorder constraints pass.
- [ ] Full Python, Node, compilation, privacy, and source-format checks pass.
- [ ] Code review findings are resolved.
- [ ] `origin/main` and the deployed Streamlit application are verified at the final commit.
