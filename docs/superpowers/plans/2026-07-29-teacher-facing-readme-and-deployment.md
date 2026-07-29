# Teacher-Facing README And Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the approved six-stage Streamlit application together with a Chinese-first, teacher-facing GitHub README that shows the actual Stage 04–06 operational closure, the local-first data boundary, and one canonical complete-demo URL.

**Architecture:** Keep `app.py`, `operational_ui.py`, and `questionnaire_ui.py` behavior frozen at the already verified Stage 04–06 implementation. Treat `tools/generate_operational_readme_assets.py` as the only source for README image binaries, strengthen `tests/test_operational_readme.py` before changing public content, and publish the application and README from one verified commit lineage to `origin/main`.

**Tech Stack:** Markdown, Pillow 11.1 drawing primitives, Python 3.13, pytest, Streamlit 1.45.1, Node's built-in test runner, GitHub, Streamlit Community Cloud.

---

## File Map

- Modify `tests/test_operational_readme.py`: Chinese-first hierarchy, canonical URL, exact image inventory, Stage 04–06 copy, deterministic generation, and privacy contracts.
- Modify `tools/generate_operational_readme_assets.py`: faithful current Stage 04–06 drawings plus a teacher-facing closure overview and completion asset.
- Modify `README.md`: research-report narrative, actual application surfaces, method/data boundary, and compact operational details.
- Modify generated files under `assets/readme/`: regenerate all committed README images from the updated generator.
- Do not modify `app.py`, `operational_ui.py`, `questionnaire_ui.py`, questionnaire definitions/scoring, recorder code, export code, authentication, or state clearing unless a verified regression proves a narrowly scoped correction is required.

### Task 1: Lock The Teacher-Facing Public Contract

**Files:**
- Modify: `tests/test_operational_readme.py`
- Test: `tests/test_operational_readme.py`

- [ ] **Step 1: Extend the exact public constants**

Add the canonical application URL and the two approved new generated assets near the existing constants:

```python
APPLICATION_URL = (
    "https://physical-stimulation-session-recorder-"
    "lqtdzyddneawgtmkzviryt.streamlit.app/"
)

EXPECTED_ASSETS = {
    "operational-workflow.gif": (1440, 810),
    "operational-workflow-static.webp": (1440, 810),
    "questionnaire-experience.webp": (1440, 810),
    "local-recording-save.webp": (1440, 810),
    "local-response-export.webp": (1440, 810),
    "completion-confirmation.webp": (1440, 810),
    "structured-response-closure.webp": (1440, 810),
    "operational-palette.webp": (1440, 160),
}
```

Keep `EXPECTED_README_IMAGE_TARGETS` derived from every asset except the palette image.

- [ ] **Step 2: Replace the old English-first hierarchy assertions**

Replace `test_readme_leads_with_stage_overview_and_prioritizes_questionnaire` with:

```python
def test_readme_is_chinese_first_research_report_with_one_complete_demo_url() -> None:
    readme = _readme()
    first_viewport = readme.split("## 实际界面与操作闭环", 1)[0]

    assert first_viewport.startswith("# 物理刺激干预会话伴侣")
    assert "Physical Stimulation Intervention Session Companion" in first_viewport
    assert "六阶段" in first_viewport
    assert "本地录制与导出" in first_viewport
    assert "无媒体上传路径" in first_viewport
    assert "assets/readme/operational-workflow.gif" in first_viewport
    assert "assets/readme/operational-workflow-static.webp" in first_viewport
    assert readme.count(APPLICATION_URL) == 1
    assert "https://physical-stimulation-session-recorder.streamlit.app" not in readme


def test_readme_shows_current_recording_questionnaire_package_and_completion() -> None:
    readme = _readme()
    section = readme.split("## 实际界面与操作闭环", 1)[1].split(
        "## 方法与数据边界", 1
    )[0]

    expected_targets = (
        "assets/readme/local-recording-save.webp",
        "assets/readme/structured-response-closure.webp",
        "assets/readme/questionnaire-experience.webp",
        "assets/readme/local-response-export.webp",
        "assets/readme/completion-confirmation.webp",
    )
    assert all(target in section for target in expected_targets)
    assert section.index("03 本地录制") < section.index("04 分步结构化作答")
    assert section.index("04 分步结构化作答") < section.index("05 本地资料包")
    assert section.index("05 本地资料包") < section.index("06 完成确认")
    assert "过去 24 小时，是否出现过不想死但想故意伤害自己的想法？" in section
    assert "JSON + Excel" in section
    assert "未上传到应用服务器" in section
```

