import ast
from pathlib import Path
from types import SimpleNamespace

import showcase_media
from streamlit_webrtc import WebRtcMode


MEDIA_SOURCE = Path(__file__).resolve().parents[1] / "showcase_media.py"


def test_render_live_camera_uses_video_only_ephemeral_configuration(
    monkeypatch,
) -> None:
    calls = []
    sentinel = object()

    def fake_webrtc_streamer(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(showcase_media, "webrtc_streamer", fake_webrtc_streamer)

    assert showcase_media.render_live_camera() is sentinel
    assert calls == [
        {
            "key": "showcase_camera_preview",
            "mode": WebRtcMode.SENDRECV,
            "rtc_configuration": {
                "iceServers": [
                    {"urls": ["stun:stun.l.google.com:19302"]}
                ]
            },
            "media_stream_constraints": {"video": True, "audio": False},
            "sendback_audio": False,
            "video_html_attrs": {
                "autoPlay": True,
                "controls": False,
                "muted": True,
            },
        }
    ]
    prohibited = {
        "player_factory", "in_recorder_factory", "out_recorder_factory",
        "video_frame_callback", "audio_frame_callback",
        "queued_video_frames_callback", "queued_audio_frames_callback",
        "video_processor_factory", "audio_processor_factory",
    }
    assert prohibited.isdisjoint(calls[0])


def test_camera_is_playing_is_fail_closed() -> None:
    assert showcase_media.camera_is_playing(None) is False
    assert showcase_media.camera_is_playing(SimpleNamespace()) is False
    assert showcase_media.camera_is_playing(
        SimpleNamespace(state=SimpleNamespace(playing=False))
    ) is False
    assert showcase_media.camera_is_playing(
        SimpleNamespace(state=SimpleNamespace(playing=True))
    ) is True
    assert showcase_media.camera_is_playing(
        SimpleNamespace(state=SimpleNamespace(playing="false"))
    ) is False
    assert showcase_media.camera_is_playing(
        SimpleNamespace(state=SimpleNamespace(playing=1))
    ) is False
    assert showcase_media.camera_is_playing(
        SimpleNamespace(state=SimpleNamespace(playing=object()))
    ) is False


def test_media_boundary_uses_only_allowlisted_imports_and_calls() -> None:
    tree = ast.parse(MEDIA_SOURCE.read_text(encoding="utf-8"))
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
    assert imported_modules == {"__future__", "typing", "streamlit_webrtc"}

    call_names = {
        node.func.id
        if isinstance(node.func, ast.Name)
        else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert call_names <= {"getattr", "webrtc_streamer"}
