from __future__ import annotations

import hashlib
import hmac


class DemoTransitionError(ValueError):
    pass


TRANSITIONS = {
    ("overview", "begin"): "capture",
    ("capture", "finish_capture"): "reflection",
    ("reflection", "save_reflection"): "download",
    ("download", "finish_download"): "confirmation",
    ("confirmation", "restart"): "overview",
}


def password_matches(expected_digest: str, candidate: str) -> bool:
    normalized = expected_digest.strip().casefold()
    if len(normalized) != 64 or any(
        ch not in "0123456789abcdef" for ch in normalized
    ):
        return False
    candidate_digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate_digest, normalized)


def advance_step(current_step: str, action: str) -> str:
    try:
        return TRANSITIONS[(current_step, action)]
    except KeyError as exc:
        raise DemoTransitionError(
            f"transition not allowed: {current_step!r} + {action!r}"
        ) from exc
