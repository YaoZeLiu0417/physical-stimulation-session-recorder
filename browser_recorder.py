from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from streamlit.components.v1 import declare_component


RecorderMode = Literal["demo", "long"]
RecorderState = Literal[
    "idle",
    "ready",
    "recording",
    "stopped",
    "saved",
    "skipped",
    "failed",
]
RecorderErrorCode = Literal[
    "permission_denied",
    "camera_unavailable",
    "microphone_unavailable",
    "device_lost",
    "unsupported_format",
    "write_failed",
    "close_failed",
]


@dataclass(frozen=True)
class RecorderStatus:
    mode: RecorderMode = "demo"
    state: RecorderState = "idle"
    duration_seconds: int = 0
    camera_ready: bool = False
    microphone_ready: bool = False
    saved_confirmed: bool = False
    error_code: RecorderErrorCode | None = None


_STATUS_KEYS = {
    "mode",
    "state",
    "duration_seconds",
    "camera_ready",
    "microphone_ready",
    "saved_confirmed",
    "error_code",
}
_VALID_MODES = {"demo", "long"}
_VALID_STATES = {
    "idle",
    "ready",
    "recording",
    "stopped",
    "saved",
    "skipped",
    "failed",
}
_VALID_ERROR_CODES = {
    "permission_denied",
    "camera_unavailable",
    "microphone_unavailable",
    "device_lost",
    "unsupported_format",
    "write_failed",
    "close_failed",
}


def parse_recorder_status(value: object) -> RecorderStatus:
    if type(value) is not dict or set(value) != _STATUS_KEYS:
        return RecorderStatus()

    mode = value["mode"]
    state = value["state"]
    duration_seconds = value["duration_seconds"]
    camera_ready = value["camera_ready"]
    microphone_ready = value["microphone_ready"]
    saved_confirmed = value["saved_confirmed"]
    error_code = value["error_code"]

    if type(mode) is not str or mode not in _VALID_MODES:
        return RecorderStatus()
    if type(state) is not str or state not in _VALID_STATES:
        return RecorderStatus()
    if type(duration_seconds) is not int or not 0 <= duration_seconds <= 2700:
        return RecorderStatus()
    if type(camera_ready) is not bool:
        return RecorderStatus()
    if type(microphone_ready) is not bool:
        return RecorderStatus()
    if type(saved_confirmed) is not bool:
        return RecorderStatus()
    if error_code is not None and (
        type(error_code) is not str or error_code not in _VALID_ERROR_CODES
    ):
        return RecorderStatus()

    return RecorderStatus(
        mode=mode,
        state=state,
        duration_seconds=duration_seconds,
        camera_ready=camera_ready,
        microphone_ready=microphone_ready,
        saved_confirmed=saved_confirmed,
        error_code=error_code,
    )


_COMPONENT_PATH = Path(__file__).resolve().with_name("browser_recorder_component")
_COMPONENT = declare_component("browser_local_recorder", path=str(_COMPONENT_PATH))


def render_browser_recorder(
    *, key: str, initial_mode: RecorderMode = "demo"
) -> RecorderStatus:
    value = _COMPONENT(key=key, initial_mode=initial_mode, default=None)
    return parse_recorder_status(value)
