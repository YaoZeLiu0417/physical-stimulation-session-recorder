# Privacy-Safe Functional Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give invited teachers a password-protected end-to-end demonstration with real live camera permission, four neutral slider questions, completion, and restart without exposing or retaining research content or participant data.

**Architecture:** Isolate all WebRTC configuration in a new `showcase_media.py` boundary that provides live video only and has no recorder, callback, file, or upload capability. Keep authentication, navigation, synthetic feedback, and state cleanup in `showcase_app.py`; preserve the existing pure transition table in `showcase_workflow.py`.

**Tech Stack:** Python 3.10, Streamlit 1.37.1, streamlit-webrtc 0.63.4, pytest 8, Streamlit `AppTest`, Git, GitHub CLI, Streamlit Community Cloud.

---

## File Map

- Create: `showcase_media.py` - the only WebRTC boundary; live video, no audio, recording, callbacks, or persistence.
- Create: `tests/test_showcase_media.py` - configuration, playing-state, and media-boundary privacy tests.
- Modify: `showcase_app.py` - render live camera preview, four synthetic sliders, error fallback, and restart cleanup.
- Modify: `tests/test_showcase_app.py` - stub the media boundary and verify the complete camera/feedback flow and privacy behavior.
- Preserve: `showcase_workflow.py`, all questionnaire modules, upload/storage modules, production `app.py`, dependency pins, and `.streamlit/config.toml`.

Run all commands from:

```powershell
Set-Location 'D:\proj_taVNS\.worktrees\physical-stimulation-session-recorder\private-source-public-showcase'
```

### Task 1: Add The Ephemeral Live-Camera Boundary

**Files:**
- Create: `showcase_media.py`
- Create: `tests/test_showcase_media.py`

- [ ] **Step 1: Write the failing media-boundary tests**

Create `tests/test_showcase_media.py`:

```python
import ast
from pathlib import Path
from types import SimpleNamespace

import showcase_media
from streamlit_webrtc import WebRtcMode


MEDIA_SOURCE = Path(__file__).resolve().parents[1] / "showcase_media.py"


def test_render_live_camera_uses_video_only_ephemeral_configuration(
    monkeypatch,
) -> None:
    calls = []
    sentinel = object()

    def fake_webrtc_streamer(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(showcase_media, "webrtc_streamer", fake_webrtc_streamer)

    assert showcase_media.render_live_camera() is sentinel
    assert calls == [
        {
            "key": "showcase_camera_preview",
            "mode": WebRtcMode.SENDRECV,
            "rtc_configuration": {
                "iceServers": [
                    {"urls": ["stun:stun.l.google.com:19302"]}
                ]
            },
            "media_stream_constraints": {"video": True, "audio": False},
            "sendback_audio": False,
            "video_html_attrs": {
                "autoPlay": True,
                "controls": False,
                "muted": True,
            },
        }
    ]
    prohibited = {
        "player_factory",
        "in_recorder_factory",
        "out_recorder_factory",
        "video_frame_callback",
        "audio_frame_callback",
        "queued_video_frames_callback",
        "queued_audio_frames_callback",
        "video_processor_factory",
        "audio_processor_factory",
    }
    assert prohibited.isdisjoint(calls[0])


def test_camera_is_playing_is_fail_closed() -> None:
    assert showcase_media.camera_is_playing(None) is False
    assert showcase_media.camera_is_playing(SimpleNamespace()) is False
    assert showcase_media.camera_is_playing(
        SimpleNamespace(state=SimpleNamespace(playing=False))
    ) is False
    assert showcase_media.camera_is_playing(
        SimpleNamespace(state=SimpleNamespace(playing=True))
    ) is True


def test_media_boundary_has_no_private_or_persistence_imports() -> None:
    tree = ast.parse(MEDIA_SOURCE.read_text(encoding="utf-8"))
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    prohibited_fragments = (
        "aiortc",
        "av",
        "pathlib",
        "questionnaire",
        "record",
        "requests",
        "upload",
    )
    assert not any(
        fragment in module.casefold()
        for module in imported_modules
        for fragment in prohibited_fragments
    )
```

- [ ] **Step 2: Run the tests and verify the intended RED state**

Run:

```powershell
python -m pytest tests/test_showcase_media.py -q
```

Expected: collection error because `showcase_media` does not exist.

- [ ] **Step 3: Implement the minimal media boundary**

Create `showcase_media.py`:

```python
from __future__ import annotations

from typing import Any

from streamlit_webrtc import WebRtcMode, webrtc_streamer


RTC_CONFIGURATION = {
    "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
}
MEDIA_STREAM_CONSTRAINTS = {"video": True, "audio": False}


def render_live_camera() -> Any:
    return webrtc_streamer(
        key="showcase_camera_preview",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration=RTC_CONFIGURATION,
        media_stream_constraints=MEDIA_STREAM_CONSTRAINTS,
        sendback_audio=False,
        video_html_attrs={
            "autoPlay": True,
            "controls": False,
            "muted": True,
        },
    )


def camera_is_playing(context: Any) -> bool:
    state = getattr(context, "state", None)
    return bool(getattr(state, "playing", False))
```

- [ ] **Step 4: Run the media tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_showcase_media.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Check and commit the isolated media boundary**

Run:

```powershell
git diff -- showcase_media.py tests/test_showcase_media.py
git diff --check
git add showcase_media.py tests/test_showcase_media.py
git commit -m "feat: add ephemeral showcase camera"
```

Expected: one commit containing exactly the media module and its tests.

### Task 2: Integrate The Live Camera Into The Four-Step Page

**Files:**
- Modify: `showcase_app.py`
- Modify: `tests/test_showcase_app.py`
- Test: `tests/test_showcase_media.py`
- Test: `tests/test_showcase_workflow.py`

- [ ] **Step 1: Add the camera stub and failing page assertions**

Add these imports to `tests/test_showcase_app.py`:

```python
from types import SimpleNamespace

import pytest

import showcase_media
```

Add this autouse fixture after the constants:

```python
@pytest.fixture(autouse=True)
def _stub_live_camera(monkeypatch):
    monkeypatch.setattr(
        showcase_media,
        "render_live_camera",
        lambda: SimpleNamespace(state=SimpleNamespace(playing=True)),
    )
```

Add `"warning"` to `_visible_text()`'s collection list. In
`test_showcase_completes_and_restarts_session_only_flow`, replace the capture
assertions with:

```python
    capture_text = _visible_text(app)
    assert "实时摄像预览" in capture_text
    assert "摄像头" in capture_text
    assert "不写入文件" in capture_text
    assert "项目存储" in capture_text
    assert app.session_state["showcase_camera_started"] is True
    _assert_progress(app, "2 会话记录")
    _element_by_key(app.button, "finish_capture").click().run()
```

Add this failure-path test:

```python
def test_camera_initialization_failure_keeps_the_flow_available(monkeypatch):
    def unavailable_camera():
        raise RuntimeError("synthetic camera failure")

    monkeypatch.setattr(showcase_media, "render_live_camera", unavailable_camera)
    app = _authenticate(_app_with_password())
    _element_by_key(app.button, "begin_demo").click().run()

    assert not app.exception
    assert [item.value for item in app.warning] == [
        "摄像头暂时不可用，可继续体验后续流程。"
    ]
    _element_by_key(app.button, "finish_capture").click().run()
    assert app.session_state["showcase_step"] == "reflection"
```

- [ ] **Step 2: Run the focused page tests and verify RED**

Run:

```powershell
python -m pytest tests/test_showcase_app.py -q
```

Expected: failures because the page still renders the simulated progress panel,
does not set `showcase_camera_started`, and has no camera failure fallback.

- [ ] **Step 3: Add the live-camera page integration**

Add to the top of `showcase_app.py`:

```python
import logging

from showcase_media import camera_is_playing, render_live_camera
```

Add beside the product constants:

```python
LOGGER = logging.getLogger(__name__)
```

Replace the complete `step == "capture"` branch with:

```python
    elif step == "capture":
        st.subheader("实时摄像预览")
        st.caption(
            "点击 START 后，浏览器会请求摄像头权限。视频不写入文件，"
            "也不会保存到项目存储。"
        )
        try:
            camera_context = render_live_camera()
        except Exception:
            LOGGER.warning("showcase camera preview unavailable", exc_info=True)
            camera_context = None
            st.warning("摄像头暂时不可用，可继续体验后续流程。")

        if camera_is_playing(camera_context):
            st.session_state["showcase_camera_started"] = True
            st.info("摄像头已连接。完成预览后可继续。")
        else:
            st.info("等待摄像头连接。也可直接继续体验后续流程。")

        if st.button("完成摄像演示", type="primary", key="finish_capture"):
            _go("finish_capture")
```

- [ ] **Step 4: Run all focused showcase tests**

Run:

```powershell
python -m pytest tests/test_showcase_media.py tests/test_showcase_app.py tests/test_showcase_workflow.py -q
```

Expected: `37 passed`.

- [ ] **Step 5: Confirm no persistence capability entered the page and commit**

Run:

```powershell
python -m pytest tests/test_showcase_app.py::test_showcase_source_has_no_private_or_io_capabilities -q
git diff --check
git add showcase_app.py tests/test_showcase_app.py
git commit -m "feat: integrate live showcase camera"
```

Expected: the source privacy test passes and the commit contains only the page
and page-test changes.

### Task 3: Expand Neutral Feedback And Clear Session State

**Files:**
- Modify: `showcase_app.py`
- Modify: `tests/test_showcase_app.py`

- [ ] **Step 1: Extend the flow test before changing the page**

Add these constants to `tests/test_showcase_app.py`:

```python
SYNTHETIC_RESPONSES = {
    "process_clarity": 3,
    "camera_smoothness": 4,
    "information_load": 1,
    "workflow_willingness": 4,
}
SYNTHETIC_LABELS = (
    "本次演示流程有多清晰？",
    "摄像头交互有多顺畅？",
    "界面的信息量有多合适？",
    "你愿意继续使用这一流程吗？",
)
```

In `test_showcase_completes_and_restarts_session_only_flow`, replace the two
slider assertions and assignments with:

```python
    for key in SYNTHETIC_RESPONSES:
        assert _element_by_key(app.slider, key).value == 2
    assert tuple(element.label for element in app.slider) == SYNTHETIC_LABELS
    _assert_progress(app, "3 引导反馈")

    for key, value in SYNTHETIC_RESPONSES.items():
        _element_by_key(app.slider, key).set_value(value)
    app.run()
    _element_by_key(app.button, "save_reflection").click().run()
```

After the confirmation privacy assertions, add:

```python
    confirmation_text = _visible_text(app)
    assert "总分" not in confirmation_text
    assert "得分" not in confirmation_text
    assert not app.metric
    for label in SYNTHETIC_LABELS:
        assert label not in confirmation_text

    _element_by_key(app.button, "restart_demo").click().run()
    assert app.session_state["showcase_step"] == "overview"
    for key in (*SYNTHETIC_RESPONSES, "showcase_camera_started"):
        assert key not in app.session_state
```

Remove the old separate `restart_app` block from this test.

- [ ] **Step 2: Run the complete-flow test and verify RED**

Run:

```powershell
python -m pytest tests/test_showcase_app.py::test_showcase_completes_and_restarts_session_only_flow -q
```

Expected: failure because only two old slider keys exist and restart does not
clear the four approved response keys or camera state.

- [ ] **Step 3: Add the four neutral controls and cleanup constant**

Add beside the product constants in `showcase_app.py`:

```python
SYNTHETIC_RESPONSE_KEYS = (
    "process_clarity",
    "camera_smoothness",
    "information_load",
    "workflow_willingness",
)
```

Replace the complete reflection branch with:

```python
    elif step == "reflection":
        st.subheader("演示反馈")
        st.caption("以下为通用合成反馈，不对应任何研究测量内容或评分规则。")
        st.slider(
            "本次演示流程有多清晰？", 0, 4, 2, key="process_clarity"
        )
        st.slider(
            "摄像头交互有多顺畅？", 0, 4, 2, key="camera_smoothness"
        )
        st.slider(
            "界面的信息量有多合适？", 0, 4, 2, key="information_load"
        )
        st.slider(
            "你愿意继续使用这一流程吗？",
            0,
            4,
            2,
            key="workflow_willingness",
        )
        if st.button("提交演示反馈", type="primary", key="save_reflection"):
            _go("save_reflection")
```

Replace the restart cleanup with:

```python
        if st.button("重新体验", key="restart_demo"):
            for key in (*SYNTHETIC_RESPONSE_KEYS, "showcase_camera_started"):
                st.session_state.pop(key, None)
            _go("restart")
```

- [ ] **Step 4: Run the complete focused showcase suite**

Run:

```powershell
python -m pytest tests/test_showcase_media.py tests/test_showcase_app.py tests/test_showcase_workflow.py -q
```

Expected: `37 passed`.

- [ ] **Step 5: Re-run neutral-copy, privacy, and palette gates**

Run:

```powershell
python -m pytest `
  tests/test_showcase_app.py::test_visible_copy_is_neutral_on_every_authenticated_step `
  tests/test_showcase_app.py::test_showcase_source_has_no_private_or_io_capabilities `
  tests/test_showcase_app.py::test_streamlit_theme_and_app_palette_are_exact_and_green_free `
  -q
```

Expected: `3 passed`; no private study terms, recording/file APIs, score output,
green palette, or gradient enters the page.

- [ ] **Step 6: Commit the neutral feedback workflow**

Run:

```powershell
git diff --check
git add showcase_app.py tests/test_showcase_app.py
git commit -m "feat: add neutral showcase feedback"
```

Expected: one commit containing only the synthetic feedback and cleanup changes.

### Task 4: Verify, Release Privately, And Validate The Teacher Flow

**Files:**
- Verify: all source and tests
- Release: `feat/privacy-safe-functional-showcase`
- Deploy: private `main` / `showcase_app.py`

- [ ] **Step 1: Run focused and dependency contract gates**

Run:

```powershell
python -m pytest tests/test_requirements_contract.py tests/test_showcase_media.py tests/test_showcase_app.py tests/test_showcase_workflow.py -q
```

Expected: `38 passed`.

- [ ] **Step 2: Run the full regression and compilation gates**

Run:

```powershell
python -m pytest -q
python -m compileall -q app.py app_workflow.py link_auth.py questionnaire_scoring.py questionnaire_specs.py questionnaire_ui.py record_store.py showcase_app.py showcase_audit.py showcase_media.py showcase_workflow.py upload_workflow.py tests
git diff --check origin/main...HEAD
git status --short --branch
```

Expected: `407 passed, 3 skipped`, compilation exits `0`, patch check is silent,
and the worktree is clean.

- [ ] **Step 3: Reconfirm private scope before pushing**

Run:

```powershell
$repoState = gh repo view YaoZeLiu0417/physical-stimulation-session-recorder --json visibility,defaultBranchRef | ConvertFrom-Json
if ($repoState.visibility -ne 'PRIVATE') { throw 'Source repository is not private' }
if ($repoState.defaultBranchRef.name -ne 'main') { throw 'Unexpected default branch' }
git diff --name-only origin/main...HEAD
```

Expected: visibility `PRIVATE`; changes are limited to the approved design/plan,
`showcase_media.py`, `showcase_app.py`, and their focused tests.

- [ ] **Step 4: Push and merge a private pull request**

Run:

```powershell
git push --set-upstream origin feat/privacy-safe-functional-showcase
$prUrl = gh pr create `
  --repo YaoZeLiu0417/physical-stimulation-session-recorder `
  --base main `
  --head feat/privacy-safe-functional-showcase `
  --title 'Add privacy-safe functional showcase' `
  --body 'Adds an ephemeral live-camera preview and four neutral synthetic feedback controls to the password-protected showcase. No recording, file persistence, upload, research instrument, participant data, or score output is introduced. Full local regression and privacy gates pass.'
$prNumber = [int](Split-Path $prUrl -Leaf)
gh pr diff $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder --name-only
gh pr checks $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder
gh pr merge $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder --merge --delete-branch
```

Expected: exact private PR diff, no failed configured checks, merge commit on
private `main`, and remote feature branch deleted. If GitHub reports no checks,
use the fresh local gates as the release evidence.

- [ ] **Step 5: Verify post-merge privacy and deployment response**

Run unauthenticated GitHub checks:

```powershell
$anonymousUrls = @(
  'https://api.github.com/repos/YaoZeLiu0417/physical-stimulation-session-recorder',
  'https://raw.githubusercontent.com/YaoZeLiu0417/physical-stimulation-session-recorder/main/showcase_app.py'
)
foreach ($url in $anonymousUrls) {
    $status = curl.exe -sS -o NUL -w '%{http_code}' $url
    if ($status -ne '404') { throw "Anonymous request returned $status" }
}
```

Expected: both URLs return `404` and repository visibility remains `PRIVATE`.
Wait for Community Cloud to rebuild `showcase_app.py`; do not treat the platform
authentication redirect as application health. Confirm the app opens through
the user's authorized browser session.

- [ ] **Step 6: Complete the signed-in teacher-flow checklist**

At `https://physical-stimulation-session-recorder.streamlit.app` verify:

1. wrong password is rejected;
2. approved password opens the overview;
3. the camera step requests browser video permission but not microphone access;
4. START shows a live preview and no download/upload/file UI appears;
5. denial or unavailable camera still permits continuing without a traceback;
6. four neutral sliders appear and no study instrument or total score appears;
7. completion does not echo responses;
8. restart returns to overview and starts a fresh synthetic session.

Expected: all eight checks pass. Browser automation must use the in-app Browser
runtime if available; do not substitute external Playwright. If browser control
is unavailable, obtain the user's visual confirmation after all automated gates
and deployment evidence pass.

## Agent Retry Rule

If any implementation or review subagent fails specifically with HTTP `429`,
wait 5-10 seconds and automatically dispatch a fresh retry with the same bounded
task, worktree, and acceptance criteria. Do not change application code in
response to an agent-service rate limit.
