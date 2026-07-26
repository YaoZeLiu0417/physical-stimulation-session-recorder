from __future__ import annotations

from urllib.parse import urlsplit

from streamlit_webrtc.config import RTCConfiguration, RTCIceServer
from streamlit_webrtc.credentials import get_twilio_ice_servers


_ICE_SCHEMES = frozenset({"stun", "stuns", "turn", "turns"})
_TURN_SCHEMES = frozenset({"turn", "turns"})
_TURN_QUERIES = frozenset({"transport=tcp", "transport=udp"})
_MISSING = object()


def _canonical_ice_url(url: str) -> tuple[str, str] | None:
    if not url or any(character.isspace() for character in url):
        return None

    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.casefold()
        if scheme not in _ICE_SCHEMES or "#" in url:
            return None
        if parsed.netloc:
            return None
        transport = None
        if parsed.query:
            query = parsed.query.casefold()
            if (
                scheme not in _TURN_SCHEMES
                or query not in _TURN_QUERIES
                or (scheme == "turns" and query != "transport=tcp")
            ):
                return None
            transport = query.removeprefix("transport=")
        elif "?" in url:
            return None

        endpoint = urlsplit(f"//{parsed.path}")

        if (
            endpoint.path
            or endpoint.username is not None
            or endpoint.password is not None
        ):
            return None
        host = endpoint.hostname
        if not host or ":" in host or endpoint.netloc.endswith(":"):
            return None
        port = endpoint.port
    except ValueError:
        return None

    canonical = f"{scheme}:{host}"
    if port is not None:
        canonical += f":{port}"
    if transport is not None:
        canonical += f"?transport={transport}"
    return canonical, scheme


def _validated_ice_servers(value: object) -> list[RTCIceServer] | None:
    if not isinstance(value, list) or not value:
        return None

    sanitized_servers: list[RTCIceServer] = []
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

        canonical_urls = []
        server_has_turn = False
        for url in url_values:
            parsed_url = _canonical_ice_url(url)
            if parsed_url is None:
                return None
            canonical_url, scheme = parsed_url
            canonical_urls.append(canonical_url)
            server_has_turn = server_has_turn or scheme in _TURN_SCHEMES

        username = server.get("username", _MISSING)
        credential = server.get("credential", _MISSING)
        if username is not _MISSING and (
            not isinstance(username, str) or not username.strip()
        ):
            return None
        if credential is not _MISSING and (
            not isinstance(credential, str) or not credential.strip()
        ):
            return None
        if server_has_turn and (
            username is _MISSING or credential is _MISSING
        ):
            return None

        sanitized = RTCIceServer(
            urls=canonical_urls[0] if isinstance(urls, str) else canonical_urls
        )
        if isinstance(username, str):
            sanitized["username"] = username
        if isinstance(credential, str):
            sanitized["credential"] = credential
        sanitized_servers.append(sanitized)
        has_turn = has_turn or server_has_turn

    if not has_turn:
        return None
    return sanitized_servers


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
