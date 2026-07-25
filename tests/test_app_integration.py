import ast
import importlib
import json
import os
import stat
import sys
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from link_auth import sign_subject_link
from questionnaire_specs import FORMAL_INSTRUMENTS, VISIT_INSTRUMENT_IDS
from record_store import (
    DailyRecordStore,
    RecordArchivedError,
    RecordConflictError,
    RecordCorruptionError,
    RecordLockError,
)
from upload_workflow import LocalCleanupError, UploadResultError, upload_record_bundle


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
            "questionnaire_visits": {},
        },
        "upload": {"json": "pending", "video": "pending"},
    }


def _visible_app_text(app: AppTest) -> str:
    values = [str(app.main), str(app.sidebar)]
    for collection_name in (
        "title", "header", "subheader", "caption", "markdown", "text",
        "info", "warning", "error", "success", "json", "metric", "code",
        "dataframe", "table", "button", "radio", "slider", "number_input",
        "text_area", "multiselect", "selectbox",
    ):
        for element in getattr(app, collection_name):
            for attribute in ("value", "label", "help", "placeholder"):
                value = getattr(element, attribute, None)
                if value is not None:
                    values.append(str(value))
    return "\n".join(values)


def _is_st_stop(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "st"
        and node.value.func.attr == "stop"
    )


def _participant_history_guard(tree: ast.Module) -> tuple[int, ast.If]:
    for index, node in enumerate(tree.body):
        if not (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "is_participant"
            and node.body
            and _is_st_stop(node.body[-1])
        ):
            continue
        surfaces = [
            call
            for statement in tree.body
            for call in ast.walk(statement)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
            and (
                (
                    call.func.attr == "subheader"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and "历史文件上传" in call.args[0].value
                )
                or call.func.attr == "expander"
            )
        ]
        has_history = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
            and call.func.attr == "subheader"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and "历史文件上传" in call.args[0].value
            for statement in tree.body[index + 1 :]
            for call in ast.walk(statement)
        )
        has_operations = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
            and call.func.attr == "expander"
            for statement in tree.body[index + 1 :]
            for call in ast.walk(statement)
        )
        if (
            has_history
            and has_operations
            and surfaces
            and min(call.lineno for call in surfaces) > node.end_lineno
        ):
            return index, node
    raise AssertionError("history and operations need a top-level participant stop guard")


def _upload_button_branch(tree: ast.Module) -> ast.If:
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Call):
            continue
        call = node.test
        if (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "c1"
            and call.func.attr == "button"
        ):
            return node
    raise AssertionError("upload button branch not found")


def _contains_bundle_upload(node: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "upload_record_bundle"
        for call in ast.walk(node)
    )


def _record_store_saves(nodes: list[ast.stmt]) -> list[ast.Call]:
    return [
        call
        for node in nodes
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "record_store"
        and call.func.attr == "save"
    ]


def _statement_lists(node: ast.AST):
    for _, value in ast.iter_fields(node):
        if isinstance(value, list):
            statements = [item for item in value if isinstance(item, ast.stmt)]
            if statements:
                yield value
            for item in value:
                if isinstance(item, ast.AST):
                    yield from _statement_lists(item)
        elif isinstance(value, ast.AST):
            yield from _statement_lists(value)


def _enclosing_statement_list(
    tree: ast.Module, target: ast.stmt
) -> tuple[list[ast.stmt], int]:
    for statements in _statement_lists(tree):
        for index, statement in enumerate(statements):
            if statement is target:
                return statements, index
    raise AssertionError("enclosing statement list not found")


def _assert_no_success_path_save_after_bundle(tree: ast.Module) -> None:
    branch = _upload_button_branch(tree)
    try_index = next(
        index
        for index, statement in enumerate(branch.body)
        if isinstance(statement, ast.Try) and _contains_bundle_upload(statement)
    )
    upload_try = branch.body[try_index]
    assert isinstance(upload_try, ast.Try)
    upload_index = next(
        index
        for index, statement in enumerate(upload_try.body)
        if _contains_bundle_upload(statement)
    )
    success_reachable = [
        *upload_try.body[upload_index + 1 :],
        *upload_try.orelse,
        *upload_try.finalbody,
        *branch.body[try_index + 1 :],
    ]
    siblings, branch_index = _enclosing_statement_list(tree, branch)
    success_reachable.extend(siblings[branch_index + 1 :])
    assert _record_store_saves(success_reachable) == []


def test_app_visible_titles_use_neutral_product_name():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    titles = [
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "title"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ]

    assert sorted(titles) == sorted(
        [
            "🔒 Physical Stimulation Session Recorder 准入界面",
            "📓 Physical Stimulation Session Recorder",
        ]
    )
    assert all("tavns" not in title.casefold() for title in titles)


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


def test_missing_upload_configuration_uses_only_fixed_redacted_startup_boundary():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    config_guard = next(
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and {
            name.id
            for name in ast.walk(node.test)
            if isinstance(name, ast.Name)
        }
        == {"AK", "SK"}
    )
    participant_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "is_participant"
            for target in node.targets
        )
    )
    assert config_guard.lineno < participant_assignment.lineno

    calls = [node for node in ast.walk(config_guard) if isinstance(node, ast.Call)]
    log_calls = [
        call
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "LOGGER"
    ]
    assert len(log_calls) == 1
    assert log_calls[0].func.attr == "warning"
    assert len(log_calls[0].args) == 1
    assert isinstance(log_calls[0].args[0], ast.Constant)
    assert log_calls[0].args[0].value == "application configuration unavailable"
    assert log_calls[0].keywords == []

    ui_calls = [
        call
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr != "stop"
    ]
    assert len(ui_calls) == 1
    assert ui_calls[0].func.attr == "error"
    assert len(ui_calls[0].args) == 1
    assert isinstance(ui_calls[0].args[0], ast.Constant)
    startup_message = ui_calls[0].args[0].value
    assert startup_message == "应用配置暂不可用，请联系研究团队。"
    for forbidden in (
        "AK",
        "SK",
        "Secrets",
        "config.toml",
        "baidu",
        "app_key",
        "secret_key",
    ):
        assert forbidden not in startup_message
    assert any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "stop"
        for call in calls
    )


