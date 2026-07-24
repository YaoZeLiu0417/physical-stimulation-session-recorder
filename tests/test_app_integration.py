import ast
import importlib
import json
from datetime import date
from pathlib import Path

import pytest

from questionnaire_specs import FORMAL_INSTRUMENTS, VISIT_INSTRUMENT_IDS
from record_store import DailyRecordStore
from upload_workflow import LocalCleanupError


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
WORKFLOW_MODULE = "app_workflow"


def _workflow():
    try:
        return importlib.import_module(WORKFLOW_MODULE)
    except ModuleNotFoundError:
        pytest.fail("app_workflow integration layer is not implemented")


def _record(day=6):
    return {
        "record_id": "sub-001_20260724_deadbeef",
        "subject_id": "sub-001",
        "record_date": "2026-07-24",
        "intervention_day": day,
        "revision": 3,
        "instrument_versions": {
            "daily_nssi_ema": "1.0",
            "weekly_nssi": "1.0",
            "formal_nssi_crf": "1.0",
        },
        "daily_core": {},
        "conditional_details": {},
        "weekly_extension": {},
        "formal_visits": {},
        "field_status": {},
        "derived_metrics": {},
        "safety_signals": {},
        "recording": {},
        "completion": {
            "status": "draft",
            "answered_field_ids": {},
            "current_step": {},
        },
        "upload": {"json": "pending", "video": "pending"},
    }


def test_app_imports_required_integration_interfaces():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert {
        "DailyRecordStore",
        "LocalCleanupError",
        "questionnaire_state_keys",
        "remote_record_dir",
        "render_questionnaire",
        "upload_record_bundle",
        "validate_subject_id",
    } <= imported


def test_app_uses_revision_scoped_questionnaire_state_and_callback_step():
    source = APP_PATH.read_text(encoding="utf-8")
    assert 'state_namespace = f"{record[\'record_id\']}:r{record[\'revision\']}"' in source
    assert "state_keys = questionnaire_state_keys(state_namespace, visit)" in source
    assert "st.session_state.get(state_keys.step" in source
    assert "state_namespace=state_namespace" in source
    assert "initial_answered_field_ids=answered_by_visit.get(visit, [])" in source
    assert "initial_step=step_by_visit.get(visit, 0)" in source


def test_app_has_no_legacy_global_questionnaire_restoration():
    source = APP_PATH.read_text(encoding="utf-8")
    assert "questionnaire_restored_" not in source
    assert "question_step_" not in source
    assert 'st.session_state["answered_field_ids"]' not in source
    assert 'st.session_state["q_' not in source


def test_trusted_intervention_day_accepts_only_subject_scoped_values_1_to_28():
    workflow = _workflow()
    assert workflow.resolve_trusted_intervention_day(
        {"sub-001": 7, "sub-002": "28"}, "sub-001"
    ) == 7
    assert workflow.resolve_trusted_intervention_day(
        json.dumps({"sub-001": 7, "sub-002": "28"}), "sub-002"
    ) == 28

    for config, subject in (
        ({"sub-002": 7}, "sub-001"),
        ({"sub-001": 0}, "sub-001"),
        ({"sub-001": 29}, "sub-001"),
        ({"sub-001": True}, "sub-001"),
        ("not-json", "sub-001"),
    ):
        with pytest.raises(ValueError, match="1.*28|trusted|配置"):
            workflow.resolve_trusted_intervention_day(config, subject)


def test_app_admin_selects_day_but_signed_link_never_uses_unsigned_day():
    source = APP_PATH.read_text(encoding="utf-8")
    assert 'key=f"admin_intervention_day::{safe_subject_id}"' in source
    assert "min_value=1" in source and "max_value=28" in source
    assert "resolve_trusted_intervention_day" in source
    assert 'q.get("day"' not in source
    assert "q.get('day'" not in source
    assert "无法确认本次干预日期，请联系研究团队。" in source


