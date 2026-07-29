"""Contracts for the shared operational presentation shell."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

import operational_ui


class ShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


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


def test_stage_shell_escapes_hostile_stage_values(monkeypatch: pytest.MonkeyPatch) -> None:
    hostile_stages = (
        operational_ui.OperationalStage(1, '<img onerror="bad">', '<script>bad</script>'),
        *operational_ui.STAGES[1:],
    )
    monkeypatch.setattr(operational_ui, "STAGES", hostile_stages)

    markup = operational_ui.stage_shell_markup(1)

    assert markup.count('&lt;img onerror=&quot;bad&quot;&gt;') == 3
    assert markup.count('&lt;script&gt;bad&lt;/script&gt;') == 3
    assert '<img onerror' not in markup
    assert '<script>' not in markup


def test_checkpoint_status_returns_exact_escaped_markup() -> None:
    assert operational_ui.operational_status_markup("checkpoint", '<ready "now">') == (
        '<div class="operational-status operational-status--checkpoint" role="status">'
        '&lt;ready &quot;now&quot;&gt;</div>'
    )


def test_status_markup_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="status kind"):
        operational_ui.operational_status_markup("unknown", "message")


class UnhashableString(str):
    __hash__ = None


@pytest.mark.parametrize("kind", [[], {}, 1, None, UnhashableString("ready")])
def test_status_markup_rejects_non_string_kind(kind: object) -> None:
    with pytest.raises(ValueError, match="status kind"):
        operational_ui.operational_status_markup(kind, "message")  # type: ignore[arg-type]


class IntSubclass(int):
    pass


@pytest.mark.parametrize("active_stage", [True, IntSubclass(1), "1", 0, 7])
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
    assert "iframe {" not in css
    assert ":focus-visible" in css
    assert "letter-spacing: 0" in css
    assert "white-space: normal" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".operational-rail {\n  box-sizing: border-box;" in css
    assert "overflow-y: auto" in css
    assert ".block-container {\n  margin-left: 252px; width: calc(100% - 252px);" in css
    assert ".operational-stage--active {" in css
    assert ".operational-stage--active .operational-stage__number {" in css
    assert ".operational-stage--future .operational-stage__number {" in css
    assert '[data-testid="stHorizontalBlock"]' in css
    assert '[data-testid="column"]' in css
    assert "flex-direction: column" in css
    assert ".operational-status { display: inline-block; padding: 8px 12px; border-radius: 6px; background: var(--operational-violet); color: var(--operational-white); }" in css
    assert (
        ".block-container {\n"
        "    margin-left: 0;\n"
        "    margin-right: 0;\n"
        "    width: 100%;\n"
        "    max-width: none;\n"
        "    box-sizing: border-box;\n"
        "    padding: 1rem 1rem 3rem;\n"
        "  }"
    ) in css
    assert (
        ".operational-mobile__row {\n"
        "    align-items: flex-start;\n"
        "    box-sizing: border-box;\n"
        "    display: flex;\n"
        "    flex-wrap: wrap;\n"
        "    gap: 12px;\n"
        "    justify-content: space-between;\n"
        "    width: 100%;\n"
        "  }"
    ) in css
    assert (
        '[data-testid="stHeader"], [data-testid="stDecoration"], '
        '[data-testid="stToolbar"] {\n'
        '  display: none !important;\n'
        '}'
    ) in css
    assert "padding: 1rem 1rem 3rem;" in css
    for forbidden in ("gradient", "vw", "https://", "http://", "@import", "url("):
        assert forbidden not in css.lower()


def test_recorder_iframe_preserves_streamlit_reported_height() -> None:
    css = operational_ui.OPERATIONAL_CSS

    assert (
        'iframe[title*="browser_local_recorder"] { width: 100%; max-width: 100%; }'
        in css
    )
    assert 'iframe[title*="browser_local_recorder"] { aspect-ratio:' not in css
    assert "height: auto !important" not in css


def test_stage_markers_have_stable_circular_geometry_and_state_surfaces() -> None:
    css = operational_ui.OPERATIONAL_CSS

    assert (
        ".operational-stage__number {\n"
        "  align-items: center;\n"
        "  border: 2px solid var(--operational-violet);\n"
        "  border-radius: 50%;\n"
        "  box-sizing: border-box;\n"
        "  display: flex;\n"
        "  font-weight: 700;\n"
        "  height: 30px;\n"
        "  justify-content: center;\n"
        "  width: 30px;\n"
        "}"
    ) in css
    assert (
        ".operational-stage--completed .operational-stage__number {\n"
        "  background: var(--operational-cyan);\n"
        "  border-color: var(--operational-cyan);\n"
        "  color: var(--operational-navy);\n"
        "}"
    ) in css
    assert ".operational-stage--active {" in css
    assert (
        ".operational-stage--active .operational-stage__number {\n"
        "  background: transparent;\n"
        "  border: 3px solid var(--operational-rose);\n"
        "  color: var(--operational-white);\n"
        "}"
    ) in css
    assert (
        ".operational-stage--future .operational-stage__number {\n"
        "  background: transparent;\n"
        "  border-color: var(--operational-violet);\n"
        "  color: var(--operational-white);\n"
        "}"
    ) in css


def test_active_stage_row_uses_a_rose_outline_without_a_filled_surface() -> None:
    css = operational_ui.OPERATIONAL_CSS

    assert (
        ".operational-stage {\n"
        "  align-items: center;\n"
        "  border: 1px solid transparent;\n"
        "  border-radius: 6px;\n"
        "  box-sizing: border-box;\n"
        "  color: var(--operational-white);\n"
        "  display: grid;\n"
        "  gap: 10px;\n"
        "  grid-template-columns: 32px 1fr;\n"
        "  padding: 8px;\n"
        "}"
    ) in css
    assert (
        ".operational-stage--active {\n"
        "  background: transparent;\n"
        "  border-color: var(--operational-rose);\n"
        "  color: var(--operational-white);\n"
        "}"
    ) in css


def test_mobile_header_contains_bilingual_current_stage_label_and_counter() -> None:
    markup = operational_ui.stage_shell_markup(3)

    assert '<header class="operational-mobile">' in markup
    assert '<div class="operational-mobile__current">' in markup
    current_label = markup.split('<div class="operational-mobile__current">', 1)[1].split(
        "</div>", 1
    )[0]
    assert operational_ui.STAGES[2].english in current_label
    assert operational_ui.STAGES[2].chinese in current_label
    assert "03 / 06" in current_label


def test_button_hierarchy_keeps_base_buttons_native_and_primary_buttons_rose() -> None:
    css = operational_ui.OPERATIONAL_CSS

    assert (
        ".stButton > button, .stDownloadButton > button {\n"
        "  border-radius: 6px;\n"
        "  min-height: 2.75rem;\n"
        "  white-space: normal;\n"
        "}"
    ) in css
    assert (
        '.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {\n'
        "  background: var(--operational-rose);\n"
        "  border-color: var(--operational-rose);\n"
        "  color: var(--operational-white);\n"
        "}"
    ) in css
    base_rule = css.split(".stButton > button, .stDownloadButton > button {", 1)[1].split("}", 1)[0]
    assert "background: var(--operational-rose)" not in base_rule


def test_stage_shell_has_no_custom_workspace_wrapper() -> None:
    markup = operational_ui.stage_shell_markup(1)

    assert "operational-workspace" not in markup
    assert "<main" not in markup


def test_stage_shell_has_the_expected_semantic_structure() -> None:
    parser = ShellParser()
    parser.feed(operational_ui.stage_shell_markup(3))

    assert sum(tag == "aside" for tag, _ in parser.tags) == 1
    assert sum(tag == "header" for tag, _ in parser.tags) == 1
    assert sum(tag == "h1" for tag, _ in parser.tags) == 1
    assert sum(tag == "li" and attrs.get("class") == "operational-stage operational-stage--future" for tag, attrs in parser.tags) == 3
    assert sum(tag == "li" and attrs.get("class", "").startswith("operational-stage ") for tag, attrs in parser.tags) == 6
    assert sum(attrs.get("class", "").startswith("operational-progress__segment ") for _, attrs in parser.tags) == 6


def test_streamlit_theme_values_are_exact() -> None:
    config = Path(".streamlit/config.toml").read_text(encoding="utf-8")

    assert config == (
        '[theme]\n'
        'primaryColor = "#DD1D86"\n'
        'backgroundColor = "#F4F5F7"\n'
        'secondaryBackgroundColor = "#FFFFFF"\n'
        'textColor = "#000035"\n'
        'font = "sans serif"\n'
    )


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
