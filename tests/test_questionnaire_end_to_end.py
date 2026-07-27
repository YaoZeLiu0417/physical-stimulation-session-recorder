import ast
from datetime import date
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import openpyxl
import pytest
from streamlit.testing.v1 import AppTest

from questionnaire_specs import (
    DAILY_CONDITIONAL,
    DAILY_CORE,
    FORMAL_INSTRUMENTS,
    VISIT_INSTRUMENT_IDS,
    WEEKLY_INSTRUMENTS,
)
from questionnaire_ui import build_flow, formal_flow, questionnaire_state_keys
from session_record_workflow import (
    create_session_record,
    mark_questionnaire_visit_complete,
    persist_daily_questionnaire,
    persist_formal_questionnaire,
    questionnaire_answers,
    questionnaire_visit_complete,
)


FIXTURE = Path(__file__).parent / "fixtures" / "questionnaire_app.py"
RECORD_DATE = date(2026, 7, 27)
SUBJECT_ID = "sub-001"
TOKEN = "01abcdef"
CREATED_AT_ISO = "2026-07-27T10:00:00+00:00"
COMPLETED_AT_ISO = "2026-07-27T10:15:00+00:00"
EXPORTED_AT_ISO = "2026-07-27T10:30:00+00:00"
SESSION_RECORD_KEY = "session_record"
SESSION_EXPORT_KEY = "session_export"
SESSION_NAMESPACE = "fixture-record"
RECORDING_KEYS = (
    "version",
    "storage",
    "status",
    "mode",
    "duration_seconds",
    "camera_ready",
    "microphone_ready",
    "saved_confirmed",
)


def _negative_daily_answers() -> dict[str, object]:
    return {
        "nssi_thought_present_24h": False,
        "nssi_behavior_present_24h": False,
        "suicide_thought_present_24h": False,
        "nssi_urge_now": 0,
        "nssi_resistance_confidence_now": 0,
    }


def _raw_value(question, *, positive: bool) -> object:
    if question.kind == "boolean":
        return positive
    if question.kind == "slider":
        return question.max_value if positive else question.min_value
    if question.kind == "integer":
        return question.min_value
    if question.kind == "multiselect":
        return list(question.options[:2]) if positive else []
    if question.kind == "text":
        return f"raw:{question.id}" if positive else ""
    raise AssertionError(f"unsupported question kind: {question.kind}")


def _positive_daily_answers() -> dict[str, object]:
    questions = (*DAILY_CORE, *DAILY_CONDITIONAL)
    answers = {
        question.id: _raw_value(question, positive=True)
        for question in questions
    }
    first_count = next(
        question.id for question in DAILY_CONDITIONAL if question.kind == "integer"
    )
    answers[first_count] = 1
    return answers


def _weekly_questions():
    return tuple(
        question
        for instrument in WEEKLY_INSTRUMENTS
        for question in instrument.questions
    )


def _formal_questions(visit: str):
    return tuple(
        question
        for instrument_id in VISIT_INSTRUMENT_IDS[visit]
        for question in FORMAL_INSTRUMENTS[instrument_id].questions
    )


def _recording(status: str = "saved") -> dict[str, object]:
    saved = status == "saved"
    return {
        "version": 2,
        "storage": "browser_local",
        "status": status,
        "mode": "long" if saved else "demo",
        "duration_seconds": 60 if saved else 0,
        "camera_ready": saved,
        "microphone_ready": saved,
        "saved_confirmed": saved,
    }


def _new_record(
    *, day: int = 1, visit: str = "daily", recording_status: str = "saved"
) -> dict[str, object]:
    record = create_session_record(
        SUBJECT_ID,
        RECORD_DATE,
        day,
        visit,
        token=TOKEN,
        now_iso=CREATED_AT_ISO,
    )
    record["recording"] = _recording(recording_status)
    return record


def _unique_element(elements, *, key, label):
    matches = [
        element
        for element in elements
        if element.key == key and element.label == label
    ]
    assert len(matches) == 1
    return matches[0]


