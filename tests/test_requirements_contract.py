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


def _operations_guide_text() -> str:
    guide = OPERATIONS_GUIDE.read_text(encoding="utf-8").casefold()
    return re.sub(r"\s+", " ", guide)


def _system_package_specs(path: Path) -> tuple[str, ...]:
    specs = []
    for package_file in path.glob("packages*.txt"):
        for raw_line in package_file.read_text(encoding="utf-8").splitlines():
            spec = raw_line.split("#", 1)[0].strip()
            if spec:
                specs.append(spec)
    return tuple(specs)


def _server_media_system_packages(path: Path) -> set[str]:
    media_prefixes = (
        "ffmpeg",
        "gstreamer",
        "libavcodec",
        "libavdevice",
        "libavfilter",
        "libavformat",
        "libavresample",
        "libavutil",
        "libpostproc",
        "libswresample",
        "libswscale",
    )
    package_names = {
        re.split(r"[=:\s]", spec, maxsplit=1)[0].casefold()
        for spec in _system_package_specs(path)
    }
    return {
        name for name in package_names if name.startswith(media_prefixes)
    }


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
    assert not _server_media_system_packages(ROOT)


def test_system_package_contract_allows_unrelated_packages_and_rejects_media(
    tmp_path: Path,
) -> None:
    (tmp_path / "packages-observability.txt").write_text(
        "curl\nca-certificates  # TLS roots\n",
        encoding="utf-8",
    )

    assert not _server_media_system_packages(tmp_path)

    (tmp_path / "packages-media.txt").write_text(
        "FFmpeg  # media process\nlibavcodec-extra\n",
        encoding="utf-8",
    )

    assert _server_media_system_packages(tmp_path) == {"ffmpeg", "libavcodec-extra"}


def test_operations_guide_describes_current_browser_local_flow() -> None:
    guide = _operations_guide_text()
    required_statements = (
        "controlled access",
        "signed access link",
        "chrome",
        "https",
        "camera and microphone",
        "webm",
        "participant-selected local destination",
        "raw questionnaire responses",
        "json and excel",
        "local zip",
        "local-save confirmation",
        "finish clears",
        "refreshing or closing the page",
        "cannot be recovered",
        "support contact",
        "recording media is not sent to the streamlit server",
        "questionnaire answers travel over the streamlit connection",
        "current server session memory",
        "not written to server disk or a database",
        "not sent to external storage",
    )
    assert all(statement in guide for statement in required_statements)


def test_operations_guide_does_not_conflate_transient_server_memory_with_upload() -> None:
    guide = _operations_guide_text()
    misleading_statements = (
        "does not upload recording or questionnaire data",
        "does not store participant data on the server",
        "no recording or questionnaire transfer",
    )
    assert all(statement not in guide for statement in misleading_statements)


def test_operations_guide_has_no_legacy_cloud_or_server_media_guidance() -> None:
    guide = _operations_guide_text()
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
    guide = _operations_guide_text()
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
