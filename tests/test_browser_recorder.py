import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import browser_recorder
from browser_recorder import RecorderStatus, parse_recorder_status


RECORDER_SOURCE = Path(__file__).resolve().parents[1] / "browser_recorder.py"
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


def _with(field, value):
    return {**VALID_STATUS, field: value}


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
