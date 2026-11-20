"""Safe parsing and deterministic row validation for CSV/XLSX imports."""

from __future__ import annotations

import csv
import io
import math
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePath
from typing import Any

from openpyxl import load_workbook  # type: ignore[import-untyped]

ALLOWED_UNITS = {"piece", "kg", "liter", "meter", "box"}
PERSIAN_UNITS = {
    "عدد": "piece",
    "دانه": "piece",
    "کیلو": "kg",
    "کیلوگرم": "kg",
    "لیتر": "liter",
    "متر": "meter",
    "جعبه": "box",
}
PRODUCT_FIELDS = {"sku", "name", "unit", "description", "sale_price", "purchase_cost", "is_active"}
SUPPLIER_PRICE_FIELDS = {"raw_name", "sku", "unit_price", "unit", "currency"}
REQUIRED_FIELDS = {
    "products": {"sku", "name", "unit"},
    "supplier_prices": {"raw_name", "unit_price", "unit"},
}
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class ImportFileError(ValueError):
    """A safe, client-displayable import file validation error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ParsedImportFile:
    headers: list[str]
    rows: list[tuple[int, dict[str, Any]]]
    sheet_name: str | None


def _safe_cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _headers(values: tuple[Any, ...], max_columns: int) -> list[str]:
    if len(values) > max_columns:
        raise ImportFileError("IMPORT_TOO_MANY_COLUMNS")
    headers = [str(value).strip() if value is not None else "" for value in values]
    while headers and not headers[-1]:
        headers.pop()
    if not headers or any(not header for header in headers):
        raise ImportFileError("IMPORT_HEADER_INVALID")
    folded = [header.casefold() for header in headers]
    if len(folded) != len(set(folded)):
        raise ImportFileError("IMPORT_DUPLICATE_HEADERS")
    if any(unicodedata.category(char)[0] == "C" for header in headers for char in header):
        raise ImportFileError("IMPORT_HEADER_INVALID")
    if any(len(header) > 128 for header in headers):
        raise ImportFileError("IMPORT_HEADER_TOO_LONG")
    return headers


def _rows_from_matrix(
    matrix: Any, headers: list[str], max_rows: int, max_cells: int
) -> list[tuple[int, dict[str, Any]]]:
    result: list[tuple[int, dict[str, Any]]] = []
    for row_number, values in enumerate(matrix, start=2):
        cells = list(values)
        if len(cells) > len(headers) and any(
            value not in (None, "") for value in cells[len(headers) :]
        ):
            raise ImportFileError("IMPORT_ROW_TOO_WIDE")
        cells = cells[: len(headers)]
        if not any(value not in (None, "") for value in cells):
            continue
        result.append(
            (
                row_number,
                {
                    header: _safe_cell(cells[i] if i < len(cells) else None)
                    for i, header in enumerate(headers)
                },
            )
        )
        if len(result) > max_rows:
            raise ImportFileError("IMPORT_TOO_MANY_ROWS")
        if len(result) * len(headers) > max_cells:
            raise ImportFileError("IMPORT_TOO_MANY_CELLS")
    return result


def _parse_csv(data: bytes, max_rows: int, max_columns: int, max_cells: int) -> ParsedImportFile:
    if b"\x00" in data:
        raise ImportFileError("IMPORT_ENCODING_INVALID")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1256")
        except UnicodeDecodeError as exc:
            raise ImportFileError("IMPORT_ENCODING_INVALID") from exc
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect, strict=True)
    try:
        header_values = tuple(next(reader))
    except StopIteration as exc:
        raise ImportFileError("IMPORT_EMPTY_FILE") from exc
    headers = _headers(header_values, max_columns)
    result: list[tuple[int, dict[str, Any]]] = []
    try:
        for row_number, values in enumerate(reader, start=2):
            if len(values) > len(headers) and any(
                value.strip() for value in values[len(headers) :]
            ):
                raise ImportFileError("IMPORT_ROW_TOO_WIDE")
            if not any(value.strip() for value in values):
                continue
            cells = values[: len(headers)]
            result.append(
                (
                    row_number,
                    {
                        header: cells[i].strip() if i < len(cells) else None
                        for i, header in enumerate(headers)
                    },
                )
            )
            if len(result) > max_rows:
                raise ImportFileError("IMPORT_TOO_MANY_ROWS")
            if len(result) * len(headers) > max_cells:
                raise ImportFileError("IMPORT_TOO_MANY_CELLS")
    except csv.Error as exc:
        raise ImportFileError("IMPORT_CSV_INVALID") from exc
    return ParsedImportFile(headers=headers, rows=result, sheet_name=None)


def _validate_xlsx_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > 2000:
                raise ImportFileError("IMPORT_ARCHIVE_LIMIT")
            total_uncompressed = 0
            for info in infos:
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or "../" in name or info.flag_bits & 0x1:
                    raise ImportFileError("IMPORT_ARCHIVE_INVALID")
                total_uncompressed += info.file_size
                if info.file_size > 1_000_000 and info.file_size / max(info.compress_size, 1) > 100:
                    raise ImportFileError("IMPORT_ARCHIVE_RATIO_LIMIT")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ImportFileError("IMPORT_ARCHIVE_INVALID")
            if total_uncompressed > 100 * 1024 * 1024:
                raise ImportFileError("IMPORT_ARCHIVE_SIZE_LIMIT")
            names = {info.filename.casefold() for info in infos}
            if any(name.endswith("vbaproject.bin") for name in names):
                raise ImportFileError("IMPORT_MACRO_NOT_ALLOWED")
            if any(name.startswith("xl/externallinks/") for name in names):
                raise ImportFileError("IMPORT_EXTERNAL_LINKS_NOT_ALLOWED")
            if "[content_types].xml" not in names or "xl/workbook.xml" not in names:
                raise ImportFileError("IMPORT_XLSX_INVALID")
    except zipfile.BadZipFile as exc:
        raise ImportFileError("IMPORT_XLSX_INVALID") from exc


def _parse_xlsx(
    data: bytes, max_rows: int, max_columns: int, max_cells: int, requested_sheet: str | None
) -> ParsedImportFile:
    _validate_xlsx_archive(data)
    workbook = None
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        worksheets = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"]
        if any(sheet.max_row is not None and sheet.max_row > max_rows + 1 for sheet in worksheets):
            raise ImportFileError("IMPORT_TOO_MANY_ROWS")
        if any(
            sheet.max_column is not None and sheet.max_column > max_columns for sheet in worksheets
        ):
            raise ImportFileError("IMPORT_TOO_MANY_COLUMNS")
        if not worksheets:
            raise ImportFileError("IMPORT_SHEET_NOT_FOUND")
        if requested_sheet is None:
            sheet = worksheets[0]
        else:
            sheet = next((item for item in worksheets if item.title == requested_sheet), None)
            if sheet is None:
                raise ImportFileError("IMPORT_SHEET_NOT_FOUND")
        iterator = sheet.iter_rows(values_only=True)
        try:
            header_values = tuple(next(iterator))
        except StopIteration as exc:
            raise ImportFileError("IMPORT_EMPTY_FILE") from exc
        headers = _headers(header_values, max_columns)
        return ParsedImportFile(
            headers=headers,
            rows=_rows_from_matrix(iterator, headers, max_rows, max_cells),
            sheet_name=sheet.title,
        )
    except ImportFileError:
        raise
    except Exception as exc:
        raise ImportFileError("IMPORT_XLSX_INVALID") from exc
    finally:
        if workbook is not None:
            workbook.close()


def parse_import_file(
    filename: str,
    content_type: str | None,
    data: bytes,
    *,
    max_rows: int,
    max_columns: int,
    max_cells: int = 1_000_000,
    requested_sheet: str | None = None,
) -> ParsedImportFile:
    extension = PurePath(filename.replace("\\", "/")).suffix.casefold()
    mime = (content_type or "").split(";", 1)[0].strip().casefold()
    if extension == ".csv":
        if mime not in {
            "",
            "text/csv",
            "application/csv",
            "application/vnd.ms-excel",
            "text/plain",
            "application/octet-stream",
        }:
            raise ImportFileError("IMPORT_MIME_NOT_ALLOWED")
        return _parse_csv(data, max_rows, max_columns, max_cells)
    if extension == ".xlsx":
        if mime not in {
            "",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        }:
            raise ImportFileError("IMPORT_MIME_NOT_ALLOWED")
        if not data.startswith(b"PK\x03\x04"):
            raise ImportFileError("IMPORT_MAGIC_INVALID")
        return _parse_xlsx(data, max_rows, max_columns, max_cells, requested_sheet)
    raise ImportFileError("IMPORT_EXTENSION_NOT_ALLOWED")


def validate_mapping(kind: str, mapping: dict[str, str | None], headers: list[str]) -> None:
    fields = PRODUCT_FIELDS if kind == "products" else SUPPLIER_PRICE_FIELDS
    required = REQUIRED_FIELDS[kind]
    if set(mapping) - fields or not required.issubset(mapping):
        raise ImportFileError("IMPORT_MAPPING_INVALID")
    selected: list[str] = []
    for field, header in mapping.items():
        if header is None:
            if field in required:
                raise ImportFileError("IMPORT_MAPPING_REQUIRED")
            continue
        if header not in headers:
            raise ImportFileError("IMPORT_MAPPING_HEADER_NOT_FOUND")
        selected.append(header.casefold())
    if len(selected) != len(set(selected)):
        raise ImportFileError("IMPORT_MAPPING_DUPLICATE_COLUMN")


def _value(raw: dict[str, Any], mapping: dict[str, str | None], field: str) -> Any:
    header = mapping.get(field)
    return raw.get(header) if header else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _money(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        raise ValueError("MONEY_INVALID")
    raw = str(value).strip().translate(PERSIAN_DIGITS)
    raw = raw.replace("٬", "").replace(",", "").replace("٫", ".").replace("−", "-").replace(" ", "")
    if not raw:
        raise ValueError("MONEY_INVALID")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("MONEY_INVALID") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("999999999999999999.99"):
        raise ValueError("MONEY_RANGE")
    if amount.quantize(Decimal("0.01")) != amount:
        raise ValueError("MONEY_SCALE")
    return format(amount, ".2f")


def _unit(value: Any) -> str:
    raw = _text(value)
    if raw is None:
        raise ValueError("UNIT_REQUIRED")
    normalized = PERSIAN_UNITS.get(raw, raw.casefold())
    if normalized not in ALLOWED_UNITS:
        raise ValueError("UNIT_INVALID")
    return normalized


def _boolean(value: Any) -> bool:
    raw = str(value).strip().casefold().translate(PERSIAN_DIGITS)
    if raw in {"1", "true", "yes", "y", "فعال", "بله"}:
        return True
    if raw in {"0", "false", "no", "n", "غیرفعال", "خیر"}:
        return False
    raise ValueError("BOOLEAN_INVALID")


def _error(field: str, code: str, message: str) -> dict[str, str]:
    return {"field": field, "code": code, "message_fa": message}


def normalize_import_row(
    kind: str, raw: dict[str, Any], mapping: dict[str, str | None], tenant_currency: str
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    if kind == "products":
        normalized: dict[str, Any] = {}
        for field, maximum, label in (("sku", 100, "شناسه کالا"), ("name", 200, "نام کالا")):
            value = _text(_value(raw, mapping, field))
            if value is None:
                errors.append(_error(field, "FIELD_REQUIRED", f"{label} الزامی است."))
            elif len(value) > maximum:
                errors.append(_error(field, "FIELD_TOO_LONG", f"طول {label} بیش از حد مجاز است."))
            else:
                normalized[field] = value
        try:
            normalized["unit"] = _unit(_value(raw, mapping, "unit"))
        except ValueError as exc:
            errors.append(_error("unit", str(exc), "واحد کالا نامعتبر یا خالی است."))
        description = _text(_value(raw, mapping, "description"))
        if description is not None:
            normalized["description"] = description
        for field in ("sale_price", "purchase_cost"):
            value = _text(_value(raw, mapping, field))
            if value is not None:
                try:
                    normalized[field] = _money(value)
                except ValueError as exc:
                    errors.append(
                        _error(
                            field,
                            str(exc),
                            "مبلغ نامعتبر است؛ مبلغ باید غیرمنفی و حداکثر دو رقم اعشار داشته باشد.",
                        )
                    )
        active_value = _text(_value(raw, mapping, "is_active"))
        if active_value is not None:
            try:
                normalized["is_active"] = _boolean(active_value)
            except ValueError as exc:
                errors.append(_error("is_active", str(exc), "وضعیت فعال بودن نامعتبر است."))
        else:
            normalized["is_active"] = True
        return (normalized if not errors else None), errors

    normalized = {}
    raw_name = _text(_value(raw, mapping, "raw_name"))
    if raw_name is None:
        errors.append(
            _error("raw_name", "FIELD_REQUIRED", "نام کالا در فایل تأمین‌کننده الزامی است.")
        )
    elif len(raw_name) > 250:
        errors.append(_error("raw_name", "FIELD_TOO_LONG", "نام کالا بیش از حد مجاز است."))
    else:
        normalized["raw_name"] = raw_name
    sku = _text(_value(raw, mapping, "sku"))
    if sku is not None:
        if len(sku) > 100:
            errors.append(_error("sku", "FIELD_TOO_LONG", "شناسه کالا بیش از حد مجاز است."))
        else:
            normalized["sku"] = sku
    try:
        normalized["unit_price"] = _money(_value(raw, mapping, "unit_price"))
    except ValueError as exc:
        errors.append(
            _error(
                "unit_price",
                str(exc),
                "قیمت نامعتبر است؛ قیمت باید غیرمنفی و حداکثر دو رقم اعشار داشته باشد.",
            )
        )
    try:
        normalized["unit"] = _unit(_value(raw, mapping, "unit"))
    except ValueError as exc:
        errors.append(_error("unit", str(exc), "واحد کالا نامعتبر یا خالی است."))
    currency = (_text(_value(raw, mapping, "currency")) or tenant_currency).upper()
    if currency not in {"IRT", "IRR"}:
        errors.append(_error("currency", "CURRENCY_INVALID", "واحد پول نامعتبر است."))
    elif currency != tenant_currency:
        errors.append(
            _error(
                "currency", "CURRENCY_MISMATCH", "واحد پول فایل با واحد پول فضای کاری یکسان نیست."
            )
        )
    else:
        normalized["currency"] = currency
    return (normalized if not errors else None), errors


def validate_duplicates(
    kind: str,
    normalized_rows: list[tuple[int, dict[str, Any] | None, list[dict[str, str]]]],
    existing_skus: set[str],
) -> list[tuple[int, dict[str, Any] | None, str, list[dict[str, str]]]]:
    seen: set[str] = set()
    result: list[tuple[int, dict[str, Any] | None, str, list[dict[str, str]]]] = []
    for row_number, normalized, errors in normalized_rows:
        duplicate = False
        field = "sku"
        message = "شناسه کالا در فضای کاری یا همین فایل تکراری است."
        if normalized is not None:
            if kind == "products":
                key = str(normalized["sku"])
                duplicate = key in existing_skus or key in seen
            else:
                sku = normalized.get("sku")
                key = f"sku:{sku}" if sku else f"name:{normalized['raw_name']}"
                duplicate = key in seen
                field = "sku" if sku else "raw_name"
                message = "ردیف قیمت در همین فایل تکراری است."
            seen.add(key)
        row_errors = list(errors)
        if duplicate:
            row_errors.append(_error(field, "DUPLICATE_ROW", message))
        status = "duplicate" if duplicate and not errors else ("error" if row_errors else "valid")
        result.append((row_number, normalized if not row_errors else None, status, row_errors))
    return result
