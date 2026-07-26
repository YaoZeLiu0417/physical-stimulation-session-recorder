from __future__ import annotations

from typing import Any

from streamlit_webrtc.credentials import get_twilio_ice_servers


def _contains_turn(ice_servers: list[dict[str, Any]]) -> bool:
    for server in ice_servers:
        urls = server.get("urls", ())
        if isinstance(urls, str):
            urls = (urls,)
        if any(
            isinstance(url, str)
            and url.casefold().startswith(("turn:", "turns:"))
            for url in urls
        ):
            return True
    return False


def resolve_turn_rtc_configuration(
    account_sid: str,
    auth_token: str,
) -> dict[str, Any] | None:
    account_sid = account_sid.strip()
    auth_token = auth_token.strip()
    if not account_sid or not auth_token:
        return None

    try:
        ice_servers = get_twilio_ice_servers(account_sid, auth_token)
    except Exception:
        return None

    if not _contains_turn(ice_servers):
        return None
    return {"iceServers": ice_servers}
