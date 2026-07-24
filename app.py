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
import hmac
import hashlib
import random
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List

import requests
import toml
import streamlit as st
from streamlit.components.v1 import html
from streamlit_webrtc import webrtc_streamer, WebRtcMode, RTCConfiguration
from aiortc.contrib.media import MediaRecorder

from link_auth import (
    VerifiedLink,
    mark_admin_authenticated,
    reconcile_link_auth_state,
    verify_subject_link,
)
from app_workflow import (
    cleanup_pending_message,
    persist_daily_questionnaire,
    persist_formal_questionnaire,
    questionnaire_answers,
    resolve_trusted_intervention_day,
    support_needed,
    upload_failure_message,
)
from questionnaire_specs import VISIT_INSTRUMENT_IDS
from questionnaire_ui import questionnaire_state_keys, render_questionnaire
from record_store import DailyRecordStore, remote_record_dir, validate_subject_id
from upload_workflow import LocalCleanupError, upload_record_bundle

# =========================
# 基础：页面设置 & 工具函数
# =========================
st.set_page_config(
    page_title="欢迎来到清华大学YMH-Lab",
    page_icon="🎥",
    layout="centered",
)

def _safe_secret(key: str, default: Any = "") -> Any:
    """优先从 st.secrets 读取；无 secrets.toml 时回退到环境变量。"""
    try:
        return st.secrets[key]  # 本地无 secrets.toml 时可能抛异常
    except Exception:
        return os.getenv(key, default)

ROOT = Path(__file__).resolve().parent
REC_DIR = ROOT / "recordings"
REC_DIR.mkdir(parents=True, exist_ok=True)
record_store = DailyRecordStore(REC_DIR)
CONF_PATH = ROOT / "config.toml"

# ---- 读取配置：优先 Secrets，其次本地 config.toml（仅本地调试用） ----
CFG: Dict[str, Any] = {}
try:
    if "baidu" in st.secrets:  # type: ignore[operator]
        CFG = dict(st.secrets["baidu"])  # type: ignore[index]
except Exception:
    pass
if not CFG and CONF_PATH.exists():
    CFG = toml.loads(CONF_PATH.read_text(encoding="utf-8")).get("baidu", {}) or {}

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

def _get_query_params() -> Dict[str, str]:
    try:
        return dict(st.query_params)  # streamlit>=1.36
    except Exception:
        qp = st.experimental_get_query_params()
        return {k: (v[0] if isinstance(v, list) and v else "") for k, v in qp.items()}

def verify_link_params() -> tuple[Optional[VerifiedLink], str, bool]:
    q = _get_query_params()
    sid = q.get("sid", "")
    exp_raw = q.get("exp", "")
    sig = q.get("sig", "")
    signed_link_attempted = bool(sid or exp_raw or sig)
    if not (sid and exp_raw and sig and LINK_SIGNING_KEY):
        return None, "参数/密钥缺失", signed_link_attempted
    try:
        exp = int(exp_raw)
    except Exception:
        return None, "exp 非法", signed_link_attempted
    verified = verify_subject_link(
        LINK_SIGNING_KEY,
        sid,
        exp,
        sig,
        q.get("visit", "daily"),
        now=int(datetime.now(timezone.utc).timestamp()),
    )
    if verified is None:
        return None, "签名或访视不匹配", signed_link_attempted
    return verified, "", signed_link_attempted


verified_link, why_not, signed_link_attempted = verify_link_params()
invalid_signed_link = reconcile_link_auth_state(
    st.session_state,
    verified_link,
    signed_link_attempted=signed_link_attempted,
)

# =========================
# 入口门禁：先验签（被试免口令），否则走口令
# =========================
def require_app_password():
    # ① 验签成功（被试入口）→ 直接放行并锁定编号
    if verified_link:
        return

    if invalid_signed_link:
        st.error(f"链接未锁定：{why_not}")
        st.stop()

    # ② 否则需要口令（管理员/调试）
    expected_hash = _safe_secret("APP_PASSWORD_SHA256", "")
    if not expected_hash:
        return  # 未配置口令则放行（仅内部/本地）
    if (
        st.session_state.get("authed", False)
        and st.session_state.get("auth_source") == "admin"
    ):
        return

    st.title("🔒 taVNS干预视频日志准入界面")
    st.warning("请输入访问密码以继续")
    pw = st.text_input("访问密码", type="password")
    if st.button("登录", type="primary"):
        got = hashlib.sha256((pw or "").encode("utf-8")).hexdigest()
        if hmac.compare_digest(got, expected_hash):
            mark_admin_authenticated(st.session_state)
            st.rerun()
        else:
            st.error("密码错误"); st.stop()
    else:
        st.stop()

