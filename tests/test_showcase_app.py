import ast
import hashlib
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import browser_recorder
import showcase_export
from browser_recorder import RecorderStatus
from showcase_export import SyntheticShowcaseArchive


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "showcase_app.py"
THEME = ROOT / ".streamlit" / "config.toml"
PASSWORD = "demonstration-passphrase"
PRODUCT_NAME = "Physical Stimulation Session Recorder"
PRODUCT_CAPTION = "物理刺激干预记录工具 · 本页面只使用合成内容"
SYNTHETIC_RESPONSES = {
    "process_clarity": 3,
    "camera_smoothness": 4,
    "information_load": 1,
    "workflow_willingness": 4,
}
NON_CAMERA_RESPONSE_KEYS = (
    "process_clarity",
    "information_load",
    "workflow_willingness",
)
CAMERA_FEEDBACK_SKIPPED_CAPTION = (
    "本次未完成录像，无需评价摄像头交互。"
)
RECORDER_SESSION_KEYS = (
    "showcase_recorder_status",
    "showcase_session_recorder",
)
SHOWCASE_ARCHIVE_KEY = "showcase_synthetic_archive"
SHOWCASE_EXPORT_ERROR_KEY = "showcase_export_error"
SHOWCASE_LOCAL_SAVE_KEY = "showcase_export_saved_confirmed"
SHOWCASE_DOWNLOAD_BUTTON_KEY = "showcase_download_archive"
SHOWCASE_RETRY_BUTTON_KEY = "showcase_retry_export"
SHOWCASE_DATA_KEYS = (
    *SYNTHETIC_RESPONSES,
    "showcase_camera_started",
    *RECORDER_SESSION_KEYS,
    SHOWCASE_ARCHIVE_KEY,
    SHOWCASE_EXPORT_ERROR_KEY,
    SHOWCASE_LOCAL_SAVE_KEY,
    SHOWCASE_DOWNLOAD_BUTTON_KEY,
    SHOWCASE_RETRY_BUTTON_KEY,
)
RAW_WIDGET_WITH_PRIVATE_FIELDS = {
    "mode": "demo",
    "state": "saved",
    "duration_seconds": 2,
    "camera_ready": True,
    "microphone_ready": True,
    "saved_confirmed": True,
    "error_code": None,
    "blob": "private-blob-marker",
    "media": "private-media-marker",
    "path": "private-path-marker",
}
SYNTHETIC_LABELS = (
    "本次演示流程有多清晰？",
    "摄像头交互有多顺畅？",
    "界面的信息量有多合适？",
    "你愿意继续使用这一流程吗？",
)
PROGRESS_LABELS = (
    "1 安全进入",
    "2 会话记录",
    "3 引导反馈",
    "4 本地下载",
    "5 完成确认",
)
EXPECTED_DOWNLOAD_INVENTORY = (
    ("title", "value", PRODUCT_NAME),
    ("caption", "value", PRODUCT_CAPTION),
    (
        "markdown",
        "value",
        '<p class="demo-kicker">CONTROLLED DEMONSTRATION</p>',
    ),
    ("subheader", "value", "下载合成演示数据"),
    (
        "caption",
        "value",
        "下载文件仅包含合成演示内容，并且只会保存在本机。",
    ),
    ("download_button", "value", False),
    ("download_button", "label", "下载合成演示 ZIP"),
    ("checkbox", "value", False),
    ("checkbox", "label", "我已确认合成 ZIP 已保存在本机"),
    ("button", "label", "完成演示"),
)
EXPECTED_CONFIRMATION_INVENTORY = (
    ("title", "value", PRODUCT_NAME),
    ("caption", "value", PRODUCT_CAPTION),
    (
        "markdown",
        "value",
        '<p class="demo-kicker">CONTROLLED DEMONSTRATION</p>',
    ),
    (
        "markdown",
        "value",
        '<div class="completion-status" role="status">'
        "演示流程已完成。</div>",
    ),
    (
        "markdown",
        "value",
        '<div class="privacy-note"><strong>隐私边界</strong><br>'
        "本演示不包含研究名称、干预参数、测量内容、评分规则或真实参与者数据。"
        "</div>",
    ),
    ("button", "label", "重新体验"),
)


def _app_with_password(app_path: Path = APP) -> AppTest:
    app = AppTest.from_file(str(app_path), default_timeout=10)
    app.secrets["SHOWCASE_PASSWORD_SHA256"] = hashlib.sha256(
        PASSWORD.encode("utf-8")
    ).hexdigest()
    return app


def _element_by_key(elements, key):
    matches = [element for element in elements if element.key == key]
    assert len(matches) == 1
    return matches[0]


def _visible_text(app: AppTest) -> str:
    values = []
    for collection_name in (
        "title",
        "subheader",
        "caption",
        "markdown",
        "info",
        "warning",
        "error",
        "success",
        "button",
        "checkbox",
        "slider",
        "text_input",
    ):
        for element in getattr(app, collection_name):
            attributes = (
                ("label", "help", "placeholder")
                if collection_name
                in {"button", "checkbox", "slider", "text_input"}
                else ("value", "label", "help", "placeholder")
            )
            for attribute in attributes:
                value = getattr(element, attribute, None)
                if value is not None:
                    values.append(str(value))
    for element in app.get("download_button"):
        for attribute in ("label", "help"):
            value = getattr(element, attribute, None)
            if value is not None:
                values.append(str(value))
    return "\n".join(values)


