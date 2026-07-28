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
        "assets/palette.webp",
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
MAX_GIF_FILE_BYTES = 8 * 1024 * 1024 - 1
MAX_GIF_TOTAL_BYTES = 14 * 1024 * 1024 - 1
MAX_WEBP_FILE_BYTES = 350 * 1024 - 1
MAX_METADATA_BYTES = 64 * 1024
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
XML_ENCODING_PATTERN = re.compile(
    r"\A<\?xml\s+[^?]*?\bencoding\s*=\s*(['\"])([^'\"]+)\1",
    re.IGNORECASE,
)
AMBIGUOUS_BINARY_TEXT_PATTERN = re.compile(
    rb"(?:[\x09\x0a\x0d\x20-\x7e]\x00){3,}"
    rb"|(?:\x00[\x09\x0a\x0d\x20-\x7e]){3,}"
)


class _InvalidMediaError(ValueError):
    pass


class _MetadataParseError(ValueError):
    pass


class _MetadataDecodeError(ValueError):
    pass


class _UnsupportedBinaryMetadataError(ValueError):
    pass


class _FileTooLargeError(ValueError):
    pass


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


def _read_sub_blocks(
    data: bytes,
    position: int,
    *,
    collect: bool = False,
    metadata_used: int = 0,
) -> tuple[bytes, int, int]:
    payload = bytearray()
    payload_size = 0
    while True:
        if position >= len(data):
            raise _InvalidMediaError
        block_size = data[position]
        position += 1
        if block_size == 0:
            return bytes(payload), position, payload_size
        block_end = position + block_size
        if block_end > len(data):
            raise _InvalidMediaError
        payload_size += block_size
        if collect:
            if metadata_used + payload_size > MAX_METADATA_BYTES:
                raise _MetadataParseError
            payload.extend(data[position:block_end])
        position = block_end


def _gif_text_metadata(data: bytes) -> list[bytes]:
    if len(data) < 13:
        raise _InvalidMediaError

    packed_fields = data[10]
    position = 13
    if packed_fields & 0x80:
        position += 3 * (2 ** ((packed_fields & 0x07) + 1))
    if position > len(data) or data[6:8] == b"\x00\x00" or data[8:10] == b"\x00\x00":
        raise _InvalidMediaError

    metadata: list[bytes] = []
    metadata_used = 0
    found_image = False
    while True:
        if position >= len(data):
            raise _InvalidMediaError
        marker = data[position]
        position += 1
        if marker == 0x3B:
            if position != len(data) or not found_image:
                raise _InvalidMediaError
            return metadata
        if marker == 0x2C:
            if position + 9 > len(data):
                raise _InvalidMediaError
            if data[position + 4 : position + 6] == b"\x00\x00":
                raise _InvalidMediaError
            if data[position + 6 : position + 8] == b"\x00\x00":
                raise _InvalidMediaError
            image_fields = data[position + 8]
            position += 9
            if image_fields & 0x80:
                position += 3 * (2 ** ((image_fields & 0x07) + 1))
            if position >= len(data):
                raise _InvalidMediaError
            lzw_code_size = data[position]
            if not 2 <= lzw_code_size <= 8:
                raise _InvalidMediaError
            position += 1
            _, position, image_data_size = _read_sub_blocks(data, position)
            if image_data_size == 0:
                raise _InvalidMediaError
            found_image = True
            continue
        if marker != 0x21 or position >= len(data):
            raise _InvalidMediaError

        extension_type = data[position]
        position += 1
        if extension_type == 0xFE:
            text, position, text_size = _read_sub_blocks(
                data, position, collect=True, metadata_used=metadata_used
            )
            metadata_used += text_size
            metadata.append(text)
        elif extension_type == 0x01:
            if position >= len(data) or data[position] != 12:
                raise _InvalidMediaError
            header_size = data[position]
            position += 1 + header_size
            if position > len(data):
                raise _InvalidMediaError
            text, position, text_size = _read_sub_blocks(
                data, position, collect=True, metadata_used=metadata_used
            )
            metadata_used += text_size
            metadata.append(text)
        elif extension_type == 0xFF:
            if position >= len(data) or data[position] != 11:
                raise _InvalidMediaError
            identifier_size = data[position]
            position += 1
            identifier_end = position + identifier_size
            if identifier_end > len(data):
                raise _InvalidMediaError
            identifier = data[position:identifier_end]
            position = identifier_end
            is_metadata = identifier.startswith(b"XMP")
            application_data, position, payload_size = _read_sub_blocks(
                data,
                position,
                collect=is_metadata,
                metadata_used=metadata_used,
            )
            if is_metadata:
                metadata_used += payload_size
                metadata.append(application_data)
        elif extension_type == 0xF9:
            if position + 6 > len(data) or data[position] != 4:
                raise _InvalidMediaError
            if data[position + 5] != 0:
                raise _InvalidMediaError
            position += 6
        else:
            _, position, _ = _read_sub_blocks(data, position)


