import ast
import copy
import hashlib
import json
import re
import stat
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import browser_recorder
import questionnaire_export
import questionnaire_ui
from app_workflow import (
    confirm_admin_intervention_day,
    resolve_trusted_intervention_day,
    support_needed,
)
from browser_recorder import RecorderStatus
from link_auth import sign_subject_link
from local_export_bundle import LocalExportBundle, build_local_export_bundle
from questionnaire_specs import FORMAL_INSTRUMENTS, VISIT_INSTRUMENT_IDS
from questionnaire_ui import ALTO_COLORS, ALTO_CSS, validate_submission
from session_record_workflow import (
    DAILY_CONTEXT_DEFAULTS,
    create_session_record,
    mark_questionnaire_visit_complete,
    persist_daily_questionnaire,
    persist_formal_questionnaire,
    questionnaire_answers,
    questionnaire_visit_complete,
)


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
APP_WORKFLOW_PATH = ROOT / "app_workflow.py"
DELETED_OPERATIONAL_PATHS = (
    ROOT / "upload_workflow.py",
    ROOT / "bd_init.py",
    ROOT / "tests" / "test_upload_workflow.py",
)
SESSION_EXACT_KEYS = {
    "operational_record",
    "operational_export_bundle",
    "operational_export_error",
    "operational_saved_locally",
    "operational_complete",
    "participant_identifier",
    "operational_finish",
    "operational_visit_selection",
}
SESSION_PREFIXES = (
    "questionnaire::",
    "operational_recorder::",
    "operational_daily_context::",
    "operational_recording_continue::",
    "operational_admin_day::",
)


def _source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_source())


@dataclass(frozen=True)
class _LocalModule:
    name: str
    path: Path
    tree: ast.Module


def _module_name_from_path(path: Path, root: Path) -> str:
    relative = path.resolve().relative_to(root.resolve())
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def _resolve_local_module(module_name: str, root: Path) -> Path | None:
    relative = Path(*module_name.split("."))
    candidates = (root / relative / "__init__.py", (root / relative).with_suffix(".py"))
    resolved_root = root.resolve()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved.is_relative_to(resolved_root):
            return resolved
    return None


def _resolved_module_chain(module_name: str, root: Path) -> list[tuple[str, Path]]:
    parts = module_name.split(".")
    resolved = []
    for length in range(1, len(parts) + 1):
        qualified_name = ".".join(parts[:length])
        path = _resolve_local_module(qualified_name, root)
        if path is not None:
            resolved.append((qualified_name, path))
    return resolved


