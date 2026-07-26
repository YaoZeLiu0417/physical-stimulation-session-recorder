# Browser-Local Recorder Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a Chrome-native local audio/video recorder, prove short and long recording in the private Streamlit deployment, replace the teacher showcase TURN path, and remove Twilio without changing real questionnaires.

**Architecture:** A no-build Streamlit custom component owns `getUserMedia`, `MediaRecorder`, preview, Blob download, and File System Access writes. Python receives a strict status-only payload through a focused wrapper. The existing TURN showcase remains the default during a query-gated deployment probe, then is removed only after the user confirms the real Chrome capability gate.

**Tech Stack:** Python 3.10, Streamlit 1.37.1 custom components, HTML5, CSS, ES modules, Chrome MediaRecorder, File System Access API, Node built-in test runner, pytest 8, Streamlit AppTest, GitHub CLI, Streamlit Community Cloud.

---

## File Map

- Create: `browser_recorder.py` - typed Python component boundary and status validation.
- Create: `browser_recorder_component/index.html` - stable recorder DOM and accessible controls.
- Create: `browser_recorder_component/recorder.css` - Alto-inspired responsive recorder styling.
- Create: `browser_recorder_component/recorder_core.mjs` - state machine, MIME selection, timer limits, status sanitization, and serialized writes.
- Create: `browser_recorder_component/recorder_app.mjs` - DOM, device, MediaRecorder, audio meter, save, cleanup, and Streamlit protocol integration.
- Create: `tests/test_browser_recorder.py` - Python boundary and source-capability tests.
- Create: `tests/js/test_recorder_core.mjs` - dependency-free JavaScript unit tests.
- Modify: `showcase_app.py` - add the query-gated capability probe, then make local recording the default.
- Modify: `tests/test_showcase_app.py` - lock probe, success, skip/failure, privacy, and restart behavior.
- Delete after the gate: `showcase_ice.py`, `showcase_media.py`, `tests/test_showcase_ice.py`, `tests/test_showcase_media.py`.
- Modify after the gate: `requirements.txt`, `tests/test_requirements_contract.py` - remove Twilio only; retain WebRTC packages until the operational application migrates.
- Preserve: `app.py`, `app_workflow.py`, questionnaire modules/specs, `record_store.py`, and all operational questionnaire tests.

Run all commands from:

```powershell
Set-Location 'D:\proj_taVNS\.worktrees\physical-stimulation-session-recorder\twilio-turn-preview'
```

## Task 1: Add The Strict Python Status Boundary

**Files:**
- Create: `browser_recorder.py`
- Create: `tests/test_browser_recorder.py`

- [ ] **Step 1: Write failing status parser tests**

Create `tests/test_browser_recorder.py` with tests that accept only the exact
status schema and reject media-bearing or local-path fields:

```python
from pathlib import Path

import pytest

import browser_recorder


VALID_STATUS = {
    "mode": "demo",
    "state": "saved",
    "duration_seconds": 12,
    "camera_ready": True,
    "microphone_ready": True,
    "saved_confirmed": True,
    "error_code": None,
}


def test_parse_recorder_status_accepts_exact_status_payload() -> None:
    result = browser_recorder.parse_recorder_status(VALID_STATUS)
    assert result.mode == "demo"
    assert result.state == "saved"
    assert result.duration_seconds == 12
    assert result.saved_confirmed is True


@pytest.mark.parametrize(
    "extra_key",
    ("blob", "bytes", "chunk", "path", "filename", "device_label", "object_url"),
)
def test_parse_recorder_status_rejects_media_and_local_fields(extra_key) -> None:
    payload = {**VALID_STATUS, extra_key: "forbidden"}
    assert browser_recorder.parse_recorder_status(payload).state == "idle"


@pytest.mark.parametrize("payload", (None, [], "saved", {"state": "saved"}))
def test_parse_recorder_status_fails_closed(payload) -> None:
    assert browser_recorder.parse_recorder_status(payload).state == "idle"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests/test_browser_recorder.py -q
```

Expected: collection fails because `browser_recorder` does not exist.

- [ ] **Step 3: Implement the typed parser and component declaration**

Create `browser_recorder.py` with one immutable result type, exact key/type
validation, and a component wrapper:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from streamlit.components.v1 import declare_component


