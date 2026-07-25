# Private Source and Public Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the completed intervention recorder in a neutral, private source repository and create a separate public README-only showcase with a password-protected synthetic Streamlit demonstration.

**Architecture:** The existing source history becomes a private repository named `physical-stimulation-session-recorder`; its release branch imports the completed questionnaire work, neutralizes visible product copy, and adds a standalone synthetic showcase app. A new repository named `physical-stimulation-session-recorder-showcase` is initialized from scratch and contains only a bilingual README plus one audited SVG preview; it never receives source history or study materials.

**Tech Stack:** Python 3.10, Streamlit 1.37, pytest, Streamlit `AppTest`, Git, GitHub CLI, Streamlit Community Cloud, Markdown, SVG.

---

## File Map

### Private source repository

- Modify: `app.py` - replace the two visible legacy product titles without changing storage or protocol identifiers.
- Modify: `tests/test_app_integration.py` - lock neutral user-visible product copy.
- Create: `showcase_workflow.py` - pure helpers for fail-closed password validation and deterministic synthetic demo transitions.
- Create: `showcase_app.py` - password-protected, session-only synthetic demonstration; no upload or real questionnaire imports.
- Create: `.streamlit/config.toml` - Alto-inspired Streamlit theme shared by the synthetic demo.
- Create: `tests/test_showcase_workflow.py` - unit tests for authentication and transition rules.
- Create: `tests/test_showcase_app.py` - `AppTest` coverage for fail-closed access and the complete synthetic flow.
- Create: `showcase_audit.py` - standard-library audit for the public repository allowlist, forbidden terms, unsafe URLs, and absolute paths.
- Create: `tests/test_showcase_audit.py` - audit acceptance and rejection cases.
- Preserve: `docs/superpowers/specs/2026-07-25-private-source-public-showcase-readme-design.md` - approved design.
- Preserve: `docs/superpowers/plans/2026-07-25-private-source-public-showcase.md` - this implementation plan.

### Public showcase repository

- Create: `README.md` - Chinese-first public overview with a short English summary and controlled demo URL.
- Create: `assets/session-recorder-preview.svg` - synthetic Alto-inspired interface preview with no study content.
- Create: `.gitignore` - OS/editor noise only; no source or build files are expected.

## Task 1: Enforce the Remote Privacy Gate and Neutral Repository Name

**Files:**
- No source file changes.
- Remote setting: `YaoZeLiu0417/taVNS_video_log` visibility and name.

- [ ] **Step 1: Capture the current remote state**

Run:

```powershell
gh repo view YaoZeLiu0417/taVNS_video_log --json nameWithOwner,isPrivate,defaultBranchRef,url
```

Expected: `isPrivate` is `false`, default branch is `main`, and the owner is `YaoZeLiu0417`.

- [ ] **Step 2: Change the source repository to private**

Run:

```powershell
gh repo edit YaoZeLiu0417/taVNS_video_log --visibility private --accept-visibility-change-consequences
```

Expected: exit code `0`.

- [ ] **Step 3: Verify privacy before any source push**

Run:

```powershell
gh repo view YaoZeLiu0417/taVNS_video_log --json isPrivate --jq .isPrivate
```

Expected: `true`. Stop the plan if this check fails.

- [ ] **Step 4: Rename the private repository**

Run:

```powershell
gh repo rename physical-stimulation-session-recorder --repo YaoZeLiu0417/taVNS_video_log --yes
```

Expected: exit code `0`.

- [ ] **Step 5: Update and verify the local remote**

Run:

```powershell
git remote set-url origin https://github.com/YaoZeLiu0417/physical-stimulation-session-recorder.git
git remote -v
gh repo view YaoZeLiu0417/physical-stimulation-session-recorder --json nameWithOwner,isPrivate,url
```

Expected: both Git fetch/push URLs use the neutral name and GitHub reports `isPrivate: true`.

- [ ] **Step 6: Verify anonymous users cannot read the source repository**

Run:

```powershell
try {
  Invoke-WebRequest -UseBasicParsing -Uri 'https://api.github.com/repos/YaoZeLiu0417/physical-stimulation-session-recorder' -TimeoutSec 15
  throw 'Private repository unexpectedly readable without GitHub CLI authentication'
} catch {
  if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
}
```

Expected: unauthenticated GitHub API request returns `404`.

## Task 2: Assemble the Private Release Branch from the Completed Feature Work

**Files:**
- Import all files from local commit `a420a5373ee125bedd6be01e11fb04b11cb2e60c`.
- Preserve both documentation commits from the local `design/private-source-public-showcase` branch.

- [ ] **Step 1: Fetch the completed local feature branch**