def _imported_local_modules(module: _LocalModule, root: Path) -> set[tuple[str, Path]]:
    imported: set[tuple[str, Path]] = set()
    package_parts = module.name.split(".")
    if module.path.name != "__init__.py":
        package_parts = package_parts[:-1]

    for node in ast.walk(module.tree):
        requested_names: list[str] = []
        if isinstance(node, ast.Import):
            requested_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parent_count = node.level - 1
                if parent_count > len(package_parts):
                    continue
                base_parts = package_parts[: len(package_parts) - parent_count]
                if node.module:
                    base_parts.extend(node.module.split("."))
                base_name = ".".join(base_parts)
            elif node.module:
                base_name = node.module
            else:
                continue
            if base_name:
                requested_names.append(base_name)
                requested_names.extend(
                    f"{base_name}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
        for requested_name in requested_names:
            imported.update(_resolved_module_chain(requested_name, root))
    return imported


def _local_runtime_closure(entry_path: Path) -> dict[str, _LocalModule]:
    root = ROOT.resolve()
    resolved_entry = entry_path.resolve()
    entry_name = _module_name_from_path(resolved_entry, root)
    pending = _resolved_module_chain(entry_name, root)
    if not pending:
        pending = [(entry_name, resolved_entry)]
    closure: dict[str, _LocalModule] = {}
    visited_paths: set[Path] = set()
    while pending:
        module_name, path = pending.pop()
        if path in visited_paths:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = _LocalModule(module_name, path, tree)
        closure[module_name] = module
        visited_paths.add(path)
        pending.extend(_imported_local_modules(module, root))
    return closure


def _write_python_modules(root: Path, sources: dict[str, str]) -> None:
    for relative_path, source in sources.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def _module_trees(closure: dict[str, object]) -> tuple[ast.Module, ...]:
    return tuple(
        module.tree if isinstance(module, _LocalModule) else module
        for module in closure.values()
    )


def _qualified_expression_name(
    node: ast.AST, aliases: dict[str, str] | None = None
) -> str | None:
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    qualified_name = ".".join(reversed(parts)).casefold()
    head, separator, tail = qualified_name.partition(".")
    resolved_head = (aliases or {}).get(head, head)
    return f"{resolved_head}{separator}{tail}"


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = alias.name.casefold()
                bound_name = (alias.asname or alias.name.split(".", 1)[0]).casefold()
                aliases[bound_name] = (
                    imported if alias.asname else imported.split(".", 1)[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_name = node.module.casefold()
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound_name = (alias.asname or alias.name).casefold()
                aliases[bound_name] = f"{module_name}.{alias.name.casefold()}"
    return aliases


def _docstring_nodes(tree: ast.Module) -> set[ast.Constant]:
    docstrings: set[ast.Constant] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            docstrings.add(node.body[0].value)
    return docstrings


def _operational_closure_violations(closure: dict[str, object]) -> set[str]:
    trees = _module_trees(closure)
    imported_names = {
        alias.name.casefold()
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        imported_name
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for imported_name in {
            node.module.casefold(),
            *(
                f"{node.module}.{alias.name}".casefold()
                for alias in node.names
                if alias.name != "*"
            ),
        }
    }
    imported_roots = {name.split(".", 1)[0] for name in imported_names}
    prohibited_imports = {
        "requests",
        "httpx",
        "aiohttp",
        "socket",
        "ftplib",
        "urllib",
        "urllib3",
        "http",
        "websockets",
        "smtplib",
        "imaplib",
        "poplib",
        "telnetlib",
        "subprocess",
        "toml",
        "dotenv",
        "streamlit_webrtc",
        "aiortc",
        "av",
    }
    violations = {
        f"import:{module}" for module in prohibited_imports & imported_roots
    }
    exact_identifier_fragments = {
        "history",
        "recordings",
        "rec_dir",
        "save_dir",
    }
    substring_identifier_fragments = {
        "upload",
        "baidu",
        "oauth",
        "refresh_token",
        "client_secret",
        "remote_path",
        "cleanup",
        "ffmpeg",
        "transcod",
    }
    prohibited_calls = {
        "urllib.request.urlopen",
        "http.client.httpsconnection",
        "subprocess.run",
        "subprocess.popen",
        "os.system",
        "os.popen",
    }

    def add_identifier_violations(identifier: str) -> None:
        normalized = identifier.casefold()
        tokens = set(re.split(r"[^a-z0-9]+", normalized))
        for fragment in exact_identifier_fragments:
            if normalized == fragment or fragment in tokens:
                violations.add(f"source:{fragment}")
        for fragment in substring_identifier_fragments:
            if fragment in normalized:
                violations.add(f"source:{fragment}")

    for imported_name in imported_names:
        for component in imported_name.split("."):
            add_identifier_violations(component)

    for tree in trees:
        docstrings = _docstring_nodes(tree)
        aliases = _import_aliases(tree)
        for node in ast.walk(tree):
            identifiers = []
            if isinstance(node, ast.Name):
                identifiers.append(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.append(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identifiers.append(node.name)
            elif isinstance(node, ast.arg):
                identifiers.append(node.arg)
            for identifier in identifiers:
                add_identifier_violations(identifier)

            if isinstance(node, ast.Call):
                call_name = _qualified_expression_name(node.func, aliases)
                if call_name == "st.video":
                    violations.add("source:st.video")
                if call_name in prohibited_calls or (
                    call_name is not None
                    and call_name.startswith("subprocess.check_")
                ):
                    violations.add(f"call:{call_name}")

            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node not in docstrings
            ):
                value = node.value.casefold()
                if re.search(r"\bhttps?://", value):
                    violations.add("url:https")
                if re.search(r"\bftp://", value):
                    violations.add("url:ftp")
                for fragment in (
                    "upload",
                    "baidu",
                    "oauth",
                    "refresh_token",
                    "client_secret",
                    "remote_path",
                    "local_cleanup",
                    ".flv",
                    ".mp4",
                ):
                    if fragment in value:
                        violations.add(f"source:{fragment}")
    return violations


def _record(*, visit: str = "daily", day: int = 6) -> dict[str, object]:
    return create_session_record(
        "sub-001",
        date(2026, 7, 24),
        day,
        visit,
        token="deadbeef",
        now_iso="2026-07-24T08:09:10+00:00",
    )


def _visible_app_text(app: AppTest) -> str:
    values = [str(app.main), str(app.sidebar)]
    for collection_name in (
        "title",
        "header",
        "subheader",
        "caption",
        "markdown",
        "text",
        "info",
        "warning",
        "error",
        "success",
        "json",
        "metric",
        "code",
        "dataframe",
        "table",
        "button",
        "radio",
        "slider",
        "number_input",
        "text_area",
        "multiselect",
        "selectbox",
        "checkbox",
    ):
        for element in getattr(app, collection_name, []):
            for attribute in ("value", "label", "help", "placeholder"):
                value = getattr(element, attribute, None)
                if value is not None:
                    values.append(str(value))
    return "\n".join(values)


def _element_by_label(elements, label: str):
    return next(element for element in elements if element.label == label)


def _signed_app(
    monkeypatch,
    *,
    status: RecorderStatus = RecorderStatus(mode="long"),
    visit: str = "daily",
    subject_id: str = "sub-001",
    render_questionnaire=None,
    build_export=None,
    initial_state: dict[str, object] | None = None,
) -> tuple[AppTest, list[tuple[str, str]]]:
    recorder_calls: list[tuple[str, str]] = []

    def fake_recorder(*, key: str, initial_mode: str):
        recorder_calls.append((key, initial_mode))
        return status() if callable(status) else status

    monkeypatch.setattr(browser_recorder, "render_browser_recorder", fake_recorder)
    if render_questionnaire is not None:
        monkeypatch.setattr(
            questionnaire_ui,
            "render_questionnaire",
            render_questionnaire,
        )
    if build_export is not None:
        monkeypatch.setattr(
            questionnaire_export,
            "build_participant_export",
            build_export,
        )

    key = "operational-app-test-key"
    expiry = int(time.time()) + 3600
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.secrets["LINK_SIGNING_KEY"] = key
    app.secrets["TRUSTED_INTERVENTION_DAYS"] = {subject_id: 6}
    app.secrets["SAFETY_CONTACT"] = "请联系值班支持人员。"
    app.query_params["sid"] = subject_id
    app.query_params["exp"] = str(expiry)
    app.query_params["sig"] = sign_subject_link(
        key,
        subject_id,
        expiry,
        visit,
    )
    app.query_params["visit"] = visit
    for state_key, value in (initial_state or {}).items():
        app.session_state[state_key] = copy.deepcopy(value)
    app.run()
    return app, recorder_calls


def _admin_app(
    monkeypatch,
    *,
    status=RecorderStatus(mode="long", state="recording"),
    render_questionnaire=None,
    build_export=None,
) -> AppTest:
    monkeypatch.setattr(
        browser_recorder,
        "render_browser_recorder",
        lambda **kwargs: status() if callable(status) else status,
    )
    if render_questionnaire is not None:
        monkeypatch.setattr(
            questionnaire_ui,
            "render_questionnaire",
            render_questionnaire,
        )
    if build_export is not None:
        monkeypatch.setattr(
            questionnaire_export,
            "build_participant_export",
            build_export,
        )
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.secrets["APP_PASSWORD_SHA256"] = hashlib.sha256(
        b"admin-password"
    ).hexdigest()
    app.session_state["authed"] = True
    app.session_state["auth_source"] = "admin"
    app.session_state["subject_id"] = "sub-001"
    app.run()
    return app


def _saved_status() -> RecorderStatus:
    return RecorderStatus(
        mode="long",
        state="saved",
        duration_seconds=1250,
        camera_ready=True,
        microphone_ready=True,
        saved_confirmed=True,
    )


def _terminal_metadata(terminal_state: str) -> dict[str, object]:
    return {
        "version": 2,
        "storage": "browser_local",
        "status": terminal_state,
        "mode": "long",
        "duration_seconds": 0,
        "camera_ready": False,
        "microphone_ready": False,
        "saved_confirmed": False,
    }


def _zip_bytes(
    members: tuple[str, ...] = ("responses.json", "responses.xlsx"),
    *,
    json_data: bytes = b"{}",
    compression: int = ZIP_DEFLATED,
    member_modes: dict[str, int] | None = None,
    archive_comment: bytes = b"",
    member_comments: dict[str, bytes] | None = None,
    member_extras: dict[str, bytes] | None = None,
) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        archive.comment = archive_comment
        for member in members:
            data = json_data if member == "responses.json" else b"minimal-xlsx"
            info = ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = compression
            info.create_system = 3
            info.external_attr = (
                (member_modes or {}).get(member, stat.S_IFREG | 0o600) << 16
            )
            info.comment = (member_comments or {}).get(member, b"")
            info.extra = (member_extras or {}).get(member, b"")
            archive.writestr(info, data, compress_type=compression)
    return output.getvalue()


def _valid_bundle(*, json_data: bytes = b"{}") -> LocalExportBundle:
    return LocalExportBundle(
        filename="session-20260724-080910.zip",
        mime_type="application/zip",
        data=_zip_bytes(json_data=json_data),
    )


class _LocalExportBundleSubclass(LocalExportBundle):
    pass


def _corrupt_zip_bytes() -> bytes:
    data = bytearray(_zip_bytes(json_data=b"unique-json-payload"))
    local_header = data.index(b"PK\x03\x04")
    filename_length = int.from_bytes(
        data[local_header + 26 : local_header + 28], "little"
    )
    extra_length = int.from_bytes(
        data[local_header + 28 : local_header + 30], "little"
    )
    compressed_size = int.from_bytes(
        data[local_header + 18 : local_header + 22], "little"
    )
    payload_index = (
        local_header
        + 30
        + filename_length
        + extra_length
        + compressed_size // 2
    )
    data[payload_index] ^= 1
    return bytes(data)


def _patch_central_uncompressed_sizes(
    archive_data: bytes,
    sizes: tuple[int, int],
) -> bytes:
    data = bytearray(archive_data)
    offset = 0
    for size in sizes:
        central_header = data.index(b"PK\x01\x02", offset)
        data[central_header + 24 : central_header + 28] = size.to_bytes(
            4, "little"
        )
        offset = central_header + 46
    return bytes(data)


def _patch_zip_encryption_flags(archive_data: bytes) -> bytes:
    data = bytearray(archive_data)
    offset = 0
    while True:
        candidates = [
            index
            for signature in (b"PK\x03\x04", b"PK\x01\x02")
            if (index := data.find(signature, offset)) >= 0
        ]
        if not candidates:
            break
        header = min(candidates)
        flag_offset = header + (6 if data[header : header + 4] == b"PK\x03\x04" else 8)
        flags = int.from_bytes(data[flag_offset : flag_offset + 2], "little")
        data[flag_offset : flag_offset + 2] = (flags | 1).to_bytes(2, "little")
        offset = header + 4
    return bytes(data)


def _bundle_with_data(data: bytes) -> LocalExportBundle:
    return LocalExportBundle(
        filename="session-20260724-080910.zip",
        mime_type="application/zip",
        data=data,
    )


def _hostile_zip_bundles() -> tuple[object, ...]:
    valid_data = _zip_bytes()
    return (
        pytest.param(
            _bundle_with_data(
                _zip_bytes(
                    member_modes={
                        "responses.json": stat.S_IFLNK | 0o777,
                    }
                )
            ),
            id="unix-symlink-member",
        ),
        pytest.param(
            _bundle_with_data(
                _zip_bytes(
                    member_modes={
                        "responses.xlsx": stat.S_IFIFO | 0o600,
                    }
                )
            ),
            id="unix-non-regular-member",
        ),
        pytest.param(
            _bundle_with_data(
                _zip_bytes(
                    member_modes={
                        "responses.json": stat.S_IFDIR | 0o700,
                    }
                )
            ),
            id="unix-directory-member",
        ),
        pytest.param(
            _bundle_with_data(
                _zip_bytes(archive_comment=b"unexpected archive comment")
            ),
            id="archive-comment",
        ),
        pytest.param(
            _bundle_with_data(
                _zip_bytes(
                    member_comments={
                        "responses.json": b"unexpected member comment",
                    }
                )
            ),
            id="member-comment",
        ),
        pytest.param(
            _bundle_with_data(
                _zip_bytes(
                    member_extras={
                        "responses.xlsx": b"\xfe\xca\x01\x00x",
                    }
                )
            ),
            id="member-extra-metadata",
        ),
        pytest.param(
            _bundle_with_data(
                _zip_bytes(compression=ZIP_STORED)
            ),
            id="unsupported-compression",
        ),
        pytest.param(
            _bundle_with_data(_patch_zip_encryption_flags(valid_data)),
            id="encrypted-member-flags",
        ),
        pytest.param(
            _bundle_with_data(
                _patch_central_uncompressed_sizes(
                    valid_data,
                    (64 * 1024 * 1024, len(b"minimal-xlsx")),
                )
            ),
            id="oversized-member-metadata",
        ),
        pytest.param(
            _bundle_with_data(
                _patch_central_uncompressed_sizes(
                    valid_data,
                    (25 * 1024 * 1024, 25 * 1024 * 1024),
                )
            ),
            id="oversized-total-metadata",
        ),
        pytest.param(
            _bundle_with_data(
                _patch_central_uncompressed_sizes(
                    valid_data,
                    (8 * 1024 * 1024, len(b"minimal-xlsx")),
                )
            ),
            id="high-expansion-metadata",
        ),
    )


def _invalid_bundles() -> tuple[object, ...]:
    valid_data = _zip_bytes()
    return (
        pytest.param(
            _LocalExportBundleSubclass(
                filename="session-20260724-080910.zip",
                mime_type="application/zip",
                data=valid_data,
            ),
            id="subclass",
        ),
        pytest.param(
            LocalExportBundle(
                filename="subject-sub-001.zip",
                mime_type="application/zip",
                data=valid_data,
            ),
            id="identifying-filename",
        ),
        pytest.param(
            LocalExportBundle(
                filename=20260724080910,  # type: ignore[arg-type]
                mime_type="application/zip",
                data=valid_data,
            ),
            id="non-string-filename",
        ),
        pytest.param(
            LocalExportBundle(
                filename="session-20260724-080910.zip",
                mime_type="application/octet-stream",
                data=valid_data,
            ),
            id="wrong-mime",
        ),
        pytest.param(
            LocalExportBundle(
                filename="session-20260724-080910.zip",
                mime_type=object(),  # type: ignore[arg-type]
                data=valid_data,
            ),
            id="non-string-mime",
        ),
        pytest.param(
            LocalExportBundle(
                filename="session-20260724-080910.zip",
                mime_type="application/zip",
                data=bytearray(valid_data),  # type: ignore[arg-type]
            ),
            id="non-bytes-data",
        ),
        pytest.param(
            LocalExportBundle(
                filename="session-20260724-080910.zip",
                mime_type="application/zip",
                data=b"not-a-zip",
            ),
            id="non-zip-data",
        ),
        pytest.param(
            LocalExportBundle(
                filename="session-20260724-080910.zip",
                mime_type="application/zip",
                data=_corrupt_zip_bytes(),
            ),
            id="corrupt-zip-data",
        ),
        pytest.param(
            LocalExportBundle(
                filename="session-20260724-080910.zip",
                mime_type="application/zip",
                data=_zip_bytes(("answers.json", "responses.xlsx")),
            ),
            id="wrong-member",
        ),
        pytest.param(
            LocalExportBundle(
                filename="session-20260724-080910.zip",
                mime_type="application/zip",
                data=_zip_bytes(("responses.json",)),
            ),
            id="missing-member",
        ),
        pytest.param(
            LocalExportBundle(
                filename="session-20260724-080910.zip",
                mime_type="application/zip",
                data=_zip_bytes(
                    ("responses.json", "responses.xlsx", "private.txt")
                ),
            ),
            id="extra-member",
        ),
        pytest.param(
            LocalExportBundle(
                filename="session-20260724-080910.zip",
                mime_type="application/zip",
                data=_zip_bytes(("responses.xlsx", "responses.json")),
            ),
            id="wrong-member-order",
        ),
        *_hostile_zip_bundles(),
    )


def _operational_phase_state(record: dict[str, object]) -> dict[str, object]:
    return {
        "operational_record": copy.deepcopy(record),
        "operational_export_bundle": _valid_bundle(),
        "operational_export_error": True,
        "operational_saved_locally": True,
        "operational_complete": True,
        "operational_export_retry": True,
        "participant_identifier": "stale-participant-widget",
        "operational_finish": True,
        "operational_visit_selection": "V6",
        "questionnaire::stale": {"private": "answer"},
        "operational_recorder::stale": {"private": "status"},
        "operational_recorder::pending::stale": _terminal_metadata("failed"),
        "operational_recording_continue::stale": True,
        "operational_daily_context::stale": "private context",
        "operational_admin_day::stale": 6,
    }


def _assert_stale_phase_state_cleared(app: AppTest) -> None:
    for key in (
        "operational_export_bundle",
        "operational_export_error",
        "operational_saved_locally",
        "operational_complete",
        "operational_export_retry",
        "operational_finish",
        "operational_visit_selection",
    ):
        assert key not in app.session_state
    assert not any(
        "stale" in str(key) for key in app.session_state.filtered_state
    )


def _remaining_user_state_keys(app: AppTest) -> set[str]:
    return {
        str(key)
        for key in app.session_state.filtered_state
        if not str(key).startswith("$$")
    }


def _minimal_daily_answers(*, support: bool = False) -> dict[str, object]:
    answers: dict[str, object] = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": support,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }
    if support:
        answers["suicide_thought_frequency_24h"] = 1
    return answers


def _complete_renderer(calls: list[dict[str, object]]):
    def render(**kwargs):
        calls.append(kwargs)
        answers = _minimal_daily_answers()
        kwargs["save_draft"](answers, set(answers))
        return answers, True

    return render


def test_app_imports_only_the_browser_local_session_runtime_interfaces():
    tree = _tree()
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    referenced = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }

    assert {
        "render_browser_recorder",
        "local_recording_metadata",
        "recording_gate_satisfied",
        "create_session_record",
        "session_record_matches",
        "clear_owned_session_state",
        "build_participant_export",
        "questionnaire_state_keys",
        "render_questionnaire",
    } <= imported
    forbidden = {
        "DailyRecordStore",
        "record_store",
        "upload_workflow",
        "requests",
        "toml",
        "streamlit_webrtc",
        "aiortc",
        "MediaRecorder",
        "webrtc_streamer",
        "WebRtcMode",
        "RTCConfiguration",
        "Path",
        "open",
        "REC_DIR",
        "upload_record_bundle",
        "upload_generated_json",
        "remote_record_dir",
        "trusted_recording_files",
    }
    assert forbidden.isdisjoint(imported | referenced)


def test_app_source_has_no_server_media_storage_upload_or_history_runtime():
    source = _source()
    lowered = source.casefold()
    forbidden_fragments = (
        "recordings",
        "config.toml",
        "baidu",
        "oauth",
        "refresh_token",
        "remote_path",
        "save_dir",
        "upload progress",
        "upload_progress",
        "server playback",
        "historical",
        "history",
        ".flv",
        ".mp4",
        "ffmpeg",
        "transcode",
        "out_recorder_factory",
        "st.video",
    )
    assert all(fragment not in lowered for fragment in forbidden_fragments)


def test_operational_import_closure_has_no_server_upload_or_history_capability():
    closure = _local_runtime_closure(APP_PATH)
    assert set(closure) == {
        "app",
        "app_workflow",
        "browser_recorder",
        "link_auth",
        "local_export_bundle",
        "local_recording_workflow",
        "participant_identity",
        "questionnaire_export",
        "questionnaire_scoring",
        "questionnaire_specs",
        "questionnaire_ui",
        "session_record_workflow",
    }
    assert {"record_store", "upload_workflow", "bd_init"}.isdisjoint(closure)
    assert not _operational_closure_violations(closure)


def test_local_runtime_closure_resolves_nested_from_package_submodule(
    tmp_path, monkeypatch
):
    _write_python_modules(
        tmp_path,
        {
            "entry.py": "from outer.inner import worker\n",
            "outer/__init__.py": "",
            "outer/inner/__init__.py": "",
            "outer/inner/worker.py": "VALUE = 1\n",
        },
    )
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)

    closure = _local_runtime_closure(tmp_path / "entry.py")

    assert set(closure) == {"entry", "outer", "outer.inner", "outer.inner.worker"}
    assert {module.path for module in closure.values()} == {
        (tmp_path / "entry.py").resolve(),
        (tmp_path / "outer/__init__.py").resolve(),
        (tmp_path / "outer/inner/__init__.py").resolve(),
        (tmp_path / "outer/inner/worker.py").resolve(),
    }


def test_local_runtime_closure_resolves_relative_submodule(tmp_path, monkeypatch):
    _write_python_modules(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/entry.py": "from . import sibling\n",
            "pkg/sibling.py": "VALUE = 1\n",
        },
    )
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)

    closure = _local_runtime_closure(tmp_path / "pkg/entry.py")

    assert set(closure) == {"pkg", "pkg.entry", "pkg.sibling"}


