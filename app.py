# app.py
# pyright: reportMissingImports=false
"""Private operational questionnaire session with browser-local media save."""

from __future__ import annotations

import copy
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from app_workflow import (
    confirm_admin_intervention_day,
    resolve_trusted_intervention_day,
    support_needed,
)
from browser_recorder import parse_recorder_status, render_browser_recorder
from link_auth import (
    VerifiedLink,
    mark_admin_authenticated,
    reconcile_link_auth_state,
    verify_subject_link,
)
from local_export_bundle import LocalExportBundle
from local_recording_workflow import (
    local_recording_metadata,
    recording_gate_satisfied,
)
from participant_identity import validate_subject_id
from questionnaire_export import build_participant_export
from questionnaire_specs import VISIT_INSTRUMENT_IDS
from questionnaire_ui import questionnaire_state_keys, render_questionnaire
from session_record_workflow import (
    DAILY_CONTEXT_DEFAULTS,
    clear_owned_session_state,
    create_session_record,
    mark_questionnaire_visit_complete,
    persist_daily_questionnaire,
    persist_formal_questionnaire,
    questionnaire_answers,
    questionnaire_visit_complete,
    session_record_matches,
)


_RECORD_KEY = "operational_record"
_EXPORT_KEY = "operational_export_bundle"
_EXPORT_ERROR_KEY = "operational_export_error"
_SAVED_LOCALLY_KEY = "operational_saved_locally"
_COMPLETE_KEY = "operational_complete"
_OWNED_EXACT_KEYS = (
    _RECORD_KEY,
    _EXPORT_KEY,
    _EXPORT_ERROR_KEY,
    _SAVED_LOCALLY_KEY,
    _COMPLETE_KEY,
    "operational_export_retry",
)
_FINISH_EXACT_KEYS = (
    *_OWNED_EXACT_KEYS,
    "participant_identifier",
    "operational_finish",
    "operational_visit_selection",
)
_OWNED_PREFIXES = (
    "questionnaire::",
    "operational_recorder::",
    "operational_daily_context::",
    "operational_recording_continue::",
)
_FINISH_PREFIXES = (*_OWNED_PREFIXES, "operational_admin_day::")


st.set_page_config(
    page_title="问卷会话",
    page_icon="📝",
    layout="centered",
)


def _safe_secret(key: str, default: Any = "") -> Any:
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _get_query_params() -> dict[str, str]:
    try:
        return dict(st.query_params)
    except Exception:
        query = st.experimental_get_query_params()
        return {
            key: value[0] if isinstance(value, list) and value else ""
            for key, value in query.items()
        }


def verify_link_params() -> tuple[VerifiedLink | None, str, bool]:
    query = _get_query_params()
    subject = query.get("sid", "")
    expiry_raw = query.get("exp", "")
    signature = query.get("sig", "")
    attempted = bool(subject or expiry_raw or signature)
    signing_key = _safe_secret("LINK_SIGNING_KEY", "")
    if not (subject and expiry_raw and signature and signing_key):
        return None, "参数或密钥缺失", attempted
    try:
        expiry = int(expiry_raw)
    except (TypeError, ValueError):
        return None, "链接参数无效", attempted
    verified = verify_subject_link(
        signing_key,
        subject,
        expiry,
        signature,
        query.get("visit", "daily"),
        now=int(_utc_now().timestamp()),
    )
    if verified is None:
        return None, "签名或访视不匹配", attempted
    return verified, "", attempted


previous_auth_source = st.session_state.get("auth_source")
previous_signed_context = (
    st.session_state.get("subject_id"),
    st.session_state.get("visit"),
)
verified_link, why_not, signed_link_attempted = verify_link_params()
invalid_signed_link = reconcile_link_auth_state(
    st.session_state,
    verified_link,
    signed_link_attempted=signed_link_attempted,
)
current_auth_source = st.session_state.get("auth_source")
auth_role_changed = (
    previous_auth_source in {"admin", "signed_link"}
    and previous_auth_source != current_auth_source
)
signed_identity_changed = (
    verified_link is not None
    and previous_auth_source == "signed_link"
    and previous_signed_context
    != (verified_link.subject_id, verified_link.visit)
)
if auth_role_changed or signed_identity_changed:
    st.session_state.pop(_COMPLETE_KEY, None)
    st.session_state.pop("participant_identifier", None)


