"""Contracts for the shared operational presentation shell."""

from __future__ import annotations

import pytest

import operational_ui


def test_palette_and_stages_are_exact() -> None:
    assert operational_ui.PALETTE == {
        "navy": "#000035",
        "violet": "#2D2674",
        "rose": "#DD1D86",
        "cyan": "#33B0E4",
        "peach": "#FFBC7D",
        "mist": "#F4F5F7",
        "white": "#FFFFFF",
    }
    assert tuple((stage.number, stage.english, stage.chinese) for stage in operational_ui.STAGES) == (
        (1, "Controlled access", "受控进入"),
        (2, "Daily context", "当日状态"),
        (3, "Browser-local recording", "本地音视频"),
        (4, "Stepwise questionnaire", "分步结构化作答"),
        (5, "Local response package", "本地资料包"),
        (6, "Completion confirmation", "完成确认"),
    )
    assert operational_ui.OperationalStage.__dataclass_params__.frozen


@pytest.mark.parametrize("active_stage", range(1, 7))
def test_stage_shell_marks_exactly_one_active_stage_and_progress_segment(
    active_stage: int,
) -> None:
    markup = operational_ui.stage_shell_markup(active_stage)

    assert markup.count('operational-stage--active') == 1
    assert markup.count('operational-progress__segment--active') == 1
    assert markup.count('operational-stage--completed') == active_stage - 1
    assert markup.count('operational-progress__segment--completed') == active_stage - 1
    assert markup.count('aria-current="step"') == 2
    assert f"{active_stage:02d} / 06" in markup
    assert markup.count('class="operational-rail"') == 1
    assert markup.count('class="operational-mobile"') == 1


def test_stage_shell_escapes_hostile_context_values() -> None:
    markup = operational_ui.stage_shell_markup(
        2,
        subject_id='<img src=x onerror="alert(1)">',
        intervention_day='<b>2</b>',
    )

    assert '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in markup
    assert '<img' not in markup
    assert '第 &lt;b&gt;2&lt;/b&gt; 天' in markup
    assert '<b>2</b>' not in markup


def test_checkpoint_status_returns_exact_escaped_markup() -> None:
    assert operational_ui.operational_status_markup("checkpoint", '<ready "now">') == (
        '<div class="operational-status operational-status--checkpoint" role="status">'
        '&lt;ready &quot;now&quot;&gt;</div>'
    )


def test_status_markup_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="status kind"):
        operational_ui.operational_status_markup("unknown", "message")


@pytest.mark.parametrize("active_stage", [True, "1", 0, 7])
def test_stage_shell_rejects_invalid_active_stage(active_stage: object) -> None:
    with pytest.raises(ValueError, match="active stage"):
        operational_ui.stage_shell_markup(active_stage)  # type: ignore[arg-type]


def test_css_meets_operational_visual_contract() -> None:
    css = operational_ui.OPERATIONAL_CSS

    for value in operational_ui.PALETTE.values():
        assert value in css
    for selector in (
        ".operational-rail",
        ".operational-mobile",
        ".operational-status--ready",
        ".operational-status--checkpoint",
        ".operational-status--blocking",
    ):
        assert selector in css
    assert "@media (max-width: 840px)" in css
    assert "grid-template-columns: repeat(6, minmax(0, 1fr))" in css
    assert "aspect-ratio: 16 / 9" in css
    assert ":focus-visible" in css
    assert "letter-spacing: 0" in css
    assert "white-space: normal" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    for forbidden in ("gradient", "vw", "https://", "http://", "@import", "url("):
        assert forbidden not in css.lower()


def test_renderer_emits_css_then_stage_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        operational_ui.st,
        "markdown",
        lambda markup, unsafe_allow_html: calls.append((markup, unsafe_allow_html)),
    )

    operational_ui.render_operational_stage(3, subject_id="S-01", intervention_day=2)

    assert calls == [
        (operational_ui.OPERATIONAL_CSS, True),
        (operational_ui.stage_shell_markup(3, subject_id="S-01", intervention_day=2), True),
    ]


def test_status_renderer_emits_status_markup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        operational_ui.st,
        "markdown",
        lambda markup, unsafe_allow_html: calls.append((markup, unsafe_allow_html)),
    )

    operational_ui.render_operational_status("ready", "Available")

    assert calls == [(operational_ui.operational_status_markup("ready", "Available"), True)]
