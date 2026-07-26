# Browser-Local Recorder Operational Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the verified Chrome-local recorder into the private operational application, preserve every questionnaire and safety workflow, upload structured JSON only, and eliminate all server-side media handling and WebRTC dependencies.

**Architecture:** The shared `browser_recorder` component returns a validated status object to `app.py`. A pure operational gate converts that object into a versioned, path-free `recording` mapping. The existing record index keeps its two upload keys for backward compatibility, using `video="local_only"` for new records while accepting legacy pending/uploaded/failed video states.

**Tech Stack:** Python 3.10, Streamlit 1.37.1, the verified browser recorder component, DailyRecordStore schema/integrity indexes, questionnaire UI/scoring modules, pytest 8, Streamlit AppTest/integration tests, requests-based JSON upload.

---

## Preconditions

- Complete the browser-local recorder showcase plan through its real Chrome
  capability gate.
- The shared `browser_recorder.py` and component assets must already be on this
  branch.
- Do not begin if camera, microphone, short download, or long direct-write
  verification is open.
- Create `feat/browser-local-recorder-operational` from the exact merged private
  `main` commit and verify a clean full-test baseline before editing.

## File Map

- Create: `local_recording_workflow.py` - pure operational status, metadata, and continuation rules.
- Create: `tests/test_local_recording_workflow.py` - exact status and privacy contracts.
- Modify: `record_store.py` - schema version 5 upload compatibility for `video="local_only"`.
- Modify: `tests/test_record_store.py` - new/legacy upload lifecycle and integrity coverage.
- Modify: `app.py` - replace server WebRTC recording with the browser component and JSON-only completion.
- Modify: `app_workflow.py` - remove completed-file/path gates and keep questionnaire completion helpers.
- Modify: `tests/test_app_integration.py` - lock component ordering, no server media, and unchanged questionnaire flow.
- Modify: `tests/fixtures/questionnaire_app.py` - use local recording metadata in the fixture.
- Modify: `tests/test_questionnaire_end_to_end.py` - preserve raw answers/branches without video files.
- Modify: `upload_workflow.py` - retain safe JSON generation/upload, remove video-bundle and cleanup APIs.
- Modify: `tests/test_upload_workflow.py` - JSON-only success/failure/security tests.
- Modify: `requirements.txt` - remove streamlit-webrtc, aiortc, and av.
- Modify: `tests/test_requirements_contract.py` - lock the reduced production dependency set.
- Preserve: questionnaire specs, scoring, UI labels/branches, support-needed behavior, admin-only derived metrics, subject authentication, and all prior records on disk.

## Task 1: Define Versioned Local Recording Metadata

**Files:**
- Create: `local_recording_workflow.py`
- Create: `tests/test_local_recording_workflow.py`

- [ ] **Step 1: Write failing metadata tests**

Create tests around a saved `RecorderStatus` and assert the exact stored mapping:

```python
from browser_recorder import RecorderStatus
from local_recording_workflow import (
    local_recording_metadata,
    recording_gate_satisfied,
)


def test_saved_local_recording_metadata_contains_no_media_location() -> None:
    status = RecorderStatus(
        mode="long",
        state="saved",
        duration_seconds=1250,
        camera_ready=True,
        microphone_ready=True,
        saved_confirmed=True,
    )
    assert local_recording_metadata(status) == {
        "version": 2,
        "storage": "browser_local",
        "status": "saved",
        "mode": "long",
        "duration_seconds": 1250,
        "camera_ready": True,
        "microphone_ready": True,
        "saved_confirmed": True,
    }
    assert recording_gate_satisfied(status, continue_without_recording=False) is True
```

Add tests proving `recording` never includes filename/path/format/URL/media,
recording blocks continuation, saved requires confirmation and both tracks,
failed/skipped requires an explicit `continue_without_recording=True`, and an
idle/ready/stopped status never passes.

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_local_recording_workflow.py -q
```

Expected: collection fails because the module does not exist.

- [ ] **Step 3: Implement exact metadata and gate functions**

Create a dependency-free module importing only `RecorderStatus`. Define
`local_recording_metadata(status)` and
`recording_gate_satisfied(status, continue_without_recording)` with no file,
upload, path, network, questionnaire, or scoring capability.

- [ ] **Step 4: Add source-boundary tests and verify GREEN**

AST-test the import/call allowlist and prohibited fragments. Run focused tests,
compileall, and diff check.

- [ ] **Step 5: Commit**

```powershell
git add local_recording_workflow.py tests/test_local_recording_workflow.py
git commit -m "feat: add local recording workflow gate"
```

## Task 2: Add Backward-Compatible Local-Only Upload State

**Files:**
- Modify: `record_store.py`
- Modify: `tests/test_record_store.py`

- [ ] **Step 1: Write failing schema version 5 tests**

Assert new records use:

```python
assert record["schema_version"] == 5
assert record["upload"] == {"json": "pending", "video": "local_only"}
assert record["recording"] == {}
```

Assert `_validate_upload` accepts `video` values `pending`, `uploaded`,
`failed`, and `local_only`; old schema-4 records and integrity indexes still
load; new records reach lifecycle `uploaded` when JSON is uploaded and video is
local-only; `can_cleanup` remains true only for two genuinely uploaded server
files.

- [ ] **Step 2: Run focused record-store tests and verify RED**

Run the exact new tests and confirm schema/status failures.

- [ ] **Step 3: Implement the compatibility rule**

Add `local_only` to the video validator only, not the JSON validator. Add:

```python
def record_upload_complete(upload: Mapping[str, str]) -> bool:
    return upload.get("json") == "uploaded" and upload.get("video") in {
        "uploaded",
        "local_only",
    }
