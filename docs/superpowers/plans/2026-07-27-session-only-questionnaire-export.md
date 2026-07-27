# Session-Only Questionnaire Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the operational application's server recording, record persistence, and upload path with the verified browser-local recorder, the complete existing questionnaires, and one participant-downloaded in-memory ZIP containing JSON and Excel.

**Architecture:** `app.py` owns one session-scoped record dictionary and never instantiates the legacy disk store. Pure workflow modules create the record, preserve raw questionnaire branches, build one canonical participant-safe snapshot, and serialize the same snapshot to JSON and Excel before assembling a ZIP entirely in memory. The participant confirms local save, then the application clears all sensitive session keys.

**Tech Stack:** Python 3.10, Streamlit 1.37.1, the verified browser recorder component, `XlsxWriter` for in-memory XLSX generation, `openpyxl` for independent test parsing, Python `json`/`io`/`zipfile`, pytest 8, Streamlit AppTest.

---

## Preconditions

- Work from `D:\proj_taVNS\.worktrees\physical-stimulation-session-recorder\browser-local-recorder-operational`.
- Branch: `feat/browser-local-recorder-operational`.
- Merged private base: `0360253`.
- Approved design: `docs/superpowers/specs/2026-07-27-local-questionnaire-export-and-showcase-design.md`.
- Existing verified prerequisite commit: `a958f88 feat: add local recording workflow gate`.
- Baseline: `615 passed, 3 skipped` and Node recorder `42 passed`.
- Do not modify questionnaire wording, field IDs, option sets, visit schedules, branch predicates, scoring inputs, or safety triggers.
- Do not delete, rewrite, migrate, or inspect historical participant files during implementation.

## Resolved Design Choices

- One signed link/session represents one visit. Each ZIP exports the current
  visit only; every configured visit type must be supported, but a ZIP does not
  aggregate separate historical sessions.
- The existing explicit continue-without-recording path remains eligible for
  questionnaires and export. Its ZIP contains only the sanitized
  `failed`/`skipped` recording status.
- All application/export timestamps are timezone-aware UTC values serialized
  to second precision.
- Finish preserves authentication/link-lock state and a non-sensitive completion
  marker only; all questionnaire, recorder, and export state is removed.
- `record_store.py` remains inactive archival code. `upload_workflow.py` and
  `bd_init.py` are removed because retaining upload capability is outside the
  approved boundary.

## File Map

- Create: `participant_identity.py` - pure participant ID validation shared by signed links and archival storage.
- Create: `tests/test_participant_identity.py` - exact validation and import-boundary tests.
- Create: `session_record_workflow.py` - pure session record construction, context matching, and cleanup ownership.
- Create: `tests/test_session_record_workflow.py` - exact record schema and no-storage contracts.
- Create: `local_export_bundle.py` - generic in-memory JSON/XLSX/ZIP serialization.
- Create: `tests/test_local_export_bundle.py` - ZIP/XLSX correctness, styling, and formula-injection tests.
- Create: `questionnaire_export.py` - participant-safe questionnaire snapshot and workbook rows.
- Create: `tests/test_questionnaire_export.py` - raw-answer equivalence and prohibited-field tests.
- Create: `tests/test_questionnaire_inventory.py` - checked-in pre-migration questionnaire contract.
- Create: `tests/fixtures/questionnaire_inventory.json` - exact field/option/branch/visit inventory.
- Modify: `link_auth.py`, `record_store.py` - import pure participant identity validation.
- Modify: `app_workflow.py` - support raw-only operational persistence and remove active media/upload helpers.
- Modify: `app.py` - session-only record, local recorder, questionnaires, download, confirmation, cleanup.
- Modify: `tests/test_app_integration.py` - lock ordering, session-only behavior, privacy, and no server capability.
- Modify: `tests/fixtures/questionnaire_app.py` - session-only end-to-end fixture.
- Delete: `tests/fixtures/questionnaire_fixture_storage.py` when no test imports it.
- Modify: `tests/test_questionnaire_end_to_end.py` - preserve questionnaire behavior without disk recovery/upload.
- Delete: `upload_workflow.py`, `tests/test_upload_workflow.py` after all runtime callers are removed.
- Modify: `requirements.txt`, `tests/test_requirements_contract.py` - remove media/upload dependencies and add XLSX support.
- Modify: `requirements-dev.txt` - add independent XLSX parsing for tests.
- Delete: `bd_init.py` - obsolete interactive Baidu credential utility.
- Preserve as inactive archive: `record_store.py`, `tests/test_record_store.py`, and existing historical data.