Run from `D:\proj_taVNS\taVNS_video_log`:

```powershell
git fetch 'D:\exp_recorder_streamlit' 'feat/tavns-nssi-questionnaire'
git rev-parse FETCH_HEAD
```

Expected: `FETCH_HEAD` is `a420a5373ee125bedd6be01e11fb04b11cb2e60c`.

- [ ] **Step 2: Create the release branch at the completed feature commit**

Run:

```powershell
git switch -c feat/private-source-public-showcase FETCH_HEAD
```

Expected: new branch is based on the fully tested questionnaire implementation.

- [ ] **Step 3: Cherry-pick the approved documentation commits**

Cherry-pick the two documentation commits that are newer than the original remote `main` tip:

```powershell
git cherry-pick 902677e..design/private-source-public-showcase
```

Expected: both documentation commits apply without conflict.

- [ ] **Step 4: Verify the assembled branch**

Run:

```powershell
git status --short --branch
git log -5 --oneline --decorate
```

Expected: clean `feat/private-source-public-showcase` branch containing the feature and both documentation commits.

## Task 3: Neutralize User-Visible Product Copy with TDD

**Files:**
- Modify: `tests/test_app_integration.py`
- Modify: `app.py:209`
- Modify: `app.py:223`

- [ ] **Step 1: Add a failing visible-brand test**

Append to `tests/test_app_integration.py`:

```python
def test_app_visible_titles_use_neutral_product_name():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    titles = [
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "title"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ]

    assert "🔒 Physical Stimulation Session Recorder 准入界面" in titles
    assert "📓 Physical Stimulation Session Recorder" in titles
    assert all("tavns" not in title.casefold() for title in titles)
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
pytest tests/test_app_integration.py::test_app_visible_titles_use_neutral_product_name -q
```

Expected: FAIL because the old visible titles are still present.

- [ ] **Step 3: Replace only the visible title literals**

In `app.py`, use:

```python
st.title("🔒 Physical Stimulation Session Recorder 准入界面")
```

and:

```python
st.title("📓 Physical Stimulation Session Recorder")
```

Do not rename internal questionnaire IDs, record fields, schemas, or storage paths.

- [ ] **Step 4: Run the focused test**

Run:

```powershell
pytest tests/test_app_integration.py::test_app_visible_titles_use_neutral_product_name -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit the neutral copy**

Run:

```powershell
git add app.py tests/test_app_integration.py
git commit -m "feat: neutralize visible product branding"
```

Expected: one focused commit.

## Task 4: Add a Fail-Closed Synthetic Showcase Workflow with TDD

**Files:**
- Create: `showcase_workflow.py`
- Create: `tests/test_showcase_workflow.py`

- [ ] **Step 1: Write failing workflow tests**

Create `tests/test_showcase_workflow.py`:

```python
import hashlib

import pytest

from showcase_workflow import (
    DemoTransitionError,
    advance_step,
    password_matches,
)


def test_password_matches_only_exact_sha256_digest():
    expected = hashlib.sha256(b"demonstration-passphrase").hexdigest()
    assert password_matches(expected, "demonstration-passphrase") is True
    assert password_matches(expected, "wrong-passphrase") is False
    assert password_matches("", "demonstration-passphrase") is False
    assert password_matches("not-a-digest", "demonstration-passphrase") is False


@pytest.mark.parametrize(
    ("step", "action", "expected"),
    (
        ("overview", "begin", "capture"),
        ("capture", "finish_capture", "reflection"),
        ("reflection", "save_reflection", "confirmation"),
        ("confirmation", "restart", "overview"),
    ),
)
def test_advance_step_allows_only_declared_transitions(step, action, expected):
    assert advance_step(step, action) == expected


def test_advance_step_rejects_skips_and_unknown_actions():
    with pytest.raises(DemoTransitionError):
        advance_step("overview", "save_reflection")
    with pytest.raises(DemoTransitionError):
        advance_step("unknown", "begin")
```

- [ ] **Step 2: Run the tests and verify import failure**

Run:

```powershell
pytest tests/test_showcase_workflow.py -q
```

Expected: collection ERROR because `showcase_workflow` does not exist.

- [ ] **Step 3: Implement the pure workflow**

Create `showcase_workflow.py`:

```python
from __future__ import annotations

import hashlib
import hmac


class DemoTransitionError(ValueError):
    pass


TRANSITIONS = {
    ("overview", "begin"): "capture",
    ("capture", "finish_capture"): "reflection",
    ("reflection", "save_reflection"): "confirmation",
    ("confirmation", "restart"): "overview",
}


