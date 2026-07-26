from __future__ import annotations

import logging
import os

import streamlit as st

from browser_recorder import RecorderStatus, render_browser_recorder
from showcase_ice import resolve_turn_rtc_configuration
from showcase_media import camera_is_playing, render_live_camera
from showcase_workflow import advance_step, password_matches


LOGGER = logging.getLogger(__name__)
PRODUCT_NAME = "Physical Stimulation Session Recorder"
PRODUCT_CAPTION = "物理刺激干预记录工具 · 本页面只使用合成内容"
SYNTHETIC_RESPONSE_KEYS = (
    "process_clarity",
    "camera_smoothness",
    "information_load",
    "workflow_willingness",
)
RECORDER_STATUS_KEY = "showcase_recorder_status"
RECORDER_COMPONENT_KEY = "showcase_session_recorder"
RECORDER_SESSION_KEYS = (RECORDER_STATUS_KEY, RECORDER_COMPONENT_KEY)

st.set_page_config(page_title=PRODUCT_NAME, layout="centered")
st.markdown(
    """
    <style>
    :root {
        --navy: #000035;
        --violet: #2D2674;
        --pink: #DD1D86;
        --blue: #33B0E4;
        --peach: #FFBC7D;
        --gray: #F4F4F4;
        --white: #FFFFFF;
    }
    .stApp {
        color: var(--navy);
        background: var(--white);
    }
    [data-testid="stAppViewBlockContainer"] {
        max-width: 760px;
        padding-top: 2.5rem;
    }
    [data-testid="stHeader"] {
        background: var(--white);
    }
    [data-testid="stSidebar"] {
        background: var(--violet);
    }
    [data-testid="stSidebar"] * {
        color: var(--white);
    }
    h1, h2, h3, p, label {
        color: var(--navy);
        letter-spacing: 0;
    }
    h1 {
        font-size: 2rem;
    }
    .demo-kicker {
        color: var(--pink);
        font-size: 0.75rem;
        font-weight: 700;
        margin: 0 0 0.4rem;
    }
    .demo-note, .privacy-note, .completion-status {
        background: var(--gray);
        padding: 0.85rem 1rem;
    }
    .demo-note {
        border-left: 4px solid var(--blue);
    }
    .privacy-note {
        border-left: 4px solid var(--peach);
    }
    .completion-status {
        border-left: 4px solid var(--pink);
        color: var(--navy);
        font-weight: 700;
    }
    div.stButton > button {
        border-radius: 4px;
    }
    div.stButton > button[kind="primary"] {
        background: var(--pink);
        border-color: var(--pink);
        color: var(--white);
    }
    div.stButton > button[kind="primary"]:hover {
        background: var(--violet);
        border-color: var(--violet);
        color: var(--white);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets[name])
    except Exception:
        return os.getenv(name, default)


def _require_access() -> None:
    expected_digest = _secret("SHOWCASE_PASSWORD_SHA256")
    if not expected_digest:
        st.error("演示暂未开放，请联系项目团队。")
        st.stop()

    if st.session_state.get("showcase_authenticated", False):
        return

    candidate = st.text_input(
        "访问密码",
        type="password",
        key="showcase_password",
    )
    if st.button("进入演示", type="primary", key="enter_demo"):
        if password_matches(expected_digest, candidate):
            st.session_state["showcase_authenticated"] = True
            st.rerun()
        st.error("访问密码错误。")
    st.stop()


def _go(action: str) -> None:
    st.session_state["showcase_step"] = advance_step(
        st.session_state["showcase_step"], action
    )
    st.rerun()


def _clear_recorder_probe_state() -> None:
    for key in RECORDER_SESSION_KEYS:
        st.session_state.pop(key, None)


def _return_to_overview() -> None:
    _clear_recorder_probe_state()
    st.session_state["showcase_step"] = "overview"
    st.rerun()


def _consume_recorder_status(rendered_status: object) -> RecorderStatus:
    raw_component_value = st.session_state.pop(RECORDER_COMPONENT_KEY, None)
    stored_status = st.session_state.get(RECORDER_STATUS_KEY)
    if raw_component_value is not None or not isinstance(
        stored_status, RecorderStatus
    ):
        stored_status = (
            rendered_status
            if isinstance(rendered_status, RecorderStatus)
            else RecorderStatus()
        )
        st.session_state[RECORDER_STATUS_KEY] = stored_status
    return stored_status


def _render_recorder_probe() -> None:
    st.subheader("本机录制")
    st.caption(
        "视频和声音仅保存在本机，不会上传。请勿录入可识别身份的信息。"
    )
    if st.button("返回流程概览", key="return_to_overview"):
        _return_to_overview()

    rendered_status = render_browser_recorder(
        key=RECORDER_COMPONENT_KEY,
        initial_mode="demo",
    )
    status = _consume_recorder_status(rendered_status)

    if status.state == "recording":
        st.info("正在本机录制。停止并确认保存后才能继续。")
    elif status.state == "ready":
        st.info("设备已就绪，可以开始本机录制。")
    elif status.state == "stopped":
        st.info("录制已停止。请保存并确认后继续。")
    elif status.state == "saved" and status.saved_confirmed:
        st.info("录像已保存在本机，可以继续后续流程。")
        if st.button(
            "继续后续流程",
            type="primary",
            key="finish_capture",
        ):
            st.session_state["showcase_camera_started"] = True
            _go("finish_capture")
    elif status.state == "saved":
        st.info("请先确认录像已保存在本机。")
    elif status.state in {"skipped", "failed"}:
        st.warning("本次未完成录像。如需继续，请明确选择无录像继续。")
        if st.button(
            "无录像继续",
            type="primary",
            key="continue_without_recording",
        ):
            st.session_state.pop("showcase_camera_started", None)
            _go("finish_capture")
    else:
        st.info("本机录制工具正在准备。")


st.title(PRODUCT_NAME)
st.caption(PRODUCT_CAPTION)
_require_access()

recorder_probe_enabled = (
    st.query_params.get("recorder_probe") == "1"
    and st.query_params.get_all("recorder_probe") == ["1"]
)
step = st.session_state.setdefault("showcase_step", "overview")
if step != "capture" or not recorder_probe_enabled:
    st.session_state.pop(RECORDER_COMPONENT_KEY, None)

st.sidebar.caption("SESSION PROGRESS")
for label, state in (
    ("1 安全进入", "overview"),
    ("2 会话记录", "capture"),
    ("3 引导反馈", "reflection"),
    ("4 完成确认", "confirmation"),
):
    st.sidebar.markdown(f"**当前 · {label}**" if step == state else label)

st.markdown(
    '<p class="demo-kicker">CONTROLLED DEMONSTRATION</p>',
    unsafe_allow_html=True,
)

with st.container():
    if step == "overview":
        st.subheader("准备开始本次演示")
        st.markdown(
            '<div class="demo-note">本受控合成演示展示安全进入、会话记录、引导反馈和完成确认。不会保存文件，也不会连接外部存储。</div>',
            unsafe_allow_html=True,
        )
        if st.button("开始演示", type="primary", key="begin_demo"):
            _go("begin")
    elif step == "capture":
        if recorder_probe_enabled:
            _render_recorder_probe()
        else:
            st.subheader("实时摄像预览")
            st.caption(
                "实时预览仅使用摄像头，不启用麦克风；视频不写入文件，"
                "也不会保存到项目存储。"
            )
            camera_unavailable = False
            camera_context = None
            try:
                rtc_configuration = resolve_turn_rtc_configuration(
                    _secret("TWILIO_ACCOUNT_SID"),
                    _secret("TWILIO_AUTH_TOKEN"),
                )
                if rtc_configuration is None:
                    camera_unavailable = True
                else:
                    camera_context = render_live_camera(rtc_configuration)
            except Exception:
                camera_unavailable = True
                LOGGER.warning("showcase camera preview unavailable")

            if camera_unavailable:
                st.warning("实时摄像预览暂时不可用，可继续体验后续流程。")
            elif camera_is_playing(camera_context):
                st.session_state["showcase_camera_started"] = True
                st.info("摄像头已连接。完成预览后可继续。")
            else:
                st.info(
                    "正在建立安全摄像预览连接。若长时间无画面，可继续后续流程。"
                )

            if st.button(
                "完成摄像演示", type="primary", key="finish_capture"
            ):
                _go("finish_capture")
    elif step == "reflection":
        st.subheader("演示反馈")
        st.caption("以下为通用合成反馈，不对应任何研究测量内容或评分规则。")
        st.slider(
            "本次演示流程有多清晰？", 0, 4, 2, key="process_clarity"
        )
        if st.session_state.get("showcase_camera_started") is True:
            st.slider(
                "摄像头交互有多顺畅？",
                0,
                4,
                2,
                key="camera_smoothness",
            )
        else:
            st.session_state.pop("camera_smoothness", None)
            st.caption("本次未建立实时摄像预览，无需评价摄像头交互。")
        st.slider(
            "界面的信息量有多合适？", 0, 4, 2, key="information_load"
        )
        st.slider(
            "你愿意继续使用这一流程吗？",
            0,
            4,
            2,
            key="workflow_willingness",
        )
        if st.button("提交演示反馈", type="primary", key="save_reflection"):
            _go("save_reflection")
    elif step == "confirmation":
        st.markdown(
            '<div class="completion-status" role="status">演示流程已完成。</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="privacy-note"><strong>隐私边界</strong><br>本演示不包含研究名称、干预参数、测量内容、评分规则或真实参与者数据。</div>',
            unsafe_allow_html=True,
        )
        if st.button("重新体验", key="restart_demo"):
            for key in (
                *SYNTHETIC_RESPONSE_KEYS,
                "showcase_camera_started",
                *RECORDER_SESSION_KEYS,
            ):
                st.session_state.pop(key, None)
            _go("restart")