## Task 0: Snapshot The Pre-Migration Questionnaire Contract

**Files:**
- Create: `tests/test_questionnaire_inventory.py`
- Create: `tests/fixtures/questionnaire_inventory.json`

- [ ] **Step 1: Write the failing inventory test**

Build a deterministic inventory directly from `DAILY_CORE`,
`DAILY_CONDITIONAL`, `WEEKLY_INSTRUMENTS`, `FORMAL_INSTRUMENTS`,
`VISIT_INSTRUMENT_IDS`, and `WEEKLY_DAYS`. For every item capture ID, prompt,
kind, required flag, range, labels, options, and `show_if`. Capture instrument
IDs, labels, time windows, item order, visit order, and weekly schedule. Also
capture:

- SHA-256 hashes of `questionnaire_specs.py`, `questionnaire_ui.py`, and
  `questionnaire_scoring.py` from the approved base;
- the daily count/scoring input IDs and every formal instrument scoring input
  ID in protocol order;
- the SICQ reverse-scored raw input ID without serializing a reversed value;
- the daily suicide-support trigger and all formal `pss_*` support trigger IDs.

```python
EXPECTED = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
assert build_current_inventory() == EXPECTED
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_questionnaire_inventory.py -q
```

Expected: FAIL because the fixture is absent.

- [ ] **Step 3: Generate and review the one-time fixture**

Use the same deterministic helper to emit sorted, UTF-8 JSON with two-space
indentation. Inspect the diff for complete daily, weekly, formal, and visit
coverage. The production questionnaire files remain unchanged.

- [ ] **Step 4: Verify and commit**

```powershell
python -m pytest tests/test_questionnaire_inventory.py tests/test_questionnaire_specs.py -q
git diff --check
git add tests/test_questionnaire_inventory.py tests/fixtures/questionnaire_inventory.json
git commit -m "test: snapshot questionnaire equivalence contract"
```

## Task 1: Extract Pure Participant Identity Validation

**Files:**
- Create: `participant_identity.py`
- Create: `tests/test_participant_identity.py`
- Modify: `record_store.py`
- Modify: `link_auth.py`
- Modify: `tests/test_link_auth.py`

- [ ] **Step 1: Write failing source-boundary and behavior tests**

Create tests that require `participant_identity.validate_subject_id` to accept
only trimmed IDs matching `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`. Add an AST test
requiring `link_auth.py` to import `validate_subject_id` from
`participant_identity`, not `record_store`.

```python
@pytest.mark.parametrize("subject_id", ["sub-001", "A", "user_name-2"])
def test_validate_subject_id_accepts_approved_identifiers(subject_id):
    assert validate_subject_id(subject_id) == subject_id


@pytest.mark.parametrize("subject_id", ["", " subject", "subject ", "../subject", "a" * 65])
def test_validate_subject_id_rejects_unsafe_identifiers(subject_id):
    with pytest.raises(ValueError):
        validate_subject_id(subject_id)
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_participant_identity.py tests/test_link_auth.py -q
```

Expected: collection fails because `participant_identity` does not exist and
the source-boundary assertion still sees the archival store import.

- [ ] **Step 3: Implement the pure module and redirect imports**

