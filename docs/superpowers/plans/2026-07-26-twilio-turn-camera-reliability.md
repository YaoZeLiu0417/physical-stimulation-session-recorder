# Twilio TURN Camera Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Streamlit Community Cloud STUN-only white-screen path with a Twilio TURN-backed, video-only preview that fails closed and never asks users to rate a camera interaction they could not experience.

**Architecture:** Add `showcase_ice.py` as the only Twilio credential-exchange boundary. It accepts server-side secrets and returns only a short-lived TURN-capable RTC configuration; `showcase_media.py` consumes that configuration and remains free of credential, recording, callback, file, and upload logic. `showcase_app.py` renders the component only when TURN is available and conditionally renders the camera feedback item only after a connected preview.

**Tech Stack:** Python 3.10, Streamlit 1.37.1, streamlit-webrtc 0.63.4, aiortc 1.15.0, Twilio Python SDK 9.x, pytest 8, Streamlit AppTest, GitHub CLI, Streamlit Community Cloud.

---

## File Map

- Create: `showcase_ice.py` - exchange server-only Twilio credentials for short-lived TURN configuration and reject non-TURN results.
- Create: `tests/test_showcase_ice.py` - credential, TURN classification, failure, and source-boundary tests.
- Modify: `showcase_media.py` - accept the resolved RTC configuration and restore explicit responsive video attributes.
- Modify: `tests/test_showcase_media.py` - lock explicit video return, audio denial, responsive rendering, and prohibited capabilities.
- Modify: `showcase_app.py` - fail closed when TURN is unavailable and skip camera feedback unless preview connected.
- Modify: `tests/test_showcase_app.py` - stub TURN, verify no-TURN flow, and retain confirmation privacy inventory.
- Modify: `requirements.txt` - add bounded Twilio SDK dependency.
- Modify: `tests/test_requirements_contract.py` - lock the production dependency set.
- Preserve: `showcase_workflow.py`, questionnaire modules, recording/storage modules, deployment configuration, public repository, and all research materials.

Run all commands from:

```powershell
Set-Location 'D:\proj_taVNS\.worktrees\physical-stimulation-session-recorder\twilio-turn-preview'
```

### Task 1: Add The Server-Only TURN Configuration Boundary

**Files:**
- Create: `showcase_ice.py`
- Create: `tests/test_showcase_ice.py`
- Modify: `requirements.txt`
- Modify: `tests/test_requirements_contract.py`

- [ ] **Step 1: Write failing TURN resolver and dependency tests**

Create `tests/test_showcase_ice.py`:

```python
import ast
from pathlib import Path

import pytest

import showcase_ice


ICE_SOURCE = Path(__file__).resolve().parents[1] / "showcase_ice.py"


def test_resolve_turn_rtc_configuration_returns_short_lived_turn_servers(
    monkeypatch,
) -> None:
    ice_servers = [
        {"urls": "stun:global.stun.twilio.com:3478"},
        {
            "urls": ["turn:global.turn.twilio.com:3478?transport=udp"],
            "username": "ephemeral-user",
            "credential": "ephemeral-credential",
        },
    ]
    calls = []

    def fake_get_twilio_ice_servers(account_sid, auth_token):
        calls.append((account_sid, auth_token))
        return ice_servers

    monkeypatch.setattr(
        showcase_ice,
        "get_twilio_ice_servers",
        fake_get_twilio_ice_servers,
    )

    assert showcase_ice.resolve_turn_rtc_configuration(
        "  test-account  ", "  test-token  "
    ) == {"iceServers": ice_servers}
    assert calls == [("test-account", "test-token")]


@pytest.mark.parametrize(
    ("account_sid", "auth_token"),
    (("", ""), ("account", ""), ("", "token"), ("   ", "token")),
)
def test_resolve_turn_rtc_configuration_rejects_missing_credentials(
    monkeypatch, account_sid, auth_token
) -> None:
    def unexpected_call(*_args):
        raise AssertionError("Twilio must not be called")

    monkeypatch.setattr(
        showcase_ice,
        "get_twilio_ice_servers",
        unexpected_call,
    )

    assert (
        showcase_ice.resolve_turn_rtc_configuration(account_sid, auth_token)
        is None
    )


def test_resolve_turn_rtc_configuration_rejects_stun_only_and_failures(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        showcase_ice,
        "get_twilio_ice_servers",
        lambda *_args: [{"urls": ["stun:stun.l.google.com:19302"]}],
    )
    assert showcase_ice.resolve_turn_rtc_configuration("account", "token") is None

    def unavailable(*_args):
        raise RuntimeError("credential exchange detail")

    monkeypatch.setattr(showcase_ice, "get_twilio_ice_servers", unavailable)
    assert showcase_ice.resolve_turn_rtc_configuration("account", "token") is None


def test_ice_boundary_has_no_page_file_or_persistence_capabilities() -> None:
    source = ICE_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
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
    assert imported_modules == {
        "__future__",
        "typing",
        "streamlit_webrtc.credentials",
    }
    prohibited = (
        "questionnaire",
        "record",
        "upload",
        "pathlib",
        "requests",
    )
    assert not any(
        fragment in module.casefold()
        for module in imported_modules
        for fragment in prohibited
    )
    assert "print(" not in source
    assert "logging" not in source
```