def _control_for_question(app, question, key):
    collection = {
        "boolean": app.radio,
        "slider": app.slider,
        "integer": app.number_input,
        "multiselect": app.multiselect,
        "text": app.text_area,
    }[question.kind]
    return _unique_element(collection, key=key, label=question.prompt)


def _answer_and_continue(app, question, visit, value):
    keys = questionnaire_state_keys(SESSION_NAMESPACE, visit)
    control = _control_for_question(app, question, keys.widget(question.id))
    if question.kind == "slider" and control.value == value:
        alternate = value + 1 if value < question.max_value else value - 1
        control.set_value(alternate).run()
        control = _control_for_question(app, question, keys.widget(question.id))
    control.set_value(value).run()
    next_button = _unique_element(
        app.button,
        key=keys.next_button,
        label=(
            "检查并提交"
            if not [
                button
                for button in app.button
                if button.key == keys.next_button and button.label == "继续"
            ]
            else "继续"
        ),
    )
    return next_button.click().run()


def _start_fixture(scenario: str = "day1", *, recording_status: str = "saved"):
    app = AppTest.from_file(str(FIXTURE), default_timeout=10)
    app.query_params["scenario"] = scenario
    app.query_params["recording"] = recording_status
    app.run()
    assert not app.exception
    return app


def _complete_fixture(app, questions, visit: str, answers):
    for question in questions:
        app = _answer_and_continue(app, question, visit, answers[question.id])
        assert not app.exception
    return app


def _visible_text(app) -> str:
    values = [str(app.main), str(app.sidebar)]
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
        "button",
        "radio",
        "slider",
        "number_input",
        "text_area",
        "multiselect",
        "checkbox",
    ):
        for element in getattr(app, collection_name):
            for attribute in ("value", "label", "help", "placeholder"):
                value = getattr(element, attribute, None)
                if value is not None:
                    values.append(str(value))
    return "\n".join(values)


def _worksheet_rows(worksheet) -> list[dict[str, object]]:
    rows = list(worksheet.iter_rows(values_only=True))
    headers = rows[0]
    return [dict(zip(headers, row, strict=True)) for row in rows[1:]]


def test_questionnaire_fixture_source_is_session_memory_only():
    source = FIXTURE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    call_names = {
        node.func.id
        if isinstance(node.func, ast.Name)
        else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }

    assert "create_session_record" in source
    assert "st.session_state" in source
    assert "persist_daily_questionnaire" in source
    assert "persist_formal_questionnaire" in source
    assert "build_participant_export" in source
    assert {
        "record_store",
        "questionnaire_fixture_storage",
        "questionnaire_scoring",
        "upload_workflow",
        "pathlib",
        "tempfile",
        "requests",
        "urllib",
        "httpx",
        "socket",
    }.isdisjoint(imported_roots)
    assert {
        "DailyRecordStore",
        "Path",
        "open",
        "mkdtemp",
        "NamedTemporaryFile",
        "TemporaryDirectory",
        "write_text",
        "write_bytes",
        "mkdir",
        "get_or_create",
    }.isdisjoint(call_names)
    forbidden_source = (
        "DailyRecordStore",
        "record_store",
        "questionnaire_fixture_storage",
        "QUESTIONNAIRE_FIXTURE_STORE",
        "video_filename",
        "remote_path",
        "upload",
        "include_derived",
        "derived_metrics",
        "safety_signals",
        "recordings",
        "requests.",
        "urllib.",
        "httpx.",
    )
    assert all(value.casefold() not in source.casefold() for value in forbidden_source)


