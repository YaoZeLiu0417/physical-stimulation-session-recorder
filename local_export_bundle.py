from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
import json
import math
import re
import unicodedata
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import xlsxwriter


_MAX_PREFIX_LENGTH = 64
_MAX_JSON_DEPTH = 64
_MAX_CONTAINER_ITEMS = 100_000
_MAX_TOTAL_VALUES = 1_000_000
_MAX_EXCEL_TEXT_LENGTH = 32_767
_MAX_EXACT_EXCEL_INTEGER = (1 << 53) - 1
_FIXED_ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_FIXED_WORKBOOK_TIMESTAMP = datetime(2000, 1, 1)
_PREFIX_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.ASCII)
_FORBIDDEN_SHEET_CHARACTERS = frozenset("[]:*?/\\")
_FORMULA_PREFIXES = ("=", "+", "-", "@")


@dataclass(frozen=True, slots=True)
class LocalExportBundle:
    filename: str
    mime_type: str
    data: bytes


class _ValidationState:
    __slots__ = ("active_container_ids", "value_count")

    def __init__(self) -> None:
        self.active_container_ids: set[int] = set()
        self.value_count = 0

    def count(self) -> None:
        self.value_count += 1
        if self.value_count > _MAX_TOTAL_VALUES:
            raise ValueError("input structure contains too many values")


