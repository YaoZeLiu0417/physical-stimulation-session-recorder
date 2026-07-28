import ast
from pathlib import Path

import pytest

from browser_recorder import RecorderStatus
from local_recording_workflow import (
    confirm_local_recording_saved,
    local_recording_metadata,
    recording_gate_satisfied,
)


WORKFLOW_SOURCE = Path(__file__).resolve().parents[1] / "local_recording_workflow.py"
METADATA_KEYS = {
    "version",
    "storage",
    "status",
    "mode",
    "duration_seconds",
    "camera_ready",
    "microphone_ready",
    "saved_confirmed",
}
MEDIA_LOCATION_KEYS = {
    "filename",
    "file_name",
    "filepath",
    "file_path",
    "path",
    "format",
    "url",
    "media",
    "media_bytes",
    "media_path",
    "media_url",
    "device_label",
}


def test_saved_local_recording_metadata_contains_no_media_location() -> None:
    status = RecorderStatus(
        mode="long",
        state="saved",
        duration_seconds=1250,
        camera_ready=False,
        microphone_ready=False,
        saved_confirmed=True,
    )

    metadata = local_recording_metadata(status)

    assert metadata == {
        "version": 2,
        "storage": "browser_local",
        "status": "saved",
        "mode": "long",
        "duration_seconds": 1250,
        "camera_ready": False,
        "microphone_ready": False,
        "saved_confirmed": True,
    }
    assert set(metadata) == METADATA_KEYS
    assert set(metadata).isdisjoint(MEDIA_LOCATION_KEYS)
    assert recording_gate_satisfied(status, continue_without_recording=False) is True


@pytest.mark.parametrize("continue_without_recording", [False, True])
def test_active_recording_blocks_continuation(
    continue_without_recording: bool,
) -> None:
    status = RecorderStatus(
        state="recording",
        camera_ready=True,
        microphone_ready=True,
    )

    assert (
        recording_gate_satisfied(status, continue_without_recording) is False
    )


@pytest.mark.parametrize(
    ("camera_ready", "microphone_ready"),
    [
        (True, True),
        (False, True),
        (True, False),
        (False, False),
    ],
)
@pytest.mark.parametrize("saved_confirmed", [False, True])
@pytest.mark.parametrize("continue_without_recording", [False, True])
def test_saved_requires_only_explicit_confirmation(
    camera_ready: bool,
    microphone_ready: bool,
    saved_confirmed: bool,
    continue_without_recording: bool,
) -> None:
    status = RecorderStatus(
        state="saved",
        camera_ready=camera_ready,
        microphone_ready=microphone_ready,
        saved_confirmed=saved_confirmed,
    )

    assert (
        recording_gate_satisfied(status, continue_without_recording)
        is saved_confirmed
    )


@pytest.mark.parametrize("state", ["failed", "skipped"])
def test_failed_or_skipped_requires_explicit_continuation(state: str) -> None:
    status = RecorderStatus(state=state)

    assert recording_gate_satisfied(status, False) is False
    assert recording_gate_satisfied(status, True) is True


def test_stopped_recording_can_be_explicitly_confirmed_on_host() -> None:
    status = RecorderStatus(
        mode="long",
        state="stopped",
        duration_seconds=1250,
        camera_ready=False,
        microphone_ready=False,
    )

    confirmed = confirm_local_recording_saved(status)

    assert confirmed == RecorderStatus(
        mode="long",
        state="saved",
        duration_seconds=1250,
        camera_ready=False,
        microphone_ready=False,
        saved_confirmed=True,
    )


@pytest.mark.parametrize(
    "state",
    ["idle", "ready", "recording", "saved", "skipped", "failed"],
)
def test_host_confirmation_rejects_any_non_stopped_state(state: str) -> None:
    with pytest.raises(ValueError, match="stopped recording"):
        confirm_local_recording_saved(RecorderStatus(state=state))


@pytest.mark.parametrize("state", ["idle", "ready", "stopped"])
@pytest.mark.parametrize("continue_without_recording", [False, True])
def test_incomplete_states_never_pass(
    state: str,
    continue_without_recording: bool,
) -> None:
    status = RecorderStatus(
        state=state,
        camera_ready=True,
        microphone_ready=True,
        saved_confirmed=True,
    )

    assert (
        recording_gate_satisfied(status, continue_without_recording) is False
    )


def test_workflow_imports_only_recorder_status() -> None:
    tree = ast.parse(WORKFLOW_SOURCE.read_text(encoding="utf-8"))
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]

    assert len(imports) == 1
    assert isinstance(imports[0], ast.ImportFrom)
    assert imports[0].module == "browser_recorder"
    assert imports[0].level == 0
    assert [(alias.name, alias.asname) for alias in imports[0].names] == [
        ("RecorderStatus", None)
    ]
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert all(isinstance(call.func, ast.Name) for call in calls)
    assert sorted(call.func.id for call in calls) == [
        "RecorderStatus",
        "ValueError",
    ]


def test_workflow_source_has_no_external_capability() -> None:
    source = WORKFLOW_SOURCE.read_text(encoding="utf-8").lower()
    prohibited_fragments = {
        "file",
        "format",
        "http",
        "media",
        "network",
        "path",
        "questionnaire",
        "requests",
        "scoring",
        "server",
        "socket",
        "upload",
        "url",
    }

    assert [fragment for fragment in prohibited_fragments if fragment in source] == []