def test_local_runtime_closure_keeps_same_stem_modules_distinct(tmp_path, monkeypatch):
    _write_python_modules(
        tmp_path,
        {
            "entry.py": "import alpha.shared\nimport beta.shared\n",
            "alpha/__init__.py": "",
            "alpha/shared.py": "ALPHA = True\n",
            "beta/__init__.py": "",
            "beta/shared.py": "BETA = True\n",
        },
    )
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)

    closure = _local_runtime_closure(tmp_path / "entry.py")

    assert set(closure) == {
        "entry",
        "alpha",
        "alpha.shared",
        "beta",
        "beta.shared",
    }
    assert closure["alpha.shared"].path != closure["beta.shared"].path


def test_local_runtime_closure_terminates_package_cycle(tmp_path, monkeypatch):
    _write_python_modules(
        tmp_path,
        {
            "entry.py": "import cycle_pkg.a\n",
            "cycle_pkg/__init__.py": "from . import a\n",
            "cycle_pkg/a.py": "from . import b\n",
            "cycle_pkg/b.py": "from . import a\n",
        },
    )
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)

    closure = _local_runtime_closure(tmp_path / "entry.py")

    assert set(closure) == {"entry", "cycle_pkg", "cycle_pkg.a", "cycle_pkg.b"}


@pytest.mark.parametrize(
    ("fragment", "synthetic_source"),
    (
        ("history", "HiStOrY = []"),
        ("recordings", "ReCoRdInGs = []"),
        ("rec_dir", "ReC_DiR = 'server'"),
        ("save_dir", "SaVe_DiR = 'server'"),
        ("cleanup", "def ClEaNuP(): pass"),
        ("ffmpeg", "FfMpEg = object()"),
        ("st.video", "st.ViDeO(b'media')"),
    ),
)
def test_operational_closure_scanner_rejects_generic_server_media_aliases(
    fragment, synthetic_source
):
    closure = {"synthetic": ast.parse(synthetic_source)}
    assert f"source:{fragment}" in _operational_closure_violations(closure)


@pytest.mark.parametrize(
    ("capability", "synthetic_source"),
    (
        ("urllib.request.urlopen", "urllib.request.urlopen('HTTPS://example.invalid')"),
        ("http.client.httpsconnection", "http.client.HTTPSConnection('example.invalid')"),
        ("subprocess.run", "subprocess.run(['tool'])"),
        ("subprocess.popen", "subprocess.Popen(['tool'])"),
        ("subprocess.check_output", "subprocess.check_output(['tool'])"),
        ("os.system", "os.system('tool')"),
        ("os.popen", "os.popen('tool')"),
    ),
)
def test_operational_closure_scanner_rejects_network_and_process_calls(
    capability, synthetic_source
):
    closure = {"synthetic": ast.parse(synthetic_source)}
    assert f"call:{capability}" in _operational_closure_violations(closure)


@pytest.mark.parametrize(
    "module_name",
    ("ReQuEsTs", "HtTpX", "AiOhTtP", "SoCkEt", "FtPlIb", "UrLlIb", "HtTp"),
)
def test_operational_closure_scanner_rejects_case_insensitive_network_imports(
    module_name
):
    closure = {"synthetic": ast.parse(f"import {module_name}\n")}
    assert f"import:{module_name.casefold()}" in _operational_closure_violations(closure)


@pytest.mark.parametrize(
    ("fragment", "synthetic_source"),
    (
        ("history", "import server.HiStOrY"),
        ("recordings", "from server.ReCoRdInGs import reader"),
        ("cleanup", "from server import ClEaNuP"),
    ),
)
def test_operational_closure_scanner_rejects_qualified_server_capability_imports(
    fragment, synthetic_source
):
    closure = {"synthetic": ast.parse(synthetic_source)}
    assert f"source:{fragment}" in _operational_closure_violations(closure)