RecorderMode = Literal["demo", "long"]
RecorderState = Literal[
    "idle", "ready", "recording", "stopped", "saved", "skipped", "failed"
]
_STATUS_KEYS = frozenset(
    {
        "mode",
        "state",
        "duration_seconds",
        "camera_ready",
        "microphone_ready",
        "saved_confirmed",
        "error_code",
    }
)
_MODES = frozenset({"demo", "long"})
_STATES = frozenset(
    {"idle", "ready", "recording", "stopped", "saved", "skipped", "failed"}
)
_ERROR_CODES = frozenset(
    {
        None,
        "permission_denied",
        "camera_unavailable",
        "microphone_unavailable",
        "device_lost",
        "unsupported_format",
        "write_failed",
        "close_failed",
    }
)


@dataclass(frozen=True)
class RecorderStatus:
    mode: RecorderMode = "demo"
    state: RecorderState = "idle"
    duration_seconds: int = 0
    camera_ready: bool = False
    microphone_ready: bool = False
    saved_confirmed: bool = False
    error_code: str | None = None


def parse_recorder_status(value: object) -> RecorderStatus:
    if not isinstance(value, dict) or set(value) != _STATUS_KEYS:
        return RecorderStatus()
    mode = value["mode"]
    state = value["state"]
    duration = value["duration_seconds"]
    booleans = (
        value["camera_ready"],
        value["microphone_ready"],
        value["saved_confirmed"],
    )
    error_code = value["error_code"]
    if (
        not isinstance(mode, str)
        or mode not in _MODES
        or not isinstance(state, str)
        or state not in _STATES
        or not isinstance(duration, int)
        or isinstance(duration, bool)
        or duration < 0
        or duration > 45 * 60
        or not all(isinstance(item, bool) for item in booleans)
        or not (error_code is None or isinstance(error_code, str))
        or error_code not in _ERROR_CODES
    ):
        return RecorderStatus()
    return RecorderStatus(
        mode=mode,
        state=state,
        duration_seconds=duration,
        camera_ready=booleans[0],
        microphone_ready=booleans[1],
        saved_confirmed=booleans[2],
        error_code=error_code,
    )


_COMPONENT = declare_component(
    "browser_local_recorder",
    path=str(Path(__file__).with_name("browser_recorder_component")),
)


def render_browser_recorder(*, key: str, initial_mode: RecorderMode = "demo") -> RecorderStatus:
    raw = _COMPONENT(key=key, initial_mode=initial_mode, default=None)
    return parse_recorder_status(raw)
