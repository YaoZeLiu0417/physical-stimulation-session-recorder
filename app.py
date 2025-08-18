# app.py
# pyright: reportMissingImports=false
"""
实验干预录制 & 上传（NLP 采集 / 链接锁定 / 重试 / 免口令）
- 被试用带签名链接 ?sid=...&exp=...&sig=... 直接进入（免口令，自动锁定被试编号）
- 管理员仍可用 APP_PASSWORD_SHA256 口令进入
- 录制：浏览器→服务器落盘(FLV)→(如有 ffmpeg 自动转 MP4)
- 上传：百度网盘 precreate/superfile2/create 分片 + 指数退避重试
- 上传成功后默认删除服务器本地副本（视频+JSON，可关闭）
"""

from __future__ import annotations

import os
import json
import time
import base64
import hmac
import hashlib
import random
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List

import requests
# Robust TOML reader: stdlib first, then optional fallbacks
try:
    import tomllib as toml  # Python 3.11+
except Exception:  # pragma: no cover
    try:
        import tomli as toml  # if pinned in local dev
    except Exception:
        toml = None  # will guard reads below
import streamlit as st
from streamlit.components.v1 import html
from streamlit_webrtc import webrtc_streamer, WebRtcMode, RTCConfiguration
from aiortc.contrib.media import MediaRecorder

# =========================
# 基础：页面设置 & 工具函数
# =========================
st.set_page_config(
    page_title="欢迎来到清华大学YMH-Lab",
    page_icon="🎥",
    layout="centered",
)

def load_baidu_conf():
    # 1) 优先从 Streamlit Secrets 读取（云端推荐）
    if "baidu" in st.secrets:
        b = st.secrets["baidu"]
        # 统一成普通 dict
        return {
            "app_key": b["app_key"],
            "secret_key": b["secret_key"],
            "refresh_token": b["refresh_token"],
            "save_dir": b.get("save_dir", "/apps/collector"),
        }

    # 2) 回退到本地 config.toml（便于本地调试）
    cfg_path_candidates = [
        Path("config.toml"),
        Path(__file__).resolve().parent / "config.toml",
    ]
    for p in cfg_path_candidates:
        if p.exists():
            if toml is None:
                st.error("读取 config.toml 需要 TOML 解析器。建议使用 Python 3.11+（内置 tomllib），或在本地安装 tomli。")
                st.stop()
            with open(p, "rb") as f:
                data = toml.load(f)
            return data.get("baidu", {})

    # 3) 两者都没有 -> 给出友好提示并中止
    st.error("缺少配置：请在 Secrets 中添加 [baidu] 或在项目根目录提供 config.toml。")
    st.stop()

def _safe_secret(key: str, default: str = "") -> str:
    """优先从 st.secrets 读取；无 secrets.toml 时回退到环境变量。"""
    try:
        return st.secrets[key]  # 本地无 secrets.toml 时可能抛异常
    except Exception:
        return os.getenv(key, default)

ROOT = Path(__file__).resolve().parent
REC_DIR = ROOT / "recordings"
REC_DIR.mkdir(parents=True, exist_ok=True)
CONF_PATH = ROOT / "config.toml"

# ---- 读取配置：优先 Secrets，其次本地 config.toml（仅本地调试用） ----
CFG: Dict[str, Any] = {}
try:
    if "baidu" in st.secrets:  # type: ignore[operator]
        CFG = dict(st.secrets["baidu"])  # type: ignore[index]
except Exception:
    pass
if not CFG and CONF_PATH.exists():
    if toml is None:
        st.error("读取 config.toml 需要 TOML 解析器。请在 Python>=3.11 环境下运行（内置 tomllib），或在本地安装 tomli。"); st.stop()
    with open(CONF_PATH, 'rb') as f:
        CFG = toml.load(f).get('baidu', {}) or {}