def _main_content_inventory(app: AppTest):
    inventory = []

    def visit(node):
        node_type = getattr(node, "type", type(node).__name__)
        visible_fields = []
        for attribute in ("value", "label", "help", "placeholder"):
            if node_type == "button" and attribute == "value":
                continue
            try:
                value = getattr(node, attribute)
            except AttributeError:
                continue
            if value is None or (isinstance(value, str) and value == ""):
                continue
            if not isinstance(value, (str, int, float, bool)):
                value = repr(value)
            visible_fields.append((attribute, value))

        markdown_values = [
            value
            for attribute, value in visible_fields
            if attribute == "value" and isinstance(value, str)
        ]
        is_standalone_stylesheet = (
            node_type == "markdown"
            and len(markdown_values) == 1
            and markdown_values[0].strip().startswith("<style>")
            and markdown_values[0].strip().endswith("</style>")
            and markdown_values[0].strip().count("<style>") == 1
            and markdown_values[0].strip().count("</style>") == 1
        )

        structural_types = {"main", "vertical"}
        if not is_standalone_stylesheet and (
            node_type not in structural_types or visible_fields
        ):
            if visible_fields:
                inventory.extend(
                    (node_type, attribute, value)
                    for attribute, value in visible_fields
                )
            else:
                inventory.append((node_type, "node", None))

        children = getattr(node, "children", None)
        if children is not None:
            for child in children.values():
                visit(child)

    visit(app.main)
    return tuple(inventory)


def _authenticate(app: AppTest) -> AppTest:
    app.run()
    _element_by_key(app.text_input, "showcase_password").set_value(PASSWORD)
    _element_by_key(app.button, "enter_demo").click().run()
    assert not app.exception
    return app


def _assert_progress(app: AppTest, active_label: str) -> None:
    sidebar_text = "\n".join(item.value for item in app.sidebar.markdown)
    for label in PROGRESS_LABELS:
        assert label in sidebar_text
    assert f"当前 · {active_label}" in sidebar_text


def _recorder_spy(monkeypatch, status=RecorderStatus()):
    recorder_calls = []

    def render_recorder(*, key, initial_mode):
        recorder_calls.append((key, initial_mode))
        return status

    monkeypatch.setattr(
        browser_recorder,
        "render_browser_recorder",
        render_recorder,
    )
    return recorder_calls


def _capture_app(monkeypatch, status=RecorderStatus()) -> tuple[AppTest, list]:
    recorder_calls = _recorder_spy(monkeypatch, status)
    app = _app_with_password()
    _authenticate(app)
    _element_by_key(app.button, "begin_demo").click().run()

    assert not app.exception
    return app, recorder_calls


def _advance_to_download(
    monkeypatch,
    *,
    status: RecorderStatus,
    responses: dict[str, int],
) -> AppTest:
    app, _ = _capture_app(monkeypatch, status)
    continue_key = (
        "finish_capture"
        if status.state == "saved" and status.saved_confirmed
        else "continue_without_recording"
    )
    _element_by_key(app.button, continue_key).click().run()
    for key, value in responses.items():
        _element_by_key(app.slider, key).set_value(value)
    app.run()
    _element_by_key(app.button, "save_reflection").click().run()
    assert not app.exception
    assert app.session_state["showcase_step"] == "download"
    return app


def _seed_download_state(app: AppTest) -> None:
    for key, value in SYNTHETIC_RESPONSES.items():
        app.session_state[key] = value
    app.session_state["showcase_camera_started"] = True
    app.session_state[SHOWCASE_ARCHIVE_KEY] = SyntheticShowcaseArchive(
        filename="synthetic-session.zip",
        data=b"synthetic-zip",
    )
    app.session_state[SHOWCASE_EXPORT_ERROR_KEY] = True
    app.session_state[SHOWCASE_LOCAL_SAVE_KEY] = True
    app.session_state[SHOWCASE_DOWNLOAD_BUTTON_KEY] = True
    app.session_state[SHOWCASE_RETRY_BUTTON_KEY] = True


def test_showcase_fails_closed_without_configured_password(monkeypatch):
    monkeypatch.delenv("SHOWCASE_PASSWORD_SHA256", raising=False)

    app = AppTest.from_file(str(APP), default_timeout=10).run()

    assert not app.exception
    assert [item.value for item in app.error] == [
        "演示暂未开放，请联系项目团队。"
    ]
    assert not app.text_input
    assert not app.button
    assert "showcase_step" not in app.session_state


def test_showcase_rejects_wrong_password_and_accepts_exact_password():
    app = _app_with_password().run()
    assert PRODUCT_NAME in [item.value for item in app.title]
    assert PRODUCT_CAPTION in [item.value for item in app.caption]

    _element_by_key(app.text_input, "showcase_password").set_value(
        "wrong-passphrase"
    )
    _element_by_key(app.button, "enter_demo").click().run()
    assert [item.value for item in app.error] == ["访问密码错误。"]
    assert "showcase_authenticated" not in app.session_state

    _element_by_key(app.text_input, "showcase_password").set_value(PASSWORD)
    _element_by_key(app.button, "enter_demo").click().run()

    assert not app.exception
    assert app.session_state["showcase_authenticated"] is True
    assert app.session_state["showcase_step"] == "overview"
    assert PRODUCT_NAME in [item.value for item in app.title]


