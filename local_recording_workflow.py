from browser_recorder import RecorderStatus


def local_recording_metadata(status: RecorderStatus) -> dict[str, object]:
    return {
        "version": 2,
        "storage": "browser_local",
        "status": status.state,
        "mode": status.mode,
        "duration_seconds": status.duration_seconds,
        "camera_ready": status.camera_ready,
        "microphone_ready": status.microphone_ready,
        "saved_confirmed": status.saved_confirmed,
    }


def recording_gate_satisfied(
    status: RecorderStatus, continue_without_recording: bool
) -> bool:
    if status.state == "saved":
        return (
            status.saved_confirmed
            and status.camera_ready
            and status.microphone_ready
        )
    if status.state in {"failed", "skipped"}:
        return continue_without_recording is True
    return False