In `tests/test_requirements_contract.py`, insert the expected dependency after `av`:

```python
        "twilio>=9.0,<10",
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_showcase_ice.py tests/test_requirements_contract.py -q
```

Expected: collection fails because `showcase_ice` does not exist, and the requirements contract does not yet contain Twilio.

- [ ] **Step 3: Implement the minimal TURN resolver**

Create `showcase_ice.py`:

```python
from __future__ import annotations

from typing import Any

from streamlit_webrtc.credentials import get_twilio_ice_servers


def _contains_turn(ice_servers: list[dict[str, Any]]) -> bool:
    for server in ice_servers:
        urls = server.get("urls", ())
        if isinstance(urls, str):
            urls = (urls,)
        if any(
            isinstance(url, str)
            and url.casefold().startswith(("turn:", "turns:"))
            for url in urls
        ):
            return True
    return False


def resolve_turn_rtc_configuration(
    account_sid: str,
    auth_token: str,
) -> dict[str, Any] | None:
    account_sid = account_sid.strip()
    auth_token = auth_token.strip()
    if not account_sid or not auth_token:
        return None

    try:
        ice_servers = get_twilio_ice_servers(account_sid, auth_token)
    except Exception:
        return None

    if not _contains_turn(ice_servers):
        return None
    return {"iceServers": ice_servers}
```

Add to `requirements.txt` after `av`:

```text
twilio>=9.0,<10       # short-lived TURN credentials
```

- [ ] **Step 4: Verify GREEN and dependency resolution**

Run:

```powershell
python -m pytest tests/test_showcase_ice.py tests/test_requirements_contract.py -q
python -m pip install --dry-run -r requirements.txt
```

Expected: resolver and contract tests pass; pip reports a satisfiable dependency set including Twilio 9.x without installing it into the active environment.

- [ ] **Step 5: Commit the isolated TURN boundary**

Run:

```powershell
git diff --check
git add showcase_ice.py tests/test_showcase_ice.py requirements.txt tests/test_requirements_contract.py
git commit -m "feat: add private TURN configuration"
```

Expected: one commit containing only the resolver, dependency, and their tests.

### Task 2: Make The Media Preview Explicit And Responsive

**Files:**
- Modify: `showcase_media.py`
- Modify: `tests/test_showcase_media.py`

- [ ] **Step 1: Change the media test first**

In `tests/test_showcase_media.py`, define a TURN-capable configuration and call the renderer with it:

```python
TURN_RTC_CONFIGURATION = {
    "iceServers": [
        {
            "urls": ["turn:global.turn.twilio.com:3478?transport=udp"],
            "username": "ephemeral-user",
            "credential": "ephemeral-credential",
        }
    ]
}
```

Change the call and exact expected kwargs to:

```python
    assert showcase_media.render_live_camera(TURN_RTC_CONFIGURATION) is sentinel
    assert calls == [
        {
            "key": "showcase_camera_preview",
            "mode": WebRtcMode.SENDRECV,
            "rtc_configuration": TURN_RTC_CONFIGURATION,
            "media_stream_constraints": {"video": True, "audio": False},
            "sendback_video": True,
            "sendback_audio": False,
            "video_html_attrs": {
                "autoPlay": True,
                "controls": False,
                "muted": True,
                "playsInline": True,
                "style": {"width": "100%"},
            },
        }
    ]
```