@pytest.mark.parametrize(
    "query_value",
    (None, "", "0", "1", "true", "01", ["1", "1"], ["0", "1"]),
    ids=(
        "missing",
        "empty",
        "zero",
        "one",
        "word",
        "padded",
        "repeated",
        "ambiguous-repeated",
    ),
)
def test_capture_always_uses_browser_recorder_regardless_of_probe_query(
    monkeypatch, query_value
):
    status = RecorderStatus(
        state="ready",
        camera_ready=True,
        microphone_ready=True,
    )
    recorder_calls = _recorder_spy(monkeypatch, status)
    app = _app_with_password()
    if query_value is not None:
        app.query_params["recorder_probe"] = query_value

    _authenticate(app)
    _element_by_key(app.button, "begin_demo").click().run()

    assert not app.exception
    assert recorder_calls == [("showcase_session_recorder", "demo")]
    assert app.session_state["showcase_recorder_status"] == status
    assert "showcase_camera_started" not in app.session_state


def test_authenticated_capture_uses_stable_browser_recorder_key(
    monkeypatch,
):
    status = RecorderStatus(
        state="ready",
        camera_ready=True,
        microphone_ready=True,
    )
    app, recorder_calls = _capture_app(monkeypatch, status)

    assert recorder_calls == [("showcase_session_recorder", "demo")]
    assert app.session_state["showcase_recorder_status"] == status

    app.run()

    assert recorder_calls == [
        ("showcase_session_recorder", "demo"),
        ("showcase_session_recorder", "demo"),
    ]


def test_recorder_is_not_rendered_before_authentication(
    monkeypatch,
):
    recorder_calls = _recorder_spy(monkeypatch)
    app = _app_with_password()
    app.query_params["recorder_probe"] = "1"

    app.run()

    assert recorder_calls == []
    assert "视频和声音仅保存在本机" not in _visible_text(app)
    assert "返回流程概览" not in _visible_text(app)

    _element_by_key(app.text_input, "showcase_password").set_value(
        "wrong-passphrase"
    )
    _element_by_key(app.button, "enter_demo").click().run()

    assert recorder_calls == []
    assert "视频和声音仅保存在本机" not in _visible_text(app)


@pytest.mark.parametrize("query_value", (None, "1"), ids=("default", "legacy-query"))
def test_overview_always_describes_user_controlled_local_saving(query_value):
    app = _app_with_password()
    if query_value is not None:
        app.query_params["recorder_probe"] = query_value
    visible_text = _visible_text(_authenticate(app))

    assert "录像" in visible_text
    assert "保存在本机" in visible_text
    assert "不会上传" in visible_text
    assert "外部存储" in visible_text
    assert "不会保存文件" not in visible_text


def test_idle_recorder_is_neutral_and_cannot_continue(monkeypatch):
    app, _ = _capture_app(monkeypatch, RecorderStatus())

    assert [item.value for item in app.info] == ["本机录制工具正在准备。"]
    assert not [button for button in app.button if button.key == "finish_capture"]
    assert not [
        button
        for button in app.button
        if button.key == "continue_without_recording"
    ]


def test_registered_recorder_component_discards_raw_and_preserves_identity():
    recording_raw = {
        "mode": "demo",
        "state": "recording",
        "duration_seconds": 2,
        "camera_ready": True,
        "microphone_ready": True,
        "saved_confirmed": False,
        "error_code": None,
    }
    recording_status = RecorderStatus(
        state="recording",
        duration_seconds=2,
        camera_ready=True,
        microphone_ready=True,
    )
    saved_raw = {
        **recording_raw,
        "state": "saved",
        "saved_confirmed": True,
    }
    saved_status = RecorderStatus(
        state="saved",
        duration_seconds=2,
        camera_ready=True,
        microphone_ready=True,
        saved_confirmed=True,
    )
    app = _app_with_password()
    app.session_state["showcase_authenticated"] = True
    app.session_state["showcase_step"] = "capture"
    app.session_state["showcase_session_recorder"] = recording_raw

    app.run()

    assert not app.exception
    assert "showcase_session_recorder" not in app.session_state
    assert app.session_state["showcase_recorder_status"] == recording_status
    first_components = app.get("component_instance")
    assert len(first_components) == 1
    component_id = first_components[0].proto.id

    app.run()

    assert not app.exception
    assert "showcase_session_recorder" not in app.session_state
    assert app.session_state["showcase_recorder_status"] == recording_status
    second_components = app.get("component_instance")
    assert len(second_components) == 1
    assert second_components[0].proto.id == component_id

    app.session_state["showcase_session_recorder"] = saved_raw
    app.run()

    assert not app.exception
    assert "showcase_session_recorder" not in app.session_state
    assert app.session_state["showcase_recorder_status"] == saved_status
    third_components = app.get("component_instance")
    assert len(third_components) == 1
    assert third_components[0].proto.id == component_id


def test_registered_recorder_component_discards_private_raw_fields():
    app = _app_with_password()
    app.session_state["showcase_authenticated"] = True
    app.session_state["showcase_step"] = "capture"
    app.session_state["showcase_session_recorder"] = dict(
        RAW_WIDGET_WITH_PRIVATE_FIELDS
    )

    app.run()

    assert not app.exception
    assert "showcase_session_recorder" not in app.session_state
    assert app.session_state["showcase_recorder_status"] == RecorderStatus()
    for marker in (
        "private-blob-marker",
        "private-media-marker",
        "private-path-marker",
    ):
        assert marker not in _visible_text(app)