def _validate_unicode_text(value: str, *, context: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{context} must contain valid Unicode text") from exc


def _enter_container(
    value: object,
    *,
    state: _ValidationState,
    depth: int,
    context: str,
) -> int:
    if depth >= _MAX_JSON_DEPTH:
        raise ValueError(f"{context} is too deeply nested")
    identifier = id(value)
    if identifier in state.active_container_ids:
        raise ValueError(f"{context} contains a cycle")
    if len(value) > _MAX_CONTAINER_ITEMS:  # type: ignore[arg-type]
        raise ValueError(f"{context} contains too many items")
    state.active_container_ids.add(identifier)
    return identifier


def _copy_json_value(
    value: object,
    *,
    state: _ValidationState,
    depth: int,
    context: str,
) -> object:
    state.count()
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        _validate_unicode_text(value, context=context)
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{context} numbers must be finite")
        return value
    if isinstance(value, Mapping):
        identifier = _enter_container(
            value,
            state=state,
            depth=depth,
            context=context,
        )
        copied: dict[str, object] = {}
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError(f"{context} mapping keys must be strings")
                _validate_unicode_text(key, context=f"{context} mapping key")
                if key in copied:
                    raise ValueError(f"{context} contains a duplicate mapping key")
                copied[key] = _copy_json_value(
                    item,
                    state=state,
                    depth=depth + 1,
                    context=f"{context}.{key}",
                )
        finally:
            state.active_container_ids.remove(identifier)
        return copied
    if isinstance(value, list):
        identifier = _enter_container(
            value,
            state=state,
            depth=depth,
            context=context,
        )
        try:
            return [
                _copy_json_value(
                    item,
                    state=state,
                    depth=depth + 1,
                    context=f"{context}[{index}]",
                )
                for index, item in enumerate(value)
            ]
        finally:
            state.active_container_ids.remove(identifier)
    raise TypeError(f"{context} contains an unsupported value: {type(value).__name__}")


def _copy_cell_value(
    value: object,
    *,
    state: _ValidationState,
    context: str,
) -> object:
    if isinstance(value, datetime):
        state.count()
        offset = value.utcoffset()
        if offset is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if isinstance(value, date):
        state.count()
        return value
    if isinstance(value, time):
        state.count()
        if value.utcoffset() is not None:
            raise ValueError(f"{context} timezone-aware time values are unsupported")
        return value
    if isinstance(value, timedelta):
        state.count()
        return value
    return _copy_json_value(value, state=state, depth=0, context=context)


def _canonical_json_bytes(snapshot: Mapping[str, object]) -> bytes:
    copied = _copy_json_value(
        snapshot,
        state=_ValidationState(),
        depth=0,
        context="snapshot",
    )
    return json.dumps(
        copied,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
        separators=(",", ": "),
    ).encode("utf-8")


def _canonical_cell_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _excel_text(value: str) -> str:
    rendered = f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value
    if len(rendered) > _MAX_EXCEL_TEXT_LENGTH:
        raise ValueError("Excel text cells cannot exceed 32,767 characters")
    return rendered


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _excel_text(value)
    if isinstance(value, (dict, list)):
        return _excel_text(_canonical_cell_json(value))
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    return str(value)


def _validate_sheet_name(name: object, normalized_names: set[str]) -> str:
    if not isinstance(name, str):
        raise TypeError("sheet names must be strings")
    _validate_unicode_text(name, context="sheet name")
    if not name or len(name) > 31:
        raise ValueError("sheet name must contain between 1 and 31 characters")
    if name[0] == "'" or name[-1] == "'":
        raise ValueError("sheet name cannot begin or end with an apostrophe")
    if any(character in _FORBIDDEN_SHEET_CHARACTERS for character in name):
        raise ValueError("sheet name contains an Excel-forbidden character")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("sheet name contains a control character")
    normalized = unicodedata.normalize("NFKC", name).casefold()
    if normalized in normalized_names:
        raise ValueError("duplicate sheet name after case-insensitive normalization")
    normalized_names.add(normalized)
    return name


def _prepare_sheets(
    sheets: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[tuple[str, list[str], list[dict[str, object]]]]:
    if not isinstance(sheets, Mapping):
        raise TypeError("sheets must be a mapping")
    if not sheets:
        raise ValueError("sheets must contain at least one worksheet")
    if len(sheets) > _MAX_CONTAINER_ITEMS:
        raise ValueError("sheets contains too many worksheets")

    state = _ValidationState()
    normalized_names: set[str] = set()
    prepared: list[tuple[str, list[str], list[dict[str, object]]]] = []
    for raw_name, raw_rows in sheets.items():
        name = _validate_sheet_name(raw_name, normalized_names)
        if not isinstance(raw_rows, Sequence) or isinstance(
            raw_rows,
            (str, bytes, bytearray),
        ):
            raise TypeError(f"rows for sheet {name!r} must be a sequence")
        rows_identifier = _enter_container(
            raw_rows,
            state=state,
            depth=0,
            context=f"sheet {name!r} rows",
        )
        headers: list[str] = []
        header_names: set[str] = set()
        copied_rows: list[dict[str, object]] = []
        try:
            for row_index, raw_row in enumerate(raw_rows):
                if not isinstance(raw_row, Mapping):
                    raise TypeError(f"sheet {name!r} row {row_index} must be a mapping")
                row_identifier = _enter_container(
                    raw_row,
                    state=state,
                    depth=0,
                    context=f"sheet {name!r} row {row_index}",
                )
                copied_row: dict[str, object] = {}
                try:
                    for key, value in raw_row.items():
                        if not isinstance(key, str):
                            raise TypeError(
                                f"sheet {name!r} row keys must be strings"
                            )
                        _validate_unicode_text(key, context="worksheet header")
                        _excel_text(key)
                        if key in copied_row:
                            raise ValueError(
                                f"sheet {name!r} row contains a duplicate key"
                            )
                        copied_value = _copy_cell_value(
                            value,
                            state=state,
                            context=f"sheet {name!r} row {row_index} cell {key!r}",
                        )
                        if isinstance(copied_value, str):
                            _excel_text(copied_value)
                        elif isinstance(copied_value, (dict, list)):
                            _excel_text(_canonical_cell_json(copied_value))
                        copied_row[key] = copied_value
                        if key not in header_names:
                            header_names.add(key)
                            headers.append(key)
                finally:
                    state.active_container_ids.remove(row_identifier)
                copied_rows.append(copied_row)
        finally:
            state.active_container_ids.remove(rows_identifier)
        prepared.append((name, headers, copied_rows))
    return prepared


def _require_write_success(result: int, *, context: str) -> None:
    if result != 0:
        raise RuntimeError(f"XlsxWriter failed to write {context} (code {result})")


def _write_cell(
    worksheet: object,
    *,
    row: int,
    column: int,
    value: object,
    cell_format: object,
    formats: Mapping[str, object],
    context: str,
) -> None:
    if value is None:
        result = worksheet.write_blank(row, column, None, cell_format)
    elif isinstance(value, str):
        result = worksheet.write_string(row, column, _excel_text(value), cell_format)
    elif isinstance(value, bool):
        result = worksheet.write_boolean(row, column, value, cell_format)
    elif isinstance(value, int):
        if abs(value) <= _MAX_EXACT_EXCEL_INTEGER:
            result = worksheet.write_number(row, column, value, cell_format)
        else:
            result = worksheet.write_string(row, column, str(value), cell_format)
    elif isinstance(value, float):
        result = worksheet.write_number(row, column, value, cell_format)
    elif isinstance(value, datetime):
        result = worksheet.write_datetime(
            row,
            column,
            value,
            formats["datetime_accent" if column == 0 else "datetime"],
        )
    elif isinstance(value, date):
        result = worksheet.write_datetime(
            row,
            column,
            value,
            formats["date_accent" if column == 0 else "date"],
        )
    elif isinstance(value, time):
        result = worksheet.write_datetime(
            row,
            column,
            value,
            formats["time_accent" if column == 0 else "time"],
        )
    elif isinstance(value, timedelta):
        result = worksheet.write_datetime(
            row,
            column,
            value,
            formats["duration_accent" if column == 0 else "duration"],
        )
    elif isinstance(value, (dict, list)):
        result = worksheet.write_string(
            row,
            column,
            _excel_text(_canonical_cell_json(value)),
            cell_format,
        )
    else:
        raise TypeError(f"unsupported prepared cell value: {type(value).__name__}")
    _require_write_success(result, context=context)


def _line_count(value: object) -> int:
    text = _cell_text(value)
    lines = text.splitlines() or [""]
    return max(1, sum(max(1, (len(line) + 47) // 48) for line in lines))


def _column_width(header: str, rows: Sequence[Mapping[str, object]]) -> float:
    widest = max(
        [len(part) for part in _cell_text(header).splitlines() or [""]]
        + [
            len(part)
            for row in rows
            for part in (_cell_text(row.get(header)).splitlines() or [""])
        ]
    )
    return min(47.25, max(12, widest + 2))


def _workbook_formats(workbook: object) -> dict[str, object]:
    base = {"text_wrap": True, "valign": "top"}
    accent = {**base, "bold": True, "font_color": "#2D2674"}
    return {
        "header": workbook.add_format(
            {
                **base,
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#000035",
            }
        ),
        "body": workbook.add_format(base),
        "accent": workbook.add_format(accent),
        "date": workbook.add_format({**base, "num_format": "yyyy-mm-dd"}),
        "date_accent": workbook.add_format(
            {**accent, "num_format": "yyyy-mm-dd"}
        ),
        "datetime": workbook.add_format(
            {**base, "num_format": "yyyy-mm-dd hh:mm:ss"}
        ),
        "datetime_accent": workbook.add_format(
            {**accent, "num_format": "yyyy-mm-dd hh:mm:ss"}
        ),
        "time": workbook.add_format({**base, "num_format": "hh:mm:ss"}),
        "time_accent": workbook.add_format(
            {**accent, "num_format": "hh:mm:ss"}
        ),
        "duration": workbook.add_format({**base, "num_format": "[h]:mm:ss"}),
        "duration_accent": workbook.add_format(
            {**accent, "num_format": "[h]:mm:ss"}
        ),
    }


def _build_workbook_bytes(
    sheets: Sequence[tuple[str, list[str], list[dict[str, object]]]],
) -> bytes:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(
        output,
        {
            "in_memory": True,
            "strings_to_formulas": False,
            "strings_to_urls": False,
        },
    )
    try:
        workbook.set_properties(
            {
                "title": "Responses export",
                "subject": "Local responses",
                "author": "",
                "company": "",
                "comments": "",
                "created": _FIXED_WORKBOOK_TIMESTAMP,
            }
        )
        formats = _workbook_formats(workbook)
        for name, headers, rows in sheets:
            worksheet = workbook.add_worksheet(name)
            worksheet.set_tab_color("#2D2674")
            worksheet.freeze_panes(1, 0)
            _require_write_success(
                worksheet.set_row(0, 24),
                context=f"sheet {name!r} header height",
            )
            for column, header in enumerate(headers):
                _require_write_success(
                    worksheet.write_string(
                        0,
                        column,
                        _excel_text(header),
                        formats["header"],
                    ),
                    context=f"sheet {name!r} header {header!r}",
                )
                _require_write_success(
                    worksheet.set_column(
                        column,
                        column,
                        _column_width(header, rows),
                    ),
                    context=f"sheet {name!r} column {column}",
                )
            if headers:
                worksheet.autofilter(0, 0, len(rows), len(headers) - 1)
            else:
                _require_write_success(
                    worksheet.set_column(0, 0, 12),
                    context=f"sheet {name!r} empty column",
                )
                worksheet.autofilter(0, 0, 0, 0)
            for row_index, row in enumerate(rows, start=1):
                height = min(
                    90,
                    max(
                        18,
                        15
                        * max(
                            (
                                _line_count(row.get(header))
                                for header in headers
                            ),
                            default=1,
                        ),
                    ),
                )
                _require_write_success(
                    worksheet.set_row(row_index, height),
                    context=f"sheet {name!r} row {row_index}",
                )
                for column, header in enumerate(headers):
                    value = row.get(header)
                    cell_format = formats["accent" if column == 0 else "body"]
                    _write_cell(
                        worksheet,
                        row=row_index,
                        column=column,
                        value=value,
                        cell_format=cell_format,
                        formats=formats,
                        context=f"sheet {name!r} cell ({row_index}, {column})",
                    )
        workbook.close()
    except Exception:
        try:
            workbook.close()
        except Exception:
            pass
        raise
    return output.getvalue()


def _validate_export_time(exported_at: datetime) -> None:
    if not isinstance(exported_at, datetime):
        raise TypeError("exported_at must be a datetime")
    if exported_at.tzinfo is None or exported_at.utcoffset() != timedelta(0):
        raise ValueError("exported_at must be timezone-aware UTC")
    if exported_at.microsecond != 0:
        raise ValueError("exported_at must use second precision")


def _validate_filename_prefix(filename_prefix: str) -> None:
    if not isinstance(filename_prefix, str):
        raise TypeError("filename_prefix must be a string")
    if not 1 <= len(filename_prefix) <= _MAX_PREFIX_LENGTH:
        raise ValueError("filename_prefix must contain between 1 and 64 characters")
    if _PREFIX_PATTERN.fullmatch(filename_prefix) is None:
        raise ValueError(
            "filename_prefix must use lowercase ASCII letters, digits, and single hyphens"
        )


def _archive_member(name: str) -> ZipInfo:
    member = ZipInfo(filename=name, date_time=_FIXED_ARCHIVE_TIMESTAMP)
    member.compress_type = ZIP_DEFLATED
    member.create_system = 3
    member.external_attr = 0o100600 << 16
    member.extra = b""
    member.comment = b""
    return member


def build_local_export_bundle(
    *,
    snapshot: Mapping[str, object],
    sheets: Mapping[str, Sequence[Mapping[str, object]]],
    exported_at: datetime,
    filename_prefix: str = "session",
) -> LocalExportBundle:
    """Build a deterministic JSON and Excel ZIP without persistent storage."""
    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot must be a mapping")
    _validate_export_time(exported_at)
    _validate_filename_prefix(filename_prefix)

    json_bytes = _canonical_json_bytes(snapshot)
    prepared_sheets = _prepare_sheets(sheets)
    workbook_bytes = _build_workbook_bytes(prepared_sheets)

    archive_output = BytesIO()
    with ZipFile(
        archive_output,
        mode="w",
        compression=ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        archive.writestr(
            _archive_member("responses.json"),
            json_bytes,
            compress_type=ZIP_DEFLATED,
            compresslevel=9,
        )
        archive.writestr(
            _archive_member("responses.xlsx"),
            workbook_bytes,
            compress_type=ZIP_DEFLATED,
            compresslevel=9,
        )

    return LocalExportBundle(
        filename=f"{filename_prefix}-{exported_at:%Y%m%d-%H%M%S}.zip",
        mime_type="application/zip",
        data=archive_output.getvalue(),
    )
