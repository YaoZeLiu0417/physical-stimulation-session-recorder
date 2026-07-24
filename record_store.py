import json
import os
import re
import uuid
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping


SUBJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_subject_id(subject_id: str) -> str:
    safe_subject_id = subject_id.strip()
    if not SUBJECT_ID_RE.fullmatch(safe_subject_id):
        raise ValueError("受试者编号仅允许字母、数字、下划线和连字符，长度为 1-64 个字符。")
    return safe_subject_id


def can_cleanup(upload: Mapping[str, str]) -> bool:
    return upload.get("json") == "uploaded" and upload.get("video") == "uploaded"


def remote_record_dir(
    save_dir: str, subject_id: str, record_date: str, record_id: str
) -> str:
    return "/".join(
        (save_dir.rstrip("/"), validate_subject_id(subject_id), record_date, record_id)
    )


class DailyRecordStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _matching_paths(self, subject_id: str, record_date: date) -> list[Path]:
        safe_subject_id = validate_subject_id(subject_id)
        date_key = record_date.strftime("%Y%m%d")
        return sorted(self.root.glob(f"{safe_subject_id}_{date_key}_*_r*_state.json"))

    def _new_record(
        self, subject_id: str, record_date: date, intervention_day: int
    ) -> dict[str, Any]:
        safe_subject_id = validate_subject_id(subject_id)
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "schema_version": 4,
            "record_id": f"{safe_subject_id}_{record_date:%Y%m%d}_{uuid.uuid4().hex[:8]}",
            "subject_id": safe_subject_id,
            "record_date": record_date.isoformat(),
            "intervention_day": intervention_day,
            "revision": 1,
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
            "created_at_iso": now,
            "updated_at_iso": now,
        }

    def get_or_create(
        self, subject_id: str, record_date: date, intervention_day: int
    ) -> dict[str, Any]:
        matching_records: list[dict[str, Any]] = []
        for path in self._matching_paths(subject_id, record_date):
            with path.open(encoding="utf-8") as handle:
                matching_records.append(json.load(handle))
        if matching_records:
            return max(matching_records, key=lambda record: int(record["revision"]))

        record = self._new_record(subject_id, record_date, intervention_day)
        self.save(record)
        return record

    def path_for(self, record: Mapping[str, Any]) -> Path:
        return self.root / f"{record['record_id']}_r{record['revision']}_state.json"

    def save(self, record: dict[str, Any]) -> Path:
        record["updated_at_iso"] = datetime.now().isoformat(timespec="seconds")
        target = self.path_for(record)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
        return target

    def revise(self, record: Mapping[str, Any]) -> dict[str, Any]:
        revised = deepcopy(record)
        previous_revision = revised["revision"]
        revised["supersedes_revision"] = previous_revision
        revised["revision"] = previous_revision + 1
        revised["completion"] = {
            "status": "draft",
            "answered_field_ids": {},
            "current_step": {},
        }
        prior_upload = revised.get("upload", {})
        video_status = prior_upload.get("video", "pending")
        revised["upload"] = {"json": "pending", "video": video_status}
        self.save(revised)
        return revised