@pytest.mark.parametrize(
    ("raw_status", "expected_status", "continue_available"),
    (
        (
            {
                "mode": "demo",
                "state": "recording",
                "duration_seconds": 3,
                "camera_ready": True,
                "microphone_ready": True,
                "saved_confirmed": False,
                "error_code": None,
            },
            RecorderStatus(
                state="recording",
                duration_seconds=3,
                camera_ready=True,
                microphone_ready=True,
            ),
            False,
        ),
        (
            {
                "mode": "demo",
                "state": "saved",
                "duration_seconds": 3,
                "camera_ready": True,
                "microphone_ready": True,
                "saved_confirmed": True,
                "error_code": None,
            },
            RecorderStatus(
                state="saved",
                duration_seconds=3,
                camera_ready=True,
                microphone_ready=True,
                saved_confirmed=True,
            ),
            True,
        ),
    ),
    ids=("recording", "saved"),
)
def test_recorder_consumes_raw_events_and_preserves_status_on_plain_rerun(
    monkeypatch, raw_status, expected_status, continue_available
):
    component_values = [raw_status, None]
    component_calls = []

    def fake_component(**kwargs):
        component_calls.append(kwargs)
        value = component_values.pop(0)
        st.session_state[kwargs["key"]] = value
        return value

    monkeypatch.setattr(browser_recorder, "_COMPONENT", fake_component)
    app = _app_with_password()
    app.session_state["showcase_authenticated"] = True
    app.session_state["showcase_step"] = "capture"

    app.run()

    assert not app.exception
    assert app.session_state["showcase_recorder_status"] == expected_status
    assert "showcase_session_recorder" not in app.session_state

    app.run()

    assert not app.exception
    assert app.session_state["showcase_recorder_status"] == expected_status
    assert "showcase_session_recorder" not in app.session_state
    assert bool(
        [button for button in app.button if button.key == "finish_capture"]
    ) is continue_available
    assert component_calls == [
        {
            "key": "showcase_session_recorder",
            "initial_mode": "demo",
            "default": None,
        },
        {
            "key": "showcase_session_recorder",
            "initial_mode": "demo",
            "default": None,
        },
    ]


@pytest.mark.parametrize(
    "status",
    (
        RecorderStatus(state="ready", camera_ready=True, microphone_ready=True),
        RecorderStatus(state="recording", duration_seconds=3),
        RecorderStatus(state="stopped", duration_seconds=3),
        RecorderStatus(
            state="saved",
            duration_seconds=3,
            saved_confirmed=False,
        ),
    ),
    ids=("ready", "recording", "stopped", "unconfirmed-save"),
)
def test_recorder_blocks_continue_until_local_save_is_confirmed(
    monkeypatch, status
):
    app, _ = _capture_app(monkeypatch, status)

    assert not [button for button in app.button if button.key == "finish_capture"]
    assert not [
        button
        for button in app.button
        if button.key == "continue_without_recording"
    ]
    assert app.info


def test_recorder_confirmed_save_continues_with_camera_feedback(
    monkeypatch,
):
    status = RecorderStatus(
        state="saved",
        duration_seconds=3,
        camera_ready=True,
        microphone_ready=True,
        saved_confirmed=True,
    )
    app, _ = _capture_app(monkeypatch, status)

    continue_button = _element_by_key(app.button, "finish_capture")
    assert "继续" in continue_button.label
    continue_button.click().run()

    assert app.session_state["showcase_step"] == "reflection"
    assert app.session_state["showcase_camera_started"] is True
    assert tuple(slider.key for slider in app.slider) == tuple(
        SYNTHETIC_RESPONSES
    )


@pytest.mark.parametrize(
    "status",
    (
        RecorderStatus(state="skipped"),
        RecorderStatus(state="failed", error_code="write_failed"),
    ),
    ids=("skipped", "failed"),
)
def test_recorder_requires_explicit_continue_without_video(
    monkeypatch, status
):
    app, _ = _capture_app(monkeypatch, status)

    continue_button = _element_by_key(
        app.button, "continue_without_recording"
    )
    assert "无录像继续" in continue_button.label
    assert "write_failed" not in _visible_text(app)
    continue_button.click().run()

    assert app.session_state["showcase_step"] == "reflection"
    assert "showcase_camera_started" not in app.session_state
    assert tuple(slider.key for slider in app.slider) == NON_CAMERA_RESPONSE_KEYS
    assert CAMERA_FEEDBACK_SKIPPED_CAPTION in [
        item.value for item in app.caption
    ]


def test_recorder_copy_is_local_private_and_neutral(monkeypatch):
    app, _ = _capture_app(
        monkeypatch,
        RecorderStatus(
            state="ready",
            camera_ready=True,
            microphone_ready=True,
        ),
    )

    visible_text = _visible_text(app)
    assert "视频和声音仅保存在本机" in visible_text
    assert "不会上传" in visible_text
    assert "返回流程概览" in visible_text
    for forbidden in (
        "tavns",
        "nssi",
        "twi" + "lio",
        "t" + "urn",
        "i" + "ce",
        "问卷",
        "评分",
        "阈值",
    ):
        assert forbidden not in visible_text.casefold()