- [ ] **Step 3: Update generator-copy contracts for current Stage 04–06 surfaces**

Replace the old handoff-only tuples with exact current copy:

```python
QUESTIONNAIRE_COPY = (
    "CURRENT PROMPT",
    "过去 24 小时，是否出现过不想死但想故意伤害自己的想法？",
    "否",
    "是",
)
PACKAGE_COPY = (
    "LOCAL EXPORT",
    "问卷资料包已准备",
    "session-20260729-103000.zip",
    "JSON + Excel",
    "仅保存到本机",
    "我确认问卷 ZIP 已保存到本地",
)
COMPLETION_COPY = (
    "本次会话已完成。",
    "本地资料包已确认保存",
    "问卷数据已从当前会话清理",
    "录制媒体未上传到应用服务器",
    "现在可以安全关闭此页面。",
)
```

Update `test_generator_declares_exact_labels_palette_and_handoff_copy` so each tuple is checked only inside its corresponding `_draw_questionnaire`, `_draw_export`, or `_draw_completion` function source. Also require `def draw_structured_response_closure` and each of `"04"`, `"05"`, and `"06"` inside that function's source slice.

- [ ] **Step 4: Strengthen public safety without hiding the approved representative prompt**

Keep `PROTECTED_SUBSTRING_SIGNATURES` unchanged. The selected representative prompt deliberately avoids the forbidden literal study terms while showing the real visible question. Add:

```python
def test_public_readme_uses_only_the_approved_visible_question() -> None:
    readme = _readme()
    assert readme.count(
        "过去 24 小时，是否出现过不想死但想故意伤害自己的想法？"
    ) == 1
    assert "全部题目" not in readme
    assert "完整题库" not in readme
    assert re.search(r"\bsub-\d{3,}\b", readme, flags=re.IGNORECASE) is None
```

- [ ] **Step 5: Run the focused contract and verify RED**

Run:

```powershell
python -m pytest -q tests/test_operational_readme.py
```

Expected: failures for the two missing assets, old English-first title, old application URL, absent Stage 04–06 section/copy, and generator functions that still depict the previous surfaces. Existing deterministic and safety tests must still collect normally.

- [ ] **Step 6: Commit the RED contract**

```powershell
git add tests/test_operational_readme.py
git commit -m "test: specify teacher-facing README presentation"
```

### Task 2: Update The Reproducible Visual Asset Generator

**Files:**
- Modify: `tools/generate_operational_readme_assets.py`
- Test: `tests/test_operational_readme.py`

- [ ] **Step 1: Keep the shared shell and replace only Stage 04–06 drawings**

Retain `draw_header`, `draw_progress_rail`, `draw_workspace_header`, the Stage 01–03 renderers, palette, GIF durations, font fallback, and lossless WEBP output. Replace `_draw_questionnaire` with an open-canvas drawing that uses the actual visible prompt and exact current hierarchy:

```python
def _draw_questionnaire(draw: ImageDraw.ImageDraw) -> None:
    draw.text((454, 326), "CURRENT PROMPT", font=font(13, True), fill=COLORS["rose"])
    draw.text((454, 358), "过去 24 小时", font=font(20, True), fill=COLORS["navy"])
    draw.text((1306, 344), "01 / 08", font=font(20, True), fill=COLORS["navy"], anchor="ra")
    draw.rounded_rectangle((454, 396, 1306, 402), radius=3, fill=COLORS["line"])
    draw.rounded_rectangle((454, 396, 560, 402), radius=3, fill=COLORS["rose"])
    draw.rectangle((454, 438, 458, 532), fill=COLORS["cyan"])
    draw.multiline_text(
        (478, 438),
        "过去 24 小时，是否出现过不想死但想故意\n伤害自己的想法？",
        font=font(24, True),
        fill=COLORS["navy"],
        spacing=10,
    )
    for index, label in enumerate(("否", "是")):
        top = 558 + index * 60
        rounded_box(
            draw,
            (478, top, 1306, top + 48),
            fill=COLORS["paper"],
            outline=COLORS["violet"],
            radius=4,
        )
        draw.ellipse((500, top + 14, 520, top + 34), outline=COLORS["violet"], width=2)
        draw.text((540, top + 10), label, font=font(18, True), fill=COLORS["navy"])
```

- [ ] **Step 2: Replace the Stage 05 package drawing**