def test_questionnaire_fixture_never_constructs_a_server_store(tmp_path, monkeypatch):
    import record_store

    def reject_server_store(*args, **kwargs):
        raise AssertionError("fixture attempted server storage")

    monkeypatch.setattr(record_store, "DailyRecordStore", reject_server_store)
    monkeypatch.setenv("QUESTIONNAIRE_FIXTURE_STORE", str(tmp_path))
    app = _start_fixture("day1")

    assert app.session_state[SESSION_RECORD_KEY]["schema_version"] == 5
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("scenario", "visit", "day"),
    (
        ("day1", "daily", 1),
        ("day7", "daily", 7),
        *((visit, visit, 7) for visit in VISIT_INSTRUMENT_IDS),
    ),
)
def test_fresh_browser_session_creates_one_deterministic_raw_v5_record(
    scenario, visit, day
):
    app = _start_fixture(scenario)
    record = app.session_state[SESSION_RECORD_KEY]

    assert record["schema_version"] == 5
    assert record["record_id"] == "sub-001_20260727_01abcdef"
    assert record["subject_id"] == SUBJECT_ID
    assert record["record_date"] == RECORD_DATE.isoformat()
    assert record["intervention_day"] == day
    assert record["visit"] == visit
    assert record["revision"] == 1
    assert record["created_at_iso"] == CREATED_AT_ISO
    assert record["updated_at_iso"] == CREATED_AT_ISO
    assert record["recording"] == _recording()
    assert record["completion"]["status"] == "draft"
    assert questionnaire_answers(record, visit) == {}
    assert {
        "derived_metrics",
        "safety_signals",
        "upload",
        "history",
        "remote_path",
        "local_path",
    }.isdisjoint(record)
    record_keys = [
        str(key)
        for key, value in app.session_state.filtered_state.items()
        if isinstance(value, dict) and value.get("schema_version") == 5
    ]
    assert record_keys == [SESSION_RECORD_KEY]
    assert not any(
        str(key).startswith("fixture_")
        for key in app.session_state.filtered_state
    )


@pytest.mark.parametrize("status", ("saved", "skipped", "failed"))
def test_fixture_uses_only_sanitized_browser_local_v2_metadata(status):
    app = _start_fixture("day1", recording_status=status)
    metadata = app.session_state[SESSION_RECORD_KEY]["recording"]

    assert tuple(metadata) == RECORDING_KEYS
    assert metadata == _recording(status)
    assert {
        "path",
        "filename",
        "bytes",
        "video",
        "blob",
        "upload",
    }.isdisjoint(metadata)


def test_negative_day_one_keeps_false_zero_status_and_completion_metadata():
    record = _new_record()
    stale = {
        **_positive_daily_answers(),
        **_negative_daily_answers(),
    }
    persisted = persist_daily_questionnaire(
        record,
        stale,
        set(stale),
        current_step=len(DAILY_CORE) - 1,
    )

    expected = _negative_daily_answers()
    assert persisted == expected
    assert record["daily_core"] == expected
    assert record["conditional_details"] == {}
    assert record["weekly_extension"] == {}
    assert questionnaire_answers(record, "daily") == expected
    assert record["completion"]["answered_field_ids"]["daily"] == sorted(expected)
    assert all(
        record["field_status"]["daily"][question.id] == "answered"
        for question in DAILY_CORE
    )
    assert all(
        record["field_status"]["daily"][question.id] == "not_applicable"
        for question in DAILY_CONDITIONAL
    )

    mark_questionnaire_visit_complete(
        record,
        "daily",
        completed_at_iso=COMPLETED_AT_ISO,
    )

    assert questionnaire_visit_complete(record, "daily") is True
    assert record["revision"] == 1
    assert record["created_at_iso"] == CREATED_AT_ISO
    assert record["updated_at_iso"] == COMPLETED_AT_ISO
    assert record["completion"]["status"] == "complete"
    assert record["completion"]["questionnaire_visits"]["daily"] == {
        "status": "complete",
        "revision": 1,
        "completed_at_iso": COMPLETED_AT_ISO,
    }
    assert "derived_metrics" not in record
    assert "safety_signals" not in record