def test_recorder_rejects_unparsed_component_values(monkeypatch):
    app, _ = _capture_app(
        monkeypatch,
        {"state": "saved", "blob": b"private-media-marker"},
    )

    assert app.session_state["showcase_recorder_status"] == RecorderStatus()
    assert "private-media-marker" not in _visible_text(app)


def test_recorder_can_return_to_overview_and_clears_recorder_state(
    monkeypatch,
):
    app, _ = _capture_app(
        monkeypatch,
        RecorderStatus(
            state="ready",
            camera_ready=True,
            microphone_ready=True,
        ),
    )
    app.session_state["showcase_session_recorder"] = dict(
        RAW_WIDGET_WITH_PRIVATE_FIELDS
    )
    _seed_download_state(app)

    _element_by_key(app.button, "return_to_overview").click().run()

    assert app.session_state["showcase_step"] == "overview"
    assert app.session_state["showcase_authenticated"] is True
    for key in SHOWCASE_DATA_KEYS:
        assert key not in app.session_state


def test_restart_clears_recorder_state_without_exposing_raw_status():
    app = _app_with_password()
    app.session_state["showcase_authenticated"] = True
    app.session_state["showcase_step"] = "confirmation"
    app.session_state["showcase_recorder_status"] = RecorderStatus(
        state="failed",
        error_code="write_failed",
    )
    app.session_state["showcase_session_recorder"] = dict(
        RAW_WIDGET_WITH_PRIVATE_FIELDS
    )
    _seed_download_state(app)
    app.run()

    assert not app.exception
    assert "showcase_session_recorder" not in app.session_state
    assert _main_content_inventory(app) == EXPECTED_CONFIRMATION_INVENTORY
    assert "write_failed" not in _visible_text(app)

    _element_by_key(app.button, "restart_demo").click().run()

    assert app.session_state["showcase_step"] == "overview"
    assert app.session_state["showcase_authenticated"] is True
    for key in SHOWCASE_DATA_KEYS:
        assert key not in app.session_state


def test_download_builds_once_and_uses_exact_cached_archive_contract(
    monkeypatch,
):
    archive = SyntheticShowcaseArchive(
        filename="synthetic-session-20260728-091530.zip",
        data=b"exact-synthetic-zip-bytes",
    )
    build_calls: list[dict[str, object]] = []
    download_calls: list[dict[str, object]] = []

    def build_archive(**kwargs):
        build_calls.append(kwargs)
        return archive

    def capture_download(**kwargs):
        download_calls.append(kwargs)
        return True

    monkeypatch.setattr(
        showcase_export,
        "build_synthetic_showcase_zip",
        build_archive,
    )
    monkeypatch.setattr(st, "download_button", capture_download)
    before = datetime.now(timezone.utc).replace(microsecond=0)

    app = _advance_to_download(
        monkeypatch,
        status=RecorderStatus(
            state="saved",
            duration_seconds=3,
            camera_ready=True,
            microphone_ready=True,
            saved_confirmed=True,
        ),
        responses=dict(SYNTHETIC_RESPONSES),
    )
    after = datetime.now(timezone.utc).replace(microsecond=0)

    assert len(build_calls) == 1
    assert build_calls[0] == {
        **SYNTHETIC_RESPONSES,
        "recording_state": "saved",
        "generated_at": build_calls[0]["generated_at"],
    }
    generated_at = build_calls[0]["generated_at"]
    assert type(generated_at) is datetime
    assert generated_at.tzinfo is timezone.utc
    assert generated_at.microsecond == 0
    assert before <= generated_at <= after
    assert app.session_state[SHOWCASE_ARCHIVE_KEY] is archive
    assert SHOWCASE_EXPORT_ERROR_KEY not in app.session_state
    assert app.session_state["showcase_step"] == "download"
    assert download_calls == [
        {
            "label": "下载合成演示 ZIP",
            "data": archive.data,
            "file_name": archive.filename,
            "mime": "application/zip",
            "key": SHOWCASE_DOWNLOAD_BUTTON_KEY,
        }
    ]
    assert _element_by_key(app.button, "finish_download").disabled is True

    app.run()

    assert not app.exception
    assert len(build_calls) == 1
    assert app.session_state[SHOWCASE_ARCHIVE_KEY] is archive
    assert app.session_state["showcase_step"] == "download"
    assert download_calls == [download_calls[0], download_calls[0]]


