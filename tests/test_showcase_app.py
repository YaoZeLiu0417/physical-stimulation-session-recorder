import ast
import hashlib
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import showcase_media


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
    "4 完成确认",
)


@pytest.fixture(autouse=True)
def _stub_live_camera(monkeypatch):
    monkeypatch.setattr(
        showcase_media,
        "render_live_camera",
        lambda: SimpleNamespace(state=SimpleNamespace(playing=True)),
    )


def _app_with_password() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=10)
    app.secrets["SHOWCASE_PASSWORD_SHA256"] = hashlib.sha256(
        PASSWORD.encode("utf-8")
    ).hexdigest()
    return app


def _element_by_key(elements, key):
    matches = [element for element in elements if element.key == key]
    assert len(matches) == 1
    return matches[0]


def _visible_text(app: AppTest) -> str:
    values = [str(app.main), str(app.sidebar)]
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
        "slider",
        "text_input",
    ):
        for element in getattr(app, collection_name):
            attributes = (
                ("label", "help", "placeholder")
                if collection_name in {"button", "slider", "text_input"}
                else ("value", "label", "help", "placeholder")
            )
            for attribute in attributes:
                value = getattr(element, attribute, None)
                if value is not None:
                    values.append(str(value))
    return "\n".join(values)


def _main_content_inventory(app: AppTest):
    inventory = []
    for collection_name in (
        "title",
        "header",
        "subheader",
        "caption",
        "markdown",
        "text",
        "info",
        "warning",
        "error",
        "success",
        "metric",
        "json",
        "code",
        "button",
        "slider",
        "number_input",
        "text_input",
        "text_area",
        "radio",
        "selectbox",
        "multiselect",
        "dataframe",
        "table",
    ):
        attributes = ("label",) if collection_name == "button" else (
            "value",
            "label",
        )
        for element in getattr(app.main, collection_name):
            for attribute in attributes:
                value = getattr(element, attribute, None)
                if value is None:
                    continue
                if (
                    collection_name == "markdown"
                    and attribute == "value"
                    and str(value).strip().startswith("<style>")
                ):
                    continue
                inventory.append((collection_name, attribute, value))
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


def test_showcase_completes_and_restarts_session_only_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = _authenticate(_app_with_password())

    overview_text = _visible_text(app)
    assert "准备开始本次演示" in overview_text
    assert "不会保存文件" in overview_text
    assert "不会连接外部存储" in overview_text
    _assert_progress(app, "1 安全进入")
    _element_by_key(app.button, "begin_demo").click().run()

    capture_text = _visible_text(app)
    assert "实时摄像预览" in capture_text
    assert "摄像头" in capture_text
    assert "不写入文件" in capture_text
    assert "项目存储" in capture_text
    assert app.session_state["showcase_camera_started"] is True
    _assert_progress(app, "2 会话记录")
    _element_by_key(app.button, "finish_capture").click().run()

    for key in SYNTHETIC_RESPONSES:
        slider = _element_by_key(app.slider, key)
        assert slider.value == 2
        assert slider.proto.min == 0
        assert slider.proto.max == 4
    assert tuple(element.label for element in app.slider) == SYNTHETIC_LABELS
    _assert_progress(app, "3 引导反馈")

    for key, value in SYNTHETIC_RESPONSES.items():
        _element_by_key(app.slider, key).set_value(value)
    app.run()
    _element_by_key(app.button, "save_reflection").click().run()

    assert not app.exception
    assert not app.success
    completion_panels = [
        item.value
        for item in app.markdown
        if 'class="completion-status"' in item.value
    ]
    assert completion_panels == [
        '<div class="completion-status" role="status">演示流程已完成。</div>'
    ]
    assert "隐私边界" in _visible_text(app)
    _assert_progress(app, "4 完成确认")
    assert list(tmp_path.iterdir()) == []

    # AppTest 1.37.1 and 1.45.1 retain stale pre-rerun slider deltas, so this
    # fresh populated session verifies current confirmation rendering and cleanup.
    confirmation_app = _app_with_password()
    confirmation_app.session_state["showcase_authenticated"] = True
    confirmation_app.session_state["showcase_step"] = "confirmation"
    confirmation_app.session_state["showcase_camera_started"] = True
    for key, value in SYNTHETIC_RESPONSES.items():
        confirmation_app.session_state[key] = value
    confirmation_app.run()

    assert _main_content_inventory(confirmation_app) == (
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

    _element_by_key(confirmation_app.button, "restart_demo").click().run()
    assert confirmation_app.session_state["showcase_step"] == "overview"
    for key in (*SYNTHETIC_RESPONSES, "showcase_camera_started"):
        assert key not in confirmation_app.session_state


def test_camera_initialization_failure_keeps_the_flow_available(
    monkeypatch, caplog
):
    def unavailable_camera():
        raise RuntimeError("synthetic camera failure")

    monkeypatch.setattr(showcase_media, "render_live_camera", unavailable_camera)
    app = _authenticate(_app_with_password())
    _element_by_key(app.button, "begin_demo").click().run()

    camera_logs = [
        record
        for record in caplog.records
        if record.getMessage() == "showcase camera preview unavailable"
    ]
    assert camera_logs
    assert all(record.exc_info is None for record in camera_logs)
    assert "synthetic camera failure" not in caplog.text
    assert str(APP.resolve()) not in caplog.text
    assert "等待摄像头连接。也可直接继续体验后续流程。" not in [
        item.value for item in app.info
    ]
    assert not app.exception
    assert [item.value for item in app.warning] == [
        "摄像头暂时不可用，可继续体验后续流程。"
    ]
    _element_by_key(app.button, "finish_capture").click().run()
    assert app.session_state["showcase_step"] == "reflection"


def test_visible_copy_is_neutral_on_every_authenticated_step():
    app = _authenticate(_app_with_password())
    visible_by_step = [_visible_text(app)]

    _element_by_key(app.button, "begin_demo").click().run()
    visible_by_step.append(_visible_text(app))
    _element_by_key(app.button, "finish_capture").click().run()
    visible_by_step.append(_visible_text(app))
    _element_by_key(app.button, "save_reflection").click().run()
    visible_by_step.append(_visible_text(app))

    for visible_text in visible_by_step:
        assert PRODUCT_NAME in visible_text
        assert PRODUCT_CAPTION in visible_text
        assert "tavns" not in visible_text.casefold()
        assert "nssi" not in visible_text.casefold()


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