```

Use this helper for lifecycle summaries. Keep `can_cleanup` restricted to
`json=uploaded` and `video=uploaded`. New and revised browser-local records use
`video=local_only`; revising a legacy record preserves `uploaded` when present
and otherwise moves the new revision to `local_only`.

- [ ] **Step 4: Verify integrity and legacy regressions**

Run all record-store, app integration, and questionnaire end-to-end tests.
Verify no existing file is rewritten during load.

- [ ] **Step 5: Commit**

```powershell
git add record_store.py tests/test_record_store.py
git commit -m "feat: track browser-local video status"
```

## Task 3: Replace The Operational Recording Gate

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_integration.py`

- [ ] **Step 1: Replace server-recorder AST expectations with failing local-component expectations**

Update tests to require imports of `render_browser_recorder`,
`local_recording_metadata`, and `recording_gate_satisfied`. Assert the recorder
appears after daily context/day confirmation and before questionnaire rendering.
Assert the source contains none of `webrtc_streamer`, `MediaRecorder`,
`RTCConfiguration`, `out_recorder_factory`, `.flv`, `transcode_to_mp4`,
`recorder_out_path`, or server-side `st.video` playback.

- [ ] **Step 2: Add failing behavior tests for saved and skipped/failed paths**

Stub the component with saved, recording, skipped, and failed results. Assert:

- recording stops page advancement;
- saved+confirmed persists exact version-2 metadata and renders the existing
  questionnaire;
- skipped/failed presents an explicit continue-without-recording confirmation;
- no path or filename enters the record/session state;
- participant pages never render the local status dictionary.

- [ ] **Step 3: Verify RED**

Run the new integration tests and confirm they fail on the old WebRTC block.

- [ ] **Step 4: Remove the server recording block and render the component**

Delete FLV/MP4 path initialization, recorder factory, conversion, server
playback, and completed-file gate. Render the shared component with a stable key
derived from record ID/revision but never send that identifier into the media
filename. Persist only `local_recording_metadata` after the gate passes.

- [ ] **Step 5: Preserve questionnaire ordering and safety behavior**

Keep `daily_context`, questionnaire state keys, draft saves, conditional
questions, `support_needed`, safety contact copy, visit completion, and
participant/admin boundaries byte-for-byte unless a test fixture import must
change. Do not move questionnaires ahead of the recording gate.

- [ ] **Step 6: Verify focused and full tests, then commit**

Run app integration, questionnaire UI/scoring/end-to-end, record store, then
full pytest and diff check.

```powershell
git add app.py tests/test_app_integration.py
git commit -m "feat: use local recorder in operational flow"
```

## Task 4: Convert Upload Completion To JSON-Only

**Files:**
- Modify: `app.py`
- Modify: `upload_workflow.py`
- Modify: `tests/test_upload_workflow.py`
- Modify: `tests/test_app_integration.py`
- Modify: `tests/test_questionnaire_end_to_end.py`

- [ ] **Step 1: Write failing JSON-only upload tests**

Use a synthetic record and fake upload callback. Assert one generated JSON
snapshot is uploaded to `<remote_dir>/<record_id>.json`; no video path,
recordings directory, progress object, cleanup path, or local filename is
accepted. Failure sets JSON status to failed without changing local video
status; success sets JSON uploaded and leaves video local-only.

- [ ] **Step 2: Verify RED against the bundle workflow**

Run upload workflow and end-to-end tests; expect assertions showing the current
JSON-video-JSON upload sequence.

- [ ] **Step 3: Use `upload_generated_json` for the completed record**

After questionnaire completion, upload the current record mapping with a
basename-only filename and remote JSON path. Persist `upload={"json":
"uploaded", "video": "local_only"}` only after an explicit successful result.
The participant command becomes `上传问卷记录`; no video progress or delete
checkbox remains.

- [ ] **Step 4: Remove video bundle APIs**

Delete `upload_record_bundle`, `upload_private_snapshot` if no non-media caller
remains, `LocalCleanupError`, cleanup intent helpers used only for server video,
historical video upload UI, and their tests. Retain the descriptor-safe or
temporary-file code required by JSON upload only. Use `rg` to prove no source
call can upload a media extension.