def _webp_text_metadata(data: bytes) -> list[bytes]:
    if len(data) < 12 or int.from_bytes(data[4:8], "little") != len(data) - 8:
        raise _InvalidMediaError

    metadata: list[bytes] = []
    metadata_used = 0
    found_image = False
    found_exif = False
    position = 12
    while position < len(data):
        if position + 8 > len(data):
            raise _InvalidMediaError
        chunk_type = data[position : position + 4]
        if any(byte < 0x20 or byte > 0x7E for byte in chunk_type):
            raise _InvalidMediaError
        chunk_size = int.from_bytes(data[position + 4 : position + 8], "little")
        chunk_start = position + 8
        chunk_end = chunk_start + chunk_size
        padded_end = chunk_end + (chunk_size % 2)
        if padded_end > len(data):
            raise _InvalidMediaError
        if chunk_size % 2 and data[chunk_end] != 0:
            raise _InvalidMediaError
        if chunk_type == b"EXIF":
            found_exif = True
        elif chunk_type == b"XMP ":
            if metadata_used + chunk_size > MAX_METADATA_BYTES:
                raise _MetadataParseError
            metadata.append(data[chunk_start:chunk_end])
            metadata_used += chunk_size
        if chunk_type in {b"VP8 ", b"VP8L"}:
            if chunk_size == 0:
                raise _InvalidMediaError
            found_image = True
        elif chunk_type == b"ANMF":
            if chunk_size < 16:
                raise _InvalidMediaError
            found_image = True
        elif chunk_type == b"VP8X" and chunk_size != 10:
            raise _InvalidMediaError
        position = padded_end
    if not found_image:
        raise _InvalidMediaError
    if found_exif:
        raise _UnsupportedBinaryMetadataError
    return metadata


def _decode_metadata(payload: bytes) -> str:
    bom_encoding: str | None = None
    if payload.startswith(b"\xef\xbb\xbf"):
        bom_encoding = "utf-8-sig"
    elif payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        bom_encoding = "utf-16"

    observed_utf16: str | None = None
    if payload.startswith(b"<\x00?\x00x\x00m\x00l\x00"):
        observed_utf16 = "utf-16-le"
    elif payload.startswith(b"\x00<\x00?\x00x\x00m\x00l"):
        observed_utf16 = "utf-16-be"

    encoding = bom_encoding or observed_utf16 or "utf-8"
    try:
        text = payload.decode(encoding, errors="strict")
    except (LookupError, UnicodeError) as error:
        raise _MetadataDecodeError from error
    if encoding in {"utf-8", "utf-8-sig"} and AMBIGUOUS_BINARY_TEXT_PATTERN.search(
        payload
    ):
        raise _MetadataDecodeError

    declaration = XML_ENCODING_PATTERN.search(text)
    if declaration is None:
        if observed_utf16 is not None:
            raise _MetadataDecodeError
        return text

    declared = declaration.group(2).casefold().replace("_", "-")
    aliases = {
        "utf-8": "utf-8",
        "utf8": "utf-8",
        "utf-16": "utf-16",
        "utf16": "utf-16",
        "utf-16le": "utf-16-le",
        "utf16le": "utf-16-le",
        "utf-16be": "utf-16-be",
        "utf16be": "utf-16-be",
    }
    canonical = aliases.get(declared)
    if canonical is None:
        raise _MetadataDecodeError

    actual = encoding
    if actual == "utf-8-sig":
        actual = "utf-8"
    elif actual == "utf-16":
        actual = "utf-16-le" if payload.startswith(b"\xff\xfe") else "utf-16-be"
    if canonical == "utf-16":
        if actual not in {"utf-16-le", "utf-16-be"}:
            raise _MetadataDecodeError
    elif canonical != actual:
        raise _MetadataDecodeError
    return text