def test_positive_daily_browser_branch_preserves_every_nssi_field_then_drops_stale():
    positive = _positive_daily_answers()
    flow = build_flow(positive, 1)
    app = _complete_fixture(_start_fixture("day1"), flow, "daily", positive)
    record = app.session_state[SESSION_RECORD_KEY]

    expected_conditional_ids = {question.id for question in DAILY_CONDITIONAL}
    assert set(record["conditional_details"]) == expected_conditional_ids
    assert questionnaire_answers(record, "daily") == {
        question.id: positive[question.id] for question in flow
    }
    assert all(
        record["field_status"]["daily"][field_id] == "answered"
        for field_id in expected_conditional_ids
    )
    assert record["completion"]["answered_field_ids"]["daily"] == sorted(
        question.id for question in flow
    )

    stale_record = _new_record()
    stale = {**positive, **_negative_daily_answers()}
    persist_daily_questionnaire(
        stale_record,
        stale,
        set(stale),
        current_step=len(DAILY_CORE) - 1,
    )
    assert stale_record["conditional_details"] == {}
    assert all(
        stale_record["field_status"]["daily"][field_id] == "not_applicable"
        for field_id in expected_conditional_ids
    )


def test_day_seven_keeps_daily_and_weekly_raw_inventory_distinct():
    record = _new_record(day=7)
    weekly_questions = _weekly_questions()
    weekly_answers = {
        question.id: _raw_value(question, positive=True)
        for question in weekly_questions
    }
    answers = {**_negative_daily_answers(), **weekly_answers}
    flow = build_flow(answers, 7)

    persist_daily_questionnaire(
        record,
        answers,
        set(answers),
        current_step=len(flow) - 1,
    )

    daily_ids = {question.id for question in DAILY_CORE}
    weekly_ids = {question.id for question in weekly_questions}
    assert set(record["daily_core"]) == daily_ids
    assert set(record["weekly_extension"]) == weekly_ids
    assert not set(record["daily_core"]) & set(record["weekly_extension"])
    assert list(record["weekly_extension"]) == [
        question.id for question in weekly_questions
    ]
    assert all(
        record["field_status"]["daily"][field_id] == "answered"
        for field_id in weekly_ids
    )
    assert questionnaire_answers(record, "daily") == {
        question.id: answers[question.id] for question in flow
    }


@pytest.mark.parametrize("visit", tuple(VISIT_INSTRUMENT_IDS))
def test_every_formal_visit_keeps_complete_instrument_and_item_inventory(visit):
    record = _new_record(day=7, visit=visit)
    questions = _formal_questions(visit)
    answers = {
        question.id: _raw_value(question, positive=True) for question in questions
    }
    active_questions = formal_flow(visit, answers)

    persist_formal_questionnaire(
        record,
        visit,
        answers,
        set(answers),
        current_step=len(active_questions) - 1,
    )

    visit_payload = record["formal_visits"][visit]
    assert list(visit_payload["raw_answers"]) == [
        question.id for question in active_questions
    ]
    assert visit_payload["raw_answers"] == questionnaire_answers(record, visit)
    assert tuple(visit_payload["instruments"]) == VISIT_INSTRUMENT_IDS[visit]
    assert visit_payload["complete"] is True
    assert all(
        record["field_status"][visit][question.id] == "answered"
        for question in active_questions
    )
    assert record["completion"]["answered_field_ids"][visit] == sorted(
        question.id for question in active_questions
    )
    for instrument_id in VISIT_INSTRUMENT_IDS[visit]:
        payload = visit_payload["instruments"][instrument_id]
        expected_ids = [
            question.id
            for question in FORMAL_INSTRUMENTS[instrument_id].questions
        ]
        assert set(payload) == {
            "instrument_id",
            "instrument_version",
            "label",
            "time_window",
            "raw_answers",
            "completeness",
            "complete",
        }
        assert payload["instrument_id"] == instrument_id
        assert payload["instrument_version"] == "1.0"
        assert list(payload["raw_answers"]) == expected_ids
        assert payload["complete"] is True
        assert payload["completeness"]["answered"] == payload["completeness"][
            "required"
        ]

    mark_questionnaire_visit_complete(
        record,
        visit,
        completed_at_iso=COMPLETED_AT_ISO,
    )
    assert questionnaire_visit_complete(record, visit) is True
    assert record["completion"]["questionnaire_visits"][visit]["revision"] == 1
    assert record["completion"]["questionnaire_visits"][visit][
        "completed_at_iso"
    ] == COMPLETED_AT_ISO