def test_refresh_token_rotation_is_log_only_and_redacted():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    ensure_token = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "ensure_token"
    )
    rotation_guard = next(
        node
        for node in ast.walk(ensure_token)
        if isinstance(node, ast.If)
        and any(
            isinstance(operator, ast.NotEq)
            for operator in ast.walk(node.test)
        )
        and any(
            isinstance(value, ast.Constant) and value.value == "refresh_token"
            for value in ast.walk(node.test)
        )
    )

    ui_calls = [
        call
        for call in ast.walk(ensure_token)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
    ]
    assert ui_calls == []

    log_calls = [
        call
        for call in ast.walk(rotation_guard)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "LOGGER"
    ]
    assert len(log_calls) == 1
    assert log_calls[0].func.attr == "warning"
    assert len(log_calls[0].args) == 1
    assert isinstance(log_calls[0].args[0], ast.Constant)
    assert log_calls[0].args[0].value == (
        "baidu refresh token rotated manual_update_required=true"
    )
    assert log_calls[0].keywords == []


def test_try_save_record_calls_store_and_returns_none():
    workflow = _workflow()
    record = _record()
    saved = []

    class Store:
        def save(self, current):
            saved.append(current)

    assert workflow.try_save_record(Store(), record) is None
    assert saved == [record]


@pytest.mark.parametrize(
    "error_type",
    [RecordConflictError, RecordCorruptionError, RecordLockError, OSError],
)
def test_try_save_record_returns_only_expected_exception_type(error_type):
    workflow = _workflow()
    sentinel = r"C:\SENTINEL\private-record.json"

    class Store:
        def save(self, current):
            raise error_type(sentinel)

    result = workflow.try_save_record(Store(), _record())

    assert result == error_type.__name__
    assert "SENTINEL" not in result


def test_try_save_record_does_not_catch_system_exit():
    workflow = _workflow()

    class Store:
        def save(self, current):
            raise SystemExit(2)

    with pytest.raises(SystemExit, match="2"):
        workflow.try_save_record(Store(), _record())


def test_app_routes_participant_record_saves_through_fixed_failure_boundary():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    boundary = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "save_record_or_stop"
        ),
        None,
    )
    assert boundary is not None

    helper_calls = [
        call
        for call in ast.walk(boundary)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "try_save_record"
    ]
    assert len(helper_calls) == 1

    warning_calls = [
        call
        for call in ast.walk(boundary)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "LOGGER"
        and call.func.attr == "warning"
    ]
    assert len(warning_calls) == 1
    warning = warning_calls[0]
    assert len(warning.args) == 4
    assert isinstance(warning.args[0], ast.Constant)
    assert warning.args[0].value == (
        "record save failed record_id=%s stage=%s exception_type=%s"
    )
    record_id_arg = warning.args[1]
    assert isinstance(record_id_arg, ast.Call)
    assert isinstance(record_id_arg.func, ast.Attribute)
    assert isinstance(record_id_arg.func.value, ast.Name)
    assert record_id_arg.func.value.id == "record"
    assert record_id_arg.func.attr == "get"
    assert [arg.value for arg in record_id_arg.args if isinstance(arg, ast.Constant)] == [
        "record_id",
        "unknown",
    ]
    assert isinstance(warning.args[2], ast.Name) and warning.args[2].id == "stage"
    assert (
        isinstance(warning.args[3], ast.Name)
        and warning.args[3].id == "exception_type"
    )
    assert warning.keywords == []

    error_calls = [
        call
        for call in ast.walk(boundary)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "error"
    ]
    assert len(error_calls) == 1
    assert len(error_calls[0].args) == 1
    assert isinstance(error_calls[0].args[0], ast.Constant)
    assert error_calls[0].args[0].value == "记录暂时无法保存，请重试。"
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "stop"
        for call in ast.walk(boundary)
    )

    upload_branch = _upload_button_branch(tree)
    routed_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "save_record_or_stop"
        and call.lineno < upload_branch.lineno
    ]
    assert len(routed_calls) == 3
    stages = {
        keyword.value.value
        for call in routed_calls
        for keyword in call.keywords
        if keyword.arg == "stage"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }
    assert stages == {
        "recording_metadata",
        "questionnaire_draft",
        "questionnaire_completion",
    }
    assert [
        call
        for call in _record_store_saves(tree.body)
        if call.lineno < upload_branch.lineno
    ] == []


def test_app_uses_revision_scoped_questionnaire_state_and_callback_step():
    source = APP_PATH.read_text(encoding="utf-8")
    assert 'state_namespace = f"{record[\'record_id\']}:r{record[\'revision\']}"' in source
    assert "state_keys = questionnaire_state_keys(state_namespace, visit)" in source
    assert "st.session_state.get(state_keys.step" in source
    assert "state_namespace=state_namespace" in source
    assert "initial_answered_field_ids=answered_by_visit.get(visit, [])" in source
    assert "initial_step=step_by_visit.get(visit, 0)" in source


