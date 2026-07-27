import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
DEV_REQUIREMENTS = ROOT / "requirements-dev.txt"


def _requirement_specs(path: Path) -> tuple[str, ...]:
    specs = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        spec = raw_line.split("#", 1)[0].strip()
        if spec:
            specs.append(spec)
    return tuple(specs)


def _package_name(spec: str) -> str:
    return re.split(r"[<>=!~\[]", spec, maxsplit=1)[0].casefold()


def test_production_requirements_are_exact_browser_local_runtime() -> None:
    assert _requirement_specs(REQUIREMENTS) == (
        "streamlit==1.37.1",
        "numpy>=1.24,<2.0",
        "XlsxWriter>=3.2,<4",
        "protobuf<5",
    )


def test_development_requirements_include_production_and_exact_test_tools() -> None:
    assert _requirement_specs(DEV_REQUIREMENTS) == (
        "-r requirements.txt",
        "pytest>=8.3,<9",
        "openpyxl>=3.1,<4",
    )


def test_removed_operational_packages_are_not_direct_dependencies() -> None:
    direct_specs = (
        *_requirement_specs(REQUIREMENTS),
        *(
            spec
            for spec in _requirement_specs(DEV_REQUIREMENTS)
            if not spec.startswith("-")
        ),
    )
    direct_packages = {_package_name(spec) for spec in direct_specs}
    assert {
        "requests",
        "toml",
        "python-dotenv",
        "dotenv",
        "streamlit-webrtc",
        "aiortc",
        "av",
    }.isdisjoint(direct_packages)