- [ ] **Step 5: Update questionnaire fixtures without changing fields**

Replace fixture video filenames with version-2 local recording metadata. Remove
temporary video creation. Keep every raw-answer, answered-field, branch,
derived-metric, support, visit, and revision assertion.

- [ ] **Step 6: Verify and commit**

Run upload, app integration, questionnaire end-to-end, record store, full
pytest, compileall, diff check, and a source scan for FLV/MP4/video-upload APIs.

```powershell
git add app.py app_workflow.py upload_workflow.py record_store.py tests
git commit -m "refactor: make operational uploads JSON only"
```

## Task 5: Remove Remaining Server Media Helpers And Dependencies

**Files:**
- Modify: `app_workflow.py`
- Modify: `tests/test_app_integration.py`
- Modify: `requirements.txt`
- Modify: `tests/test_requirements_contract.py`

- [ ] **Step 1: Write failing dependency and source-boundary tests**

Change the approved production requirements to exactly:

```python
(
    "streamlit==1.37.1",
    "numpy>=1.24,<2.0",
    "requests>=2.31,<3",
    "protobuf<5",
    "python-dotenv>=1.0,<2",
)
```

Assert production source imports none of `streamlit_webrtc`, `aiortc`, `av`, or
`twilio`, and contains no trusted recording file/path/resume/transcode helpers.

- [ ] **Step 2: Verify RED**

Run requirements and app-workflow tests; expect old media dependencies/helpers.

- [ ] **Step 3: Delete orphaned media helpers and imports**

Remove completed-recording dataclasses, trusted video path/file iteration,
historical upload adapters, uploaded-video cleanup recovery, and any now-unused
OS/path/stat imports. Do not remove JSON record integrity, questionnaire,
revision, support, or authentication helpers.

- [ ] **Step 4: Remove WebRTC/media dependencies**

Delete `streamlit-webrtc`, `aiortc`, and `av` from requirements and update the
contract. Run pip dry-run to prove the reduced set resolves.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/test_requirements_contract.py tests/test_app_integration.py tests/test_questionnaire_end_to_end.py -q
python -m pytest -q
python -m pip install --dry-run -r requirements.txt
python -m compileall -q app.py app_workflow.py browser_recorder.py local_recording_workflow.py record_store.py questionnaire_scoring.py questionnaire_specs.py questionnaire_ui.py tests
rg -n "streamlit_webrtc|aiortc|MediaRecorder|\.flv|transcode_to_mp4|upload_record_bundle" . --glob '!docs/superpowers/**'
git diff --check
git add app_workflow.py requirements.txt tests
git commit -m "chore: remove server media dependencies"
```

Expected: source search is empty and all tests pass.

## Task 6: Prove Questionnaire And Privacy Equivalence

**Files:**
- Modify only tests if a missing equivalence gate is found.

- [ ] **Step 1: Compare questionnaire inventories to the pre-migration base**

Use existing questionnaire spec inventories and snapshot-like assertions to
prove field IDs, option sets, visit schedules, conditional follow-ups, required
status, scoring inputs, and safety triggers are identical.

- [ ] **Step 2: Run participant privacy inventory tests**

Verify no item score, total, interpretation, risk label, admin derived metric,
recording metadata mapping, filename, path, or upload response is visible on
participant pages or confirmation.

- [ ] **Step 3: Run recovery/revision tests**

Verify old schema-4 records and legacy recording mappings remain loadable;
revisions create schema-5/local-only upload state without deleting legacy files
or mutating archived revisions.

- [ ] **Step 4: Commit only necessary equivalence tests**

If the current suite already proves all gates, do not create a no-op commit.
Otherwise commit focused tests as `test: lock local recorder questionnaire equivalence`.

## Task 7: Final Private Release And Operational Chrome Test

**Files:**
- Verify all changes from Tasks 1-6.

- [ ] **Step 1: Run all automated gates**

Run Node component tests, all recorder/record-store/app/questionnaire/upload
focused tests, full pytest, compileall, dependency dry-run, source/privacy scan,
diff check, and clean status.

- [ ] **Step 2: Complete spec and quality reviews**

Review implementation against this plan and the approved design. Fix every
Critical/Important issue through TDD and repeat both reviews.

- [ ] **Step 3: Merge a private PR**

Confirm repository privacy, exact file scope, credential scan, checks, and
anonymous source 404 before and after merging with remote branch deletion.

- [ ] **Step 4: Run a real operational session in Chrome**

Use synthetic subject data. Record and locally save audio/video, confirm the
file, complete a daily negative branch and a conditional positive branch,
verify support response when triggered, upload JSON only, inspect admin-only
derived fields, restart/revise, and confirm no media request or server media
file appears.

## Agent Retry Rule

If an implementation or review subagent fails specifically with HTTP `429`,
wait 5-10 seconds and automatically retry the same bounded task. Do not modify
application code because of an agent-service rate limit.
