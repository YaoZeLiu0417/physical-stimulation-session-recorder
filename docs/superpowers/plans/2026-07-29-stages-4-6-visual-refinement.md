# Stages 4-6 Visual Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved open-canvas questionnaire, local package summary, and completion confirmation without changing questionnaire behavior, ZIP bytes, finish gating, or privacy boundaries.

**Architecture:** Keep `app.py` as the workflow owner, add escaped pure presentation helpers and shared CSS to `operational_ui.py`, and keep questionnaire-specific progress and native widget rendering in `questionnaire_ui.py`. Keyed borderless Streamlit containers provide stable CSS scope and width alignment while existing widget keys, callbacks, reruns, export construction, and state clearing remain authoritative.

**Tech Stack:** Python 3.13, Streamlit, HTML/CSS emitted through escaped pure helpers, pytest, Streamlit `AppTest`, Node's built-in test runner for recorder regressions.

---

## File Map

- Modify `operational_ui.py`: shared stage 04-06 CSS plus escaped local-package and completion markup/render helpers.
- Modify `questionnaire_ui.py`: validated progress markup and keyed open-canvas layout around the existing one-question renderer.
- Modify `app.py`: stage 05 package canvas, primary download presentation, aligned retry surface, and stage 06 completion helper.
- Modify `tests/test_questionnaire_flow.py`: pure questionnaire progress and escaping contracts.
- Modify `tests/test_operational_ui.py`: package/completion markup, escaping, CSS, responsive, and no-heavy-panel contracts.
- Modify `tests/test_app_integration.py`: exact stage 04-06 surfaces and unchanged workflow/data contracts.

### Task 1: Open Questionnaire Canvas

**Files:**
- Modify: `tests/test_questionnaire_flow.py`
- Modify: `tests/test_operational_ui.py`
- Modify: `questionnaire_ui.py`
- Modify: `operational_ui.py`

- [ ] **Step 1: Write failing pure progress tests**

Add `questionnaire_progress_markup` to the imports in
`tests/test_questionnaire_flow.py` and replace the old plain-context
expectations with explicit progress semantics:

```python
def test_questionnaire_progress_markup_is_escaped_and_accessible():
    markup = questionnaire_progress_markup(
        '<img src=x onerror="bad">', current=3, total=8
    )

    assert "<img" not in markup
    assert "&lt;img src=x onerror=&quot;bad&quot;&gt;" in markup
    assert 'class="questionnaire-progress"' in markup
    assert 'role="progressbar"' in markup
    assert 'aria-valuemin="1"' in markup
    assert 'aria-valuemax="8"' in markup
    assert 'aria-valuenow="3"' in markup
    assert 'style="width: 37.5%"' in markup
    assert "03" in markup and "08" in markup


@pytest.mark.parametrize(
    ("current", "total"),
    ((0, 1), (2, 1), (1, 0), (-1, 3), (True, 3), (1, False)),
)
def test_questionnaire_progress_markup_rejects_invalid_bounds(current, total):
    with pytest.raises(ValueError):
        questionnaire_progress_markup("context", current=current, total=total)
```

- [ ] **Step 2: Write failing open-canvas CSS tests**

Add a focused contract to `tests/test_operational_ui.py`:

```python
def test_questionnaire_canvas_is_open_aligned_and_responsive():
    css = operational_ui.OPERATIONAL_CSS

    assert ".st-key-operational_questionnaire_canvas" in css
    assert "max-width: 960px" in css
    assert ".questionnaire-progress__track" in css
    assert ".questionnaire-prompt" in css
    assert "border-left: 4px solid var(--operational-cyan)" in css
    assert ".questionnaire-progress__fill" in css
    assert "background: var(--operational-rose)" in css
    assert ".st-key-operational_questionnaire_canvas" not in css.split(
        "border: 1px solid", 1
    )[0]
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_questionnaire_flow.py tests/test_operational_ui.py
```

Expected: failures because `questionnaire_progress_markup` and the new CSS
selectors do not exist.

