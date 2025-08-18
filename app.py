# app.py
# pyright: reportMissingImports=false, reportAttributeAccessIssue=false

from __future__ import annotations

import os
import json
import time
import hmac
import hashlib
import secrets
import mimetypes
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests
import streamlit as st
from streamlit.components.v1 import html

from streamlit_webrtc import (
    webrtc_streamer,
    WebRtcMode,
    RTCConfiguration,
)
from aiortc.contrib.media import MediaRecorder

# ------------------------------
# 常量 & 路径
# ------------------------------
APP_PASSWORD_SHA256 = str(os.getenv("APP_PASSWORD_SHA256") or st.secrets.get("APP_PASSWORD_SHA256", ""))
LINK_SIGNING_KEY    = os.getenv("LINK_SIGNING_KEY") or st.secrets.get("LINK_SIGNING_KEY", "")

BASE_DIR   = Path(__file__).resolve().parent
RECORD_DIR = (BASE_DIR / "records").resolve()
RECORD_DIR.mkdir(exist_ok=True, parents=True)

# ------------------------------
# 页面设置
# ------------------------------
st.set_page_config(page_title="taVNS 干预日志", page_icon="🎥", layout="centered")


# ------------------------------
# 配置读取（优先 Secrets，回退到本地 config.toml）
# ------------------------------
def _read_toml_file(path: Path) -> Dict[str, Any]:
    # 兼容 tomllib / tomli / toml 三种包的差异
    try:
        import tomllib  # Python 3.11+
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        try:
            import tomli  # type: ignore
            with open(path, "rb") as f:
                return tomli.load(f)  # type: ignore
        except Exception:
            import toml  # type: ignore
            text = path.read_text(encoding="utf-8")
            return toml.loads(text)  # type: ignore

def load_baidu_conf() -> Dict[str, Any]:
    if "baidu" in st.secrets:
        b = st.secrets["baidu"]
        return {
            "app_key": b["app_key"],
            "secret_key": b["secret_key"],
            "refresh_token": b["refresh_token"],
            "save_dir": b.get("save_dir", "/apps/collector"),
        }

    cfg_path = Path("config.toml")
    if not cfg_path.exists():
        cfg_path = BASE_DIR / "config.toml"
    if cfg_path.exists():
        data = _read_toml_file(cfg_path)
        if "baidu" in data:
            return data["baidu"]
    st.error("缺少 config.toml 或 Secrets 中的 [baidu] 配置。")
    st.stop()

BAIDU = load_baidu_conf()
APP_AK = BAIDU["app_key"]
APP_SK = BAIDU["secret_key"]
REFRESH_TOKEN = BAIDU["refresh_token"]
SAVE_DIR = BAIDU.get("save_dir", "/apps/collector")


# ------------------------------
# 免口令签名链接 & 密码准入
# ------------------------------
def _hmac_sha256_hex(key: str, msg: str) -> str:
    return hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()

def gatekeeper():
    try:
        q = st.query_params  # Streamlit 新接口
    except Exception:
        q = st.experimental_get_query_params()

    # —— 统一取首个值，并强制成 str —— 
    sid: str = str(q.get("sid", [""])[0] if isinstance(q.get("sid"), list) else q.get("sid", ""))
    exp: str = str(q.get("exp", [""])[0] if isinstance(q.get("exp"), list) else q.get("exp", ""))
    sig: str = str(q.get("sig", [""])[0] if isinstance(q.get("sig"), list) else q.get("sig", ""))

    if sid and exp and sig and LINK_SIGNING_KEY:
        expected = _hmac_sha256_hex(LINK_SIGNING_KEY, f"{sid}:{exp}")
        # 用 bytes，且把对方签名做 strip/lower 规范化，避免大小写/空白问题
        if hmac.compare_digest(expected.encode("ascii"), sig.strip().lower().encode("ascii")):
            st.session_state["authed"] = True
            st.session_state.setdefault("default_sid", sid)
            st.session_state.setdefault("default_exp", exp)

    if st.session_state.get("authed"):
        return

    st.title("🔒 taVNS干预视频日志准入界面")
    st.warning("请输入访问密码以继续")
    pw = st.text_input("访问密码", type="password")
    if st.button("登录", type="primary"):
        got_hex = hashlib.sha256((pw or "").encode("utf-8")).hexdigest()
        # 同样用 bytes 做常量时间比较
        if APP_PASSWORD_SHA256 and hmac.compare_digest(
            got_hex.encode("ascii"), APP_PASSWORD_SHA256.strip().lower().encode("ascii")
        ):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("密码错误"); st.stop()
    else:
        st.stop()


