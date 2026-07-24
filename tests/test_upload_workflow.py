import json
from pathlib import Path

import pytest

import upload_workflow
from upload_workflow import LocalCleanupError, UploadResultError, upload_record_bundle


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
    json_snapshots = []

    def upload(local_path, remote_path, *, progress_cb):
        events.append(("upload", local_path, remote_path, progress_cb))
        if local_path == json_path:
            json_snapshots.append(
                json.loads(json_path.read_text(encoding="utf-8"))
            )

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
    assert json_snapshots[0]["upload"] == {}
    assert json_snapshots[1]["upload"] == {
        "json": "uploaded",
        "video": "uploaded",
    }
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


def test_partial_cleanup_rerun_deletes_only_remaining_files_without_reupload(
    tmp_path, monkeypatch
):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    uploads = []
    original_unlink = Path.unlink
    failed_json_once = False

    def upload(local_path, remote_path, *, progress_cb):
        uploads.append((local_path, remote_path))

    def fail_json_cleanup_once(path, *args, **kwargs):
        nonlocal failed_json_once
        if path == json_path and not failed_json_once:
            failed_json_once = True
            raise PermissionError("record JSON is busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_json_cleanup_once)
    with pytest.raises(LocalCleanupError):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
        )

    assert len(uploads) == 3
    assert not raw_video_path.exists()
    assert not video_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == {
        "json": "uploaded",
        "video": "uploaded",
    }

    monkeypatch.undo()
    upload_workflow.cleanup_uploaded_bundle(
        json_path, video_path, cleanup_paths=(raw_video_path,)
    )

    assert len(uploads) == 3
    assert not json_path.exists()


def test_source_cleanup_failure_rerun_cleans_full_bundle_without_reupload(
    tmp_path, monkeypatch
):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["local_cleanup"] = {"requested": True, "status": "pending"}
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    uploads = []
    original_unlink = Path.unlink

    def upload(local_path, remote_path, *, progress_cb):
        uploads.append((local_path, remote_path))

    def fail_source_cleanup(path, *args, **kwargs):
        if path == raw_video_path:
            raise PermissionError("source FLV is busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_source_cleanup)
    with pytest.raises(LocalCleanupError):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
        )

    assert len(uploads) == 3
    assert json_path.exists() and video_path.exists() and raw_video_path.exists()

    monkeypatch.undo()
    upload_workflow.cleanup_uploaded_bundle(
        json_path, video_path, cleanup_paths=(raw_video_path,)
    )

    assert len(uploads) == 3
    assert not json_path.exists()
    assert not video_path.exists()
    assert not raw_video_path.exists()


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

    assert unlinked == [raw_video_path, video_path, json_path]


@pytest.mark.parametrize(
    ("failed_call", "expected_state"),
    [
        (1, {"json": "failed", "video": "pending"}),
        (2, {"json": "uploaded", "video": "failed"}),
        (3, {"json": "failed", "video": "uploaded"}),
    ],
    ids=("initial-json", "video", "final-json"),
)
@pytest.mark.parametrize(
    "failure_result",
    [False, {"ok": False}],
    ids=("literal-false", "mapping-false"),
)
def test_unsuccessful_upload_result_fails_the_corresponding_stage_without_cleanup(
    tmp_path, failed_call, expected_state, failure_result
):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    calls = []

    def upload(local_path, remote_path, *, progress_cb):
        calls.append(local_path)
        if len(calls) == failed_call:
            return failure_result
        return None

    with pytest.raises(UploadResultError, match="did not report success"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
        )

    assert len(calls) == failed_call
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == expected_state
    assert video_path.exists()
    assert raw_video_path.exists()


@pytest.mark.parametrize("success_result", [None, True, {"ok": True}])
def test_upload_result_protocol_accepts_only_explicit_success_forms(
    tmp_path, success_result
):
    json_path, video_path, _ = _bundle(tmp_path)

    result = upload_record_bundle(
        json_path,
        video_path,
        "/remote/record",
        lambda *args, **kwargs: success_result,
        persist_state=_json_persister(json_path),
        delete_after_upload=False,
    )

    assert result == {"json": "uploaded", "video": "uploaded"}