def test_daily_persistence_keeps_only_active_answered_and_removes_stale_safety():
    workflow = _workflow()
    record = _record(day=6)
    record["conditional_details"] = {
        "suicide_thought_frequency_24h": 4,
        "nssi_medical_care_24h": True,
    }
    record["safety_signals"]["daily"] = {
        "suicide_thought_present_24h": True,
        "nssi_medical_care_24h": True,
    }
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
        "nssi_thought_frequency_24h": 4,
        "suicide_thought_frequency_24h": 4,
        "nssi_medical_care_24h": True,
    }
    answered = set(answers)

    filtered = workflow.persist_daily_questionnaire(
        record, answers, answered, current_step=4
    )

    assert filtered == {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }
    assert record["conditional_details"] == {}
    assert record["weekly_extension"] == {}
    assert record["derived_metrics"]["daily"]["nssi_total_count_24h"] == 0
    assert record["safety_signals"]["daily"] == {
        "suicide_thought_present_24h": False
    }
    assert record["completion"]["answered_field_ids"]["daily"] == sorted(filtered)
    assert record["completion"]["current_step"]["daily"] == 4
    assert record["field_status"]["daily"]["nssi_medical_care_24h"] == "not_applicable"


def test_daily_weekly_sicq_scores_only_current_active_answered_values():
    workflow = _workflow()
    record = _record(day=7)
    core = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }
    weekly = {f"sicq_{index}": 0 for index in range(1, 8)}
    answers = {**core, **weekly}
    answered = set(answers)

    workflow.persist_daily_questionnaire(record, answers, answered, current_step=1)

    assert record["weekly_extension"] == weekly
    assert record["derived_metrics"]["weekly_sicq"] == {
        "total": 4,
        "complete": True,
        "scored_items": [0, 0, 0, 0, 0, 0, 4],
    }


def test_formal_persistence_filters_branches_and_unanswered_pss_signal():
    workflow = _workflow()
    record = _record()
    record["safety_signals"]["V1"] = {"pss_positive": True}
    answers = {
        "nssi_ideation_6m_present": False,
        "nssi_ideation_6m_frequency": 6,
        "nssi_ideation_6m_intensity": 5,
        "pss_1": False,
        "pss_2": True,
    }
    answered = {
        "nssi_ideation_6m_present",
        "nssi_ideation_6m_frequency",
        "nssi_ideation_6m_intensity",
        "pss_1",
    }

    filtered = workflow.persist_formal_questionnaire(
        record, "V1", answers, answered, current_step=8
    )

    assert filtered == {"nssi_ideation_6m_present": False, "pss_1": False}
    visit = record["formal_visits"]["V1"]
    assert visit["raw_answers"] == filtered
    assert visit["instruments"]["nssi_ideation"]["raw_answers"] == {
        "nssi_ideation_6m_present": False
    }
    assert visit["instruments"]["pss"]["raw_answers"] == {"pss_1": False}
    assert record["safety_signals"]["V1"] == {"pss_positive": False}
    assert record["field_status"]["V1"]["nssi_ideation_6m_frequency"] == "not_applicable"
    assert record["field_status"]["V1"]["pss_2"] == "missing"
    assert record["completion"]["answered_field_ids"]["V1"] == sorted(filtered)


def test_formal_instrument_payload_has_protocol_metadata_and_defined_score():
    workflow = _workflow()
    record = _record()
    answers = {f"dshi_lifetime_{index}": 1 for index in range(1, 7)}

    workflow.persist_formal_questionnaire(
        record, "V1", answers, set(answers), current_step=6
    )

    payload = record["formal_visits"]["V1"]["instruments"]["dshi_lifetime"]
    assert payload["instrument_id"] == "dshi_lifetime"
    assert payload["version"] == "1.0"
    assert payload["time_window"] == FORMAL_INSTRUMENTS["dshi_lifetime"].time_window
    assert payload["raw_answers"] == answers
    assert payload["scored_answers"] == answers
    assert payload["score"] == {"total": 6, "complete": True}
    assert payload["complete"] is True


