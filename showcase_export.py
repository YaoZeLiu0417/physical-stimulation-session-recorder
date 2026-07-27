from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from local_export_bundle import build_local_export_bundle


_RECORDING_STATES = frozenset({"saved", "skipped", "failed"})


@dataclass(frozen=True, slots=True)
class SyntheticShowcaseArchive:
    filename: str
    data: bytes


def _validate_rating(name: str, value: object) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact integer")
    if not 0 <= value <= 4:
        raise ValueError(f"{name} must be between 0 and 4")
    return value


def _trusted_generated_at(generated_at: datetime) -> datetime:
    if not isinstance(generated_at, datetime):
        raise TypeError("generated_at must be a datetime")
    if type(generated_at) is not datetime:
        raise ValueError("generated_at must be a plain datetime")
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware UTC")
    offset_failed = False
    offset = None
    try:
        offset = generated_at.utcoffset()
    except Exception:
        offset_failed = True
    if offset_failed:
        raise ValueError(
            "generated_at timezone could not be validated safely"
        )
    if type(offset) is not timedelta:
        raise ValueError(
            "generated_at timezone could not be validated safely"
        ) from None
    if offset != timedelta(0):
        raise ValueError("generated_at must be timezone-aware UTC")
    if generated_at.microsecond != 0:
        raise ValueError("generated_at must use second precision")
    return datetime(
        generated_at.year,
        generated_at.month,
        generated_at.day,
        generated_at.hour,
        generated_at.minute,
        generated_at.second,
        generated_at.microsecond,
        tzinfo=timezone.utc,
    )


def build_synthetic_showcase_zip(
    *,
    process_clarity: int,
    camera_smoothness: int | None,
    information_load: int,
    workflow_willingness: int,
    recording_state: str,
    generated_at: datetime,
) -> SyntheticShowcaseArchive:
    if type(recording_state) is not str:
        raise TypeError("recording_state must be a string")
    if recording_state not in _RECORDING_STATES:
        raise ValueError("recording_state must be saved, skipped, or failed")

    validated_process_clarity = _validate_rating(
        "process_clarity", process_clarity
    )
    if camera_smoothness is None:
        if recording_state == "saved":
            raise ValueError(
                "camera_smoothness is required when recording_state is saved"
            )
        validated_camera_smoothness = None
    else:
        validated_camera_smoothness = _validate_rating(
            "camera_smoothness", camera_smoothness
        )
    validated_information_load = _validate_rating(
        "information_load", information_load
    )
    validated_workflow_willingness = _validate_rating(
        "workflow_willingness", workflow_willingness
    )
    trusted_generated_at = _trusted_generated_at(generated_at)

    generated_at_utc = trusted_generated_at.isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    ratings: list[dict[str, object]] = [
        {
            "item_id": "demo_process_clarity",
            "value": validated_process_clarity,
            "applicable": True,
        },
        {
            "item_id": "demo_camera_smoothness",
            "value": validated_camera_smoothness,
            "applicable": validated_camera_smoothness is not None,
        },
        {
            "item_id": "demo_information_load",
            "value": validated_information_load,
            "applicable": True,
        },
        {
            "item_id": "demo_workflow_willingness",
            "value": validated_workflow_willingness,
            "applicable": True,
        },
    ]
    recording: dict[str, object] = {
        "state": recording_state,
        "synthetic": True,
    }
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "recording": recording,
        "ratings": ratings,
    }
    sheets = {
        "Session": [
            {
                "schema_version": 1,
                "generated_at_utc": generated_at_utc,
            }
        ],
        "Responses": ratings,
        "Recording": [recording],
    }

    bundle = build_local_export_bundle(
        snapshot=snapshot,
        sheets=sheets,
        exported_at=trusted_generated_at,
        filename_prefix="synthetic-session",
    )
    return SyntheticShowcaseArchive(
        filename=bundle.filename,
        data=bundle.data,
    )