```python
import re


SUBJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_subject_id(subject_id: str) -> str:
    if not isinstance(subject_id, str):
        raise ValueError("participant identifier is invalid")
    safe_subject_id = subject_id.strip()
    if safe_subject_id != subject_id or not SUBJECT_ID_RE.fullmatch(safe_subject_id):
        raise ValueError("participant identifier is invalid")
    return safe_subject_id
```

Import this function from both `link_auth.py` and `record_store.py`; remove the
duplicate regex/function from `record_store.py`. Keep public re-export
compatibility in `record_store.py` so archival callers and tests continue to
work.

- [ ] **Step 4: Verify and commit**

```powershell
python -m pytest tests/test_participant_identity.py tests/test_link_auth.py tests/test_record_store.py -q
python -m compileall -q participant_identity.py link_auth.py record_store.py tests
git diff --check
git add participant_identity.py link_auth.py record_store.py tests/test_participant_identity.py tests/test_link_auth.py
git commit -m "refactor: isolate participant identity validation"
```

## Task 2: Define The Session-Only Record

**Files:**
- Create: `session_record_workflow.py`
- Create: `tests/test_session_record_workflow.py`

- [ ] **Step 1: Write failing exact-schema tests**

Require this public API:

```python
def create_session_record(
    subject_id: str,
    record_date: date,
    intervention_day: int,
    visit: str,
    *,
    token: str,
    now_iso: str,
) -> dict[str, object]: ...


def session_record_matches(
    record: object,
    *,
    subject_id: str,
    record_date: date,
    intervention_day: int,
    visit: str,
) -> bool: ...


def clear_owned_session_state(
    state: MutableMapping[str, object],
    *,
    exact_keys: Iterable[str],
    prefixes: Iterable[str],
) -> None: ...
```

The record contains `schema_version=5`, pseudonymous identity, visit,
instrument versions, daily/raw/formal sections, field status, sanitized
recording metadata, completion state, and timestamps. It contains no
`upload`, `local_cleanup`, `derived_metrics`, path, filename, or media field.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_session_record_workflow.py -q
```

Expected: collection fails because the module is absent.

- [ ] **Step 3: Implement exact construction and context matching**

Validate `token` as exactly eight lowercase hex characters, validate the visit
against `("daily", *VISIT_INSTRUMENT_IDS)`, validate the intervention day as
`1..28`, and use a record ID only inside the record:

```python
{
    "schema_version": 5,
    "record_id": f"{safe_subject_id}_{record_date:%Y%m%d}_{token}",
    "subject_id": safe_subject_id,
    "record_date": record_date.isoformat(),
    "intervention_day": intervention_day,
    "visit": visit,
    "revision": 1,
    "instrument_versions": {
        "daily_nssi_ema": "1.0",
        "weekly_nssi": "1.0",
        "formal_nssi_crf": "1.0",
    },
    "daily_context": {},
    "daily_core": {},
    "conditional_details": {},
    "weekly_extension": {},
    "formal_visits": {},
    "field_status": {},
    "recording": {},
    "completion": {
        "status": "draft",
        "answered_field_ids": {},
        "current_step": {},
        "questionnaire_visits": {},
    },
    "created_at_iso": now_iso,
    "updated_at_iso": now_iso,
}
```

Cleanup must delete only exact owned keys and keys beginning with approved
prefixes; it must never clear authentication or unrelated Streamlit state.

- [ ] **Step 4: Add source-capability tests**

AST/source tests reject `pathlib`, `open`, `tempfile`, `requests`, sockets,
uploads, storage APIs, `DailyRecordStore`, media bytes, and filenames.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/test_session_record_workflow.py -q
python -m compileall -q session_record_workflow.py tests/test_session_record_workflow.py
git diff --check
git add session_record_workflow.py tests/test_session_record_workflow.py
git commit -m "feat: add session-only participant record"
```

## Task 3: Move Questionnaire Persistence To The Session Record