def password_matches(expected_digest: str, candidate: str) -> bool:
    normalized = expected_digest.strip().casefold()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        return False
    candidate_digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate_digest, normalized)


def advance_step(current_step: str, action: str) -> str:
    try:
        return TRANSITIONS[(current_step, action)]
    except KeyError as exc:
        raise DemoTransitionError(
            f"transition not allowed: {current_step!r} + {action!r}"
        ) from exc
```

- [ ] **Step 4: Run the workflow tests**

Run:

```powershell
pytest tests/test_showcase_workflow.py -q
```

Expected: `6 passed`.

- [ ] **Step 5: Commit the workflow unit**

Run:

```powershell
git add showcase_workflow.py tests/test_showcase_workflow.py
git commit -m "feat: add synthetic showcase workflow"
```

## Task 5: Build the Password-Protected Alto-Inspired Showcase App with TDD

**Files:**
- Create: `showcase_app.py`
- Create: `.streamlit/config.toml`
- Create: `tests/test_showcase_app.py`

- [ ] **Step 1: Write failing app tests**

Create `tests/test_showcase_app.py`:

```python
import hashlib
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).parents[1] / "showcase_app.py"
PASSWORD = "demonstration-passphrase"


def _app_with_password():
    app = AppTest.from_file(str(APP), default_timeout=10)
    app.secrets["SHOWCASE_PASSWORD_SHA256"] = hashlib.sha256(
        PASSWORD.encode("utf-8")
    ).hexdigest()
    return app


def _element_by_key(elements, key):
    matches = [element for element in elements if element.key == key]
    assert len(matches) == 1
    return matches[0]


def test_showcase_fails_closed_without_configured_password():
    app = AppTest.from_file(str(APP), default_timeout=10).run()
    assert not app.exception
    assert any("演示暂未开放" in item.value for item in app.error)


def test_showcase_rejects_wrong_password_and_accepts_correct_password():
    app = _app_with_password().run()
    app.text_input[0].set_value("wrong-passphrase")
    app.button[0].click().run()
    assert any("访问密码错误" in item.value for item in app.error)

    app.text_input[0].set_value(PASSWORD)
    app.button[0].click().run()
    assert not app.exception
    assert any("Physical Stimulation Session Recorder" in item.value for item in app.title)