@pytest.mark.parametrize(
    ("capability", "synthetic_source"),
    (
        ("subprocess.run", "from subprocess import run as execute\nexecute(['tool'])"),
        ("os.system", "from os import system as execute\nexecute('tool')"),
    ),
)
def test_operational_closure_scanner_resolves_aliased_process_calls(
    capability, synthetic_source
):
    closure = {"synthetic": ast.parse(synthetic_source)}
    assert f"call:{capability}" in _operational_closure_violations(closure)


def test_operational_closure_scanner_rejects_network_urls_case_insensitively():
    closure = {"synthetic": ast.parse("endpoint = 'HTTPS://example.invalid/api'")}
    assert "url:https" in _operational_closure_violations(closure)


def test_operational_closure_scanner_ignores_harmless_comments_and_docstrings():
    source = '''
"""History, cleanup, recordings, upload, ffmpeg, and st.video are words here."""
# save_dir, rec_dir, OAuth, and remote_path are harmless in a comment.
def harmless():
    """No capability is executed from this cleanup and history discussion."""
    return None
'''
    closure = {"synthetic": ast.parse(source)}
    assert not _operational_closure_violations(closure)


def test_obsolete_operational_modules_are_absent_and_unreferenced():
    assert all(not path.exists() for path in DELETED_OPERATIONAL_PATHS)

    prohibited_modules = {"upload_workflow", "bd_init"}
    for path in ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert prohibited_modules.isdisjoint(imported_roots), path.name


def test_app_and_workflow_have_no_obsolete_server_media_symbols():
    source = "\n".join(
        path.read_text(encoding="utf-8").casefold()
        for path in (APP_PATH, APP_WORKFLOW_PATH)
    )
    forbidden_fragments = (
        "upload",
        "requests",
        "toml",
        "dotenv",
        "streamlit_webrtc",
        "aiortc",
        "from av",
        "import av",
        "completedrecording",
        "trusted_recording",
        "recordings_dir",
        "local_cleanup",
        "cleanup_pending",
        "baidu",
        "oauth",
        ".flv",
        ".mp4",
        "transcod",
        "historical",
    )
    assert all(fragment not in source for fragment in forbidden_fragments)


def test_runtime_call_order_is_context_then_recorder_then_questionnaire_then_export():
    tree = _tree()
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    def named_call(name: str) -> ast.Call:
        return next(
            call
            for call in calls
            if isinstance(call.func, ast.Name) and call.func.id == name
        )

    recorder = named_call("render_browser_recorder")
    questionnaire = named_call("render_questionnaire")
    export = named_call("build_participant_export")
    context_assignment = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "daily_context"
            for target in node.targets
        )
    )

    assert context_assignment.lineno < recorder.lineno < questionnaire.lineno < export.lineno
    assert any(
        keyword.arg == "initial_mode"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value == "long"
        for keyword in recorder.keywords
    )


def test_download_control_has_exact_local_zip_contract_and_separate_finish_gate():
    tree = _tree()
    download_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "download_button"
    ]
    assert len(download_calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in download_calls[0].keywords}
    assert isinstance(keywords["label"], ast.Constant)
    assert keywords["label"].value == "下载问卷记录（JSON + Excel）"
    assert ast.unparse(keywords["data"]) == "bundle.data"
    assert ast.unparse(keywords["file_name"]) == "bundle.filename"
    assert isinstance(keywords["mime"], ast.Constant)
    assert keywords["mime"].value == "application/zip"

    source = _source()
    assert "我确认问卷 ZIP 已保存到本地" in source
    assert "完成本次会话" in source
    assert "disabled=not saved_locally" in source


def test_participant_source_has_no_scoring_paths_status_views_or_private_widget_keys():
    tree = _tree()
    source = _source().casefold()
    forbidden_source_terms = (
        "questionnaire_scoring",
        "score_formal_instrument",
        "daily_derived_metrics",
        "derived_metrics",
        "risk_level",
        "thresholds",
        "answer summary",
        "raw mapping",
        "device label",
        "tavns",
        "nlp",
    )
    assert all(term not in source for term in forbidden_source_terms)
    forbidden_surfaces = {"json", "metric", "dataframe", "table", "video"}
    assert not any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr in forbidden_surfaces
        for call in ast.walk(tree)
    )
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        for keyword in call.keywords:
            if keyword.arg != "key":
                continue
            key_names = {
                node.id
                for node in ast.walk(keyword.value)
                if isinstance(node, ast.Name)
            }
            assert {"subject_id", "safe_subject_id", "record_id"}.isdisjoint(
                key_names
            )


def test_signed_link_locks_subject_and_visit_and_creates_record_once(monkeypatch):
    app, recorder_calls = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state="recording"),
        visit="V1",
    )

    assert not app.exception
    subject = _element_by_label(app.text_input, "来访者编号（已由链接锁定）")
    assert subject.value == "sub-001"
    assert subject.disabled is True
    assert not [item for item in app.selectbox if item.label == "问卷访视"]
    first = copy.deepcopy(app.session_state["operational_record"])
    assert first["subject_id"] == "sub-001"
    assert first["visit"] == "V1"
    assert first["intervention_day"] == 6
    assert first["record_date"] == datetime.now(timezone.utc).date().isoformat()
    assert first["created_at_iso"] == first["updated_at_iso"]
    assert "." not in first["created_at_iso"]
    assert first["created_at_iso"].endswith("+00:00")

    app.run()
    second = app.session_state["operational_record"]
    assert second["record_id"] == first["record_id"]
    assert second["created_at_iso"] == first["created_at_iso"]
    assert len(recorder_calls) == 2
    assert all(mode == "long" for _, mode in recorder_calls)
    assert all("sub-001" not in key for key, _ in recorder_calls)
    assert all(
        "sub-001" not in str(key)
        for key in app.session_state.filtered_state
    )


def test_context_mismatch_clears_owned_state_and_recreates_exact_record(monkeypatch):
    app, _ = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state="recording"),
    )
    original_id = app.session_state["operational_record"]["record_id"]
    app.session_state["operational_record"]["visit"] = "V1"
    app.session_state["operational_export_bundle"] = object()
    app.session_state["operational_export_error"] = True
    app.session_state["operational_saved_locally"] = True
    app.session_state["questionnaire::stale"] = {"private": "answer"}
    app.session_state["operational_recorder::stale"] = {"private": "status"}
    app.session_state["operational_daily_context::stale"] = "private"

    app.run()

    replacement = app.session_state["operational_record"]
    assert replacement["record_id"] != original_id
    assert replacement["visit"] == "daily"
    assert replacement["intervention_day"] == 6
    assert "operational_export_bundle" not in app.session_state
    assert "operational_export_error" not in app.session_state
    assert "operational_saved_locally" not in app.session_state
    assert not any(
        str(key).startswith(SESSION_PREFIXES) and "stale" in str(key)
        for key in app.session_state.filtered_state
    )
    assert app.session_state["authed"] is True
    assert app.session_state["auth_source"] == "signed_link"
    assert app.session_state["subject_id"] == "sub-001"
    assert app.session_state["visit"] == "daily"


def test_malformed_cached_export_clears_local_save_acknowledgement(monkeypatch):
    app, recorder_calls = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state="recording"),
    )
    app.session_state["operational_export_bundle"] = object()
    app.session_state["operational_saved_locally"] = True

    app.run()

    assert not app.exception
    assert "operational_export_bundle" not in app.session_state
    assert "operational_saved_locally" not in app.session_state
    assert len(recorder_calls) == 2
    assert _element_by_label(
        app.number_input,
        "昨夜睡眠（小时）",
    ).value == 7.0
    assert not app.get("download_button")


@pytest.mark.parametrize("invalid_bundle", _invalid_bundles())
def test_invalid_cached_export_is_discarded_before_finalization(
    monkeypatch,
    invalid_bundle,
):
    app, recorder_calls = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state="recording"),
    )
    app.session_state["operational_export_bundle"] = copy.deepcopy(
        invalid_bundle
    )
    app.session_state["operational_saved_locally"] = True

    app.run()

    assert not app.exception
    assert "operational_export_bundle" not in app.session_state
    assert "operational_saved_locally" not in app.session_state
    assert len(recorder_calls) == 2
    assert _element_by_label(app.number_input, "昨夜睡眠（小时）")
    assert not app.get("download_button")
    assert not [button for button in app.button if button.label == "完成本次会话"]


def test_recording_blocks_questionnaire_and_uses_neutral_component_key(monkeypatch):
    questionnaire_calls = []

    def forbidden_questionnaire(**kwargs):
        questionnaire_calls.append(kwargs)
        return {}, False

    app, recorder_calls = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state="recording"),
        render_questionnaire=forbidden_questionnaire,
    )

    assert not app.exception
    assert questionnaire_calls == []
    assert recorder_calls and recorder_calls[0][1] == "long"
    assert "sub-001" not in recorder_calls[0][0]
    assert app.session_state["operational_record"]["recording"] == {}
    assert not app.get("download_button")


def test_saved_recording_persists_only_exact_v2_metadata_and_enters_questionnaire(
    monkeypatch,
):
    questionnaire_calls = []

    def incomplete_questionnaire(**kwargs):
        questionnaire_calls.append(kwargs)
        return kwargs["answers"], False

    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=incomplete_questionnaire,
    )

    assert not app.exception
    assert len(questionnaire_calls) == 1
    assert app.session_state["operational_record"]["recording"] == {
        "version": 2,
        "storage": "browser_local",
        "status": "saved",
        "mode": "long",
        "duration_seconds": 1250,
        "camera_ready": True,
        "microphone_ready": True,
        "saved_confirmed": True,
    }
    visible = _visible_app_text(app)
    assert "duration_seconds" not in visible
    assert "camera_ready" not in visible
    assert "microphone_ready" not in visible
    assert "filename" not in visible.casefold()
    assert "刷新或关闭页面" in visible