**Files:**
- Modify: `session_record_workflow.py`
- Modify: `app_workflow.py`
- Modify: `tests/test_app_integration.py`
- Modify: `tests/test_questionnaire_end_to_end.py`

- [ ] **Step 1: Write failing raw-only session tests**

Move these public functions to `session_record_workflow.py`:

```python
questionnaire_answers(record, visit)
questionnaire_visit_complete(record, visit)
mark_questionnaire_visit_complete(record, visit, *, completed_at_iso)
persist_daily_questionnaire(record, answers, answered_field_ids, *, current_step, daily_context=None)
persist_formal_questionnaire(record, visit, answers, answered_field_ids, *, current_step)
```

Assert the functions preserve raw answers, false/zero/empty values, answered
IDs, field status, conditional applicability, instrument metadata,
completeness, completion time, and stable order while creating no
`derived_metrics`, `scored_answers`, `score`, or hidden safety classification.
Stale conditional answers must be removed when their controller changes.

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_app_integration.py tests/test_questionnaire_end_to_end.py -q
```

Expected: the session module lacks the functions and the active workflow still
computes/serializes derived results.

- [ ] **Step 3: Implement raw-only session mutation**

Port only the raw projection, applicability, instrument grouping, completion,
and field-status behavior. Specifically:

- do not import or call `daily_derived_metrics`, `score_sicq`,
  `_formal_scored_answers`, or `score_formal_instrument`;
- do not create `record["derived_metrics"]` or store `safety_signals`;
- formal instrument payloads contain `instrument_id`, version, time window,
  `raw_answers`, completeness, and `complete` only;
- continue updating `field_status`, completion, current step, and raw answer
  sections.

Keep `support_needed` in `app_workflow.py` as a pure calculation over current
raw answers and answered IDs. Remove scoring imports from the active
`app_workflow.py` import graph. The standalone `questionnaire_scoring.py` and
its tests remain for authorized offline analysis.

- [ ] **Step 4: Verify raw equivalence and offline scoring coverage**

```powershell
python -m pytest tests/test_app_integration.py tests/test_questionnaire_end_to_end.py tests/test_questionnaire_scoring.py tests/test_questionnaire_specs.py -q
git diff --check
git add session_record_workflow.py app_workflow.py tests/test_app_integration.py tests/test_questionnaire_end_to_end.py
git commit -m "feat: preserve raw questionnaire responses without scoring"
```

## Task 4: Build A Generic In-Memory JSON And Excel ZIP

**Files:**
- Create: `local_export_bundle.py`
- Create: `tests/test_local_export_bundle.py`

- [ ] **Step 1: Write failing bundle and workbook tests**

Define:

```python
@dataclass(frozen=True)
class LocalExportBundle:
    filename: str
    mime_type: str
    data: bytes


def build_local_export_bundle(
    *,
    snapshot: Mapping[str, object],
    sheets: Mapping[str, Sequence[Mapping[str, object]]],
    exported_at: datetime,
    filename_prefix: str = "session",
) -> LocalExportBundle: ...
```

Tests must open the returned bytes with `zipfile.ZipFile`, require exactly
`responses.json` and `responses.xlsx`, parse JSON, load XLSX from `BytesIO` with
`openpyxl`, and
assert both represent the same supplied rows. The outer filename must match
`session-YYYYMMDD-HHMMSS.zip` and contain no participant/study identifier.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_local_export_bundle.py -q
```

Expected: collection fails because the module is absent.

- [ ] **Step 3: Implement memory-only serialization**

Use only `BytesIO`, `json.dumps`, `zipfile.ZipFile`, and
`xlsxwriter.Workbook`. Construct the workbook with `in_memory=True`,
`strings_to_formulas=False`, and `strings_to_urls=False`; close it into
`BytesIO`. Never accept or construct a filesystem path.

Use a stable workbook style:

- navy header fill `000035`, white bold text;
- violet section accents `2D2674`;
- frozen first row and autofilter;
- wrapped text and bounded column widths `12..48`;
- typed numbers/booleans/dates where possible;
- no formulas, charts, hidden sheets, macros, or external links.

