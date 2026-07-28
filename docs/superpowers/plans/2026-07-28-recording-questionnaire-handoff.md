# Recording-to-Questionnaire Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a confirmed browser-local recording visibly and automatically advance into the next questionnaire stage without weakening the explicit local-save confirmation boundary.

**Architecture:** Keep the recorder component as the authority for the explicit local-save confirmation. The private operational app persists only the validated terminal metadata, reruns once to lock and remove the recorder, and then renders a clearly labeled questionnaire stage. The public teacher showcase uses the same saved event to advance directly to synthetic feedback, while the component presents a prominent three-step local-save checklist.

**Tech Stack:** Streamlit 1.37 AppTest, Python 3, browser-local HTML/CSS/ES modules, Node test runner, Chrome browser verification.

---

### Task 1: Automatic Parent-Page Handoff

**Files:**
- Modify: `tests/test_app_integration.py`
- Modify: `tests/test_showcase_app.py`
- Modify: `app.py`
- Modify: `showcase_app.py`

- [ ] **Step 1: Write failing private-flow assertions**

Extend `test_saved_recording_persists_only_exact_v2_metadata_and_enters_questionnaire` to require the visible messages `录制已确认保存在本机，现已进入问卷。` and `③ 正式问卷`, while preserving the exact version-2 metadata assertion and one questionnaire render.

- [ ] **Step 2: Write the failing showcase-flow assertion**

Change the confirmed-save test so `_capture_app(...)` must already have `showcase_step == "reflection"`, all synthetic sliders visible, `showcase_camera_started is True`, and no `finish_capture` button. Update helpers and end-to-end tests so only skipped/failed recordings use a manual continue button.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_app_integration.py::test_saved_recording_persists_only_exact_v2_metadata_and_enters_questionnaire tests/test_showcase_app.py::test_recorder_confirmed_save_continues_with_camera_feedback -q
```

Expected: failures because the private page lacks the explicit stage label and the showcase still waits for `finish_capture`.

- [ ] **Step 4: Implement the minimal handoff**

In `app.py`, after validated saved metadata is written for the first time, call `st.rerun()` so the next render takes the locked branch and no longer mounts the recorder. In the locked saved branch render:

```python
st.success("录制已确认保存在本机，现已进入问卷。")
```

Immediately before the questionnaire warning render:

```python
st.subheader("③ 正式问卷")
```

Do not auto-advance skipped or failed recordings; their explicit confirmation remains required.

In `showcase_app.py`, replace the confirmed-save button with:

```python
st.session_state["showcase_camera_started"] = True
_go("finish_capture")
```

The transition happens only for `state == "saved" and saved_confirmed is True`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the two focused tests, then:

```powershell
python -m pytest tests/test_app_integration.py tests/test_showcase_app.py -q
```

Expected: all selected tests pass with no exceptions.

- [ ] **Step 6: Commit**

Commit as `YaoZeLiu0417 <YaoZeLiu0417@users.noreply.github.com>` with message:

```text
fix: enter questionnaire after local recording
```

### Task 2: Explicit Recorder Save Checklist

**Files:**
- Modify: `tests/js/test_recorder_core.mjs`
- Modify: `tests/test_browser_recorder.py`
- Modify: `browser_recorder_component/index.html`
- Modify: `browser_recorder_component/recorder_app.mjs`
- Modify: `browser_recorder_component/recorder.css`

- [ ] **Step 1: Write failing component tests**

Add a `save-panel` element to the JS harness and assert it is hidden before completion, visible when local output is finalized, and still visible in the saved state. Add markup assertions requiring three ordered steps: save/download, verify local playback/file, and check explicit confirmation.

- [ ] **Step 2: Run component tests and verify RED**

Run:

```powershell
node --test tests/js/test_recorder_core.mjs
python -m pytest tests/test_browser_recorder.py -q
```

Expected: failures because `save-panel` and its checklist do not exist.

- [ ] **Step 3: Implement the minimal checklist UI**

Wrap the existing checkbox in `<section id="save-panel" class="save-panel" hidden>` and add a short ordered list that instructs users to save/download, verify the local result, then confirm. Preserve the existing checkbox id and published status contract. In `renderControls`, set:

```javascript
elements.savePanel.hidden = !localCompletionReady;
```

Style the panel as a full-width, high-contrast completion block using the existing Alto palette (`#000035`, `#2d2674`, `#dd1d86`, `#33b0e4`) with square-to-4px radii and responsive text wrapping.

- [ ] **Step 4: Run component tests and verify GREEN**

Run the Node and Python component tests above. Expected: all pass.

- [ ] **Step 5: Commit**

Commit with message:

```text
fix: clarify local recording completion
```

### Task 3: Full Verification and Private Deployment

**Files:**
- Verify only unless a test exposes a defect.

- [ ] **Step 1: Run all automated checks**

```powershell
node --test tests/js/test_recorder_core.mjs
python -m pytest -q
python -m py_compile app.py showcase_app.py browser_recorder.py
git diff --check origin/main..HEAD
```

Expected: zero JavaScript failures, `1546+` Python tests passing with the two known skips, successful compilation, and no whitespace errors.

- [ ] **Step 2: Verify the real Chrome path**

Start the private Streamlit entry point, then use Chrome with fake camera/audio to complete: record, stop, download/save, verify playback, check local-save confirmation, observe automatic recorder removal, answer the first questionnaire screen, and confirm that no extra continue button is required.

- [ ] **Step 3: Publish the private operational branch**

After review approval, update the private repository `main` to the verified operational HEAD without changing the public showcase repository. Confirm the Streamlit deployment entry point is `app.py` and wait for the deployed commit to become healthy.

- [ ] **Step 4: Verify the deployed flow**

Open `https://physical-stimulation-session-recorder.streamlit.app`, authenticate through the controlled entry, and repeat the recording-to-questionnaire handoff. Confirm that formal questionnaire content remains absent from the public README/showcase repository.