def test_app_controller_uses_canonical_record_date_and_completion_boundaries():
    source = APP_PATH.read_text(encoding="utf-8")

    assert "date.fromisoformat(record[\"record_date\"]).strftime(\"%Y%m%d\")" in source
    assert "upload_ready_for_visit(record, visit)" in source
    assert "mark_questionnaire_visit_complete(record, visit)" in source
    assert "suppress_persisted_resume=" in source
    assert (
        "RecordConflictError" in source
        and "RecordCorruptionError" in source
        and "RecordLockError" in source
    )
    assert "record upload failed record_id=%s stage=upload exception_type=%s" in source


def test_admin_confirmation_is_scoped_to_subject_and_record_date():
    source = APP_PATH.read_text(encoding="utf-8")
    assert "admin_intervention_state_keys(safe_subject_id, record_date)" in source


def test_app_generated_iso_timestamps_are_offset_aware():
    source = APP_PATH.read_text(encoding="utf-8")
    assert "datetime.now().isoformat" not in source
    assert "datetime.now(timezone.utc).isoformat" in source


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
    assert "admin_intervention_state_keys" in source
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
    record["safety_signals"] = {
        "suicide_thought_present_24h": True,
        "nssi_medical_care_24h": True,
        "V1_pss_positive": True,
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
    assert record["safety_signals"] == {
        "suicide_thought_present_24h": False,
        "V1_pss_positive": True,
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
    assert record["derived_metrics"]["sicq_weekly"] == {
        "total": 4,
        "complete": True,
        "scored_items": [0, 0, 0, 0, 0, 0, 4],
    }


def test_formal_persistence_filters_branches_and_unanswered_pss_signal():
    workflow = _workflow()
    record = _record()
    record["safety_signals"]["V1_pss_positive"] = True
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
    assert record["safety_signals"]["V1_pss_positive"] is False
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
    assert payload["instrument_version"] == "1.0"
    assert "version" not in payload
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


def test_questionnaire_completion_is_scoped_to_the_current_visit_and_revision():
    workflow = _workflow()
    record = _record()

    workflow.mark_questionnaire_visit_complete(record, "daily")

    assert workflow.questionnaire_visit_complete(record, "daily") is True
    assert workflow.questionnaire_visit_complete(record, "V1") is False
    record["revision"] += 1
    assert workflow.questionnaire_visit_complete(record, "daily") is False


def test_completion_sets_top_level_complete_and_persists_upload_ready_after_reload(tmp_path):
    workflow = _workflow()
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }
    workflow.persist_daily_questionnaire(record, answers, set(answers), current_step=4)
    workflow.mark_questionnaire_visit_complete(record, "daily")
    store.save(record)

    reloaded = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)
    assert reloaded["completion"]["status"] == "complete"
    assert workflow.upload_ready_for_visit(reloaded, "daily") is True


def test_persisted_positive_safety_survives_reload_and_upload_ready_retry(tmp_path):
    workflow = _workflow()
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": True,
        "suicide_thought_frequency_24h": 2,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }
    workflow.persist_daily_questionnaire(record, answers, set(answers), current_step=4)
    workflow.mark_questionnaire_visit_complete(record, "daily")
    store.save(record)

    reloaded = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)
    assert workflow.upload_ready_for_visit(reloaded, "daily") is True
    assert workflow.persisted_support_needed(reloaded, "daily") is True


def test_persisted_formal_pss_support_survives_reload_and_upload_ready_retry(tmp_path):
    workflow = _workflow()
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)
    workflow.persist_formal_questionnaire(
        record, "V1", {"pss_1": True}, {"pss_1"}, current_step=1
    )
    workflow.mark_questionnaire_visit_complete(record, "V1")
    store.save(record)

    reloaded = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)
    assert workflow.upload_ready_for_visit(reloaded, "V1") is True
    assert workflow.persisted_support_needed(reloaded, "V1") is True


def test_daily_safety_uses_canonical_suicide_frequency_and_medical_keys():
    workflow = _workflow()
    record = _record(day=6)
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": True,
        "nssi_medical_care_24h": True,
        "suicide_thought_present_24h": True,
        "suicide_thought_frequency_24h": 3,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }
    workflow.persist_daily_questionnaire(record, answers, set(answers), current_step=4)
    assert record["safety_signals"] == {
        "suicide_thought_present_24h": True,
        "suicide_thought_frequency_24h": 3,
        "medical_care_required_24h": True,
    }

    answers["nssi_behavior_present_24h"] = False
    answers["suicide_thought_present_24h"] = False
    workflow.persist_daily_questionnaire(record, answers, set(answers), current_step=4)
    assert record["safety_signals"] == {"suicide_thought_present_24h": False}


def test_daily_safety_preserves_explicit_false_for_an_active_medical_branch():
    workflow = _workflow()
    record = _record(day=6)
    answers = {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": True,
        "nssi_medical_care_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 7,
    }

    workflow.persist_daily_questionnaire(record, answers, set(answers), current_step=4)

    assert record["safety_signals"]["medical_care_required_24h"] is False
    assert "nssi_medical_care_24h" not in record["safety_signals"]


def test_archived_uploaded_record_uses_the_completed_lifecycle_policy(tmp_path):
    workflow = _workflow()
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)
    record["completion"]["status"] = "complete"
    record["completion"]["questionnaire_visits"] = {
        "daily": {"status": "complete", "revision": 1}
    }
    record["upload"] = {"json": "uploaded", "video": "uploaded"}
    store.save(record)
    store.path_for(record).unlink()

    with pytest.raises(RecordArchivedError) as raised:
        store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)

    assert workflow.archived_record_is_completed(raised.value, 6, "daily") is True
    assert workflow.archived_record_is_completed(raised.value, 6, "V1") is False
    assert workflow.archived_record_is_completed(raised.value, 7, "daily") is False
    assert workflow.archived_record_success_message(raised.value, 6, "daily") == (
        f"本次记录已完成（记录编号：{record['record_id']}）。"
    )
    assert workflow.archived_record_success_message(raised.value, 6, "V1") is None
    assert workflow.archived_record_success_message(raised.value, 7, "daily") is None
    assert workflow.archived_record_success_message(raised.value, 6, "unknown") is None
    assert workflow.archived_record_success_message(raised.value, 6, None) is None


