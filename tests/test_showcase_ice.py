import ast
from pathlib import Path

import pytest

import showcase_ice


ICE_SOURCE = Path(__file__).resolve().parents[1] / "showcase_ice.py"


@pytest.mark.parametrize(
    "turn_urls",
    (
        "turn:synthetic.invalid:3478?transport=udp",
        ["turns:synthetic.invalid:5349?transport=tcp"],
    ),
    ids=("string", "list"),
)
def test_resolve_turn_rtc_configuration_accepts_turn_url_shapes_and_trims_credentials(
    monkeypatch, turn_urls
) -> None:
    ice_servers = [
        {"urls": "stun:synthetic.invalid:3478"},
        {
            "urls": turn_urls,
            "username": "ephemeral-user",
            "credential": "ephemeral-credential",
        },
    ]
    calls = []

    def fake_get_twilio_ice_servers(account_sid, auth_token):
        calls.append((account_sid, auth_token))
        return ice_servers

    monkeypatch.setattr(
        showcase_ice,
        "get_twilio_ice_servers",
        fake_get_twilio_ice_servers,
    )

    assert showcase_ice.resolve_turn_rtc_configuration(
        "  test-account  ", "  test-token  "
    ) == {"iceServers": ice_servers}
    assert calls == [("test-account", "test-token")]


@pytest.mark.parametrize(
    ("account_sid", "auth_token"),
    (
        ("", ""),
        ("account", ""),
        ("", "token"),
        ("   ", "token"),
        ("account", "   "),
    ),
)
def test_resolve_turn_rtc_configuration_rejects_missing_credentials(
    monkeypatch, account_sid, auth_token
) -> None:
    def unexpected_call(*_args):
        raise AssertionError("Twilio must not be called")

    monkeypatch.setattr(
        showcase_ice,
        "get_twilio_ice_servers",
        unexpected_call,
    )

    assert (
        showcase_ice.resolve_turn_rtc_configuration(account_sid, auth_token)
        is None
    )


def test_resolve_turn_rtc_configuration_rejects_stun_only_and_failures(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        showcase_ice,
        "get_twilio_ice_servers",
        lambda *_args: [{"urls": ["stun:synthetic.invalid:19302"]}],
    )
    assert showcase_ice.resolve_turn_rtc_configuration("account", "token") is None

    def unavailable(*_args):
        raise RuntimeError("credential exchange detail")

    monkeypatch.setattr(showcase_ice, "get_twilio_ice_servers", unavailable)
    assert showcase_ice.resolve_turn_rtc_configuration("account", "token") is None


def test_ice_boundary_has_no_page_file_or_persistence_capabilities() -> None:
    source = ICE_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported_modules == {
        "__future__",
        "typing",
        "streamlit_webrtc.credentials",
    }
    prohibited = (
        "questionnaire",
        "record",
        "upload",
        "pathlib",
        "requests",
    )
    assert not any(
        fragment in module.casefold()
        for module in imported_modules
        for fragment in prohibited
    )
    assert "print(" not in source
    assert "logging" not in source
