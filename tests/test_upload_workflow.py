import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

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
        events.append(("upload", local_path.name, remote_path, progress_cb))
        if local_path.suffix == ".json":
            json_snapshots.append(
                json.loads(local_path.read_text(encoding="utf-8"))
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
        ("upload", "record.json", "/remote/record/record.json", None),
        ("upload", "record.mp4", "/remote/record/record.mp4", None),
        ("persist", {"json": "uploaded", "video": "uploaded"}),
        ("upload", "record.json", "/remote/record/record.json", None),
    ]
    assert json_snapshots[0]["upload"] == {}
    assert json_snapshots[1]["upload"] == {
        "json": "uploaded",
        "video": "uploaded",
    }
    assert not json_path.exists()
    assert not video_path.exists()
    assert not raw_video_path.exists()


def test_final_sync_confirmation_failure_keeps_bundle_and_uploaded_state(tmp_path):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    uploads = []

    def upload(local_path, remote_path, *, progress_cb):
        uploads.append(remote_path)

    def fail_confirmation():
        raise OSError("ready confirmation failed")

    with pytest.raises(OSError, match="ready confirmation failed"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
            confirm_final_sync=fail_confirmation,
        )

    assert uploads == [
        "/remote/record/record.json",
        "/remote/record/record.mp4",
        "/remote/record/record.json",
    ]
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == {
        "json": "uploaded",
        "video": "uploaded",
    }
    assert video_path.exists()
    assert raw_video_path.exists()


def test_cleanup_runs_only_after_final_json_confirmation(tmp_path, monkeypatch):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    events = []
    original_cleanup = upload_workflow._cleanup_local_files

    def upload(local_path, remote_path, *, progress_cb):
        events.append(("upload", remote_path))

    def confirm_final_sync():
        events.append(("confirm", None))

    def tracking_cleanup(*args, **kwargs):
        events.append(("cleanup", None))
        return original_cleanup(*args, **kwargs)

    monkeypatch.setattr(upload_workflow, "_cleanup_local_files", tracking_cleanup)
    upload_record_bundle(
        json_path,
        video_path,
        "/remote/record",
        upload,
        persist_state=_json_persister(json_path),
        delete_after_upload=True,
        cleanup_paths=(raw_video_path,),
        confirm_final_sync=confirm_final_sync,
    )

    assert events[-3:] == [
        ("upload", "/remote/record/record.json"),
        ("confirm", None),
        ("cleanup", None),
    ]


def test_bundle_uploads_private_snapshots_and_final_json_reflects_persisted_state(
    tmp_path,
):
    json_path, video_path, _ = _bundle(tmp_path)
    uploads = []

    def upload(local_path, remote_path, *, progress_cb):
        uploads.append(
            (
                local_path,
                remote_path,
                local_path.read_bytes(),
                stat.S_IMODE(os.lstat(local_path).st_mode),
            )
        )

    upload_record_bundle(
        json_path,
        video_path,
        "/remote/record",
        upload,
        persist_state=_json_persister(json_path),
        delete_after_upload=False,
    )

    assert [remote for _, remote, _, _ in uploads] == [
        "/remote/record/record.json",
        "/remote/record/record.mp4",
        "/remote/record/record.json",
    ]
    assert all(local not in {json_path, video_path} for local, _, _, _ in uploads)
    assert all(mode & 0o600 == 0o600 for _, _, _, mode in uploads)
    assert json.loads(uploads[0][2].decode("utf-8"))["upload"] == {}
    assert uploads[1][2] == b"mp4"
    assert json.loads(uploads[2][2].decode("utf-8"))["upload"] == {
        "json": "uploaded",
        "video": "uploaded",
    }


def test_bundle_rejects_video_replaced_by_external_hardlink_before_upload(
    tmp_path,
):
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    json_path, video_path, _ = _bundle(recordings_dir)
    secret_path = tmp_path / "outside-secret.mp4"
    secret_path.write_bytes(b"SECRET-CONTENT")
    uploaded_bytes = []

    def swap_after_initial_json(local_path, remote_path, *, progress_cb):
        uploaded_bytes.append(local_path.read_bytes())
        if len(uploaded_bytes) == 1:
            video_path.unlink()
            os.link(secret_path, video_path)

    with pytest.raises(OSError, match="unsafe"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            swap_after_initial_json,
            persist_state=_json_persister(json_path),
            delete_after_upload=False,
        )

    assert uploaded_bytes == [json.dumps({"upload": {}}).encode("utf-8")]
    assert video_path.read_bytes() == b"SECRET-CONTENT"


