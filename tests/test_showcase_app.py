import ast
import hashlib
import re
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import browser_recorder
import showcase_export
from browser_recorder import RecorderStatus
from showcase_audit import FORBIDDEN_TERMS
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
PROGRESS_STATES = (
    "overview",
    "capture",
    "reflection",
    "download",
    "confirmation",
)
DOWNLOAD_RETRY_RECORDING_STATES = ("saved", "skipped", "failed")
EXPECTED_SIDEBAR_INVENTORIES = {
    "access": (),
    **{
        state: (
            ("caption", "value", "SESSION PROGRESS"),
            *(
                (
                    "markdown",
                    "value",
                    f"**当前 · {label}**" if state == label_state else label,
                )
                for label, label_state in zip(
                    PROGRESS_LABELS,
                    PROGRESS_STATES,
                    strict=True,
                )
            ),
        )
        for state in PROGRESS_STATES
    },
}
AUTHENTICATED_INVENTORY_PREFIX = (
    ("title", "value", PRODUCT_NAME),
    ("caption", "value", PRODUCT_CAPTION),
    (
        "markdown",
        "value",
        '<p class="demo-kicker">CONTROLLED DEMONSTRATION</p>',
    ),
)
EXPECTED_ACCESS_INVENTORY = (
    ("title", "value", PRODUCT_NAME),
    ("caption", "value", PRODUCT_CAPTION),
    ("text_input", "label", "访问密码"),
    ("button", "label", "进入演示"),
)
EXPECTED_OVERVIEW_INVENTORY = AUTHENTICATED_INVENTORY_PREFIX + (
    ("subheader", "value", "准备开始本次演示"),
    (
        "markdown",
        "value",
        '<div class="demo-note">本受控合成演示展示安全进入、会话记录、引导反馈、本地下载和完成确认。'
        "录像仅由用户保存在本机，不会上传，也不会连接外部存储。</div>",
    ),
    ("button", "label", "开始演示"),
)
EXPECTED_CAPTURE_NO_RECORDING_INVENTORY = AUTHENTICATED_INVENTORY_PREFIX + (
    ("subheader", "value", "本机录制"),
    (
        "caption",
        "value",
        "视频和声音仅保存在本机，不会上传。请勿录入可识别身份的信息。",
    ),
    ("button", "label", "返回流程概览"),
    (
        "warning",
        "value",
        "本次未完成录像。如需继续，请明确选择无录像继续。",
    ),
    ("button", "label", "无录像继续"),
)
EXPECTED_REFLECTION_SAVED_INVENTORY = AUTHENTICATED_INVENTORY_PREFIX + (
    ("subheader", "value", "演示反馈"),
    (
        "caption",
        "value",
        "以下为通用合成反馈，不对应任何研究测量内容或评分规则。",
    ),
    ("slider", "value", 2),
    ("slider", "label", "本次演示流程有多清晰？"),
    ("slider", "value", 2),
    ("slider", "label", "摄像头交互有多顺畅？"),
    ("slider", "value", 2),
    ("slider", "label", "界面的信息量有多合适？"),
    ("slider", "value", 2),
    ("slider", "label", "你愿意继续使用这一流程吗？"),
    ("button", "label", "提交演示反馈"),
)
EXPECTED_REFLECTION_NO_RECORDING_INVENTORY = AUTHENTICATED_INVENTORY_PREFIX + (
    ("subheader", "value", "演示反馈"),
    (
        "caption",
        "value",
        "以下为通用合成反馈，不对应任何研究测量内容或评分规则。",
    ),
    ("slider", "value", 2),
    ("slider", "label", "本次演示流程有多清晰？"),
    ("caption", "value", CAMERA_FEEDBACK_SKIPPED_CAPTION),
    ("slider", "value", 2),
    ("slider", "label", "界面的信息量有多合适？"),
    ("slider", "value", 2),
    ("slider", "label", "你愿意继续使用这一流程吗？"),
    ("button", "label", "提交演示反馈"),
)
EXPECTED_DOWNLOAD_INVENTORY = AUTHENTICATED_INVENTORY_PREFIX + (
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
EXPECTED_DOWNLOAD_ERROR_INVENTORY = AUTHENTICATED_INVENTORY_PREFIX + (
    ("subheader", "value", "下载合成演示数据"),
    (
        "caption",
        "value",
        "下载文件仅包含合成演示内容，并且只会保存在本机。",
    ),
    ("warning", "value", "下载文件暂时无法生成，请重试。"),
    ("button", "label", "重试生成"),
)
EXPECTED_CONFIRMATION_INVENTORY = AUTHENTICATED_INVENTORY_PREFIX + (
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
VISIBLE_FORBIDDEN_TERMS = tuple(
    term for term in FORBIDDEN_TERMS if term != "评分规则"
) + (
    "questionnaire",
    "score",
    "answer",
    "risk",
    "threshold",
    "media",
    "blob",
    "participant id",
    "participant_id",
    "subject id",
    "subject_id",
    "path",
    "filename",
    "device label",
    "upload status",
    "upload_status",
    "recording_state",
    "showcase_recorder_status",
    "showcase_synthetic_archive",
    "showcase_export_error",
    "error_code",
    "write_failed",
    "twi" + "lio",
    "i" + "ce",
)
SOURCE_FORBIDDEN_TERMS = tuple(
    term for term in FORBIDDEN_TERMS if term != "评分规则"
) + (
    "questionnaire",
    "score",
    "risk",
    "threshold",
    "participant_id",
    "participantid",
    "subject_id",
    "recording_path",
    "file_path",
    "upload_status",
)
EXPECTED_SHOWCASE_IMPORT_BINDINGS = (
    ("from", "__future__.annotations", "annotations"),
    ("from", "browser_recorder.RecorderStatus", "RecorderStatus"),
    (
        "from",
        "browser_recorder.render_browser_recorder",
        "render_browser_recorder",
    ),
    ("from", "datetime.datetime", "datetime"),
    ("from", "datetime.timezone", "timezone"),
    (
        "from",
        "showcase_export.build_synthetic_showcase_zip",
        "build_synthetic_showcase_zip",
    ),
    ("from", "showcase_workflow.advance_step", "advance_step"),
    ("from", "showcase_workflow.password_matches", "password_matches"),
    ("import", "os", "os"),
    ("import", "streamlit", "st"),
)
EXPECTED_SHOWCASE_CALL_INVENTORY = Counter(
    {
        "ValueError": 2,
        "_build_cached_synthetic_archive": 1,
        "_clear_showcase_session_state": 2,
        "_consume_recorder_status": 1,
        "_go": 6,
        "_preserve_completed_ratings": 1,
        "_recording_export_state": 1,
        "_render_export_retry": 2,
        "_render_local_recorder": 1,
        "_render_synthetic_download": 1,
        "_require_access": 1,
        "_return_to_overview": 1,
        "_secret": 1,
        "browser_recorder.RecorderStatus": 1,
        "browser_recorder.render_browser_recorder": 1,
        "completed_ratings.items": 1,
        "datetime.datetime.now": 1,
        "datetime.datetime.now().replace": 1,
        "isinstance": 3,
        "os.getenv": 1,
        "showcase_export.build_synthetic_showcase_zip": 1,
        "showcase_workflow.advance_step": 1,
        "showcase_workflow.password_matches": 1,
        "str": 1,
        "streamlit.button": 8,
        "streamlit.caption": 5,
        "streamlit.checkbox": 1,
        "streamlit.container": 1,
        "streamlit.download_button": 1,
        "streamlit.error": 2,
        "streamlit.info": 5,
        "streamlit.markdown": 5,
        "streamlit.rerun": 3,
        "streamlit.session_state.get": 7,
        "streamlit.session_state.pop": 10,
        "streamlit.session_state.setdefault": 1,
        "streamlit.set_page_config": 1,
        "streamlit.sidebar.caption": 1,
        "streamlit.sidebar.markdown": 1,
        "streamlit.slider": 4,
        "streamlit.stop": 2,
        "streamlit.subheader": 4,
        "streamlit.text_input": 1,
        "streamlit.title": 1,
        "streamlit.warning": 2,
    }
)
ALLOWED_SHOWCASE_CALLS = set(EXPECTED_SHOWCASE_CALL_INVENTORY) | {"str.replace"}
EXPECTED_SHOWCASE_OS_ATTRIBUTE_INVENTORY = Counter({"os.getenv": 1})
EXPECTED_SHOWCASE_AST_FINGERPRINT = (
    "7d8fd98c7aba72baff8db2d2459331b38e9459de18ff953c5f009161bd5adfcd"
)
FORBIDDEN_SHOWCASE_BUILTIN_LOADS = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "input",
        "open",
        "setattr",
    }
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


def _content_inventory(root):
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

        structural_types = {"main", "sidebar", "vertical"}
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

    visit(root)
    return tuple(inventory)


def _main_content_inventory(app: AppTest):
    return _content_inventory(app.main)


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
    if status.state in {"skipped", "failed"}:
        _element_by_key(app.button, "continue_without_recording").click().run()
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


def _fresh_inventory_app(
    monkeypatch,
    *,
    step: str,
    recording_state: str | None,
) -> AppTest:
    app = _app_with_password()
    if step == "access":
        return app.run()

    app.session_state["showcase_authenticated"] = True
    app.session_state["showcase_step"] = step
    if recording_state is None:
        return app.run()

    saved = recording_state == "saved"
    status = RecorderStatus(
        state=recording_state,
        duration_seconds=3 if saved else 0,
        camera_ready=saved,
        microphone_ready=saved,
        saved_confirmed=saved,
        error_code="write_failed" if recording_state == "failed" else None,
    )
    app.session_state["showcase_recorder_status"] = status
    if step == "capture":
        _recorder_spy(monkeypatch, status)
    if saved:
        app.session_state["showcase_camera_started"] = True
    if step in {"download", "confirmation"}:
        app.session_state[SHOWCASE_ARCHIVE_KEY] = SyntheticShowcaseArchive(
            filename="synthetic-session-private-detail.zip",
            data=b"inventory-synthetic-zip",
        )
        for key, value in SYNTHETIC_RESPONSES.items():
            if key != "camera_smoothness" or saved:
                app.session_state[key] = value
    return app.run()


def _assert_showcase_only_inventory(
    app: AppTest,
    *,
    step: str,
    expected_inventory: tuple[tuple[str, str, object], ...],
) -> None:
    visible_text = _visible_text(app)
    folded_text = visible_text.casefold()
    for term in VISIBLE_FORBIDDEN_TERMS:
        assert term.casefold() not in folded_text, term
    assert _main_content_inventory(app) == expected_inventory
    assert _content_inventory(app.sidebar) == EXPECTED_SIDEBAR_INVENTORIES[step]


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
    assert not third_components
    assert app.session_state["showcase_step"] == "reflection"
    assert app.session_state["showcase_camera_started"] is True
    assert tuple(slider.key for slider in app.slider) == tuple(
        SYNTHETIC_RESPONSES
    )
    assert not [button for button in app.button if button.key == "finish_capture"]


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
    ("raw_status", "expected_status", "auto_advance"),
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
    monkeypatch, raw_status, expected_status, auto_advance
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
    assert app.session_state["showcase_step"] == (
        "reflection" if auto_advance else "capture"
    )

    app.run()

    assert not app.exception
    assert app.session_state["showcase_recorder_status"] == expected_status
    assert "showcase_session_recorder" not in app.session_state
    assert not [button for button in app.button if button.key == "finish_capture"]
    expected_component_call = {
        "key": "showcase_session_recorder",
        "initial_mode": "demo",
        "default": None,
    }
    assert component_calls == [expected_component_call] * (1 if auto_advance else 2)
    if auto_advance:
        assert app.session_state["showcase_camera_started"] is True
        assert tuple(slider.key for slider in app.slider) == tuple(
            SYNTHETIC_RESPONSES
        )


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

    assert app.session_state["showcase_step"] == "reflection"
    assert app.session_state["showcase_camera_started"] is True
    assert not [button for button in app.button if button.key == "finish_capture"]
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


def test_download_retry_matrix_covers_all_terminal_recording_states() -> None:
    assert set(DOWNLOAD_RETRY_RECORDING_STATES) == {
        "saved",
        "skipped",
        "failed",
    }


@pytest.mark.parametrize(
    "recording_state",
    DOWNLOAD_RETRY_RECORDING_STATES,
)
def test_download_failure_is_neutral_retryable_and_preserves_all_state(
    monkeypatch,
    recording_state,
):
    saved = recording_state == "saved"
    status = RecorderStatus(
        state=recording_state,
        duration_seconds=3 if saved else 0,
        camera_ready=saved,
        microphone_ready=saved,
        saved_confirmed=saved,
        error_code="write_failed" if recording_state == "failed" else None,
    )
    responses = {
        key: value
        for key, value in SYNTHETIC_RESPONSES.items()
        if saved or key != "camera_smoothness"
    }
    expected_camera_rating = (
        SYNTHETIC_RESPONSES["camera_smoothness"] if saved else None
    )
    expected_non_camera_responses = {
        key: SYNTHETIC_RESPONSES[key] for key in NON_CAMERA_RESPONSE_KEYS
    }
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
        responses=responses,
    )

    assert len(attempts) == 1
    assert attempts[0]["recording_state"] == recording_state
    assert attempts[0]["camera_smoothness"] == expected_camera_rating
    if saved:
        assert type(attempts[0]["camera_smoothness"]) is int
    else:
        assert attempts[0]["camera_smoothness"] is None
    assert {
        key: attempts[0][key] for key in NON_CAMERA_RESPONSE_KEYS
    } == expected_non_camera_responses
    visible = _visible_text(app)
    assert "下载文件暂时无法生成，请重试。" in visible
    assert "PRIVATE-EXPORT-TRACE" not in visible
    assert "/secret/path.zip" not in visible
    assert app.session_state[SHOWCASE_EXPORT_ERROR_KEY] is True
    assert type(app.session_state[SHOWCASE_EXPORT_ERROR_KEY]) is bool
    assert SHOWCASE_ARCHIVE_KEY not in app.session_state
    assert not app.get("download_button")
    assert not [button for button in app.button if button.key == "finish_download"]
    assert {key: app.session_state[key] for key in responses} == responses
    assert ("camera_smoothness" in app.session_state) is saved
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
    assert {key: app.session_state[key] for key in responses} == responses
    assert ("camera_smoothness" in app.session_state) is saved
    assert app.session_state["showcase_recorder_status"] == status
    _assert_showcase_only_inventory(
        app,
        step="download",
        expected_inventory=EXPECTED_DOWNLOAD_ERROR_INVENTORY,
    )
    _element_by_key(app.button, SHOWCASE_RETRY_BUTTON_KEY).click().run()

    assert not app.exception
    assert len(attempts) == 2
    for attempt in attempts:
        assert attempt["recording_state"] == recording_state
        assert attempt["camera_smoothness"] == expected_camera_rating
        assert {
            key: attempt[key] for key in NON_CAMERA_RESPONSE_KEYS
        } == expected_non_camera_responses
    assert app.session_state[SHOWCASE_ARCHIVE_KEY] is archive
    assert SHOWCASE_EXPORT_ERROR_KEY not in app.session_state
    assert {key: app.session_state[key] for key in responses} == responses
    assert ("camera_smoothness" in app.session_state) is saved
    assert app.session_state["showcase_recorder_status"] == status
    assert len(app.get("download_button")) == 1
    assert app.session_state["showcase_step"] == "download"
    assert _element_by_key(app.button, "finish_download").disabled is True
    _assert_showcase_only_inventory(
        app,
        step="download",
        expected_inventory=EXPECTED_DOWNLOAD_INVENTORY,
    )
    visible = _visible_text(app)
    for hidden in (
        "PRIVATE-EXPORT-TRACE",
        "/secret/path.zip",
        "write_failed",
        "recording_state",
        SHOWCASE_ARCHIVE_KEY,
        SHOWCASE_EXPORT_ERROR_KEY,
        archive.filename,
    ):
        assert hidden.casefold() not in visible.casefold()


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