def test_accepted_saved_recording_locks_component_phase_on_questionnaire_rerun(
    monkeypatch,
):
    statuses = [
        _saved_status(),
        RecorderStatus(mode="long", state="recording"),
    ]
    questionnaire_calls = []

    def next_status():
        return statuses.pop(0)

    def incomplete_questionnaire(**kwargs):
        questionnaire_calls.append(kwargs)
        return kwargs["answers"], False

    app, recorder_calls = _signed_app(
        monkeypatch,
        status=next_status,
        render_questionnaire=incomplete_questionnaire,
    )
    stored = copy.deepcopy(app.session_state["operational_record"]["recording"])
    assert len(recorder_calls) == 1

    app.run()

    assert not app.exception
    assert len(statuses) == 1
    assert len(recorder_calls) == 1
    assert len(questionnaire_calls) == 2
    assert app.session_state["operational_record"]["recording"] == stored


@pytest.mark.parametrize("terminal_state", ["skipped", "failed"])
def test_skipped_or_failed_recording_requires_explicit_continue_confirmation(
    monkeypatch,
    terminal_state,
):
    questionnaire_calls = []

    def incomplete_questionnaire(**kwargs):
        questionnaire_calls.append(kwargs)
        return kwargs["answers"], False

    app, _ = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state=terminal_state),
        render_questionnaire=incomplete_questionnaire,
    )

    assert questionnaire_calls == []
    confirmation = _element_by_label(
        app.checkbox,
        "我确认继续填写问卷，不保存本次录制",
    )
    assert app.session_state["operational_record"]["recording"] == {}

    confirmation.check().run()

    assert not app.exception
    assert len(questionnaire_calls) == 1
    stored = app.session_state["operational_record"]["recording"]
    assert stored == _terminal_metadata(terminal_state)
    assert "error_code" not in stored


@pytest.mark.parametrize("terminal_state", ["skipped", "failed"])
def test_one_shot_terminal_recording_survives_idle_confirmation_rerun(
    monkeypatch,
    terminal_state,
):
    statuses = [
        RecorderStatus(mode="long", state=terminal_state),
        RecorderStatus(mode="long"),
        RecorderStatus(mode="long", state="recording"),
    ]
    questionnaire_calls = []

    def next_status():
        return statuses.pop(0)

    def incomplete_questionnaire(**kwargs):
        questionnaire_calls.append(kwargs)
        return kwargs["answers"], False

    app, recorder_calls = _signed_app(
        monkeypatch,
        status=next_status,
        render_questionnaire=incomplete_questionnaire,
    )
    pending_keys = {
        str(key)
        for key in app.session_state.filtered_state
        if str(key).startswith("operational_recorder::pending::")
    }
    assert len(pending_keys) == 1
    pending_key = pending_keys.pop()
    assert "sub-001" not in pending_key
    assert app.session_state[pending_key] == _terminal_metadata(terminal_state)
    assert app.session_state["operational_record"]["recording"] == {}
    confirmation = _element_by_label(
        app.checkbox,
        "我确认继续填写问卷，不保存本次录制",
    )

    confirmation.check().run()

    assert not app.exception
    assert len(statuses) == 1
    assert len(recorder_calls) == 2
    assert len(questionnaire_calls) == 1
    assert app.session_state["operational_record"]["recording"] == (
        _terminal_metadata(terminal_state)
    )
    assert pending_key not in app.session_state

    app.run()

    assert not app.exception
    assert len(statuses) == 1
    assert len(recorder_calls) == 2
    assert len(questionnaire_calls) == 2
    assert app.session_state["operational_record"]["recording"] == (
        _terminal_metadata(terminal_state)
    )


@pytest.mark.parametrize("terminal_state", ["skipped", "failed"])
def test_unconfirmed_terminal_then_idle_is_treated_as_recorder_reset(
    monkeypatch,
    terminal_state,
):
    statuses = [
        RecorderStatus(mode="long", state=terminal_state),
        RecorderStatus(mode="long"),
    ]
    questionnaire_calls = []

    def incomplete_questionnaire(**kwargs):
        questionnaire_calls.append(kwargs)
        return kwargs["answers"], False

    app, recorder_calls = _signed_app(
        monkeypatch,
        status=lambda: statuses.pop(0),
        render_questionnaire=incomplete_questionnaire,
    )
    pending_key = next(
        str(key)
        for key in app.session_state.filtered_state
        if str(key).startswith("operational_recorder::pending::")
    )
    confirmation_key = next(
        str(key)
        for key in app.session_state.filtered_state
        if str(key).startswith("operational_recording_continue::")
    )
    assert app.session_state[confirmation_key] is False

    app.run()

    assert not app.exception
    assert statuses == []
    assert len(recorder_calls) == 2
    assert questionnaire_calls == []
    assert app.session_state["operational_record"]["recording"] == {}
    assert pending_key not in app.session_state
    assert confirmation_key not in app.session_state
    assert not [
        checkbox
        for checkbox in app.checkbox
        if checkbox.label == "我确认继续填写问卷，不保存本次录制"
    ]


def test_pending_terminal_is_cleared_when_new_recording_activity_arrives(
    monkeypatch,
):
    statuses = [
        RecorderStatus(mode="long", state="skipped"),
        RecorderStatus(mode="long", state="recording"),
    ]

    app, _ = _signed_app(
        monkeypatch,
        status=lambda: statuses.pop(0),
    )
    assert any(
        str(key).startswith("operational_recorder::pending::")
        for key in app.session_state.filtered_state
    )

    app.run()

    assert statuses == []
    assert app.session_state["operational_record"]["recording"] == {}
    assert not any(
        str(key).startswith("operational_recorder::pending::")
        for key in app.session_state.filtered_state
    )


def test_questionnaire_callback_mutates_only_raw_session_record(monkeypatch):
    raw_answers = _minimal_daily_answers()

    def draft_renderer(**kwargs):
        kwargs["save_draft"](raw_answers, set(raw_answers))
        return raw_answers, False

    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=draft_renderer,
    )

    record = app.session_state["operational_record"]
    assert record["daily_core"] == raw_answers
    assert record["conditional_details"] == {}
    assert record["weekly_extension"] == {}
    assert record["completion"]["answered_field_ids"]["daily"] == sorted(
        raw_answers
    )
    for forbidden in (
        "score",
        "derived",
        "derived_metrics",
        "risk",
        "risk_level",
        "threshold",
        "safety_signals",
        "upload",
    ):
        assert forbidden not in record
    source = _source()
    assert "include_derived" not in source
    assert "questionnaire_scoring" not in source


def test_required_and_conditional_questions_block_completion_and_export(monkeypatch):
    answers = _minimal_daily_answers()
    answers["nssi_thought_present_24h"] = True
    errors = validate_submission(answers, set(answers), intervention_day=6)
    assert errors
    assert any("未完成" in error or "请" in error for error in errors)

    export_calls = []

    def incomplete_renderer(**kwargs):
        kwargs["save_draft"](answers, set(answers))
        return answers, False

    def forbidden_export(*args, **kwargs):
        export_calls.append((args, kwargs))
        raise AssertionError("incomplete questionnaire must not export")

    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=incomplete_renderer,
        build_export=forbidden_export,
    )

    assert not app.exception
    assert not questionnaire_visit_complete(
        app.session_state["operational_record"], "daily"
    )
    assert export_calls == []
    assert not app.get("download_button")


def test_support_copy_still_renders_for_current_answered_signal(monkeypatch):
    answers = _minimal_daily_answers(support=True)

    def support_renderer(**kwargs):
        kwargs["save_draft"](answers, set(answers))
        return answers, False

    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=support_renderer,
    )

    visible = _visible_app_text(app)
    assert "你的安全很重要" in visible
    assert "当地急救服务" in visible
    assert "请联系值班支持人员。" in visible


def test_complete_questionnaire_builds_and_caches_one_export_from_a_snapshot(
    monkeypatch,
):
    render_calls: list[dict[str, object]] = []
    export_calls: list[tuple[object, str, datetime]] = []
    bundle = _valid_bundle(json_data=b'{"export":"exact"}')

    def build_export(record, *, visit, exported_at):
        export_calls.append((record, visit, exported_at))
        return bundle

    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=_complete_renderer(render_calls),
        build_export=build_export,
    )

    assert not app.exception
    assert len(render_calls) == 1
    assert len(export_calls) == 1
    snapshot, export_visit, exported_at = export_calls[0]
    assert snapshot is not app.session_state["operational_record"]
    assert export_visit == "daily"
    assert exported_at.tzinfo is timezone.utc
    assert exported_at.microsecond == 0
    assert app.session_state["operational_export_bundle"] is bundle
    assert len(app.get("download_button")) == 1
    assert "刷新或关闭页面" in _visible_app_text(app)

    app.session_state["operational_record"]["daily_context"][
        "narrative"
    ] = "later"
    assert snapshot["daily_context"]["narrative"] != "later"
    app.run()

    assert not app.exception
    assert len(export_calls) == 1
    assert len(app.get("download_button")) == 1