def require_app_password() -> None:
    if verified_link is not None:
        return
    if invalid_signed_link:
        st.error(f"链接未锁定：{why_not}")
        st.stop()

    expected_hash = _safe_secret("APP_PASSWORD_SHA256", "")
    if not expected_hash:
        return
    if (
        st.session_state.get("authed") is True
        and st.session_state.get("auth_source") == "admin"
    ):
        return

    st.title("问卷会话准入")
    st.warning("请输入访问密码以继续")
    password = st.text_input("访问密码", type="password", key="admin_password")
    if st.button("登录", type="primary", key="admin_login"):
        supplied_hash = hashlib.sha256((password or "").encode("utf-8")).hexdigest()
        if hmac.compare_digest(supplied_hash, expected_hash):
            mark_admin_authenticated(st.session_state)
            st.rerun()
        st.error("密码错误")
        st.stop()
    st.stop()


def _clear_current_session() -> None:
    clear_owned_session_state(
        st.session_state,
        exact_keys=_OWNED_EXACT_KEYS,
        prefixes=_OWNED_PREFIXES,
    )


def _finish_current_session() -> None:
    auth_source = st.session_state.get("auth_source")
    clear_owned_session_state(
        st.session_state,
        exact_keys=_FINISH_EXACT_KEYS,
        prefixes=_FINISH_PREFIXES,
    )
    if auth_source == "admin":
        st.session_state.pop("subject_id", None)
        st.session_state.pop("visit", None)
    st.session_state[_COMPLETE_KEY] = True


def _render_export_finalization(bundle: LocalExportBundle) -> None:
    st.warning("下载前请勿刷新或关闭页面，否则当前问卷内容将丢失。")
    st.download_button(
        label="下载问卷记录（JSON + Excel）",
        data=bundle.data,
        file_name=bundle.filename,
        mime="application/zip",
    )
    saved_locally = st.checkbox(
        "我确认问卷 ZIP 已保存到本地",
        key=_SAVED_LOCALLY_KEY,
    )
    st.button(
        "完成本次会话",
        type="primary",
        disabled=not saved_locally,
        on_click=_finish_current_session,
        key="operational_finish",
    )


def _show_support_message() -> None:
    contact = _safe_secret("SAFETY_CONTACT", "请联系研究团队。")
    st.warning(
        "你的安全很重要。请立即联系研究团队或你信任的监护人；\n"
        "如果你正处于紧急危险中，请联系当地急救服务。\n"
        f"{contact or '请联系研究团队。'}"
    )


def _stored_recorder_status(value: object):
    if not isinstance(value, dict) or set(value) != {
        "version",
        "storage",
        "status",
        "mode",
        "duration_seconds",
        "camera_ready",
        "microphone_ready",
        "saved_confirmed",
    }:
        return None
    if value.get("version") != 2 or value.get("storage") != "browser_local":
        return None
    status = parse_recorder_status(
        {
            "mode": value.get("mode"),
            "state": value.get("status"),
            "duration_seconds": value.get("duration_seconds"),
            "camera_ready": value.get("camera_ready"),
            "microphone_ready": value.get("microphone_ready"),
            "saved_confirmed": value.get("saved_confirmed"),
            "error_code": None,
        }
    )
    if local_recording_metadata(status) != value:
        return None
    return status


require_app_password()

if st.session_state.get(_COMPLETE_KEY) is True:
    st.success("本次会话已完成。")
    st.stop()

st.title("问卷会话")
st.subheader("① 当日状态")

locked_link = verified_link
if locked_link is not None:
    subject_id = st.text_input(
        "来访者编号（已由链接锁定）",
        value=locked_link.subject_id, disabled=True,
        key="participant_identifier",
    )
else:
    subject_id = st.text_input(
        "来访者编号",
        value=st.session_state.get("subject_id", "sub-001"),
        key="participant_identifier",
    )
    if why_not and _safe_secret("LINK_SIGNING_KEY", ""):
        st.caption(f"链接未锁定：{why_not}（当前可手动输入编号）")
