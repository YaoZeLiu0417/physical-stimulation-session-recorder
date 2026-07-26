from __future__ import annotations

from typing import Any

from streamlit_webrtc import WebRtcMode, webrtc_streamer


MEDIA_STREAM_CONSTRAINTS = {"video": True, "audio": False}


def render_live_camera(rtc_configuration: dict[str, Any]) -> Any:
    return webrtc_streamer(
        key="showcase_camera_preview",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration=rtc_configuration,
        media_stream_constraints=MEDIA_STREAM_CONSTRAINTS,
        sendback_video=True,
        sendback_audio=False,
        video_html_attrs={
            "autoPlay": True,
            "controls": False,
            "muted": True,
            "playsInline": True,
            "style": {"width": "100%"},
        },
    )


def camera_is_playing(context: Any) -> bool:
    state = getattr(context, "state", None)
    return getattr(state, "playing", False) is True