def test_archived_complete_record_without_the_requested_completed_visit_fails_closed(tmp_path):
    workflow = _workflow()
    store = DailyRecordStore(tmp_path)
    record = store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)
    record["completion"]["status"] = "complete"
    record["completion"]["questionnaire_visits"] = {}
    record["upload"] = {"json": "uploaded", "video": "uploaded"}
    store.save(record)
    store.path_for(record).unlink()

    with pytest.raises(RecordArchivedError) as raised:
        store.get_or_create("sub-001", date(2026, 7, 24), intervention_day=6)

    assert workflow.archived_record_success_message(raised.value, 6, "daily") is None


def test_admin_day_state_keys_are_isolated_by_subject_and_date():
    workflow = _workflow()
    first = workflow.admin_intervention_state_keys("sub-001", date(2026, 7, 24))
    second = workflow.admin_intervention_state_keys("sub-001", date(2026, 7, 25))
    assert first != second
    assert "2026-07-24" in first.selection and "2026-07-24" in first.confirmation
    assert "2026-07-25" in second.selection and "2026-07-25" in second.confirmation


def test_upload_readiness_survives_retry_but_not_an_incomplete_sibling_visit():
    workflow = _workflow()
    record = _record()

    workflow.mark_questionnaire_visit_complete(record, "daily")

    assert workflow.upload_ready_for_visit(record, "daily") is True
    assert workflow.upload_ready_for_visit(record, "V1") is False
    assert workflow.upload_ready_for_visit(record, "daily") is True


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


def test_uploaded_cleanup_recovery_requires_missing_video_and_preserves_retained_copy(
    tmp_path,
):
    workflow = _workflow()
    record = _record()
    record["upload"] = {"json": "uploaded", "video": "uploaded"}
    record["recording"] = {
        "video_filename": f"{record['record_id']}.mp4",
        "started_at_iso": "2026-07-24T10:00:00+00:00",
        "ended_at_iso": "2026-07-24T10:01:00+00:00",
        "format": "mp4",
    }
    json_path = tmp_path / f"{record['record_id']}_r3_state.json"
    json_path.write_text("{}", encoding="utf-8")
    video_path = tmp_path / record["recording"]["video_filename"]
    video_path.write_bytes(b"retained administrator copy")

    record["local_cleanup"] = {"requested": False, "status": "retained"}
    assert workflow.uploaded_cleanup_recovery(
        record, json_path=json_path, recordings_dir=tmp_path
    ) is None

    record["local_cleanup"] = {"requested": True, "status": "pending"}
    assert workflow.uploaded_cleanup_recovery(
        record, json_path=json_path, recordings_dir=tmp_path
    ) is None

    record["local_cleanup"] = {"requested": True, "status": "ready"}
    requested_recovery = workflow.uploaded_cleanup_recovery(
        record, json_path=json_path, recordings_dir=tmp_path
    )
    assert requested_recovery is not None
    assert requested_recovery.video_path == video_path

    record.pop("local_cleanup")
    assert workflow.uploaded_cleanup_recovery(
        record, json_path=json_path, recordings_dir=tmp_path
    ) is None

    video_path.unlink()
    legacy_recovery = workflow.uploaded_cleanup_recovery(
        record, json_path=json_path, recordings_dir=tmp_path
    )
    assert legacy_recovery is not None
    record["local_cleanup"] = {"requested": False, "status": "retained"}
    assert workflow.uploaded_cleanup_recovery(
        record, json_path=json_path, recordings_dir=tmp_path
    ) is None
    record["local_cleanup"] = {"requested": True, "status": "pending"}
    assert workflow.uploaded_cleanup_recovery(
        record, json_path=json_path, recordings_dir=tmp_path
    ) is None
    record["local_cleanup"] = {"requested": True, "status": "ready"}
    recovery = workflow.uploaded_cleanup_recovery(
        record, json_path=json_path, recordings_dir=tmp_path
    )
    assert recovery is not None
    assert recovery.json_path == json_path
    assert recovery.video_path == video_path
    assert set(recovery.cleanup_paths) == {
        tmp_path / f"{record['record_id']}.flv",
    }

    record["upload"] = {"json": "uploaded", "video": "failed"}
    assert workflow.uploaded_cleanup_recovery(
        record, json_path=json_path, recordings_dir=tmp_path
    ) is None


def test_failed_final_json_state_persist_never_authorizes_pending_cleanup(tmp_path):
    workflow = _workflow()
    record = _record()
    record["upload"] = {"json": "pending", "video": "pending"}
    record["local_cleanup"] = {"requested": True, "status": "pending"}
    video_path = tmp_path / f"{record['record_id']}.mp4"
    video_path.write_bytes(b"video")
    record["recording"] = {
        "video_filename": video_path.name,
        "started_at_iso": "2026-07-24T10:00:00+00:00",
        "ended_at_iso": "2026-07-24T10:01:00+00:00",
        "format": "mp4",
    }
    json_path = tmp_path / f"{record['record_id']}_r3_state.json"
    json_path.write_text(json.dumps(record), encoding="utf-8")
    uploads = 0

    def upload(local_path, remote_path, *, progress_cb):
        nonlocal uploads
        uploads += 1
        if uploads == 3:
            raise RuntimeError("final JSON failed")

    def persist(state):
        if state["json"] == "failed":
            raise OSError("failed-state persist failed")
        record["upload"] = dict(state)
        json_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(OSError, match="failed-state persist failed"):
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            upload,
            persist_state=persist,
            delete_after_upload=True,
        )

    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted["upload"] == {"json": "uploaded", "video": "uploaded"}
    assert persisted["local_cleanup"] == {"requested": True, "status": "pending"}
    assert workflow.uploaded_cleanup_recovery(
        persisted, json_path=json_path, recordings_dir=tmp_path
    ) is None
    assert json_path.exists()
    assert video_path.exists()