st.session_state["subject_id"] = subject_id

try:
    safe_subject_id = validate_subject_id(subject_id)
except ValueError:
    st.error("编号无效，请联系研究团队。")
    st.stop()

record_date = _utc_now().date()
is_participant = st.session_state.get("auth_source") == "signed_link"
if is_participant:
    try:
        intervention_day = resolve_trusted_intervention_day(
            _safe_secret("TRUSTED_INTERVENTION_DAYS", {}),
            safe_subject_id,
        )
    except ValueError:
        st.error("无法确认本次日期，请联系研究团队。")
        st.stop()
else:
    admin_scope = hashlib.sha256(
        f"{safe_subject_id}|{record_date.isoformat()}".encode("utf-8")
    ).hexdigest()[:12]
    admin_selection_key = f"operational_admin_day::{admin_scope}::selection"
    admin_confirmation_key = f"operational_admin_day::{admin_scope}::confirmation"
    intervention_day = st.number_input(
        "第几天",
        min_value=1,
        max_value=28,
        value=int(st.session_state.get(admin_selection_key, 1)),
        step=1,
        key=admin_selection_key,
    )
    if st.button(
        "确认日期",
        key=f"operational_admin_day::{admin_scope}::button",
    ):
        st.session_state[admin_confirmation_key] = int(intervention_day)
    if st.session_state.get(admin_confirmation_key) != int(intervention_day):
        st.info("请确认本次日期后继续。")
        st.stop()
    intervention_day = confirm_admin_intervention_day(
        intervention_day,
        confirmed=True,
    )

visit_options = ("daily", *VISIT_INSTRUMENT_IDS)
if locked_link is not None:
    visit = locked_link.visit
    if visit not in visit_options:
        st.error("无法确认本次问卷访视，请联系研究团队。")
        st.stop()
else:
    selected_visit = st.session_state.get("visit", "daily")
    if selected_visit not in visit_options:
        selected_visit = "daily"
    visit = st.selectbox(
        "问卷访视",
        visit_options,
        index=visit_options.index(selected_visit),
        key="operational_visit_selection",
    )
st.session_state["visit"] = visit

record = st.session_state.get(_RECORD_KEY)
if not session_record_matches(
    record,
    subject_id=safe_subject_id,
    record_date=record_date,
    intervention_day=int(intervention_day),
    visit=visit,
):
    _clear_current_session()
    record = create_session_record(
        safe_subject_id,
        record_date,
        int(intervention_day),
        visit,
        token=secrets.token_hex(4),
        now_iso=_utc_now().isoformat(timespec="seconds"),
    )
    st.session_state[_RECORD_KEY] = record

cached_bundle = st.session_state.get(_EXPORT_KEY)
if cached_bundle is not None and not isinstance(
    cached_bundle,
    LocalExportBundle,
):
    st.session_state.pop(_EXPORT_KEY, None)
    st.session_state.pop(_SAVED_LOCALLY_KEY, None)
elif isinstance(cached_bundle, LocalExportBundle):
    _render_export_finalization(cached_bundle)
    st.stop()

session_token = str(record["record_id"]).rsplit("_", 1)[-1]
stored_context = record.get("daily_context", {})
if not isinstance(stored_context, dict):
    stored_context = {}
context_defaults = {
    field_id: copy.deepcopy(stored_context.get(field_id, default))
    for field_id, default in DAILY_CONTEXT_DEFAULTS.items()
}
context_state_keys = {
    field_id: f"operational_daily_context::{session_token}::{field_id}"
    for field_id in DAILY_CONTEXT_DEFAULTS
}
for field_id, widget_key in context_state_keys.items():
    if widget_key not in st.session_state:
        st.session_state[widget_key] = context_defaults[field_id]