Write every textual value with `write_string`; prefix text beginning with `=`,
`+`, `-`, or `@` with an apostrophe. JSON retains the original raw text. Reject
text longer than Excel's 32,767-character cell limit instead of silently
truncating it.

- [ ] **Step 4: Add capability and corruption tests**

Reject invalid sheet names, duplicate normalized names, non-UTC/naive export
times, unsafe filename prefixes, NaN/Infinity, and unsupported cell objects.
Set deterministic ZIP member timestamps and ordering. Source tests
reject filesystem paths, temporary files, network calls, and upload APIs.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/test_local_export_bundle.py -q
python -m compileall -q local_export_bundle.py tests/test_local_export_bundle.py
git diff --check
git add local_export_bundle.py tests/test_local_export_bundle.py
git commit -m "feat: build in-memory JSON and Excel export bundles"
```

## Task 5: Build The Participant-Safe Questionnaire Snapshot

**Files:**
- Create: `questionnaire_export.py`
- Create: `tests/test_questionnaire_export.py`

- [ ] **Step 1: Write failing canonical snapshot tests**

Require:

```python
RawExportValue = str | int | float | bool | tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ResponseSnapshot:
    visit: str
    instrument_id: str
    instrument_version: str
    field_id: str
    question_text: str
    question_kind: str
    answered: bool
    applicability: str
    raw_value: RawExportValue
    display_value: str


@dataclass(frozen=True, slots=True)
class VisitSnapshot:
    visit: str
    visit_status: str
    completed_at_iso: str
    instrument_id: str
    instrument_version: str
    instrument_status: str
    answered_field_ids: tuple[str, ...]
    field_status: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ParticipantSnapshot:
    export_schema_version: int
    participant_id: str
    record_date: str
    intervention_day: int
    visit: str
    exported_at_iso: str
    daily_context: tuple[tuple[str, RawExportValue], ...]
    recording: tuple[tuple[str, RawExportValue], ...]
    answered_field_ids: tuple[str, ...]
    field_status: tuple[tuple[str, str], ...]
    responses: tuple[ResponseSnapshot, ...]
    visits: tuple[VisitSnapshot, ...]


def build_participant_snapshot(
    record: Mapping[str, object],
    *,
    visit: str,
    exported_at_iso: str,
) -> ParticipantSnapshot: ...


def participant_snapshot_json(
    snapshot: ParticipantSnapshot,
) -> dict[str, object]: ...


def questionnaire_export_sheets(
    snapshot: ParticipantSnapshot,
) -> dict[str, tuple[dict[str, object], ...]]: ...


def build_participant_export(
    record: Mapping[str, object],
    *,
    visit: str,
    exported_at: datetime,
) -> LocalExportBundle: ...
```

The snapshot includes schema version, pseudonymous session context, daily
context, sanitized version-2 recording metadata, raw answers, field status,
answered IDs, conditional applicability, one `VisitSnapshot` per applicable
instrument, and completion timestamps. It excludes every `derived_metrics`, `score`,
`scored_answers`, `safety_signals`, risk, threshold, upload, cleanup, path,
filename, device label, and media field even when hostile input includes them.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_questionnaire_export.py -q
```

Expected: collection fails because the module is absent.

- [ ] **Step 3: Implement explicit allowlist projection**

Never copy the record recursively and delete prohibited keys. Construct frozen
tuples from an explicit allowlist so later record mutation cannot change a
cached export. Resolve question metadata from
`DAILY_CORE`, `DAILY_CONDITIONAL`, `WEEKLY_INSTRUMENTS`, and
`FORMAL_INSTRUMENTS`; create exactly these workbook sheets:

```python
{
    "Session": session_rows,
    "Responses": response_rows,
    "Visits": visit_rows,
    "Recording": recording_rows,
}
```

