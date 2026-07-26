import ast
from pathlib import Path

import pytest

import showcase_ice


ICE_SOURCE = Path(__file__).resolve().parents[1] / "showcase_ice.py"


@pytest.mark.parametrize(
    "turn_urls",
    (
        "TURN:synthetic.invalid:3478",
        ["TURNS:synthetic.invalid:5349?TRANSPORT=TCP"],
        "turn:[2001:db8::1]:3478",
    ),
    ids=("uppercase-string", "uppercase-list", "bracket-ipv6"),
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


def test_resolve_turn_rtc_configuration_sanitizes_servers_and_unknown_fields(
    monkeypatch,
) -> None:
    unknown_value = object()
    ice_servers = [
        {
            "urls": "stun:synthetic.invalid:3478",
            "unknown": unknown_value,
        },
        {
            "urls": ["turn:synthetic.invalid:3478?transport=UDP"],
            "username": "ephemeral-user",
            "credential": "ephemeral-credential",
            "unknown": unknown_value,
        },
    ]
    monkeypatch.setattr(
        showcase_ice,
        "get_twilio_ice_servers",
        lambda *_args: ice_servers,
    )

    result = showcase_ice.resolve_turn_rtc_configuration("account", "token")

    assert result == {
        "iceServers": [
            {"urls": "stun:synthetic.invalid:3478"},
            {
                "urls": ["turn:synthetic.invalid:3478?transport=UDP"],
                "username": "ephemeral-user",
                "credential": "ephemeral-credential",
            },
        ]
    }
    assert result["iceServers"] is not ice_servers
    assert all(
        sanitized is not original
        for sanitized, original in zip(result["iceServers"], ice_servers)
    )


@pytest.mark.parametrize(
    "ice_servers",
    (
        pytest.param(
            [
                {"urls": "stun:synthetic.invalid:3478"},
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "credential": "ephemeral-credential",
                },
            ],
            id="turn-missing-username",
        ),
        pytest.param(
            [
                {"urls": "stun:synthetic.invalid:3478"},
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                },
            ],
            id="turn-missing-credential",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "   ",
                    "credential": "ephemeral-credential",
                }
            ],
            id="turn-blank-username",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "\t",
                }
            ],
            id="turn-blank-credential",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": 7,
                    "credential": "ephemeral-credential",
                }
            ],
            id="turn-non-string-username",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": object(),
                }
            ],
            id="turn-non-string-credential",
        ),
        pytest.param(
            [
                {"urls": "stun:synthetic.invalid:3478", "username": 7},
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                },
            ],
            id="stun-non-string-username",
        ),
        pytest.param(
            [
                {"urls": "stun:synthetic.invalid:3478", "credential": None},
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                },
            ],
            id="stun-non-string-credential",
        ),
        pytest.param(
            [
                {"urls": "stun:synthetic.invalid:3478", "username": ""},
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                },
            ],
            id="stun-empty-username",
        ),
        pytest.param(
            [
                {"urls": "stun:synthetic.invalid:3478", "credential": "  "},
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                },
            ],
            id="stun-blank-credential",
        ),
    ),
)
def test_resolve_turn_rtc_configuration_rejects_invalid_ice_credentials(
    monkeypatch, ice_servers
) -> None:
    monkeypatch.setattr(
        showcase_ice,
        "get_twilio_ice_servers",
        lambda *_args: ice_servers,
    )

    assert showcase_ice.resolve_turn_rtc_configuration("account", "token") is None


