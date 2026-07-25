"""Fail-closed privacy audit for the public README-only showcase tree."""

import os
import re
from pathlib import Path


PUBLIC_FILES = (
    ".gitignore",
    "README.md",
    "assets/session-recorder-preview.svg",
)
APPROVED_URLS = {
    "https://physical-stimulation-session-recorder.streamlit.app",
    "http://www.w3.org/2000/svg",
}
FORBIDDEN_TERMS = (
    "tavns",
    "nssi",
    "sicq",
    "dshi",
    "fasm",
    "\u81ea\u4f24",
    "\u81ea\u6740",
    "\u91cf\u8868",
    "\u95ee\u5377",
    "\u8bc4\u5206\u89c4\u5219",
)

URI_PATTERN = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*):"
    r"(?P<body>[^\s<>\"'`)\]}]+)"
)
URI_START_BOUNDARIES = frozenset(" \t\r\n([{<>\"'`=")
WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?<![a-z0-9])[a-z]:\\[^\s<>\"']+")
UNIX_PATH_PATTERN = re.compile(r"(?i)(?<![a-z0-9])/(?:users|home)/[^\s<>\"']*")
CREDENTIAL_PATTERN = re.compile(
    r"[?&](sid|sig|exp|token|secret|password)\s*=", re.IGNORECASE
)


def _relative_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _audit_text(relative_path: str, text: str) -> list[str]:
    findings: list[str] = []
    folded_text = text.casefold()

    for term in FORBIDDEN_TERMS:
        if term.casefold() in folded_text:
            findings.append(f"forbidden-term: {relative_path}: {term}")

    for path_kind, pattern in (
        ("Windows", WINDOWS_PATH_PATTERN),
        ("Unix", UNIX_PATH_PATTERN),
    ):
        if pattern.search(text):
            findings.append(f"absolute-path: {relative_path}: {path_kind}")

    for match in CREDENTIAL_PATTERN.finditer(text):
        findings.append(
            f"credential-param: {relative_path}: {match.group(1).casefold()}"
        )

    for match in URI_PATTERN.finditer(text):
        uri = match.group()
        is_windows_path = (
            len(match.group("scheme")) == 1
            and match.group("body").startswith("\\")
        )
        if is_windows_path:
            continue
        has_suspicious_prefix = (
            match.start() > 0
            and text[match.start() - 1] not in URI_START_BOUNDARIES
        )
        if has_suspicious_prefix or uri not in APPROVED_URLS:
            findings.append(f"unapproved-url: {relative_path}: {uri}")

    return findings


def audit_showcase(root: Path) -> list[str]:
    """Return privacy findings for a proposed public showcase directory."""
    try:
        root_exists = root.exists()
        root_is_directory = root.is_dir() if root_exists else False
    except OSError:
        return ["root-error: .: unable to inspect showcase root"]

    if not root_exists or not root_is_directory:
        return ["invalid-root: .: showcase root is missing or is not a directory"]

    findings: list[str] = []
    public_paths: list[Path] = []
    walk_errors: list[OSError] = []
    try:
        for current_dir, directory_names, file_names in os.walk(
            root,
            topdown=True,
            onerror=walk_errors.append,
            followlinks=False,
        ):
            directory_names[:] = [
                name for name in directory_names if name != ".git"
            ]
            current_path = Path(current_dir)
            for file_name in file_names:
                path = current_path / file_name
                relative = path.relative_to(root)
                if ".git" in relative.parts:
                    continue
                public_paths.append(path)
    except OSError as error:
        walk_errors.append(error)

    if walk_errors:
        findings.append("scan-error: .: unable to enumerate complete public tree")

    paths_by_name = {
        _relative_name(path, root): path
        for path in sorted(public_paths, key=lambda item: _relative_name(item, root))
    }
    for required_path in PUBLIC_FILES:
        if required_path not in paths_by_name:
            findings.append(f"missing-file: {required_path}")

    for relative_path, path in paths_by_name.items():
        if relative_path not in PUBLIC_FILES:
            findings.append(f"extra-file: {relative_path}")

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"decode-error: {relative_path}: invalid UTF-8")
            continue
        except OSError:
            findings.append(f"read-error: {relative_path}: unable to read public file")
            continue

        if any(
            (ord(character) < 32 and character not in "\t\n\r\f")
            or 127 <= ord(character) <= 159
            for character in text
        ):
            findings.append(f"binary-content: {relative_path}: control bytes")
            continue

        findings.extend(_audit_text(relative_path, text))

    return findings