def test_questionnaire_answers_restore_only_the_current_visit_sections():
    workflow = _workflow()
    record = _record()
    record["daily_core"] = {"nssi_urge_now": 2}
    record["conditional_details"] = {"nssi_thought_frequency_24h": 3}
    record["weekly_extension"] = {"sicq_1": 1}
    record["formal_visits"]["V3"] = {"raw_answers": {"pss_1": True}}

    assert workflow.questionnaire_answers(record, "daily") == {
        "nssi_urge_now": 2,
        "nssi_thought_frequency_24h": 3,
        "sicq_1": 1,
    }
    assert workflow.questionnaire_answers(record, "V3") == {"pss_1": True}
    assert workflow.questionnaire_answers(record, "V1") == {}


def test_support_signal_uses_only_current_active_answered_values():
    workflow = _workflow()
    assert workflow.support_needed(
        "daily",
        {"suicide_thought_present_24h": True},
        {"suicide_thought_present_24h"},
        6,
    ) is True
    assert workflow.support_needed(
        "daily",
        {
            "suicide_thought_present_24h": False,
            "suicide_thought_frequency_24h": 4,
        },
        {"suicide_thought_present_24h", "suicide_thought_frequency_24h"},
        6,
    ) is False
    assert workflow.support_needed("V1", {"pss_1": True}, set(), 6) is False
    assert workflow.support_needed("V1", {"pss_1": True}, {"pss_1"}, 6) is True


def test_upload_error_copy_separates_failure_from_cleanup_pending(tmp_path):
    workflow = _workflow()
    record_id = "sub-001_20260724_deadbeef"
    participant_error = workflow.upload_failure_message(record_id, participant=True)
    assert record_id in participant_error
    assert "重试" in participant_error

    error = LocalCleanupError(
        tmp_path / "private" / "video.mp4",
        [tmp_path / "private" / "video.mp4", tmp_path / "private" / "record.json"],
    )
    participant_cleanup = workflow.cleanup_pending_message(error, participant=True)
    admin_cleanup = workflow.cleanup_pending_message(error, participant=False)
    assert "上传失败" not in participant_cleanup
    assert "清理" in participant_cleanup
    assert "video.mp4" not in participant_cleanup
    assert "video.mp4" in admin_cleanup and "record.json" in admin_cleanup
    assert str(tmp_path) not in admin_cleanup


def test_app_participant_view_hides_operational_surfaces_and_raw_responses():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    admin_only_blocks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Name)
        and node.test.operand.id == "is_participant"
    ]
    assert admin_only_blocks
    assert any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "json"
        for block in admin_only_blocks
        for call in ast.walk(block)
        if isinstance(call, ast.Call)
    )

    participant_stops = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "is_participant"
    ]
    assert any(
        any(
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
            and call.func.attr == "stop"
            for call in ast.walk(block)
            if isinstance(call, ast.Call)
        )
        for block in participant_stops
    )


def test_app_does_not_save_after_successful_bundle_cleanup():
    source = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    upload_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "upload_record_bundle"
    )
    containing_try = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        and node.lineno <= upload_call.lineno <= node.end_lineno
    )
    save_calls_after_upload = [
        call
        for call in ast.walk(containing_try)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "record_store"
        and call.func.attr == "save"
        and call.lineno > upload_call.lineno
        and call.lineno < containing_try.handlers[0].lineno
    ]
    assert save_calls_after_upload == []


def test_all_formal_visit_specs_are_representable_by_persistence():
    workflow = _workflow()
    for visit, instrument_ids in VISIT_INSTRUMENT_IDS.items():
        record = _record()
        workflow.persist_formal_questionnaire(record, visit, {}, set(), current_step=0)
        assert tuple(record["formal_visits"][visit]["instruments"]) == instrument_ids


def test_admin_record_day_requires_subject_confirmed_selection_before_creation(tmp_path):
    workflow = _workflow()
    store = DailyRecordStore(tmp_path)

    assert workflow.confirm_admin_intervention_day(7, confirmed=False) is None
    assert list(tmp_path.glob("*_state.json")) == []
    assert workflow.confirm_admin_intervention_day(7, confirmed=True) == 7
    created = store.get_or_create("sub-001", date(2026, 7, 24), 7)
    assert created["intervention_day"] == 7
    for value in (0, 29, True, 1.5, "7", "seven"):
        with pytest.raises(ValueError):
            workflow.confirm_admin_intervention_day(value, confirmed=True)