@pytest.mark.parametrize(
    "ice_servers",
    (
        pytest.param(None, id="none"),
        pytest.param("", id="top-level-empty-string"),
        pytest.param([], id="top-level-empty-list"),
        pytest.param({"urls": "turn:synthetic.invalid:3478"}, id="top-level-dict"),
        pytest.param([None], id="non-dict-server"),
        pytest.param([{}], id="missing-urls"),
        pytest.param([{"urls": None}], id="none-urls"),
        pytest.param([{"urls": 7}], id="integer-urls"),
        pytest.param([{"urls": {"turn:x": 1}}], id="mapping-urls"),
        pytest.param([{"urls": ""}], id="empty-string-urls"),
        pytest.param([{"urls": []}], id="empty-list-urls"),
        pytest.param(
            [{"urls": ("turn:synthetic.invalid:3478",)}],
            id="tuple-urls",
        ),
        pytest.param(
            [{"urls": ["turn:synthetic.invalid:3478", 7]}],
            id="non-string-url-item",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="turn-empty-host",
        ),
        pytest.param(
            [
                {
                    "urls": "turns:",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="turns-empty-host",
        ),
        pytest.param([{"urls": "turnish:host"}], id="pseudo-scheme"),
        pytest.param([{"urls": "synthetic.invalid:3478"}], id="missing-scheme"),
        pytest.param(
            [
                {
                    "urls": "turn:user@synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="userinfo",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="whitespace",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:not-a-port",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="non-numeric-port",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:70000",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="out-of-range-port",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:3478/path",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="path-component",
        ),
        pytest.param(
            [
                {
                    "urls": "turn://synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="authority-form",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:3478?unknown=value",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="unknown-query",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:3478?transport=sctp",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="unsupported-transport",
        ),
        pytest.param(
            [
                {
                    "urls": (
                        "turn:synthetic.invalid:3478"
                        "?transport=udp&unknown=value"
                    ),
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="multiple-query-parameters",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:3478?",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="empty-query",
        ),
        pytest.param(
            [
                {"urls": "stun:synthetic.invalid:3478?transport=udp"},
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                },
            ],
            id="stun-query",
        ),
        pytest.param(
            [
                {"urls": "stuns:synthetic.invalid:5349?transport=tcp"},
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                },
            ],
            id="stuns-query",
        ),
        pytest.param(
            [
                {
                    "urls": "turn:synthetic.invalid:3478",
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                },
                {"urls": None},
            ],
            id="valid-turn-before-invalid-server",
        ),
        pytest.param(
            [
                {
                    "urls": [
                        "turn:synthetic.invalid:3478",
                        "stun:",
                    ],
                    "username": "ephemeral-user",
                    "credential": "ephemeral-credential",
                }
            ],
            id="valid-turn-with-invalid-companion-url",
        ),
    ),
)
def test_resolve_turn_rtc_configuration_rejects_malformed_helper_results(
    monkeypatch, ice_servers
) -> None:
    monkeypatch.setattr(
        showcase_ice,
        "get_twilio_ice_servers",
        lambda *_args: ice_servers,
    )

    assert showcase_ice.resolve_turn_rtc_configuration("account", "token") is None


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
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "streamlit_webrtc.credentials"
        and any(alias.name == "get_twilio_ice_servers" for alias in node.names)
        for node in ast.walk(tree)
    )
    prohibited_fragments = (
        "questionnaire",
        "record",
        "upload",
    )
    assert not any(
        fragment in module.casefold()
        for module in imported_modules
        for fragment in prohibited_fragments
    )
    prohibited_roots = {
        "io",
        "logging",
        "os",
        "pathlib",
        "requests",
        "socket",
        "subprocess",
    }
    assert not any(
        module.casefold().split(".", 1)[0] in prohibited_roots
        for module in imported_modules
    )
    assert not any(
        module == "streamlit" or module.startswith("streamlit.")
        for module in imported_modules
    )

    logging_methods = {
        "critical",
        "debug",
        "error",
        "exception",
        "info",
        "log",
        "warning",
    }
    calls = (node for node in ast.walk(tree) if isinstance(node, ast.Call))
    assert not any(
        (isinstance(call.func, ast.Name) and call.func.id in {"open", "print"})
        or (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in logging_methods
        )
        for call in calls
    )