AK = CFG.get("app_key", "")
SK = CFG.get("secret_key", "")
REDIR = CFG.get("redirect_uri", "http://localhost:8501/oauth/callback")
SAVE_DIR = CFG.get("save_dir", "/apps/collector")

if not AK or not SK:
    st.error("未找到百度网盘 AK/SK。请在 Cloud 的 Secrets 填写 [baidu] 配置，或在本地提供 config.toml（不提交仓库）。")
    st.stop()

# =========================
# 被试专属链接：签名校验（用于免口令与锁定 subject_id）
# =========================
LINK_SIGNING_KEY = _safe_secret("LINK_SIGNING_KEY", "")  # 在 Secrets/环境变量配置

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def _sign_sid(sid: str, exp_ts: int) -> str:
    mac = hmac.new(LINK_SIGNING_KEY.encode(), f"{sid}|{exp_ts}".encode(), hashlib.sha256).digest()
    return _b64url(mac)

def _get_query_params() -> Dict[str, str]:
    try:
        return dict(st.query_params)  # streamlit>=1.36
    except Exception:
        qp = st.experimental_get_query_params()
        return {k: (v[0] if isinstance(v, list) and v else "") for k, v in qp.items()}

def _verify_sig(sid: str, exp: str, sig: str) -> bool:
    if not (sid and exp and sig and LINK_SIGNING_KEY):
        return False
    try:
        exp_ts = int(exp)
    except Exception:
        return False
    if exp_ts < int(time.time()):
        return False
    return hmac.compare_digest(sig, _sign_sid(sid, exp_ts))

# =========================
# 口令准入（管理员/调试）
# =========================
def check_password():
    # ① URL 已带签名 -> 直接放行并锁定 subject_id
    qp = _get_query_params()
    sid = qp.get("sid", "")
    exp = qp.get("exp", "")
    sig = qp.get("sig", "")
    if _verify_sig(sid, exp, sig):
        st.session_state["authed"] = True
        st.session_state["subject_id"] = sid
        return

    # ② 否则需要口令（管理员/调试）
    expected_hash = _safe_secret("APP_PASSWORD_SHA256", "")
    if not expected_hash:
        return  # 未配置口令则放行（仅内部/本地）
    if st.session_state.get("authed", False):
        return

    st.title("🔒 taVNS干预视频日志准入界面")
    st.warning("请输入访问密码以继续")
    pw = st.text_input("访问密码", type="password")
    if st.button("登录", type="primary"):
        got = hashlib.sha256((pw or "").encode("utf-8")).hexdigest()
        if hmac.compare_digest(got, expected_hash):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("密码错误"); st.stop()

# =========================
# 百度网盘 Token & 上传
# =========================
def baidu_token_by_refresh(refresh_token: str) -> Dict[str, Any]:
    url = "https://openapi.baidu.com/oauth/2.0/token"
    r = requests.post(
        url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": AK,
            "client_secret": SK,
            "redirect_uri": REDIR,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()

def _md5_file(path: Path) -> str:
    md5 = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(2 * 1024 * 1024), b""):
            md5.update(chunk)
    return md5.hexdigest()

def _split_parts(path: Path, part_size: int = 4 * 1024 * 1024) -> List[Path]:
    parts = []
    with path.open("rb") as f:
        idx = 0
        while True:
            buf = f.read(part_size)
            if not buf:
                break
            p = path.with_suffix(f".part{idx:04d}")
            with p.open("wb") as w:
                w.write(buf)
            parts.append(p)
            idx += 1
    return parts

def _retry(fn: Callable[[], Any], max_retries=5, base_delay=0.8) -> Any:
    last = None
    for i in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(base_delay * (2 ** i) + random.random() * 0.3)
    if last:
        raise last