@pytest.mark.parametrize(
    ("step", "recording_state", "expected_inventory"),
    (
        ("access", None, EXPECTED_ACCESS_INVENTORY),
        ("overview", None, EXPECTED_OVERVIEW_INVENTORY),
        ("capture", "skipped", EXPECTED_CAPTURE_NO_RECORDING_INVENTORY),
        ("capture", "failed", EXPECTED_CAPTURE_NO_RECORDING_INVENTORY),
        ("reflection", "saved", EXPECTED_REFLECTION_SAVED_INVENTORY),
        (
            "reflection",
            "skipped",
            EXPECTED_REFLECTION_NO_RECORDING_INVENTORY,
        ),
        (
            "reflection",
            "failed",
            EXPECTED_REFLECTION_NO_RECORDING_INVENTORY,
        ),
        ("download", "saved", EXPECTED_DOWNLOAD_INVENTORY),
        ("download", "skipped", EXPECTED_DOWNLOAD_INVENTORY),
        ("download", "failed", EXPECTED_DOWNLOAD_INVENTORY),
        ("confirmation", "saved", EXPECTED_CONFIRMATION_INVENTORY),
        ("confirmation", "skipped", EXPECTED_CONFIRMATION_INVENTORY),
        ("confirmation", "failed", EXPECTED_CONFIRMATION_INVENTORY),
    ),
    ids=(
        "access",
        "overview",
        "capture-skipped",
        "capture-failed",
        "reflection-saved",
        "reflection-skipped",
        "reflection-failed",
        "download-saved",
        "download-skipped",
        "download-failed",
        "confirmation-saved",
        "confirmation-skipped",
        "confirmation-failed",
    ),
)
def test_visible_copy_and_main_inventory_are_exact_for_every_terminal_branch(
    monkeypatch,
    step,
    recording_state,
    expected_inventory,
):
    app = _fresh_inventory_app(
        monkeypatch,
        step=step,
        recording_state=recording_state,
    )

    assert not app.exception
    _assert_showcase_only_inventory(
        app,
        step=step,
        expected_inventory=expected_inventory,
    )


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

    assert app.session_state["showcase_step"] == "reflection"
    assert app.session_state["showcase_camera_started"] is True
    assert not [button for button in app.button if button.key == "finish_capture"]
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


