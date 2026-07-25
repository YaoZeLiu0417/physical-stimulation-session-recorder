import hashlib
import itertools

import pytest

from showcase_workflow import DemoTransitionError, advance_step, password_matches


ASCII_PASSWORD = "demo-password"
ASCII_DIGEST = hashlib.sha256(ASCII_PASSWORD.encode("utf-8")).hexdigest()

KNOWN_STATES = ("overview", "capture", "reflection", "confirmation")
KNOWN_ACTIONS = ("begin", "finish_capture", "save_reflection", "restart")
EXPECTED_TRANSITIONS = {
    ("overview", "begin"): "capture",
    ("capture", "finish_capture"): "reflection",
    ("reflection", "save_reflection"): "confirmation",
    ("confirmation", "restart"): "overview",
}


@pytest.mark.parametrize(
    ("expected_digest", "candidate", "expected"),
    [
        (ASCII_DIGEST, ASCII_PASSWORD, True),
        (ASCII_DIGEST, "wrong-password", False),
        ("", ASCII_PASSWORD, False),
        ("g" * 64, ASCII_PASSWORD, False),
    ],
)
def test_password_matches_only_valid_digest_for_candidate(
    expected_digest: str, candidate: str, expected: bool
) -> None:
    assert password_matches(expected_digest, candidate) is expected


@pytest.mark.parametrize(
    "candidate",
    ["Demo-password", " demo-password", "demo-password "],
    ids=["case", "leading-whitespace", "trailing-whitespace"],
)
def test_password_matches_requires_byte_exact_candidate(candidate: str) -> None:
    assert password_matches(ASCII_DIGEST, candidate) is False


def test_password_matches_non_ascii_utf8_candidate_only_exactly() -> None:
    candidate = "p\u00e4ssw\u00f6rd-\u5bc6\u78bc"
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()

    assert password_matches(digest, candidate) is True
    assert password_matches(digest, candidate + "!") is False


def test_password_matches_normalizes_configured_digest() -> None:
    configured_digest = f"\n {ASCII_DIGEST.upper()} \t"

    assert password_matches(configured_digest, ASCII_PASSWORD) is True


@pytest.mark.parametrize(
    ("current_step", "action"),
    itertools.product(KNOWN_STATES, KNOWN_ACTIONS),
)
def test_advance_step_locks_known_transition_table(
    current_step: str, action: str
) -> None:
    expected_step = EXPECTED_TRANSITIONS.get((current_step, action))

    if expected_step is None:
        with pytest.raises(DemoTransitionError):
            advance_step(current_step, action)
    else:
        assert advance_step(current_step, action) == expected_step


def test_advance_step_rejects_unknown_state() -> None:
    with pytest.raises(DemoTransitionError):
        advance_step("unknown", "begin")


def test_advance_step_rejects_unknown_action() -> None:
    with pytest.raises(DemoTransitionError):
        advance_step("overview", "unknown")