Each response row has `visit`, `instrument_id`, `field_id`, `question_text`,
`question_kind`, `answered`, `applicability`, `raw_value`, and `display_value`.
Lists and mappings use deterministic JSON strings in Excel.

- [ ] **Step 4: Add daily/formal/conditional and privacy cases**

Cover day 1, weekly day 7, a negative daily branch, a conditional positive
branch, and every formal visit inventory. Parse both ZIP members and prove raw
values and applicable/answered IDs match. Inject sentinel score/risk/path/upload
values and prove none appear in JSON, workbook cell values, filename, or ZIP
member names.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/test_questionnaire_export.py tests/test_local_export_bundle.py -q
python -m compileall -q questionnaire_export.py tests/test_questionnaire_export.py
git diff --check
git add questionnaire_export.py tests/test_questionnaire_export.py
git commit -m "feat: add participant-safe questionnaire export"
```

## Task 6: Replace The Operational App Runtime

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_integration.py`

- [ ] **Step 1: Write failing runtime source-boundary tests**

Require `app.py` to import:

- `render_browser_recorder`;
- `local_recording_metadata` and `recording_gate_satisfied`;
- `create_session_record`, `session_record_matches`, and
  `clear_owned_session_state`;
- `build_participant_export`.

Reject imports/calls for `DailyRecordStore`, `record_store`, `upload_workflow`,
`requests`, `toml`, `streamlit_webrtc`, `aiortc`, `MediaRecorder`,
`webrtc_streamer`, `Path`, `open`, `REC_DIR`, FLV/MP4 conversion, Baidu OAuth,
remote paths, upload progress, server playback, and history operations.

- [ ] **Step 2: Write failing participant-flow behavior tests**

Use Streamlit AppTest/stubs to prove:

- the signed link locks the subject and visit;
- the session record is created once for the exact subject/date/day/visit;
- local recording renders after daily context and before questionnaires;
- recording blocks progress;
- saved+confirmed stores exact version-2 local metadata;
- skipped/failed requires explicit continue-without-recording;
- questionnaire draft callbacks mutate only the raw-only session record and
  cannot request or create derived results;
- all required and conditional questions gate export;
- support copy still renders when triggered;
- participant pages never display answer summaries, scores, risk labels, raw
  export mappings, paths, or internal status dictionaries.

- [ ] **Step 3: Verify RED**

```powershell
python -m pytest tests/test_app_integration.py -q
```

Expected: source and behavior tests fail on the server recorder/store/upload
runtime.

- [ ] **Step 4: Replace bootstrap and session record acquisition**

Remove Baidu configuration requirements and all server directory creation.
Keep signed-link and admin authentication, trusted intervention day, visit
selection, daily context, questionnaire styling, and safety contact secrets.

Store the record only in `st.session_state["operational_record"]`. Generate its
token and timestamp once. If the current record does not match subject/date/day
and visit, clear owned questionnaire/recorder/export keys before creating a new
record.

- [ ] **Step 5: Integrate the browser-local recorder**

Render with a stable session-only key and `initial_mode="long"`. Persist only
`local_recording_metadata(status)` after
`recording_gate_satisfied(...)`. The component key must not contain the subject
ID. Do not render filenames or recorder status dictionaries.

- [ ] **Step 6: Preserve the questionnaire flow in raw-only mode**

Reuse `questionnaire_state_keys`, `render_questionnaire`, daily/formal
persistence, branch validation, and support messages. The session persistence
API is raw-only and exposes no `include_derived` switch. Draft saves mutate
`st.session_state` only and must not log answers.

- [ ] **Step 7: Add local download and finish cleanup**

After visit completion, build and cache one `LocalExportBundle` from an
immutable snapshot. Render one `st.download_button` with:

```python
label="下载问卷记录（JSON + Excel）"
data=bundle.data
file_name=bundle.filename
mime="application/zip"
```

