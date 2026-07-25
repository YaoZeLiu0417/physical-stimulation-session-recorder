import ast
import hashlib
import re
import tomllib
from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "showcase_app.py"
THEME = ROOT / ".streamlit" / "config.toml"
PASSWORD = "demonstration-passphrase"
PRODUCT_NAME = "Physical Stimulation Session Recorder"
PRODUCT_CAPTION = "物理刺激干预记录工具 · 本页面只使用合成内容"
PROGRESS_LABELS = (
    "1 安全进入",
    "2 会话记录",
    "3 引导反馈",
    "4 完成确认",
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
    assert all(word in capture_text for word in ("模拟", "摄像头", "文件", "网络"))
    _assert_progress(app, "2 会话记录")
    _element_by_key(app.button, "finish_capture").click().run()

    assert _element_by_key(app.slider, "session_clarity").value == 2
    assert _element_by_key(app.slider, "interaction_comfort").value == 2
    _assert_progress(app, "3 引导反馈")
    _element_by_key(app.slider, "session_clarity").set_value(3)
    _element_by_key(app.slider, "interaction_comfort").set_value(4)
    app.run()
    _element_by_key(app.button, "save_reflection").click().run()

    assert not app.exception
    assert [item.value for item in app.success] == ["演示流程已完成。"]
    assert "隐私边界" in _visible_text(app)
    _assert_progress(app, "4 完成确认")
    _element_by_key(app.button, "restart_demo")
    assert list(tmp_path.iterdir()) == []

    restart_app = _app_with_password()
    restart_app.session_state["showcase_authenticated"] = True
    restart_app.session_state["showcase_step"] = "confirmation"
    restart_app.run()
    _element_by_key(restart_app.button, "restart_demo").click().run()
    assert restart_app.session_state["showcase_step"] == "overview"
    _assert_progress(restart_app, "1 安全进入")
    assert list(tmp_path.iterdir()) == []


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