def test_showcase_completes_synthetic_flow_without_files_or_network(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = _app_with_password().run()
    app.text_input[0].set_value(PASSWORD)
    app.button[0].click().run()
    _element_by_key(app.button, "begin_demo").click().run()
    _element_by_key(app.button, "finish_capture").click().run()
    _element_by_key(app.slider, "session_clarity").set_value(3)
    _element_by_key(app.slider, "interaction_comfort").set_value(4)
    _element_by_key(app.button, "save_reflection").click().run()

    assert not app.exception
    assert any("演示流程已完成" in item.value for item in app.success)
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run the app tests and verify failure**

Run:

```powershell
pytest tests/test_showcase_app.py -q
```

Expected: FAIL because `showcase_app.py` does not exist.

- [ ] **Step 3: Add the Streamlit theme**

Create `.streamlit/config.toml`:

```toml
[theme]
primaryColor = "#DD1D86"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F4F4F4"
textColor = "#000035"
font = "sans serif"
```

- [ ] **Step 4: Implement the synthetic app**

Create `showcase_app.py` with these exact behaviors:

```python
from __future__ import annotations

import os
from typing import Any

import streamlit as st

from showcase_workflow import advance_step, password_matches


PRODUCT_NAME = "Physical Stimulation Session Recorder"

st.set_page_config(page_title=PRODUCT_NAME, page_icon="●", layout="centered")
st.markdown(
    """
    <style>
    :root { --navy:#000035; --violet:#2D2674; --pink:#DD1D86; --blue:#33B0E4; --peach:#FFBC7D; }
    .stApp { color:var(--navy); }
    [data-testid="stHeader"] { background:#FFFFFF; }
    [data-testid="stSidebar"] { background:var(--violet); }
    [data-testid="stSidebar"] * { color:#FFFFFF; }
    .demo-kicker { color:var(--pink); font-size:.78rem; font-weight:800; margin-bottom:.4rem; }
    .demo-note { border-left:4px solid var(--blue); background:#F4F4F4; padding:.85rem 1rem; }
    .privacy-note { border-left:4px solid var(--pink); background:#FFF4FA; padding:.85rem 1rem; }
    div.stButton > button { border-radius:4px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _secret(name: str, default: Any = "") -> Any:
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


def _require_access() -> None:
    expected_digest = str(_secret("SHOWCASE_PASSWORD_SHA256", ""))
    if not expected_digest:
        st.error("演示暂未开放，请联系项目团队。")
        st.stop()
    if st.session_state.get("showcase_authenticated", False):
        return
    st.title(PRODUCT_NAME)
    st.caption("受控合成演示 / Controlled synthetic demonstration")
    candidate = st.text_input("访问密码", type="password")
    if st.button("进入演示", type="primary"):
        if password_matches(expected_digest, candidate):
            st.session_state["showcase_authenticated"] = True
            st.rerun()
        st.error("访问密码错误。")
    st.stop()


def _go(action: str) -> None:
    st.session_state["showcase_step"] = advance_step(
        st.session_state["showcase_step"], action
    )
    st.rerun()


_require_access()
step = st.session_state.setdefault("showcase_step", "overview")

st.sidebar.caption("SESSION PROGRESS")
for label, key in (
    ("1  安全进入", "overview"),
    ("2  会话记录", "capture"),
    ("3  引导反馈", "reflection"),
    ("4  完成确认", "confirmation"),
):
    st.sidebar.markdown(f"**{label}**" if step == key else label)

st.markdown('<p class="demo-kicker">CONTROLLED DEMONSTRATION</p>', unsafe_allow_html=True)
st.title(PRODUCT_NAME)
st.caption("物理刺激干预记录工具 · 本页面只使用合成内容")

if step == "overview":
    st.subheader("准备开始本次演示")
    st.markdown(
        '<div class="demo-note">演示展示安全进入、会话记录、引导反馈和完成确认。不会保存文件，也不会连接外部存储。</div>',
        unsafe_allow_html=True,
    )
    if st.button("开始演示", type="primary", key="begin_demo"):
        _go("begin")
elif step == "capture":
    st.subheader("会话记录")
    st.info("合成记录正在进行。本步骤仅模拟交互，不会调用摄像头或写入磁盘。")
    st.progress(0.72)
    if st.button("完成模拟记录", type="primary", key="finish_capture"):
        _go("finish_capture")
elif step == "reflection":
    st.subheader("会话反馈")
    st.caption("以下为通用合成问题，仅用于展示滑动评分交互。")
    st.slider("今天的流程有多清晰？", 0, 4, 2, key="session_clarity")
    st.slider("你对本次交互有多舒适？", 0, 4, 2, key="interaction_comfort")
    if st.button("保存合成反馈", type="primary", key="save_reflection"):
        _go("save_reflection")
else:
    st.success("演示流程已完成。")
    st.markdown(
        '<div class="privacy-note"><strong>隐私边界</strong><br>本演示不包含研究名称、干预参数、测量内容、评分规则或真实参与者数据。</div>',
        unsafe_allow_html=True,
    )
    if st.button("重新体验", key="restart_demo"):
        st.session_state.pop("session_clarity", None)
        st.session_state.pop("interaction_comfort", None)
        _go("restart")
```

- [ ] **Step 5: Run showcase tests**

Run:

```powershell
pytest tests/test_showcase_workflow.py tests/test_showcase_app.py -q
```

Expected: all showcase tests pass and the completion test creates no files.

- [ ] **Step 6: Commit the showcase app**

Run:

```powershell
git add showcase_app.py showcase_workflow.py .streamlit/config.toml tests/test_showcase_app.py tests/test_showcase_workflow.py
git commit -m "feat: add controlled synthetic showcase"
```

## Task 6: Add a Public-Surface Privacy Auditor with TDD

**Files:**
- Create: `showcase_audit.py`
- Create: `tests/test_showcase_audit.py`

- [ ] **Step 1: Write failing audit tests**

Create `tests/test_showcase_audit.py`:

```python
from pathlib import Path

from showcase_audit import audit_showcase


SAFE_README = """# Physical Stimulation Session Recorder
[Launch controlled demo](https://physical-stimulation-session-recorder.streamlit.app)
Synthetic content only.
"""


def _safe_tree(root: Path) -> None:
    (root / "assets").mkdir()
    (root / ".gitignore").write_text(".DS_Store\n", encoding="utf-8")
    (root / "README.md").write_text(SAFE_README, encoding="utf-8")
    (root / "assets" / "session-recorder-preview.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>Synthetic session</text></svg>',
        encoding="utf-8",
    )


def test_audit_accepts_exact_public_surface(tmp_path):
    _safe_tree(tmp_path)
    assert audit_showcase(tmp_path) == []


def test_audit_rejects_extra_files_sensitive_terms_and_paths(tmp_path):
    _safe_tree(tmp_path)
    (tmp_path / "app.py").write_text("secret source", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        SAFE_README
        + "\nNSSI\nD:\\private\\recordings\n?sid=sub-001&sig=abc"
        + "\nhttps://example.com/production",
        encoding="utf-8",
    )
    findings = audit_showcase(tmp_path)
    assert any("unexpected public file: app.py" in item for item in findings)
    assert any("forbidden term" in item for item in findings)
    assert any("absolute path" in item for item in findings)
    assert any("credential-like URL parameter" in item for item in findings)
    assert any("unapproved URL" in item for item in findings)
```

- [ ] **Step 2: Run the tests and verify import failure**

Run:

```powershell
pytest tests/test_showcase_audit.py -q
```

Expected: collection ERROR because `showcase_audit` does not exist.

- [ ] **Step 3: Implement the auditor**

Create `showcase_audit.py`:

```python
from __future__ import annotations

import re
from pathlib import Path


ALLOWED_FILES = {
    ".gitignore",
    "README.md",
    "assets/session-recorder-preview.svg",
}
ALLOWED_URLS = {
    "https://physical-stimulation-session-recorder.streamlit.app",
    "http://www.w3.org/2000/svg",
}
TEXT_SUFFIXES = {"", ".md", ".svg"}
FORBIDDEN_TERMS = (
    "tavns",
    "nssi",
    "sicq",
    "dshi",
    "fasm",
    "自伤",
    "自杀",
    "量表",
    "问卷",
    "评分规则",
)
ABSOLUTE_PATH = re.compile(r"(?i)(?:[a-z]:\\|/users/|/home/)")
CREDENTIAL_QUERY = re.compile(r"(?i)[?&](?:sid|sig|exp|token|secret|password)=")
HTTP_URL = re.compile(r"https?://[^\s<>'\"`]+", re.IGNORECASE)


