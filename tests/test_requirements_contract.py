import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
DEV_REQUIREMENTS = ROOT / "requirements-dev.txt"
OPERATIONS_GUIDE = ROOT / "docs" / "questionnaire-operations.md"


def _requirement_specs(path: Path) -> tuple[str, ...]:
    specs = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        spec = raw_line.split("#", 1)[0].strip()
        if spec:
            specs.append(spec)
    return tuple(specs)


def _package_name(spec: str) -> str:
    name = re.split(r"[<>=!~\[]", spec, maxsplit=1)[0].casefold()
    return re.sub(r"[-_.]+", "-", name)


def test_package_name_uses_pep_503_normalization() -> None:
    assert {
        _package_name("Python_DotEnv>=1"),
        _package_name("streamlit.WebRTC==0.63.4"),
        _package_name("example...package___name[extra]"),
    } == {
        "python-dotenv",
        "streamlit-webrtc",
        "example-package-name",
    }


def test_deployment_installs_no_server_media_system_packages() -> None:
    assert tuple(ROOT.glob("packages*.txt")) == ()


def test_operations_guide_describes_current_browser_local_flow() -> None:
    guide = OPERATIONS_GUIDE.read_text(encoding="utf-8").casefold()
    required_statements = (
        "controlled access",
        "signed access link",
        "chrome",
        "https",
        "camera and microphone",
        "webm",
        "participant-selected local destination",
        "streamlit session memory",
        "raw questionnaire responses",
        "json and excel",
        "local zip",
        "local-save confirmation",
        "finish clears",
        "refreshing or closing the page",
        "cannot be recovered",
        "support contact",
        "does not upload recording or questionnaire data",
        "does not store participant data on the server",
    )
    assert all(statement in guide for statement in required_statements)


def test_operations_guide_has_no_legacy_cloud_or_server_media_guidance() -> None:
    guide = OPERATIONS_GUIDE.read_text(encoding="utf-8").casefold()
    legacy_fragments = (
        "baidu",
        "oauth",
        "refresh_token",
        "app_key",
        "secret_key",
        "config.toml",
        "save_dir",
        "remote_path",
        "local_cleanup",
        "localcleanuperror",
        "record_store",
        "schema 4",
        ".flv",
        ".mp4",
        "ffmpeg",
        "upload workflow",
        "upload retry",
        "server recovery",
    )
    assert all(fragment not in guide for fragment in legacy_fragments)


def test_operations_guide_contains_no_sensitive_or_study_specific_examples() -> None:
    guide = OPERATIONS_GUIDE.read_text(encoding="utf-8").casefold()
    prohibited_fragments = (
        "password",
        "token",
        "credential",
        "secret",
        "sub-001",
        "nssi",
        "dshi",
        "sicq",
        "pss_",
        "suicide thought",
    )
    assert all(fragment not in guide for fragment in prohibited_fragments)
    assert re.search(r"[a-z]:\\|/(?:apps|home|tmp|users)/", guide) is None


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
