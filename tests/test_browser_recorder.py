import ast
from dataclasses import FrozenInstanceError
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re

import pytest

import browser_recorder
from browser_recorder import RecorderStatus, parse_recorder_status


RECORDER_SOURCE = Path(__file__).resolve().parents[1] / "browser_recorder.py"
COMPONENT_DIR = RECORDER_SOURCE.with_name("browser_recorder_component")
APP_SOURCE = COMPONENT_DIR / "recorder_app.mjs"
COMPONENT_ASSETS = (
    "index.html",
    "recorder.css",
    "recorder_app.mjs",
    "recorder_core.mjs",
)
RECORDER_ELEMENT_IDS = {
    "preview",
    "settings-band",
    "mode-control",
    "camera-select",
    "microphone-select",
    "audio-meter",
    "timer",
    "record-button",
    "stop-button",
    "rerecord-button",
    "download-link",
    "skip-button",
    "status",
    "save-panel",
    "save-confirmation",
}
VALID_STATUS = {
    "mode": "long",
    "state": "saved",
    "duration_seconds": 42,
    "camera_ready": True,
    "microphone_ready": True,
    "saved_confirmed": True,
    "error_code": None,
}
DEFAULT_STATUS = RecorderStatus()


class _UnhashableString(str):
    __hash__ = None


class _HostileSchemaKey:
    def __hash__(self):
        return hash("mode")

    def __eq__(self, other):
        raise RuntimeError("hostile schema equality")


class _ComponentHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.elements_by_id = {}
        self.inputs = []
        self.scripts = []
        self.remote_urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.append(attributes["id"])
            self.elements_by_id[attributes["id"]] = (tag, attributes)
        if tag == "input":
            self.inputs.append(attributes)
        if tag == "script":
            self.scripts.append(attributes)
        for name in ("action", "href", "poster", "src"):
            value = attributes.get(name, "")
            if "://" in value or value.startswith("//"):
                self.remote_urls.append(value)


def _with(field, value):
    return {**VALID_STATUS, field: value}


def test_component_static_assets_exist() -> None:
    missing = [name for name in COMPONENT_ASSETS if not (COMPONENT_DIR / name).is_file()]

    assert missing == []


def test_component_html_has_stable_controls_and_one_local_module() -> None:
    parser = _ComponentHTMLParser()
    parser.feed((COMPONENT_DIR / "index.html").read_text(encoding="utf-8"))

    assert RECORDER_ELEMENT_IDS.issubset(parser.ids)
    assert len(parser.ids) == len(set(parser.ids))
    assert parser.scripts == [{"type": "module", "src": "recorder_app.mjs"}]
    assert parser.remote_urls == []


def test_component_html_is_semantic_and_accessible() -> None:
    parser = _ComponentHTMLParser()
    parser.feed((COMPONENT_DIR / "index.html").read_text(encoding="utf-8"))

    _, preview = parser.elements_by_id["preview"]
    assert parser.elements_by_id["preview"][0] == "video"
    assert "muted" in preview
    assert "playsinline" in preview
    settings_tag, settings_attributes = parser.elements_by_id["settings-band"]
    assert settings_tag == "section"
    assert settings_attributes["class"] == "settings-band"
    assert settings_attributes["aria-label"] == "Recording settings"
    assert parser.elements_by_id["mode-control"][0] == "fieldset"
    assert parser.elements_by_id["camera-select"][0] == "select"
    assert parser.elements_by_id["microphone-select"][0] == "select"
    assert parser.elements_by_id["audio-meter"][0] == "meter"
    assert parser.elements_by_id["status"][1]["aria-live"] == "polite"
    save_panel_tag, save_panel_attributes = parser.elements_by_id["save-panel"]
    assert save_panel_tag == "section"
    assert "hidden" in save_panel_attributes
    assert save_panel_attributes["aria-labelledby"] == "save-panel-title"
    assert parser.elements_by_id["save-confirmation"][1]["type"] == "checkbox"

    modes = {
        item.get("value")
        for item in parser.inputs
        if item.get("type") == "radio" and item.get("name") == "mode"
    }
    assert modes == {"demo", "long"}
    for element_id in ("record-button", "stop-button", "rerecord-button", "skip-button"):
        tag, attributes = parser.elements_by_id[element_id]
        assert tag == "button"
        assert attributes.get("type") == "button"
        assert attributes.get("title")