gatekeeper()


# ------------------------------
# UI - 基本信息
# ------------------------------
st.title("📓 taVNS 干预日志")

col_a, col_b = st.columns(2)
with col_a:
    subject = st.text_input("被试编号", value=st.session_state.get("default_sid", ""))
with col_b:
    experiment = st.text_input("任务/实验标签", value=st.session_state.get("default_exp", ""))

notes = st.text_area("访谈/思路/备注", placeholder="关键片段、被试反应、异常情况等…")
delete_after_upload = st.checkbox("上传成功后删除本地文件", value=True)

# ------------------------------
# WebRTC 录制（浏览器 -> 服务器）
# ------------------------------
RTC_CFG = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})

def _make_rec_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{subject or 'anon'}_{experiment or 'task'}_{ts}.mp4"
    return (RECORD_DIR / base).resolve()

# 将“输入流（浏览器传入）”直接录到文件
def _recorder_factory():
    path = _make_rec_path()
    st.session_state["last_record_file"] = str(path)
    return MediaRecorder(str(path))  # aiortc 使用 ffmpeg 写文件

st.subheader("🎥 录制")
ctx = webrtc_streamer(
    key="recorder",
    mode=WebRtcMode.SENDONLY,
    rtc_configuration=RTC_CFG,
    media_stream_constraints={"video": True, "audio": True},
    in_recorder_factory=_recorder_factory,
)

# 小计时器（仅 UI）
html(
    """
    <div id="rec-timer" style="font: 600 14px/1.6 ui-sans-serif,system-ui; margin-top:6px"></div>
    <script>
      let stPlaying = undefined;
      function tick(){
        const root = window.parent.document;
        const btn = root.querySelector('button[kind="webrtc_start_stop"]') || root.querySelector('button[title*="Stop"]');
        const playing = btn ? /Stop/i.test(btn.textContent) : false;
        if (stPlaying !== playing){
          stPlaying = playing;
          window._recStart = playing ? Date.now() : undefined;
        }
        const d = document.getElementById("rec-timer");
        if (!d) return;
        if (window._recStart){
          const s = Math.floor((Date.now() - window._recStart)/1000);
          const mm = String(Math.floor(s/60)).padStart(2, '0');
          const ss = String(s%60).padStart(2, '0');
          d.textContent = "● 正在录制 " + mm + ":" + ss;
          d.style.color = "#c00";
        }else{
          d.textContent = "未在录制";
          d.style.color = "#666";
        }
      }
      setInterval(tick, 500);
      tick();
    </script>
    """,
    height=22,
)

st.caption("点击上方组件的 Start/Stop 控件开始/停止。停止后文件会保存在服务器的 records/ 目录。")

# ------------------------------
# 辅助：列出本地视频
# ------------------------------
def list_local_videos(folder: Path) -> List[Path]:
    exts = {".mp4", ".flv", ".webm", ".mkv"}
    return sorted([p for p in folder.glob("*") if p.suffix.lower() in exts], key=lambda p: p.stat().st_mtime, reverse=True)