require_app_password()
st.title("📓 taVNS 干预日志")

# 公共 STUN
RTC_CFG = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})

# =========================
# 百度网盘 API（分片 + 指数退避重试）
# =========================
OAUTH_TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
PRECREATE_URL   = "https://pan.baidu.com/rest/2.0/xpan/file?method=precreate"
SUPERFILE2_URL  = "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2"
CREATE_URL      = "https://pan.baidu.com/rest/2.0/xpan/file?method=create"

def _headers():
    return {"User-Agent": "exp-recorder/0.4"}

def _post_with_retry(url: str, *, data=None, params=None, files=None,
                     timeout: int = 60, max_retries: int = 3,
                     backoff: float = 1.6) -> dict:
    last_err: Exception | None = None
    for i in range(max_retries):
        try:
            r = requests.post(url, data=data, params=params, files=files,
                              headers=_headers(), timeout=timeout)
            if r.status_code >= 500 or r.status_code == 429:
                raise requests.HTTPError(f"{r.status_code} {r.text[:200]}")
            return r.json()
        except Exception as e:
            last_err = e
            if i == max_retries - 1:
                break
            time.sleep((backoff ** i) + random.random() * 0.5)
    raise RuntimeError(f"请求失败（已重试 {max_retries} 次）：{last_err}")

# ---------- 用 refresh_token 刷新 access_token（带会话缓存 + 退避重试） ----------
OAUTH_TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"

def ensure_token(max_retries: int = 5) -> str:
    """
    优先使用会话缓存的 access_token；必要时用 refresh_token 刷新。
    - 触发风控/临时失败：指数退避重试
    - refresh_token 失效：抛出明确异常提示重新授权
    """
    # 1) 先用缓存（避免同一会话里重复刷新导致触发风控）
    cache = st.session_state.get("bd_token_cache", {})
    now = time.time()
    if cache and cache.get("token") and cache.get("exp_ts", 0) - 120 > now:
        return cache["token"]

    refresh_token = CFG.get("refresh_token", "")
    if not refresh_token:
        raise RuntimeError("缺少 refresh_token：请在 Secrets 的 [baidu] 中填写 refresh_token。")

    # 2) 退避重试刷新
    last_err: dict | None = None
    for i in range(max_retries):
        try:
            resp = requests.post(
                OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": AK,
                    "client_secret": SK,
                },
                timeout=15,
                headers={"User-Agent": "exp-recorder/0.4"},
            )
            j = resp.json()
        except Exception as e:
            j = {"error": "network", "error_description": str(e)}

        # 成功
        if "access_token" in j:
            token = j["access_token"]
            # 记一次缓存（优先用服务端返回的 expires_in；没有就默认 1 小时）
            ttl = int(j.get("expires_in", 3600))
            st.session_state["bd_token_cache"] = {"token": token, "exp_ts": now + ttl}
            # 如果百度顺带换发了新的 refresh_token，仅提示手动更新 Secrets（不自动写）
            if j.get("refresh_token") and j["refresh_token"] != refresh_token:
                st.info("百度返回了新的 refresh_token，请到 Secrets 手动更新。")
            return token

        # 处理常见错误
        err = str(j.get("error", "")).lower()
        desc = str(j.get("error_description", "")).lower()
        last_err = j

        # 风控/限流/临时失败 -> 退避后再试
        if ("security" in err) or ("try again later" in desc) or resp.status_code in (429, 503):
            delay = (2 ** i) + random.random() * 0.5
            time.sleep(delay)
            continue

        # 授权失效/被撤销/refresh_token 错
        if err in ("invalid_grant", "invalid_request"):
            raise RuntimeError("百度提示 refresh_token 失效或被撤销：请重新授权，更新 Secrets 中的 refresh_token。")

        # AK/SK 错
        if err in ("invalid_client", "unauthorized_client"):
            raise RuntimeError("百度提示 AK/SK 不正确或应用权限异常：请核对 Secrets 中的 app_key/secret_key。")

        # 其它错误
        break

    raise RuntimeError(f"刷新 access_token 失败（已重试 {max_retries} 次）：{last_err}")
