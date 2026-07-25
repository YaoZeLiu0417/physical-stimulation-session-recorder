# Streamlit Deployment Dependency Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the private, password-protected Streamlit showcase by replacing the source-build WebRTC dependency set with the approved wheel-backed versions and verifying the deployed four-step synthetic flow.

**Architecture:** Keep the application and questionnaire code unchanged. Add one standard-library requirements contract test, replace only the three WebRTC pins in `requirements.txt`, verify Linux/Python 3.10 binary resolution plus Python 3.13 WebRTC artifacts, then release through a private pull request and validate Streamlit health and access behavior.

**Tech Stack:** Python 3.10/3.13 compatibility checks, pytest 8, Streamlit 1.37.1, streamlit-webrtc 0.63.4, aiortc 1.15.0, PyAV 17.0.0, pip, Git, GitHub CLI, Streamlit Community Cloud, PowerShell.

---

## File Map

- Create: `tests/test_requirements_contract.py` - locks the complete production requirement specification and prevents regression to source-only WebRTC pins.
- Modify: `requirements.txt` - updates only `streamlit-webrtc`, `aiortc`, and `av`, plus the two now-stale inline compatibility comments.
- Preserve: `showcase_app.py`, `showcase_workflow.py`, all questionnaire modules, `.streamlit/config.toml`, and `packages.txt`.
- Verify: `tests/test_showcase_app.py`, `tests/test_showcase_workflow.py`, and the complete `tests/` suite.

Run all commands from:

```powershell
Set-Location 'D:\proj_taVNS\.worktrees\physical-stimulation-session-recorder\private-source-public-showcase'
```

### Task 1: Lock And Update The WebRTC Dependency Contract

**Files:**
- Create: `tests/test_requirements_contract.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write the failing dependency contract test**

Create `tests/test_requirements_contract.py` with this exact content:

```python
from pathlib import Path


REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"


def _requirement_specs() -> tuple[str, ...]:
    specs = []
    for raw_line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        spec = raw_line.split("#", 1)[0].strip()
        if spec:
            specs.append(spec)
    return tuple(specs)


def test_production_requirements_use_approved_webrtc_stack() -> None:
    assert _requirement_specs() == (
        "streamlit==1.37.1",
        "streamlit-webrtc==0.63.4",
        "aiortc==1.15.0",
        "av==17.0.0",
        "numpy>=1.24,<2.0",
        "requests>=2.31,<3",
        "protobuf<5",
        "python-dotenv>=1.0,<2",
    )
```

- [ ] **Step 2: Run the contract test and verify the intended failure**

Run:

```powershell
pytest tests/test_requirements_contract.py -q
```

Expected: `1 failed`; the assertion diff shows `streamlit-webrtc==0.47.1`, `aiortc==1.6.0`, and `av==11.0.0` instead of the approved versions.

- [ ] **Step 3: Apply the minimal production dependency update**

Keep every unrelated requirement unchanged and make the WebRTC section read exactly:

```text
# Web UI
streamlit==1.37.1
streamlit-webrtc==0.63.4

# WebRTC / 视频
aiortc==1.15.0        # requires av >= 14, < 18
av==17.0.0            # provides prebuilt Linux wheels
```

Preserve the existing four core dependency specifications below this section:

```text
numpy>=1.24,<2.0
requests>=2.31,<3
protobuf<5
python-dotenv>=1.0,<2
```

- [ ] **Step 4: Run the contract test and verify it passes**

Run:

```powershell
pytest tests/test_requirements_contract.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Confirm the diff is limited to the contract and approved dependency set**

Run:

```powershell
git diff -- requirements.txt tests/test_requirements_contract.py
git diff --check
```

Expected: one new test file, only the three approved pins and their stale inline comments changed, and no whitespace errors.

- [ ] **Step 6: Commit the tested dependency change**

Run:

```powershell
git add requirements.txt tests/test_requirements_contract.py
git commit -m "fix: use wheel-backed WebRTC dependencies"
```

Expected: one commit containing exactly the two files above.

### Task 2: Prove Binary Resolution And Run Local Regression Gates

**Files:**
- Verify: `requirements.txt`
- Verify: `tests/test_requirements_contract.py`
- Verify: `tests/test_showcase_app.py`
- Verify: `tests/test_showcase_workflow.py`
- Verify: all Python source and tests

- [ ] **Step 1: Download the complete Linux/Python 3.10 dependency graph using wheels only**

Run this in one PowerShell session:

```powershell
$wheelRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pssr-wheels-" + [guid]::NewGuid().ToString("N"))
$py310Wheelhouse = Join-Path $wheelRoot 'linux-py310'
$py313Wheelhouse = Join-Path $wheelRoot 'linux-py313-webrtc'
New-Item -ItemType Directory -Path $py310Wheelhouse, $py313Wheelhouse | Out-Null

python -m pip download `
  --disable-pip-version-check `
  --only-binary=:all: `
  --platform manylinux_2_28_x86_64 `
  --platform manylinux2014_x86_64 `
  --platform manylinux_2_17_x86_64 `
  --implementation cp `
  --python-version 310 `
  --abi cp310 `
  --abi abi3 `
  --dest $py310Wheelhouse `
  --requirement requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Linux/Python 3.10 binary resolution failed' }
```

Expected: pip reports `Successfully downloaded`; no `.tar.gz`, `.zip`, or other source archive exists in `$py310Wheelhouse`.

- [ ] **Step 2: Confirm the three approved WebRTC releases also publish Python 3.13-compatible binary artifacts**

Continue in the same PowerShell session:

```powershell
python -m pip download `
  --disable-pip-version-check `
  --only-binary=:all: `
  --no-deps `
  --platform manylinux_2_28_x86_64 `
  --implementation cp `
  --python-version 313 `
  --abi cp313 `
  --abi abi3 `
  --dest $py313Wheelhouse `
  streamlit-webrtc==0.63.4 aiortc==1.15.0 av==17.0.0
if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 WebRTC artifact check failed' }

$sourceArchives = Get-ChildItem -LiteralPath $wheelRoot -Recurse -File |
  Where-Object { $_.Name -match '\.(?:tar\.gz|tar\.bz2|zip)$' }
if ($sourceArchives) { throw "Source archives found: $($sourceArchives.Name -join ', ')" }
```

Expected: the second command downloads three wheel files and `$sourceArchives` is empty.

- [ ] **Step 3: Remove only the uniquely created temporary wheel directory**

Continue in the same PowerShell session:

```powershell
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$resolvedWheelRoot = [System.IO.Path]::GetFullPath($wheelRoot)
if (-not $resolvedWheelRoot.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove a non-temporary path: $resolvedWheelRoot"
}
Remove-Item -LiteralPath $resolvedWheelRoot -Recurse -Force
```

Expected: only the generated `pssr-wheels-*` temporary directory is removed.

- [ ] **Step 4: Run the focused deployment and synthetic-flow regression tests**

Run:

```powershell
pytest tests/test_requirements_contract.py tests/test_showcase_workflow.py tests/test_showcase_app.py -q
```

Expected: all selected tests pass with no exceptions or warnings that indicate a broken Streamlit app.

- [ ] **Step 5: Run the complete private test suite**

Run:

```powershell
pytest -q
```

Expected: `403 passed, 3 skipped` with zero failures.

- [ ] **Step 6: Compile source and run final patch checks**

Run:

```powershell
python -m compileall -q app.py app_workflow.py link_auth.py questionnaire_scoring.py questionnaire_specs.py questionnaire_ui.py record_store.py showcase_app.py showcase_audit.py showcase_workflow.py upload_workflow.py tests
git diff --check origin/main...HEAD
git status --short --branch
```

Expected: compilation exits `0`, the patch check is silent, and the branch is clean and ahead of `origin/main` only by the design, plan, test, and dependency commits.

### Task 3: Release Through The Private Repository

**Files:**
- Release: the verified commits on `fix/streamlit-deployment-dependencies`
- Preserve: private GitHub repository visibility

- [ ] **Step 1: Fail closed unless the target repository is private**

Run:

```powershell
$repoState = gh repo view YaoZeLiu0417/physical-stimulation-session-recorder --json nameWithOwner,visibility,defaultBranchRef | ConvertFrom-Json
if ($repoState.visibility -ne 'PRIVATE') { throw 'Refusing to push because the source repository is not private' }
if ($repoState.defaultBranchRef.name -ne 'main') { throw 'Unexpected default branch' }
$repoState
```

Expected: `visibility` is `PRIVATE` and the default branch is `main`.

- [ ] **Step 2: Push only the recovery branch**

Run:

```powershell
git push --set-upstream origin fix/streamlit-deployment-dependencies
```

Expected: the branch is created on the private repository; `main` is not changed directly.

- [ ] **Step 3: Open the private pull request**

Run:

```powershell
$prUrl = gh pr create `
  --repo YaoZeLiu0417/physical-stimulation-session-recorder `
  --base main `
  --head fix/streamlit-deployment-dependencies `
  --title 'Fix Streamlit deployment dependencies' `
  --body 'Replaces the source-build WebRTC stack with the approved wheel-backed versions. Adds an exact requirements contract and passes binary resolution, showcase regression, full-suite, compile, and privacy gates.'
$prNumber = [int](Split-Path $prUrl -Leaf)
$prUrl
```

Expected: `gh` returns a pull-request URL for the private repository and `$prNumber` is an integer.

- [ ] **Step 4: Review checks and merge only the verified pull request**

Run:

```powershell
gh pr diff $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder --name-only
gh pr checks $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder
gh pr view $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder --json mergeStateStatus,statusCheckRollup
```