st.caption("请尽量用自己的语言描述当天体验。")
c21, c22, c23 = st.columns(3)
sleep_hours = c21.number_input(
    "昨夜睡眠（小时）",
    min_value=0.0,
    max_value=24.0,
    step=0.5,
    key=context_state_keys["sleep_hours"],
)
mood = c22.slider(
    "当前心境（1=很差，9=很好）",
    1,
    9,
    key=context_state_keys["mood_1to9"],
)
stress = c23.slider(
    "当前压力（1=很低，9=很高）",
    1,
    9,
    key=context_state_keys["stress_1to9"],
)

c31, c32, c33 = st.columns(3)
pain = c31.slider(
    "身体不适/疼痛（0=无，10=最剧烈）",
    0,
    10,
    key=context_state_keys["pain_0to10"],
)
urge = c32.slider(
    "自伤冲动强度（0=无，10=极强）",
    0,
    10,
    key=context_state_keys["nssi_urge_0to10"],
)
coping_effect = c33.slider(
    "本日应对效果（1=很差，5=很好）",
    1,
    5,
    key=context_state_keys["coping_effect_1to5"],
)

c41, c42 = st.columns(2)
caffeine = c41.selectbox(
    "近6小时咖啡因",
    ["无", "少量", "适度", "较多"],
    key=context_state_keys["caffeine"],
)
exercise = c42.selectbox(
    "近24小时运动量",
    ["无", "少量", "适度", "剧烈"],
    key=context_state_keys["exercise"],
)
tags = st.multiselect(
    "今天我想要描述的内容涉及...（请选择）",
    [
        "情绪波动",
        "睡眠",
        "人际",
        "学业/工作压力",
        "身体不适",
        "药物相关",
        "积极事件",
        "其他",
    ],
    key=context_state_keys["tags"],
)
narrative = st.text_area(
    "当日状态叙述（自由输入，尽量详细）",
    height=220,
    placeholder="今天发生了什么？情绪何时变化？哪些方法有效？有哪些支持？",
    key=context_state_keys["narrative"],
)
triggers = st.text_area(
    "今天发生的不如意与哪些触发因素或情境有关？",
    height=120,
    placeholder="例如人际、学业、工作、身体不适、环境、回忆或想法；也可留空。",
    key=context_state_keys["triggers"],
)
coping_used = st.multiselect(
    "面对今天的不如意，我的应对方式是...（可多选）",
    [
        "转移注意",
        "呼吸放松/冥想",
        "运动",
        "写作/绘画",
        "联系他人",
        "专业求助",
        "其他",
    ],
    key=context_state_keys["coping_used"],
)

daily_context = {
    "sleep_hours": float(sleep_hours),
    "mood_1to9": int(mood),
    "stress_1to9": int(stress),
    "pain_0to10": int(pain),
    "nssi_urge_0to10": int(urge),
    "coping_effect_1to5": int(coping_effect),
    "caffeine": caffeine,
    "exercise": exercise,
    "tags": list(tags),
    "coping_used": list(coping_used),
    "narrative": narrative or "",
    "triggers": triggers or "",
}
record["daily_context"] = copy.deepcopy(daily_context)

st.subheader("② 本地录制")
pending_terminal_key = f"operational_recorder::pending::{session_token}"
continue_without_key = f"operational_recording_continue::{session_token}"
stored_status = _stored_recorder_status(record.get("recording"))
stored_continue = (
    stored_status is not None
    and stored_status.state in {"skipped", "failed"}
)
recording_locked = (
    stored_status is not None
    and recording_gate_satisfied(stored_status, stored_continue)
)
recording_phase_complete = recording_locked
if recording_locked:
    gate_status = stored_status
    st.session_state.pop(pending_terminal_key, None)
    st.session_state.pop(continue_without_key, None)