def upload_to_baidu(
    local_path: Path,
    remote_path: str,
    chunk_size: int = 8 * 1024 * 1024,
    progress_cb: Callable[[float, str], None] | None = None,
) -> dict:
    """三步上传：precreate -> superfile2(分片) -> create（带重试）。"""
    token = ensure_token()
    size = local_path.stat().st_size

    # 分片 md5
    part_md5s: List[str] = []
    with local_path.open("rb") as f:
        while True:
            buf = f.read(chunk_size)
            if not buf:
                break
            part_md5s.append(hashlib.md5(buf).hexdigest())

    # 1) precreate
    pre = _post_with_retry(
        PRECREATE_URL,
        data={
            "access_token": token, "path": remote_path, "size": size,
            "isdir": 0, "autoinit": 1, "rtype": 3,
            "block_list": json.dumps(part_md5s),
        },
        timeout=60,
        max_retries=4,
    )
    if pre.get("return_type") == 2:
        if progress_cb: progress_cb(1.0, "秒传完成")
        return {"ok": True, "fast_upload": True, "path": pre.get("path")}

    uploadid = pre["uploadid"]
    need_idx = set(pre["block_list"])

    # 2) superfile2
    sent = 0
    with local_path.open("rb") as f:
        for idx in range(len(part_md5s)):
            buf = f.read(chunk_size)
            if idx not in need_idx:
                sent += len(buf)
                if progress_cb: progress_cb(sent/size, f"跳过已存在分片 {idx}")
                continue
            files = {"file": ("blob", buf)}
            params = {
                "access_token": token, "method": "upload", "type": "tmpfile",
                "path": remote_path, "uploadid": uploadid, "partseq": idx
            }
            j = _post_with_retry(
                SUPERFILE2_URL, params=params, files=files,
                timeout=120, max_retries=4
            )
            if "md5" not in j:
                raise RuntimeError(f"分片 {idx} 上传失败：{j}")
            sent += len(buf)
            if progress_cb: progress_cb(sent/size, f"已上传分片 {idx}")

    # 3) create
    create = _post_with_retry(
        CREATE_URL,
        data={
            "access_token": token, "path": remote_path, "size": size,
            "isdir": 0, "rtype": 3, "uploadid": uploadid,
            "block_list": json.dumps(part_md5s),
        },
        timeout=60,
        max_retries=4,
    )
    if "fs_id" not in create:
        raise RuntimeError(f"创建文件失败：{create}")
    if progress_cb: progress_cb(1.0, "合并完成")
    return {"ok": True, "fast_upload": False, "result": create}

# =========================
# 转码：FLV/WebM -> MP4（ffmpeg）
# =========================
def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None