def test_cached_export_enters_finalization_only_and_ignores_stale_widget_events(
    monkeypatch,
):
    questionnaire_calls: list[dict[str, object]] = []
    export_snapshots: list[dict[str, object]] = []
    downloads: list[dict[str, object]] = []
    bundle = _valid_bundle(json_data=b'{"export":"frozen"}')

    def render_with_answer_probe(**kwargs):
        questionnaire_calls.append(kwargs)
        answers = _minimal_daily_answers()
        state_keys = questionnaire_ui.questionnaire_state_keys(
            kwargs["state_namespace"],
            kwargs["visit"],
        )
        answer_key = state_keys.widget("nssi_urge_now")

        def save_changed_answer():
            changed_answers = dict(answers)
            changed_answers["nssi_urge_now"] = int(
                st.session_state[answer_key]
            )
            kwargs["save_draft"](changed_answers, set(changed_answers))

        st.slider(
            "answer mutation probe",
            0,
            10,
            value=0,
            key=answer_key,
            on_change=save_changed_answer,
        )
        kwargs["save_draft"](answers, set(answers))
        return answers, True

    def build_export(record, *, visit, exported_at):
        export_snapshots.append(record)
        return bundle

    def capture_download(**kwargs):
        downloads.append(kwargs)
        return False

    monkeypatch.setattr(st, "download_button", capture_download)
    app, recorder_calls = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=render_with_answer_probe,
        build_export=build_export,
    )
    frozen_record = copy.deepcopy(app.session_state["operational_record"])
    sleep_control = _element_by_label(
        app.number_input,
        "昨夜睡眠（小时）",
    )
    answer_control = _element_by_label(app.slider, "answer mutation probe")
    assert frozen_record["daily_context"]["sleep_hours"] == 7.0
    assert export_snapshots[0]["daily_context"]["sleep_hours"] == 7.0

    sleep_control.set_value(8.0)
    answer_control.set_value(9)
    app.run()

    assert not app.exception
    assert app.session_state["operational_record"] == frozen_record
    assert export_snapshots[0]["daily_context"]["sleep_hours"] == 7.0
    assert len(export_snapshots) == 1
    assert len(recorder_calls) == 1
    assert len(questionnaire_calls) == 1
    assert not [
        item
        for item in app.number_input
        if item.label == "昨夜睡眠（小时）"
    ]
    assert not [
        item for item in app.slider if item.label == "answer mutation probe"
    ]
    assert not app.text_area
    assert not app.multiselect
    assert downloads == [
        {
            "label": "下载问卷记录（JSON + Excel）",
            "data": bundle.data,
            "file_name": "session-20260724-080910.zip",
            "mime": "application/zip",
        },
        {
            "label": "下载问卷记录（JSON + Excel）",
            "data": bundle.data,
            "file_name": "session-20260724-080910.zip",
            "mime": "application/zip",
        },
    ]
    assert _element_by_label(
        app.checkbox,
        "我确认问卷 ZIP 已保存到本地",
    ).value is False


def test_download_button_receives_exact_bundle_bytes_name_and_mime(monkeypatch):
    captured = []
    bundle = _valid_bundle(json_data=b'{"download":"exact"}')

    def capture_download(**kwargs):
        captured.append(kwargs)
        return False

    monkeypatch.setattr(st, "download_button", capture_download)
    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=_complete_renderer([]),
        build_export=lambda *args, **kwargs: bundle,
    )

    assert not app.exception
    assert captured == [
        {
            "label": "下载问卷记录（JSON + Excel）",
            "data": bundle.data,
            "file_name": "session-20260724-080910.zip",
            "mime": "application/zip",
        }
    ]
    assert bundle.filename not in _visible_app_text(app)


def test_export_failure_is_neutral_retryable_and_preserves_responses(monkeypatch):
    render_calls: list[dict[str, object]] = []
    attempts = []
    bundle = _valid_bundle(json_data=b'{"export":"retry"}')

    def flaky_export(record, *, visit, exported_at):
        attempts.append(copy.deepcopy(record))
        if len(attempts) == 1:
            raise RuntimeError("PRIVATE-EXPORT-TRACE-/secret/path")
        return bundle

    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=_complete_renderer(render_calls),
        build_export=flaky_export,
    )

    visible = _visible_app_text(app)
    assert "下载文件暂时无法生成，请重试。" in visible
    assert "PRIVATE-EXPORT-TRACE" not in visible
    assert "/secret/path" not in visible
    retained = copy.deepcopy(app.session_state["operational_record"]["daily_core"])
    assert retained == _minimal_daily_answers()
    assert "operational_export_bundle" not in app.session_state

    _element_by_label(app.button, "重试生成下载文件").click().run()

    assert not app.exception
    assert len(attempts) == 2
    assert app.session_state["operational_record"]["daily_core"] == retained
    assert app.session_state["operational_export_bundle"] is bundle
    assert len(app.get("download_button")) == 1


@pytest.mark.parametrize("invalid_bundle", _invalid_bundles())
def test_invalid_built_export_is_neutral_retryable_and_preserves_answers(
    monkeypatch,
    invalid_bundle,
):
    attempts: list[dict[str, object]] = []
    valid_bundle = _valid_bundle(json_data=b'{"retry":"valid"}')

    def invalid_then_valid(record, *, visit, exported_at):
        attempts.append(copy.deepcopy(record))
        return invalid_bundle if len(attempts) == 1 else valid_bundle

    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=_complete_renderer([]),
        build_export=invalid_then_valid,
    )

    assert not app.exception
    visible = _visible_app_text(app)
    assert "下载文件暂时无法生成，请重试。" in visible
    assert "BadZipFile" not in visible
    assert "subject-sub-001.zip" not in visible
    retained = copy.deepcopy(app.session_state["operational_record"]["daily_core"])
    assert retained == _minimal_daily_answers()
    assert "operational_export_bundle" not in app.session_state
    assert not app.get("download_button")
    assert not [button for button in app.button if button.label == "完成本次会话"]

    _element_by_label(app.button, "重试生成下载文件").click().run()

    assert not app.exception
    assert len(attempts) == 2
    assert app.session_state["operational_record"]["daily_core"] == retained
    assert app.session_state["operational_export_bundle"] is valid_bundle
    assert len(app.get("download_button")) == 1


@pytest.mark.parametrize("source", ["cache", "builder"])
@pytest.mark.parametrize("invalid_bundle", _hostile_zip_bundles())
def test_hostile_zip_metadata_is_rejected_before_crc_decompression(
    monkeypatch,
    source,
    invalid_bundle,
):
    testzip_calls: list[tuple[str, ...]] = []

    def forbidden_testzip(archive):
        testzip_calls.append(tuple(archive.namelist()))
        raise AssertionError("metadata preflight must run before testzip")

    monkeypatch.setattr(ZipFile, "testzip", forbidden_testzip)
    if source == "cache":
        app, recorder_calls = _signed_app(
            monkeypatch,
            status=RecorderStatus(mode="long", state="recording"),
        )
        app.session_state["operational_export_bundle"] = invalid_bundle
        app.session_state["operational_saved_locally"] = True
        app.run()
        assert len(recorder_calls) == 2
        assert "operational_saved_locally" not in app.session_state
    else:
        app, _ = _signed_app(
            monkeypatch,
            status=_saved_status(),
            render_questionnaire=_complete_renderer([]),
            build_export=lambda *args, **kwargs: invalid_bundle,
        )
        assert "下载文件暂时无法生成，请重试。" in _visible_app_text(app)

    assert not app.exception
    assert testzip_calls == []
    assert "operational_export_bundle" not in app.session_state
    assert not app.get("download_button")


@pytest.mark.parametrize("source", ["cache", "builder"])
def test_oversized_archive_is_rejected_before_zip_open(monkeypatch, source):
    oversized_bundle = _bundle_with_data(
        _zip_bytes(
            json_data=b"x" * (16 * 1024 * 1024),
            compression=ZIP_STORED,
        )
    )
    zip_open_calls: list[int] = []

    def forbidden_zip_init(archive, *args, **kwargs):
        zip_open_calls.append(1)
        raise AssertionError("archive size preflight must run before ZIP open")

    monkeypatch.setattr(ZipFile, "__init__", forbidden_zip_init)
    if source == "cache":
        app, recorder_calls = _signed_app(
            monkeypatch,
            status=RecorderStatus(mode="long", state="recording"),
        )
        app.session_state["operational_export_bundle"] = oversized_bundle
        app.session_state["operational_saved_locally"] = True
        app.run()
        assert len(recorder_calls) == 2
        assert "operational_saved_locally" not in app.session_state
    else:
        app, _ = _signed_app(
            monkeypatch,
            status=_saved_status(),
            render_questionnaire=_complete_renderer([]),
            build_export=lambda *args, **kwargs: oversized_bundle,
        )
        assert "下载文件暂时无法生成，请重试。" in _visible_app_text(app)

    assert not app.exception
    assert zip_open_calls == []
    assert "operational_export_bundle" not in app.session_state
    assert not app.get("download_button")


def test_task4_canonical_bundle_is_accepted_for_build_and_cached_rerun(
    monkeypatch,
):
    bundle = build_local_export_bundle(
        snapshot={"schema_version": 1, "value": "raw"},
        sheets={"Session": ({"field": "value"},)},
        exported_at=datetime(2026, 7, 24, 8, 9, 10, tzinfo=timezone.utc),
    )
    build_calls: list[dict[str, object]] = []

    def return_canonical(record, *, visit, exported_at):
        build_calls.append(copy.deepcopy(record))
        return bundle

    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=_complete_renderer([]),
        build_export=return_canonical,
    )

    assert not app.exception
    assert len(build_calls) == 1
    assert app.session_state["operational_export_bundle"] is bundle
    assert len(app.get("download_button")) == 1

    app.run()

    assert not app.exception
    assert len(build_calls) == 1
    assert app.session_state["operational_export_bundle"] is bundle
    assert len(app.get("download_button")) == 1