def test_ready_confirmation_survives_cleanup_failure_for_refresh_recovery(
    tmp_path, monkeypatch
):
    workflow = _workflow()
    record = _record()
    record["upload"] = {"json": "pending", "video": "pending"}
    workflow.set_local_cleanup_intent(record, requested=True)
    video_path = tmp_path / f"{record['record_id']}.mp4"
    video_path.write_bytes(b"video")
    raw_path = tmp_path / f"{record['record_id']}.flv"
    raw_path.write_bytes(b"raw")
    record["recording"] = {
        "video_filename": video_path.name,
        "started_at_iso": "2026-07-24T10:00:00+00:00",
        "ended_at_iso": "2026-07-24T10:01:00+00:00",
        "format": "mp4",
    }
    json_path = tmp_path / f"{record['record_id']}_r3_state.json"
    json_path.write_text(json.dumps(record), encoding="utf-8")
    original_unlink = Path.unlink

    def persist(state):
        record["upload"] = dict(state)
        json_path.write_text(json.dumps(record), encoding="utf-8")

    def confirm_ready():
        workflow.mark_local_cleanup_ready(record)
        json_path.write_text(json.dumps(record), encoding="utf-8")

    def fail_raw_cleanup(path, *args, **kwargs):
        if path == raw_path:
            raise PermissionError("raw is busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_raw_cleanup)
    with pytest.raises(LocalCleanupError) as captured:
        upload_record_bundle(
            json_path,
            video_path,
            "/remote/record",
            lambda *args, **kwargs: None,
            persist_state=persist,
            delete_after_upload=True,
            cleanup_paths=(raw_path,),
            confirm_final_sync=confirm_ready,
        )

    assert captured.value.failed_path == raw_path
    assert isinstance(captured.value.__cause__, PermissionError)
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted["local_cleanup"] == {"requested": True, "status": "ready"}
    recovery = workflow.uploaded_cleanup_recovery(
        persisted, json_path=json_path, recordings_dir=tmp_path
    )
    assert recovery is not None
    assert recovery.json_path == json_path
    assert recovery.video_path == video_path


def test_local_cleanup_intent_is_separate_from_upload_state():
    workflow = _workflow()
    record = _record()

    assert workflow.set_local_cleanup_intent(record, requested=True) == {
        "requested": True,
        "status": "pending",
    }
    assert record["upload"] == {"json": "pending", "video": "pending"}
    assert workflow.set_local_cleanup_intent(record, requested=False) == {
        "requested": False,
        "status": "retained",
    }


def test_local_cleanup_ready_requires_requested_pending_and_is_idempotent():
    workflow = _workflow()
    record = _record()

    workflow.set_local_cleanup_intent(record, requested=True)
    assert workflow.mark_local_cleanup_ready(record) == {
        "requested": True,
        "status": "ready",
    }
    assert workflow.mark_local_cleanup_ready(record) == {
        "requested": True,
        "status": "ready",
    }

    workflow.set_local_cleanup_intent(record, requested=False)
    with pytest.raises(ValueError, match="not requested"):
        workflow.mark_local_cleanup_ready(record)
    assert record["local_cleanup"] == {"requested": False, "status": "retained"}


def test_app_persists_cleanup_intent_before_bundle_upload():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    calls = [call for call in ast.walk(tree) if isinstance(call, ast.Call)]
    intent_call = next(
        call
        for call in calls
        if isinstance(call.func, ast.Name)
        and call.func.id == "set_local_cleanup_intent"
    )
    bundle_call = next(
        call
        for call in calls
        if isinstance(call.func, ast.Name) and call.func.id == "upload_record_bundle"
    )
    saves_between = [
        call
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "record_store"
        and call.func.attr == "save"
        and intent_call.lineno < call.lineno < bundle_call.lineno
    ]
    assert intent_call.lineno < bundle_call.lineno
    assert saves_between


def test_app_confirms_local_cleanup_ready_after_final_remote_json():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    confirmation = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "confirm_local_cleanup_ready"
    )
    called_names = {
        call.func.id
        for call in ast.walk(confirmation)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    bundle_call = next(
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "upload_record_bundle"
    )

    assert "mark_local_cleanup_ready" in called_names
    assert any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "record_store"
        and call.func.attr == "save"
        for call in ast.walk(confirmation)
        if isinstance(call, ast.Call)
    )
    assert any(
        keyword.arg == "confirm_final_sync"
        and isinstance(keyword.value, ast.IfExp)
        for keyword in bundle_call.keywords
    )


def test_app_runs_cleanup_only_recovery_before_constructing_recorder():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    calls = [call for call in ast.walk(tree) if isinstance(call, ast.Call)]
    recovery_call = next(
        call
        for call in calls
        if isinstance(call.func, ast.Name)
        and call.func.id == "uploaded_cleanup_recovery"
    )
    cleanup_call = next(
        call
        for call in calls
        if isinstance(call.func, ast.Name)
        and call.func.id == "cleanup_uploaded_bundle"
    )
    recorder_call = next(
        call
        for call in calls
        if isinstance(call.func, ast.Name) and call.func.id == "webrtc_streamer"
    )

    assert recovery_call.lineno < cleanup_call.lineno < recorder_call.lineno