def test_inventory_gate_rejects_canonical_forbidden_copy_drift(tmp_path):
    source = APP.read_text(encoding="utf-8")
    access_anchor = "st.caption(PRODUCT_CAPTION)\n_require_access()\n"
    mutated_source = source.replace(
        access_anchor,
        'st.caption(PRODUCT_CAPTION)\nst.caption("NSSI private label")\n'
        "_require_access()\n",
        1,
    )
    assert mutated_source != source
    mutated_path = tmp_path / "mutated_showcase_access.py"
    mutated_path.write_text(mutated_source, encoding="utf-8")
    mutated_app = _app_with_password(mutated_path).run()

    assert not mutated_app.exception
    with pytest.raises(AssertionError, match="nssi"):
        _assert_showcase_only_inventory(
            mutated_app,
            step="access",
            expected_inventory=EXPECTED_ACCESS_INVENTORY,
        )


def test_sidebar_inventory_rejects_unknown_visible_node_type(tmp_path):
    source = APP.read_text(encoding="utf-8")
    progress_anchor = 'st.sidebar.caption("SESSION PROGRESS")\n'
    mutated_source = source.replace(
        progress_anchor,
        progress_anchor + 'st.sidebar.error("额外合成演示信息")\n',
        1,
    )
    assert mutated_source != source
    mutated_path = tmp_path / "mutated_showcase_sidebar.py"
    mutated_path.write_text(mutated_source, encoding="utf-8")
    mutated_app = _app_with_password(mutated_path)
    mutated_app.session_state["showcase_authenticated"] = True
    mutated_app.session_state["showcase_step"] = "overview"
    mutated_app.run()

    assert not mutated_app.exception
    with pytest.raises(AssertionError):
        _assert_showcase_only_inventory(
            mutated_app,
            step="overview",
            expected_inventory=EXPECTED_OVERVIEW_INVENTORY,
        )