# 保存一份元数据
def write_meta_for(video: Path):
    data = {
        "subject": subject,
        "experiment": experiment,
        "notes": notes,
        "filename": video.name,
        "filesize": video.stat().st_size if video.exists() else 0,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    meta_path = video.with_suffix(".json")
    meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------
# 百度网盘：OAuth & 分片上传
# ------------------------------
OAUTH_TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
PRECREATE_URL   = "https://pan.baidu.com/rest/2.0/xpan/file?method=precreate"
SUPERFILE2_URL  = "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2"
CREATE_URL      = "https://pan.baidu.com/rest/2.0/xpan/file?method=create"

def _headers() -> Dict[str, str]:
    return {"User-Agent": "exp-recorder/0.5"}

def get_access_token() -> str:
    r = requests.post(
        OAUTH_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id": APP_AK,
            "client_secret": APP_SK,
        },
        headers=_headers(),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def _md5_bytes(b: bytes) -> str:
    h = hashlib.md5()
    h.update(b)
    return h.hexdigest()

CHUNK = 4 * 1024 * 1024

def _iter_parts(p: Path) -> Iterable[bytes]:
    with open(p, "rb") as f:
        while True:
            buf = f.read(CHUNK)
            if not buf:
                break
            yield buf

def upload_to_baidu(video: Path, *, save_root: str = SAVE_DIR) -> bool:
    access_token = get_access_token()
    size = video.stat().st_size
    parts = list(_iter_parts(video))
    block_list = [_md5_bytes(b) for b in parts]

    # precreate
    pre_r = requests.post(
        PRECREATE_URL,
        params={"access_token": access_token},
        data={
            "path": f"{save_root.rstrip('/')}/{subject}/{datetime.now().strftime('%Y%m%d')}/{video.name}",
            "size": str(size),
            "isdir": "0",
            "autoinit": "1",
            "rtype": "3",
            "block_list": json.dumps(block_list),
        },
        headers=_headers(),
        timeout=60,
    )
    pre = pre_r.json()
    if pre.get("errno", 0) != 0:
        st.error(f"预创建失败：{pre}")
        return False

    uploadid = pre.get("uploadid")
    if not uploadid:
        # 秒传
        return True

    # superfile2
    for i, b in enumerate(parts):
        r = requests.post(
            SUPERFILE2_URL,
            params={
                "access_token": access_token,
                "method": "upload",
                "path": pre.get("path", video.name),
                "type": "tmpfile",
                "uploadid": uploadid,
                "partseq": str(i),
            },
            files={"file": ("blob", b)},
            headers=_headers(),
            timeout=300,
        )
        if r.status_code != 200:
            st.error(f"分片 {i+1} 上传失败：{r.text}")
            return False
        st.write(f"已上传分片 {i+1}/{len(parts)}")

    # create
    fin = requests.post(
        CREATE_URL,
        params={"access_token": access_token},
        data={
            "path": pre.get("path", video.name),
            "size": str(size),
            "isdir": "0",
            "rtype": "3",
            "uploadid": uploadid,
            "block_list": json.dumps(block_list),
        },
        headers=_headers(),
        timeout=120,
    )
    if fin.status_code != 200:
        st.error(f"合并失败：{fin.text}")
        return False
    return True


# ------------------------------
# 上传区
# ------------------------------
st.subheader("☁️ 上传到网盘（百度）")

videos = list_local_videos(RECORD_DIR)
if not videos:
    st.info("还没有录制文件。点击上面的 Start 进行录制。")
else:
    vid = st.selectbox("选择一个待上传的文件", options=videos, format_func=lambda p: f"{p.name}（{round(p.stat().st_size/1024/1024,2)} MB）")
    if st.button("开始上传", type="primary"):
        write_meta_for(vid)
        with st.spinner("上传中…"):
            ok = upload_to_baidu(vid)
        if ok:
            st.success("上传成功！")
            if delete_after_upload:
                try:
                    vid.unlink(missing_ok=True)
                    mp4_json = vid.with_suffix(".json")
                    if mp4_json.exists():
                        mp4_json.unlink()
                except Exception as e:
                    st.warning(f"清理本地文件失败：{e}")
        else:
            st.error("上传失败，请稍后重试。")

st.divider()
st.caption("如果你看到 Pylance 的 `tomli`/`ClientSettings` 报错，这是类型提示与依赖差异导致的静态分析提示。此版本已移除 ClientSettings，并兼容 tomllib/tomli/toml 三种解析方式。")
