import hashlib

import pytest

from showcase_workflow import DemoTransitionError, advance_step, password_matches


@pytest.mark.parametrize(
    ("expected_digest", "candidate", "expected"),
    [
        (hashlib.sha256(b"demo-password").hexdigest(), "demo-password", True),
        (hashlib.sha256(b"demo-password").hexdigest(), "wrong-password", False),
        ("", "demo-password", False),
        ("g" * 64, "demo-password", False),
    ],
)
def test_password_matches_only_valid_digest_for_candidate(
    expected_digest: str, candidate: str, expected: bool
) -> None:
    assert password_matches(expected_digest, candidate) is expected


def test_advance_step_follows_showcase_sequence() -> None:
    transitions = [
        ("overview", "begin", "capture"),
        ("capture", "finish_capture", "reflection"),
        ("reflection", "save_reflection", "confirmation"),
        ("confirmation", "restart", "overview"),
    ]

    for current_step, action, expected_step in transitions:
        assert advance_step(current_step, action) == expected_step


def test_advance_step_rejects_skips_and_unknown_steps() -> None:
    invalid_transitions = [
        ("overview", "finish_capture"),
        ("unknown", "begin"),
    ]

    for current_step, action in invalid_transitions:
        with pytest.raises(DemoTransitionError):
            advance_step(current_step, action)
