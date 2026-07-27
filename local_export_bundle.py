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


_MAX_JSON_DEPTH = 64
_MAX_CONTAINER_ITEMS = 100_000
_MAX_TOTAL_VALUES = 1_000_000
_MAX_EXCEL_COLUMNS = 16_384
_MAX_EXCEL_TEXT_LENGTH = 32_767
_FIXED_ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_FIXED_WORKBOOK_TIMESTAMP = datetime(2000, 1, 1)
_MIN_EXCEL_DATE = date(1900, 1, 1)
_MAX_EXCEL_DATETIME = datetime(9999, 12, 31, 23, 59, 59, 999_000)
_MAX_EXCEL_TIMEDELTA = timedelta(
    days=2_958_465,
    seconds=86_399,
    microseconds=999_000,
)
_ALLOWED_FILENAME_PREFIXES = frozenset({"session", "synthetic-session"})
_FORBIDDEN_SHEET_CHARACTERS = frozenset("[]:*?/\\")
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_OOXML_ESCAPE_PATTERN = re.compile(r"_x[0-9a-f]{4}_", re.IGNORECASE)


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
        self.reserve(1)

    def reserve(self, count: int) -> None:
        self.value_count += count
        if self.value_count > _MAX_TOTAL_VALUES:
            raise ValueError("input structure contains too many values")


def _validate_unicode_text(value: str, *, context: str) -> None:
    encoding_failed = False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        encoding_failed = True
    if encoding_failed:
        raise ValueError(f"{context} must contain valid Unicode text")
    if any(
        ord(character) < 32 and character not in {"\t", "\n"}
        for character in value
    ) or any(character in {"\ufffe", "\uffff"} for character in value):
        raise ValueError(
            f"{context} contains text that Excel XML cannot represent losslessly"
        )
    if _OOXML_ESCAPE_PATTERN.search(value) is not None:
        raise ValueError(f"{context} contains an ambiguous OOXML escape token")