def audit_showcase(root: Path) -> list[str]:
    root = root.resolve()
    findings: list[str] = []
    files = sorted(path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts)
    for path in files:
        relative = path.relative_to(root).as_posix()
        if relative not in ALLOWED_FILES:
            findings.append(f"unexpected public file: {relative}")
        if path.suffix.casefold() not in TEXT_SUFFIXES and path.name != ".gitignore":
            continue
        text = path.read_text(encoding="utf-8")
        folded = text.casefold()
        for term in FORBIDDEN_TERMS:
            if term.casefold() in folded:
                findings.append(f"forbidden term in {relative}: {term}")
        if ABSOLUTE_PATH.search(text):
            findings.append(f"absolute path in {relative}")
        if CREDENTIAL_QUERY.search(text):
            findings.append(f"credential-like URL parameter in {relative}")
        for match in HTTP_URL.finditer(text):
            url = match.group(0).rstrip(".,;:!?)]}")
            if url not in ALLOWED_URLS:
                findings.append(f"unapproved URL in {relative}: {url}")
    missing = ALLOWED_FILES - {path.relative_to(root).as_posix() for path in files}
    findings.extend(f"missing public file: {path}" for path in sorted(missing))
    return findings
```

- [ ] **Step 4: Run the audit tests**

Run:

```powershell
pytest tests/test_showcase_audit.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit the auditor**

Run:

```powershell
git add showcase_audit.py tests/test_showcase_audit.py
git commit -m "test: audit public showcase privacy"
```

## Task 7: Run the Private Release Gate and Merge Through a Private PR

**Files:**
- Verify all private source files.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
pytest tests/test_app_integration.py::test_app_visible_titles_use_neutral_product_name tests/test_showcase_workflow.py tests/test_showcase_app.py tests/test_showcase_audit.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the full test suite**

Run:

```powershell
pytest -q
```

Expected: at least `314 passed, 3 skipped`; the three permitted skips are Windows symbolic-link permission cases.

- [ ] **Step 3: Run compile and patch checks**

Run:

```powershell
python -m compileall -q app.py app_workflow.py link_auth.py questionnaire_scoring.py questionnaire_specs.py questionnaire_ui.py record_store.py showcase_app.py showcase_audit.py showcase_workflow.py upload_workflow.py tests
git diff --check
git status --short --branch
```

Expected: compile and diff checks succeed; branch is clean.

- [ ] **Step 4: Push only after confirming the repository is private**

Run:

```powershell
gh repo view YaoZeLiu0417/physical-stimulation-session-recorder --json isPrivate --jq .isPrivate
git push -u origin feat/private-source-public-showcase
```

Expected: first command prints `true`; branch push succeeds.

- [ ] **Step 5: Create and merge the private PR**

Run:

```powershell
gh pr create --repo YaoZeLiu0417/physical-stimulation-session-recorder --base main --head feat/private-source-public-showcase --title "Add neutral recorder release and controlled showcase" --body "Integrates the tested questionnaire workflow, neutralizes visible branding, and adds a password-protected synthetic demonstration. Full tests and public-surface privacy audit pass."
gh pr checks --repo YaoZeLiu0417/physical-stimulation-session-recorder --watch
gh pr merge --repo YaoZeLiu0417/physical-stimulation-session-recorder --merge --delete-branch
```

Expected: PR checks pass and the PR is merged into private `main`. If no remote checks are configured, record that fact and rely on the locally verified full suite before merging.

## Task 8: Deploy the Controlled Streamlit Demonstration

**Files:**
- Deployment entry point: `showcase_app.py` from private `main`.
- Streamlit secret: `SHOWCASE_PASSWORD_SHA256` only.

- [ ] **Step 1: Generate a one-time high-entropy demonstration password and digest**

Run in one PowerShell session and keep both values out of Git and shell history files:

```powershell
$bytes = New-Object byte[] 18
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$demoPassword = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
$sha = [Security.Cryptography.SHA256]::Create()
$digest = [Convert]::ToHexString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($demoPassword))).ToLowerInvariant()
[PSCustomObject]@{Password=$demoPassword;Digest=$digest}
```

Expected: a URL-safe 24-character password and a 64-character lowercase digest. Share the password with the user once; never commit either value.

- [ ] **Step 2: Create the Streamlit Community Cloud app**

Open `https://share.streamlit.io`, authenticate as the repository owner, and create an app using these exact settings:

```text
Repository: YaoZeLiu0417/physical-stimulation-session-recorder
Branch: main
Main file path: showcase_app.py
App URL: physical-stimulation-session-recorder
```

Expected URL: `https://physical-stimulation-session-recorder.streamlit.app`.

- [ ] **Step 3: Configure the fail-closed secret**

In the same PowerShell session as Step 1, render the exact TOML line:

```powershell
$secretToml = 'SHOWCASE_PASSWORD_SHA256 = "' + $digest + '"'
$secretToml
```

Copy the rendered line into the app's Streamlit Secrets editor, save it, and reboot the app. Do not store the line in a repository file.

- [ ] **Step 4: Verify access behavior**

Verify in the browser:

```text
No password configured -> "演示暂未开放"
Wrong password -> "访问密码错误"
Generated password -> overview opens
Overview -> capture -> reflection -> confirmation -> restart completes
```

Expected: no camera permission, file download, external upload, participant identifier, or study-specific content appears.

## Task 9: Build and Audit the Public Showcase Locally

**Files:**
- Create: `D:\proj_taVNS\physical-stimulation-session-recorder-showcase\README.md`
- Create: `D:\proj_taVNS\physical-stimulation-session-recorder-showcase\assets\session-recorder-preview.svg`
- Create: `D:\proj_taVNS\physical-stimulation-session-recorder-showcase\.gitignore`

- [ ] **Step 1: Initialize an independent local repository**

Run:

```powershell
New-Item -ItemType Directory -Path 'D:\proj_taVNS\physical-stimulation-session-recorder-showcase'
git -C 'D:\proj_taVNS\physical-stimulation-session-recorder-showcase' init -b main
New-Item -ItemType Directory -Path 'D:\proj_taVNS\physical-stimulation-session-recorder-showcase\assets'
```

Expected: a new Git repository with no source-repository remote or history.

- [ ] **Step 2: Create the public README**

Create `README.md` with this approved content:

```markdown
# Physical Stimulation Session Recorder

> 面向结构化干预流程的安全会话记录工具  
> A privacy-conscious session recorder for structured intervention workflows.

[**打开受控演示 / Launch controlled demo**](https://physical-stimulation-session-recorder.streamlit.app)

访问方式通过项目协作渠道单独提供。演示不保存文件，也不连接外部存储。

![Synthetic preview of the session recorder](assets/session-recorder-preview.svg)

## 工具概览 / Overview

该工具将一次会话拆分为清晰、低认知负担的步骤，帮助使用者依次完成安全进入、会话记录、引导反馈与完成确认。

The experience guides a user through secure access, session capture, structured reflection, and confirmation in a calm step-by-step flow.

## 核心体验 / Core experience

| 安全进入 | 分步记录 | 可靠完成 |
| --- | --- | --- |
| 受控入口与明确的会话边界 | 一次聚焦一个任务，支持清晰反馈 | 完成状态明确，不向使用者展示内部运维信息 |

## 演示流程 / Demonstration flow

1. **安全进入**：通过独立提供的访问方式进入合成演示。
2. **会话记录**：体验不调用摄像头、不写入磁盘的模拟记录状态。
3. **引导反馈**：使用通用合成内容体验滑动评分交互。
4. **完成确认**：查看明确的完成状态并可重新开始。

## 公开边界 / Public boundary

本仓库仅用于工具界面展示，只包含本说明和合成视觉资源。公开内容不包含未公开的项目设计、具体测量内容、内部实现、真实参与者信息或访问凭据。

This repository is a presentation surface only. It contains no application source, private implementation details, participant information, or access credentials.

## 视觉方向 / Visual direction

界面采用白色主画布、深靛蓝文字、紫色结构和洋红行动按钮，并以天蓝和浅橙提供少量状态强调。所有展示资源均为原创合成内容。

## Access

演示访问说明通过现有协作渠道提供。公开 Issue 不用于申请访问或讨论内部项目内容。
```

