"""Fail-closed privacy audit for the public README-only showcase tree."""

import html
import os
import re
import stat
from pathlib import Path


TEXT_FILES = frozenset({".gitignore", "README.md"})
GIF_FILES = frozenset(
    {"assets/workflow-demo.gif", "assets/local-recording.gif"}
)
WEBP_FILES = frozenset(
    {
        "assets/workflow-demo-static.webp",
        "assets/local-recording-static.webp",
        "assets/step-01-access.webp",
        "assets/step-02-overview.webp",
        "assets/step-03-permissions.webp",
        "assets/step-04-mode.webp",
        "assets/step-05-recording.webp",
        "assets/step-06-local-video-save.webp",
        "assets/step-07-synthetic-feedback.webp",
        "assets/step-08-local-zip-download.webp",
        "assets/step-09-confirmation.webp",
    }
)
PUBLIC_FILES = tuple(sorted(TEXT_FILES | GIF_FILES | WEBP_FILES))
APPROVED_URLS = {
    "https://physical-stimulation-session-recorder.streamlit.app",
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
WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?<![a-z0-9])[a-z]:+\\[^\s<>\"']+")
UNIX_PATH_PATTERN = re.compile(r"(?i)(?<![a-z0-9])/(?:users|home)/[^\s<>\"']*")
CREDENTIAL_PATTERN = re.compile(
    r"[?&](sid|sig|exp|token|secret|password)\s*=", re.IGNORECASE
)


def _relative_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_reparse_point(file_info: object) -> bool:
    attributes = getattr(file_info, "st_file_attributes", 0) or 0
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0
    return bool(attributes & reparse_flag)


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
    decoded_text = html.unescape(text)
    folded_text = decoded_text.casefold()

    for term in FORBIDDEN_TERMS:
        if term.casefold() in folded_text:
            findings.append(f"forbidden-term: {relative_path}")

    for path_kind, pattern in (
        ("Windows", WINDOWS_PATH_PATTERN),
        ("Unix", UNIX_PATH_PATTERN),
    ):
        if pattern.search(decoded_text):
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


def _read_sub_blocks(data: bytes, position: int) -> tuple[bytes, int]:
    parts: list[bytes] = []
    while position < len(data):
        block_size = data[position]
        position += 1
        if block_size == 0:
            break
        expected_end = position + block_size
        block_end = min(expected_end, len(data))
        parts.append(data[position:block_end])
        position = block_end
        if block_end < expected_end:
            break
    return b"".join(parts), position


def _gif_text_metadata(data: bytes) -> list[bytes]:
    if len(data) < 13:
        return []

    packed_fields = data[10]
    position = 13
    if packed_fields & 0x80:
        position += 3 * (2 ** ((packed_fields & 0x07) + 1))

    metadata: list[bytes] = []
    while position < len(data):
        marker = data[position]
        position += 1
        if marker == 0x3B:
            break
        if marker == 0x2C:
            if position + 9 > len(data):
                break
            image_fields = data[position + 8]
            position += 9
            if image_fields & 0x80:
                position += 3 * (2 ** ((image_fields & 0x07) + 1))
            if position >= len(data):
                break
            position += 1
            _, position = _read_sub_blocks(data, position)
            continue
        if marker != 0x21 or position >= len(data):
            break

        extension_type = data[position]
        position += 1
        if extension_type == 0xFE:
            text, position = _read_sub_blocks(data, position)
            metadata.append(text)
        elif extension_type == 0x01:
            if position >= len(data):
                break
            header_size = data[position]
            position = min(position + 1 + header_size, len(data))
            text, position = _read_sub_blocks(data, position)
            metadata.append(text)
        elif extension_type == 0xFF:
            if position >= len(data):
                break
            identifier_size = data[position]
            position += 1
            identifier_end = min(position + identifier_size, len(data))
            identifier = data[position:identifier_end]
            position = identifier_end
            application_data, position = _read_sub_blocks(data, position)
            if identifier.startswith(b"XMP"):
                metadata.append(application_data)
        else:
            _, position = _read_sub_blocks(data, position)

    return metadata


def _webp_text_metadata(data: bytes) -> list[bytes]:
    metadata: list[bytes] = []
    position = 12
    while position + 8 <= len(data):
        chunk_type = data[position : position + 4]
        chunk_size = int.from_bytes(data[position + 4 : position + 8], "little")
        chunk_start = position + 8
        chunk_end = min(chunk_start + chunk_size, len(data))
        if chunk_type in {b"EXIF", b"XMP "}:
            metadata.append(data[chunk_start:chunk_end])
        if chunk_end < chunk_start + chunk_size:
            break
        position = chunk_end + (chunk_size % 2)
    return metadata