def transcode_to_mp4(src: Path) -> Optional[Path]:
    if not has_ffmpeg():
        return None
    dst = src.with_suffix(".mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return dst if dst.exists() else None
    except Exception:
        return None

# =========================
# ① 当日状态（NLP 友好）
# =========================
st.subheader("① 当日状态")

locked_link = verified_link
if locked_link:
    subject_id = st.text_input("来访者编号（已由链接锁定）", value=locked_link.subject_id, disabled=True)
else:
    subject_id = st.text_input("来访者编号", value=st.session_state.get("subject_id", "sub-001"))
    if why_not and LINK_SIGNING_KEY:
        st.caption(f"链接未锁定：{why_not}（当前可手动输入被试编号）")
st.session_state["subject_id"] = subject_id

is_participant = st.session_state.get("auth_source") == "signed_link"
try:
    safe_subject_id = validate_subject_id(subject_id)
except ValueError:
    st.error("受试者编号无效，请联系研究团队。")
    st.stop()

record_date = datetime.now().date()
if is_participant:
    try:
        intervention_day = resolve_trusted_intervention_day(
            _safe_secret("TRUSTED_INTERVENTION_DAYS", {}), safe_subject_id
        )
    except ValueError:
        st.error("无法确认本次干预日期，请联系研究团队。")
        st.stop()
else:
    intervention_day = st.number_input(
        "干预第几天",
        min_value=1,
        max_value=28,
        value=int(st.session_state.get(f"admin_intervention_day::{safe_subject_id}", 1)),
        step=1,
        key=f"admin_intervention_day::{safe_subject_id}",
    )

record = record_store.get_or_create(
    safe_subject_id, record_date, int(intervention_day)
)
visit = locked_link.visit if locked_link else st.selectbox(
    "问卷访视", ("daily", *VISIT_INSTRUMENT_IDS),
    index=("daily", *VISIT_INSTRUMENT_IDS).index(st.session_state.get("visit", "daily")),
)
st.session_state["visit"] = visit

st.caption("说明：尽量用你的语言详述当天体验，这将有利于我们对于你基本状况的掌握。")

c21, c22, c23 = st.columns(3)
sleep_hours = c21.number_input("昨夜睡眠（小时）", 0.0, 24.0, 7.0, 0.5)
mood        = c22.slider("当前心境（1=很差，9=很好）", 1, 9, 5)
stress      = c23.slider("当前压力（1=很低，9=很高）", 1, 9, 4)

c31, c32, c33 = st.columns(3)
pain         = c31.slider("身体不适/疼痛（0=无，10=最剧烈）", 0, 10, 1)
urge         = c32.slider("自伤冲动强度（0=无，10=极强）", 0, 10, 0)
coping_eff   = c33.slider("本日应对效果（1=很差，5=很好）", 1, 5, 3)

c41, c42 = st.columns(2)
caffeine = c41.selectbox("近6小时咖啡因", ["无", "少量", "适度", "较多"], index=1)
exercise = c42.selectbox("近24小时运动量", ["无", "少量", "适度", "剧烈"], index=1)

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
coping_used = st.multiselect(
    "面对今天的不如意，我的应对方式是...（可多选）",
    ["转移注意", "呼吸放松/冥想", "运动", "写作/绘画", "联系他人", "专业求助", "其他"],
    default=[],
)

st.session_state["state_payload"] = {
    "schema_version": 3,
    "subject_id": subject_id,
    "timestamp_client_open_iso": datetime.now().isoformat(timespec="seconds"),
    "sleep_hours": float(sleep_hours),
    "mood_1to9": int(mood),
    "stress_1to9": int(stress),
    "pain_0to10": int(pain),
    "nssi_urge_0to10": int(urge),
    "coping_effect_1to5": int(coping_eff),
    "caffeine": caffeine,
    "exercise": exercise,
    "tags": tags,
    "coping_used": coping_used,
    "narrative": narrative or "",
    "triggers": triggers or "",
}

# =========================
# ② 录制（FLV → MP4），带前端计时 & 服务器侧起止时间
# =========================
st.subheader("② 录制视频")

MAX_RECORD_MIN = 20  # 超过会在前端提示，可自行调整

base_name = record["record_id"]
flv_path = REC_DIR / f"{base_name}.flv"
if st.session_state.get("recorder_record_id") != record["record_id"]:
    st.session_state["recorder_record_id"] = record["record_id"]
    st.session_state["recorder_out_path"] = str(flv_path)
    st.session_state["recorder_converted_mp4"] = None
    st.session_state.last_saved = None
st.session_state.setdefault("recorder_format", "flv")

st.caption("点击 START 开始录制，STOP 停止并写入文件（如检测到 ffmpeg 将自动转为 MP4）。")

def out_recorder_factory():
    st.session_state["recorder_out_path"] = str(flv_path)
    st.session_state["recorder_format"] = "flv"
    st.session_state["record_started_at_iso"] = datetime.now().isoformat(timespec="seconds")
    return MediaRecorder(st.session_state["recorder_out_path"], format="flv")

webrtc_ctx = webrtc_streamer(
    key="recorder",
    mode=WebRtcMode.SENDRECV,
    rtc_configuration=RTC_CFG,
    media_stream_constraints={"video": True, "audio": True},
    out_recorder_factory=out_recorder_factory,
)

# 前端 JS 计时
if webrtc_ctx and webrtc_ctx.state.playing:
    html(
        f"""
        <div style="font-size:16px;margin:6px 0;">
          ⏱️ 正在录制：<span id="dur">00:00</span>
          <span id="warn" style="color:#d97706;font-weight:600;margin-left:8px;"></span>
        </div>
        <script>
        const start = Date.now();
        const warnAt = {MAX_RECORD_MIN} * 60;
        setInterval(() => {{
          const s = Math.floor((Date.now() - start) / 1000);
          const m = String(Math.floor(s/60)).padStart(2,'0');
          const sec = String(s%60).padStart(2,'0');
          document.getElementById('dur').innerText = m + ":" + sec;
          if (s > warnAt && document.getElementById('warn').innerText === "") {{
            document.getElementById('warn').innerText = "（提示：已超过建议录制时长）";
          }}
        }}, 500);
        </script>
        """,
        height=30,
    )

# =========================
# ③ 录制结果 → 生成 JSON → 上传（视频+JSON）
# =========================
st.subheader("③ 查看与上传")

if "last_saved" not in st.session_state:
    st.session_state.last_saved = None

out_path_str = st.session_state.get("recorder_out_path")
out_file = Path(out_path_str) if out_path_str else None

if webrtc_ctx and not webrtc_ctx.state.playing and out_file and out_file.exists():
    just_finished = st.session_state.last_saved != str(out_file)
    if just_finished:
        st.session_state.last_saved = str(out_file)
        st.session_state["record_ended_at_iso"] = datetime.now().isoformat(timespec="seconds")
        st.info("正在尝试将 FLV 转码为 MP4…（需要本机已安装 ffmpeg）")
        mp4_path = transcode_to_mp4(out_file)
        if mp4_path and mp4_path.exists():
            st.success(f"转码成功：{mp4_path.name}")
            st.session_state["recorder_converted_mp4"] = str(mp4_path)
        else:
            st.warning("未检测到 ffmpeg 或转码失败，将保留 FLV。")
            st.session_state["recorder_converted_mp4"] = None

    final_play = Path(st.session_state.get("recorder_converted_mp4") or out_file)
    st.success(f"录制完成，文件：{final_play.name}")
    st.video(str(final_play))

    # 状态 JSON
    state_payload = st.session_state.get("state_payload", {}) or {}
    state_namespace = f"{record['record_id']}:r{record['revision']}"
    state_keys = questionnaire_state_keys(state_namespace, visit)
    answered_by_visit = record.get("completion", {}).get("answered_field_ids", {})
    step_by_visit = record.get("completion", {}).get("current_step", {})
    answers = questionnaire_answers(record, visit)

    def save_questionnaire_draft(
        updated_answers: dict[str, Any], answered_field_ids: set[str]
    ) -> None:
        current_step = int(st.session_state.get(state_keys.step, 0))
        if visit == "daily":
            persist_daily_questionnaire(
                record, updated_answers, answered_field_ids, current_step=current_step
            )
        else:
            persist_formal_questionnaire(
                record, visit, updated_answers, answered_field_ids,
                current_step=current_step,
            )
        record_store.save(record)

    answers, questionnaire_complete = render_questionnaire(
        subject_id=safe_subject_id,
        intervention_day=int(record["intervention_day"]),
        answers=answers,
        save_draft=save_questionnaire_draft,
        visit=visit,
        state_namespace=state_namespace,
        initial_answered_field_ids=answered_by_visit.get(visit, []),
        initial_step=step_by_visit.get(visit, 0),
    )
    current_answered = set(st.session_state.get(state_keys.answered, []))
    if support_needed(visit, answers, current_answered, int(record["intervention_day"])):
        contact = _safe_secret("SAFETY_CONTACT", "请联系研究团队。")
        st.warning(
            "你的安全很重要。请立即联系研究团队或你信任的监护人；\n"
            "如果你正处于紧急危险中，请联系当地急救服务。\n"
            f"{contact or '请联系研究团队。'}"
        )
    if not questionnaire_complete:
        st.info("请完成问卷后继续上传。")
        st.stop()

    save_questionnaire_draft(answers, current_answered)
    record["daily_context"] = state_payload
    record["recording"] = {
        "video_filename": final_play.name,
        "started_at_iso": st.session_state.get("record_started_at_iso", ""),
        "ended_at_iso": st.session_state.get("record_ended_at_iso", ""),
        "format": final_play.suffix.lstrip(".").lower(),
    }
    record.setdefault("completion", {})["status"] = "complete"
    record_store.save(record)
    meta_path = record_store.path_for(record)
    remote_dir = remote_record_dir(
        SAVE_DIR, safe_subject_id, record["record_date"], record["record_id"]
    )

    delete_after_upload = True
    if not is_participant:
        delete_after_upload = st.checkbox(
            "上传成功后删除服务器本地副本（视频与 JSON）",
            value=True,
            key="del_after_upload_recent",
        )
        st.write("将上传到网盘目录：", f"`{remote_dir}`")
        st.json(record["upload"])

    c1, c2 = st.columns([1, 1])
    if c1.button("上传视频和问卷记录", type="primary"):
        json_progress = st.progress(0, text="正在上传问卷记录")
        video_progress = st.progress(0, text="正在上传视频")

        def on_json_progress(progress: float, message: str) -> None:
            json_progress.progress(
                min(max(progress, 0.0), 1.0), text=f"[JSON] {int(progress * 100)}% - {message}"
            )

        def on_video_progress(progress: float, message: str) -> None:
            video_progress.progress(
                min(max(progress, 0.0), 1.0), text=f"[视频] {int(progress * 100)}% - {message}"
            )

        def persist_upload(upload_state: dict[str, str]) -> None:
            record["upload"] = upload_state
            record_store.save(record)

        cleanup_paths = (out_file,) if final_play != out_file else ()
        try:
            upload_record_bundle(
                meta_path,
                final_play,
                remote_dir,
                upload_to_baidu,
                persist_state=persist_upload,
                delete_after_upload=delete_after_upload,
                cleanup_paths=cleanup_paths,
                json_progress=on_json_progress,
                video_progress=on_video_progress,
            )
            st.success("上传完成。")
        except LocalCleanupError as error:
            st.warning(cleanup_pending_message(error, participant=is_participant))
        except Exception:
            st.error(upload_failure_message(record["record_id"], participant=is_participant))

    if c2.button("重新录制"):
        st.session_state.last_saved = None
        st.session_state["recorder_converted_mp4"] = None
        st.rerun()

else:
    if webrtc_ctx and webrtc_ctx.state.playing:
        st.info("录制进行中… 点击 STOP 结束并进入上传。")
    else:
        st.info("录制未开始。点击 START 开始录制。")

# =========================
# ④ 历史文件上传（可复用当前状态JSON）
# =========================
if is_participant:
    st.stop()

st.divider()
st.subheader("④ 从 recordings 目录选择历史文件上传")

with st.expander("使用 & 运维提示"):
    st.caption("管理员可使用历史文件上传工具。")

files = sorted(
    [p for p in REC_DIR.glob("*") if p.suffix.lower() in [".mp4", ".flv"]],
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)
if not files:
    st.caption("recordings/ 目录尚无 .mp4/.flv 文件。完成一次录制后这里会列出文件。")
else:
    picked = st.selectbox("选择要上传的历史视频：", files, format_func=lambda p: p.name)

    upload_state_too = st.checkbox("同时生成并上传“当前页面的状态JSON”", value=False)

    delete_after_upload_hist = st.checkbox(
        "上传成功后删除该本地视频文件（历史）", value=True, key="del_after_upload_history"
    )

    sid_hist = st.session_state.get("subject_id", "sub-unknown")
    date_str2 = datetime.now().strftime("%Y%m%d")
    remote_dir2 = f"{SAVE_DIR}/{sid_hist}/{date_str2}"
    remote_video2 = f"{remote_dir2}/{picked.name}"
    st.write("将要上传到：", f"`{remote_dir2}`")

    go_hist = st.button("开始上传（历史视频）")
    if go_hist:
        prog2 = st.progress(0, text="上传历史视频中…")
        def on_prog2(p: float, msg: str):
            prog2.progress(min(max(p, 0.0), 1.0), text=f"[视频] {int(p*100)}% - {msg}")
        try:
            res2 = upload_to_baidu(picked, remote_video2, progress_cb=on_prog2)
            prog2.progress(1.0, text="[视频] 上传完成 ✔")
            st.success("历史视频上传成功！")
            st.json(res2)

            if upload_state_too:
                base2 = Path(picked).stem
                meta2 = st.session_state.get("state_payload", {}) or {}
                meta2 = {
                    **meta2,
                    "file_basename": base2,
                    "video_filename": picked.name,
                    "timestamp_iso_generated": datetime.now().isoformat(timespec="seconds"),
                }
                meta_path2 = REC_DIR / f"{base2}_state.json"
                meta_path2.write_text(json.dumps(meta2, ensure_ascii=False, indent=2), encoding="utf-8")
                prog3 = st.progress(0, text="上传历史状态JSON中…")
                def on_prog3(p: float, msg: str):
                    prog3.progress(min(max(p, 0.0), 1.0), text=f"[JSON] {int(p*100)}% - {msg}")
                res3 = upload_to_baidu(meta_path2, f"{remote_dir2}/{meta_path2.name}", progress_cb=on_prog3)
                prog3.progress(1.0, text="[JSON] 上传完成 ✔")
                st.success("历史状态JSON上传成功！")
                st.json(res3)
                try:
                    meta_path2.unlink(missing_ok=True)
                except Exception:
                    pass

            if delete_after_upload_hist:
                try:
                    picked.unlink(missing_ok=True)
                    st.caption("已从服务器删除该本地视频（历史）。")
                except Exception:
                    pass

        except Exception as e:
            prog2.progress(0.0, text="上传失败")
            st.error(f"上传失败：{e}")

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