Require a separate checkbox confirming local save and an explicit finish
button. Finish clears the record, export bytes, questionnaire prefixes,
recorder keys, local-save confirmation, and daily-context widget keys while
preserving authentication. Show only a neutral completion message afterward.

- [ ] **Step 8: Verify and commit**

```powershell
python -m pytest tests/test_app_integration.py tests/test_browser_recorder.py tests/test_local_recording_workflow.py tests/test_session_record_workflow.py tests/test_questionnaire_export.py -q
git diff --check
git add app.py tests/test_app_integration.py
git commit -m "feat: use session-only questionnaires and local export"
```

## Task 7: Convert The End-To-End Questionnaire Fixture To Memory

**Files:**
- Modify: `tests/fixtures/questionnaire_app.py`
- Delete: `tests/fixtures/questionnaire_fixture_storage.py`
- Modify: `tests/test_questionnaire_end_to_end.py`

- [ ] **Step 1: Write failing no-disk fixture tests**

Require the fixture to use `create_session_record` and Streamlit session state,
not `DailyRecordStore`, environment store roots, run directories, or temporary
video files. Assert a fresh AppTest session has no prior draft while reruns in
the same session retain current answers.

- [ ] **Step 2: Replace persistence/recovery expectations**

Keep tests for day 1, day 7, every formal visit, conditional branches, raw
answers, answered IDs, safety response, step navigation, and privacy. Replace
server restart/revision/upload tests with:

- same-session rerun retention;
- new-session loss as the documented behavior;
- successful JSON/XLSX ZIP generation;
- local-save confirmation and sensitive-session cleanup.

- [ ] **Step 3: Implement the session fixture**

Create the record once with deterministic token/time, place it in
`st.session_state`, and mutate it through raw-only persistence callbacks. Do not
construct `Path`, write a file, expose a remote path, or add synthetic derived
scores to participant-visible state.

- [ ] **Step 4: Verify and commit**

```powershell
python -m pytest tests/test_questionnaire_end_to_end.py -q
git diff --check
git add tests/fixtures/questionnaire_app.py tests/test_questionnaire_end_to_end.py
git rm tests/fixtures/questionnaire_fixture_storage.py
git commit -m "test: run questionnaire journeys without server storage"
```

## Task 8: Remove Obsolete Runtime Media, Upload, And Dependencies

**Files:**
- Modify: `app_workflow.py`
- Delete: `upload_workflow.py`
- Delete: `tests/test_upload_workflow.py`
- Delete: `bd_init.py`
- Modify: `tests/test_app_integration.py`
- Modify: `requirements.txt`
- Modify: `tests/test_requirements_contract.py`

- [ ] **Step 1: Write failing dependency and source inventory tests**

Require the exact direct requirements:

```python
(
    "streamlit==1.37.1",
    "numpy>=1.24,<2.0",
    "XlsxWriter>=3.2,<4",
    "protobuf<5",
)
```

Require the exact development additions in `requirements-dev.txt`:

```python
(
    "pytest>=8.3,<9",
    "openpyxl>=3.1,<4",
)
```