def test_download_error_inventory_rejects_extra_neutral_copy(tmp_path):
    source = APP.read_text(encoding="utf-8")
    retry_anchor = '    st.warning("下载文件暂时无法生成，请重试。")\n'
    mutated_source = source.replace(
        retry_anchor,
        retry_anchor + '    st.info("额外合成演示信息")\n',
        1,
    )
    assert mutated_source != source
    mutated_path = tmp_path / "mutated_showcase_download_error.py"
    mutated_path.write_text(mutated_source, encoding="utf-8")
    mutated_app = _app_with_password(mutated_path)
    mutated_app.session_state["showcase_authenticated"] = True
    mutated_app.session_state["showcase_step"] = "download"
    mutated_app.session_state["showcase_recorder_status"] = RecorderStatus(
        state="saved",
        saved_confirmed=True,
    )
    mutated_app.session_state[SHOWCASE_EXPORT_ERROR_KEY] = True
    for key, value in SYNTHETIC_RESPONSES.items():
        mutated_app.session_state[key] = value
    mutated_app.run()

    assert not mutated_app.exception
    with pytest.raises(AssertionError):
        _assert_showcase_only_inventory(
            mutated_app,
            step="download",
            expected_inventory=EXPECTED_DOWNLOAD_ERROR_INVENTORY,
        )


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


