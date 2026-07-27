import ast
import base64
import hashlib
import hmac
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from link_auth import (
    mark_admin_authenticated,
    reconcile_link_auth_state,
    sign_subject_link,
    verify_subject_link,
)
from make_links import build_subject_link


def test_link_auth_imports_participant_validation_from_pure_module() -> None:
    source_path = Path(__file__).parent.parent / "link_auth.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    from_imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_roots.add(node.module.split(".", 1)[0])
            else:
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)

    assert ("participant_identity", "validate_subject_id") in from_imports
    assert "record_store" not in imported_roots


def test_daily_signature_is_compatible_with_existing_links() -> None:
    expected = base64.urlsafe_b64encode(
        hmac.new(
            b"test-key", b"sub-001|2000000000", hashlib.sha256
        ).digest()
    ).rstrip(b"=").decode("ascii")

    signature = sign_subject_link("test-key", "sub-001", 2000000000)

    assert signature == expected
    assert "=" not in signature
    assert verify_subject_link(
        "test-key", "sub-001", 2000000000, signature, now=1900000000
    ).subject_id == "sub-001"
    assert verify_subject_link(
        "test-key", "sub-001", 2000000000, signature, now=1900000000
    ).visit == "daily"


def test_formal_visit_is_authenticated_by_the_signature() -> None:
    formal_signature = sign_subject_link("test-key", "sub-001", 2000000000, "V5")

    verified = verify_subject_link(
        "test-key", "sub-001", 2000000000, formal_signature, "V5", now=1900000000
    )

    assert verified is not None
    assert verified.visit == "V5"
    assert verify_subject_link(
        "test-key", "sub-001", 2000000000, formal_signature, "V6", now=1900000000
    ) is None
    assert verify_subject_link(
        "test-key", "sub-001", 2000000000, formal_signature, now=1900000000
    ) is None
    assert formal_signature != sign_subject_link("test-key", "sub-001", 2000000000)


def test_invalid_or_expired_links_are_rejected() -> None:
    signature = sign_subject_link("test-key", "sub-001", 2000000000)

    assert verify_subject_link(
        "test-key", "sub-001", 2000000000, signature, now=2000000001
    ) is None
    assert verify_subject_link(
        "test-key", "sub-001", 2000000000, signature, now=2000000000
    ) is not None
    assert verify_subject_link(
        "test-key", "sub-001", 2000000000, signature, "V2", now=1900000000
    ) is None
    with pytest.raises(ValueError, match="unsupported visit: V2"):
        sign_subject_link("test-key", "sub-001", 2000000000, "V2")
    assert verify_subject_link(
        "test-key", "../path", 2000000000, signature, now=1900000000
    ) is None
    with pytest.raises(ValueError):
        sign_subject_link("test-key", "../path", 2000000000)
    assert verify_subject_link("", "sub-001", 2000000000, signature, now=1900000000) is None
    assert verify_subject_link(
        "test-key", "sub-001", 2000000000, signature + "x", now=1900000000
    ) is None
    assert verify_subject_link(
        "test-key", "sub-001", 2000000000, "\u00e9", now=1900000000
    ) is None


def test_app_renders_authenticated_subject_id_from_verified_link() -> None:
    app_source = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")

    assert "locked_link = verified_link" in app_source
    assert "value=locked_link.subject_id, disabled=True" in app_source
    assert not re.search(r"value=locked_link(?:[,)])", app_source)


@pytest.mark.parametrize("later_signature,later_now", [
    (None, 2000000001),
    ("mutated", 1900000000),
])
def test_signed_link_auth_state_is_cleared_when_a_later_link_is_invalid(
    later_signature: str | None, later_now: int
) -> None:
    state: dict[str, object] = {}
    signature = sign_subject_link("test-key", "sub-001", 2000000000, "V5")
    verified = verify_subject_link(
        "test-key", "sub-001", 2000000000, signature, "V5", now=1900000000,
    )

    assert reconcile_link_auth_state(state, verified, signed_link_attempted=True) is False
    assert state == {
        "authed": True,
        "auth_source": "signed_link",
        "subject_id": "sub-001",
        "visit": "V5",
    }

    later_verified = verify_subject_link(
        "test-key", "sub-001", 2000000000,
        later_signature or signature, "V5", now=later_now,
    )
    assert later_verified is None
    assert reconcile_link_auth_state(state, later_verified, signed_link_attempted=True) is True
    assert state == {}


def test_admin_auth_state_does_not_inherit_signed_link_identity() -> None:
    state: dict[str, object] = {
        "authed": True,
        "auth_source": "signed_link",
        "subject_id": "sub-001",
        "visit": "V5",
    }

    mark_admin_authenticated(state)

    assert state == {"authed": True, "auth_source": "admin"}
    assert reconcile_link_auth_state(state, None, signed_link_attempted=False) is False
    assert state == {"authed": True, "auth_source": "admin"}


def test_legacy_signed_link_state_without_auth_source_is_cleared() -> None:
    state: dict[str, object] = {
        "authed": True,
        "subject_id": "sub-old",
        "visit": "V5",
    }

    assert reconcile_link_auth_state(state, None, signed_link_attempted=False) is False
    assert state == {}

    state.update({"authed": True, "subject_id": "sub-old", "visit": "V5"})
    mark_admin_authenticated(state)
    assert state == {"authed": True, "auth_source": "admin"}


def test_app_verifies_link_once_and_reuses_the_result() -> None:
    app_source = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")

    assert app_source.count("verify_link_params()") == 2
    assert "reconcile_link_auth_state(" in app_source


def test_generated_urls_only_include_formal_visit_when_needed() -> None:
    daily_query = parse_qs(urlparse(build_subject_link(
        "https://example.test/app", "test-key", "sub-001", 2000000000, "daily"
    )).query)
    formal_query = parse_qs(urlparse(build_subject_link(
        "https://example.test/app", "test-key", "sub-001", 2000000000, "V5"
    )).query)

    assert "visit" not in daily_query
    assert formal_query["visit"] == ["V5"]
    assert verify_subject_link(
        "test-key", formal_query["sid"][0], int(formal_query["exp"][0]),
        formal_query["sig"][0], formal_query["visit"][0], now=1900000000,
    ) is not None
    assert verify_subject_link(
        "test-key", formal_query["sid"][0], int(formal_query["exp"][0]),
        formal_query["sig"][0], "V6", now=1900000000,
    ) is None