else:
    recorder_key = f"operational_recorder::{session_token}"
    recorder_status = render_browser_recorder(
        key=recorder_key,
        initial_mode="long",
    )
    terminal_status = None
    if recorder_status.state in {"skipped", "failed"}:
        terminal_status = recorder_status
        st.session_state[pending_terminal_key] = local_recording_metadata(
            recorder_status
        )
    elif recorder_status.state == "idle":
        pending_status = _stored_recorder_status(
            st.session_state.get(pending_terminal_key)
        )
        if (
            pending_status is not None
            and pending_status.state in {"skipped", "failed"}
            and pending_status.mode == recorder_status.mode
            and st.session_state.get(continue_without_key) is True
        ):
            terminal_status = pending_status
        else:
            st.session_state.pop(pending_terminal_key, None)
            st.session_state.pop(continue_without_key, None)
    else:
        st.session_state.pop(pending_terminal_key, None)
        st.session_state.pop(continue_without_key, None)

    gate_status = terminal_status or recorder_status
    continue_without_recording = False
    if terminal_status is not None:
        continue_without_recording = st.checkbox(
            "我确认继续填写问卷，不保存本次录制",
            key=continue_without_key,
        )

    recording_phase_complete = recording_gate_satisfied(
        gate_status,
        continue_without_recording,
    )
if not recording_phase_complete:
    st.info("请先完成本地录制保存，或在无法录制时明确确认继续。")
    st.stop()
if not recording_locked:
    st.session_state.pop(pending_terminal_key, None)
    record["recording"] = local_recording_metadata(gate_status)

st.warning("进入问卷后请勿刷新或关闭页面，否则当前问卷内容将丢失。")
state_namespace = f"operational_questionnaire::{session_token}"
state_keys = questionnaire_state_keys(state_namespace, visit)
completion = record.get("completion", {})
answered_by_visit = completion.get("answered_field_ids", {})
step_by_visit = completion.get("current_step", {})
answers = questionnaire_answers(record, visit)


def save_questionnaire_draft(
    updated_answers: dict[str, Any],
    answered_field_ids: set[str],
) -> None:
    if isinstance(st.session_state.get(_EXPORT_KEY), LocalExportBundle):
        return
    current_step = int(st.session_state.get(state_keys.step, 0))
    if visit == "daily":
        persist_daily_questionnaire(
            record,
            updated_answers,
            answered_field_ids,
            current_step=current_step,
            daily_context=daily_context,
        )
    else:
        record["daily_context"] = copy.deepcopy(daily_context)
        persist_formal_questionnaire(
            record,
            visit,
            updated_answers,
            answered_field_ids,
            current_step=current_step,
        )


if not questionnaire_visit_complete(record, visit):
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
    persisted_answered = record.get("completion", {}).get(
        "answered_field_ids", {}
    )
    if isinstance(persisted_answered, dict):
        current_answered.update(persisted_answered.get(visit, []))
    if support_needed(
        visit,
        answers,
        current_answered,
        int(record["intervention_day"]),
    ):
        _show_support_message()
    if not questionnaire_complete:
        st.info("请完成所有必填且适用的问题后继续。")
        st.stop()

    save_questionnaire_draft(answers, current_answered)
    mark_questionnaire_visit_complete(
        record,
        visit,
        completed_at_iso=_utc_now().isoformat(timespec="seconds"),
    )
else:
    current_answered = set(answered_by_visit.get(visit, []))
    if support_needed(
        visit,
        answers,
        current_answered,
        int(record["intervention_day"]),
    ):
        _show_support_message()

bundle = st.session_state.get(_EXPORT_KEY)
if bundle is None and st.session_state.get(_EXPORT_ERROR_KEY) is True:
    st.error("下载文件暂时无法生成，请重试。")
    if st.button("重试生成下载文件", key="operational_export_retry"):
        st.session_state.pop(_EXPORT_ERROR_KEY, None)
        st.rerun()
    st.stop()

if bundle is None:
    record_snapshot = copy.deepcopy(record)
    try:
        bundle = build_participant_export(
            record_snapshot,
            visit=visit,
            exported_at=_utc_now(),
        )
        if not isinstance(bundle, LocalExportBundle):
            raise TypeError("export builder returned an invalid bundle")
    except Exception:
        st.session_state[_EXPORT_ERROR_KEY] = True
        st.error("下载文件暂时无法生成，请重试。")
        if st.button("重试生成下载文件", key="operational_export_retry"):
            st.session_state.pop(_EXPORT_ERROR_KEY, None)
            st.rerun()
        st.stop()
    st.session_state[_EXPORT_KEY] = bundle
    st.session_state.pop(_EXPORT_ERROR_KEY, None)

_render_export_finalization(bundle)