Implement the current open package summary without a surrounding card:

```python
def _draw_export(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((454, 326, 1306, 330), fill=COLORS["cyan"])
    draw.text((454, 354), "LOCAL EXPORT", font=font(13, True), fill=COLORS["rose"])
    draw.text((454, 386), "问卷资料包已准备", font=font(28, True), fill=COLORS["navy"])
    rounded_box(draw, (1184, 354, 1306, 390), fill=COLORS["cyan"], radius=18)
    _centered_text(draw, (1184, 354, 1306, 390), "READY", face=font(13, True), fill=COLORS["navy"])
    draw.line((454, 430, 1306, 430), fill=COLORS["line"], width=1)
    draw.text((454, 454), "session-20260729-103000.zip", font=font(17), fill=COLORS["violet"])
    facts = (("FORMAT", "ZIP"), ("CONTENTS", "JSON + Excel"), ("STORAGE", "仅保存到本机"))
    for index, (label, value) in enumerate(facts):
        left = 454 + index * 284
        draw.text((left, 506), label, font=font(12, True), fill=COLORS["muted"])
        draw.text((left, 536), value, font=font(18, True), fill=COLORS["navy"])
    draw_button(draw, (454, 592, 1306, 644), "下载问卷记录（JSON + Excel）", fill=COLORS["rose"])
    draw.text((454, 670), "□  我确认问卷 ZIP 已保存到本地", font=font(17, True), fill=COLORS["navy"])
```

- [ ] **Step 3: Replace the Stage 06 completion drawing**

Use the current open confirmation list and exact privacy copy:

```python
def _draw_completion(draw: ImageDraw.ImageDraw) -> None:
    draw.ellipse((454, 330, 518, 394), fill=COLORS["cyan"])
    _check(draw, 474, 349, COLORS["navy"], scale=2)
    draw.text((546, 332), "本次会话已完成。", font=font(30, True), fill=COLORS["navy"])
    draw.text((546, 376), "本地资料包已确认保存，当前会话数据已完成清理。", font=font(16), fill=COLORS["muted"])
    draw.rectangle((454, 438, 1306, 442), fill=COLORS["cyan"])
    rows = (
        "本地资料包已确认保存",
        "问卷数据已从当前会话清理",
        "录制媒体未上传到应用服务器",
    )
    for index, label in enumerate(rows):
        top = 468 + index * 62
        _check(draw, 470, top + 5, COLORS["cyan"])
        draw.text((510, top), label, font=font(19, True), fill=COLORS["navy"])
        draw.line((454, top + 42, 1306, top + 42), fill=COLORS["line"], width=1)
    draw.text((454, 676), "现在可以安全关闭此页面。", font=font(17, True), fill=COLORS["violet"])
```

- [ ] **Step 4: Add the teacher-facing Stage 04–06 closure overview**

Add `draw_structured_response_closure()` that creates a fresh `1440 x 810` RGB canvas from drawing primitives. Use three equal columns with exact titles `04 分步结构化作答`, `05 本地资料包`, and `06 完成确认`; within them draw the rose progress/cyan prompt rule, ZIP facts/download, and completion checklist respectively. Use `rounded_box(... radius=6)` for controls, no card nesting, and a shared top caption:

```python
def draw_structured_response_closure() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["mist"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 106), fill=COLORS["navy"])
    draw.text((54, 30), "STRUCTURED RESPONSE CLOSURE", font=font(20, True), fill=COLORS["paper"])
    draw.text((54, 64), "结构化作答、本地资料包与完成确认", font=font(18), fill="#C9CAE0")
    columns = (
        (54, 134, 478, 746, "04", "分步结构化作答", COLORS["rose"]),
        (508, 134, 932, 746, "05", "本地资料包", COLORS["cyan"]),
        (962, 134, 1386, 746, "06", "完成确认", COLORS["cyan"]),
    )
    for left, top, right, bottom, number, title, accent in columns:
        draw.rectangle((left, top, right, top + 4), fill=accent)
        draw.text((left, top + 22), number, font=font(15, True), fill=COLORS["violet"])
        draw.text((left + 46, top + 18), title, font=font(20, True), fill=COLORS["navy"])
        draw.line((left, top + 60, right, top + 60), fill=COLORS["line"], width=1)

    draw.text((78, 224), "CURRENT PROMPT", font=font(11, True), fill=COLORS["rose"])
    draw.text((442, 220), "01 / 08", font=font(13, True), fill=COLORS["navy"], anchor="ra")
    draw.rounded_rectangle((78, 254, 442, 260), radius=3, fill=COLORS["line"])
    draw.rounded_rectangle((78, 254, 126, 260), radius=3, fill=COLORS["rose"])
    draw.rectangle((78, 292, 82, 394), fill=COLORS["cyan"])
    draw.multiline_text(
        (98, 292),
        "过去 24 小时，是否出现过\n不想死但想故意伤害自己的想法？",
        font=font(17, True),
        fill=COLORS["navy"],
        spacing=8,
    )
    for index, label in enumerate(("否", "是")):
        top = 430 + index * 58
        rounded_box(draw, (98, top, 442, top + 44), fill=COLORS["paper"], outline=COLORS["violet"], radius=4)
        draw.ellipse((116, top + 12, 136, top + 32), outline=COLORS["violet"], width=2)
        draw.text((154, top + 8), label, font=font(16, True), fill=COLORS["navy"])

    draw.text((532, 224), "LOCAL EXPORT", font=font(11, True), fill=COLORS["rose"])
    draw.text((532, 256), "问卷资料包已准备", font=font(20, True), fill=COLORS["navy"])
    draw.text((532, 302), "session-20260729-103000.zip", font=font(13), fill=COLORS["violet"])
    facts = (("FORMAT", "ZIP"), ("CONTENTS", "JSON + Excel"), ("STORAGE", "仅保存到本机"))
    for index, (label, value) in enumerate(facts):
        top = 356 + index * 58
        draw.text((532, top), label, font=font(10, True), fill=COLORS["muted"])
        draw.text((648, top - 3), value, font=font(15, True), fill=COLORS["navy"])
        draw.line((532, top + 34, 908, top + 34), fill=COLORS["line"], width=1)
    draw_button(draw, (532, 552, 908, 600), "下载问卷记录", fill=COLORS["rose"])
    draw.text((532, 630), "□  我确认问卷 ZIP 已保存到本地", font=font(14, True), fill=COLORS["navy"])

    draw.ellipse((986, 218, 1042, 274), fill=COLORS["cyan"])
    _check(draw, 1002, 234, COLORS["navy"], scale=2)
    draw.text((1062, 224), "本次会话已完成。", font=font(20, True), fill=COLORS["navy"])
    draw.rectangle((986, 310, 1362, 314), fill=COLORS["cyan"])
    completion_rows = (
        "本地资料包已确认保存",
        "问卷数据已从当前会话清理",
        "录制媒体未上传到应用服务器",
    )
    for index, label in enumerate(completion_rows):
        top = 354 + index * 76
        _check(draw, 998, top + 4, COLORS["cyan"])
        draw.text((1034, top), label, font=font(15, True), fill=COLORS["navy"])
        draw.line((986, top + 42, 1362, top + 42), fill=COLORS["line"], width=1)
    draw.text((986, 616), "现在可以安全关闭此页面。", font=font(15, True), fill=COLORS["violet"])
    return image
```

Do not call `Image.open`, read project files, use network operations, or ingest screenshots.

- [ ] **Step 5: Save the new assets from `generate_assets`**

Keep all existing outputs and add:

```python
_save_webp(frames[5], ASSET_DIR / "completion-confirmation.webp")
_save_webp(
    draw_structured_response_closure(),
    ASSET_DIR / "structured-response-closure.webp",
)
```

- [ ] **Step 6: Run the generator tests and verify generator GREEN**

Run:

```powershell
python -m pytest -q tests/test_operational_readme.py -k "generator or asset or animation"
```

Expected: generation/safety tests pass against temporary output; README hierarchy tests still fail because `README.md` and committed assets are not updated yet.

- [ ] **Step 7: Commit the generator implementation**

```powershell
git add tools/generate_operational_readme_assets.py
git commit -m "feat: draw current questionnaire closure assets"
```

### Task 3: Rewrite The README Around The Research Report Narrative

**Files:**
- Modify: `README.md`
- Test: `tests/test_operational_readme.py`

- [ ] **Step 1: Replace the first viewport with the approved Chinese-first header**

Start `README.md` with this exact structure:

```markdown
# 物理刺激干预会话伴侣

**Physical Stimulation Intervention Session Companion**

面向居家物理刺激干预研究的六阶段受控会话工具：从受控进入、本地音视频和结构化作答，到本地资料包与完成确认，让每一步操作和数据边界都清楚可见。

[打开完整演示 / Open the complete demo](https://physical-stimulation-session-recorder-lqtdzyddneawgtmkzviryt.streamlit.app/)

| 06 阶段流程 | 本地录制与导出 | 无媒体上传路径 |
| --- | --- | --- |
| 从进入到完成确认 | WebM 与 JSON + Excel ZIP | 录制媒体保留在 Chrome 本地 |

![六阶段研究会话工作流](assets/readme/operational-workflow.gif)

<details>
<summary>查看静态流程图 / Static workflow fallback</summary>

![六阶段研究会话静态流程图](assets/readme/operational-workflow-static.webp)

</details>
```

Follow it with the existing six-stage table, changing headers and cell order to Chinese first with English after a slash. Preserve all six completion semantics.

- [ ] **Step 2: Add the actual application closure section**

Insert immediately after the stage table:

```markdown
## 实际界面与操作闭环

### 03 本地录制 / Browser-local recording

![浏览器本地录制、回放、下载与确认](assets/readme/local-recording-save.webp)

摄像头预览、录制、回放和 WebM 下载都在当前 Chrome 中完成。只有在主持者检查画面与声音并确认结果后，流程才进入问卷；跳过或不可用时使用明确的“不保存本次录制”路径。

![04 至 06 的结构化作答闭环](assets/readme/structured-response-closure.webp)

### 04 分步结构化作答 / Stepwise questionnaire

![分步结构化作答页面](assets/readme/questionnaire-experience.webp)

代表性实际题目：**过去 24 小时，是否出现过不想死但想故意伤害自己的想法？** 页面一次只呈现一个步骤，按需显示后续问题，并保留必答检查；参与者页面不显示分数或解释。

### 05 本地资料包 / Local response package

![本地 JSON 与 Excel 问卷资料包](assets/readme/local-response-export.webp)

问卷结果生成一个本地 **JSON + Excel ZIP**。用户下载并找到文件后，必须确认“我确认问卷 ZIP 已保存到本地”，完成按钮才会解锁。

### 06 完成确认 / Completion confirmation

![会话完成与本地隐私确认](assets/readme/completion-confirmation.webp)

完成页确认本地资料包已保存、问卷数据已从当前会话清理，并明确说明录制媒体**未上传到应用服务器**。现在可以安全关闭页面。
```

- [ ] **Step 3: Make method and privacy the next main section**

Rename the privacy section to `## 方法与数据边界 / Method and data boundary`. Keep the current Mermaid nodes and edges because they encode the tested boundary. Precede it with two concise Chinese bullets and follow it with one English summary paragraph:

```markdown
- 摄像头和麦克风数据只进入 Chrome 本地录制器，用户自行保存 WebM。
- 当日状态和问卷值只在活动会话的临时内存中用于生成本地 ZIP，应用不把服务器作为持久响应档案。
```

Do not add server upload, storage, database, score, risk-label, or identity claims.

- [ ] **Step 4: Add verification evidence and compact the operational details**

Add before the details blocks:

```markdown
## 验证证据 / Verification

- 六阶段门禁、认证边界与会话状态清理
- 问卷分支、必答检查、进度语义与支持信息
- ZIP 字节、文件名、MIME、本地下载和保存确认
- 浏览器本地录制器状态机、媒体清理与无网络能力边界
- README 资产、尺寸、链接、可复现生成和公开内容安全合同
```

Move the Chrome guide and troubleshooting table into one details block titled `Chrome 操作与故障排查 / Chrome guide and troubleshooting`. Keep separate details blocks for local setup, Streamlit deployment/secret key names, and verification commands. Keep the final showcase reference text-only and after the last README image.

- [ ] **Step 5: Run the README text tests and verify README GREEN**

Run:

```powershell
python -m pytest -q tests/test_operational_readme.py -k "readme or public_contract"
```

Expected: text hierarchy, exact URL, method boundary, section order, and public safety assertions pass. Asset inventory tests may still fail until committed binaries are regenerated.

- [ ] **Step 6: Commit the README narrative**

```powershell
git add README.md
git commit -m "docs: present the six-stage research workflow"
```

### Task 4: Generate, Inspect, And Commit The Public Assets

**Files:**
- Modify generated files under: `assets/readme/`
- Test: `tests/test_operational_readme.py`

- [ ] **Step 1: Regenerate every committed asset from the updated generator**

Run:

```powershell
python tools/generate_operational_readme_assets.py
```

Expected: the existing six assets are deterministically replaced and the two new WEBP assets are created. No other files appear under `assets/readme/`.