def test_component_html_gives_three_explicit_local_save_steps() -> None:
    source = (COMPONENT_DIR / "index.html").read_text(encoding="utf-8")
    match = re.search(
        r'<section\b[^>]*\bid="save-panel"[^>]*>(.*?)</section>',
        source,
        flags=re.DOTALL,
    )

    assert match is not None
    panel_source = match.group(1)
    steps = [
        " ".join(unescape(re.sub(r"<[^>]+>", " ", item)).split()).lower()
        for item in re.findall(r"<li\b[^>]*>(.*?)</li>", panel_source, re.DOTALL)
    ]

    assert len(steps) == 3
    assert "save or download" in steps[0]
    assert "chosen local folder" in steps[0]
    assert all(concept in steps[1] for concept in ("open", "play", "check", "video", "sound"))
    assert all(concept in steps[2] for concept in ("confirmation", "continue", "next step"))
    assert re.search(
        r'<label\b[^>]*\bfor="save-confirmation"[^>]*>.*?'
        r'<input\b[^>]*\bid="save-confirmation"[^>]*>.*?'
        r"saved.*checked.*video.*sound",
        panel_source,
        flags=re.DOTALL | re.IGNORECASE,
    )


def test_component_css_has_the_approved_responsive_visual_contract() -> None:
    source = (COMPONENT_DIR / "recorder.css").read_text(encoding="utf-8")

    for color in ("#000035", "#2D2674", "#DD1D86", "#33B0E4", "#FFBC7D"):
        assert color.lower() in source.lower()
    assert "aspect-ratio: 16 / 9" in source
    assert "border-radius: 4px" in source
    assert ":focus-visible" in source
    assert "@media (max-width: 640px)" in source
    assert "gradient" not in source.lower()
    assert "green" not in source.lower()


def test_component_css_styles_a_responsive_high_contrast_save_panel() -> None:
    source = (COMPONENT_DIR / "recorder.css").read_text(encoding="utf-8")
    panel_rule = re.search(r"\.save-panel\s*\{([^}]*)\}", source, re.DOTALL)

    assert panel_rule is not None
    declarations = panel_rule.group(1).lower()
    assert "width: 100%" in declarations
    assert "background: #000035" in declarations
    assert "color: #ffffff" in declarations
    assert "border-radius: 4px" in declarations
    assert "overflow-wrap: anywhere" in declarations
    assert re.search(
        r"@media\s*\(max-width:\s*640px\).*?\.save-panel\s*\{",
        source,
        re.DOTALL,
    )


def test_recorder_app_uses_required_local_browser_apis() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    required = (
        "navigator.mediaDevices.getUserMedia",
        "navigator.mediaDevices.enumerateDevices",
        "MediaRecorder",
        "showSaveFilePicker",
        "createWritable",
        "AudioContext",
        "track.stop()",
    )
    for capability in required:
        assert capability in source

    for behavior in (
        "start(1000)",
        "LIMITS.demoMax",
        "LIMITS.longWarning",
        "LIMITS.longMax",
        "URL.createObjectURL",
        "URL.revokeObjectURL",
        "writer.enqueue",
        ".close()",
        "AbortError",
        'addEventListener("pagehide"',
        'addEventListener("beforeunload"',
    ):
        assert behavior in source

    for constraint in (
        "width: { ideal: 1280 }",
        "height: { ideal: 720 }",
        "frameRate: { ideal: 30 }",
        "echoCancellation: true",
        "noiseSuppression: true",
        "autoGainControl: true",
    ):
        assert constraint in source