```

- [ ] **Step 4: Add source-boundary and wrapper tests**

Extend `tests/test_browser_recorder.py` to monkeypatch `_COMPONENT`, prove the
key/mode call contract, and parse the module AST. The allowed imports are
`__future__`, `dataclasses`, `pathlib`, `typing`, and
`streamlit.components.v1`; prohibited source fragments include `open(`,
`requests`, `socket`, `upload`, `recordings`, `streamlit_webrtc`, `twilio`, and
`MediaRecorder`.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```powershell
python -m pytest tests/test_browser_recorder.py -q
python -m compileall -q browser_recorder.py tests/test_browser_recorder.py
git diff --check
git add browser_recorder.py tests/test_browser_recorder.py
git commit -m "feat: add browser recorder status boundary"
```

Expected: all focused tests pass and the commit contains exactly two files.

## Task 2: Implement The Dependency-Free Recorder Core

**Files:**
- Create: `browser_recorder_component/recorder_core.mjs`
- Create: `tests/js/test_recorder_core.mjs`

- [ ] **Step 1: Write failing Node tests for pure recorder behavior**

Create `tests/js/test_recorder_core.mjs` using only `node:test` and
`node:assert/strict`. Cover:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import {
  LIMITS,
  SerialChunkWriter,
  chooseMimeType,
  createStatus,
  formatDuration,
  nextState,
} from "../../browser_recorder_component/recorder_core.mjs";

test("chooses VP9, then VP8, then generic WebM", () => {
  const supported = new Set(["video/webm;codecs=vp8,opus", "video/webm"]);
  assert.equal(chooseMimeType((type) => supported.has(type)), "video/webm;codecs=vp8,opus");
});

test("formats a stable timer", () => {
  assert.equal(formatDuration(0), "00:00");
  assert.equal(formatDuration(65), "01:05");
  assert.equal(formatDuration(2700), "45:00");
});

test("uses five, thirty, and forty-five minute boundaries", () => {
  assert.deepEqual(LIMITS, {demoMax: 300, longWarning: 1800, longMax: 2700});
});

test("rejects forbidden lifecycle transitions", () => {
  assert.equal(nextState("idle", "permission-granted"), "ready");
  assert.equal(nextState("ready", "record"), "recording");
  assert.throws(() => nextState("idle", "saved"), /invalid recorder transition/);
});
```

Add fake writable tests that enqueue three numbered Blob-like objects, verify
write order, verify `close()` waits for all writes, and verify a failed write is
reported only as `write_failed`.

- [ ] **Step 2: Run Node tests and verify RED**

Run:

```powershell
node --test tests/js/test_recorder_core.mjs
```

Expected: FAIL because the core module does not exist.

- [ ] **Step 3: Implement the state machine and MIME/timer helpers**

Create `recorder_core.mjs` exporting the exact constants and functions used by
the tests. `createStatus` must construct only the seven approved keys, coerce
duration to an integer in `0..2700`, and map unknown errors to a known category.

- [ ] **Step 4: Implement serialized writes without leaking errors**

Add `SerialChunkWriter` with a promise tail. Each `enqueue` appends one write to
the tail; `close` drains the tail, throws a sanitized `write_failed` error if a
write failed, and otherwise closes once. `abort` is idempotent. It must never
store a path, handle name, or chunk outside the queue lifetime.

- [ ] **Step 5: Add a JavaScript source boundary test**

In the Node test, read `recorder_core.mjs` and assert it contains none of:
`fetch(`, `XMLHttpRequest`, `WebSocket`, `sendBeacon`, `RTCPeerConnection`,
`localStorage`, `indexedDB`, `console.log`, `path`, or `filename`.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```powershell
node --test tests/js/test_recorder_core.mjs
git diff --check
git add browser_recorder_component/recorder_core.mjs tests/js/test_recorder_core.mjs
git commit -m "feat: add local recorder state machine"
```

Expected: all Node tests pass.

## Task 3: Build The Chrome Recorder Surface

**Files:**
- Create: `browser_recorder_component/index.html`
- Create: `browser_recorder_component/recorder.css`
- Create: `browser_recorder_component/recorder_app.mjs`
- Modify: `tests/test_browser_recorder.py`
- Modify: `tests/js/test_recorder_core.mjs`

- [ ] **Step 1: Add failing static asset contract tests**

Extend the Python test to require all four component assets, parse `index.html`,
and assert stable IDs for preview, mode control, device selectors, audio meter,
timer, record, stop, re-record, download, skip, status, and save confirmation.
Assert one module script points to `recorder_app.mjs` and no remote URL exists.

- [ ] **Step 2: Add failing interaction-source contracts**

Assert `recorder_app.mjs` contains `navigator.mediaDevices.getUserMedia`,
`navigator.mediaDevices.enumerateDevices`, `MediaRecorder`,
`showSaveFilePicker`, `createWritable`, `AudioContext`, and explicit track
`stop()`. Assert it contains none of `fetch`, XHR, WebSocket, beacon,
RTCPeerConnection, or a server upload/file path.

- [ ] **Step 3: Run asset tests and verify RED**

Run:

```powershell
python -m pytest tests/test_browser_recorder.py -q
```

Expected: FAIL because the component assets do not exist.

- [ ] **Step 4: Create the accessible recorder DOM and CSS**

Build a semantic full-width tool with a stable 16:9 `<video muted playsinline>`,
radio-backed segmented mode control, device `<select>` controls, an audio
`<meter>`, a fixed-width timer, icon-and-text commands, live status region, and
save confirmation. Use the approved navy/violet/pink/blue/peach palette, 4px
button radius, visible focus rings, no gradients, no green, no nested cards,
and responsive control wrapping at 640px.

- [ ] **Step 5: Implement Streamlit component messaging**

In `recorder_app.mjs`, send `streamlit:componentReady` version 1 on load,
handle only `streamlit:render` messages, apply `initial_mode`, report frame
height, and send only `createStatus(...)` through
`streamlit:setComponentValue`. No media object may enter `postMessage`.

- [ ] **Step 6: Implement device acquisition and the audio meter**

Request `{video: {width: {ideal: 1280}, height: {ideal: 720}, frameRate:
{ideal: 30}}, audio: {echoCancellation: true, noiseSuppression: true,
autoGainControl: true}}` only from a user command. Populate selectors after
permission, rebuild the stream when a selector changes, keep preview muted,
and animate the meter from an analyser without retaining samples.

- [ ] **Step 7: Implement demonstration recording**

Choose the first supported WebM MIME type, start with a one-second timeslice,
append nonempty chunks, stop automatically at 300 seconds, assemble a Blob on
stop, create a local object URL, enable playback/download, and revoke old URLs
on re-record, restart, and unmount.

- [ ] **Step 8: Implement long recording**

Invoke `showSaveFilePicker` directly inside the record-button event with the
neutral timestamp filename and WebM accept filter. Create a writable stream,
enqueue nonempty chunks through `SerialChunkWriter`, warn at 1800 seconds,
auto-stop at 2700 seconds, drain and close after the final data event, and show
saved only after close succeeds.

- [ ] **Step 9: Implement error and cleanup paths**

Map permission/device/format/write/close failures to the approved codes. Picker
`AbortError` returns to ready without starting. `pagehide`, `beforeunload`,
component rerender, skip, and re-record perform idempotent cleanup of recorder,
tracks, timers, animation frame, audio context, URL, and writable stream.

- [ ] **Step 10: Verify unit and source gates, then commit**

Run:

```powershell
node --test tests/js/test_recorder_core.mjs
python -m pytest tests/test_browser_recorder.py -q
python -m compileall -q browser_recorder.py tests/test_browser_recorder.py
git diff --check
git add browser_recorder_component tests/test_browser_recorder.py tests/js/test_recorder_core.mjs
git commit -m "feat: build Chrome local recorder"
```

Expected: all focused tests pass and no remote media capability appears.

## Task 4: Deploy A Query-Gated Chrome Capability Probe

**Files:**
- Modify: `showcase_app.py`
- Modify: `tests/test_showcase_app.py`

- [ ] **Step 1: Write failing probe routing tests**

Stub `browser_recorder.render_browser_recorder`. With no query parameter,
assert the existing TURN path still renders. With `recorder_probe=1`, assert
the browser recorder renders and the TURN resolver/media renderer are never
called. Assert the probe uses only neutral text and can return to overview.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_showcase_app.py -q
```

Expected: probe tests fail because routing is absent.

- [ ] **Step 3: Add the temporary private probe route**

After password authentication, read
`st.query_params.get("recorder_probe") == "1"`. In capture, render the new
component only on that route and keep the current TURN flow unchanged for the
default route. Store only the parsed status in session state and never render
its raw dictionary.

- [ ] **Step 4: Verify privacy and regression gates**

Run:

```powershell
python -m pytest tests/test_browser_recorder.py tests/test_showcase_app.py -q
python -m pytest tests/test_requirements_contract.py tests/test_showcase_workflow.py -q
python -m pytest -q
node --test tests/js/test_recorder_core.mjs
git diff --check
```

Expected: all tests pass; default showcase behavior is unchanged.

- [ ] **Step 5: Commit and release the private probe**

Commit only the probe integration, then push and open a private PR titled
`Add Chrome-local recorder capability probe`. Reconfirm repository visibility,
exact PR scope, checks, anonymous source 404, and Streamlit auth boundary before
merge. Delete the remote probe branch after merging.

- [ ] **Step 6: Run the real Chrome capability checklist**

Open the signed-in deployment with `?recorder_probe=1` and verify:

1. camera and microphone permissions are both requested;
2. live preview is nonblank, 16:9, responsive, and muted;
3. microphone meter moves;
4. a short WebM records, stops, plays with sound, and downloads nonempty;
5. long mode opens Chrome's save picker from the record command;
6. ordered chunks write for at least two minutes and close into a playable file;
7. stop/re-record/restart release both device indicators;
8. no media request appears in Chrome Network inspection.

Expected: all eight pass. If file picker is blocked, stop this plan and execute
the same component as a dedicated same-origin recorder page before continuing.

- [ ] **Step 7: Start the final migration from merged main**

Fetch `origin/main` after the probe passes and create
`feat/browser-local-recorder-final` from that exact commit in an isolated
worktree. Confirm the recorder/component files and probe tests are present and
the full baseline passes before Task 5. Do not continue committing on the
already-merged probe branch.

## Task 5: Replace The Showcase And Remove Twilio

**Files:**
- Modify: `showcase_app.py`
- Modify: `tests/test_showcase_app.py`
- Delete: `showcase_ice.py`
- Delete: `showcase_media.py`
- Delete: `tests/test_showcase_ice.py`
- Delete: `tests/test_showcase_media.py`
- Modify: `requirements.txt`
- Modify: `tests/test_requirements_contract.py`

- [ ] **Step 1: Write failing final showcase tests**

Remove the probe/default split from test expectations. Stub the browser recorder
with `ready`, `recording`, `saved`, `skipped`, and `failed` results. Assert:

- recording blocks the continue command;
- saved plus local confirmation enables four neutral feedback sliders;
- skipped/failed requires an explicit continue-without-recording command and
  yields only the three applicable sliders;
- confirmation inventory remains exact and restart clears all recorder keys;
- no Twilio Secret, ICE server, score, answer, research term, media byte, path,
  or filename is visible.

- [ ] **Step 2: Verify RED**

Run the final showcase tests and confirm they fail against the probe routing.

- [ ] **Step 3: Make browser-local recording the only showcase path**

Replace TURN capture with `render_browser_recorder`. Use stable session keys for
parsed status and skip acknowledgment. Keep the recording status out of
confirmation output. Preserve all Alto palette and neutral questionnaire copy.

- [ ] **Step 4: Delete TURN-only source and tests**

Delete the four ICE/media files. Remove the `twilio>=9.0,<10` requirement and
its contract expectation. Retain `streamlit-webrtc`, `aiortc`, and `av` because
`app.py` still uses them until the operational-integration plan completes.

- [ ] **Step 5: Verify exact privacy and dependency boundaries**

Run:

```powershell
rg -n "TWILIO_|showcase_ice|showcase_media|get_twilio_ice_servers" . --glob '!docs/superpowers/**'
python -m pytest tests/test_browser_recorder.py tests/test_showcase_app.py tests/test_requirements_contract.py -q
node --test tests/js/test_recorder_core.mjs
python -m pytest -q
python -m pip install --dry-run -r requirements.txt
python -m compileall -q browser_recorder.py showcase_app.py tests
git diff --check
```

Expected: search returns no production/test references, all tests pass, and the
dependency set resolves without Twilio.

- [ ] **Step 6: Commit final showcase migration**

```powershell
git add -A browser_recorder.py browser_recorder_component showcase_app.py showcase_ice.py showcase_media.py requirements.txt tests
git commit -m "feat: replace TURN showcase with local recording"
```

Expected: the commit contains only recorder/showcase/dependency changes.

## Task 6: Final Private Release And Teacher Flow

**Files:**
- Verify all files changed by Tasks 1-5.
- Release branch `feat/browser-local-recorder` to private `main`.

- [ ] **Step 1: Run all component, focused, full, compile, and diff gates**

Run the Node tests, recorder/showcase/workflow tests, full pytest, compileall,
dependency dry-run, source/privacy searches, and `git diff --check
origin/main...HEAD`. Require a clean worktree.

- [ ] **Step 2: Request final spec and code-quality reviews**

Review the complete range from `origin/main` to HEAD. Fix every Critical or
Important issue through TDD and repeat both reviews after fixes.

- [ ] **Step 3: Merge through a private pull request**

Verify private visibility/default main, push, create a PR titled
`Replace TURN with browser-local recording`, inspect exact files, use configured
checks or fresh local gates, merge with remote branch deletion, and confirm
anonymous API/raw access remains 404.

- [ ] **Step 4: Remove unused remote Twilio Secrets manually**

After the new deployment passes, the user deletes `TWILIO_ACCOUNT_SID` and
`TWILIO_AUTH_TOKEN` from Streamlit Secrets. Never read or print their values.

- [ ] **Step 5: Verify the signed-in teacher workflow**

Run the final Chrome short-mode flow, neutral feedback, confirmation, and
restart. Verify downloaded video and audio, muted live preview, no network media
payload, no score/answer echo, and complete device cleanup.

## Agent Retry Rule

If an implementation or review subagent fails specifically with HTTP `429`,
wait 5-10 seconds and automatically dispatch a fresh retry with the same
bounded task and acceptance criteria. Do not change application code in
response to an agent-service rate limit.
