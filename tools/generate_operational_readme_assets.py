"""Generate the privacy-safe visual assets used by the operational README."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1440, 810
PALETTE_HEIGHT = 160
COLORS = {
    "navy": "#000035",
    "violet": "#2D2674",
    "rose": "#DD1D86",
    "cyan": "#33B0E4",
    "peach": "#FFBC7D",
    "paper": "#FFFFFF",
    "mist": "#F4F5F7",
    "line": "#DDE1E8",
    "muted": "#62647A",
}
STAGES = (
    ("01", "Controlled access", "受控进入"),
    ("02", "Daily context", "当日状态"),
    ("03", "Browser-local recording", "本地音视频"),
    ("04", "Stepwise questionnaire", "分步结构化作答"),
    ("05", "Local response package", "本地资料包"),
    ("06", "Completion confirmation", "完成确认"),
)
STAGE_ACCENTS = (
    COLORS["rose"],
    COLORS["peach"],
    COLORS["cyan"],
    COLORS["rose"],
    COLORS["violet"],
    COLORS["cyan"],
)
DURATIONS = (1800, 1800, 2200, 2200, 2000, 2600)
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "readme"


def _font_candidates(bold: bool) -> tuple[str, ...]:
    windows = Path("C:/Windows/Fonts")
    if bold:
        return (
            str(windows / "msyhbd.ttc"),
            str(windows / "arialbd.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        )
    return (
        str(windows / "msyh.ttc"),
        str(windows / "arial.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _font_candidates(bold):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def rounded_box(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    fill: str,
    outline: str | None = None,
    radius: int = 16,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(bounds, radius=radius, fill=fill, outline=outline, width=width)


def _text_width(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=face)
    return box[2] - box[0]


def _centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    *,
    face: ImageFont.ImageFont,
    fill: str,
) -> None:
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=face)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.text(
        (left + (right - left - width) / 2, top + (bottom - top - height) / 2 - bounds[1]),
        text,
        font=face,
        fill=fill,
    )


def _check(draw: ImageDraw.ImageDraw, x: int, y: int, color: str, scale: int = 1) -> None:
    draw.line(
        [(x, y + 7 * scale), (x + 7 * scale, y + 14 * scale), (x + 20 * scale, y)],
        fill=color,
        width=3 * scale,
        joint="curve",
    )


def draw_header(draw: ImageDraw.ImageDraw, stage_index: int) -> None:
    draw.text((54, 34), "SESSION COMPANION", font=font(20, True), fill=COLORS["paper"])
    draw.text(
        (54, 68),
        "A calm, local-first path from entry to confirmation",
        font=font(16),
        fill="#C9CAE0",
    )
    stage_number = f"{stage_index + 1:02d} / {len(STAGES):02d}"
    draw.text((1326, 46), stage_number, font=font(16, True), fill=COLORS["paper"], anchor="ra")


def draw_progress_rail(draw: ImageDraw.ImageDraw, stage_index: int) -> None:
    x = 54
    start_y = 150
    row_height = 92
    draw.text((x, 118), "SESSION FLOW / 会话流程", font=font(15, True), fill="#BFC0D6")
    draw.line((76, start_y + 22, 76, start_y + row_height * 5 + 22), fill="#514B8B", width=3)

    for index, (number, english, chinese) in enumerate(STAGES):
        y = start_y + index * row_height
        active = index == stage_index
        complete = index < stage_index
        if active:
            rounded_box(
                draw,
                (42, y - 10, 360, y + 70),
                fill="#17134F",
                outline=STAGE_ACCENTS[index],
                radius=10,
                width=2,
            )
        circle_fill = STAGE_ACCENTS[index] if active else (COLORS["cyan"] if complete else COLORS["violet"])
        draw.ellipse((58, y + 4, 94, y + 40), fill=circle_fill)
        if complete:
            _check(draw, 66, y + 13, COLORS["paper"])
        else:
            _centered_text(
                draw,
                (58, y + 4, 94, y + 40),
                number,
                face=font(13, True),
                fill=COLORS["paper"],
            )
        label_fill = COLORS["paper"] if active else "#D7D8E7"
        draw.text((112, y + 2), english, font=font(18, True), fill=label_fill)
        draw.text((112, y + 31), chinese, font=font(15), fill="#AAACC4")


def draw_workspace_header(draw: ImageDraw.ImageDraw, stage_index: int) -> None:
    number, english, chinese = STAGES[stage_index]
    accent = STAGE_ACCENTS[stage_index]
    rounded_box(draw, (454, 136, 520, 170), fill=accent, radius=17)
    _centered_text(
        draw,
        (454, 136, 520, 170),
        f"STEP {number}",
        face=font(13, True),
        fill=COLORS["paper"],
    )
    draw.text((454, 194), english, font=font(36, True), fill=COLORS["navy"])
    draw.text((454, 242), chinese, font=font(23), fill=COLORS["violet"])
    draw.line((454, 286, 1346, 286), fill=COLORS["line"], width=2)


def draw_button(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    label: str,
    *,
    fill: str,
    foreground: str = COLORS["paper"],
) -> None:
    rounded_box(draw, bounds, fill=fill, radius=8)
    _centered_text(draw, bounds, label, face=font(17, True), fill=foreground)


def draw_footer(draw: ImageDraw.ImageDraw, message: str) -> None:
    draw.line((454, 734, 1346, 734), fill=COLORS["line"], width=1)
    draw.ellipse((454, 758, 464, 768), fill=COLORS["cyan"])
    draw.text((478, 750), message, font=font(15), fill=COLORS["muted"])
    draw.text((1346, 750), "LOCAL-FIRST / 本地优先", font=font(13, True), fill=COLORS["violet"], anchor="ra")


def _status_row(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    title: str,
    subtitle: str,
    accent: str,
) -> None:
    rounded_box(draw, (x, y, x + width, y + 82), fill=COLORS["paper"], outline=COLORS["line"], radius=10)
    draw.ellipse((x + 20, y + 23, x + 56, y + 59), fill=accent)
    _check(draw, x + 28, y + 32, COLORS["paper"])
    draw.text((x + 76, y + 17), title, font=font(18, True), fill=COLORS["navy"])
    draw.text((x + 76, y + 47), subtitle, font=font(14), fill=COLORS["muted"])


def _draw_access(draw: ImageDraw.ImageDraw) -> None:
    rounded_box(draw, (454, 324, 956, 674), fill=COLORS["paper"], outline=COLORS["line"])
    draw.text((494, 362), "Controlled session entry", font=font(24, True), fill=COLORS["navy"])
    draw.text((494, 405), "受控会话入口", font=font(18), fill=COLORS["violet"])
    draw.text((494, 459), "Access is checked before the guided flow begins.", font=font(16), fill=COLORS["muted"])
    rounded_box(draw, (494, 508, 916, 568), fill=COLORS["mist"], outline=COLORS["line"], radius=8)
    draw.text((516, 527), "Secure access field", font=font(16), fill="#85879A")
    draw_button(draw, (494, 592, 720, 646), "Continue / 继续", fill=COLORS["rose"])

    rounded_box(draw, (986, 324, 1346, 674), fill="#F8F7FC", outline=COLORS["line"])
    draw.ellipse((1088, 372, 1244, 528), fill=COLORS["violet"])
    draw.arc((1134, 406, 1198, 476), 180, 360, fill=COLORS["paper"], width=7)
    rounded_box(draw, (1130, 444, 1202, 494), fill=COLORS["paper"], radius=8)
    draw.text((1166, 563), "Access boundary", font=font(18, True), fill=COLORS["navy"], anchor="ma")
    draw.text((1166, 596), "权限边界", font=font(16), fill=COLORS["violet"], anchor="ma")
    draw.text((1166, 630), "No credential shown", font=font(14), fill=COLORS["muted"], anchor="ma")


def _draw_daily_context(draw: ImageDraw.ImageDraw) -> None:
    draw.text((454, 326), "Confirm today\'s context before continuing", font=font(23, True), fill=COLORS["navy"])
    draw.text((454, 365), "继续前确认当日会话信息", font=font(18), fill=COLORS["violet"])
    _status_row(draw, 454, 418, 560, "Session context", "Ready for a guided check", COLORS["peach"])
    _status_row(draw, 454, 518, 560, "Required fields", "Completion checks are active", COLORS["cyan"])
    rounded_box(draw, (1046, 418, 1346, 600), fill="#FFF8F1", outline="#F3D8BE", radius=12)
    draw.text((1080, 452), "Quiet checkpoint", font=font(20, True), fill=COLORS["navy"])
    draw.text((1080, 489), "简洁确认", font=font(17), fill=COLORS["violet"])
    draw.text((1080, 538), "No response values\nare displayed here.", font=font(15), fill=COLORS["muted"], spacing=8)
    draw_button(draw, (1120, 624, 1346, 678), "Confirm / 确认", fill=COLORS["rose"])


def _draw_recording(draw: ImageDraw.ImageDraw) -> None:
    rounded_box(draw, (454, 324, 1028, 650), fill=COLORS["navy"], radius=12)
    draw.rectangle((476, 346, 1006, 628), outline="#4D4A78", width=2)
    draw.ellipse((668, 395, 814, 541), outline=COLORS["cyan"], width=6)
    draw.arc((620, 493, 862, 603), 200, 340, fill=COLORS["cyan"], width=6)
    draw.text((486, 362), "LOCAL PREVIEW", font=font(13, True), fill="#BFC0D6")
    draw.ellipse((928, 360, 944, 376), fill=COLORS["rose"])
    draw.text((954, 357), "Ready", font=font(14), fill=COLORS["paper"])

    _status_row(draw, 1058, 324, 288, "Camera", "Ready", COLORS["cyan"])
    _status_row(draw, 1058, 420, 288, "Microphone", "Ready", COLORS["cyan"])
    rounded_box(draw, (1058, 516, 1346, 650), fill=COLORS["paper"], outline=COLORS["line"], radius=10)
    draw.text((1082, 542), "Browser-local WebM", font=font(17, True), fill=COLORS["navy"])
    draw.text((1082, 576), "音视频保留在浏览器本地", font=font(14), fill=COLORS["violet"])
    draw_button(draw, (1082, 604, 1322, 638), "Record / 开始录制", fill=COLORS["rose"])
    draw_footer(draw, "Preview, record, review, download, then confirm the local save")


def _draw_questionnaire(draw: ImageDraw.ImageDraw) -> None:
    rounded_box(draw, (454, 322, 1346, 682), fill=COLORS["paper"], outline=COLORS["line"])
    draw.text((494, 354), "ONE-STEP FOCUS / 单步聚焦", font=font(14, True), fill=COLORS["rose"])
    draw.text((494, 392), "One focused step at a time", font=font(24, True), fill=COLORS["navy"])
    draw.text((494, 432), "每次只呈现一个结构化步骤", font=font(18), fill=COLORS["violet"])
    draw.text((494, 483), "Response choices", font=font(15, True), fill=COLORS["muted"])
    for index in range(3):
        left = 494 + index * 142
        rounded_box(draw, (left, 516, left + 122, 568), fill=COLORS["mist"], outline=COLORS["line"], radius=8)
        draw.ellipse((left + 18, 533, left + 36, 551), outline=COLORS["violet"], width=2)
        draw.line((left + 50, 542, left + 100, 542), fill="#A7A9B7", width=3)
    rounded_box(draw, (494, 602, 844, 646), fill="#FCEAF4", radius=8)
    draw.text((514, 613), "Applicable follow-ups appear when needed", font=font(14), fill=COLORS["violet"])
    rounded_box(draw, (900, 354, 1306, 646), fill="#F8F7FC", outline=COLORS["line"], radius=12)
    _status_row(draw, 924, 378, 358, "Completion checks", "Required steps stay visible", COLORS["cyan"])
    _status_row(draw, 924, 474, 358, "Support copy", "Direct guidance when applicable", COLORS["peach"])
    draw.text((944, 592), "No participant-facing scores", font=font(17, True), fill=COLORS["navy"])
    draw.text((944, 620), "参与者页面不显示分数", font=font(14), fill=COLORS["violet"])


def _file_tile(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    subtitle: str,
    accent: str,
) -> None:
    rounded_box(draw, (x, y, x + 260, y + 230), fill=COLORS["paper"], outline=COLORS["line"], radius=12)
    rounded_box(draw, (x + 28, y + 28, x + 108, y + 112), fill=accent, radius=8)
    draw.rectangle((x + 50, y + 49, x + 86, y + 92), outline=COLORS["paper"], width=3)
    draw.line((x + 57, y + 63, x + 79, y + 63), fill=COLORS["paper"], width=2)
    draw.line((x + 57, y + 76, x + 79, y + 76), fill=COLORS["paper"], width=2)
    draw.text((x + 28, y + 136), label, font=font(21, True), fill=COLORS["navy"])
    draw.text((x + 28, y + 173), subtitle, font=font(14), fill=COLORS["muted"])


def _draw_export(draw: ImageDraw.ImageDraw) -> None:
    draw.text((454, 326), "Prepare the local response package", font=font(23, True), fill=COLORS["navy"])
    draw.text((454, 365), "生成并保存本地资料包", font=font(18), fill=COLORS["violet"])
    _file_tile(draw, 454, 418, "JSON record", "Structured local copy", COLORS["violet"])
    _file_tile(draw, 736, 418, "Excel record", "Readable local copy", COLORS["cyan"])
    rounded_box(draw, (1018, 418, 1346, 648), fill="#FCEAF4", outline="#F4C3DD", radius=12)
    draw.text((1050, 452), "ZIP package", font=font(22, True), fill=COLORS["navy"])
    draw.text((1050, 490), "JSON + Excel", font=font(18, True), fill=COLORS["rose"])
    draw.text((1050, 530), "Saved by the user\nto a local folder", font=font(15), fill=COLORS["muted"], spacing=8)
    draw_button(draw, (1050, 588, 1314, 632), "Save locally / 本地保存", fill=COLORS["rose"])


def _draw_completion(draw: ImageDraw.ImageDraw) -> None:
    rounded_box(draw, (454, 324, 1346, 682), fill="#F8F7FC", outline=COLORS["line"])
    draw.ellipse((550, 404, 750, 604), fill=COLORS["cyan"])
    _check(draw, 606, 466, COLORS["paper"], scale=4)
    draw.text((816, 400), "Local files confirmed", font=font(28, True), fill=COLORS["navy"])
    draw.text((816, 448), "本地文件已检查", font=font(21), fill=COLORS["violet"])
    draw.text(
        (816, 510),
        "Recording and response package\nhave separate save confirmations.",
        font=font(17),
        fill=COLORS["muted"],
        spacing=10,
    )
    rounded_box(draw, (816, 594, 1266, 636), fill="#E7F7FD", radius=8)
    draw.text((840, 604), "Session complete / 会话完成", font=font(16, True), fill=COLORS["navy"])


def draw_scene(stage_index: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["mist"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 400, HEIGHT), fill=COLORS["navy"])
    draw.rectangle((400, 0, WIDTH, 108), fill=COLORS["navy"])
    draw.rectangle((400, 108, WIDTH, HEIGHT), fill=COLORS["mist"])
    draw_header(draw, stage_index)
    draw_progress_rail(draw, stage_index)
    draw_workspace_header(draw, stage_index)
    renderers = (
        _draw_access,
        _draw_daily_context,
        _draw_recording,
        _draw_questionnaire,
        _draw_export,
        _draw_completion,
    )
    renderers[stage_index](draw)
    if stage_index not in (2,):
        draw_footer(draw, "Guided, privacy-conscious, and explicit at every handoff")
    return image


def draw_palette() -> Image.Image:
    image = Image.new("RGB", (WIDTH, PALETTE_HEIGHT), COLORS["paper"])
    draw = ImageDraw.Draw(image)
    swatches = (
        ("#000035", "DEEP NAVY"),
        ("#2D2674", "VIOLET"),
        ("#DD1D86", "ROSE"),
        ("#33B0E4", "CYAN"),
        ("#FFBC7D", "PEACH"),
    )
    swatch_width = WIDTH // len(swatches)
    for index, (color, name) in enumerate(swatches):
        left = index * swatch_width
        right = WIDTH if index == len(swatches) - 1 else left + swatch_width
        draw.rectangle((left, 0, right, PALETTE_HEIGHT), fill=color)
        text_color = COLORS["navy"] if color in (COLORS["cyan"], COLORS["peach"]) else COLORS["paper"]
        draw.text((left + 28, 50), name, font=font(17, True), fill=text_color)
        draw.text((left + 28, 88), color, font=font(16), fill=text_color)
    return image


def _save_webp(image: Image.Image, destination: Path) -> None:
    image.save(destination, format="WEBP", lossless=True, method=6)


def generate_assets() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    frames = [draw_scene(index) for index in range(len(STAGES))]
    frames[0].save(
        ASSET_DIR / "operational-workflow.gif",
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=DURATIONS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    _save_webp(frames[0], ASSET_DIR / "operational-workflow-static.webp")
    _save_webp(frames[3], ASSET_DIR / "questionnaire-experience.webp")
    _save_webp(frames[2], ASSET_DIR / "local-recording-save.webp")
    _save_webp(frames[4], ASSET_DIR / "local-response-export.webp")
    _save_webp(draw_palette(), ASSET_DIR / "operational-palette.webp")


if __name__ == "__main__":
    generate_assets()