@pytest.mark.parametrize("failure_result", [False, {"ok": False}])
def test_private_snapshot_rejects_failed_result_before_deleting_source(
    tmp_path, failure_result
):
    source_path = tmp_path / "history.mp4"
    source_path.write_bytes(b"video")

    with pytest.raises(UploadResultError, match="did not report success"):
        upload_workflow.upload_private_snapshot(
            source_path,
            "/remote/history.mp4",
            lambda *args, **kwargs: failure_result,
            delete_after_upload=True,
        )

    assert source_path.read_bytes() == b"video"


def test_generated_json_upload_uses_private_file_and_ignores_preexisting_hardlink(
    tmp_path,
):
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    outside = tmp_path / "outside-secret.json"
    outside.write_bytes(b"SECRET-CONTENT")
    hostile_path = recordings_dir / "history_state.json"
    os.link(outside, hostile_path)
    observed = {}
    payload = {"subject": "sub-001", "status": "complete"}

    def upload(local_path, remote_path, *, progress_cb):
        observed["path"] = local_path
        observed["remote"] = remote_path
        observed["payload"] = json.loads(local_path.read_text(encoding="utf-8"))
        observed["mode"] = stat.S_IMODE(local_path.lstat().st_mode)
        return {"ok": True}

    result = upload_workflow.upload_generated_json(
        payload,
        filename=hostile_path.name,
        remote_path=f"/remote/{hostile_path.name}",
        upload_fn=upload,
    )

    assert result == {"ok": True}
    assert observed["path"] != hostile_path
    assert observed["path"].parent != recordings_dir
    assert observed["path"].name == hostile_path.name
    assert observed["remote"] == "/remote/history_state.json"
    assert observed["payload"] == payload
    assert observed["mode"] & 0o600 == 0o600
    assert not observed["path"].exists()
    assert hostile_path.read_bytes() == b"SECRET-CONTENT"
    assert outside.read_bytes() == b"SECRET-CONTENT"


