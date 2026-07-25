import os
from pathlib import Path

import pytest

from showcase_audit import audit_showcase


APP_URL = "https://physical-stimulation-session-recorder.streamlit.app"
SVG_URL = "http://www.w3.org/2000/svg"


def _write_safe_tree(root: Path) -> None:
    (root / "assets").mkdir(parents=True)
    (root / ".gitignore").write_text(
        "*\n!.gitignore\n!README.md\n!assets/\n", encoding="utf-8"
    )
    (root / "README.md").write_text(
        f"# Public demo\n\n[Open the demo]({APP_URL}).\n", encoding="utf-8"
    )
    (root / "assets" / "session-recorder-preview.svg").write_text(
        f'<svg xmlns="{SVG_URL}"></svg>\n', encoding="utf-8"
    )


def _joined_findings(root: Path) -> str:
    return "\n".join(audit_showcase(root))


def test_safe_tree_passes_and_git_contents_are_ignored(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    git_leak = tmp_path / ".git" / "objects" / "leak"
    git_leak.parent.mkdir(parents=True)
    git_leak.write_text(
        "tavns https://example.test/?token=secret C:\\private\\file.txt",
        encoding="utf-8",
    )

    assert audit_showcase(tmp_path) == []


def test_approved_markdown_and_svg_urls_pass(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(
        f"[demo]({APP_URL})\n", encoding="utf-8"
    )

    assert audit_showcase(tmp_path) == []


def test_reports_extra_file_sensitive_content_paths_credentials_and_url(
    tmp_path: Path,
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(
        "TAVNS and \u81ea\u4f24\n"
        "C:\\Users\\Alice\\private.txt\n"
        "/Users/alice/private.txt\n"
        "/HOME/alice/private.txt\n"
        "https://example.test/private?ToKeN=value\n",
        encoding="utf-8",
    )
    (tmp_path / "private-notes.txt").write_text("public-looking text", encoding="utf-8")

    findings = _joined_findings(tmp_path)

    assert "extra-file: private-notes.txt" in findings
    assert "forbidden-term: README.md" in findings
    assert "absolute-path: README.md" in findings
    assert "credential-param: README.md" in findings
    assert "unapproved-url: README.md" in findings


def test_reports_every_missing_allowlisted_file(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)

    findings = _joined_findings(tmp_path)

    assert "missing-file: .gitignore" in findings
    assert "missing-file: README.md" in findings
    assert "missing-file: assets/session-recorder-preview.svg" in findings


@pytest.mark.parametrize(
    "term",
    [
        "TaVnS",
        "NSSI",
        "SiCq",
        "DSHI",
        "FaSm",
        "\u81ea\u4f24",
        "\u81ea\u6740",
        "\u91cf\u8868",
        "\u95ee\u5377",
        "\u8bc4\u5206\u89c4\u5219",
    ],
)
def test_forbidden_terms_are_case_insensitive(tmp_path: Path, term: str) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(term, encoding="utf-8")

    findings = _joined_findings(tmp_path)

    assert "forbidden-term: README.md" in findings


@pytest.mark.parametrize(
    "path_text",
    [r"D:\private\record.txt", "/Users/Alice/record.txt", "/HoMe/alice/record.txt"],
)
def test_absolute_path_forms_are_rejected(tmp_path: Path, path_text: str) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(path_text, encoding="utf-8")

    findings = _joined_findings(tmp_path)

    assert "absolute-path: README.md" in findings


@pytest.mark.parametrize(
    "parameter",
    ["sid", "SIG", "exp", "ToKeN", "secret", "PASSWORD"],
)
def test_credential_query_parameters_are_case_insensitive(
    tmp_path: Path, parameter: str
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(
        f"https://example.test/demo?mode=public&{parameter}=value", encoding="utf-8"
    )

    findings = _joined_findings(tmp_path)

    assert "credential-param: README.md" in findings


def test_invalid_utf8_fails_closed_instead_of_crashing(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_bytes(b"\xff\xfe\x00private")

    findings = _joined_findings(tmp_path)

    assert "decode-error: README.md" in findings


def test_binary_control_bytes_fail_closed(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_bytes(b"public\x00\x01text")

    findings = _joined_findings(tmp_path)

    assert "binary-content: README.md" in findings


@pytest.mark.parametrize(
    "url",
    [
        f"https://subdomain.{APP_URL.removeprefix('https://')}",
        f"{APP_URL}/private",
        f"{APP_URL}?mode=public",
        f"{APP_URL}_",
        f"evil.{APP_URL}",
        f"https://evil.example/{APP_URL}",
    ],
)
def test_only_exact_approved_urls_are_allowed(tmp_path: Path, url: str) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(url, encoding="utf-8")

    findings = _joined_findings(tmp_path)

    assert "unapproved-url: README.md" in findings


@pytest.mark.parametrize(
    "markdown",
    [
        f"[demo]({APP_URL}!)",
        f"[demo](javascript:{APP_URL})",
    ],
)
def test_markdown_cannot_hide_url_bypasses(
    tmp_path: Path, markdown: str
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(markdown, encoding="utf-8")

    findings = _joined_findings(tmp_path)

    assert "unapproved-url: README.md" in findings


@pytest.mark.parametrize("root_kind", ["missing", "file"])
def test_invalid_root_fails_closed(tmp_path: Path, root_kind: str) -> None:
    root = tmp_path / "showcase"
    if root_kind == "file":
        root.write_text("not a directory", encoding="utf-8")

    findings = audit_showcase(root)

    assert findings
    assert findings[0].startswith("invalid-root:")


@pytest.mark.parametrize("method_name", ["exists", "is_dir"])
def test_root_metadata_oserror_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method_name: str
) -> None:
    _write_safe_tree(tmp_path)

    def raise_oserror(_path: Path) -> bool:
        raise OSError("metadata denied")

    monkeypatch.setattr(Path, method_name, raise_oserror)

    findings = audit_showcase(tmp_path)

    assert findings
    assert findings[0].startswith("root-error:")


def test_walk_onerror_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_safe_tree(tmp_path)
    real_walk = os.walk

    def walk_with_error(
        top: Path,
        topdown: bool = True,
        onerror=None,
        followlinks: bool = False,
    ):
        assert onerror is not None
        assert followlinks is False
        onerror(PermissionError("walk denied"))
        return real_walk(
            top, topdown=topdown, onerror=onerror, followlinks=followlinks
        )

    monkeypatch.setattr(os, "walk", walk_with_error)

    findings = _joined_findings(tmp_path)

    assert "scan-error: ." in findings


def test_read_text_oserror_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_safe_tree(tmp_path)
    real_read_text = Path.read_text

    def read_text_with_error(path: Path, *args, **kwargs) -> str:
        if path.name == "README.md":
            raise OSError("read denied")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text_with_error)

    findings = _joined_findings(tmp_path)

    assert "read-error: README.md" in findings
