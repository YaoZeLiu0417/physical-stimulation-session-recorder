import atexit
import re
import secrets
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path


RUN_TOKEN_PATTERN = re.compile(r"[0-9a-f]{16}")
SCENARIO_NAMES = frozenset({"default", "day1", "day7", "V5"})
_internal_root: Path | None = None


def valid_run_token(value: object) -> bool:
    return isinstance(value, str) and RUN_TOKEN_PATTERN.fullmatch(value) is not None


def resolve_run_token(value: object) -> str:
    return value if valid_run_token(value) else secrets.token_hex(8)


def register_process_cleanup(
    root: Path, *, register: Callable[..., object] = atexit.register
) -> None:
    register(shutil.rmtree, root, ignore_errors=True)


def resolve_store_root(configured_root: str | None) -> Path:
    if configured_root:
        return Path(configured_root)

    global _internal_root
    if _internal_root is None:
        _internal_root = Path(tempfile.mkdtemp(prefix="questionnaire-browser-qa-"))
        register_process_cleanup(_internal_root)
    return _internal_root


def run_store_root(base_root: Path, run_token: str, scenario: str) -> Path:
    if not valid_run_token(run_token) or scenario not in SCENARIO_NAMES:
        raise ValueError("invalid questionnaire fixture storage namespace")
    resolved_base = base_root.resolve()
    target = base_root / run_token / scenario
    resolved_target = target.resolve()
    if resolved_target.parent.parent != resolved_base:
        raise ValueError("questionnaire fixture storage escaped its root")
    return target