Keep the prohibited recorder/callback/processor assertion unchanged.

- [ ] **Step 2: Run the media test and verify RED**

Run:

```powershell
python -m pytest tests/test_showcase_media.py::test_render_live_camera_uses_video_only_ephemeral_configuration -q
```

Expected: failure because `render_live_camera` takes no argument and lacks explicit `sendback_video`, inline playback, and responsive width.

- [ ] **Step 3: Implement the minimal media change**

Replace the fixed STUN constant and renderer in `showcase_media.py` with:

```python
MEDIA_STREAM_CONSTRAINTS = {"video": True, "audio": False}


def render_live_camera(rtc_configuration: dict[str, Any]) -> Any:
    return webrtc_streamer(
        key="showcase_camera_preview",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration=rtc_configuration,
        media_stream_constraints=MEDIA_STREAM_CONSTRAINTS,
        sendback_video=True,
        sendback_audio=False,
        video_html_attrs={
            "autoPlay": True,
            "controls": False,
            "muted": True,
            "playsInline": True,
            "style": {"width": "100%"},
        },
    )
```

- [ ] **Step 4: Verify media boundary GREEN**

Run:

```powershell
python -m pytest tests/test_showcase_media.py -q
git diff --check
```

Expected: all media tests pass and the source allowlist still permits only `getattr` and `webrtc_streamer` calls.

- [ ] **Step 5: Commit the media change**

Run:

```powershell
git add showcase_media.py tests/test_showcase_media.py
git commit -m "fix: render responsive TURN camera"
```

Expected: one commit containing only the media boundary and its tests.

### Task 3: Fail Closed In The Page And Skip Invalid Camera Feedback

**Files:**
- Modify: `showcase_app.py`
- Modify: `tests/test_showcase_app.py`

- [ ] **Step 1: Update the default test boundaries before page code**

Add to `tests/test_showcase_app.py`:

```python
import showcase_ice


TURN_RTC_CONFIGURATION = {
    "iceServers": [
        {
            "urls": ["turn:global.turn.twilio.com:3478?transport=udp"],
            "username": "ephemeral-user",
            "credential": "ephemeral-credential",
        }
    ]
}
```

Replace the autouse fixture with:

```python
@pytest.fixture(autouse=True)
def _stub_live_camera(monkeypatch):
    monkeypatch.setattr(
        showcase_ice,
        "resolve_turn_rtc_configuration",
        lambda account_sid, auth_token: TURN_RTC_CONFIGURATION,
    )
    monkeypatch.setattr(
        showcase_media,
        "render_live_camera",
        lambda rtc_configuration: SimpleNamespace(
            state=SimpleNamespace(playing=True)
        ),
    )
```

In `_app_with_password`, add synthetic test-only Twilio secrets:

```python
    app.secrets["TWILIO_ACCOUNT_SID"] = "test-account"
    app.secrets["TWILIO_AUTH_TOKEN"] = "test-token"
```

Update the failure stub to accept `rtc_configuration`:

```python
    def unavailable_camera(_rtc_configuration):
        raise RuntimeError("synthetic camera failure")
```

- [ ] **Step 2: Add a failing no-TURN flow test**

Add:

