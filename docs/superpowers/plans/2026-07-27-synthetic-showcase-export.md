# Synthetic Showcase Local Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the private teacher showcase with a synthetic questionnaire ZIP download step while keeping every real questionnaire, score, study term, and participant value outside the showcase.

**Architecture:** The showcase gains a five-state transition table and a dedicated `showcase_export` module that accepts only four fixed synthetic ratings plus a sanitized recording outcome. It delegates generic in-memory JSON/XLSX/ZIP serialization to `local_export_bundle` but never imports operational questionnaire modules.

**Tech Stack:** Python 3.10, Streamlit 1.37.1, the verified browser recorder, the generic in-memory export bundle, XlsxWriter, openpyxl test parsing, pytest 8, Streamlit AppTest.

---

## Preconditions

- Complete and review `docs/superpowers/plans/2026-07-27-session-only-questionnaire-export.md` first.
- `local_export_bundle.py` and its focused tests must be merged on the feature branch.
- Work in the same private isolated worktree; do not place screenshots or exports in the source repository.
- Preserve the current access password boundary and the verified local recorder behavior.
- The showcase must remain synthetic and may not import `questionnaire_specs`, `questionnaire_ui`, `questionnaire_scoring`, `session_record_workflow`, or `questionnaire_export`.

## File Map

- Create: `showcase_export.py` - closed synthetic snapshot and ZIP builder.
- Create: `tests/test_showcase_export.py` - exact archive, isolation, and privacy tests.
- Modify: `showcase_workflow.py` - add the download state.
- Modify: `tests/test_showcase_workflow.py` - lock the five-state transition table.
- Modify: `showcase_app.py` - render download, confirmation, retry, and cleanup.
- Modify: `tests/test_showcase_app.py` - verify the complete synthetic flow and visible inventory.

## Task 1: Add The Download State

**Files:**
- Modify: `showcase_workflow.py`
- Modify: `tests/test_showcase_workflow.py`

- [ ] **Step 1: Write the failing transition-table test**

Require exactly:

```python
EXPECTED_TRANSITIONS = {
    ("overview", "begin"): "capture",
    ("capture", "finish_capture"): "reflection",
    ("reflection", "save_reflection"): "download",
    ("download", "finish_download"): "confirmation",
    ("confirmation", "restart"): "overview",
}
```

Keep the Cartesian invalid-transition test with states
`overview/capture/reflection/download/confirmation` and actions
`begin/finish_capture/save_reflection/finish_download/restart`.

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_showcase_workflow.py -q
```

Expected: reflection still transitions directly to confirmation and the new
state/action are rejected.

- [ ] **Step 3: Implement the exact table and verify**

Change only `TRANSITIONS`; keep password behavior untouched.

```powershell
python -m pytest tests/test_showcase_workflow.py -q
git diff --check
git add showcase_workflow.py tests/test_showcase_workflow.py
git commit -m "feat: add showcase download transition"
```

## Task 2: Build The Isolated Synthetic Export

**Files:**
- Create: `showcase_export.py`
- Create: `tests/test_showcase_export.py`

- [ ] **Step 1: Write failing fixed-input export tests**

Define:

```python
@dataclass(frozen=True, slots=True)
class SyntheticShowcaseArchive:
    filename: str
    data: bytes


def build_synthetic_showcase_zip(
    *,
    process_clarity: int,
    camera_smoothness: int | None,
    information_load: int,
    workflow_willingness: int,
    recording_state: str,
    generated_at: datetime,
) -> SyntheticShowcaseArchive: ...
```

Accept ratings only as exact integers `0..4`. `camera_smoothness=None` is valid
only when the recording state is `skipped` or `failed`. Recording state is one
of `saved/skipped/failed`; no arbitrary mapping is accepted.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_showcase_export.py -q
```

Expected: collection fails because the module is absent.

- [ ] **Step 3: Implement the synthetic snapshot and bundle**

Create invented IDs only:

```python
(
    "demo_process_clarity",
    "demo_camera_smoothness",
    "demo_information_load",
    "demo_workflow_willingness",
)
```