- [ ] **Step 2: Run the full README contract**

```powershell
python -m pytest -q tests/test_operational_readme.py
```

Expected: every README, generator, inventory, GIF, dimension, deterministic, safety, and metadata test passes. The showcase-clone comparison may use its established environment skip when that clone is absent.

- [ ] **Step 3: Inspect every changed image**

Use `view_image` on:

```text
assets/readme/operational-workflow-static.webp
assets/readme/questionnaire-experience.webp
assets/readme/local-recording-save.webp
assets/readme/local-response-export.webp
assets/readme/completion-confirmation.webp
assets/readme/structured-response-closure.webp
```

Check that Chinese text renders without replacement glyphs, Stage 04 prompt and options fit, Stage 05 filename/facts/buttons do not overlap, Stage 06 rows remain readable, the three overview panels share alignment, and no text is clipped at `1440 x 810`.

- [ ] **Step 4: Confirm exact asset inventory and metadata**

Run:

```powershell
python -c "from pathlib import Path; from PIL import Image; root=Path('assets/readme'); [(print(p.name, Image.open(p).size, Image.open(p).format)) for p in sorted(root.iterdir()) if p.is_file()]"
git diff --check
```

Expected: eight exact assets, seven `1440 x 810` presentation images plus one `1440 x 160` palette, GIF only for the workflow, WEBP for the rest, and no diff errors.

- [ ] **Step 5: Commit the generated binaries and final contract**

```powershell
git add assets/readme tests/test_operational_readme.py
git commit -m "docs: add current application presentation assets"
```

### Task 5: Full Regression, Publish, And Verify The Public Entry

**Files:**
- Modify only if a verified regression requires a scoped correction.

- [ ] **Step 1: Run the complete automated matrix on the final HEAD**

Run in parallel where possible:

```powershell
python -m pytest -q
node --test tests/js/test_recorder_core.mjs
python -m compileall -q app.py app_workflow.py operational_ui.py questionnaire_ui.py browser_recorder.py tools/generate_operational_readme_assets.py
git diff --check
```

Expected: all Python tests pass with only the established environment skips, Node reports 44 passing recorder tests, compile exits zero, and diff check is clean.

- [ ] **Step 2: Review the complete public delta**

Run:

```powershell
git diff 4acc0e2..HEAD -- app.py operational_ui.py questionnaire_ui.py requirements.txt README.md tools/generate_operational_readme_assets.py assets/readme tests
git status --short --branch
```

Verify no question definitions, scoring, recorder behavior, ZIP schema/bytes, auth, privacy boundary, or session-clearing behavior changed. Confirm the worktree is clean.

- [ ] **Step 3: Verify the local application and public README target before push**

Check the local server health and the canonical deployed URL without exposing credentials:

```powershell
curl.exe --silent --show-error --max-time 10 http://127.0.0.1:8502/_stcore/health
curl.exe --silent --show-error --head --max-time 20 https://physical-stimulation-session-recorder-lqtdzyddneawgtmkzviryt.streamlit.app/
```

Expected: local health returns `ok`; the public URL returns a valid Streamlit response or its controlled Streamlit authentication redirect, not DNS failure or `404`.

- [ ] **Step 4: Fetch and publish the verified HEAD to `main` without force**

```powershell
git fetch origin
git merge-base --is-ancestor origin/main HEAD
git push origin HEAD:main
```

Expected: ancestry check exits zero and the push is a fast-forward. If origin moved and ancestry fails, stop, inspect the new commits, integrate them normally, rerun the complete matrix, and only then push. Never force-push.

- [ ] **Step 5: Confirm GitHub and Streamlit received the synchronized version**

```powershell
$remoteMain = git ls-remote origin refs/heads/main
$localHead = git rev-parse HEAD
$remoteMain
$localHead
curl.exe --silent --show-error --location --max-time 30 https://raw.githubusercontent.com/YaoZeLiu0417/physical-stimulation-session-recorder/main/README.md
```

Expected: remote `main` SHA equals local HEAD and the raw README begins with `# 物理刺激干预会话伴侣`. Recheck the Streamlit URL after deployment; an authentication redirect is acceptable, while an application build error is not.

- [ ] **Step 6: Report the published result and residual visual limitation**

Report the final SHA, GitHub repository URL, complete-demo URL, exact Python/Node counts, and whether browser automation was available for real deployed screenshots. Do not claim desktop/mobile interactive inspection if the browser-control surface remained unavailable.