def test_app_participant_view_hides_operational_surfaces_and_raw_responses():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    guard_index, participant_guard = _participant_history_guard(tree)
    assert guard_index + 1 < len(tree.body)
    assert _is_st_stop(participant_guard.body[-1])
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

    mutated = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    del mutated.body[guard_index]
    with pytest.raises(AssertionError):
        _participant_history_guard(mutated)


def test_production_participant_visible_tree_omits_sensitive_record_payload(
    tmp_path, monkeypatch
):
    sentinel = "PRODUCTION-PARTICIPANT-PRIVATE-7F31"
    record = _record(day=7)
    record.update(
        {
            "derived_metrics": {"participant_score": f"{sentinel}:score"},
            "safety_signals": {"risk_level": f"{sentinel}:risk"},
            "remote_path": f"/remote/{sentinel}",
            "local_path": str(tmp_path / sentinel / "record.mp4"),
            "raw_upload_response": {"request_id": f"{sentinel}:response"},
            "upload_history": [f"{sentinel}:history"],
            "operations": f"{sentinel}:operations",
        }
    )

    class FakeStore:
        def __init__(self, root):
            self.root = Path(root)

        def get_or_create(self, subject_id, record_date, intervention_day):
            return json.loads(json.dumps(record))

        def path_for(self, current):
            return self.root / f"{current['record_id']}_r3_state.json"

        def save(self, current):
            raise AssertionError("active recorder participant run must not save")

    monkeypatch.setattr("record_store.DailyRecordStore", FakeStore)
    monkeypatch.setattr(
        "streamlit_webrtc.webrtc_streamer",
        lambda *args, **kwargs: SimpleNamespace(
            state=SimpleNamespace(playing=True)
        ),
    )
    key = "production-app-test-key"
    expiry = int(time.time()) + 3600
    main_module = sys.modules["__main__"]
    missing = object()
    original_main_file = getattr(main_module, "__file__", missing)
    try:
        app = AppTest.from_file(str(APP_PATH), default_timeout=10)
        app.secrets["baidu"] = {
            "app_key": "fake-app-key",
            "secret_key": "fake-secret-key",
            "save_dir": "/apps/test",
        }
        app.secrets["LINK_SIGNING_KEY"] = key
        app.secrets["TRUSTED_INTERVENTION_DAYS"] = {"sub-001": 7}
        app.query_params["sid"] = "sub-001"
        app.query_params["exp"] = str(expiry)
        app.query_params["sig"] = sign_subject_link(key, "sub-001", expiry)
        app.query_params["visit"] = "daily"
        app.run()

        assert not app.exception
        visible = _visible_app_text(app)
        for forbidden in (
            f"{sentinel}:score",
            f"{sentinel}:risk",
            f"/remote/{sentinel}",
            str(tmp_path / sentinel),
            f"{sentinel}:response",
            f"{sentinel}:history",
            f"{sentinel}:operations",
        ):
            assert forbidden not in visible
    finally:
        current_main_module = sys.modules["__main__"]
        if original_main_file is missing:
            if hasattr(current_main_module, "__file__"):
                delattr(current_main_module, "__file__")
        else:
            current_main_module.__file__ = original_main_file


def test_app_does_not_save_after_successful_bundle_cleanup():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    _assert_no_success_path_save_after_bundle(tree)

    mutated = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    branch = _upload_button_branch(mutated)
    branch.body.append(
        ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="record_store"), attr="save"
                ),
                args=[ast.Name(id="record")],
                keywords=[],
            )
        )
    )
    with pytest.raises(AssertionError):
        _assert_no_success_path_save_after_bundle(mutated)

    sibling_mutation = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    sibling_branch = _upload_button_branch(sibling_mutation)
    siblings, branch_index = _enclosing_statement_list(sibling_mutation, sibling_branch)
    siblings.insert(
        branch_index + 1,
        ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="record_store"), attr="save"
                ),
                args=[ast.Name(id="record")],
                keywords=[],
            )
        ),
    )
    with pytest.raises(AssertionError):
        _assert_no_success_path_save_after_bundle(sibling_mutation)


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


def test_recording_context_projection_excludes_transient_state_payload_fields():
    workflow = _workflow()
    payload = {
        **workflow.DAILY_CONTEXT_DEFAULTS,
        "timestamp_client_open_iso": "2026-07-24T10:00:00+00:00",
        "schema_version": 3,
        "subject_id": "sub-001",
    }

    assert workflow.recording_context(payload) == workflow.DAILY_CONTEXT_DEFAULTS


