import ast
import importlib
import json
from pathlib import Path

import pytest

from questionnaire_specs import FORMAL_INSTRUMENTS, VISIT_INSTRUMENT_IDS
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
    source = APP_PATH.read_text(encoding="utf-8")
    assert 'is_participant = st.session_state.get("auth_source") == "signed_link"' in source
    assert "if not is_participant:" in source
    assert "upload_record_bundle(" in source
    assert "remote_record_dir(" in source
    assert "st.json(record[\"upload\"])" in source
    assert 'with st.expander("使用 & 运维提示")' in source


def test_app_does_not_save_after_successful_bundle_cleanup():
    source = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "upload_record_bundle"
        for call in calls
    )
    marker = "upload_record_bundle("
    success_tail = source[source.index(marker) :]
    success_block = success_tail.split("except LocalCleanupError", 1)[0]
    assert "store.save(record)" not in success_block.split(")", 1)[1]


def test_all_formal_visit_specs_are_representable_by_persistence():
    workflow = _workflow()
    for visit, instrument_ids in VISIT_INSTRUMENT_IDS.items():
        record = _record()
        workflow.persist_formal_questionnaire(record, visit, {}, set(), current_step=0)
        assert tuple(record["formal_visits"][visit]["instruments"]) == instrument_ids