def _audit_binary_metadata(relative_path: str, payloads: list[bytes]) -> list[str]:
    findings: list[str] = []
    for payload in payloads:
        text = payload.decode("utf-8", errors="ignore")
        for finding in _audit_text(relative_path, text):
            category = finding.partition(":")[0]
            redacted_finding = f"{category}: {relative_path}"
            if redacted_finding not in findings:
                findings.append(redacted_finding)
    return findings


def audit_showcase(root: Path) -> list[str]:
    """Return privacy findings for a proposed public showcase directory."""
    try:
        root_info = os.lstat(root)
    except FileNotFoundError:
        return ["invalid-root: .: showcase root is missing or is not a directory"]
    except (OSError, ValueError):
        return ["root-error: .: unable to inspect showcase root"]

    if not stat.S_ISDIR(root_info.st_mode) or _is_reparse_point(root_info):
        return ["invalid-root: .: showcase root must be a regular directory"]

    try:
        root_exists = root.exists()
        root_is_directory = root.is_dir() if root_exists else False
    except OSError:
        return ["root-error: .: unable to inspect showcase root"]

    if not root_exists or not root_is_directory:
        return ["invalid-root: .: showcase root is missing or is not a directory"]

    findings: list[str] = []
    entries_by_name: dict[str, tuple[Path, int, bool, int]] = {}
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
                    file_info = os.lstat(path)
                except OSError:
                    entry_errors.append(relative_path)
                    continue
                mode = file_info.st_mode
                is_reparse = _is_reparse_point(file_info)
                entries_by_name[relative_path] = (
                    path,
                    mode,
                    is_reparse,
                    getattr(file_info, "st_nlink", 1),
                )
                if stat.S_ISDIR(mode) and not is_reparse:
                    traversable_directories.append(directory_name)
            directory_names[:] = traversable_directories

            for file_name in file_names:
                if file_name == ".git":
                    continue
                path = current_path / file_name
                relative_path = _relative_name(path, root)
                try:
                    file_info = os.lstat(path)
                except OSError:
                    entry_errors.append(relative_path)
                    continue
                entries_by_name[relative_path] = (
                    path,
                    file_info.st_mode,
                    _is_reparse_point(file_info),
                    getattr(file_info, "st_nlink", 1),
                )
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
        if entry is None or not stat.S_ISREG(entry[1]) or entry[2]:
            findings.append(f"missing-file: {required_path}")

    assets_entry = entries_by_name.get("assets")
    if (
        assets_entry is None
        or not stat.S_ISDIR(assets_entry[1])
        or assets_entry[2]
    ):
        findings.append("missing-directory: assets")

    regular_files: list[tuple[str, Path]] = []
    for relative_path, (path, mode, is_reparse, link_count) in sorted(
        entries_by_name.items()
    ):
        expected_file = relative_path in PUBLIC_FILES
        expected_directory = relative_path == "assets"
        if is_reparse:
            findings.append(f"special-entry: {relative_path}")
        elif stat.S_ISREG(mode):
            if not expected_file:
                findings.append(f"extra-file: {relative_path}")
            elif link_count > 1:
                findings.append(f"hardlink: {relative_path}")
            else:
                regular_files.append((relative_path, path))
        elif stat.S_ISDIR(mode):
            if not expected_directory:
                findings.append(f"extra-entry: {relative_path}")
        else:
            findings.append(f"special-entry: {relative_path}")

    for relative_path, path in regular_files:
        if relative_path in GIF_FILES or relative_path in WEBP_FILES:
            try:
                data = path.read_bytes()
            except OSError:
                findings.append(f"read-error: {relative_path}")
                continue

            if relative_path in GIF_FILES:
                if not data.startswith((b"GIF87a", b"GIF89a")):
                    findings.append(f"invalid-signature: {relative_path}")
                    continue
                metadata = _gif_text_metadata(data)
            else:
                if not (
                    len(data) >= 12
                    and data.startswith(b"RIFF")
                    and data[8:12] == b"WEBP"
                ):
                    findings.append(f"invalid-signature: {relative_path}")
                    continue
                metadata = _webp_text_metadata(data)

            findings.extend(_audit_binary_metadata(relative_path, metadata))
            continue

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