- [ ] **Step 4: Implement validated questionnaire progress markup**

In `questionnaire_ui.py`, replace the plain context HTML with a pure helper and
keep `render_question_context` as the Streamlit boundary:

```python
def questionnaire_progress_markup(
    context_label: object, *, current: int, total: int
) -> str:
    if (
        type(current) is not int
        or type(total) is not int
        or total < 1
        or not 1 <= current <= total
    ):
        raise ValueError("questionnaire progress must be within the active flow")
    safe_context = html.escape(str(context_label), quote=True)
    percentage = current / total * 100
    return (
        '<section class="questionnaire-progress">'
        '<div class="questionnaire-progress__meta">'
        '<div><span class="questionnaire-progress__eyebrow">CURRENT PROMPT</span>'
        f'<strong>{safe_context}</strong></div>'
        f'<div class="questionnaire-progress__counter">{current:02d} '
        f'<span>/ {total:02d}</span></div></div>'
        '<div class="questionnaire-progress__track" role="progressbar" '
        f'aria-valuemin="1" aria-valuemax="{total}" aria-valuenow="{current}">'
        f'<span class="questionnaire-progress__fill" style="width: {percentage:g}%">'
        '</span></div></section>'
    )


def render_question_context(context_label: object, *, current: int, total: int) -> None:
    st.markdown(
        questionnaire_progress_markup(context_label, current=current, total=total),
        unsafe_allow_html=True,
    )
```

Do not change `state_keys`, `_mark_answered`, `_save_draft_at_step`, validation,
branching, callback order, reruns, or returned values. Task 3 adds the keyed
borderless container around the existing top-level `render_questionnaire`
call, avoiding a large indentation-only refactor inside this renderer.

- [ ] **Step 5: Add the approved questionnaire CSS**

In `operational_ui.py`, add scoped rules for a centered `960px` borderless
canvas, metadata/counter layout, rose progress fill, cyan prompt rule, larger
native labels, answer spacing, endpoint alignment, and a divided navigation
row. Add mobile stacking inside the existing `840px` media query. Use only the
existing palette variables and `4px` or `6px` control radii.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_questionnaire_flow.py tests/test_operational_ui.py tests/test_questionnaire_end_to_end.py
```

Expected: all selected tests pass with unchanged questionnaire behavior.

- [ ] **Step 7: Commit Task 1**

```powershell
git add questionnaire_ui.py operational_ui.py tests/test_questionnaire_flow.py tests/test_operational_ui.py
git commit -m "feat: refine operational questionnaire canvas"
```

### Task 2: Package And Completion Presentation Helpers

**Files:**
- Modify: `tests/test_operational_ui.py`
- Modify: `operational_ui.py`

- [ ] **Step 1: Write failing package and completion markup tests**

Add tests that require hostile filenames to be escaped and exact approved facts
to be present:

```python
def test_local_package_summary_is_escaped_and_local_only():
    markup = operational_ui.local_package_summary_markup(
        '<script>alert("x")</script>.zip'
    )
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert "LOCAL EXPORT" in markup
    assert "JSON + Excel" in markup
    assert "仅保存到本机" in markup
    assert 'class="operational-package"' in markup


def test_completion_confirmation_has_only_approved_outcomes():
    markup = operational_ui.completion_confirmation_markup()
    assert "本次会话已完成。" in markup
    assert "本地资料包已确认保存" in markup
    assert "问卷数据已从当前会话清理" in markup
    assert "未上传到应用服务器" in markup
    assert "现在可以安全关闭此页面。" in markup
    assert "subject" not in markup.casefold()
    assert "filename" not in markup.casefold()
```

- [ ] **Step 2: Write failing CSS and render-boundary tests**

Require `.operational-package`, `.operational-package__facts`,
`.operational-completion`, `.operational-completion__row`, desktop alignment,
and mobile fact stacking. Monkeypatch `operational_ui.st.markdown` to prove the
render helpers pass only their corresponding pure markup with
`unsafe_allow_html=True`.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_operational_ui.py
```