def test_finish_requires_local_save_then_clears_sensitive_state_only(monkeypatch):
    bundle = _valid_bundle(json_data=b'{"finish":"signed"}')
    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=_complete_renderer([]),
        build_export=lambda *args, **kwargs: bundle,
    )

    finish = _element_by_label(app.button, "完成本次会话")
    assert finish.disabled is True
    app.session_state["operational_admin_day::stale"] = 7
    app.session_state["operational_visit_selection"] = "V1"
    app.session_state["operational_recorder::pending::stale"] = (
        _terminal_metadata("failed")
    )
    _element_by_label(
        app.checkbox,
        "我确认问卷 ZIP 已保存到本地",
    ).check().run()
    finish = _element_by_label(app.button, "完成本次会话")
    assert finish.disabled is False
    finish.click().run()

    assert not app.exception
    assert app.session_state["authed"] is True
    assert app.session_state["auth_source"] == "signed_link"
    assert app.session_state["subject_id"] == "sub-001"
    assert app.session_state["visit"] == "daily"
    assert app.session_state["operational_complete"] is True
    assert _remaining_user_state_keys(app) == {
        "authed",
        "auth_source",
        "subject_id",
        "visit",
        "operational_complete",
    }
    visible = _visible_app_text(app)
    assert "本次会话已完成。" in visible
    assert not app.get("download_button")
    assert not app.slider
    assert not app.text_area


def test_admin_finish_preserves_auth_only_and_clears_selected_context(monkeypatch):
    bundle = _valid_bundle(json_data=b'{"finish":"admin"}')
    app = _admin_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=_complete_renderer([]),
        build_export=lambda *args, **kwargs: bundle,
    )
    _element_by_label(app.button, "确认日期").click().run()
    assert not app.exception
    assert app.session_state["auth_source"] == "admin"
    assert app.session_state["subject_id"] == "sub-001"
    assert app.session_state["visit"] == "daily"
    assert "participant_identifier" in app.session_state
    assert "operational_visit_selection" in app.session_state
    assert any(
        str(key).startswith("operational_admin_day::")
        for key in app.session_state.filtered_state
    )

    _element_by_label(
        app.checkbox,
        "我确认问卷 ZIP 已保存到本地",
    ).check().run()
    _element_by_label(app.button, "完成本次会话").click().run()

    assert not app.exception
    assert _remaining_user_state_keys(app) == {
        "authed",
        "auth_source",
        "operational_complete",
    }
    assert app.session_state["auth_source"] == "admin"
    assert app.session_state["operational_complete"] is True
    assert _visible_app_text(app).strip().endswith("本次会话已完成。")


def test_admin_completion_does_not_short_circuit_valid_signed_request(monkeypatch):
    app, recorder_calls = _signed_app(
        monkeypatch,
        subject_id="sub-002",
        status=RecorderStatus(mode="long", state="recording"),
        initial_state={
            "authed": True,
            "auth_source": "admin",
            "operational_complete": True,
        },
    )

    assert not app.exception
    assert app.session_state["auth_source"] == "signed_link"
    assert app.session_state["subject_id"] == "sub-002"
    assert "operational_complete" not in app.session_state
    assert app.session_state["operational_record"]["subject_id"] == "sub-002"
    assert len(recorder_calls) == 1


def test_admin_to_signed_same_context_clears_every_operational_phase(monkeypatch):
    app, recorder_calls = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state="recording"),
    )
    original = copy.deepcopy(app.session_state["operational_record"])
    for key, value in _operational_phase_state(original).items():
        app.session_state[key] = copy.deepcopy(value)
    app.session_state["authed"] = True
    app.session_state["auth_source"] = "admin"

    app.run()

    assert not app.exception
    assert app.session_state["authed"] is True
    assert app.session_state["auth_source"] == "signed_link"
    assert app.session_state["subject_id"] == "sub-001"
    assert app.session_state["visit"] == "daily"
    assert app.session_state["participant_identifier"] == "sub-001"
    assert app.session_state["operational_record"]["record_id"] != original[
        "record_id"
    ]
    assert len(recorder_calls) == 2
    _assert_stale_phase_state_cleared(app)
    assert not app.get("download_button")


def test_signed_to_admin_same_context_clears_phase_before_login(monkeypatch):
    app, _ = _signed_app(
        monkeypatch,
        status=RecorderStatus(mode="long", state="recording"),
    )
    original = copy.deepcopy(app.session_state["operational_record"])
    for key, value in _operational_phase_state(original).items():
        app.session_state[key] = copy.deepcopy(value)
    admin_scope = hashlib.sha256(
        f"sub-001|{original['record_date']}".encode("utf-8")
    ).hexdigest()[:12]
    selection_key = f"operational_admin_day::{admin_scope}::selection"
    confirmation_key = f"operational_admin_day::{admin_scope}::confirmation"
    app.session_state[selection_key] = 6
    app.session_state[confirmation_key] = 6
    app.secrets["APP_PASSWORD_SHA256"] = hashlib.sha256(
        b"admin-password"
    ).hexdigest()
    app.query_params.clear()

    app.run()

    assert not app.exception
    _assert_stale_phase_state_cleared(app)
    assert selection_key not in app.session_state
    assert confirmation_key not in app.session_state
    assert "operational_record" not in app.session_state
    assert "participant_identifier" not in app.session_state
    _element_by_label(app.text_input, "访问密码").set_value("admin-password")
    _element_by_label(app.button, "登录").click().run()

    assert not app.exception
    assert app.session_state["authed"] is True
    assert app.session_state["auth_source"] == "admin"
    assert "operational_record" not in app.session_state
    assert not app.get("download_button")
    assert _element_by_label(app.button, "确认日期")


def test_passwordless_manual_completion_cannot_short_circuit_new_signed_identity(
    monkeypatch,
):
    original = _record()
    app, recorder_calls = _signed_app(
        monkeypatch,
        subject_id="sub-002",
        status=RecorderStatus(mode="long", state="recording"),
        initial_state={
            **_operational_phase_state(original),
            "subject_id": "sub-001",
            "visit": "daily",
        },
    )

    assert not app.exception
    assert app.session_state["authed"] is True
    assert app.session_state["auth_source"] == "signed_link"
    assert app.session_state["subject_id"] == "sub-002"
    assert app.session_state["visit"] == "daily"
    assert app.session_state["operational_record"]["record_id"] != original[
        "record_id"
    ]
    assert len(recorder_calls) == 1
    _assert_stale_phase_state_cleared(app)


def test_legacy_signed_completion_same_identity_remains_complete(monkeypatch):
    app, recorder_calls = _signed_app(
        monkeypatch,
        initial_state={
            "authed": True,
            "subject_id": "sub-001",
            "visit": "daily",
            "operational_complete": True,
        },
    )

    assert not app.exception
    assert app.session_state["auth_source"] == "signed_link"
    assert app.session_state["operational_complete"] is True
    assert recorder_calls == []
    assert _visible_app_text(app).strip().endswith("本次会话已完成。")


@pytest.mark.parametrize(
    ("target_subject", "target_visit"),
    [("sub-002", "daily"), ("sub-001", "V1")],
)
def test_legacy_signed_completion_is_cleared_for_different_verified_identity(
    monkeypatch,
    target_subject,
    target_visit,
):
    original = _record()
    app, recorder_calls = _signed_app(
        monkeypatch,
        subject_id=target_subject,
        visit=target_visit,
        status=RecorderStatus(mode="long", state="recording"),
        initial_state={
            **_operational_phase_state(original),
            "authed": True,
            "subject_id": "sub-001",
            "visit": "daily",
        },
    )

    assert not app.exception
    assert app.session_state["auth_source"] == "signed_link"
    assert app.session_state["subject_id"] == target_subject
    assert app.session_state["visit"] == target_visit
    assert app.session_state["operational_record"]["record_id"] != original[
        "record_id"
    ]
    assert len(recorder_calls) == 1
    _assert_stale_phase_state_cleared(app)


def test_signed_completion_is_cleared_before_admin_login():
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.secrets["APP_PASSWORD_SHA256"] = hashlib.sha256(
        b"admin-password"
    ).hexdigest()
    app.session_state["authed"] = True
    app.session_state["auth_source"] = "signed_link"
    app.session_state["subject_id"] = "sub-001"
    app.session_state["visit"] = "daily"
    app.session_state["operational_complete"] = True

    app.run()

    assert not app.exception
    assert "operational_complete" not in app.session_state
    _element_by_label(app.text_input, "访问密码").set_value("admin-password")
    _element_by_label(app.button, "登录").click().run()
    assert not app.exception
    assert app.session_state["auth_source"] == "admin"
    assert "operational_complete" not in app.session_state
    assert _element_by_label(app.button, "确认日期")


@pytest.mark.parametrize(
    ("target_subject", "target_visit"),
    [("sub-002", "daily"), ("sub-001", "V1")],
)
def test_signed_completion_is_scoped_to_verified_subject_and_visit(
    monkeypatch,
    target_subject,
    target_visit,
):
    app, recorder_calls = _signed_app(
        monkeypatch,
        subject_id=target_subject,
        visit=target_visit,
        status=RecorderStatus(mode="long", state="recording"),
        initial_state={
            "authed": True,
            "auth_source": "signed_link",
            "subject_id": "sub-001",
            "visit": "daily",
            "operational_complete": True,
        },
    )

    assert not app.exception
    assert "operational_complete" not in app.session_state
    assert app.session_state["operational_record"]["subject_id"] == target_subject
    assert app.session_state["operational_record"]["visit"] == target_visit
    assert len(recorder_calls) == 1


def test_visible_titles_and_generated_timestamps_are_neutral_and_utc_aware():
    tree = _tree()
    titles = [
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "title"
        and call.args
        and isinstance(call.args[0], ast.Constant)
    ]
    assert sorted(titles) == ["问卷会话", "问卷会话准入"]
    assert all("tavns" not in title.casefold() for title in titles)
    source = _source()
    assert "datetime.now().isoformat" not in source
    assert "datetime.now(timezone.utc)" in source
    assert '.isoformat(timespec="seconds")' in source


def test_app_has_no_legacy_global_questionnaire_or_answer_state():
    source = _source()
    assert "questionnaire_restored_" not in source
    assert "question_step_" not in source
    assert 'st.session_state["answered_field_ids"]' not in source
    assert 'st.session_state["q_' not in source
    assert "state_payload" not in source


