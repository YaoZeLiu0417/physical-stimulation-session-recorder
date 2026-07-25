"""Fail-closed privacy audit for the public README-only showcase tree."""

import html
import os
import re
import stat
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
    r"(?:(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*):|(?P<protocol_relative>//))"
    r"(?P<body>[^\s<>\"'`]+)"
)
URI_START_BOUNDARIES = frozenset(" \t\r\n([{<>\"'`=")
WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?<![a-z0-9])[a-z]:\\[^\s<>\"']+")
UNIX_PATH_PATTERN = re.compile(r"(?i)(?<![a-z0-9])/(?:users|home)/[^\s<>\"']*")
CREDENTIAL_PATTERN = re.compile(
    r"[?&](sid|sig|exp|token|secret|password)\s*=", re.IGNORECASE
)


def _relative_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_approved_uri_token(text: str, match: re.Match[str]) -> bool:
    uri = match.group()
    if uri in APPROVED_URLS:
        return True
    if match.start() == 0 or text[match.start() - 1] != "(":
        return False
    return any(
        uri in (f"{approved_url})", f"{approved_url}).")
        for approved_url in APPROVED_URLS
    )


def _audit_text(relative_path: str, text: str) -> list[str]:
    findings: list[str] = []
    folded_text = text.casefold()
    decoded_text = html.unescape(text)

    for term in FORBIDDEN_TERMS:
        if term.casefold() in folded_text:
            findings.append(f"forbidden-term: {relative_path}")

    for path_kind, pattern in (
        ("Windows", WINDOWS_PATH_PATTERN),
        ("Unix", UNIX_PATH_PATTERN),
    ):
        if pattern.search(text):
            findings.append(f"absolute-path: {relative_path}: {path_kind}")

    for match in CREDENTIAL_PATTERN.finditer(decoded_text):
        findings.append(
            f"credential-param: {relative_path}: {match.group(1).casefold()}"
        )

    for match in URI_PATTERN.finditer(decoded_text):
        scheme = match.group("scheme")
        is_windows_path = (
            scheme is not None
            and len(scheme) == 1
            and match.group("body").startswith("\\")
        )
        if is_windows_path:
            continue
        has_suspicious_prefix = (
            match.start() > 0
            and decoded_text[match.start() - 1] not in URI_START_BOUNDARIES
        )
        if has_suspicious_prefix or not _is_approved_uri_token(decoded_text, match):
            findings.append(f"unapproved-url: {relative_path}")

    return findings


def audit_showcase(root: Path) -> list[str]:
    """Return privacy findings for a proposed public showcase directory."""
    try:
        root_mode = os.lstat(root).st_mode
    except FileNotFoundError:
        return ["invalid-root: .: showcase root is missing or is not a directory"]
    except (OSError, ValueError):
        return ["root-error: .: unable to inspect showcase root"]

    if not stat.S_ISDIR(root_mode):
        return ["invalid-root: .: showcase root must be a regular directory"]

    try:
        root_exists = root.exists()
        root_is_directory = root.is_dir() if root_exists else False
    except OSError:
        return ["root-error: .: unable to inspect showcase root"]

    if not root_exists or not root_is_directory:
        return ["invalid-root: .: showcase root is missing or is not a directory"]

    findings: list[str] = []
    entries_by_name: dict[str, tuple[Path, int]] = {}
    entry_errors: list[str] = []
    walk_errors: list[OSError] = []
    try:
        for current_dir, directory_names, file_names in os.walk(
            root,
            topdown=True,
            onerror=walk_errors.append,
            followlinks=False,
        ):
            current_path = Path(current_dir)
            traversable_directories: list[str] = []
            for directory_name in directory_names:
                if directory_name == ".git":
                    continue
                path = current_path / directory_name
                relative_path = _relative_name(path, root)
                try:
                    mode = os.lstat(path).st_mode
                except OSError:
                    entry_errors.append(relative_path)
                    continue
                entries_by_name[relative_path] = (path, mode)
                if stat.S_ISDIR(mode):
                    traversable_directories.append(directory_name)
            directory_names[:] = traversable_directories

            for file_name in file_names:
                if file_name == ".git":
                    continue
                path = current_path / file_name
                relative_path = _relative_name(path, root)
                try:
                    mode = os.lstat(path).st_mode
                except OSError:
                    entry_errors.append(relative_path)
                    continue
                entries_by_name[relative_path] = (path, mode)
    except OSError as error:
        walk_errors.append(error)

    if walk_errors:
        findings.append("scan-error: .: unable to enumerate complete public tree")
    findings.extend(
        f"entry-error: {relative_path}: unable to inspect public entry"
        for relative_path in sorted(set(entry_errors))
    )

    for required_path in PUBLIC_FILES:
        entry = entries_by_name.get(required_path)
        if entry is None or not stat.S_ISREG(entry[1]):
            findings.append(f"missing-file: {required_path}")

    assets_entry = entries_by_name.get("assets")
    if assets_entry is None or not stat.S_ISDIR(assets_entry[1]):
        findings.append("missing-directory: assets")

    regular_files: list[tuple[str, Path]] = []
    for relative_path, (path, mode) in sorted(entries_by_name.items()):
        expected_file = relative_path in PUBLIC_FILES
        expected_directory = relative_path == "assets"
        if stat.S_ISREG(mode):
            if not expected_file:
                findings.append(f"extra-file: {relative_path}")
            regular_files.append((relative_path, path))
        elif stat.S_ISDIR(mode):
            if not expected_directory:
                findings.append(f"extra-entry: {relative_path}")
        else:
            findings.append(f"special-entry: {relative_path}")

    for relative_path, path in regular_files:
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