def _validate_excel_number(value: object, *, context: str) -> int | float:
    if type(value) not in {int, float}:
        raise TypeError(f"{context} contains an unsupported numeric type")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{context} numbers must be finite")
    conversion_failed = False
    serialized = ""
    round_tripped: int | float = 0
    try:
        serialized = f"{value:.16G}"
        try:
            round_tripped = int(serialized)
        except ValueError:
            round_tripped = float(serialized)
    except (OverflowError, ValueError):
        conversion_failed = True
    if conversion_failed:
        raise ValueError(
            f"{context} cannot survive the Excel numeric round-trip"
        )

    type_changed = type(round_tripped) is not type(value)
    value_changed = round_tripped != value
    became_non_finite = isinstance(round_tripped, float) and not math.isfinite(
        round_tripped
    )
    zero_sign_changed = (
        isinstance(value, float)
        and value == 0
        and isinstance(round_tripped, float)
        and math.copysign(1.0, round_tripped) != math.copysign(1.0, value)
    )
    if type_changed or value_changed or became_non_finite or zero_sign_changed:
        raise ValueError(
            f"{context} cannot survive the Excel numeric round-trip"
        )
    return value


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
        return _validate_excel_number(value, context=context)
    if isinstance(value, float):
        return _validate_excel_number(value, context=context)
    if isinstance(value, Mapping):
        identifier = _enter_container(
            value,
            state=state,
            depth=depth,
            context=context,
        )
        copied: dict[str, object] = {}
        try:
            for item_index, (key, item) in enumerate(value.items()):
                if not isinstance(key, str):
                    raise TypeError(f"{context} mapping keys must be strings")
                _validate_unicode_text(
                    key,
                    context=f"{context} mapping key at index {item_index}",
                )
                if key in copied:
                    raise ValueError(f"{context} contains a duplicate mapping key")
                copied[key] = _copy_json_value(
                    item,
                    state=state,
                    depth=depth + 1,
                    context=f"{context} mapping value at index {item_index}",
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
    raise TypeError(f"{context} contains an unsupported value type")


def _copy_cell_value(
    value: object,
    *,
    state: _ValidationState,
    context: str,
) -> object:
    if isinstance(value, datetime):
        state.count()
        normalization_failed = False
        normalized = datetime(1900, 1, 1)
        try:
            offset = value.utcoffset()
            normalized = (
                value.astimezone(timezone.utc).replace(tzinfo=None)
                if offset is not None
                else value.replace(tzinfo=None)
            )
        except Exception:
            normalization_failed = True
        if normalization_failed:
            raise ValueError(
                f"{context} datetime could not be normalized safely"
            )
        if normalized.date() < _MIN_EXCEL_DATE:
            raise ValueError(
                f"{context} datetime is outside the Excel 1900 date range"
            )
        if normalized > _MAX_EXCEL_DATETIME:
            raise ValueError(
                f"{context} datetime is outside the Excel 1900 date range"
            )
        if normalized.microsecond % 1_000:
            raise ValueError(
                f"{context} datetime must use millisecond precision"
            )
        return normalized
    if isinstance(value, date):
        state.count()
        if value < _MIN_EXCEL_DATE:
            raise ValueError(
                f"{context} date is outside the Excel 1900 date range"
            )
        return value
    if isinstance(value, time):
        state.count()
        offset_failed = False
        offset = None
        try:
            offset = value.utcoffset()
        except Exception:
            offset_failed = True
        if offset_failed:
            raise ValueError(f"{context} time could not be validated safely")
        if offset is not None:
            raise ValueError(f"{context} timezone-aware time values are unsupported")
        if value.microsecond % 1_000:
            raise ValueError(f"{context} time must use millisecond precision")
        return value.replace(tzinfo=None)
    if isinstance(value, timedelta):
        state.count()
        if value < timedelta(0):
            raise ValueError(
                f"{context} duration cannot be negative in the Excel 1900 date system"
            )
        if value.microseconds % 1_000:
            raise ValueError(f"{context} duration must use millisecond precision")
        if value > _MAX_EXCEL_TIMEDELTA:
            raise ValueError(
                f"{context} duration is outside the representable Excel range"
            )
        return value
    return _copy_json_value(value, state=state, depth=0, context=context)


def _canonical_json_bytes(
    snapshot: Mapping[str, object],
    *,
    state: _ValidationState,
) -> bytes:
    copied = _copy_json_value(
        snapshot,
        state=state,
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
    *,
    state: _ValidationState,
) -> list[tuple[str, list[str], list[dict[str, object]]]]:
    if not isinstance(sheets, Mapping):
        raise TypeError("sheets must be a mapping")
    if not sheets:
        raise ValueError("sheets must contain at least one worksheet")
    if len(sheets) > _MAX_CONTAINER_ITEMS:
        raise ValueError("sheets contains too many worksheets")

    normalized_names: set[str] = set()
    prepared: list[tuple[str, list[str], list[dict[str, object]]]] = []
    state.count()
    sheets_identifier = _enter_container(
        sheets,
        state=state,
        depth=0,
        context="sheets",
    )
    try:
        for worksheet_index, (raw_name, raw_rows) in enumerate(sheets.items()):
            state.count()
            name = _validate_sheet_name(raw_name, normalized_names)
            worksheet_context = f"worksheet at index {worksheet_index}"
            if not isinstance(raw_rows, Sequence) or isinstance(
                raw_rows,
                (str, bytes, bytearray),
            ):
                raise TypeError(f"{worksheet_context} rows must be a sequence")
            state.count()
            rows_identifier = _enter_container(
                raw_rows,
                state=state,
                depth=0,
                context=f"{worksheet_context} rows",
            )
            headers: list[str] = []
            header_names: set[str] = set()
            copied_rows: list[dict[str, object]] = []
            present_cell_count = 0
            try:
                for row_index, raw_row in enumerate(raw_rows):
                    if not isinstance(raw_row, Mapping):
                        raise TypeError(
                            f"{worksheet_context} row at index {row_index} "
                            "must be a mapping"
                        )
                    state.count()
                    row_identifier = _enter_container(
                        raw_row,
                        state=state,
                        depth=0,
                        context=f"{worksheet_context} row at index {row_index}",
                    )
                    copied_row: dict[str, object] = {}
                    try:
                        for cell_index, (key, value) in enumerate(raw_row.items()):
                            if not isinstance(key, str):
                                raise TypeError(
                                    f"{worksheet_context} row at index {row_index} "
                                    "keys must be strings"
                                )
                            header_context = (
                                f"{worksheet_context} header at entry index "
                                f"{cell_index}"
                            )
                            _validate_unicode_text(key, context=header_context)
                            _excel_text(key)
                            if key in copied_row:
                                raise ValueError(
                                    f"{worksheet_context} row at index {row_index} "
                                    "contains a duplicate key"
                                )
                            is_new_header = key not in header_names
                            if is_new_header and len(headers) >= _MAX_EXCEL_COLUMNS:
                                raise ValueError(
                                    f"{worksheet_context} cannot exceed 16,384 columns"
                                )
                            copied_value = _copy_cell_value(
                                value,
                                state=state,
                                context=(
                                    f"{worksheet_context} row at index {row_index} "
                                    f"cell at entry index {cell_index}"
                                ),
                            )
                            if isinstance(copied_value, str):
                                _excel_text(copied_value)
                            elif isinstance(copied_value, (dict, list)):
                                _excel_text(_canonical_cell_json(copied_value))
                            copied_row[key] = copied_value
                            if is_new_header:
                                header_names.add(key)
                                headers.append(key)
                    finally:
                        state.active_container_ids.remove(row_identifier)
                    copied_rows.append(copied_row)
                    present_cell_count += len(copied_row)
            finally:
                state.active_container_ids.remove(rows_identifier)
            rectangular_cell_count = len(copied_rows) * len(headers)
            state.reserve(rectangular_cell_count - present_cell_count)
            prepared.append((name, headers, copied_rows))
    finally:
        state.active_container_ids.remove(sheets_identifier)
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
        result = worksheet.write_number(row, column, value, cell_format)
    elif isinstance(value, float):
        result = worksheet.write_number(row, column, value, cell_format)
    elif isinstance(value, datetime):
        datetime_format = formats[
            "datetime_accent" if column == 0 else "datetime"
        ]
        if value.date() == _MIN_EXCEL_DATE:
            elapsed_milliseconds = (
                ((value.hour * 60 + value.minute) * 60 + value.second) * 1_000
                + value.microsecond // 1_000
            )
            result = worksheet.write_number(
                row,
                column,
                1 + elapsed_milliseconds / 86_400_000,
                datetime_format,
            )
        else:
            result = worksheet.write_datetime(
                row,
                column,
                value,
                datetime_format,
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


def _display_width(value: object) -> int:
    return max(len(part) for part in _cell_text(value).splitlines() or [""])


def _column_widths(
    headers: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> dict[str, float]:
    widest = {header: _display_width(header) for header in headers}
    for row in rows:
        for header, value in row.items():
            widest[header] = max(widest[header], _display_width(value))
    return {
        header: min(47.25, max(12, width + 2))
        for header, width in widest.items()
    }


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
        for worksheet_index, (name, headers, rows) in enumerate(sheets):
            worksheet_context = f"worksheet at index {worksheet_index}"
            worksheet = workbook.add_worksheet(name)
            worksheet.set_tab_color("#2D2674")
            worksheet.freeze_panes(1, 0)
            _require_write_success(
                worksheet.set_row(0, 24),
                context=f"{worksheet_context} header height",
            )
            column_widths = _column_widths(headers, rows)
            header_columns = {
                header: column for column, header in enumerate(headers)
            }
            for column, header in enumerate(headers):
                _require_write_success(
                    worksheet.write_string(
                        0,
                        column,
                        _excel_text(header),
                        formats["header"],
                    ),
                    context=f"{worksheet_context} header at column {column}",
                )
                _require_write_success(
                    worksheet.set_column(
                        column,
                        column,
                        column_widths[header],
                    ),
                    context=f"{worksheet_context} column {column}",
                )
            if headers:
                worksheet.autofilter(0, 0, len(rows), len(headers) - 1)
            else:
                _require_write_success(
                    worksheet.set_column(0, 0, 12),
                    context=f"{worksheet_context} empty column",
                )
                worksheet.autofilter(0, 0, 0, 0)
            for row_index, row in enumerate(rows, start=1):
                height = min(
                    90,
                    max(
                        18,
                        15
                        * max(
                            (_line_count(value) for value in row.values()),
                            default=1,
                        ),
                    ),
                )
                _require_write_success(
                    worksheet.set_row(row_index, height),
                    context=f"{worksheet_context} row {row_index}",
                )
                for header, value in row.items():
                    column = header_columns[header]
                    cell_format = formats["accent" if column == 0 else "body"]
                    _write_cell(
                        worksheet,
                        row=row_index,
                        column=column,
                        value=value,
                        cell_format=cell_format,
                        formats=formats,
                        context=(
                            f"{worksheet_context} cell ({row_index}, {column})"
                        ),
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
    if exported_at.tzinfo is None:
        raise ValueError("exported_at must be timezone-aware UTC")
    offset_failed = False
    offset = None
    try:
        offset = exported_at.utcoffset()
    except Exception:
        offset_failed = True
    if offset_failed:
        raise ValueError("exported_at timezone could not be validated safely")
    if offset != timedelta(0):
        raise ValueError("exported_at must be timezone-aware UTC")
    if exported_at.microsecond != 0:
        raise ValueError("exported_at must use second precision")


def _validate_filename_prefix(filename_prefix: str) -> None:
    if not isinstance(filename_prefix, str):
        raise TypeError("filename_prefix must be a string")
    if filename_prefix not in _ALLOWED_FILENAME_PREFIXES:
        raise ValueError(
            "filename_prefix must be 'session' or 'synthetic-session'"
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

    validation_state = _ValidationState()
    json_bytes = _canonical_json_bytes(snapshot, state=validation_state)
    prepared_sheets = _prepare_sheets(sheets, state=validation_state)
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
