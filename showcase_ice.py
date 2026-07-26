from __future__ import annotations

from typing import cast
from urllib.parse import urlsplit

from streamlit_webrtc.config import RTCConfiguration, RTCIceServer
from streamlit_webrtc.credentials import get_twilio_ice_servers


_ICE_SCHEMES = frozenset({"stun", "stuns", "turn", "turns"})
_TURN_SCHEMES = frozenset({"turn", "turns"})


def _ice_url_scheme(url: str) -> str | None:
    if not url or any(character.isspace() for character in url):
        return None

    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.casefold()
        if scheme not in _ICE_SCHEMES or parsed.fragment:
            return None

        if parsed.netloc:
            endpoint = parsed
        else:
            endpoint = urlsplit(f"//{parsed.path}")

        if (
            endpoint.path
            or endpoint.username is not None
            or endpoint.password is not None
        ):
            return None
        if not endpoint.hostname or endpoint.netloc.endswith(":"):
            return None
        _ = endpoint.port
    except ValueError:
        return None

    return scheme


def _validated_ice_servers(value: object) -> list[RTCIceServer] | None:
    if not isinstance(value, list) or not value:
        return None

    has_turn = False
    for server in value:
        if not isinstance(server, dict):
            return None

        urls = server.get("urls")
        if isinstance(urls, str):
            url_values = (urls,)
        elif (
            isinstance(urls, list)
            and urls
            and all(isinstance(url, str) for url in urls)
        ):
            url_values = urls
        else:
            return None

        for url in url_values:
            scheme = _ice_url_scheme(url)
            if scheme is None:
                return None
            has_turn = has_turn or scheme in _TURN_SCHEMES

    if not has_turn:
        return None
    return cast(list[RTCIceServer], value)


def resolve_turn_rtc_configuration(
    account_sid: str,
    auth_token: str,
) -> RTCConfiguration | None:
    account_sid = account_sid.strip()
    auth_token = auth_token.strip()
    if not account_sid or not auth_token:
        return None

    try:
        ice_servers: object = get_twilio_ice_servers(account_sid, auth_token)
    except Exception:
        return None

    validated = _validated_ice_servers(ice_servers)
    if validated is None:
        return None
    return RTCConfiguration(iceServers=validated)