- [ ] **Step 3: Create the synthetic SVG preview**

Create `assets/session-recorder-preview.svg` as a 1200 by 675 vector mockup using only these visible strings:

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675" role="img" aria-labelledby="title desc">
  <title id="title">Synthetic session recorder preview</title>
  <desc id="desc">A neutral four-step session recorder interface made from synthetic content.</desc>
  <rect width="1200" height="675" fill="#F4F4F4"/>
  <rect x="55" y="45" width="1090" height="585" rx="8" fill="#FFFFFF" stroke="#DEDEE7"/>
  <rect x="55" y="45" width="1090" height="48" rx="8" fill="#000035"/>
  <rect x="55" y="85" width="1090" height="8" fill="#000035"/>
  <text x="85" y="76" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="17" font-weight="700">SESSION RECORDER</text>
  <text x="1008" y="76" fill="#FFBC7D" font-family="Arial, sans-serif" font-size="13" font-weight="700">SECURE SESSION</text>
  <rect x="55" y="93" width="310" height="537" fill="#2D2674"/>
  <text x="86" y="137" fill="#D9D6FF" font-family="Arial, sans-serif" font-size="13">SESSION PROGRESS</text>
  <text x="86" y="178" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="21" font-weight="700">Complete today’s guided record</text>
  <rect x="86" y="205" width="245" height="7" rx="3" fill="#5C5595"/>
  <rect x="86" y="205" width="158" height="7" rx="3" fill="#33B0E4"/>
  <circle cx="101" cy="266" r="14" fill="#7771A8"/><text x="96" y="271" fill="#FFFFFF" font-family="Arial" font-size="13">✓</text>
  <text x="130" y="272" fill="#FFFFFF" font-family="Arial" font-size="16">Secure access</text>
  <circle cx="101" cy="320" r="14" fill="#7771A8"/><text x="96" y="325" fill="#FFFFFF" font-family="Arial" font-size="13">✓</text>
  <text x="130" y="326" fill="#FFFFFF" font-family="Arial" font-size="16">Session capture</text>
  <circle cx="101" cy="374" r="14" fill="#DD1D86"/><text x="97" y="379" fill="#FFFFFF" font-family="Arial" font-size="13">3</text>
  <text x="130" y="380" fill="#FFFFFF" font-family="Arial" font-size="16" font-weight="700">Guided reflection</text>
  <circle cx="101" cy="428" r="14" fill="#7771A8"/><text x="97" y="433" fill="#FFFFFF" font-family="Arial" font-size="13">4</text>
  <text x="130" y="434" fill="#D9D6FF" font-family="Arial" font-size="16">Confirmation</text>
  <text x="415" y="145" fill="#DD1D86" font-family="Arial, sans-serif" font-size="13" font-weight="700">SESSION REFLECTION</text>
  <text x="415" y="190" fill="#000035" font-family="Arial, sans-serif" font-size="30" font-weight="700">How was today’s session?</text>
  <text x="415" y="222" fill="#646476" font-family="Arial, sans-serif" font-size="16">This synthetic item demonstrates the interaction pattern only.</text>
  <g font-family="Arial, sans-serif" font-size="18" font-weight="700" text-anchor="middle">
    <rect x="415" y="285" width="105" height="72" rx="5" fill="#FFFFFF" stroke="#DEDEE7"/><text x="468" y="329" fill="#2D2674">0</text>
    <rect x="538" y="285" width="105" height="72" rx="5" fill="#FFFFFF" stroke="#DEDEE7"/><text x="591" y="329" fill="#2D2674">1</text>
    <rect x="661" y="285" width="105" height="72" rx="5" fill="#FCE9F4" stroke="#DD1D86"/><text x="714" y="329" fill="#DD1D86">2</text>
    <rect x="784" y="285" width="105" height="72" rx="5" fill="#FFFFFF" stroke="#DEDEE7"/><text x="837" y="329" fill="#2D2674">3</text>
    <rect x="907" y="285" width="105" height="72" rx="5" fill="#FFFFFF" stroke="#DEDEE7"/><text x="960" y="329" fill="#2D2674">4</text>
  </g>
  <text x="415" y="389" fill="#7A7A89" font-family="Arial, sans-serif" font-size="13">Not at all</text>
  <text x="946" y="389" fill="#7A7A89" font-family="Arial, sans-serif" font-size="13">Very much</text>
  <rect x="909" y="503" width="160" height="48" rx="5" fill="#DD1D86"/>
  <text x="956" y="534" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="16" font-weight="700">Continue</text>
  <text x="1034" y="534" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="20">→</text>
