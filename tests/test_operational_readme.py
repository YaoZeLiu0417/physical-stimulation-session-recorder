import ast
import hashlib
import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image, __version__ as PILLOW_VERSION


ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
GENERATOR_PATH = ROOT / "tools" / "generate_operational_readme_assets.py"
ASSET_ROOT = ROOT / "assets" / "readme"
TEST_PATH = Path(__file__).resolve()
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
EXPECTED_README_IMAGE_TARGETS = {
    f"assets/readme/{name}"
    for name in EXPECTED_ASSETS
    if name != "operational-palette.webp"
}
EXPECTED_STAGE_LABELS = (
    ("Controlled access", "受控进入"),
    ("Daily context", "当日状态"),
    ("Browser-local recording", "本地音视频"),
    ("Stepwise questionnaire", "分步结构化作答"),
    ("Local response package", "本地资料包"),
    ("Completion confirmation", "完成确认"),
)
EXPECTED_PALETTE = ("#000035", "#2D2674", "#DD1D86", "#33B0E4", "#FFBC7D")
EXPECTED_DURATIONS = (1800, 1800, 2200, 2200, 2000, 2600)
REFERENCE_PILLOW_VERSION = "11.1.0"
REFERENCE_WINDOWS_FONTS = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
)
RECORDING_HANDOFF_COPY = (
    "下载 WebM",
    "打开本机已保存文件",
    "检查画面和声音",
    "确认",
)
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
SHOWCASE_URL = (
    "https://github.com/YaoZeLiu0417/"
    "physical-stimulation-session-recorder-showcase"
)
PROTECTED_SUBSTRING_SIGNATURES = (
    (5, "9fe0e5e2d659c9a9236ad60b31eeb73f49459c107b623bf173fae3d120ec7ecf"),
    (4, "a05bd3d07c5ddfb3b3768050941b3be057e60639524b775d62677e74a4c1051d"),
    (4, "b913c9d942bca73f56aa0816875f3edfa808e319eb6e75cf35faeb858e8e2dfc"),
    (4, "16402aedcbef4d634fb0b20dfc882f4d9efbcb4bd42341a09c3444170fbafc3a"),
    (4, "fb61a292870e8a7c2ec4a145024364e9b785b0b69b39960fdaceff1f0c236f02"),
    (2, "1379f06040a1706ad95e26ffbb88821610f0a39c571e4bcf6097787f47589056"),
    (2, "58fcfccb0ddfbd75143f7a15a6278ebd4f5a266a67e149de5ffec2a1851e6185"),
    (4, "7a0b7d4216b6d1e7121ba1c2ebee32894fffe587de5c65452ec29e680c5d0214"),
)
CREDENTIAL_PATTERN = re.compile(
    r"BEGIN (?:RSA|OPENSSH|EC|DSA) PRIVATE KEY"
    r"|AKIA[0-9A-Z]{16}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|ghp_[A-Za-z0-9]{36}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|AC[a-fA-F0-9]{32}"
)


def _readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


def _generator_source() -> str:
    return GENERATOR_PATH.read_text(encoding="utf-8")