def _audit_binary_metadata(relative_path: str, payloads: list[bytes]) -> list[str]:
    findings: list[str] = []
    for payload in payloads:
        try:
            text = _decode_metadata(payload)
        except (_MetadataDecodeError, MemoryError):
            finding = f"metadata-decode-error: {relative_path}"
            if finding not in findings:
                findings.append(finding)
            continue
        for finding in _audit_text(relative_path, text):
            category = finding.partition(":")[0]
            redacted_finding = f"{category}: {relative_path}"
            if redacted_finding not in findings:
                findings.append(redacted_finding)
    return findings


def _read_limited_file(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise _FileTooLargeError
    return data


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
    entries_by_name: dict[str, tuple[Path, int, bool, int, int]] = {}
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
                    getattr(file_info, "st_size", 0),
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
                    getattr(file_info, "st_size", 0),
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

    regular_files: list[tuple[str, Path, int]] = []
    for relative_path, (path, mode, is_reparse, link_count, file_size) in sorted(
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
                regular_files.append((relative_path, path, file_size))
        elif stat.S_ISDIR(mode):
            if not expected_directory:
                findings.append(f"extra-entry: {relative_path}")
        else:
            findings.append(f"special-entry: {relative_path}")

    gif_total_size = sum(
        file_size
        for relative_path, _, file_size in regular_files
        if relative_path in GIF_FILES
    )
    gif_total_too_large = gif_total_size > MAX_GIF_TOTAL_BYTES
    if gif_total_too_large:
        findings.append("gif-total-too-large: .")

    for relative_path, path, file_size in regular_files:
        if relative_path in GIF_FILES or relative_path in WEBP_FILES:
            if relative_path in GIF_FILES and gif_total_too_large:
                continue
            file_limit = (
                MAX_GIF_FILE_BYTES
                if relative_path in GIF_FILES
                else MAX_WEBP_FILE_BYTES
            )
            if file_size < 0 or file_size > file_limit:
                findings.append(f"file-too-large: {relative_path}")
                continue
            try:
                data = _read_limited_file(path, file_limit)
            except _FileTooLargeError:
                findings.append(f"file-too-large: {relative_path}")
                continue
            except (OSError, MemoryError):
                findings.append(f"read-error: {relative_path}")
                continue

            if relative_path in GIF_FILES:
                if not data.startswith((b"GIF87a", b"GIF89a")):
                    findings.append(f"invalid-signature: {relative_path}")
                    continue
                try:
                    metadata = _gif_text_metadata(data)
                except _MetadataParseError:
                    findings.append(f"metadata-parse-error: {relative_path}")
                    continue
                except (_InvalidMediaError, MemoryError):
                    findings.append(f"invalid-media: {relative_path}")
                    continue
            else:
                if not (
                    len(data) >= 12
                    and data.startswith(b"RIFF")
                    and data[8:12] == b"WEBP"
                ):
                    findings.append(f"invalid-signature: {relative_path}")
                    continue
                try:
                    metadata = _webp_text_metadata(data)
                except _UnsupportedBinaryMetadataError:
                    findings.append(
                        f"unsupported-binary-metadata: {relative_path}"
                    )
                    continue
                except _MetadataParseError:
                    findings.append(f"metadata-parse-error: {relative_path}")
                    continue
                except (_InvalidMediaError, MemoryError):
                    findings.append(f"invalid-media: {relative_path}")
                    continue

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