</svg>
```

- [ ] **Step 4: Create the public `.gitignore`**

Create `.gitignore`:

```gitignore
.DS_Store
Thumbs.db
.vscode/
.idea/
```

- [ ] **Step 5: Run the private auditor against the independent repository**

Run from the private source repository:

```powershell
python -c "from pathlib import Path; from showcase_audit import audit_showcase; findings=audit_showcase(Path(r'D:\proj_taVNS\physical-stimulation-session-recorder-showcase')); print('\n'.join(findings)); raise SystemExit(bool(findings))"
```

Expected: no output and exit code `0`.

- [ ] **Step 6: Render-check the SVG and README**

Open the local README and SVG in the in-app browser. Verify desktop and mobile widths, text fit, Alto-inspired colors, no overlaps, and no study-specific content. The visible SVG must be nonblank and match the accepted product-first layout.

- [ ] **Step 7: Commit the public surface locally**

Run:

```powershell
git -C 'D:\proj_taVNS\physical-stimulation-session-recorder-showcase' add README.md assets/session-recorder-preview.svg .gitignore
git -C 'D:\proj_taVNS\physical-stimulation-session-recorder-showcase' commit -m "docs: add privacy-safe recorder showcase"
git -C 'D:\proj_taVNS\physical-stimulation-session-recorder-showcase' status --short --branch
```

Expected: one root commit and a clean `main` branch.

## Task 10: Create and Verify the Public Showcase Repository

**Files:**
- Publish only the independent showcase commit from Task 9.

- [ ] **Step 1: Re-run the privacy audit immediately before publication**

Run:

```powershell
python -c "from pathlib import Path; from showcase_audit import audit_showcase; findings=audit_showcase(Path(r'D:\proj_taVNS\physical-stimulation-session-recorder-showcase')); print('\n'.join(findings)); raise SystemExit(bool(findings))"
```

Expected: no output and exit code `0`.

- [ ] **Step 2: Create and push the public repository from the independent local root**

Run:

```powershell
gh repo create YaoZeLiu0417/physical-stimulation-session-recorder-showcase --public --source 'D:\proj_taVNS\physical-stimulation-session-recorder-showcase' --remote origin --push --description "Privacy-conscious demonstration of a structured intervention session recorder" --disable-issues --disable-wiki
```

Expected: repository is created and only `README.md`, `.gitignore`, and `assets/session-recorder-preview.svg` are pushed.

- [ ] **Step 3: Set and verify the neutral demo homepage**

Run:

```powershell
gh repo edit YaoZeLiu0417/physical-stimulation-session-recorder-showcase --homepage 'https://physical-stimulation-session-recorder.streamlit.app'
gh repo view YaoZeLiu0417/physical-stimulation-session-recorder-showcase --json nameWithOwner,isPrivate,url,homepageUrl
```

Expected: `isPrivate` is `false`; repository and homepage URLs contain only neutral naming.

- [ ] **Step 4: Verify the anonymous public file surface**

Run without GitHub CLI authentication headers:

```powershell
$tree = Invoke-RestMethod -Uri 'https://api.github.com/repos/YaoZeLiu0417/physical-stimulation-session-recorder-showcase/git/trees/main?recursive=1' -TimeoutSec 15
$tree.tree.path | Sort-Object
```

Expected paths:

```text
.gitignore
README.md
assets
assets/session-recorder-preview.svg
```

- [ ] **Step 5: Verify final links and disclosure boundary**

Open:

```text
https://github.com/YaoZeLiu0417/physical-stimulation-session-recorder-showcase
https://physical-stimulation-session-recorder.streamlit.app
```

Expected: README renders correctly, preview is visible, the demo asks for a password, and neither public surface shows source, study details, participant data, local paths, credentials, or the legacy product name.

- [ ] **Step 6: Record final release evidence**

Capture in the final handoff:

```text
Private source repository URL and visibility
Private PR URL and merge commit
Full pytest result
Public showcase repository URL
Controlled Streamlit URL
Anonymous public tree contents
Any deployment step that required user authorization
```