def test_trusted_intervention_day_accepts_only_subject_scoped_values_1_to_28():
    assert resolve_trusted_intervention_day(
        {"sub-001": 7, "sub-002": "28"}, "sub-001"
    ) == 7
    assert resolve_trusted_intervention_day(
        json.dumps({"sub-001": 7, "sub-002": "28"}), "sub-002"
    ) == 28
    for config, subject in (
        ({"sub-002": 7}, "sub-001"),
        ({"sub-001": 0}, "sub-001"),
        ({"sub-001": 29}, "sub-001"),
        ({"sub-001": True}, "sub-001"),
        ("not-json", "sub-001"),
    ):
        with pytest.raises(ValueError, match="1.*28|trusted|配置"):
            resolve_trusted_intervention_day(config, subject)


def test_signed_link_never_uses_unsigned_day_and_admin_must_confirm(monkeypatch):
    source = _source()
    assert 'query.get("day"' not in source
    assert "TRUSTED_INTERVENTION_DAYS" in source

    app = _admin_app(monkeypatch)
    assert not app.exception
    assert "operational_record" not in app.session_state
    assert confirm_admin_intervention_day(7, confirmed=False) is None
    for value in (0, 29, True, 1.5, "7", "seven"):
        with pytest.raises(ValueError):
            confirm_admin_intervention_day(value, confirmed=True)

    _element_by_label(app.button, "确认日期").click().run()
    assert not app.exception
    assert app.session_state["operational_record"]["intervention_day"] == 1
    admin_keys = {
        key
        for key in app.session_state.filtered_state
        if str(key).startswith("operational_admin_day::")
    }
    assert admin_keys
    assert all("sub-001" not in str(key) for key in admin_keys)


def test_daily_persistence_keeps_only_active_answered_raw_values():
    record = _record()
    record["conditional_details"] = {
        "suicide_thought_frequency_24h": 4,
        "nssi_medical_care_24h": True,
    }
    answers = {
        **_minimal_daily_answers(),
        "nssi_thought_frequency_24h": 4,
        "suicide_thought_frequency_24h": 4,
        "nssi_medical_care_24h": True,
    }

    filtered = persist_daily_questionnaire(
        record,
        answers,
        set(answers),
        current_step=4,
    )

    assert filtered == _minimal_daily_answers()
    assert record["conditional_details"] == {}
    assert record["weekly_extension"] == {}
    assert record["field_status"]["daily"]["nssi_medical_care_24h"] == (
        "not_applicable"
    )
    assert "derived_metrics" not in record
    assert "safety_signals" not in record


def test_daily_raw_persistence_preserves_explicit_false_conditional_answer():
    record = _record()
    answers = {
        **_minimal_daily_answers(),
        "nssi_behavior_present_24h": True,
        "nssi_medical_care_24h": False,
        "nssi_behavior_count_cutting_24h": 1,
    }
    persist_daily_questionnaire(
        record,
        answers,
        set(answers),
        current_step=4,
    )
    assert record["conditional_details"]["nssi_medical_care_24h"] is False
    assert "safety_signals" not in record


def test_formal_persistence_filters_branches_and_keeps_protocol_metadata():
    record = _record(visit="V1")
    answers = {
        "nssi_ideation_6m_present": False,
        "nssi_ideation_6m_frequency": 6,
        "nssi_ideation_6m_intensity": 5,
        "pss_1": False,
        "pss_2": True,
    }
    answered = {
        "nssi_ideation_6m_present",
        "nssi_ideation_6m_frequency",
        "nssi_ideation_6m_intensity",
        "pss_1",
    }

    filtered = persist_formal_questionnaire(
        record,
        "V1",
        answers,
        answered,
        current_step=8,
    )

    assert filtered == {
        "nssi_ideation_6m_present": False,
        "pss_1": False,
    }
    visit_payload = record["formal_visits"]["V1"]
    instrument = visit_payload["instruments"]["nssi_ideation"]
    assert instrument["instrument_id"] == "nssi_ideation"
    assert instrument["instrument_version"] == "1.0"
    assert instrument["label"] == FORMAL_INSTRUMENTS["nssi_ideation"].label
    assert instrument["raw_answers"] == {
        "nssi_ideation_6m_present": False
    }
    assert "score" not in instrument
    assert "scored_answers" not in instrument
    assert record["field_status"]["V1"]["pss_2"] == "missing"


def test_questionnaire_answers_restore_only_current_visit_and_active_branches():
    record = _record(day=7)
    daily_answers = {
        **_minimal_daily_answers(),
        "nssi_thought_present_24h": True,
        "nssi_thought_frequency_24h": 3,
        **{f"sicq_{index}": 1 for index in range(1, 8)},
    }
    persist_daily_questionnaire(
        record,
        daily_answers,
        set(daily_answers),
        current_step=3,
    )
    persist_formal_questionnaire(
        record,
        "V3",
        {"pss_1": True},
        {"pss_1"},
        current_step=1,
    )

    restored_daily = questionnaire_answers(record, "daily")
    assert restored_daily == daily_answers
    assert questionnaire_answers(record, "V3") == {"pss_1": True}
    assert questionnaire_answers(record, "V1") == {}


def test_questionnaire_completion_is_current_visit_revision_and_timestamp_scoped():
    record = _record()
    mark_questionnaire_visit_complete(
        record,
        "daily",
        completed_at_iso="2026-07-24T08:10:00+00:00",
    )
    assert questionnaire_visit_complete(record, "daily") is True
    assert questionnaire_visit_complete(record, "V1") is False
    assert record["completion"]["questionnaire_visits"]["daily"] == {
        "status": "complete",
        "revision": 1,
        "completed_at_iso": "2026-07-24T08:10:00+00:00",
    }
    record["revision"] = 2
    assert questionnaire_visit_complete(record, "daily") is False


def test_support_signal_uses_only_current_active_answered_values():
    assert support_needed(
        "daily",
        {"suicide_thought_present_24h": True},
        {"suicide_thought_present_24h"},
        6,
    ) is True
    assert support_needed(
        "daily",
        {
            "suicide_thought_present_24h": False,
            "suicide_thought_frequency_24h": 4,
        },
        {"suicide_thought_present_24h", "suicide_thought_frequency_24h"},
        6,
    ) is False
    assert support_needed("V1", {"pss_1": True}, set(), 6) is False
    assert support_needed("V1", {"pss_1": True}, {"pss_1"}, 6) is True


def test_participant_visible_tree_does_not_render_bundle_name_or_internal_payload(
    monkeypatch,
):
    sentinel = "PARTICIPANT-PRIVATE-7F31"
    bundle = _valid_bundle(
        json_data=json.dumps({"sentinel": sentinel}).encode("ascii")
    )
    app, _ = _signed_app(
        monkeypatch,
        status=_saved_status(),
        render_questionnaire=_complete_renderer([]),
        build_export=lambda *args, **kwargs: bundle,
    )
    visible = _visible_app_text(app)
    assert sentinel not in visible
    assert "record_id" not in visible
    assert "field_status" not in visible
    assert "answered_field_ids" not in visible


def test_daily_context_uses_all_fields_and_raw_persistence_keeps_values():
    record = _record()
    context = {
        **DAILY_CONTEXT_DEFAULTS,
        "sleep_hours": 6.5,
        "mood_1to9": 3,
        "tags": ["睡眠"],
        "narrative": "saved narrative",
    }
    answers = _minimal_daily_answers()

    persist_daily_questionnaire(
        record,
        answers,
        set(answers),
        current_step=4,
        daily_context=context,
    )

    assert record["daily_context"] == context
    assert record["daily_core"] == answers
    assert record["conditional_details"] == {}
    assert "derived_metrics" not in record
    assert "safety_signals" not in record


def test_daily_weekly_and_formal_persistence_remain_raw_only_and_complete():
    daily_record = _record(day=7)
    daily_answers = {
        **_minimal_daily_answers(),
        **{f"sicq_{index}": 0 for index in range(1, 8)},
    }
    persist_daily_questionnaire(
        daily_record,
        daily_answers,
        set(daily_answers),
        current_step=12,
    )
    assert daily_record["weekly_extension"] == {
        f"sicq_{index}": 0 for index in range(1, 8)
    }
    assert "score" not in json.dumps(daily_record, ensure_ascii=False).casefold()

    for visit, instrument_ids in VISIT_INSTRUMENT_IDS.items():
        formal_record = _record(visit=visit)
        persist_formal_questionnaire(
            formal_record,
            visit,
            {},
            set(),
            current_step=0,
        )
        assert tuple(formal_record["formal_visits"][visit]["instruments"]) == instrument_ids
        for instrument_id in instrument_ids:
            payload = formal_record["formal_visits"][visit]["instruments"][instrument_id]
            assert payload["label"] == FORMAL_INSTRUMENTS[instrument_id].label
            assert "score" not in payload
            assert "scored_answers" not in payload


def test_alto_questionnaire_styling_contract_is_unchanged():
    assert ALTO_COLORS == {
        "black": "#050505",
        "purple": "#2D2674",
        "blue": "#33B0E4",
        "magenta": "#DD1D86",
        "orange": "#FF8D2A",
    }
    assert all(color in ALTO_CSS for color in ALTO_COLORS.values())
    assert "gradient" not in ALTO_CSS.casefold()
    assert "letter-spacing: 0" in ALTO_CSS
    assert "overflow-wrap: anywhere" in ALTO_CSS


def test_session_runtime_import_graph_has_no_scoring_or_storage_dependency():
    source = (ROOT / "session_record_workflow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert {
        "questionnaire_scoring",
        "record_store",
        "upload_workflow",
    }.isdisjoint(imports)


def test_app_compiles_as_utf8_source():
    compile(_source(), str(APP_PATH), "exec")