Expected: failures because the package/completion helpers and selectors are
absent.

- [ ] **Step 4: Implement the pure and Streamlit helpers**

In `operational_ui.py`, add:

```python
def local_package_summary_markup(filename: object) -> str:
    safe_filename = _escape(filename)
    return (
        '<section class="operational-package">'
        '<div class="operational-package__header">'
        '<div><span>LOCAL EXPORT</span><h2>问卷资料包已准备</h2></div>'
        '<strong>READY</strong></div>'
        f'<p class="operational-package__filename">{safe_filename}</p>'
        '<div class="operational-package__facts">'
        '<div><span>FORMAT</span><strong>ZIP</strong></div>'
        '<div><span>CONTENTS</span><strong>JSON + Excel</strong></div>'
        '<div><span>STORAGE</span><strong>仅保存到本机</strong></div>'
        '</div></section>'
    )


def render_local_package_summary(filename: object) -> None:
    st.markdown(local_package_summary_markup(filename), unsafe_allow_html=True)


def completion_confirmation_markup() -> str:
    return (
        '<section class="operational-completion">'
        '<div class="operational-completion__mark" aria-hidden="true">&#10003;</div>'
        '<h2>本次会话已完成。</h2>'
        '<p>本地资料包已由您确认保存，本页面中的本次会话数据已完成清理。</p>'
        '<div class="operational-completion__list">'
        '<div class="operational-completion__row"><span></span>'
        '<strong>本地资料包已确认保存</strong></div>'
        '<div class="operational-completion__row"><span></span>'
        '<strong>问卷数据已从当前会话清理</strong></div>'
        '<div class="operational-completion__row"><span></span>'
        '<strong>录制媒体未上传到应用服务器</strong></div>'
        '</div><p class="operational-completion__close">'
        '现在可以安全关闭此页面。</p></section>'
    )


def render_completion_confirmation() -> None:
    st.markdown(completion_confirmation_markup(), unsafe_allow_html=True)
```

The completion HTML must use a cyan completion mark, the exact completion
sentence, the three approved confirmation rows, and the close-page statement.
Do not accept record, identity, filename, or recording-state arguments.

- [ ] **Step 5: Add the approved package/completion CSS**

Use cyan top rules, thin neutral dividers, tabular file facts, rose package
readiness/primary hierarchy, and an open completion list. Scope widths with
`.st-key-operational_package_canvas` and
`.st-key-operational_completion_canvas`; do not add a surrounding card border.
Add single-column mobile fact rows inside the existing media query.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_operational_ui.py
```

Expected: all operational presentation tests pass.

- [ ] **Step 7: Commit Task 2**

```powershell
git add operational_ui.py tests/test_operational_ui.py
git commit -m "feat: add local package and completion surfaces"
```

### Task 3: Wire Stages 05 And 06 Without Changing Workflow

**Files:**
- Modify: `tests/test_app_integration.py`
- Modify: `app.py`

- [ ] **Step 1: Write failing stage-surface integration tests**

Extend the operational gate test and exact download test to require:

```python
assert 'class="operational-package"' in _visible_app_text(app)
assert "session-20260724-080910.zip" in _visible_app_text(app)
assert captured_download["type"] == "primary"
assert captured_download["icon"] == ":material/download:"
assert captured_download["use_container_width"] is True
```

After finish, require the completion markup and keep existing assertions that
download/questionnaire controls are absent and sensitive state is cleared:

```python
visible = _visible_app_text(app)
assert 'class="operational-completion"' in visible
assert "本次会话已完成。" in visible
assert "未上传到应用服务器" in visible
assert not app.get("download_button")
```

Add an AST/source contract that the stage 06 branch calls
`render_completion_confirmation` instead of `st.success`.

- [ ] **Step 2: Run focused integration tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_app_integration.py -k "operational_gate or download or finish or completion"
```

Expected: failures because stages 05/06 still use the unstructured controls and
default success alert.

- [ ] **Step 3: Wire stage 05 package canvas**