def test_existing_record_day_must_match_confirmed_or_trusted_day():
    workflow = _workflow()

    assert workflow.ensure_record_intervention_day({"intervention_day": 7}, 7) == 7
    with pytest.raises(ValueError):
        workflow.ensure_record_intervention_day({"intervention_day": 1}, 7)


def test_daily_context_seeds_all_scoped_fields_and_draft_persists_them():
    workflow = _workflow()
    record = _record()
    saved_context = {
        "sleep_hours": 6.5,
        "mood_1to9": 3,
        "stress_1to9": 8,
        "pain_0to10": 4,
        "nssi_urge_0to10": 6,
        "coping_effect_1to5": 2,
        "caffeine": "适度",
        "exercise": "少量",
        "tags": ["睡眠"],
        "coping_used": ["运动"],
        "narrative": "saved narrative",
        "triggers": "saved trigger",
    }
    record["daily_context"] = saved_context

    assert workflow.daily_context_values(record) == saved_context
    assert workflow.daily_context_state_keys(record) == {
        field_id: f"daily_context::{record['record_id']}:r3::{field_id}"
        for field_id in saved_context
    }

    workflow.persist_daily_questionnaire(
        record,
        {
            "nssi_thought_present_24h": False,
            "nssi_behavior_present_24h": False,
            "suicide_thought_present_24h": False,
            "nssi_urge_now": 0,
            "nssi_resistance_confidence_now": 7,
        },
        {
            "nssi_thought_present_24h",
            "nssi_behavior_present_24h",
            "suicide_thought_present_24h",
            "nssi_urge_now",
            "nssi_resistance_confidence_now",
        },
        current_step=0,
        daily_context=saved_context,
    )
    assert record["daily_context"] == saved_context


def test_daily_context_defaults_only_fill_missing_persisted_values():
    workflow = _workflow()
    record = _record()
    record["daily_context"] = {"narrative": "keep me", "mood_1to9": 2}

    values = workflow.daily_context_values(record)

    assert values["narrative"] == "keep me"
    assert values["mood_1to9"] == 2
    assert values["sleep_hours"] == 7.0
    assert values["tags"] == []


def test_recording_eligibility_requires_current_marker_safe_file_and_ordered_times(tmp_path):
    workflow = _workflow()
    record_id = "sub-001_20260724_deadbeef"
    video = tmp_path / f"{record_id}.flv"
    video.write_bytes(b"video")

    accepted = workflow.resolve_completed_recording(
        record_id,
        record_id,
        video,
        "2026-07-24T10:00:00",
        "2026-07-24T10:01:00",
        recordings_dir=tmp_path,
        persisted_recording=None,
    )
    assert accepted is not None and accepted.path == video

    for marker, path, started, ended in (
        (None, video, "2026-07-24T10:00:00", "2026-07-24T10:01:00"),
        (record_id, tmp_path / f"{record_id}.mp4", "2026-07-24T10:00:00", "2026-07-24T10:01:00"),
        (record_id, video, "", "2026-07-24T10:01:00"),
        (record_id, video, "not-an-iso-date", "2026-07-24T10:01:00"),
        (record_id, video, "2026-07-24T10:02:00", "2026-07-24T10:01:00"),
    ):
        assert workflow.resolve_completed_recording(
            record_id, marker, path, started, ended,
            recordings_dir=tmp_path, persisted_recording=None,
        ) is None


def test_recording_timestamps_require_full_consistent_iso_datetimes(tmp_path):
    workflow = _workflow()
    record_id = "sub-001_20260724_deadbeef"
    video = tmp_path / f"{record_id}.flv"
    video.write_bytes(b"video")

    def resolve(started: str, ended: str):
        return workflow.resolve_completed_recording(
            record_id, record_id, video, started, ended,
            recordings_dir=tmp_path, persisted_recording=None,
        )

    assert resolve("2026-07-24T10:00:00", "2026-07-24T10:01:00") is not None
    assert resolve(
        "2026-07-24T10:00:00+08:00", "2026-07-24T10:01:00+08:00"
    ) is not None
    for started, ended in (
        ("2026-07-24", "2026-07-25"),
        ("2026-07-24T10:00:00", "2026-07-24T10:01:00+08:00"),
        ("2026-07-24T10:00:00+08:00", "2026-07-24T10:01:00"),
    ):
        assert resolve(started, ended) is None


