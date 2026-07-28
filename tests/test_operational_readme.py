import hashlib
import re
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
ASSET_ROOT = ROOT / "assets" / "readme"
EXPECTED_ASSETS = {
    "operational-workflow.gif": (1440, 810),
    "operational-workflow-static.webp": (1440, 810),
    "questionnaire-experience.webp": (1440, 810),
    "local-recording-save.webp": (1440, 810),
    "local-response-export.webp": (1440, 810),
    "operational-palette.webp": (1440, 160),
}
CONFIDENTIAL_TERMS = (
    "tavns",
    "nssi",
    "sicq",
    "dshi",
    "fasm",
    "自伤",
    "自杀",
    "评分规则",
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


def test_operational_readme_asset_inventory_and_dimensions() -> None:
    assert ASSET_ROOT.is_dir()
    assert {path.name for path in ASSET_ROOT.iterdir() if path.is_file()} == set(
        EXPECTED_ASSETS
    )

    for name, dimensions in EXPECTED_ASSETS.items():
        path = ASSET_ROOT / name
        with Image.open(path) as image:
            assert image.size == dimensions
            assert image.format == ("GIF" if path.suffix == ".gif" else "WEBP")
            image.verify()


def test_operational_workflow_gif_is_readable_animation() -> None:
    gif_path = ASSET_ROOT / "operational-workflow.gif"

    assert gif_path.stat().st_size < 5 * 1024 * 1024
    with Image.open(gif_path) as image:
        assert image.is_animated is True
        assert image.n_frames >= 6
        for frame_index in range(image.n_frames):
            image.seek(frame_index)
            image.convert("RGB").load()


def test_operational_assets_are_not_showcase_file_reuse() -> None:
    showcase_root = _showcase_asset_root()
    if showcase_root is None:
        pytest.skip("showcase asset clone is not available")
    showcase_hashes = {
        _sha256(path) for path in showcase_root.iterdir() if path.is_file()
    }

    assert all(_sha256(path) not in showcase_hashes for path in ASSET_ROOT.iterdir())


def test_operational_readme_uses_every_local_asset_and_no_showcase_image() -> None:
    readme = _readme()
    image_targets = _image_targets(readme)

    assert {f"assets/readme/{name}" for name in EXPECTED_ASSETS} <= image_targets
    assert all((ROOT / target).is_file() for target in image_targets)
    assert "raw.githubusercontent.com" not in readme.casefold()
    assert not any(
        "physical-stimulation-session-recorder-showcase" in target.casefold()
        for target in image_targets
    )


def test_operational_readme_leads_with_questionnaire_first_alto_story() -> None:
    readme = _readme()
    first_viewport = readme.split("## Questionnaire Experience", 1)[0]
    required_first_viewport = (
        "# Physical Stimulation Intervention Session Companion",
        "Controlled access",
        "Daily context",
        "Browser-local recording",
        "Stepwise questionnaire",
        "Local response package",
        "Completion confirmation",
        "assets/readme/operational-workflow.gif",
    )

    assert all(item in first_viewport for item in required_first_viewport)
    assert readme.index("## Questionnaire Experience") < readme.index(
        "## Local-First Recording"
    )
    assert "No participant-facing scores" in readme
    assert "browser-local" in readme.casefold()
    assert "JSON + Excel" in readme
    assert readme.count("<details>") >= 2
    assert "#000035" in readme
    assert "#DD1D86" in readme


def test_operational_readme_and_asset_metadata_are_confidentiality_safe() -> None:
    readme = _readme()
    folded = readme.casefold()

    assert all(term.casefold() not in folded for term in CONFIDENTIAL_TERMS)
    assert CREDENTIAL_PATTERN.search(readme) is None
    assert re.search(r"\bsub-\d{3,}\b", readme, flags=re.IGNORECASE) is None

    for path in ASSET_ROOT.iterdir():
        with Image.open(path) as image:
            metadata = "\n".join(
                f"{key}={value}" for key, value in sorted(image.info.items())
            ).casefold()
        assert all(term.casefold() not in metadata for term in CONFIDENTIAL_TERMS)
        assert CREDENTIAL_PATTERN.search(metadata) is None