def test_recorder_app_has_a_status_only_streamlit_boundary() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert '"streamlit:componentReady"' in source
    assert '"streamlit:render"' in source
    assert '"streamlit:setComponentValue"' in source
    assert "createStatus(status)" in source
    assert "configurationKey" in source
    assert source.count("postMessage(") == 1


def test_recorder_app_gates_startup_and_preserves_critical_async_ordering() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "componentHasRendered &&" in source
    assert "startPending" in source

    picker_start = source.index("async function startLongRecording(")
    picker_end = source.index("async function replaceMediaStream", picker_start)
    picker_body = source[picker_start:picker_end]
    assert picker_body.index("showSaveFilePicker") < picker_body.index("await ")

    close_start = source.index("async function finishLongRecording(")
    close_end = source.index("async function finishDemoRecording", close_start)
    close_body = source[close_start:close_end]
    assert close_body.index("Promise.all") < close_body.index(".close()")


def test_recorder_app_has_no_network_or_persistent_storage_capability() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    forbidden = (
        r"\bfetch\s*\(",
        r"\bXMLHttpRequest\b",
        r"\bWebSocket\b",
        r"\bsendBeacon\b",
        r"\bRTCPeerConnection\b",
        r"\blocalStorage\b",
        r"\bindexedDB\b",
        r"\bupload\b",
        r"\bpath\b",
        r"\bfilename\b",
    )

    for capability in forbidden:
        assert re.search(capability, source, re.IGNORECASE) is None


def test_parse_accepts_saved_status_and_returns_frozen_value_object() -> None:
    status = parse_recorder_status(VALID_STATUS)

    assert status == RecorderStatus(
        mode="long",
        state="saved",
        duration_seconds=42,
        camera_ready=True,
        microphone_ready=True,
        saved_confirmed=True,
        error_code=None,
    )
    with pytest.raises(FrozenInstanceError):
        status.state = "idle"


@pytest.mark.parametrize("missing_key", tuple(VALID_STATUS))
def test_parse_rejects_every_missing_key(missing_key) -> None:
    value = {key: item for key, item in VALID_STATUS.items() if key != missing_key}

    assert parse_recorder_status(value) == DEFAULT_STATUS


def test_parse_rejects_hostile_schema_key_without_calling_equality() -> None:
    value = dict(VALID_STATUS)
    mode = value.pop("mode")
    value[_HostileSchemaKey()] = mode

    assert len(value) == len(VALID_STATUS)
    assert parse_recorder_status(value) == DEFAULT_STATUS


@pytest.mark.parametrize(
    "extra_key",
    ("blob", "bytes", "chunk", "path", "filename", "device_label", "object_url"),
)
def test_parse_rejects_media_and_identity_fields(extra_key) -> None:
    assert parse_recorder_status({**VALID_STATUS, extra_key: "private"}) == DEFAULT_STATUS


@pytest.mark.parametrize(
    "value",
    (
        None,
        [],
        "saved",
        {"mode": "demo"},
    ),
)
def test_parse_rejects_non_dict_and_partial_values_without_raising(value) -> None:
    assert parse_recorder_status(value) == DEFAULT_STATUS


@pytest.mark.parametrize("field", ("mode", "state", "error_code"))
@pytest.mark.parametrize(
    "value",
    ([], {}, object(), _UnhashableString("demo")),
    ids=("list", "dict", "object", "unhashable-string"),
)
def test_parse_rejects_non_exact_string_enum_values_without_raising(field, value) -> None:
    assert parse_recorder_status(_with(field, value)) == DEFAULT_STATUS


@pytest.mark.parametrize("duration", (True, False, 1.5, -1, 2701))
def test_parse_rejects_invalid_durations(duration) -> None:
    assert parse_recorder_status(_with("duration_seconds", duration)) == DEFAULT_STATUS


@pytest.mark.parametrize("duration", (0, 2700))
def test_parse_accepts_duration_boundaries(duration) -> None:
    assert parse_recorder_status(_with("duration_seconds", duration)).duration_seconds == duration