def test_download_failure_is_neutral_retryable_and_preserves_all_state(
    monkeypatch,
):
    status = RecorderStatus(
        state="saved",
        duration_seconds=3,
        camera_ready=True,
        microphone_ready=True,
        saved_confirmed=True,
    )
    archive = SyntheticShowcaseArchive(
        filename="synthetic-session.zip",
        data=b"retry-synthetic-zip",
    )
    attempts: list[dict[str, object]] = []

    def flaky_builder(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("PRIVATE-EXPORT-TRACE-/secret/path.zip")
        return archive

    monkeypatch.setattr(
        showcase_export,
        "build_synthetic_showcase_zip",
        flaky_builder,
    )
    app = _advance_to_download(
        monkeypatch,
        status=status,
        responses=dict(SYNTHETIC_RESPONSES),
    )

    visible = _visible_text(app)
    assert "下载文件暂时无法生成，请重试。" in visible
    assert "PRIVATE-EXPORT-TRACE" not in visible
    assert "/secret/path.zip" not in visible
    assert app.session_state[SHOWCASE_EXPORT_ERROR_KEY] is True
    assert type(app.session_state[SHOWCASE_EXPORT_ERROR_KEY]) is bool
    assert SHOWCASE_ARCHIVE_KEY not in app.session_state
    assert not app.get("download_button")
    assert not [button for button in app.button if button.key == "finish_download"]
    assert {
        key: app.session_state[key] for key in SYNTHETIC_RESPONSES
    } == SYNTHETIC_RESPONSES
    assert app.session_state["showcase_recorder_status"] == status
    assert all(
        "PRIVATE-EXPORT-TRACE" not in repr(value)
        and "/secret/path.zip" not in repr(value)
        for value in app.session_state.filtered_state.values()
    )
    retry_button = _element_by_key(app.button, SHOWCASE_RETRY_BUTTON_KEY)
    assert retry_button.label == "重试生成"

    app.run()

    assert not app.exception
    assert len(attempts) == 1
    assert app.session_state[SHOWCASE_EXPORT_ERROR_KEY] is True
    _element_by_key(app.button, SHOWCASE_RETRY_BUTTON_KEY).click().run()

    assert not app.exception
    assert len(attempts) == 2
    assert app.session_state[SHOWCASE_ARCHIVE_KEY] is archive
    assert SHOWCASE_EXPORT_ERROR_KEY not in app.session_state
    assert {
        key: app.session_state[key] for key in SYNTHETIC_RESPONSES
    } == SYNTHETIC_RESPONSES
    assert app.session_state["showcase_recorder_status"] == status
    assert len(app.get("download_button")) == 1
    assert app.session_state["showcase_step"] == "download"
    assert _element_by_key(app.button, "finish_download").disabled is True


@pytest.mark.parametrize(
    "invalid_status",
    ("missing", "non-status", "non-terminal"),
)
def test_download_fails_closed_for_missing_or_invalid_recording_status(
    monkeypatch,
    invalid_status,
):
    build_calls: list[dict[str, object]] = []

    def forbidden_builder(**kwargs):
        build_calls.append(kwargs)
        return SyntheticShowcaseArchive(
            filename="distorted-synthetic-session.zip",
            data=b"distorted-synthetic-zip",
        )

    monkeypatch.setattr(
        showcase_export,
        "build_synthetic_showcase_zip",
        forbidden_builder,
    )
    app = _app_with_password()
    app.session_state["showcase_authenticated"] = True
    app.session_state["showcase_step"] = "download"
    app.session_state["showcase_camera_started"] = True
    for key, value in SYNTHETIC_RESPONSES.items():
        app.session_state[key] = value
    if invalid_status == "non-status":
        app.session_state["showcase_recorder_status"] = {
            "state": "saved",
            "detail": "PRIVATE-RECORDING-STATUS",
        }
    elif invalid_status == "non-terminal":
        app.session_state["showcase_recorder_status"] = RecorderStatus(
            state="recording",
            duration_seconds=3,
        )

    app.run()

    assert not app.exception
    assert build_calls == []
    assert app.session_state[SHOWCASE_EXPORT_ERROR_KEY] is True
    assert SHOWCASE_ARCHIVE_KEY not in app.session_state
    assert not app.get("download_button")
    assert not [button for button in app.button if button.key == "finish_download"]
    assert "下载文件暂时无法生成，请重试。" in _visible_text(app)
    assert "PRIVATE-RECORDING-STATUS" not in _visible_text(app)
    assert {
        key: app.session_state[key] for key in SYNTHETIC_RESPONSES
    } == SYNTHETIC_RESPONSES

    _element_by_key(app.button, SHOWCASE_RETRY_BUTTON_KEY).click().run()

    assert not app.exception
    assert build_calls == []
    assert app.session_state[SHOWCASE_EXPORT_ERROR_KEY] is True
    assert app.session_state["showcase_step"] == "download"


@pytest.mark.parametrize("recording_state", ("skipped", "failed"))
def test_download_uses_none_camera_rating_without_saved_recording(
    monkeypatch,
    recording_state,
):
    archive = SyntheticShowcaseArchive(
        filename="synthetic-session.zip",
        data=b"non-camera-synthetic-zip",
    )
    build_calls: list[dict[str, object]] = []

    def build_archive(**kwargs):
        build_calls.append(kwargs)
        return archive

    monkeypatch.setattr(
        showcase_export,
        "build_synthetic_showcase_zip",
        build_archive,
    )
    status = RecorderStatus(
        state=recording_state,
        error_code="write_failed" if recording_state == "failed" else None,
    )
    responses = {key: SYNTHETIC_RESPONSES[key] for key in NON_CAMERA_RESPONSE_KEYS}

    app = _advance_to_download(
        monkeypatch,
        status=status,
        responses=responses,
    )

    assert len(build_calls) == 1
    assert build_calls[0]["camera_smoothness"] is None
    assert build_calls[0]["recording_state"] == recording_state
    assert {key: build_calls[0][key] for key in NON_CAMERA_RESPONSE_KEYS} == responses
    assert "camera_smoothness" not in app.session_state
    assert app.session_state["showcase_recorder_status"] == status


def test_download_inventory_is_exact_and_hides_ratings_and_filename(
    monkeypatch,
):
    archive = SyntheticShowcaseArchive(
        filename="synthetic-session-private-detail.zip",
        data=b"inventory-synthetic-zip",
    )
    monkeypatch.setattr(
        showcase_export,
        "build_synthetic_showcase_zip",
        lambda **kwargs: archive,
    )

    app = _app_with_password()
    app.session_state["showcase_authenticated"] = True
    app.session_state["showcase_step"] = "download"
    app.session_state["showcase_recorder_status"] = RecorderStatus(
        state="saved",
        duration_seconds=3,
        saved_confirmed=True,
    )
    app.session_state["showcase_camera_started"] = True
    app.session_state[SHOWCASE_ARCHIVE_KEY] = archive
    for key, value in SYNTHETIC_RESPONSES.items():
        app.session_state[key] = value
    app.run()

    assert not app.exception
    assert _main_content_inventory(app) == EXPECTED_DOWNLOAD_INVENTORY
    visible = _visible_text(app)
    assert archive.filename not in visible
    for hidden in (*SYNTHETIC_RESPONSES, "score", "answer", "path"):
        assert hidden.casefold() not in visible.casefold()


def test_showcase_completes_and_restarts_session_only_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    archive = SyntheticShowcaseArchive(
        filename="synthetic-session.zip",
        data=b"end-to-end-synthetic-zip",
    )
    monkeypatch.setattr(
        showcase_export,
        "build_synthetic_showcase_zip",
        lambda **kwargs: archive,
    )
    _recorder_spy(
        monkeypatch,
        RecorderStatus(
            state="saved",
            duration_seconds=3,
            camera_ready=True,
            microphone_ready=True,
            saved_confirmed=True,
        ),
    )
    app = _authenticate(_app_with_password())

    overview_text = _visible_text(app)
    assert "准备开始本次演示" in overview_text
    assert "录像" in overview_text
    assert "保存在本机" in overview_text
    assert "不会上传" in overview_text
    assert "外部存储" in overview_text
    _assert_progress(app, "1 安全进入")
    _element_by_key(app.button, "begin_demo").click().run()

    capture_text = _visible_text(app)
    assert "本机录制" in capture_text
    assert "视频和声音仅保存在本机" in capture_text
    assert "不会上传" in capture_text
    _assert_progress(app, "2 会话记录")
    _element_by_key(app.button, "finish_capture").click().run()

    for key in SYNTHETIC_RESPONSES:
        slider = _element_by_key(app.slider, key)
        assert slider.value == 2
        assert slider.proto.min == 0
        assert slider.proto.max == 4
    assert tuple(element.key for element in app.slider) == tuple(
        SYNTHETIC_RESPONSES
    )
    assert tuple(element.label for element in app.slider) == SYNTHETIC_LABELS
    _assert_progress(app, "3 引导反馈")

    for key, value in SYNTHETIC_RESPONSES.items():
        _element_by_key(app.slider, key).set_value(value)
    app.run()
    _element_by_key(app.button, "save_reflection").click().run()

    assert not app.exception
    assert not app.success
    assert "下载合成演示数据" in _visible_text(app)
    _assert_progress(app, "4 本地下载")
    assert len(app.get("download_button")) == 1
    finish_button = _element_by_key(app.button, "finish_download")
    assert finish_button.label == "完成演示"
    assert finish_button.disabled is True
    assert app.session_state["showcase_step"] == "download"
    assert list(tmp_path.iterdir()) == []

    confirmation = _element_by_key(
        app.checkbox,
        SHOWCASE_LOCAL_SAVE_KEY,
    )
    assert confirmation.label == "我已确认合成 ZIP 已保存在本机"
    confirmation.set_value(True)
    app.run()
    finish_button = _element_by_key(app.button, "finish_download")
    assert finish_button.disabled is False
    finish_button.click().run()

    assert not app.exception
    completion_panels = [
        item.value
        for item in app.markdown
        if 'class="completion-status"' in item.value
    ]
    assert completion_panels == [
        '<div class="completion-status" role="status">演示流程已完成。</div>'
    ]
    assert "隐私边界" in _visible_text(app)
    _assert_progress(app, "5 完成确认")
    assert list(tmp_path.iterdir()) == []

    # AppTest 1.37.1 and 1.45.1 retain stale pre-rerun slider deltas, so this
    # fresh populated session verifies current confirmation rendering and cleanup.
    confirmation_app = _app_with_password()
    confirmation_app.session_state["showcase_authenticated"] = True
    confirmation_app.session_state["showcase_step"] = "confirmation"
    _seed_download_state(confirmation_app)
    confirmation_app.session_state["showcase_recorder_status"] = RecorderStatus(
        state="saved",
        saved_confirmed=True,
    )
    confirmation_app.run()

    assert (
        _main_content_inventory(confirmation_app)
        == EXPECTED_CONFIRMATION_INVENTORY
    )

    _element_by_key(confirmation_app.button, "restart_demo").click().run()
    assert confirmation_app.session_state["showcase_step"] == "overview"
    assert confirmation_app.session_state["showcase_authenticated"] is True
    for key in SHOWCASE_DATA_KEYS:
        assert key not in confirmation_app.session_state


def test_confirmation_inventory_rejects_unknown_and_style_smuggled_output(
    tmp_path,
):
    source = APP.read_text(encoding="utf-8")
    restart_anchor = '        if st.button("重新体验", key="restart_demo"):\n'
    mutations = (
        ("status", '        st.status("综合评分：4")\n'),
        ("latex", '        st.latex(r"综合评分 = 4")\n'),
        ("checkbox", '        st.checkbox("综合评分：4")\n'),
        (
            "style-smuggling",
            '        st.markdown(\n'
            '            "<style>.x { color: red; }</style><p>评分：4</p>",\n'
            "            unsafe_allow_html=True,\n"
            "        )\n",
        ),
    )
    unexpectedly_allowed = []

    for name, mutation in mutations:
        mutated_source = source.replace(
            restart_anchor,
            mutation + restart_anchor,
            1,
        )
        mutated_path = tmp_path / f"mutated_showcase_{name}.py"
        mutated_path.write_text(mutated_source, encoding="utf-8")
        mutated_app = _app_with_password(mutated_path)
        mutated_app.session_state["showcase_authenticated"] = True
        mutated_app.session_state["showcase_step"] = "confirmation"
        mutated_app.run()

        assert not mutated_app.exception
        if (
            _main_content_inventory(mutated_app)
            == EXPECTED_CONFIRMATION_INVENTORY
        ):
            unexpectedly_allowed.append(name)

    assert unexpectedly_allowed == []


def test_visible_copy_is_neutral_on_every_authenticated_step(monkeypatch):
    _recorder_spy(
        monkeypatch,
        RecorderStatus(
            state="saved",
            duration_seconds=3,
            camera_ready=True,
            microphone_ready=True,
            saved_confirmed=True,
        ),
    )
    app = _authenticate(_app_with_password())
    visible_by_step = [_visible_text(app)]

    _element_by_key(app.button, "begin_demo").click().run()
    visible_by_step.append(_visible_text(app))
    _element_by_key(app.button, "finish_capture").click().run()
    visible_by_step.append(_visible_text(app))
    _element_by_key(app.button, "save_reflection").click().run()
    visible_by_step.append(_visible_text(app))
    _element_by_key(app.checkbox, SHOWCASE_LOCAL_SAVE_KEY).set_value(True)
    app.run()
    _element_by_key(app.button, "finish_download").click().run()
    visible_by_step.append(_visible_text(app))

    for visible_text in visible_by_step:
        assert PRODUCT_NAME in visible_text
        assert PRODUCT_CAPTION in visible_text
        folded = visible_text.casefold()
        for forbidden in (
            "tavns",
            "nssi",
            "score",
            "answer",
            "threshold",
            "media",
            "blob",
            "path",
            "filename",
            "device label",
            "twi" + "lio",
            "i" + "ce",
        ):
            assert forbidden not in folded


def test_showcase_has_no_probe_split_or_legacy_media_hooks():
    source = APP.read_text(encoding="utf-8")

    assert "recorder_probe_enabled" not in source
    assert "query_params" not in source
    for legacy_name in (
        "TWILIO" + "_",
        "showcase" + "_ice",
        "showcase" + "_media",
        "resolve_turn_rtc_configuration",
        "render_live_camera",
        "camera_is_playing",
        "LOGGER",
    ):
        assert legacy_name not in source


def test_showcase_source_has_no_private_or_io_capabilities():
    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    prohibited_import_fragments = (
        "questionnaire",
        "upload",
        "requests",
        "webrtc",
        "aiortc",
        "av",
        "twi" + "lio",
        "showcase" + "_ice",
        "showcase" + "_media",
        "logging",
    )
    assert not any(
        fragment in module.casefold()
        for module in imported_modules
        for fragment in prohibited_import_fragments
    )

    prohibited_calls = {
        "camera_input",
        "file_uploader",
        "open",
        "touch",
        "mkdir",
        "write_bytes",
        "write_text",
        "webrtc_streamer",
        "resolve_turn_rtc_configuration",
        "render_live_camera",
        "camera_is_playing",
    }
    call_names = {
        node.func.id
        if isinstance(node.func, ast.Name)
        else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert prohibited_calls.isdisjoint(call_names)
    assert not any("upload" in name.casefold() for name in call_names)
    assert "http://" not in source.casefold()
    assert "https://" not in source.casefold()
    assert "st.image" not in source
    assert "st.success" not in source
    assert "st.set_page_config(page_title=PRODUCT_NAME" in source
    assert 'layout="centered"' in source


def test_streamlit_theme_and_app_palette_are_exact_and_green_free():
    config_text = THEME.read_text(encoding="utf-8")
    assert tomllib.loads(config_text) == {
        "theme": {
            "primaryColor": "#DD1D86",
            "backgroundColor": "#FFFFFF",
            "secondaryBackgroundColor": "#F4F4F4",
            "textColor": "#000035",
            "font": "sans serif",
        }
    }

    source = APP.read_text(encoding="utf-8")
    approved_colors = {
        "#000035",
        "#2D2674",
        "#DD1D86",
        "#33B0E4",
        "#FFBC7D",
        "#F4F4F4",
        "#FFFFFF",
    }
    color_tokens = {
        token.upper() for token in re.findall(r"#[0-9a-fA-F]{6}\b", source)
    }
    assert color_tokens == approved_colors
    assert "border-radius: 4px" in source

    visual_source = f"{source}\n{config_text}".casefold()
    assert not re.search(r"\b(?:green|lime|emerald|teal)\b", visual_source)
    assert "gradient" not in visual_source