class PCSClient:
    def __init__(self, access_token: str):
        self.token = access_token

    def _api(self, path: str, params: Dict[str, Any], files=None, method="POST", timeout=30):
        url = f"https://pan.baidu.com/rest/2.0/xpan/{path}"
        params = dict(params)
        params["access_token"] = self.token
        req = requests.post if method.upper() == "POST" else requests.get
        r = req(url, data=params if files is None else None, params=params if files is not None else None,
                files=files, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def rapidupload_or_precreate(self, remote_path: str, size: int, part_md5s: List[str], progress_cb: Optional[Callable[[float, str], None]] = None):
        # 先试试“秒传”
        pre = _retry(lambda: self._api(
            "file?method=rapidupload",
            {
                "path": remote_path, "size": size,
                "isdir": 0, "autoinit": 1, "rtype": 3,
                "block_list": json.dumps(part_md5s),
            },
            timeout=60,
        ), max_retries=4)
        if pre.get("return_type") == 2:
            if progress_cb: progress_cb(1.0, "秒传完成")
            return {"ok": True, "fast": True}

        # 否则走 precreate
        pre = _retry(lambda: self._api(
            "file?method=precreate",
            {
                "path": remote_path, "size": size,
                "isdir": 0, "rtype": 3, "autoinit": 1,
                "block_list": json.dumps(part_md5s),
            },
            timeout=60,
        ), max_retries=4)
        return {"ok": True, "fast": False, "uploadid": pre["uploadid"]}

    def upload_part(self, remote_path: str, uploadid: str, partseq: int, data: bytes):
        url = "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2"
        params = {"method": "upload", "type": "tmpfile", "path": remote_path,
                  "uploadid": uploadid, "partseq": partseq, "access_token": self.token}
        r = _retry(lambda: requests.post(url, params=params, files={"file": data}, timeout=60), max_retries=4)
        r.raise_for_status()
        return r.json()

    def create(self, remote_path: str, size: int, part_md5s: List[str], uploadid: str, progress_cb: Optional[Callable[[float, str], None]] = None):
        res = _retry(lambda: self._api(
            "file?method=create",
            {
                "path": remote_path, "size": size,
                "isdir": 0, "rtype": 3, "uploadid": uploadid,
                "block_list": json.dumps(part_md5s),
            },
            timeout=60,
        ), max_retries=4)
        if progress_cb: progress_cb(1.0, "合并完成")
        return res

# =========================
# 录制 & 元数据
# =========================
RTC_CONF = RTCConfiguration(
    {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
)

def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True
    except Exception:
        return False

def _to_mp4_if_possible(flv_path: Path) -> Path:
    if not _ffmpeg_available():
        return flv_path
    mp4 = flv_path.with_suffix(".mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(flv_path),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(mp4),
    ]
    subprocess.run(cmd, check=False)
    if mp4.exists() and mp4.stat().st_size > 0:
        try:
            flv_path.unlink(missing_ok=True)
        except Exception:
            pass
        return mp4
    return flv_path

def _today_folder_for(subject: str) -> Path:
    d = datetime.now().strftime("%Y%m%d")
    p = REC_DIR / subject / d
    p.mkdir(parents=True, exist_ok=True)
    return p

# =========================
# 主界面：表单 + 录制
# =========================
check_password()
st.title("🎥 taVNS 干预视频日志")

subject = st.text_input("来访者编号", value=st.session_state.get("subject_id", ""))
if not subject:
    st.info("请填写来访者编号以继续")
    st.stop()

colA, colB = st.columns(2)
with colA:
    st.subheader("📋 今日状态记录")
    mood = st.select_slider("今日总体情绪", options=["很差", "较差", "一般", "较好", "很好"], value="一般")
    sleep = st.selectbox("昨夜睡眠质量", ["很差", "较差", "一般", "较好", "很好"], index=2)
    appetite = st.selectbox("食欲状态", ["下降", "一般", "增加"], index=1)
    exercise = st.selectbox("近24小时运动量", ["无", "少量", "适度", "剧烈"], index=1)

    tags = st.multiselect(
        "今天我想要描述的内容涉及...(请选择)",
        ["情绪波动", "睡眠", "人际", "学业/工作压力", "身体不适", "药物相关", "积极事件", "其他"],
        default=[],
    )

    narrative = st.text_area(
        "当日状态叙述（自由输入，尽量详细）",
        height=220,
        placeholder="例：今天发生了什么？情绪何时变化？出现冲动时做了什么？哪些方法有效？有哪些支持？",
    )
    triggers = st.text_area(
        "今天发生了不如意的事情，这件事的与（触发因素/情境）....有关",
        height=120,
        placeholder="例：人际冲突、学业/工作、躯体不适、环境刺激、回忆/想法等；也可留空。",
    )

with colB:
    st.subheader("🎙 视频录制")
    rec_dir = _today_folder_for(subject)
    base_name = datetime.now().strftime(f"{subject}_%Y%m%d_%H%M%S")
    flv_path = rec_dir / f"{base_name}.flv"

    # 用 webrtc + MediaRecorder 落地 flv
    def recorder_factory():
        return MediaRecorder(str(flv_path))
    webrtc_streamer(
        key="recorder",
        mode=WebRtcMode.SENDONLY,
        rtc_configuration=RTC_CONF,
        media_stream_constraints={"video": True, "audio": True},
        video_frame_callback=None,
        audio_frame_callback=None,
        sendback_audio=False,
        desired_playing_state=None,
        async_processing=True,
        in_recorder_factory=recorder_factory,
    )

    if st.button("🛑 停止并保存"):
        st.toast("已停止录制，保存中…")

# 元数据保存
if st.button("💾 生成/更新状态 JSON", type="secondary"):
    meta = {
        "subject": subject,
        "time": datetime.now().isoformat(timespec="seconds"),
        "mood": mood, "sleep": sleep, "appetite": appetite, "exercise": exercise,
        "tags": tags, "narrative": narrative, "triggers": triggers,
    }
    meta_path = REC_DIR / subject / datetime.now().strftime("%Y%m%d") / f"{base_name}_state.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    st.success(f"已生成/更新状态文件：{meta_path}")

delete_after_upload = st.checkbox(
    "上传成功后删除服务器本地副本（视频与JSON，推荐）",
    value=True,
    help="如需留档，请取消勾选。",
)

# =========================
# 上传：刷新 token + 分片上传
# =========================
st.subheader("☁ 上传到网盘")
conf = load_baidu_conf()
refresh_token = conf.get("refresh_token", "")
save_root = conf.get("save_dir", SAVE_DIR) or SAVE_DIR

if st.button("🚀 开始上传"):
    if not refresh_token:
        st.error("缺少 refresh_token，请在 Secrets 的 [baidu] 中配置。")
        st.stop()

    # 1) 换取 access_token
    st.write("获取 access_token …")
    tok = baidu_token_by_refresh(refresh_token)
    access_token = tok.get("access_token", "")
    new_rt = tok.get("refresh_token")
    if not access_token:
        st.error(f"获取 access_token 失败：{tok}")
        st.stop()
    if new_rt and new_rt != refresh_token:
        st.info("百度返回了新的 refresh_token，请记得到 Secrets 里更新。")

    client = PCSClient(access_token)

    # 2) 选择要上传的当天目录
    day_dir = _today_folder_for(subject)
    files = sorted([p for p in day_dir.glob(f"{subject}_*.mp4")] + [p for p in day_dir.glob(f"{subject}_*.flv")])
    if not files:
        st.warning("未找到可上传的视频文件。请先录制并/或等待转码完成。")
        st.stop()

    # 3) 逐个文件上传（视频与同名 JSON）
    for vid in files:
        base = vid.stem
        meta_json = vid.with_name(f"{base}_state.json")
        remote_dir = f"{save_root.rstrip('/')}/{subject}/{datetime.now().strftime('%Y%m%d')}"
        remote_path = f"{remote_dir}/{vid.name}"

        st.markdown(f"**上传：** `{vid.name}` → `{remote_path}`")
        size = vid.stat().st_size
        parts = _split_parts(vid)
        part_md5s = [_md5_file(p) for p in parts]

        prog = st.progress(0.0, text="准备上传…")

        def on_prog(p: float, msg: str):
            prog.progress(min(max(p, 0.0), 1.0), text=msg)

        # precreate / rapidupload
        on_prog(0.05, "尝试快速上传/预创建…")
        pre = client.rapidupload_or_precreate(remote_path, size, part_md5s, on_prog)

        if not pre.get("ok"):
            st.error(f"预创建失败：{pre}")
            continue

        # 用 is True 做精确判断，帮助类型收窄
        if pre.get("fast") is True:
            on_prog(1.0, "已完成（秒传）")
        else:
            # 显式转换为 str，避免 pyright 把它推断成 bool | Unknown
            uploadid = str(pre.get("uploadid", ""))  # ← 关键修改
            if not uploadid:
                st.error(f"预创建成功但未返回 uploadid：{pre}")
                continue

            # 逐片上传
            total = max(len(parts), 1)
            for i, p in enumerate(parts):
                on_prog(0.1 + 0.75 * (i / total), f"上传分片 {i+1}/{len(parts)} …")
                with p.open("rb") as f:
                    client.upload_part(remote_path, uploadid, i, f.read())

            # 合并
            on_prog(0.9, "合并分片…")
            client.create(remote_path, size, part_md5s, uploadid, on_prog)  # ← 现在是 str 了
            on_prog(1.0, "完成")

        # 清理本地分片
        for p in parts:
            try: p.unlink(missing_ok=True)
            except Exception: pass

        # 上传同名 JSON（若存在）
        if meta_json.exists():
            base2 = meta_json.stem
            remote_json = f"{remote_dir}/{meta_json.name}"
            meta2 = json.loads(meta_json.read_text(encoding="utf-8"))
            meta2["uploaded_at"] = datetime.now().isoformat(timespec="seconds")
            meta_json.write_text(json.dumps(meta2, ensure_ascii=False, indent=2), encoding="utf-8")
            prog2 = st.progress(0.0, text="上传状态 JSON …")

            def on_prog2(p: float, msg: str):
                prog2.progress(min(max(p, 0.0), 1.0), text=msg)

            data = meta_json.read_bytes()
            # 直接一片上传（通常很小）
            client.rapidupload_or_precreate(remote_json, len(data), [hashlib.md5(data).hexdigest()], on_prog2)
            on_prog2(1.0, "完成")

        # 成功后可选删除本地文件
        if delete_after_upload:
            try:
                vid.unlink(missing_ok=True)
                if meta_json.exists():
                    meta_json.unlink(missing_ok=True)
                st.caption("已删除本地副本")
            except Exception as e:
                st.warning(f"删除本地文件失败：{e}")

# =========================
# 页脚提示
# =========================
with st.expander("⚙️ 使用 & 运维提示"):
    st.markdown(
        f"""
- **被试免口令**：使用签名链接 `?sid=...&exp=...&sig=...` 进入时自动放行并锁定“被试编号”。
- **管理员口令**：`APP_PASSWORD_SHA256`（口令的 SHA-256），可通过环境变量或 Secrets 配置。
- **录制**：浏览器 → 服务器落盘（FLV）；如检测到 **ffmpeg**，停止后自动转为 **MP4(H.264/AAC)**。
- **上传**：分片 + 指数退避重试；失败不会删本地文件，可稍后重试。
- **清理**：默认“上传成功即删除本地副本（视频+JSON）”，可取消勾选保留本地。
- **网盘路径**：`{SAVE_DIR}/<被试>/<YYYYMMDD>/视频与同名_state.json`。
- **Token 刷新**：每次上传前自动用 `refresh_token` 换取 `access_token`；若百度返回新的 `refresh_token`，页面会提示你去 Secrets 手动更新。
        """
    )