Require the operational import closure to contain none of `requests`, `toml`,
`python-dotenv`, `streamlit_webrtc`, `aiortc`, `av`, upload endpoints, recorder
paths, file cleanup, transcode, or server history helpers.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_requirements_contract.py tests/test_app_integration.py -q
```

Expected: old dependencies and helper APIs remain.

- [ ] **Step 3: Delete orphaned upload/media helpers**

After proving no runtime caller remains, remove completed-file/path dataclasses,
trusted media path validation, uploaded cleanup recovery, upload adapters,
upload messages, and their imports from `app_workflow.py`. Delete
`upload_workflow.py`, its test file, and the obsolete `bd_init.py` credential
utility. Keep questionnaire, intervention-day,
daily-context, support, and authentication helpers.

- [ ] **Step 4: Reduce requirements and verify resolution**

```powershell
python -m pip install --dry-run -r requirements.txt
python -m pip install --dry-run -r requirements-dev.txt
```

Expected: the four direct requirements resolve without WebRTC/media/upload
packages being requested directly.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/test_requirements_contract.py tests/test_app_integration.py tests/test_questionnaire_end_to_end.py tests/test_record_store.py -q
python -m compileall -q app.py app_workflow.py browser_recorder.py local_recording_workflow.py participant_identity.py session_record_workflow.py local_export_bundle.py questionnaire_export.py questionnaire_scoring.py questionnaire_specs.py questionnaire_ui.py tests
rg -n "streamlit_webrtc|aiortc|MediaRecorder|webrtc_streamer|\.flv|transcode_to_mp4|upload_record_bundle|pan\.baidu|recordings/" app.py app_workflow.py participant_identity.py session_record_workflow.py local_export_bundle.py questionnaire_export.py
git diff --check
git add app_workflow.py requirements.txt tests/test_requirements_contract.py tests/test_app_integration.py
git add requirements-dev.txt
git rm upload_workflow.py tests/test_upload_workflow.py bd_init.py
git commit -m "chore: remove operational server media and uploads"
```

## Task 9: Prove Questionnaire And Privacy Equivalence

**Files:**
- Modify tests only if a missing gate is found.

- [ ] **Step 1: Lock questionnaire source equivalence**

Require no production changes against the merged pre-migration base:

```powershell
git diff --exit-code 0360253 -- questionnaire_specs.py questionnaire_ui.py questionnaire_scoring.py
```

Run inventory tests that enumerate all daily/core/conditional/weekly/formal
field IDs, prompts, kinds, options, ranges, required flags, show-if predicates,
visit schedules, and scoring inputs.

- [ ] **Step 2: Exercise privacy and safety branches**

Run a daily negative branch, daily NSSI-positive conditional branch, suicide
support branch, weekly day, and every formal visit. Prove support messages
remain visible when triggered and participant-visible/export inventories contain
no derived score/risk/threshold/path/upload value.

- [ ] **Step 3: Prove no persistent write or upload**

Run the operational fixture under a temporary working directory and compare the
filesystem inventory before and after. Only pytest/Streamlit caches may change;
no participant JSON, XLSX, ZIP, video, recordings directory, or store index may
appear. Patch network clients to fail if called.

- [ ] **Step 4: Run all automated gates**

```powershell
node --test tests/js/test_recorder_core.mjs
python -m pytest tests/test_browser_recorder.py tests/test_local_recording_workflow.py tests/test_participant_identity.py tests/test_session_record_workflow.py tests/test_local_export_bundle.py tests/test_questionnaire_export.py tests/test_app_integration.py tests/test_questionnaire_end_to_end.py tests/test_questionnaire_specs.py tests/test_questionnaire_scoring.py tests/test_record_store.py tests/test_requirements_contract.py -q
python -m pytest -q
python -m compileall -q .
python -m pip install --dry-run -r requirements.txt
git diff --check
git status --short
```

- [ ] **Step 5: Request spec and quality reviews**

Review Tasks 1-9 against the approved design. Fix every Critical/Important
issue through TDD and repeat both reviews. Do not start the showcase plan while
an operational issue remains open.

## Real Chrome Gate

After private PR deployment, use a synthetic participant ID and desktop Chrome:

1. open a signed participant-style link;
2. enter daily context;
3. locally save a short audio/video recording;
4. complete a negative daily branch and a conditional-positive branch;
5. verify support guidance when triggered;
6. download the ZIP and inspect both JSON and Excel;
7. confirm no score/risk/path/upload fields are present;
8. confirm no questionnaire/media upload request occurs;
9. confirm finish clears the current questionnaire session;
10. confirm refreshing before download loses the draft as documented.

## Agent Retry Rule

If an implementation or review subagent fails specifically with HTTP `429`,
wait 5-10 seconds and automatically retry the same bounded task. Do not weaken
privacy, questionnaire, spreadsheet, or test gates because of an agent-service
rate limit.
