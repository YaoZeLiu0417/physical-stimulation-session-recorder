import base64
import hashlib
import hmac
from urllib.parse import parse_qs, urlparse

import pytest

from link_auth import sign_subject_link, verify_subject_link
from make_links import build_subject_link


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