def _showcase_ast_inventory(
    source: str,
) -> tuple[
    tuple[tuple[str, str, str], ...],
    Counter[str],
    Counter[str],
    Counter[str],
    str,
]:
    tree = ast.parse(source)
    import_inventory: list[tuple[str, str, str]] = []
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                qualified_name = (
                    alias.name if alias.asname else alias.name.split(".", 1)[0]
                )
                import_inventory.append(("import", alias.name, local_name))
                assert bindings.get(local_name, qualified_name) == qualified_name
                bindings[local_name] = qualified_name
        elif isinstance(node, ast.ImportFrom):
            module_name = "." * node.level + (node.module or "")
            assert module_name != "os"
            for alias in node.names:
                assert alias.name != "*"
                qualified_name = (
                    f"{module_name}.{alias.name}" if module_name else alias.name
                )
                local_name = alias.asname or alias.name
                import_inventory.append(("from", qualified_name, local_name))
                assert bindings.get(local_name, qualified_name) == qualified_name
                bindings[local_name] = qualified_name

    parents = {
        child: node
        for node in ast.walk(tree)
        for child in ast.iter_child_nodes(node)
    }
    os_binding_names = {
        local_name
        for local_name, qualified_name in bindings.items()
        if qualified_name == "os"
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in os_binding_names:
            parent = parents[node]
            assert isinstance(parent, ast.Attribute)
            assert parent.value is node
            assert parent.attr == "getenv"

    def qualified_expression(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return bindings.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return f"{qualified_expression(node.value)}.{node.attr}"
        if isinstance(node, ast.Call):
            return f"{qualified_expression(node.func)}()"
        if isinstance(node, ast.Constant):
            return type(node.value).__name__
        if isinstance(node, ast.Subscript):
            return f"{qualified_expression(node.value)}[]"
        return f"<{type(node).__name__}>"

    call_inventory = Counter(
        qualified_expression(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    )
    os_attribute_inventory: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            qualified_name = qualified_expression(node)
            if qualified_name.startswith("os."):
                os_attribute_inventory[qualified_name] += 1
    dangerous_builtin_load_inventory = Counter(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in FORBIDDEN_SHOWCASE_BUILTIN_LOADS
    )
    ast_fingerprint = hashlib.sha256(
        ast.dump(
            tree,
            annotate_fields=True,
            include_attributes=False,
        ).encode("utf-8")
    ).hexdigest()
    return (
        tuple(sorted(import_inventory)),
        call_inventory,
        os_attribute_inventory,
        dangerous_builtin_load_inventory,
        ast_fingerprint,
    )


def _assert_showcase_ast_boundary(source: str) -> Counter[str]:
    (
        import_inventory,
        call_inventory,
        os_attribute_inventory,
        dangerous_builtin_load_inventory,
        ast_fingerprint,
    ) = _showcase_ast_inventory(source)
    assert import_inventory == EXPECTED_SHOWCASE_IMPORT_BINDINGS
    assert set(call_inventory) <= ALLOWED_SHOWCASE_CALLS
    assert call_inventory in (
        EXPECTED_SHOWCASE_CALL_INVENTORY,
        EXPECTED_SHOWCASE_CALL_INVENTORY + Counter({"str.replace": 1}),
    )
    assert (
        os_attribute_inventory == EXPECTED_SHOWCASE_OS_ATTRIBUTE_INVENTORY
    )
    assert not dangerous_builtin_load_inventory
    assert ast_fingerprint == EXPECTED_SHOWCASE_AST_FINGERPRINT
    return call_inventory


@pytest.mark.parametrize(
    "mutation",
    (
        'os.replace("source", "target")',
        'from os import replace\nreplace("source", "target")',
        'import os as filesystem\nfilesystem.replace("source", "target")',
        'from os import replace as move_file\nmove_file("source", "target")',
    ),
    ids=("qualified", "from-import", "module-alias", "function-alias"),
)
def test_showcase_ast_boundary_rejects_os_replace_and_aliases(mutation):
    source = APP.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_showcase_ast_boundary(f"{source}\n{mutation}\n")


def test_showcase_ast_boundary_rejects_os_attribute_assignment_alias():
    source = APP.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_showcase_ast_boundary(
            f'{source}\nstr = os.replace\nstr("source", "target")\n'
        )


def test_showcase_ast_boundary_rejects_os_attribute_callback_alias():
    source = APP.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_showcase_ast_boundary(
            f'{source}\nmove_file = os.replace\n'
            'if False:\n    st.button("unused", on_click=move_file)\n'
        )


def test_showcase_ast_boundary_rejects_rebound_os_module_assignment_alias():
    source = APP.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_showcase_ast_boundary(
            f'{source}\nfilesystem = os\nstr = filesystem.replace\n'
            'str("source", "target")\n'
        )


def test_showcase_ast_boundary_rejects_rebound_os_module_callback_alias():
    source = APP.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_showcase_ast_boundary(
            f'{source}\nfilesystem = os\nmove_file = filesystem.replace\n'
            'if False:\n    st.button("unused", on_click=move_file)\n'
        )


def test_showcase_ast_boundary_rejects_getattr_os_reflection():
    source = APP.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_showcase_ast_boundary(
            f'{source}\nstr = getattr\nstr(os, "replace")\n'
        )


def test_showcase_ast_boundary_rejects_retry_button_builtin_callback():
    source = APP.read_text(encoding="utf-8")
    mutated_source = source.replace(
        "        on_click=_retry_synthetic_export,\n",
        "        on_click=open,\n        args=(__file__,),\n",
        1,
    )
    normalized_source = ast.dump(
        ast.parse(source),
        annotate_fields=True,
        include_attributes=False,
    ).encode("utf-8")
    normalized_mutation = ast.dump(
        ast.parse(mutated_source),
        annotate_fields=True,
        include_attributes=False,
    ).encode("utf-8")

    assert mutated_source != source
    assert hashlib.sha256(normalized_mutation).hexdigest() != hashlib.sha256(
        normalized_source
    ).hexdigest()
    with pytest.raises(AssertionError):
        _assert_showcase_ast_boundary(mutated_source)


def test_showcase_ast_boundary_rejects_duplicate_os_getenv_reference():
    source = APP.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_showcase_ast_boundary(
            f'{source}\nos.getenv("SHOWCASE_SECOND_SECRET")\n'
        )


def test_showcase_ast_inventory_treats_string_replace_as_non_capability():
    source = APP.read_text(encoding="utf-8")
    mutated_source = f'{source}\n"synthetic".replace("syn", "Syn")\n'
    (
        _,
        call_inventory,
        os_attribute_inventory,
        dangerous_builtin_load_inventory,
        ast_fingerprint,
    ) = _showcase_ast_inventory(mutated_source)

    assert call_inventory == EXPECTED_SHOWCASE_CALL_INVENTORY + Counter(
        {"str.replace": 1}
    )
    assert os_attribute_inventory == EXPECTED_SHOWCASE_OS_ATTRIBUTE_INVENTORY
    assert not dangerous_builtin_load_inventory
    assert ast_fingerprint != EXPECTED_SHOWCASE_AST_FINGERPRINT
    with pytest.raises(AssertionError):
        _assert_showcase_ast_boundary(mutated_source)


def test_showcase_ast_boundary_allows_comment_and_whitespace_changes() -> None:
    source = APP.read_text(encoding="utf-8")

    _assert_showcase_ast_boundary(f"# AST audit note\n\n{source}\n")


def test_showcase_source_has_no_private_or_io_capabilities():
    source = APP.read_text(encoding="utf-8")
    folded_source = source.casefold()
    for term in SOURCE_FORBIDDEN_TERMS:
        assert term.casefold() not in folded_source, term
    assert _assert_showcase_ast_boundary(source) == (
        EXPECTED_SHOWCASE_CALL_INVENTORY
    )
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
