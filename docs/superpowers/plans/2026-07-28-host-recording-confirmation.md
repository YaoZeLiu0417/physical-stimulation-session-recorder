# Host Recording Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a visible Streamlit-side confirmation that advances a stopped local recording into the formal questionnaire.

**Architecture:** A pure workflow transition converts only a stopped `RecorderStatus` into the existing saved-and-confirmed status. `app.py` renders one primary host action for the stopped state, stores the existing version-2 metadata, and reruns into the locked questionnaire branch.

**Tech Stack:** Python 3.10, Streamlit 1.37, pytest 8, Streamlit AppTest.

---

### Task 1: Pure stopped-to-saved transition

**Files:**
- Modify: `tests/test_local_recording_workflow.py`
- Modify: `local_recording_workflow.py`

- [ ] **Step 1: Write the failing transition tests**

Import `confirm_local_recording_saved`. Assert that a stopped long recording
returns `RecorderStatus(mode="long", state="saved", duration_seconds=1250,
camera_ready=False, microphone_ready=False, saved_confirmed=True)`. Parametrize
all other states and assert `ValueError`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_local_recording_workflow.py -q`

Expected: collection fails because `confirm_local_recording_saved` does not exist.

- [ ] **Step 3: Implement the minimal pure transition**

Add:

```python
def confirm_local_recording_saved(status: RecorderStatus) -> RecorderStatus:
    if type(status) is not RecorderStatus or status.state != "stopped":
        raise ValueError("only a stopped recording can be confirmed")
    return RecorderStatus(
        mode=status.mode,
        state="saved",
        duration_seconds=status.duration_seconds,
        camera_ready=status.camera_ready,
        microphone_ready=status.microphone_ready,
        saved_confirmed=True,
    )
```

Update the existing AST capability assertion to allow only the constructor call
to `RecorderStatus`; retain the single-import and prohibited-fragment checks.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -m pytest tests/test_local_recording_workflow.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add local_recording_workflow.py tests/test_local_recording_workflow.py
git commit -m "feat: confirm stopped recordings on host"
```

### Task 2: Main-page continuation action

**Files:**
- Modify: `tests/test_app_integration.py`
- Modify: `app.py`

- [ ] **Step 1: Write the failing AppTest coverage**

For a stopped recorder status, assert that the page shows a primary button
labeled `我已下载并检查录像，继续填写问卷`, does not call the questionnaire,
and keeps recording metadata empty. Click the button and rerun; assert exact
version-2 saved metadata, one questionnaire render, and visible `③ 正式问卷`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_app_integration.py -k "host_confirmation" -q`

Expected: failure because the host confirmation button is absent.

- [ ] **Step 3: Implement the minimal Streamlit action**

Import `confirm_local_recording_saved`. When `recorder_status.state ==
"stopped"`, render instructions to open the local file and verify video and
sound, plus the primary button. On click, write
`local_recording_metadata(confirm_local_recording_saved(recorder_status))` to
`record["recording"]` and call `st.rerun()`. Use a key beginning with
`operational_recorder::` so existing session cleanup owns it.

- [ ] **Step 4: Run focused and related tests**

Run: `python -m pytest tests/test_app_integration.py tests/test_local_recording_workflow.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_app_integration.py
git commit -m "fix: continue from local recording on main page"
```

### Task 3: Full verification and release

**Files:**
- Verify only.

- [ ] **Step 1: Run complete verification**

Run:

```powershell
python -m pytest -q
node --test tests/js/test_recorder_core.mjs
python -m py_compile app.py browser_recorder.py local_recording_workflow.py
git diff --check origin/main..HEAD
```

Expected: zero failures and zero diff-check output.

- [ ] **Step 2: Fast-forward private `main`**

Run `git push origin HEAD:main`, retrying transient failures without force.

