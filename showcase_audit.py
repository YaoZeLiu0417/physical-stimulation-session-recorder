"""Fail-closed privacy audit for the public README-only showcase tree."""

from pathlib import Path
import re


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

URL_PATTERN = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?<![a-z0-9])[a-z]:\\[^\s<>\"']+")
UNIX_PATH_PATTERN = re.compile(r"(?i)(?<![a-z0-9])/(?:users|home)/[^\s<>\"']*")
CREDENTIAL_PATTERN = re.compile(
    r"[?&](sid|sig|exp|token|secret|password)\s*=", re.IGNORECASE
)


def _relative_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _strip_url_punctuation(url: str) -> str:
    pairs = {")": "(", "]": "[", "}": "{"}
    while url:
        final = url[-1]
        if final in ".,;:!":
            url = url[:-1]
        elif final in pairs and url.count(final) > url.count(pairs[final]):
            url = url[:-1]
        else:
            break
    return url


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

    for match in URL_PATTERN.finditer(text):
        url = _strip_url_punctuation(match.group())
        has_suspicious_prefix = (
            match.start() > 0
            and (
                text[match.start() - 1].isalnum()
                or text[match.start() - 1] in "._+-"
            )
        )
        if has_suspicious_prefix or url not in APPROVED_URLS:
            findings.append(f"unapproved-url: {relative_path}: {url}")

    return findings


def audit_showcase(root: Path) -> list[str]:
    """Return privacy findings for a proposed public showcase directory."""
    if not root.exists() or not root.is_dir():
        return ["invalid-root: .: showcase root is missing or is not a directory"]

    findings: list[str] = []
    public_paths: list[Path] = []
    try:
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if ".git" in relative.parts:
                continue
            if path.is_file():
                public_paths.append(path)
    except OSError:
        return ["scan-error: .: unable to enumerate public tree"]

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