@pytest.mark.parametrize(
    "ambiguous_result",
    [{}, {"status": "ok"}, {"ok": 1}, 0, 1, "ok"],
)
def test_upload_result_protocol_rejects_ambiguous_values(tmp_path, ambiguous_result):
    json_path, video_path, _ = _bundle(tmp_path)

    with pytest.raises(UploadResultError, match="did not report success"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            lambda *args, **kwargs: ambiguous_result,
            persist_state=_json_persister(json_path),
            delete_after_upload=False,
        )

    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == {
        "json": "failed",
        "video": "pending",
    }


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


def test_invalid_extra_cleanup_target_is_rejected_before_deleting_bundle(tmp_path):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    directory = tmp_path / "cannot-unlink-directory"
    directory.mkdir()

    with pytest.raises(
        LocalCleanupError, match="Upload completed.*cleanup is incomplete"
    ) as captured:
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            lambda *args, **kwargs: None,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(directory,),
        )

    assert captured.value.uploads_completed is True
    assert captured.value.failed_path == directory
    assert captured.value.remaining_paths == (directory, video_path, json_path)
    assert isinstance(captured.value.__cause__, OSError)
    assert json_path.exists()
    assert video_path.exists()
    assert raw_video_path.exists()


def test_preflight_failure_reports_every_untouched_cleanup_candidate(tmp_path):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    invalid_directory = tmp_path / "invalid-cleanup-directory"
    invalid_directory.mkdir()

    with pytest.raises(LocalCleanupError) as captured:
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            lambda *args, **kwargs: None,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path, invalid_directory),
        )

    assert captured.value.failed_path == invalid_directory
    assert captured.value.remaining_paths == (
        raw_video_path,
        invalid_directory,
        video_path,
        json_path,
    )
    assert isinstance(captured.value.__cause__, OSError)
    assert raw_video_path.exists()
    assert invalid_directory.exists()
    assert video_path.exists()
    assert json_path.exists()


def test_extra_cleanup_unlink_failure_keeps_bundle_files_and_is_distinct(
    tmp_path, monkeypatch
):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    original_unlink = Path.unlink

    def fail_raw_cleanup(path, *args, **kwargs):
        if path == raw_video_path:
            raise PermissionError("raw video is busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_raw_cleanup)
    with pytest.raises(
        LocalCleanupError, match="Upload completed.*cleanup is incomplete"
    ) as captured:
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            lambda *args, **kwargs: None,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
        )

    assert captured.value.uploads_completed is True
    assert captured.value.failed_path == raw_video_path
    assert captured.value.remaining_paths == (raw_video_path, video_path, json_path)
    assert isinstance(captured.value.__cause__, PermissionError)
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == {
        "json": "uploaded",
        "video": "uploaded",
    }
    assert video_path.exists()
    assert raw_video_path.exists()


def test_final_json_failure_can_retry_with_stable_paths_and_final_snapshot(tmp_path):
    json_path, video_path, _ = _bundle(tmp_path)
    calls = []
    json_snapshots = []
    fail_final_once = True

    def upload(local_path, remote_path, *, progress_cb):
        nonlocal fail_final_once
        calls.append((local_path, remote_path))
        if local_path == json_path:
            json_snapshots.append(
                json.loads(json_path.read_text(encoding="utf-8"))["upload"]
            )
        if len(calls) == 3 and fail_final_once:
            fail_final_once = False
            raise RuntimeError("temporary final JSON failure")

    with pytest.raises(RuntimeError, match="temporary final JSON failure"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=_json_persister(json_path),
            delete_after_upload=False,
        )

    result = upload_record_bundle(
        json_path,
        video_path,
        "/remote/record",
        upload,
        persist_state=_json_persister(json_path),
        delete_after_upload=False,
    )

    expected_paths = [
        (json_path, "/remote/record/record.json"),
        (video_path, "/remote/record/record.mp4"),
        (json_path, "/remote/record/record.json"),
    ]
    assert calls == expected_paths * 2
    assert result == {"json": "uploaded", "video": "uploaded"}
    assert json_snapshots[-1] == {"json": "uploaded", "video": "uploaded"}
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == result