The JSON contains schema version, UTC generation time, synthetic recording
state, and the four ratings with an explicit camera applicability flag. The
workbook uses exactly `Session`, `Responses`, and `Recording` sheets. Call
`build_local_export_bundle(..., filename_prefix="synthetic-session")` and map
the returned data to `SyntheticShowcaseArchive`.

- [ ] **Step 4: Add isolation/privacy tests**

Require ZIP members exactly `responses.json` and `responses.xlsx`; compare JSON
and parsed XLSX values; cover saved and skipped/failed branches; reject unknown
values. AST/source tests prohibit real questionnaire/scoring/session/storage/
upload modules, participant IDs, paths, media filenames, network calls,
`pathlib`, and temporary files. Scan archive bytes and cell values for the
private prohibited-term inventory.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/test_showcase_export.py tests/test_local_export_bundle.py -q
python -m compileall -q showcase_export.py tests/test_showcase_export.py
git diff --check
git add showcase_export.py tests/test_showcase_export.py
git commit -m "feat: build isolated synthetic showcase export"
```

## Task 3: Integrate Download And Local Confirmation

**Files:**
- Modify: `showcase_app.py`
- Modify: `tests/test_showcase_app.py`

- [ ] **Step 1: Write failing UI flow tests**

Require progress labels:

```text
1 安全进入
2 会话记录
3 引导反馈
4 本地下载
5 完成确认
```

After feedback submission, require the `download` step with:

- heading `下载合成演示数据`;
- a synthetic-content/local-storage notice;
- one `st.download_button` using the archive bytes and neutral filename;
- checkbox `我已确认合成 ZIP 已保存在本机`;
- explicit `完成演示` button disabled until confirmation;
- no answer summary, score, path, filename detail, or raw export mapping.

Stub export generation to prove retryable failure preserves all ratings and
recorder state and shows only a neutral message.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_showcase_app.py -q
```

Expected: feedback still goes directly to confirmation and no download control
exists.

- [ ] **Step 3: Implement cached generation and download**

Use exact session keys:

```python
SHOWCASE_ARCHIVE_KEY = "showcase_synthetic_archive"
SHOWCASE_EXPORT_ERROR_KEY = "showcase_export_error"
SHOWCASE_LOCAL_SAVE_KEY = "showcase_export_saved_confirmed"
```

Build the archive once per completed feedback set. Never render the archive,
snapshot, or filename as text. A generation exception stores only a boolean or
sanitized category, not exception text.

- [ ] **Step 4: Implement exact restart/return cleanup**

Both restart and return-to-overview clear all synthetic rating keys, camera
status, recorder keys, archive object/bytes, export error, local-save
confirmation, and download-button state. Keep showcase authentication until the
existing access lifecycle clears it.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/test_showcase_app.py tests/test_showcase_workflow.py tests/test_showcase_export.py -q
git diff --check
git add showcase_app.py tests/test_showcase_app.py
git commit -m "feat: add synthetic local download to showcase"
```

## Task 4: Prove Showcase Privacy And Release Readiness

**Files:**
- Modify tests only if a missing gate is found.

- [ ] **Step 1: Run visible-copy and source inventories**

Verify every state with saved and no-recording branches. Visible inventory may
contain only access, overview, recorder, four synthetic ratings, local download,
and neutral confirmation copy. Reject real study terms, questionnaire labels,
score/risk words, participant identifiers, paths, upload status, and internal
recording/export dictionaries.

- [ ] **Step 2: Run all showcase gates**

```powershell
python -m pytest tests/test_showcase_workflow.py tests/test_showcase_export.py tests/test_showcase_app.py tests/test_showcase_audit.py -q
python -m compileall -q showcase_app.py showcase_workflow.py showcase_export.py tests
python -m pytest -q
git diff --check
git status --short
```

- [ ] **Step 3: Request spec and quality reviews**

Fix every Critical/Important issue and repeat both reviews before deploying.

- [ ] **Step 4: Run a real private Chrome demonstration**

Use synthetic ratings and a short local video. Download the synthetic ZIP,
open both members, confirm no private content, confirm finish gating and cleanup,
and verify no media/questionnaire upload request occurs.

## Agent Retry Rule

If an implementation or review subagent fails specifically with HTTP `429`,
wait 5-10 seconds and retry the same bounded task automatically.
