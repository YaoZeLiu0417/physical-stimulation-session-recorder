from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


UploadState = dict[str, str]


def upload_record_bundle(
    json_path: Path,
    video_path: Path,
    remote_dir: str,
    upload_fn: Callable[..., Any],
    *,
    persist_state: Callable[[UploadState], None],
    delete_after_upload: bool,
    cleanup_paths: Iterable[Path] = (),
    json_progress: Any = None,
    video_progress: Any = None,
) -> UploadState:
    """Upload the initial record, video, and finalized record in order."""
    state = {"json": "pending", "video": "pending"}
    remote_json_path = f"{remote_dir}/{json_path.name}"
    remote_video_path = f"{remote_dir}/{video_path.name}"

    try:
        upload_fn(json_path, remote_json_path, progress_cb=json_progress)
    except Exception:
        state["json"] = "failed"
        persist_state(dict(state))
        raise
    state["json"] = "uploaded"

    try:
        upload_fn(video_path, remote_video_path, progress_cb=video_progress)
    except Exception:
        state["video"] = "failed"
        persist_state(dict(state))
        raise
    state["video"] = "uploaded"

    persist_state(dict(state))
    try:
        upload_fn(json_path, remote_json_path, progress_cb=json_progress)
    except Exception:
        state["json"] = "failed"
        persist_state(dict(state))
        raise

    if delete_after_upload:
        seen = set()
        for path in (json_path, video_path, *cleanup_paths):
            if path in seen:
                continue
            seen.add(path)
            path.unlink(missing_ok=True)

    return dict(state)