def test_recording_resume_only_accepts_safe_current_record_basename(tmp_path):
    workflow = _workflow()
    record_id = "sub-001_20260724_deadbeef"
    video = tmp_path / f"{record_id}.mp4"
    video.write_bytes(b"video")
    persisted = {
        "video_filename": video.name,
        "started_at_iso": "2026-07-24T10:00:00",
        "ended_at_iso": "2026-07-24T10:01:00",
        "format": "mp4",
    }

    accepted = workflow.resolve_completed_recording(
        record_id, None, None, None, None,
        recordings_dir=tmp_path, persisted_recording=persisted,
    )
    assert accepted is not None and accepted.path == video

    persisted["video_filename"] = "other_20260724_deadbeef.mp4"
    assert workflow.resolve_completed_recording(
        record_id, None, None, None, None,
        recordings_dir=tmp_path, persisted_recording=persisted,
    ) is None


def test_app_uses_scoped_context_keys_and_recorder_gate_helpers():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    called_names = {
        node.func.id for node in calls if isinstance(node.func, ast.Name)
    }
    assert {"daily_context_state_keys", "daily_context_values", "resolve_completed_recording"} <= called_names
    scoped_fields = {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "context_state_keys"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }
    assert scoped_fields == {
        "sleep_hours", "mood_1to9", "stress_1to9", "pain_0to10",
        "nssi_urge_0to10", "coping_effect_1to5", "caffeine", "exercise",
        "tags", "coping_used", "narrative", "triggers",
    }


def test_app_orders_day_confirmation_recorder_gate_and_draft_context_save():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    top_level = tree.body
    get_record_index = next(
        index
        for index, node in enumerate(top_level)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "record" for target in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "record_store"
        and node.value.func.attr == "get_or_create"
    )
    get_record = top_level[get_record_index]
    confirmation = next(
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "confirm_admin_intervention_day"
    )
    confirmation_button = next(
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "button"
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "确认干预日"
    )
    confirmation_stops = [
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "stop"
        and confirmation_button.lineno < call.lineno < get_record.lineno
    ]
    assert confirmation.lineno < get_record.lineno
    assert confirmation_stops

    validation = top_level[get_record_index + 1]
    assert isinstance(validation, ast.Try)
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "ensure_record_intervention_day"
        for call in ast.walk(validation)
    )

    resolved = next(
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "resolve_completed_recording"
    )
    render = next(
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "render_questionnaire"
    )
    gate = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "completed_recording"
        and len(node.test.ops) == 1
        and isinstance(node.test.ops[0], ast.Is)
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value is None
    )
    assert resolved.lineno < gate.lineno < render.lineno
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "stop"
        for call in ast.walk(gate)
    )

    save_draft = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "save_questionnaire_draft"
    )
    context_assignment = next(
        node for node in ast.walk(save_draft)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "record"
            and isinstance(target.slice, ast.Constant)
            and target.slice.value == "daily_context"
            for target in node.targets
        )
    )
    draft_save = next(
        call for call in ast.walk(save_draft)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "record_store"
        and call.func.attr == "save"
    )
    assert context_assignment.lineno < draft_save.lineno


def test_app_signed_operational_surfaces_follow_participant_stop_guard():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    participant_guard = next(
        node for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "is_participant"
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
            and call.func.attr == "stop"
            for call in ast.walk(node)
        )
    )
    history_subheader = next(
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "subheader"
        and isinstance(call.args[0], ast.Constant)
        and "历史文件上传" in call.args[0].value
    )
    operations_expanders = [
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "expander"
    ]
    assert participant_guard.lineno < history_subheader.lineno
    assert all(participant_guard.lineno < call.lineno for call in operations_expanders)

    admin_only = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Name)
        and node.test.operand.id == "is_participant"
    )
    admin_surface_calls = [
        call for call in ast.walk(admin_only)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr in {"write", "json"}
    ]
    assert {call.func.attr for call in admin_surface_calls} == {"write", "json"}
