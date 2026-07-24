import json
from pathlib import Path

import pytest

from upload_workflow import upload_record_bundle


def _bundle(tmp_path):
    json_path = tmp_path / "record.json"
    video_path = tmp_path / "record.mp4"
    raw_video_path = tmp_path / "record.flv"
    json_path.write_text(json.dumps({"upload": {}}), encoding="utf-8")
    video_path.write_bytes(b"mp4")
    raw_video_path.write_bytes(b"flv")
    return json_path, video_path, raw_video_path


def _json_persister(json_path, events=None):
    def persist(state):
        if events is not None:
            events.append(("persist", dict(state)))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["upload"] = dict(state)
        json_path.write_text(json.dumps(payload), encoding="utf-8")

    return persist


def test_success_uploads_json_video_json_then_cleans_all_local_files(tmp_path):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    events = []

    def upload(local_path, remote_path, *, progress_cb):
        events.append(("upload", local_path, remote_path, progress_cb))

    result = upload_record_bundle(
        json_path,
        video_path,
        "/remote/record",
        upload,
        persist_state=_json_persister(json_path, events),
        delete_after_upload=True,
        cleanup_paths=(raw_video_path,),
    )

    assert result == {"json": "uploaded", "video": "uploaded"}
    assert events == [
        ("upload", json_path, "/remote/record/record.json", None),
        ("upload", video_path, "/remote/record/record.mp4", None),
        ("persist", {"json": "uploaded", "video": "uploaded"}),
        ("upload", json_path, "/remote/record/record.json", None),
    ]
    assert not json_path.exists()
    assert not video_path.exists()
    assert not raw_video_path.exists()


def test_initial_json_failure_persists_failure_and_keeps_every_local_file(tmp_path):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    uploads = []

    def upload(local_path, remote_path, *, progress_cb):
        uploads.append(local_path)
        raise RuntimeError("initial JSON failed")

    with pytest.raises(RuntimeError, match="initial JSON failed"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
        )

    assert uploads == [json_path]
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == {
        "json": "failed",
        "video": "pending",
    }
    assert video_path.exists()
    assert raw_video_path.exists()


def test_video_failure_persists_failure_and_does_not_resync_or_clean(tmp_path):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    uploads = []

    def upload(local_path, remote_path, *, progress_cb):
        uploads.append(local_path)
        if local_path == video_path:
            raise RuntimeError("video failed")

    with pytest.raises(RuntimeError, match="video failed"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
        )

    assert uploads == [json_path, video_path]
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == {
        "json": "uploaded",
        "video": "failed",
    }
    assert video_path.exists()
    assert raw_video_path.exists()


def test_final_json_failure_persists_exact_state_and_keeps_all_local_files(tmp_path):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    uploads = []

    def upload(local_path, remote_path, *, progress_cb):
        uploads.append(local_path)
        if len(uploads) == 3:
            raise RuntimeError("final JSON failed")

    with pytest.raises(RuntimeError, match="final JSON failed"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
        )

    assert uploads == [json_path, video_path, json_path]
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == {
        "json": "failed",
        "video": "uploaded",
    }
    assert video_path.exists()
    assert raw_video_path.exists()


def test_success_with_deletion_disabled_keeps_all_local_files(tmp_path):
    json_path, video_path, raw_video_path = _bundle(tmp_path)

    upload_record_bundle(
        json_path,
        video_path,
        "/remote/record",
        lambda *args, **kwargs: None,
        persist_state=_json_persister(json_path),
        delete_after_upload=False,
        cleanup_paths=(raw_video_path,),
    )

    assert json_path.exists()
    assert video_path.exists()
    assert raw_video_path.exists()


def test_cleanup_deduplicates_paths_including_bundle_files(tmp_path, monkeypatch):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    unlinked = []
    original_unlink = Path.unlink

    def tracking_unlink(path, *args, **kwargs):
        unlinked.append(path)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", tracking_unlink)
    upload_record_bundle(
        json_path,
        video_path,
        "/remote/record",
        lambda *args, **kwargs: None,
        persist_state=_json_persister(json_path),
        delete_after_upload=True,
        cleanup_paths=(raw_video_path, video_path, json_path, raw_video_path),
    )

    assert unlinked == [json_path, video_path, raw_video_path]


def test_remote_paths_and_progress_callbacks_are_passed_exactly(tmp_path):
    json_path, video_path, _ = _bundle(tmp_path)
    json_progress = object()
    video_progress = object()
    calls = []

    def upload(local_path, remote_path, *, progress_cb):
        calls.append((local_path, remote_path, progress_cb))

    upload_record_bundle(
        json_path,
        video_path,
        "study/sub-001/day-7",
        upload,
        persist_state=_json_persister(json_path),
        delete_after_upload=False,
        json_progress=json_progress,
        video_progress=video_progress,
    )

    assert calls == [
        (json_path, "study/sub-001/day-7/record.json", json_progress),
        (video_path, "study/sub-001/day-7/record.mp4", video_progress),
        (json_path, "study/sub-001/day-7/record.json", json_progress),
    ]


def test_persist_failure_after_video_upload_stops_before_final_sync_and_cleanup(
    tmp_path,
):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    uploads = []

    def upload(local_path, remote_path, *, progress_cb):
        uploads.append(local_path)

    def fail_persist(state):
        raise OSError("persist failed")

    with pytest.raises(OSError, match="persist failed"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=fail_persist,
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
        )

    assert uploads == [json_path, video_path]
    assert json_path.exists()
    assert video_path.exists()
    assert raw_video_path.exists()


def test_cleanup_failure_is_not_silently_ignored(tmp_path):
    json_path, video_path, _ = _bundle(tmp_path)
    directory = tmp_path / "cannot-unlink-directory"
    directory.mkdir()

    with pytest.raises(OSError):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            lambda *args, **kwargs: None,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(directory,),
        )