def test_browser_required_gate_and_back_navigation_restore_answer_and_step():
    app = _start_fixture("day1")
    keys = questionnaire_state_keys(SESSION_NAMESPACE, "daily")
    _unique_element(app.button, key=keys.next_button, label="继续").click().run()

    assert app.error
    assert app.session_state[keys.step] == 0
    assert questionnaire_answers(app.session_state[SESSION_RECORD_KEY], "daily") == {}

    app = _answer_and_continue(app, DAILY_CORE[0], "daily", False)
    assert app.session_state[keys.step] == 1
    _unique_element(app.button, key=keys.back_button, label="←").click().run()

    assert app.session_state[keys.step] == 0
    assert app.session_state[SESSION_RECORD_KEY]["completion"]["current_step"][
        "daily"
    ] == 0
    assert questionnaire_answers(
        app.session_state[SESSION_RECORD_KEY], "daily"
    ) == {DAILY_CORE[0].id: False}
    restored = _control_for_question(app, DAILY_CORE[0], keys.widget(DAILY_CORE[0].id))
    assert restored.value is False


def test_browser_fixture_retains_same_session_but_refresh_before_download_loses_draft():
    app = _start_fixture("day1")
    app = _answer_and_continue(app, DAILY_CORE[0], "daily", False)
    retained_record = app.session_state[SESSION_RECORD_KEY]
    stable_id = retained_record["record_id"]

    app.run()
    keys = questionnaire_state_keys(SESSION_NAMESPACE, "daily")
    assert app.session_state[SESSION_RECORD_KEY]["record_id"] == stable_id
    assert questionnaire_answers(
        app.session_state[SESSION_RECORD_KEY], "daily"
    ) == {DAILY_CORE[0].id: False}
    assert app.session_state[keys.step] == 1
    assert SESSION_EXPORT_KEY not in app.session_state

    fresh = _start_fixture("day1")
    fresh_keys = questionnaire_state_keys(SESSION_NAMESPACE, "daily")
    assert fresh.session_state[SESSION_RECORD_KEY]["record_id"] == stable_id
    assert questionnaire_answers(
        fresh.session_state[SESSION_RECORD_KEY], "daily"
    ) == {}
    assert fresh.session_state[fresh_keys.step] == 0
    assert SESSION_EXPORT_KEY not in fresh.session_state


def test_fixture_shows_support_copy_for_answered_suicide_thought_branch():
    app = _start_fixture("day1")
    for question, value in zip(DAILY_CORE[:3], (False, False, True), strict=True):
        app = _answer_and_continue(app, question, "daily", value)
        assert not app.exception

    record = app.session_state[SESSION_RECORD_KEY]
    assert questionnaire_answers(record, "daily")[
        "suicide_thought_present_24h"
    ] is True
    assert "safety_signals" not in record
    visible = _visible_text(app).casefold()
    assert "study support team" in visible
    assert "local emergency services" in visible
    assert "risk" not in visible


