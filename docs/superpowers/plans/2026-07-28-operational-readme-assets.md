# Operational README Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the operational repository's technical-first README with an Alto-inspired teacher presentation and a fully original local animation and image set.

**Architecture:** A deterministic Pillow generator owns the six new bitmap assets under `assets/readme/`. A dedicated pytest contract validates image dimensions, animation, local references, confidentiality, and non-reuse; the README consumes only those local assets and keeps technical instructions secondary.

**Tech Stack:** Python 3.10, Pillow through Streamlit dependencies, GIF, WebP, GitHub-flavored Markdown, pytest 8.

---

### Task 1: Visual asset and README contract

**Files:**
- Create: `tests/test_operational_readme.py`
- Test: `README.md`
- Test: `assets/readme/*`

- [ ] **Step 1: Write the failing asset inventory test**

Define:

```python
ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "assets" / "readme"
EXPECTED_ASSETS = {
    "operational-workflow.gif": (1440, 810),
    "operational-workflow-static.webp": (1440, 810),
    "questionnaire-experience.webp": (1440, 810),
    "local-recording-save.webp": (1440, 810),
    "local-response-export.webp": (1440, 810),
    "operational-palette.webp": (1440, 160),
}
```

Assert exact inventory, successful Pillow decoding, expected dimensions, an
animated GIF with at least six frames, and GIF size below 5 MiB.

- [ ] **Step 2: Write the failing README and non-reuse tests**

Require the README to reference every expected asset with a relative
`assets/readme/...` target. Reject `raw.githubusercontent.com` and any Markdown
or HTML image source containing `physical-stimulation-session-recorder-showcase`.
Require the product title, six approved stage labels, questionnaire-first
section ordering, no-score copy, local-media copy, local JSON + Excel copy, and
collapsed technical details.

When the sibling showcase clone exists, SHA-256 every file under its `assets/`
directory and assert no operational asset has an identical digest. Scan README
and image metadata for credential signatures, participant identifiers, actual
instrument identifiers, and the confidential intervention acronym.

- [ ] **Step 3: Run the test and verify RED**

Run: `python -m pytest tests/test_operational_readme.py -q`

Expected: failure because `assets/readme/` and the new README structure do not
exist and the current README hotlinks a showcase GIF.

### Task 2: Deterministic original asset generator

**Files:**
- Create: `tools/generate_operational_readme_assets.py`
- Create: `assets/readme/operational-workflow.gif`
- Create: `assets/readme/operational-workflow-static.webp`
- Create: `assets/readme/questionnaire-experience.webp`
- Create: `assets/readme/local-recording-save.webp`
- Create: `assets/readme/local-response-export.webp`
- Create: `assets/readme/operational-palette.webp`

- [ ] **Step 1: Implement the drawing primitives**

Use Pillow with fixed colors and dimensions:

```python
WIDTH, HEIGHT = 1440, 810
COLORS = {
    "navy": "#000035",
    "violet": "#2D2674",
    "rose": "#DD1D86",
    "cyan": "#33B0E4",
    "peach": "#FFBC7D",
    "paper": "#FFFFFF",
    "mist": "#F4F5F7",
}
STAGES = (
    ("01", "Controlled access", "受控进入"),
    ("02", "Daily context", "当日状态"),
    ("03", "Browser-local recording", "本地音视频"),
    ("04", "Stepwise questionnaire", "分步结构化作答"),
    ("05", "Local response package", "本地资料包"),
    ("06", "Completion confirmation", "完成确认"),
)
```

Implement `font(size, bold=False)`, `rounded_box`, `draw_progress_rail`,
`draw_header`, `draw_button`, and `draw_footer`. Use Microsoft YaHei on Windows,
with deterministic Arial/DejaVu fallbacks for Latin text. Save without EXIF,
XMP, comments, or embedded paths.

- [ ] **Step 2: Implement six original operational scenes**

Implement `draw_scene(stage_index)` with the same rail and canvas. Render only
neutral operational concepts: controlled entry, generic context confirmation,
browser-local recorder preview, one neutral response control with applicable
follow-up copy, JSON/XLSX local package, and completion. Use no actual item text,
scores, participant IDs, filenames, or credentials.

- [ ] **Step 3: Export GIF, static fallback, detail frames, and palette**

Generate six RGB frames, quantize with Pillow adaptive palettes, and save:

```python
frames[0].save(
    gif_path,
    save_all=True,
    append_images=frames[1:],
    duration=(1800, 1800, 2200, 2200, 2000, 2600),
    loop=0,
    optimize=True,
    disposal=2,
)
```

Save first frame and the three approved detail frames as lossless WebP at
1440 x 810. Draw the five equal palette swatches in a 1440 x 160 WebP.

- [ ] **Step 4: Run generator and inspect assets**

Run: `python tools/generate_operational_readme_assets.py`

Open the GIF, static fallback, questionnaire, recording, export, and palette
with the local image viewer. Check legibility, consistent framing, exact colors,
no overlap, and no confidential text.

### Task 3: Alto-inspired operational README

**Files:**
- Modify: `README.md`
- Test: `tests/test_operational_readme.py`

- [ ] **Step 1: Replace the first viewport**

Lead with the product name, a concise bilingual description, the controlled app
link, `assets/readme/operational-workflow.gif`, a static fallback link, and a
six-stage table. Do not use badges, custom CSS, remote images, or marketing hero
cards.

- [ ] **Step 2: Put the questionnaire experience before recording**

Add a bilingual questionnaire section with
`assets/readme/questionnaire-experience.webp`, covering one-step focus,
applicable follow-ups, completion checks, direct support copy, and no
participant-facing score. Do not name instruments or reproduce item wording.

- [ ] **Step 3: Present local recording and export**

Use `local-recording-save.webp` and `local-response-export.webp`. Explain the
host-level confirmation button, browser-local WebM, transient Streamlit session
memory, local JSON/XLSX ZIP, and explicit local-save confirmations.

- [ ] **Step 4: Add privacy, design, Chrome, and collapsed technical sections**

Add an accurate Mermaid data-boundary diagram, the local palette image, a short
Chrome workflow, troubleshooting, and `<details>` sections for local setup,
Streamlit deployment, secrets key names, and verification commands. Keep the
showcase repository as a text-only reference link at the end.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_operational_readme.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add README.md assets/readme tools/generate_operational_readme_assets.py tests/test_operational_readme.py
git commit -m "docs: rebuild operational readme experience"
```

### Task 4: Final validation and publication

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run focused and full regression checks**

Run:

```powershell
python -m pytest tests/test_operational_readme.py tests/test_showcase_audit.py -q
python -m pytest -q
python -m py_compile tools/generate_operational_readme_assets.py
git diff --check origin/main..HEAD
```

Expected: zero failures and zero diff-check output.

- [ ] **Step 2: Independently inspect visual output**

View each WebP at original resolution. Extract all GIF frames and build a contact
sheet for one-pass inspection. Verify the first and last frames, stage order,
text fit, stable layout, local image references, and file size.

- [ ] **Step 3: Publish without force**

Fetch `origin/main`, confirm it is an ancestor of `HEAD`, then run
`git push origin HEAD:main`. Retry transient errors after seven seconds without
force. Verify local, tracked, and GitHub API SHAs match.