def test_generated_json_rejects_failed_result_and_removes_temporary_file(tmp_path):
    observed_path = None

    def fail_upload(local_path, remote_path, *, progress_cb):
        nonlocal observed_path
        observed_path = local_path
        assert local_path.is_file()
        return {"ok": False}

    with pytest.raises(UploadResultError, match="did not report success"):
        upload_workflow.upload_generated_json(
            {"status": "complete"},
            filename="history_state.json",
            remote_path="/remote/history_state.json",
            upload_fn=fail_upload,
        )

    assert observed_path is not None
    assert not observed_path.exists()


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

    assert [path.name for path in uploads] == [json_path.name]
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
        if remote_path.endswith(".mp4"):
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

    assert [path.name for path in uploads] == [json_path.name, video_path.name]
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

    assert [path.name for path in uploads] == [
        json_path.name,
        video_path.name,
        json_path.name,
    ]
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

    assert [(path.name, remote, progress) for path, remote, progress in calls] == [
        (json_path.name, "study/sub-001/day-7/record.json", json_progress),
        (video_path.name, "study/sub-001/day-7/record.mp4", video_progress),
        (json_path.name, "study/sub-001/day-7/record.json", json_progress),
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

    assert [path.name for path in uploads] == [json_path.name, video_path.name]
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


def test_cleanup_rejects_hardlink_and_preserves_every_unremoved_path(tmp_path):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    video_alias = tmp_path / "video-alias.mp4"
    os.link(video_path, video_alias)

    with pytest.raises(LocalCleanupError) as captured:
        upload_workflow.cleanup_uploaded_bundle(
            json_path, video_path, cleanup_paths=(raw_video_path,)
        )

    assert captured.value.failed_path == video_path
    assert captured.value.remaining_paths == (
        raw_video_path,
        video_path,
        json_path,
    )
    assert raw_video_path.exists()
    assert video_path.exists()
    assert video_alias.exists()
    assert json_path.exists()


def test_cleanup_rejects_reparse_attribute_and_preserves_every_path(
    tmp_path, monkeypatch
):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    original_lstat = Path.lstat
    reparse_flag = 0x400
    monkeypatch.setattr(
        upload_workflow.stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        reparse_flag,
        raising=False,
    )

    def reparse_video(path):
        result = original_lstat(path)
        return SimpleNamespace(
            st_mode=result.st_mode,
            st_nlink=result.st_nlink,
            st_dev=result.st_dev,
            st_ino=result.st_ino,
            st_size=result.st_size,
            st_mtime_ns=result.st_mtime_ns,
            st_file_attributes=reparse_flag if path == video_path else 0,
        )

    monkeypatch.setattr(Path, "lstat", reparse_video)
    with pytest.raises(LocalCleanupError) as captured:
        upload_workflow.cleanup_uploaded_bundle(
            json_path, video_path, cleanup_paths=(raw_video_path,)
        )

    assert captured.value.failed_path == video_path
    assert captured.value.remaining_paths == (
        raw_video_path,
        video_path,
        json_path,
    )
    assert raw_video_path.exists()
    assert video_path.exists()
    assert json_path.exists()


def test_cleanup_rechecks_identity_before_unlink_and_preserves_replacement(
    tmp_path, monkeypatch
):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    replacement = tmp_path / "replacement.flv"
    replacement.write_bytes(b"REPLACEMENT-CONTENT")
    original_lstat = Path.lstat
    raw_lstat_calls = 0

    def swap_before_second_raw_check(path, *args, **kwargs):
        nonlocal raw_lstat_calls
        if Path(path) == raw_video_path:
            raw_lstat_calls += 1
            if raw_lstat_calls == 2:
                os.replace(replacement, raw_video_path)
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", swap_before_second_raw_check)
    with pytest.raises(LocalCleanupError) as captured:
        upload_workflow.cleanup_uploaded_bundle(
            json_path, video_path, cleanup_paths=(raw_video_path,)
        )

    assert captured.value.failed_path == raw_video_path
    assert captured.value.remaining_paths == (
        raw_video_path,
        video_path,
        json_path,
    )
    assert raw_video_path.read_bytes() == b"REPLACEMENT-CONTENT"
    assert video_path.exists()
    assert json_path.exists()


def test_bundle_rejects_extra_cleanup_file_replaced_during_final_json_upload(
    tmp_path,
):
    json_path, video_path, raw_video_path = _bundle(tmp_path)
    replacement = tmp_path / "replacement.flv"
    replacement.write_bytes(b"REPLACEMENT-FLV")
    uploads = []

    def replace_extra_on_final_json(local_path, remote_path, *, progress_cb):
        uploads.append((local_path.name, remote_path))
        if len(uploads) == 3:
            os.replace(replacement, raw_video_path)

    with pytest.raises(LocalCleanupError) as captured:
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            replace_extra_on_final_json,
            persist_state=_json_persister(json_path),
            delete_after_upload=True,
            cleanup_paths=(raw_video_path,),
        )

    assert len(uploads) == 3
    assert captured.value.failed_path == raw_video_path
    assert captured.value.remaining_paths == (
        raw_video_path,
        video_path,
        json_path,
    )
    assert raw_video_path.read_bytes() == b"REPLACEMENT-FLV"
    assert video_path.exists()
    assert json_path.exists()


def test_cleanup_error_omits_paths_confirmed_missing_during_preflight(tmp_path):
    json_path, video_path, _ = _bundle(tmp_path)
    json_path.unlink()
    invalid_directory = tmp_path / "invalid-directory"
    invalid_directory.mkdir()

    with pytest.raises(LocalCleanupError) as captured:
        upload_workflow.cleanup_uploaded_bundle(
            json_path, video_path, cleanup_paths=(invalid_directory,)
        )

    assert captured.value.failed_path == invalid_directory
    assert captured.value.remaining_paths == (invalid_directory, video_path)
    assert invalid_directory.exists()
    assert video_path.exists()


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
        if local_path.suffix == ".json":
            json_snapshots.append(
                json.loads(local_path.read_text(encoding="utf-8"))["upload"]
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
        (json_path.name, "/remote/record/record.json"),
        (video_path.name, "/remote/record/record.mp4"),
        (json_path.name, "/remote/record/record.json"),
    ]
    assert [(path.name, remote) for path, remote in calls] == expected_paths * 2
    assert result == {"json": "uploaded", "video": "uploaded"}
    assert json_snapshots[-1] == {"json": "uploaded", "video": "uploaded"}
    assert json.loads(json_path.read_text(encoding="utf-8"))["upload"] == result