def test_current_visit_export_has_exact_json_xlsx_raw_inventory_and_private_surface():
    answers = _negative_daily_answers()
    app = _complete_fixture(
        _start_fixture("day1"),
        tuple(DAILY_CORE),
        "daily",
        answers,
    )
    record = app.session_state[SESSION_RECORD_KEY]
    bundle = app.session_state[SESSION_EXPORT_KEY]

    assert questionnaire_visit_complete(record, "daily") is True
    assert record["completion"]["questionnaire_visits"]["daily"] == {
        "status": "complete",
        "revision": 1,
        "completed_at_iso": COMPLETED_AT_ISO,
    }
    assert bundle.filename == "session-20260727-103000.zip"
    assert bundle.mime_type == "application/zip"
    with ZipFile(BytesIO(bundle.data)) as archive:
        assert archive.namelist() == ["responses.json", "responses.xlsx"]
        payload = json.loads(archive.read("responses.json"))
        workbook_data = archive.read("responses.xlsx")
    workbook = openpyxl.load_workbook(BytesIO(workbook_data), data_only=False)

    expected_answered = [question.id for question in DAILY_CORE]
    assert payload["export_schema_version"] == 1
    assert payload["participant_id"] == SUBJECT_ID
    assert payload["record_date"] == RECORD_DATE.isoformat()
    assert payload["intervention_day"] == 1
    assert payload["visit"] == "daily"
    assert payload["exported_at_iso"] == EXPORTED_AT_ISO
    assert payload["recording"] == _recording()
    assert payload["answered_field_ids"] == expected_answered
    assert payload["field_status"] == record["field_status"]["daily"]
    assert [item["instrument_id"] for item in payload["visits"]] == [
        "daily_nssi_ema"
    ]
    assert payload["visits"][0]["visit_status"] == "complete"
    assert payload["visits"][0]["instrument_status"] == "complete"
    assert payload["visits"][0]["completed_at_iso"] == COMPLETED_AT_ISO
    response_by_id = {item["field_id"]: item for item in payload["responses"]}
    assert list(response_by_id) == [
        question.id for question in (*DAILY_CORE, *DAILY_CONDITIONAL)
    ]
    for field_id, value in answers.items():
        assert response_by_id[field_id]["answered"] is True
        assert response_by_id[field_id]["applicability"] == "applicable"
        assert response_by_id[field_id]["raw_value"] == value
    for question in DAILY_CONDITIONAL:
        item = response_by_id[question.id]
        assert item["answered"] is False
        assert item["applicability"] == "not_applicable"
        assert item["raw_value"] is None

    assert workbook.sheetnames == ["Session", "Responses", "Visits", "Recording"]
    session_rows = _worksheet_rows(workbook["Session"])
    response_rows = _worksheet_rows(workbook["Responses"])
    visit_rows = _worksheet_rows(workbook["Visits"])
    recording_rows = _worksheet_rows(workbook["Recording"])
    assert len(session_rows) == 1
    assert session_rows[0]["participant_id"] == SUBJECT_ID
    assert len(response_rows) == len(DAILY_CORE) + len(DAILY_CONDITIONAL)
    assert [row["field_id"] for row in response_rows] == list(response_by_id)
    assert [row["instrument_id"] for row in visit_rows] == ["daily_nssi_ema"]
    assert recording_rows == [_recording()]

    serialized = json.dumps(payload, ensure_ascii=False).casefold()
    workbook_surface = "\n".join(
        str(value)
        for worksheet in workbook.worksheets
        for row in worksheet.iter_rows(values_only=True)
        for value in row
        if value is not None
    ).casefold()
    forbidden = (
        "score",
        "risk",
        "upload",
        "remote_path",
        "local_path",
        "record_id",
        "revision",
        "derived_metrics",
        "safety_signals",
        "formal_visits",
        "raw_answers",
        "video_filename",
    )
    assert all(value not in serialized for value in forbidden)
    assert all(value not in workbook_surface for value in forbidden)
    visible = _visible_text(app).casefold()
    assert all(value not in visible for value in forbidden)
    assert len(app.get("download_button")) == 1

    finish = _unique_element(
        app.button,
        key="session_finish",
        label="Finish this session",
    )
    assert finish.disabled is True
    app.session_state["session_recorder::pending"] = _recording("failed")
    app.session_state["session_context::narrative"] = "sensitive draft"
    _unique_element(
        app.checkbox,
        key="session_saved_locally",
        label="I confirm the questionnaire ZIP is saved locally",
    ).check().run()
    finish = _unique_element(
        app.button,
        key="session_finish",
        label="Finish this session",
    )
    assert finish.disabled is False
    finish.click().run()

    remaining = {
        str(key)
        for key in app.session_state.filtered_state
        if not str(key).startswith("$$")
    }
    assert remaining == {"session_complete"}
    assert app.session_state["session_complete"] is True
    assert "This session is complete." in _visible_text(app)
    assert not app.get("download_button")
    assert not app.radio
    assert not app.slider
