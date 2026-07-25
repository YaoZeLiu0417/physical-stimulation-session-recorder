from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, MutableMapping

from record_store import validate_subject_id


ALLOWED_VISITS = frozenset({"daily", "V1", "V3", "V4", "V5", "V6"})


@dataclass(frozen=True)
class VerifiedLink:
    subject_id: str
    visit: str


def _clear_signed_link_state(state: MutableMapping[str, Any]) -> None:
    for key in ("authed", "auth_source", "subject_id", "visit"):
        state.pop(key, None)


def _has_legacy_signed_link_state(state: MutableMapping[str, Any]) -> bool:
    return (
        state.get("auth_source") is None
        and state.get("authed") is True
        and ("subject_id" in state or "visit" in state)
    )


def reconcile_link_auth_state(
    state: MutableMapping[str, Any],
    verified: VerifiedLink | None,
    *,
    signed_link_attempted: bool,
) -> bool:
    """Apply signed-link identity and report whether an invalid link must stop access."""
    if verified is not None:
        state["authed"] = True
        state["auth_source"] = "signed_link"
        state["subject_id"] = verified.subject_id
        state["visit"] = verified.visit
        return False
    if signed_link_attempted:
        _clear_signed_link_state(state)
        return True
    if state.get("auth_source") == "signed_link" or _has_legacy_signed_link_state(state):
        _clear_signed_link_state(state)
    return False


def mark_admin_authenticated(state: MutableMapping[str, Any]) -> None:
    if state.get("auth_source") == "signed_link" or _has_legacy_signed_link_state(state):
        _clear_signed_link_state(state)
    else:
        state.pop("visit", None)
    state["authed"] = True
    state["auth_source"] = "admin"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _message(subject_id: str, exp_ts: int, visit: str) -> bytes:
    safe_subject_id = validate_subject_id(subject_id)
    if visit not in ALLOWED_VISITS:
        raise ValueError(f"unsupported visit: {visit}")
    if visit == "daily":
        return f"{safe_subject_id}|{exp_ts}".encode("utf-8")
    return f"{safe_subject_id}|{exp_ts}|{visit}".encode("utf-8")


def sign_subject_link(key: str, subject_id: str, exp_ts: int, visit: str = "daily") -> str:
    message = _message(subject_id, exp_ts, visit)
    return _b64url(hmac.new(key.encode("utf-8"), message, hashlib.sha256).digest())


def verify_subject_link(
    key: str,
    subject_id: str,
    exp_ts: int,
    signature: str,
    visit: str = "daily",
    *,
    now: int,
) -> VerifiedLink | None:
    if not key or now > exp_ts:
        return None
    try:
        safe_subject_id = validate_subject_id(subject_id)
        expected = sign_subject_link(key, safe_subject_id, exp_ts, visit)
    except (TypeError, ValueError):
        return None
    try:
        expected_bytes = expected.encode("ascii")
        signature_bytes = signature.encode("ascii")
    except (AttributeError, TypeError, UnicodeEncodeError):
        return None
    if not hmac.compare_digest(expected_bytes, signature_bytes):
        return None
    return VerifiedLink(safe_subject_id, visit)