def _function_node(source: str, function_name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    assert len(matches) == 1, (
        f"expected exactly one top-level function named {function_name!r}"
    )
    return matches[0]


def _function_source(source: str, function_name: str) -> str:
    node = _function_node(source, function_name)
    assert node.end_lineno is not None
    return "\n".join(source.splitlines()[node.lineno - 1 : node.end_lineno])


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _assert_chinese_first_bilingual_cell(
    value: str,
    *,
    expected_chinese: str | None = None,
) -> None:
    parts = _normalize_whitespace(value).split(" / ")
    assert len(parts) == 2, f"expected one Chinese / English separator in {value!r}"
    chinese, english = parts
    assert re.match(r"[\u3400-\u9fff]", chinese), (
        f"expected Chinese-first cell, got {value!r}"
    )
    if expected_chinese is not None:
        assert chinese == expected_chinese
    assert re.search(r"[A-Za-z]", english), f"expected English translation in {value!r}"


class _RecordingDraw:
    def __init__(self) -> None:
        self.rendered: list[str] = []

    def text(
        self,
        xy: object,
        text: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        self.rendered.append(text)

    def multiline_text(
        self,
        xy: object,
        text: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        self.rendered.append(text)

    def textbbox(
        self,
        xy: object,
        text: str,
        *args: object,
        **kwargs: object,
    ) -> tuple[int, int, int, int]:
        lines = text.splitlines() or [""]
        return (0, 0, max(1, max(map(len, lines))) * 10, len(lines) * 20)

    def rounded_rectangle(self, *args: object, **kwargs: object) -> None:
        pass

    def rectangle(self, *args: object, **kwargs: object) -> None:
        pass

    def line(self, *args: object, **kwargs: object) -> None:
        pass

    def ellipse(self, *args: object, **kwargs: object) -> None:
        pass

    def arc(self, *args: object, **kwargs: object) -> None:
        pass

    def polygon(self, *args: object, **kwargs: object) -> None:
        pass


def _assert_rendered_copy_in_order(
    rendered: list[str],
    expected: tuple[str, ...],
) -> None:
    normalized_rendered = [_normalize_whitespace(value) for value in rendered]
    previous_index = -1
    for expected_value in expected:
        normalized_expected = _normalize_whitespace(expected_value)
        matching_index = next(
            (
                index
                for index in range(previous_index + 1, len(normalized_rendered))
                if normalized_expected in normalized_rendered[index]
            ),
            None,
        )
        assert matching_index is not None, (
            f"expected rendered copy {normalized_expected!r} after index "
            f"{previous_index}; rendered={normalized_rendered!r}"
        )
        previous_index = matching_index


def _assert_copy_in_order(value: str, expected: tuple[str, ...]) -> None:
    normalized_value = _normalize_whitespace(value)
    previous_index = -1
    for expected_value in expected:
        normalized_expected = _normalize_whitespace(expected_value)
        matching_index = normalized_value.find(normalized_expected, previous_index + 1)
        assert matching_index > previous_index, (
            f"expected copy {normalized_expected!r} after index {previous_index}; "
            f"value={normalized_value!r}"
        )
        previous_index = matching_index


def _showcase_asset_root() -> Path | None:
    candidates = (
        ROOT.parent / "physical-stimulation-session-recorder-showcase" / "assets",
        ROOT.parents[2]
        / "physical-stimulation-session-recorder-showcase"
        / "assets",
    )
    return next((candidate for candidate in candidates if candidate.is_dir()), None)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image_targets(markdown: str) -> set[str]:
    markdown_targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    html_targets = re.findall(
        r"<img\s+[^>]*src=[\"']([^\"']+)[\"']",
        markdown,
        flags=re.IGNORECASE,
    )
    return set(markdown_targets + html_targets)


def _protected_hits(text: str) -> set[str]:
    folded = text.casefold()
    hits: set[str] = set()
    for length, protected_signature in PROTECTED_SUBSTRING_SIGNATURES:
        for start in range(len(folded) - length + 1):
            candidate = folded[start : start + length].encode("utf-8")
            if hashlib.sha256(candidate).hexdigest() == protected_signature:
                hits.add(protected_signature)
    return hits


def _assert_safe_text(text: str) -> None:
    assert _protected_hits(text) == set()
    assert CREDENTIAL_PATTERN.search(text) is None


def _embedded_absolute_paths(raw_bytes: bytes) -> list[str]:
    printable_ascii = "\n".join(
        run.decode("ascii") for run in re.findall(rb"[\x20-\x7e]{6,}", raw_bytes)
    )
    printable_utf16le = "\n".join(
        run.decode("utf-16-le")
        for run in re.findall(rb"(?:[\x20-\x7e]\x00){3,}", raw_bytes)
    )
    path_pattern = re.compile(
        r"(?i)(?:\b[A-Z]:[\\/](?:[^\\/\s\x00]+[\\/])*[^\\/\s\x00]*"
        r"|\\\\[^\\\s\x00]+\\[^\\\s\x00]+"
        r"|/(?:root|home|users|mnt|data|private|srv|etc|usr|tmp|var|opt|workspace)"
        r"(?:/[^/\s\x00]+)+)"
    )
    return path_pattern.findall(printable_ascii + "\n" + printable_utf16le)


def _assert_asset_set(asset_root: Path) -> None:
    assert asset_root.is_dir()
    assert {path.name for path in asset_root.iterdir() if path.is_file()} == set(
        EXPECTED_ASSETS
    )

    for name, dimensions in EXPECTED_ASSETS.items():
        path = asset_root / name
        with Image.open(path) as image:
            assert image.size == dimensions
            assert image.format == ("GIF" if path.suffix == ".gif" else "WEBP")
            image.verify()


def _assert_gif_contract(asset_root: Path) -> None:
    gif_path = asset_root / "operational-workflow.gif"
    assert gif_path.stat().st_size < 5 * 1024 * 1024
    durations = []
    with Image.open(gif_path) as image:
        assert image.is_animated is True
        assert image.n_frames == len(EXPECTED_STAGE_LABELS)
        for frame_index in range(image.n_frames):
            image.seek(frame_index)
            durations.append(image.info["duration"])
            image.convert("RGB").load()
    assert tuple(durations) == EXPECTED_DURATIONS


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "operational_readme_asset_generator_under_test", GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_exists_and_uses_only_original_drawing_primitives() -> None:
    assert GENERATOR_PATH.is_file()
    source = _generator_source()
    parsed = ast.parse(source)

    assert "showcase" not in source.casefold()
    assert "http://" not in source.casefold()
    assert "https://" not in source.casefold()
    assert "Image.new(" in source
    assert "ImageDraw.Draw(" in source
    for input_operation in (
        "Image.open(",
        "Image.fromarray(",
        "Image.frombytes(",
        ".read_bytes(",
        ".read_text(",
        ".resize(",
        ".thumbnail(",
        ".transform(",
    ):
        assert input_operation not in source

    imported_roots: set[str] = set()
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots <= {"__future__", "pathlib", "PIL"}


def test_generator_declares_exact_labels_and_palette() -> None:
    source = _generator_source()

    for english, chinese in EXPECTED_STAGE_LABELS:
        assert f'"{english}"' in source
        assert f'"{chinese}"' in source
    assert all(value in source for value in EXPECTED_PALETTE)


@pytest.mark.parametrize(
    ("renderer_name", "expected_copy"),
    (
        pytest.param(
            "_draw_questionnaire",
            QUESTIONNAIRE_COPY,
            id="questionnaire",
        ),
        pytest.param("_draw_export", PACKAGE_COPY, id="package"),
        pytest.param("_draw_completion", COMPLETION_COPY, id="completion"),
    ),
)
def test_generator_renders_surface_copy_in_order(
    renderer_name: str,
    expected_copy: tuple[str, ...],
) -> None:
    generator = _load_generator()
    renderer = getattr(generator, renderer_name, None)
    assert callable(renderer), f"expected callable renderer {renderer_name!r}"
    recording_draw = _RecordingDraw()

    renderer(recording_draw)

    _assert_rendered_copy_in_order(recording_draw.rendered, expected_copy)


def test_recording_surface_downloads_before_local_file_review_and_confirmation() -> None:
    generator = _load_generator()
    renderer = getattr(generator, "_draw_recording", None)
    assert callable(renderer), "expected callable renderer '_draw_recording'"
    recording_draw = _RecordingDraw()

    renderer(recording_draw)

    _assert_rendered_copy_in_order(
        recording_draw.rendered,
        RECORDING_HANDOFF_COPY,
    )


def test_chrome_guide_downloads_before_local_file_review_and_confirmation() -> None:
    chrome_guide = _readme().split(
        "<summary>Chrome 操作与故障排查 / Chrome guide and troubleshooting</summary>",
        1,
    )[1].split("</details>", 1)[0]
    recording_step = next(
        line for line in chrome_guide.splitlines() if line.startswith("2. ")
    )

    _assert_copy_in_order(recording_step, RECORDING_HANDOFF_COPY)


def test_generator_draws_structured_response_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load_generator()
    closure = getattr(generator, "draw_structured_response_closure", None)
    assert callable(closure), "expected callable draw_structured_response_closure"
    recording_draw = _RecordingDraw()
    monkeypatch.setattr(generator.ImageDraw, "Draw", lambda _: recording_draw)

    closure()

    _assert_rendered_copy_in_order(
        recording_draw.rendered,
        ("04", "分步结构化作答", "05", "本地资料包", "06", "完成确认"),
    )


def test_generator_wires_structured_response_closure_asset() -> None:
    source = _generator_source()
    function_name = "generate_assets"
    generate_assets_source = _function_source(source, function_name)
    generate_assets_tree = ast.parse(generate_assets_source)
    calls_closure = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "draw_structured_response_closure"
        and not node.args
        and not node.keywords
        for node in ast.walk(generate_assets_tree)
    )
    generated_strings = {
        node.value
        for node in ast.walk(generate_assets_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    missing_wiring = []
    if not calls_closure:
        missing_wiring.append("draw_structured_response_closure()")
    if "structured-response-closure.webp" not in generated_strings:
        missing_wiring.append("structured-response-closure.webp")
    assert missing_wiring == []


def test_committed_operational_asset_inventory_dimensions_and_animation() -> None:
    _assert_asset_set(ASSET_ROOT)
    _assert_gif_contract(ASSET_ROOT)


def test_committed_operational_assets_do_not_reuse_showcase_files() -> None:
    showcase_root = _showcase_asset_root()
    if showcase_root is None:
        pytest.skip("showcase asset clone is not available")
    showcase_hashes = {
        _sha256(path) for path in showcase_root.rglob("*") if path.is_file()
    }

    assert all(_sha256(path) not in showcase_hashes for path in ASSET_ROOT.iterdir())


def test_generator_is_deterministic_and_never_mutates_committed_assets(
    tmp_path: Path,
) -> None:
    committed_hashes_before = {
        path.name: _sha256(path) for path in ASSET_ROOT.iterdir() if path.is_file()
    }
    first_root = tmp_path / "first" / "assets"
    second_root = tmp_path / "second" / "assets"
    generator = _load_generator()
    original_asset_dir = generator.ASSET_DIR
    try:
        generator.ASSET_DIR = first_root
        generator.generate_assets()
        generator.ASSET_DIR = second_root
        generator.generate_assets()
    finally:
        generator.ASSET_DIR = original_asset_dir

    _assert_asset_set(first_root)
    _assert_asset_set(second_root)
    _assert_gif_contract(first_root)
    _assert_gif_contract(second_root)
    assert {
        name: _sha256(first_root / name) for name in EXPECTED_ASSETS
    } == {name: _sha256(second_root / name) for name in EXPECTED_ASSETS}
    generated_hashes = {
        name: _sha256(first_root / name) for name in EXPECTED_ASSETS
    }
    is_reference_environment = (
        PILLOW_VERSION == REFERENCE_PILLOW_VERSION
        and all(path.is_file() for path in REFERENCE_WINDOWS_FONTS)
    )
    if is_reference_environment:
        assert committed_hashes_before == generated_hashes
    assert committed_hashes_before == {
        path.name: _sha256(path) for path in ASSET_ROOT.iterdir() if path.is_file()
    }


def test_readme_uses_exact_presentation_inventory_and_showcase_is_final_text_only() -> None:
    readme = _readme()
    image_targets = _image_targets(readme)

    assert image_targets == EXPECTED_README_IMAGE_TARGETS
    assert all((ROOT / target).is_file() for target in image_targets)
    assert "raw.githubusercontent.com" not in readme.casefold()
    assert all("showcase" not in target.casefold() for target in image_targets)
    assert readme.count(SHOWCASE_URL) == 1
    final_section_index = readme.rfind("## Presentation Reference")
    assert final_section_index > readme.rfind("![")
    final_section = readme[final_section_index:]
    assert SHOWCASE_URL in final_section
    assert "![" not in final_section
    assert readme.rstrip().endswith(").")


def test_readme_leads_with_chinese_teacher_facing_contract() -> None:
    readme = _readme()
    surface_heading = "## 实际界面与操作闭环"

    assert readme.startswith("# 物理刺激干预会话伴侣")
    assert surface_heading in readme
    first_viewport = readme.split(surface_heading, 1)[0]
    assert "Physical Stimulation Intervention Session Companion" in first_viewport
    for required_signal in (
        "六阶段",
        "本地录制与导出",
        "无媒体上传路径",
        "assets/readme/operational-workflow.gif",
        "assets/readme/operational-workflow-static.webp",
    ):
        assert required_signal in first_viewport

    stage_completion_semantics = (
        "进入成功",
        "必填信息完成",
        "本地录像已检查，或已确认不保存",
        "必答步骤完成",
        "已确认 ZIP 保存到本地",
        "录制结果与 ZIP 保存均已确认",
    )
    first_viewport_lines = first_viewport.splitlines()
    previous_row_index = -1
    first_stage_row_index: int | None = None
    for stage_number, (english, chinese), completion in zip(
        range(1, 7), EXPECTED_STAGE_LABELS, stage_completion_semantics, strict=True
    ):
        expected_stage_cell = f"{stage_number:02d} · {chinese} / {english}"
        row_prefix = f"| {expected_stage_cell} |"
        matching_rows = [
            (index, line)
            for index, line in enumerate(first_viewport_lines)
            if line.startswith(row_prefix)
        ]
        assert len(matching_rows) == 1, f"expected one row starting {row_prefix!r}"
        row_index, row = matching_rows[0]
        assert row_index > previous_row_index
        if first_stage_row_index is None:
            first_stage_row_index = row_index
        row_cells = [
            _normalize_whitespace(cell)
            for cell in row.strip().strip("|").split("|")
        ]
        assert len(row_cells) == 3
        assert row_cells[0] == expected_stage_cell
        _assert_chinese_first_bilingual_cell(row_cells[1])
        _assert_chinese_first_bilingual_cell(
            row_cells[2],
            expected_chinese=completion,
        )
        previous_row_index = row_index

    assert first_stage_row_index is not None and first_stage_row_index >= 2
    header_cells = [
        _normalize_whitespace(cell)
        for cell in first_viewport_lines[first_stage_row_index - 2]
        .strip()
        .strip("|")
        .split("|")
    ]
    separator_cells = [
        _normalize_whitespace(cell)
        for cell in first_viewport_lines[first_stage_row_index - 1]
        .strip()
        .strip("|")
        .split("|")
    ]
    assert len(header_cells) == 3
    assert all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator_cells)
    assert len(separator_cells) == len(header_cells)
    for header_cell in header_cells:
        _assert_chinese_first_bilingual_cell(header_cell)

    streamlit_urls = re.findall(
        r"https?://[A-Za-z0-9-]+\.streamlit\.app/?",
        readme,
        flags=re.IGNORECASE,
    )
    normalized_streamlit_urls = [
        url if url.endswith("/") else f"{url}/" for url in streamlit_urls
    ]
    assert normalized_streamlit_urls == [APPLICATION_URL]
    assert readme.count(APPLICATION_URL) == 1
    assert "https://physical-stimulation-session-recorder.streamlit.app" not in readme


def test_readme_current_surfaces_follow_the_operational_sequence() -> None:
    readme = _readme()
    surface_heading = "## 实际界面与操作闭环"
    boundary_heading = "## 方法与数据边界"

    assert surface_heading in readme
    assert boundary_heading in readme
    surface_start = readme.index(surface_heading)
    boundary_start = readme.index(boundary_heading)
    assert surface_start < boundary_start
    surface_section = readme[surface_start + len(surface_heading) : boundary_start]
    ordered_surfaces = (
        "03 本地录制",
        "04 分步结构化作答",
        "05 本地资料包",
        "06 完成确认",
    )
    assert all(surface in surface_section for surface in ordered_surfaces)
    positions = [surface_section.index(surface) for surface in ordered_surfaces]
    assert positions == sorted(positions)

    required_image_targets = (
        "assets/readme/local-recording-save.webp",
        "assets/readme/structured-response-closure.webp",
        "assets/readme/questionnaire-experience.webp",
        "assets/readme/local-response-export.webp",
        "assets/readme/completion-confirmation.webp",
    )
    assert all(target in surface_section for target in required_image_targets)
    assert QUESTIONNAIRE_COPY[1] in surface_section
    assert "JSON + Excel" in surface_section
    assert "未上传到应用服务器" in surface_section


def test_readme_exposes_one_representative_question_without_identity_data() -> None:
    readme = _readme()

    assert readme.count(QUESTIONNAIRE_COPY[1]) == 1
    assert "全部题目" not in readme
    assert "完整题库" not in readme
    assert re.search(r"\bsub-\d{3,}\b", readme, flags=re.IGNORECASE) is None


def test_readme_documents_recording_export_and_privacy_handoffs() -> None:
    readme = _readme()
    assert "我已下载并检查录像，继续填写问卷" in readme
    assert "我确认继续填写问卷，不保存本次录制" in readme
    assert "我确认问卷 ZIP 已保存到本地" in readme
    assert "WebM with audio" in readme
    assert "transient Streamlit session memory" in readme
    assert "explicitly confirms the package was saved locally" in readme
    assert "Recording-outcome confirmation" in readme
    assert "response package was saved and checked" not in readme
    assert "ZIP checked locally" not in readme
    assert "User checks response package" not in readme
    assert "both save confirmations" not in readme

    match = re.search(r"```mermaid\s+(.*?)```", readme, flags=re.DOTALL)
    assert match is not None
    diagram = match.group(1)
    required_semantics = (
        "Camera + microphone",
        "Browser-local recorder",
        "Locally saved WebM with audio",
        "No media upload path",
        "No-save path confirmed when recording is skipped or unavailable",
        "Transient session memory",
        "Response-package generation",
        "ZIP download",
        "Locally saved JSON + Excel ZIP",
        "User confirms ZIP saved locally",
        "no durable response store",
    )
    assert all(semantic in diagram for semantic in required_semantics)
    required_edges = (
        "AV[Camera + microphone] --> REC[Browser-local recorder]",
        "REC --> WEBM[Locally saved WebM with audio]",
        "REC --> NO_SAVE[No-save path confirmed when recording is skipped or unavailable]",
        "UI -- session controls and response values over TLS --> MEMORY",
        "MEMORY --> PACKAGE",
        "PACKAGE -- ZIP download --> DOWNLOAD",
        "DOWNLOAD --> ZIP[Locally saved JSON + Excel ZIP]",
    )
    assert all(edge in diagram for edge in required_edges)


def test_readme_details_cover_setup_deployment_secrets_and_verification() -> None:
    readme = _readme()
    detail_blocks = re.findall(r"<details>.*?</details>", readme, flags=re.DOTALL)

    assert len(detail_blocks) >= 4
    assert any(
        "Local setup" in block
        and "python -m pip install -r requirements-dev.txt" in block
        and "python -m streamlit run app.py" in block
        for block in detail_blocks
    )
    assert any(
        "Streamlit deployment" in block
        and all(
            key in block
            for key in (
                "APP_PASSWORD_SHA256",
                "LINK_SIGNING_KEY",
                "TRUSTED_INTERVENTION_DAYS",
                "SAFETY_CONTACT",
            )
        )
        for block in detail_blocks
    )
    assert any(
        "Verification commands" in block
        and "python -m pytest -q" in block
        and "python -m py_compile" in block
        for block in detail_blocks
    )


def test_public_contract_generator_readme_and_metadata_are_safe() -> None:
    for path in (README_PATH, GENERATOR_PATH, TEST_PATH):
        _assert_safe_text(path.read_text(encoding="utf-8"))
    assert re.search(r"\bsub-\d{3,}\b", _readme(), flags=re.IGNORECASE) is None

    for path in ASSET_ROOT.iterdir():
        with Image.open(path) as image:
            metadata_keys = {key.casefold() for key in image.info}
            assert metadata_keys.isdisjoint({"exif", "xmp", "comment"})
            assert not image.getexif()
            metadata = "\n".join(
                f"{key}={value}" for key, value in sorted(image.info.items())
            )
        _assert_safe_text(metadata)
        raw_bytes = path.read_bytes()
        assert _embedded_absolute_paths(raw_bytes) == []