def test_recording_eligibility_requires_current_marker_safe_file_and_ordered_times(tmp_path):
    workflow = _workflow()
    record_id = "sub-001_20260724_deadbeef"
    video = tmp_path / f"{record_id}.flv"
    video.write_bytes(b"video")

    accepted = workflow.resolve_completed_recording(
        record_id,
        record_id,
        video,
        "2026-07-24T10:00:00+00:00",
        "2026-07-24T10:01:00+00:00",
        recordings_dir=tmp_path,
        persisted_recording=None,
    )
    assert accepted is not None and accepted.path == video

    for marker, path, started, ended in (
        (None, video, "2026-07-24T10:00:00+00:00", "2026-07-24T10:01:00+00:00"),
        (record_id, tmp_path / f"{record_id}.mp4", "2026-07-24T10:00:00+00:00", "2026-07-24T10:01:00+00:00"),
        (record_id, video, "", "2026-07-24T10:01:00+00:00"),
        (record_id, video, "not-an-iso-date", "2026-07-24T10:01:00+00:00"),
        (record_id, video, "2026-07-24T10:02:00+00:00", "2026-07-24T10:01:00+00:00"),
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

    normalized = resolve(
        "2026-07-24T10:00:00+08:00", "2026-07-24T10:01:00+08:00"
    )
    assert normalized is not None
    assert normalized.started_at_iso == "2026-07-24T02:00:00+00:00"
    assert normalized.ended_at_iso == "2026-07-24T02:01:00+00:00"
    for started, ended in (
        ("2026-07-24T10:00:00", "2026-07-24T10:01:00"),
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
        "started_at_iso": "2026-07-24T10:00:00+00:00",
        "ended_at_iso": "2026-07-24T10:01:00+00:00",
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


def test_recording_path_rejects_symlinks_hardlinks_and_rerecord_resume_suppression(tmp_path):
    workflow = _workflow()
    record_id = "sub-001_20260724_deadbeef"
    video = tmp_path / f"{record_id}.mp4"
    video.write_bytes(b"video")
    persisted = {
        "video_filename": video.name,
        "started_at_iso": "2026-07-24T10:00:00+00:00",
        "ended_at_iso": "2026-07-24T10:01:00+00:00",
        "format": "mp4",
    }

    assert workflow.resolve_completed_recording(
        record_id, None, None, None, None,
        recordings_dir=tmp_path, persisted_recording=persisted,
        suppress_persisted_resume=True,
    ) is None

    hardlink = tmp_path / "source.mp4"
    hardlink.write_bytes(b"video")
    video.unlink()
    os.link(hardlink, video)
    assert workflow.resolve_completed_recording(
        record_id, None, None, None, None,
        recordings_dir=tmp_path, persisted_recording=persisted,
    ) is None


def test_historical_upload_rejects_hardlink_before_callback_without_path_leak(
    tmp_path,
):
    workflow = _workflow()
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    external = tmp_path / "external-video.mp4"
    external.write_bytes(b"external")
    candidate = recordings_dir / "history.mp4"
    os.link(external, candidate)
    calls = []

    with pytest.raises(workflow.UnsafeRecordingPathError) as captured:
        workflow.upload_trusted_recording(
            candidate,
            recordings_dir=recordings_dir,
            remote_path="/remote/history.mp4",
            upload_fn=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []
    assert str(external) not in str(captured.value)
    assert str(candidate) not in str(captured.value)
    assert workflow.trusted_recording_path(candidate, recordings_dir) is None


def test_historical_upload_rejects_symlink_before_callback_when_supported(tmp_path):
    workflow = _workflow()
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    external = tmp_path / "external-video.mp4"
    external.write_bytes(b"external")
    candidate = recordings_dir / "history.mp4"
    try:
        candidate.symlink_to(external)
    except OSError:
        pytest.skip("symlink creation is not permitted in this environment")
    calls = []

    with pytest.raises(workflow.UnsafeRecordingPathError) as captured:
        workflow.upload_trusted_recording(
            candidate,
            recordings_dir=recordings_dir,
            remote_path="/remote/history.mp4",
            upload_fn=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []
    assert str(external) not in str(captured.value)
    assert str(candidate) not in str(captured.value)


def test_historical_upload_uses_private_snapshot_when_source_is_swapped(tmp_path):
    workflow = _workflow()
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    candidate = recordings_dir / "history.mp4"
    candidate.write_bytes(b"ORIGINAL-VIDEO")
    outside = tmp_path / "outside-secret.mp4"
    outside.write_bytes(b"SECRET-OUTSIDE")
    observed = {}

    def swap_then_read(snapshot, remote_path, *, progress_cb):
        candidate.unlink()
        os.link(outside, candidate)
        observed["path"] = snapshot
        observed["bytes"] = snapshot.read_bytes()
        observed["mode"] = stat.S_IMODE(os.lstat(snapshot).st_mode)
        return {"ok": True}

    result = workflow.upload_trusted_recording(
        candidate,
        recordings_dir=recordings_dir,
        remote_path="/remote/history.mp4",
        upload_fn=swap_then_read,
    )

    assert result == {"ok": True}
    assert observed["path"] != candidate
    assert observed["path"].parent != recordings_dir
    assert observed["bytes"] == b"ORIGINAL-VIDEO"
    assert observed["mode"] & 0o600 == 0o600
    assert not observed["path"].exists()
    assert candidate.read_bytes() == b"SECRET-OUTSIDE"


def test_historical_upload_reports_incomplete_cleanup_when_source_is_swapped(
    tmp_path,
):
    workflow = _workflow()
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    candidate = recordings_dir / "history.mp4"
    candidate.write_bytes(b"ORIGINAL-VIDEO")
    outside = tmp_path / "outside-secret.mp4"
    outside.write_bytes(b"SECRET-OUTSIDE")

    def swap_after_snapshot(snapshot, remote_path, *, progress_cb):
        candidate.unlink()
        os.link(outside, candidate)
        assert snapshot.read_bytes() == b"ORIGINAL-VIDEO"
        return {"ok": True}

    with pytest.raises(LocalCleanupError) as captured:
        workflow.upload_trusted_recording(
            candidate,
            recordings_dir=recordings_dir,
            remote_path="/remote/history.mp4",
            upload_fn=swap_after_snapshot,
            delete_after_upload=True,
        )

    assert captured.value.failed_path == candidate
    assert captured.value.remaining_paths == (candidate,)
    assert candidate.read_bytes() == b"SECRET-OUTSIDE"


def test_historical_video_delete_waits_for_selected_metadata_success(tmp_path):
    workflow = _workflow()
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    candidate = recordings_dir / "history.mp4"
    candidate.write_bytes(b"ORIGINAL-VIDEO")

    def fail_metadata(_video_result):
        raise UploadResultError("metadata upload failed")

    with pytest.raises(UploadResultError, match="metadata upload failed"):
        workflow.upload_trusted_recording(
            candidate,
            recordings_dir=recordings_dir,
            remote_path="/remote/history.mp4",
            upload_fn=lambda *args, **kwargs: {"ok": True},
            delete_after_upload=True,
            after_upload_success=fail_metadata,
        )

    assert candidate.read_bytes() == b"ORIGINAL-VIDEO"


def test_app_historical_video_cleanup_stays_inside_trusted_upload_boundary():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    trusted_upload = next(
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "upload_trusted_recording"
    )

    assert any(
        keyword.arg == "delete_after_upload"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "delete_after_upload_hist"
        for keyword in trusted_upload.keywords
    )
    assert not any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "picked"
        and call.func.attr == "unlink"
        for call in ast.walk(tree)
    )


def test_app_historical_state_json_uses_generated_private_upload_only():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    calls = [call for call in ast.walk(tree) if isinstance(call, ast.Call)]

    assert any(
        isinstance(call.func, ast.Name)
        and call.func.id == "upload_generated_json"
        for call in calls
    )
    assert not any(
        isinstance(node, ast.Name) and node.id == "meta_path2"
        for node in ast.walk(tree)
    )


def test_trusted_recording_files_skips_races_and_unsafe_entries(tmp_path, monkeypatch):
    workflow = _workflow()
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    older = recordings_dir / "older.mp4"
    newer = recordings_dir / "newer.flv"
    vanishing = recordings_dir / "vanishing.mp4"
    outside = tmp_path / "outside.mp4"
    older.write_bytes(b"older")
    newer.write_bytes(b"newer")
    vanishing.write_bytes(b"vanishing")
    outside.write_bytes(b"outside")
    os.link(outside, recordings_dir / "hardlink.mp4")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))
    original_validator = workflow.trusted_recording_path

    def remove_after_validation(candidate, root):
        result = original_validator(candidate, root)
        if candidate == vanishing and result is not None:
            candidate.unlink()
        return result

    monkeypatch.setattr(workflow, "trusted_recording_path", remove_after_validation)
    files = workflow.trusted_recording_files(recordings_dir)

    assert files == (newer, older)


def test_app_uses_race_safe_history_enumeration_and_redacted_failure_copy():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    called_names = {
        call.func.id
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert "trusted_recording_files" in called_names

    upload_try = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        and any(
            isinstance(call.func, ast.Name)
            and call.func.id == "upload_trusted_recording"
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        )
    )
    error_calls = [
        call
        for handler in upload_try.handlers
        for call in ast.walk(handler)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "error"
    ]
    assert error_calls
    assert all(
        call.args and isinstance(call.args[0], ast.Constant)
        for call in error_calls
    )
    log_calls = [
        call
        for handler in upload_try.handlers
        for call in ast.walk(handler)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "LOGGER"
        and call.func.attr == "warning"
    ]
    assert log_calls
    assert any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "picked"
        and node.attr == "name"
        for call in log_calls
        for node in ast.walk(call)
    )


