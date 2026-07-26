from __future__ import annotations

from typing import Any

from streamlit_webrtc import WebRtcMode, webrtc_streamer


RTC_CONFIGURATION = {
    "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
}
MEDIA_STREAM_CONSTRAINTS = {"video": True, "audio": False}


def render_live_camera() -> Any:
    return webrtc_streamer(
        key="showcase_camera_preview",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration=RTC_CONFIGURATION,
        media_stream_constraints=MEDIA_STREAM_CONSTRAINTS,
        sendback_audio=False,
        video_html_attrs={
            "autoPlay": True,
            "controls": False,
            "muted": True,
        },
    )


def camera_is_playing(context: Any) -> bool:
    state = getattr(context, "state", None)
    return bool(getattr(state, "playing", False))