Import `render_local_package_summary` and `render_completion_confirmation` in
`app.py`. Wrap the existing top-level questionnaire call without changing any
of its arguments or returned values:

```python
with st.container(key="operational_questionnaire_canvas"):
    answers, questionnaire_complete = render_questionnaire(
        subject_id=safe_subject_id,
        intervention_day=int(record["intervention_day"]),
        answers=answers,
        save_draft=save_questionnaire_draft,
        visit=visit,
        state_namespace=state_namespace,
        initial_answered_field_ids=answered_by_visit.get(visit, []),
        initial_step=step_by_visit.get(visit, 0),
    )
```

In `_render_export_finalization`, preserve the existing checkpoint, download
data/name/MIME, checkbox key, disabled finish gate, and callback, but render
them inside:

```python
with st.container(key="operational_package_canvas"):
    render_operational_status(
        "checkpoint",
        "下载前请勿刷新或关闭页面，否则当前问卷内容将丢失。",
    )
    render_local_package_summary(bundle.filename)
    st.download_button(
        label="下载问卷记录（JSON + Excel）",
        data=bundle.data,
        file_name=bundle.filename,
        mime="application/zip",
        type="primary",
        icon=":material/download:",
        use_container_width=True,
    )
    saved_locally = st.checkbox(
        "我确认问卷 ZIP 已保存到本地",
        key=_SAVED_LOCALLY_KEY,
    )
    st.button(
        "完成本次会话",
        type="secondary",
        disabled=not saved_locally,
        on_click=_finish_current_session,
        key="operational_finish",
        use_container_width=True,
    )
```

Use the same keyed content width for export error and retry rendering without
changing retry state or `st.stop()` boundaries.

- [ ] **Step 4: Replace only the stage 06 presentation**

Keep `require_app_password`, `_COMPLETE_KEY`, `render_operational_stage(6)`, and
`st.stop()` unchanged. Replace `st.success` with:

```python
with st.container(key="operational_completion_canvas"):
    render_completion_confirmation()
```

- [ ] **Step 5: Update exact download expectations and verify GREEN**

Update captured keyword dictionaries only for the three approved presentation
arguments (`type`, `icon`, and `use_container_width`). Re-run:

```powershell
python -m pytest -q tests/test_app_integration.py
```

Expected: all integration tests pass with exact bundle bytes/schema and stage
gates unchanged.

- [ ] **Step 6: Commit Task 3**

```powershell
git add app.py tests/test_app_integration.py
git commit -m "feat: align local package and completion stages"
```

### Task 4: Full Regression And Visual Verification

**Files:**
- Modify only if a verified regression requires a scoped correction.

- [ ] **Step 1: Run the complete Python suite**

```powershell
python -m pytest -q
```

Expected: all tests pass; only the two established environment skips remain.

- [ ] **Step 2: Run recorder, compile, and diff checks**

```powershell
node --test tests/js/test_recorder_core.mjs
python -m compileall -q app.py app_workflow.py operational_ui.py questionnaire_ui.py browser_recorder.py
git diff --check
```

Expected: Node reports 44 passing tests; compile and diff checks exit zero.

- [ ] **Step 3: Inspect desktop and mobile layouts**

When the browser-control surface is available, inspect stages 04, 05, and 06
at `1440x900` and `390x844`. Confirm the question/answers remain visible,
progress semantics are present, facts stack on mobile, download and finish
commands do not overlap, focus is visible, and completion content aligns with
the stage heading. If browser control is unavailable, report that limitation
and do not claim interactive visual verification.

- [ ] **Step 4: Review the final delta against the design spec**

Check that no prompt, option, widget key, state key, ZIP argument, privacy
boundary, authentication gate, recorder behavior, or finish-clearing rule has
changed. Run:

```powershell
git diff 56d3208 -- app.py operational_ui.py questionnaire_ui.py tests
git status --short --branch
```

- [ ] **Step 5: Publish after verification**

Fetch `origin`, confirm `origin/main` is an ancestor, push the verified HEAD to
`main`, and confirm local HEAD equals `origin/main`. Do not force-push.