def test_app_filters_and_revalidates_historical_recordings_with_shared_validator():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    called_names = {
        call.func.id
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert "trusted_recording_files" in called_names
    assert "upload_trusted_recording" in called_names


def test_remote_directory_uses_a_real_store_record_date_key(tmp_path):
    from record_store import remote_record_dir

    record = DailyRecordStore(tmp_path).get_or_create(
        "sub-001", date(2026, 7, 24), intervention_day=7
    )
    remote_dir = remote_record_dir(
        "/apps/collector",
        record["subject_id"],
        date.fromisoformat(record["record_date"]).strftime("%Y%m%d"),
        record["record_id"],
    )

    assert remote_dir.endswith(f"/sub-001/20260724/{record['record_id']}")


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
        if isinstance(node, ast.Try)
        and any(
            isinstance(assignment, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "record"
                for target in assignment.targets
            )
            and isinstance(assignment.value, ast.Call)
            and isinstance(assignment.value.func, ast.Attribute)
            and isinstance(assignment.value.func.value, ast.Name)
            and assignment.value.func.value.id == "record_store"
            and assignment.value.func.attr == "get_or_create"
            for assignment in ast.walk(node)
        )
    )
    get_record = top_level[get_record_index]
    visit_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "visit" for target in node.targets)
    ]
    assert visit_assignments
    assert all(node.lineno < get_record.lineno for node in visit_assignments)
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
        and isinstance(call.func, ast.Name)
        and call.func.id == "save_record_or_stop"
    )
    assert context_assignment.lineno < draft_save.lineno
    assert any(
        keyword.arg == "stage"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value == "questionnaire_draft"
        for keyword in draft_save.keywords
    )


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
    assert any(
        call.func.attr == "write"
        and any(isinstance(node, ast.Name) and node.id == "remote_dir" for node in ast.walk(call))
        for call in admin_surface_calls
    )
    assert any(
        call.func.attr == "json"
        and isinstance(call.args[0], ast.Subscript)
        and isinstance(call.args[0].value, ast.Name)
        and call.args[0].value.id == "record"
        and isinstance(call.args[0].slice, ast.Constant)
        and call.args[0].slice.value == "upload"
        for call in admin_surface_calls
    )
