import io
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import showcase_audit
from showcase_audit import FORBIDDEN_TERMS, audit_showcase


APP_URL = "https://physical-stimulation-session-recorder.streamlit.app"
REPARSE_POINT = 0x400
EXPECTED_TEXT_FILES = frozenset({".gitignore", "README.md"})
EXPECTED_GIF_FILES = frozenset(
    {"assets/workflow-demo.gif", "assets/local-recording.gif"}
)
EXPECTED_WEBP_FILES = frozenset(
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
EXPECTED_PUBLIC_FILES = tuple(
    sorted(EXPECTED_TEXT_FILES | EXPECTED_GIF_FILES | EXPECTED_WEBP_FILES)
)
EXPECTED_MAX_GIF_FILE_BYTES = 8 * 1024 * 1024 - 1
EXPECTED_MAX_GIF_TOTAL_BYTES = 14 * 1024 * 1024 - 1
EXPECTED_MAX_WEBP_FILE_BYTES = 350 * 1024 - 1
EXPECTED_MAX_METADATA_BYTES = 64 * 1024
EXPECTED_FORBIDDEN_TERMS = (
    "tavns",
    "nssi",
    "sicq",
    "dshi",
    "fasm",
    "自伤",
    "自杀",
    "量表",
    "问卷",
    "评分规则",
)


def _public_showcase_readme() -> Path | None:
    candidates = (
        Path(__file__).resolve().parents[2]
        / "physical-stimulation-session-recorder-showcase"
        / "README.md",
        Path(__file__).resolve().parents[4]
        / "physical-stimulation-session-recorder-showcase"
        / "README.md",
    )
    return next((path for path in candidates if path.is_file()), None)


def _sub_blocks(payload: bytes, block_size: int = 255) -> bytes:
    assert 1 <= block_size <= 255
    return b"".join(
        bytes([len(payload[offset : offset + block_size])])
        + payload[offset : offset + block_size]
        for offset in range(0, len(payload), block_size)
    ) + b"\x00"


def _gif_bytes(
    metadata: bytes = b"",
    image_data: bytes = b"\x44\x01",
    metadata_kind: str = "comment",
    metadata_block_size: int = 255,
) -> bytes:
    extension = b""
    if metadata:
        metadata_blocks = _sub_blocks(metadata, metadata_block_size)
        if metadata_kind == "comment":
            extension = b"\x21\xfe" + metadata_blocks
        elif metadata_kind == "application":
            extension = b"\x21\xff\x0bXMP DataXMP" + metadata_blocks
        elif metadata_kind == "plain-text":
            extension = b"\x21\x01\x0c" + (b"\x00" * 12) + metadata_blocks
        else:
            raise ValueError(f"unsupported metadata kind: {metadata_kind}")
    return (
        b"GIF89a"
        b"\x01\x00\x01\x00\x80\x00\x00"
        b"\x00\x00\x00\xff\xff\xff"
        + extension
        + b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00"
        b"\x02"
        + _sub_blocks(image_data)
        + b"\x3b"
    )


def _riff_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    padding = b"\x00" if len(payload) % 2 else b""
    return chunk_type + len(payload).to_bytes(4, "little") + payload + padding


def _webp_bytes(
    metadata: bytes = b"",
    image_data: bytes = b"\x2f\x00\x00\x00\x00\x07\xd0\xff\xfe\xf7\xbf\xff\x81\x88\xe8\x7f\x00",
    metadata_type: bytes = b"XMP ",
    additional_metadata: tuple[tuple[bytes, bytes], ...] = (),
) -> bytes:
    metadata_chunks: list[tuple[bytes, bytes]] = []
    if metadata:
        metadata_chunks.append((metadata_type, metadata))
    metadata_chunks.extend(additional_metadata)

    chunks = b""
    if metadata_chunks:
        flags = 0
        if any(chunk_type == b"EXIF" for chunk_type, _ in metadata_chunks):
            flags |= 0x08
        if any(chunk_type == b"XMP " for chunk_type, _ in metadata_chunks):
            flags |= 0x04
        chunks += _riff_chunk(b"VP8X", bytes([flags]) + (b"\x00" * 9))
    chunks += _riff_chunk(b"VP8L", image_data)
    for chunk_type, payload in metadata_chunks:
        chunks += _riff_chunk(chunk_type, payload)
    return b"RIFF" + (len(chunks) + 4).to_bytes(4, "little") + b"WEBP" + chunks


def _tiff_with_raw_description(description: bytes) -> bytes:
    data_offset = 8 + 2 + 12 + 4
    entry = (
        b"\x01\x0e"
        b"\x00\x02"
        + len(description).to_bytes(4, "big")
        + data_offset.to_bytes(4, "big")
    )
    return (
        b"MM\x00\x2a\x00\x00\x00\x08"
        + b"\x00\x01"
        + entry
        + b"\x00\x00\x00\x00"
        + description
    )


def _write_safe_tree(root: Path) -> None:
    (root / "assets").mkdir(parents=True)
    (root / ".gitignore").write_text(
        "*\n!.gitignore\n!README.md\n!assets/\n", encoding="utf-8"
    )
    (root / "README.md").write_text(
        f"# Public demo\n\n[Open the demo]({APP_URL}).\n", encoding="utf-8"
    )
    for relative_path in EXPECTED_GIF_FILES:
        (root / relative_path).write_bytes(_gif_bytes())
    for relative_path in EXPECTED_WEBP_FILES:
        (root / relative_path).write_bytes(_webp_bytes())


def _joined_findings(root: Path) -> str:
    return "\n".join(audit_showcase(root))


def _assert_pillow_valid(data: bytes) -> None:
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()


def _with_file_type(result: os.stat_result, file_type: int) -> os.stat_result:
    values = list(result)
    values[stat.ST_MODE] = file_type | stat.S_IMODE(result.st_mode)
    return os.stat_result(values)


def _with_reparse_point(result: os.stat_result) -> SimpleNamespace:
    return SimpleNamespace(
        st_mode=result.st_mode,
        st_file_attributes=REPARSE_POINT,
    )


def test_safe_tree_passes_and_git_contents_are_ignored(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    git_leak = tmp_path / ".git" / "objects" / "leak"
    git_leak.parent.mkdir(parents=True)
    git_leak.write_text(
        "tavns https://example.test/?token=secret C:\\private\\file.txt",
        encoding="utf-8",
    )

    assert audit_showcase(tmp_path) == []


def test_public_file_inventory_matches_fancy_showcase_contract() -> None:
    assert showcase_audit.TEXT_FILES == EXPECTED_TEXT_FILES
    assert showcase_audit.GIF_FILES == EXPECTED_GIF_FILES
    assert showcase_audit.WEBP_FILES == EXPECTED_WEBP_FILES
    assert showcase_audit.PUBLIC_FILES == EXPECTED_PUBLIC_FILES
    assert showcase_audit.MAX_GIF_FILE_BYTES == EXPECTED_MAX_GIF_FILE_BYTES
    assert showcase_audit.MAX_GIF_TOTAL_BYTES == EXPECTED_MAX_GIF_TOTAL_BYTES
    assert showcase_audit.MAX_WEBP_FILE_BYTES == EXPECTED_MAX_WEBP_FILE_BYTES
    assert showcase_audit.MAX_METADATA_BYTES == EXPECTED_MAX_METADATA_BYTES


def test_approved_markdown_url_passes(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(
        f"[demo]({APP_URL})\n", encoding="utf-8"
    )

    assert audit_showcase(tmp_path) == []


def test_html_encoded_approved_url_passes(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    encoded_app_url = APP_URL.replace(":", "&#58;")
    (tmp_path / "README.md").write_text(
        f'<a href="{encoded_app_url}">demo</a>\n', encoding="utf-8"
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

    for relative_path in EXPECTED_PUBLIC_FILES:
        assert f"missing-file: {relative_path}" in findings


def test_wrong_extension_is_extra_and_does_not_replace_required_asset(
    tmp_path: Path,
) -> None:
    _write_safe_tree(tmp_path)
    required_path = tmp_path / "assets" / "workflow-demo.gif"
    required_path.rename(required_path.with_suffix(".webp"))

    findings = _joined_findings(tmp_path)

    assert "missing-file: assets/workflow-demo.gif" in findings
    assert "extra-file: assets/workflow-demo.webp" in findings


@pytest.mark.parametrize(
    ("relative_path", "content"),
    [
        ("assets/workflow-demo.gif", b"NOTGIF"),
        ("assets/step-01-access.webp", b"RIFF\x04\x00\x00\x00NOPE"),
    ],
)
def test_binary_asset_signature_must_match_declared_type(
    tmp_path: Path, relative_path: str, content: bytes
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / relative_path).write_bytes(content)

    findings = _joined_findings(tmp_path)

    assert f"invalid-signature: {relative_path}" in findings
    assert content.decode("ascii") not in findings


@pytest.mark.parametrize("gif_signature", [b"GIF87a", b"GIF89a"])
def test_both_valid_gif_signatures_pass(
    tmp_path: Path, gif_signature: bytes
) -> None:
    _write_safe_tree(tmp_path)
    gif_path = tmp_path / "assets" / "workflow-demo.gif"
    gif_path.write_bytes(gif_signature + _gif_bytes()[6:])

    assert audit_showcase(tmp_path) == []


def test_public_readme_leads_with_complete_questionnaire_story() -> None:
    readme_path = _public_showcase_readme()
    if readme_path is None:
        pytest.skip("public showcase clone is not available")
    readme = readme_path.read_text(encoding="utf-8")
    first_viewport = readme.split("## 九步流程", 1)[0]
    required_first_viewport = (
        "# Physical Stimulation Intervention Session Companion",
        "Controlled access",
        "Daily context",
        "Browser-local audio and video",
        "Stepwise structured questionnaire",
        "Local JSON + Excel package",
        "Completion confirmation",
    )

    assert all(item in first_viewport for item in required_first_viewport)
    assert "protected operational questionnaire" in readme.casefold()
    assert "public synthetic demonstration" in readme.casefold()
    assert "no participant-facing scores" in readme.casefold()
    assert all(term.casefold() not in readme.casefold() for term in FORBIDDEN_TERMS)


@pytest.mark.parametrize(
    ("relative_path", "writer"),
    [
        ("assets/workflow-demo.gif", _gif_bytes),
        ("assets/step-01-access.webp", _webp_bytes),
    ],
)
def test_binary_image_payload_is_not_decoded_or_privacy_scanned(
    tmp_path: Path, relative_path: str, writer
) -> None:
    _write_safe_tree(tmp_path)
    image_payload = b"\xff\xfe\x00https://evil.example/?token=tavns C:\\Users\\Secret"
    (tmp_path / relative_path).write_bytes(writer(image_data=image_payload))

    assert audit_showcase(tmp_path) == []


@pytest.mark.parametrize(
    ("metadata", "category"),
    [
        (b"tavns", "forbidden-term"),
        (b"C:\\Users\\Alice\\private.txt", "absolute-path"),
        (b"https://example.test/private?token=value", "credential-param"),
        (b"https://example.test/private", "unapproved-url"),
    ],
)
@pytest.mark.parametrize(
    ("relative_path", "writer"),
    [
        ("assets/workflow-demo.gif", _gif_bytes),
        ("assets/step-01-access.webp", _webp_bytes),
    ],
)
def test_binary_text_metadata_is_privacy_scanned_without_echoing_bytes(
    tmp_path: Path,
    relative_path: str,
    writer,
    metadata: bytes,
    category: str,
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / relative_path).write_bytes(writer(metadata=metadata))

    findings = _joined_findings(tmp_path)

    assert f"{category}: {relative_path}" in findings
    assert metadata.decode("ascii") not in findings


@pytest.mark.parametrize("metadata_kind", ["comment", "application", "plain-text"])
def test_real_gif_fixtures_with_multi_sub_blocks_are_valid_and_scanned(
    tmp_path: Path, metadata_kind: str
) -> None:
    _write_safe_tree(tmp_path)
    data = _gif_bytes(
        metadata=b"public-prefix tavns public-suffix",
        metadata_kind=metadata_kind,
        metadata_block_size=3,
    )
    _assert_pillow_valid(data)
    (tmp_path / "assets" / "workflow-demo.gif").write_bytes(data)

    findings = _joined_findings(tmp_path)

    assert "forbidden-term: assets/workflow-demo.gif" in findings
    assert "tavns" not in findings


def test_real_webp_fixture_with_benign_exif_is_rejected(
    tmp_path: Path,
) -> None:
    _write_safe_tree(tmp_path)
    exif = Image.Exif()
    exif[0x010E] = "public-exif"
    data = _webp_bytes(
        metadata=b"<?xml version='1.0' encoding='UTF-8'?><x>public</x>",
        additional_metadata=((b"EXIF", exif.tobytes()),),
    )
    _assert_pillow_valid(data)
    (tmp_path / "assets" / "step-01-access.webp").write_bytes(data)

    findings = _joined_findings(tmp_path)

    assert findings == "unsupported-binary-metadata: assets/step-01-access.webp"
    assert "public-exif" not in findings


@pytest.mark.parametrize(
    "sensitive_text",
    [
        *(term for term in FORBIDDEN_TERMS if not term.isascii()),
        r"C:\Users\Alice\private.txt",
        "https://example.test/private",
        "https://example.test/private?token=value",
    ],
    ids=[
        "non-ascii-term-1",
        "non-ascii-term-2",
        "non-ascii-term-3",
        "non-ascii-term-4",
        "non-ascii-term-5",
        "absolute-path",
        "url",
        "credential",
    ],
)
@pytest.mark.parametrize(
    "encoding", ["utf-16-le", "utf-16-be"], ids=["little-endian", "big-endian"]
)
def test_opaque_utf16_exif_metadata_fails_closed_without_echoing_content(
    tmp_path: Path, sensitive_text: str, encoding: str
) -> None:
    _write_safe_tree(tmp_path)
    relative_path = "assets/step-01-access.webp"
    exif = _tiff_with_raw_description(sensitive_text.encode(encoding) + b"\x00\x00")
    data = _webp_bytes(metadata=exif, metadata_type=b"EXIF")
    _assert_pillow_valid(data)
    (tmp_path / relative_path).write_bytes(data)

    findings = audit_showcase(tmp_path)

    assert findings == [f"unsupported-binary-metadata: {relative_path}"]
    assert sensitive_text not in "\n".join(findings)


@pytest.mark.parametrize(
    "metadata",
    [
        b"\xef\xbb\xbf" + "tavns".encode("utf-8"),
        b"\xff\xfe" + "tavns".encode("utf-16-le"),
        b"\xfe\xff" + "tavns".encode("utf-16-be"),
        "<?xml version='1.0' encoding='UTF-16LE'?><x>tavns</x>".encode(
            "utf-16-le"
        ),
        b"<?xml version='1.0' encoding='UTF-8'?><x>tavns</x>",
    ],
    ids=["utf8-bom", "utf16le-bom", "utf16be-bom", "xml-utf16le", "xml-utf8"],
)
@pytest.mark.parametrize(
    ("relative_path", "writer"),
    [
        ("assets/workflow-demo.gif", _gif_bytes),
        ("assets/step-01-access.webp", _webp_bytes),
    ],
)
def test_declared_metadata_encodings_are_strictly_decoded_and_scanned(
    tmp_path: Path, relative_path: str, writer, metadata: bytes
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / relative_path).write_bytes(writer(metadata=metadata))

    findings = _joined_findings(tmp_path)

    assert f"forbidden-term: {relative_path}" in findings
    assert "metadata-decode-error" not in findings
    assert "tavns" not in findings


def test_bom_utf16_exif_metadata_is_rejected_as_opaque(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    relative_path = "assets/step-01-access.webp"
    metadata = b"\xff\xfe" + "tavns".encode("utf-16-le")
    (tmp_path / relative_path).write_bytes(
        _webp_bytes(metadata=metadata, metadata_type=b"EXIF")
    )

    findings = _joined_findings(tmp_path)

    assert findings == f"unsupported-binary-metadata: {relative_path}"
    assert "tavns" not in findings


@pytest.mark.parametrize(
    "metadata",
    [
        b"invalid-utf8-\xff-DO_NOT_LOG_THIS",
        b"<?xml version='1.0' encoding='ISO-8859-1'?><x>DO_NOT_LOG_THIS</x>",
        b"<?xml version='1.0' encoding='UTF-16LE'?><x>truncated\x00",
    ],
    ids=["invalid-utf8", "unknown-xml-encoding", "invalid-declared-encoding"],
)
@pytest.mark.parametrize(
    ("relative_path", "writer"),
    [
        ("assets/workflow-demo.gif", _gif_bytes),
        ("assets/step-01-access.webp", _webp_bytes),
    ],
)
def test_undecodable_metadata_fails_closed_without_echoing_content(
    tmp_path: Path, relative_path: str, writer, metadata: bytes
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / relative_path).write_bytes(writer(metadata=metadata))

    findings = _joined_findings(tmp_path)

    assert f"metadata-decode-error: {relative_path}" in findings
    assert "DO_NOT_LOG_THIS" not in findings


@pytest.mark.parametrize(
    "data",
    [
        b"GIF89a",
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00",
        _gif_bytes()[:-1],
        _gif_bytes()[:19] + b"\x00" + _gif_bytes()[20:],
        (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
            b"\x00\x00\x00\xff\xff\xff\x21\xfe\x05abc"
        ),
    ],
    ids=["header-only", "truncated-color-table", "missing-trailer", "bad-marker", "truncated-sub-block"],
)
def test_malformed_gif_container_fails_closed(tmp_path: Path, data: bytes) -> None:
    _write_safe_tree(tmp_path)
    relative_path = "assets/workflow-demo.gif"
    (tmp_path / relative_path).write_bytes(data)

    findings = _joined_findings(tmp_path)

    assert f"invalid-media: {relative_path}" in findings


def _riff(chunks: bytes, declared_size: int | None = None) -> bytes:
    size = len(chunks) + 4 if declared_size is None else declared_size
    return b"RIFF" + size.to_bytes(4, "little") + b"WEBP" + chunks


@pytest.mark.parametrize(
    "data",
    [
        _riff(b""),
        _webp_bytes()[:4] + (999).to_bytes(4, "little") + _webp_bytes()[8:],
        _riff(b"VP8L\x11\x00\x00\x00short"),
        _riff(b"VP8L\x01\x00\x00\x00x"),
        _riff(_riff_chunk(b"XMP ", b"public")),
    ],
    ids=["header-only", "wrong-riff-size", "truncated-chunk", "missing-padding", "no-image-payload"],
)
def test_malformed_webp_container_fails_closed(tmp_path: Path, data: bytes) -> None:
    _write_safe_tree(tmp_path)
    relative_path = "assets/step-01-access.webp"
    (tmp_path / relative_path).write_bytes(data)

    findings = _joined_findings(tmp_path)

    assert f"invalid-media: {relative_path}" in findings


def test_forbidden_term_inventory_matches_canonical_contract() -> None:
    assert FORBIDDEN_TERMS == EXPECTED_FORBIDDEN_TERMS


@pytest.mark.parametrize(
    "term",
    tuple(term.swapcase() for term in FORBIDDEN_TERMS),
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


@pytest.mark.parametrize("relative_path", sorted(EXPECTED_TEXT_FILES))
def test_invalid_utf8_text_file_fails_closed_instead_of_crashing(
    tmp_path: Path, relative_path: str
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / relative_path).write_bytes(b"\xff\xfe\x00private")

    findings = _joined_findings(tmp_path)

    assert f"decode-error: {relative_path}" in findings


@pytest.mark.parametrize("relative_path", sorted(EXPECTED_TEXT_FILES))
def test_binary_control_bytes_in_text_file_fail_closed(
    tmp_path: Path, relative_path: str
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / relative_path).write_bytes(b"public\x00\x01text")

    findings = _joined_findings(tmp_path)

    assert f"binary-content: {relative_path}" in findings


@pytest.mark.parametrize("relative_path", sorted(EXPECTED_TEXT_FILES))
def test_each_text_file_receives_full_privacy_audit(
    tmp_path: Path, relative_path: str
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / relative_path).write_text(
        "tavns and \u81ea\u4f24\n"
        "C:\\Users\\Alice\\private.txt\n"
        "https://example.test/private?token=value\n",
        encoding="utf-8",
    )

    findings = _joined_findings(tmp_path)

    assert f"forbidden-term: {relative_path}" in findings
    assert f"absolute-path: {relative_path}" in findings
    assert f"credential-param: {relative_path}" in findings
    assert f"unapproved-url: {relative_path}" in findings


def _with_size(result: os.stat_result, size: int) -> SimpleNamespace:
    return SimpleNamespace(
        st_mode=result.st_mode,
        st_file_attributes=getattr(result, "st_file_attributes", 0),
        st_nlink=result.st_nlink,
        st_size=size,
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://subdomain.{APP_URL.removeprefix('https://')}",
        f"{APP_URL}/private",
        f"{APP_URL}?mode=public",
        f"{APP_URL}_",
        f"{APP_URL})evil",
        f"{APP_URL}]evil",
        f"{APP_URL}}}evil",
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
    "uri",
    [
        "ftp://evil.example/private",
        "mailto:private@example.com",
        "data:text/plain,secret",
    ],
)
def test_non_http_uri_schemes_are_rejected(tmp_path: Path, uri: str) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(uri, encoding="utf-8")

    findings = _joined_findings(tmp_path)

    assert "unapproved-url: README.md" in findings


@pytest.mark.parametrize(
    "markup",
    [
        '<a href="//evil.example/private">demo</a>',
        '<a href="https&#58;//evil.example/private">demo</a>',
        '<a href="https&#x3A;&#x2F;&#x2F;evil.example/private">demo</a>',
    ],
)
def test_protocol_relative_and_html_encoded_urls_are_rejected(
    tmp_path: Path, markup: str
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(markup, encoding="utf-8")

    findings = _joined_findings(tmp_path)

    assert "unapproved-url: README.md" in findings


@pytest.mark.parametrize(
    ("rendered_source", "category"),
    [
        ("tav&#110;s", "forbidden-term"),
        (r"C&#58;:\Users\Alice\private.txt", "absolute-path"),
        ("&#47;Users/alice/private.txt", "absolute-path"),
    ],
)
def test_html_decoded_terms_and_paths_are_rejected_without_echoing_content(
    tmp_path: Path, rendered_source: str, category: str
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(rendered_source, encoding="utf-8")

    findings = _joined_findings(tmp_path)

    assert f"{category}: README.md" in findings
    assert rendered_source not in findings


@pytest.mark.parametrize("sentinel", ["DO_NOT_LOG_THIS", "tavns"])
def test_findings_do_not_echo_url_or_credential_values(
    tmp_path: Path, sentinel: str
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(
        f"https://evil.example/private?token={sentinel}", encoding="utf-8"
    )

    findings = audit_showcase(tmp_path)
    joined = "\n".join(findings)

    assert "unapproved-url: README.md" in joined
    assert "credential-param: README.md" in joined
    assert sentinel not in joined


def test_markdown_label_colons_are_not_treated_as_uris(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Access:\n\nAccess: public showcase\n"
        "\u8bbf\u95ee\uff1a\u516c\u5f00\u6f14\u793a\n",
        encoding="utf-8",
    )

    assert audit_showcase(tmp_path) == []


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


def test_malformed_root_fails_closed() -> None:
    findings = audit_showcase(Path("invalid\0root"))

    assert findings
    assert findings[0].startswith(("root-error:", "invalid-root:"))


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


@pytest.mark.parametrize(
    ("relative_path", "size_limit"),
    [
        ("assets/workflow-demo.gif", EXPECTED_MAX_GIF_FILE_BYTES),
        ("assets/step-01-access.webp", EXPECTED_MAX_WEBP_FILE_BYTES),
    ],
)
def test_binary_file_size_limit_boundary_is_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    size_limit: int,
) -> None:
    _write_safe_tree(tmp_path)
    target = tmp_path / relative_path
    real_lstat = os.lstat

    def lstat_at_boundary(path):
        result = real_lstat(path)
        if Path(path) == target:
            return _with_size(result, size_limit)
        return result

    monkeypatch.setattr(os, "lstat", lstat_at_boundary)

    assert audit_showcase(tmp_path) == []


@pytest.mark.parametrize(
    ("relative_path", "size_limit"),
    [
        ("assets/workflow-demo.gif", EXPECTED_MAX_GIF_FILE_BYTES),
        ("assets/step-01-access.webp", EXPECTED_MAX_WEBP_FILE_BYTES),
    ],
)
def test_oversized_binary_file_is_rejected_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    size_limit: int,
) -> None:
    _write_safe_tree(tmp_path)
    target = tmp_path / relative_path
    real_lstat = os.lstat
    real_open = Path.open

    def lstat_over_limit(path):
        result = real_lstat(path)
        if Path(path) == target:
            return _with_size(result, size_limit + 1)
        return result

    def fail_if_target_is_read(path: Path, *args, **kwargs):
        if path == target:
            raise AssertionError("oversized file was read")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", lstat_over_limit)
    monkeypatch.setattr(Path, "open", fail_if_target_is_read)

    findings = _joined_findings(tmp_path)

    assert f"file-too-large: {relative_path}" in findings


@pytest.mark.parametrize("total_size", [EXPECTED_MAX_GIF_TOTAL_BYTES, EXPECTED_MAX_GIF_TOTAL_BYTES + 1])
def test_gif_total_size_limit_is_checked_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, total_size: int
) -> None:
    _write_safe_tree(tmp_path)
    gif_paths = [tmp_path / name for name in sorted(EXPECTED_GIF_FILES)]
    first_size = total_size // 2
    sizes = {gif_paths[0]: first_size, gif_paths[1]: total_size - first_size}
    real_lstat = os.lstat
    real_open = Path.open

    def lstat_with_gif_sizes(path):
        result = real_lstat(path)
        if Path(path) in sizes:
            return _with_size(result, sizes[Path(path)])
        return result

    def fail_if_over_total_is_read(path: Path, *args, **kwargs):
        if total_size > EXPECTED_MAX_GIF_TOTAL_BYTES and path in sizes:
            raise AssertionError("GIF was read after aggregate limit failed")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", lstat_with_gif_sizes)
    monkeypatch.setattr(Path, "open", fail_if_over_total_is_read)

    findings = audit_showcase(tmp_path)

    if total_size == EXPECTED_MAX_GIF_TOTAL_BYTES:
        assert findings == []
    else:
        assert "gif-total-too-large: ." in findings


@pytest.mark.parametrize(
    ("relative_path", "data"),
    [
        (
            "assets/workflow-demo.gif",
            _gif_bytes(metadata=b" " * EXPECTED_MAX_METADATA_BYTES),
        ),
        (
            "assets/step-01-access.webp",
            _webp_bytes(metadata=b" " * EXPECTED_MAX_METADATA_BYTES),
        ),
    ],
    ids=["gif-boundary", "webp-boundary"],
)
def test_metadata_size_limit_boundary_is_allowed(
    tmp_path: Path, relative_path: str, data: bytes
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / relative_path).write_bytes(data)

    assert audit_showcase(tmp_path) == []


@pytest.mark.parametrize(
    ("relative_path", "data"),
    [
        (
            "assets/workflow-demo.gif",
            _gif_bytes(metadata=b"a" * (EXPECTED_MAX_METADATA_BYTES + 1)),
        ),
        (
            "assets/step-01-access.webp",
            _webp_bytes(
                metadata=b"a" * (EXPECTED_MAX_METADATA_BYTES // 2 + 1),
                additional_metadata=(
                    (b"XMP ", b"b" * (EXPECTED_MAX_METADATA_BYTES // 2)),
                ),
            ),
        ),
    ],
    ids=["gif-over-limit", "webp-cumulative-over-limit"],
)
def test_cumulative_metadata_over_limit_fails_closed(
    tmp_path: Path, relative_path: str, data: bytes
) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / relative_path).write_bytes(data)

    findings = _joined_findings(tmp_path)

    assert f"metadata-parse-error: {relative_path}" in findings


@pytest.mark.parametrize("error_type", [OSError, MemoryError])
def test_binary_read_errors_fail_closed_without_echoing_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    _write_safe_tree(tmp_path)
    relative_path = "assets/workflow-demo.gif"
    target = tmp_path / relative_path
    real_open = Path.open

    def open_with_error(path: Path, *args, **kwargs):
        if path == target:
            raise error_type("DO_NOT_LOG_THIS")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_with_error)

    findings = _joined_findings(tmp_path)

    assert f"read-error: {relative_path}" in findings
    assert "DO_NOT_LOG_THIS" not in findings


@pytest.mark.parametrize(
    "file_type",
    [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK],
    ids=["symlink", "fifo", "device", "socket"],
)
def test_allowlisted_file_must_be_regular(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_type: int,
) -> None:
    _write_safe_tree(tmp_path)
    target = tmp_path / "README.md"
    real_lstat = os.lstat

    def lstat_with_special_file(path) -> os.stat_result:
        result = real_lstat(path)
        if Path(path) == target:
            return _with_file_type(result, file_type)
        return result

    monkeypatch.setattr(os, "lstat", lstat_with_special_file)

    findings = _joined_findings(tmp_path)

    assert "special-entry: README.md" in findings


def test_allowlisted_hardlink_is_rejected(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    hidden_link = tmp_path / ".git" / "README-copy"
    hidden_link.parent.mkdir()
    os.link(tmp_path / "README.md", hidden_link)

    findings = _joined_findings(tmp_path)

    assert "hardlink: README.md" in findings


def test_root_symlink_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_safe_tree(tmp_path)
    real_lstat = os.lstat

    def lstat_with_symlink_root(path) -> os.stat_result:
        result = real_lstat(path)
        if Path(path) == tmp_path:
            return _with_file_type(result, stat.S_IFLNK)
        return result

    monkeypatch.setattr(os, "lstat", lstat_with_symlink_root)

    findings = audit_showcase(tmp_path)

    assert findings
    assert findings[0].startswith("invalid-root:")


def test_directory_symlink_is_not_silently_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_safe_tree(tmp_path)
    assets = tmp_path / "assets"
    real_lstat = os.lstat

    def lstat_with_symlink_assets(path) -> os.stat_result:
        result = real_lstat(path)
        if Path(path) == assets:
            return _with_file_type(result, stat.S_IFLNK)
        return result

    monkeypatch.setattr(os, "lstat", lstat_with_symlink_assets)

    findings = _joined_findings(tmp_path)

    assert "special-entry: assets" in findings


def test_extra_empty_directory_is_reported(tmp_path: Path) -> None:
    _write_safe_tree(tmp_path)
    (tmp_path / "private-directory").mkdir()

    findings = _joined_findings(tmp_path)

    assert "extra-entry: private-directory" in findings


def test_root_reparse_point_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_safe_tree(tmp_path)
    real_lstat = os.lstat
    monkeypatch.setattr(
        stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        REPARSE_POINT,
        raising=False,
    )

    def lstat_with_reparse_root(path):
        result = real_lstat(path)
        if Path(path) == tmp_path:
            return _with_reparse_point(result)
        return result

    monkeypatch.setattr(os, "lstat", lstat_with_reparse_root)

    findings = audit_showcase(tmp_path)

    assert findings
    assert findings[0].startswith("invalid-root:")


def test_assets_reparse_point_is_reported_and_not_traversed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_safe_tree(tmp_path)
    assets = tmp_path / "assets"
    real_lstat = os.lstat
    monkeypatch.setattr(
        stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        REPARSE_POINT,
        raising=False,
    )

    def lstat_with_reparse_assets(path):
        result = real_lstat(path)
        if Path(path) == assets:
            return _with_reparse_point(result)
        return result

    monkeypatch.setattr(os, "lstat", lstat_with_reparse_assets)

    findings = _joined_findings(tmp_path)

    assert "special-entry: assets" in findings
    for relative_path in EXPECTED_GIF_FILES | EXPECTED_WEBP_FILES:
        assert f"missing-file: {relative_path}" in findings


def test_allowlisted_file_reparse_point_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_safe_tree(tmp_path)
    readme = tmp_path / "README.md"
    real_lstat = os.lstat
    monkeypatch.setattr(
        stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        REPARSE_POINT,
        raising=False,
    )

    def lstat_with_reparse_readme(path):
        result = real_lstat(path)
        if Path(path) == readme:
            return _with_reparse_point(result)
        return result

    monkeypatch.setattr(os, "lstat", lstat_with_reparse_readme)

    findings = _joined_findings(tmp_path)

    assert "special-entry: README.md" in findings