Expected: only the design/plan documents, `requirements.txt`, and `tests/test_requirements_contract.py` appear. Configured checks pass; an empty check list is acceptable because the complete local suite already passed. Do not merge if any configured check fails or the diff contains another file.

Then run:

```powershell
gh pr merge $prNumber --repo YaoZeLiu0417/physical-stimulation-session-recorder --merge --delete-branch
```

Expected: the PR is merged into private `main` and the remote feature branch is deleted.

- [ ] **Step 5: Reconfirm private visibility and anonymous source denial**

Run:

```powershell
$visibility = gh repo view YaoZeLiu0417/physical-stimulation-session-recorder --json visibility --jq '.visibility'
if ($visibility -ne 'PRIVATE') { throw 'Source repository visibility changed' }

$anonymousUrls = @(
  'https://api.github.com/repos/YaoZeLiu0417/physical-stimulation-session-recorder',
  'https://raw.githubusercontent.com/YaoZeLiu0417/physical-stimulation-session-recorder/main/showcase_app.py'
)
foreach ($url in $anonymousUrls) {
    $status = curl.exe -sS -o NUL -w '%{http_code}' $url
    if ($status -ne '404') { throw "Anonymous request returned $status for $url" }
}
```

Expected: authenticated visibility remains `PRIVATE`; both unauthenticated URLs return `404`.

### Task 4: Recover And Verify The Streamlit Deployment

**Files:**
- Deploy: private `main` / `showcase_app.py`
- Preserve: existing Streamlit secret key `SHOWCASE_PASSWORD_SHA256`; never write its value to Git or this plan

- [ ] **Step 1: Poll the post-merge rebuild without exposing credentials**

Run:

```powershell
$appUrl = 'https://physical-stimulation-session-recorder.streamlit.app'
$healthUrl = "$appUrl/_stcore/health"
$healthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    $body = curl.exe -fsS --max-time 20 $healthUrl 2>$null
    if ($LASTEXITCODE -eq 0 -and $body.Trim() -eq 'ok') {
        $healthy = $true
        break
    }
    Start-Sleep -Seconds 10
}
$healthy
```

Expected: `$healthy` becomes `True` and the health endpoint returns exactly `ok`.

- [ ] **Step 2: If health remains false, align the Community Cloud runtime without changing project dependencies**

Use the signed-in Streamlit Community Cloud app settings for only this app. Confirm these exact deployment fields:

```text
Repository: YaoZeLiu0417/physical-stimulation-session-recorder
Branch: main
Main file path: showcase_app.py
App URL: physical-stimulation-session-recorder
Python version: 3.10
Secret key present: SHOWCASE_PASSWORD_SHA256
```

If the existing app was created with Python 3.13 and the runtime selector is immutable, remove only the failed `physical-stimulation-session-recorder` app and recreate it immediately with the same URL and Python 3.10. Restore the existing digest from the secure session into the Secrets editor; do not print it, add it to shell history, or store it in a file. Re-run Step 1 after the reboot.

Expected: the backend becomes healthy. If logs still show dependency installation failure on Python 3.10, stop before changing more dependencies and return to the isolated-entry-point rollback in the approved design.

- [ ] **Step 3: Confirm root and health responses**

Run:

```powershell
$rootStatus = curl.exe -sS -o NUL -w '%{http_code}' $appUrl
$healthStatus = curl.exe -sS -o NUL -w '%{http_code}' $healthUrl
$healthBody = curl.exe -fsS $healthUrl
[PSCustomObject]@{ RootStatus=$rootStatus; HealthStatus=$healthStatus; HealthBody=$healthBody }
```

Expected: root status `200`, health status `200`, and health body `ok`.

- [ ] **Step 4: Verify the protected four-step experience**

Open `$appUrl` in the signed-in in-app browser and perform this exact sequence:

1. Submit a deliberately wrong password and confirm access is rejected.
2. Enter the approved one-time demonstration password from the secure session and confirm the overview opens.
3. Advance through overview, synthetic capture, two slider ratings, confirmation, and restart.
4. Confirm restart returns to the overview without a download, camera prompt, upload, participant identifier, study-specific label, questionnaire content, or visible score.

Expected: the complete flow matches `tests/test_showcase_app.py`; only neutral synthetic content is visible. If in-app browser control is unavailable, pause only this visual check and ask the user to perform the same sequence after backend health is proven.

- [ ] **Step 5: Record the recovery boundary and continue the existing release plan**

Report the merged private PR URL, full pytest result, anonymous `404` results, deployed app URL, and remote health result. Then resume Tasks 9 and 10 in `docs/superpowers/plans/2026-07-25-private-source-public-showcase.md` to build, audit, and publish the separate README-only public showcase repository.

Expected: the deployment recovery is complete before any public repository is created.