@pytest.mark.parametrize(
    "field", ("camera_ready", "microphone_ready", "saved_confirmed")
)
@pytest.mark.parametrize("value", (0, 1, None, "true", object()))
def test_parse_rejects_non_boolean_readiness_fields(field, value) -> None:
    assert parse_recorder_status(_with(field, value)) == DEFAULT_STATUS


@pytest.mark.parametrize("mode", ("demo", "long"))
@pytest.mark.parametrize(
    "state", ("idle", "ready", "recording", "stopped", "saved", "skipped", "failed")
)
@pytest.mark.parametrize(
    "error_code",
    (
        None,
        "permission_denied",
        "camera_unavailable",
        "microphone_unavailable",
        "device_lost",
        "unsupported_format",
        "write_failed",
        "close_failed",
    ),
)
def test_parse_accepts_allowlisted_values(mode, state, error_code) -> None:
    status = parse_recorder_status(
        {
            **VALID_STATUS,
            "mode": mode,
            "state": state,
            "error_code": error_code,
        }
    )

    assert status.mode == mode
    assert status.state == state
    assert status.error_code == error_code


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("mode", "preview"),
        ("state", "closed"),
        ("error_code", "unknown"),
    ),
)
def test_parse_rejects_values_outside_allowlists(field, value) -> None:
    assert parse_recorder_status(_with(field, value)) == DEFAULT_STATUS


def test_render_passes_exact_component_arguments_and_parses_result(monkeypatch) -> None:
    calls = []

    def fake_component(**kwargs):
        calls.append(kwargs)
        return VALID_STATUS

    monkeypatch.setattr(browser_recorder, "_COMPONENT", fake_component)

    assert browser_recorder.render_browser_recorder(
        key="session-recorder", initial_mode="long"
    ) == parse_recorder_status(VALID_STATUS)
    assert calls == [
        {"key": "session-recorder", "initial_mode": "long", "default": None}
    ]


def test_render_fails_closed_for_invalid_component_value(monkeypatch) -> None:
    monkeypatch.setattr(browser_recorder, "_COMPONENT", lambda **kwargs: {"blob": b"x"})

    assert browser_recorder.render_browser_recorder(key="recorder") == DEFAULT_STATUS


def test_render_fails_closed_when_component_raises_exception(monkeypatch) -> None:
    calls = []

    def fail_component(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("component failure must not escape")

    monkeypatch.setattr(browser_recorder, "_COMPONENT", fail_component)

    assert browser_recorder.render_browser_recorder(
        key="failed-recorder", initial_mode="long"
    ) == DEFAULT_STATUS
    assert calls == [
        {"key": "failed-recorder", "initial_mode": "long", "default": None}
    ]


def test_module_uses_only_the_status_component_boundary() -> None:
    source = RECORDER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert imported_modules == {
        "__future__",
        "dataclasses",
        "pathlib",
        "typing",
        "streamlit.components.v1",
    }

    forbidden_names = {
        "MediaRecorder",
        "open",
        "print",
        "read_bytes",
        "read_text",
        "requests",
        "socket",
        "streamlit_webrtc",
        "twilio",
        "unlink",
        "upload",
        "write_bytes",
        "write_text",
    }
    referenced_names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert forbidden_names.isdisjoint(referenced_names)
    assert "recordings" not in source.lower()
    assert "device_label" not in source
    assert "object_url" not in source


def test_component_is_declared_for_absolute_sibling_directory() -> None:
    expected_path = str(RECORDER_SOURCE.with_name("browser_recorder_component"))
    tree = ast.parse(RECORDER_SOURCE.read_text(encoding="utf-8"))
    component_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_COMPONENT"
            for target in node.targets
        )
    )
    declaration = component_assignment.value

    assert isinstance(declaration, ast.Call)
    assert isinstance(declaration.func, ast.Name)
    assert declaration.func.id == "declare_component"
    assert isinstance(declaration.args[0], ast.Constant)
    assert declaration.args[0].value == "browser_local_recorder"
    assert browser_recorder._COMPONENT.path == expected_path
    assert Path(browser_recorder._COMPONENT.path).is_absolute()