```python
def test_missing_turn_skips_preview_and_camera_feedback(monkeypatch):
    monkeypatch.setattr(
        showcase_ice,
        "resolve_turn_rtc_configuration",
        lambda account_sid, auth_token: None,
    )

    def unexpected_camera(_rtc_configuration):
        raise AssertionError("camera component must not render without TURN")

    monkeypatch.setattr(showcase_media, "render_live_camera", unexpected_camera)
    app = _authenticate(_app_with_password())
    _element_by_key(app.button, "begin_demo").click().run()

    assert not app.exception
    assert [item.value for item in app.warning] == [
        "实时摄像预览暂时不可用，可继续体验后续流程。"
    ]
    assert "showcase_camera_started" not in app.session_state

    _element_by_key(app.button, "finish_capture").click().run()
    assert tuple(slider.key for slider in app.slider) == (
        "process_clarity",
        "information_load",
        "workflow_willingness",
    )
    assert "本次未建立实时摄像预览，无需评价摄像头交互。" in [
        item.value for item in app.caption
    ]
    assert "camera_smoothness" not in app.session_state

    _element_by_key(app.button, "save_reflection").click().run()
    assert app.session_state["showcase_step"] == "confirmation"

    confirmation_app = _app_with_password()
    confirmation_app.session_state["showcase_authenticated"] = True
    confirmation_app.session_state["showcase_step"] = "confirmation"
    confirmation_app.run()
    assert (
        _main_content_inventory(confirmation_app)
        == EXPECTED_CONFIRMATION_INVENTORY
    )
```

- [ ] **Step 3: Run page tests and verify RED**

Run:

```powershell
python -m pytest tests/test_showcase_app.py -q
```

Expected: failures because `showcase_ice` is not used, `render_live_camera` receives no RTC configuration, and the camera feedback slider always renders.

- [ ] **Step 4: Implement TURN-gated capture rendering**

Add to `showcase_app.py`:

```python
from showcase_ice import resolve_turn_rtc_configuration
```

Replace the capture branch's camera setup with:

```python
        st.caption(
            "实时预览仅使用摄像头，不启用麦克风；视频不写入文件，"
            "也不会保存到项目存储。"
        )
        camera_unavailable = False
        camera_context = None
        try:
            rtc_configuration = resolve_turn_rtc_configuration(
                _secret("TWILIO_ACCOUNT_SID"),
                _secret("TWILIO_AUTH_TOKEN"),
            )
            if rtc_configuration is None:
                camera_unavailable = True
            else:
                camera_context = render_live_camera(rtc_configuration)
        except Exception:
            camera_unavailable = True
            LOGGER.warning("showcase camera preview unavailable")

        if camera_unavailable:
            st.warning("实时摄像预览暂时不可用，可继续体验后续流程。")
        elif camera_is_playing(camera_context):
            st.session_state["showcase_camera_started"] = True
            st.info("摄像头已连接。完成预览后可继续。")
        else:
            st.info("正在建立安全摄像预览连接。若长时间无画面，可继续后续流程。")
```

Do not log exception objects or `exc_info`.

- [ ] **Step 5: Implement conditional camera feedback**

In the reflection branch, replace the unconditional camera slider with:

```python
        if st.session_state.get("showcase_camera_started") is True:
            st.slider(
                "摄像头交互有多顺畅？",
                0,
                4,
                2,
                key="camera_smoothness",
            )
        else:
            st.session_state.pop("camera_smoothness", None)
            st.caption("本次未建立实时摄像预览，无需评价摄像头交互。")
```

Keep `camera_smoothness` in `SYNTHETIC_RESPONSE_KEYS` so restart clears stale state defensively.

- [ ] **Step 6: Verify page GREEN and privacy gates**

Run:

```powershell
python -m pytest tests/test_showcase_app.py -q
python -m pytest `
  tests/test_showcase_app.py::test_visible_copy_is_neutral_on_every_authenticated_step `
  tests/test_showcase_app.py::test_showcase_source_has_no_private_or_io_capabilities `
  tests/test_showcase_app.py::test_streamlit_theme_and_app_palette_are_exact_and_green_free `
  -q
git diff --check
```

Expected: all page tests pass; confirmation inventory stays exact; no private terms, IO capability, green palette, gradient, score, or response echo appears.

- [ ] **Step 7: Commit the page behavior**

Run:

```powershell
git add showcase_app.py tests/test_showcase_app.py
git commit -m "fix: fail closed when camera relay is unavailable"
```

Expected: one commit containing only page behavior and its focused tests.

### Task 4: Verify, Release Privately, And Configure The Runtime Secret Gate

**Files:**
- Verify: all changed source, tests, and requirements.
- Release: branch `fix/twilio-turn-preview` to private `main`.
- Runtime: Streamlit Community Cloud Secrets, managed outside Git.

- [ ] **Step 1: Run focused and dependency gates**

Run:

```powershell
python -m pytest tests/test_requirements_contract.py tests/test_showcase_ice.py tests/test_showcase_media.py tests/test_showcase_app.py tests/test_showcase_workflow.py -q
python -m pip install --dry-run -r requirements.txt
```

Expected: all focused tests pass and the production dependency set resolves with Twilio 9.x.

- [ ] **Step 2: Run the full regression and compilation gates**

Run:

```powershell
python -m pytest -q
python -m compileall -q app.py app_workflow.py link_auth.py questionnaire_scoring.py questionnaire_specs.py questionnaire_ui.py record_store.py showcase_app.py showcase_audit.py showcase_ice.py showcase_media.py showcase_workflow.py upload_workflow.py tests
git diff --check origin/main...HEAD
git status --short --branch
```

Expected: all tests pass, compilation exits `0`, diff check is silent, and the worktree is clean.

- [ ] **Step 3: Reconfirm private scope and exact diff**

Run:

```powershell
$repoState = gh repo view YaoZeLiu0417/physical-stimulation-session-recorder --json visibility,defaultBranchRef | ConvertFrom-Json
if ($repoState.visibility -ne 'PRIVATE') { throw 'Source repository is not private' }
if ($repoState.defaultBranchRef.name -ne 'main') { throw 'Unexpected default branch' }
git diff --name-only origin/main...HEAD
rg -n --hidden --glob '!docs/superpowers/**' --glob '!tests/**' 'AC[a-zA-Z0-9]{20,}|TWILIO_AUTH_TOKEN\s*=|TWILIO_ACCOUNT_SID\s*=' .
```

Expected: private `main`; only the approved design/plan, ICE/media/page modules, focused tests, and requirements files changed; no credential value or assignment appears.

- [ ] **Step 4: Push and merge a private pull request**

Run:

```powershell
git push --set-upstream origin fix/twilio-turn-preview
$prUrl = gh pr create `
  --repo YaoZeLiu0417/physical-stimulation-session-recorder `
  --base main `
  --head fix/twilio-turn-preview `
  --title 'Fix camera preview with private TURN relay' `
  --body 'Adds server-side Twilio TURN credential exchange, a responsive video-only preview, and fail-closed feedback behavior. Account credentials remain in Streamlit Secrets; no microphone, recording, file persistence, upload, research content, participant data, or score output is introduced.'
$prNumber = [int](Split-Path $prUrl -Leaf)
gh pr diff $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder --name-only
gh pr checks $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder
gh pr merge $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder --merge --delete-branch
```

Expected: exact private PR diff, no failed configured checks, merge commit on private `main`, and remote feature branch deleted. If GitHub reports no checks, use the fresh local gates as release evidence.

- [ ] **Step 5: Reconfirm post-merge privacy and deployment response**

Run anonymous checks against the private repository API and raw source; both must return `404`. Confirm the Streamlit URL still reaches the platform authentication boundary and wait for the dependency rebuild to finish.

- [ ] **Step 6: Configure Twilio secrets outside Git**

In the Streamlit Community Cloud app settings, the user adds the root-level
keys `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` through the secret editor,
using the corresponding values from the private Twilio console.

Do not paste real values into chat, shell history, Git, screenshots, logs, or README. Save the secret configuration and wait for the app to restart.

- [ ] **Step 7: Complete the signed-in teacher-flow checklist**

At `https://physical-stimulation-session-recorder.streamlit.app`, verify:

1. wrong password is rejected and the approved password opens the overview;
2. capture requests camera permission but not microphone permission;
3. START reaches `摄像头已连接` and displays a nonblank live image;
4. the preview fits the page width without overlap;
5. successful preview yields all four neutral sliders;
6. missing/unavailable TURN shows no START white-screen trap and yields only the three applicable sliders plus the not-experienced caption;
7. confirmation contains no responses, scores, credentials, ICE data, or research content;
8. restart returns to overview and clears camera/feedback session state.

Expected: all eight checks pass before publishing the separate README-only public showcase repository.

## Agent Retry Rule

If any implementation or review subagent fails specifically with HTTP `429`, wait 5-10 seconds and automatically dispatch a fresh retry with the same bounded task, worktree, and acceptance criteria. Do not change application code in response to an agent-service rate limit.
