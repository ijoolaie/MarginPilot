from __future__ import annotations

import io
import zipfile
from datetime import datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.modules.imports.router import _safe_spreadsheet_value
from app.modules.imports.service import (
    ImportFileError,
    normalize_import_row,
    parse_import_file,
    validate_duplicates,
    validate_mapping,
)


def _xlsx_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_csv_parser_handles_semicolon_and_persian_utf8() -> None:
    data = "شناسه;نام;واحد;قیمت\nP-1;جعبه;عدد;۱۲۵۰٫۵۰\n".encode("utf-8-sig")
    parsed = parse_import_file("products.csv", "text/csv", data, max_rows=10, max_columns=10)
    assert parsed.headers == ["شناسه", "نام", "واحد", "قیمت"]
    assert parsed.rows == [(2, {"شناسه": "P-1", "نام": "جعبه", "واحد": "عدد", "قیمت": "۱۲۵۰٫۵۰"})]
    assert parsed.sheet_name is None


def test_csv_parser_supports_cp1256() -> None:
    data = "sku,name\nP-1,کالا\n".encode("cp1256")
    parsed = parse_import_file(
        "products.csv", "application/vnd.ms-excel", data, max_rows=10, max_columns=10
    )
    assert parsed.rows[0][1]["name"] == "کالا"


def test_csv_rejects_duplicate_headers_and_excess_rows() -> None:
    with pytest.raises(ImportFileError, match="IMPORT_DUPLICATE_HEADERS"):
        parse_import_file("x.csv", "text/csv", b"SKU,sku\n1,2\n", max_rows=10, max_columns=10)
    with pytest.raises(ImportFileError, match="IMPORT_TOO_MANY_ROWS"):
        parse_import_file("x.csv", "text/csv", b"sku,name\n1,a\n2,b\n", max_rows=1, max_columns=10)


def test_csv_rejects_binary_and_unsupported_mime() -> None:
    with pytest.raises(ImportFileError, match="IMPORT_ENCODING_INVALID"):
        parse_import_file("x.csv", "text/csv", b"sku\x00name", max_rows=10, max_columns=10)
    with pytest.raises(ImportFileError, match="IMPORT_MIME_NOT_ALLOWED"):
        parse_import_file("x.csv", "application/pdf", b"sku,name\n", max_rows=10, max_columns=10)
    with pytest.raises(ImportFileError, match="IMPORT_EXTENSION_NOT_ALLOWED"):
        parse_import_file(
            "x.xlsm", "application/octet-stream", b"PK\x03\x04", max_rows=10, max_columns=10
        )


def test_xlsx_parser_uses_visible_sheet_and_safe_values() -> None:
    data = _xlsx_bytes(
        [["SKU", "Name", "Price", "Created"], ["P-1", "Tape", 12.5, datetime(2026, 1, 2)]]
    )
    parsed = parse_import_file(
        "products.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data,
        max_rows=10,
        max_columns=10,
    )
    assert parsed.sheet_name == "Sheet"
    assert parsed.rows[0][1] == {
        "SKU": "P-1",
        "Name": "Tape",
        "Price": 12.5,
        "Created": "2026-01-02T00:00:00",
    }


def test_xlsx_rejects_macros_and_zip_bombs() -> None:
    original = _xlsx_bytes([["SKU"], ["P-1"]])
    macro = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(original)) as source,
        zipfile.ZipFile(macro, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            target.writestr(item.filename, source.read(item.filename))
        target.writestr("xl/vbaProject.bin", b"macro")
    with pytest.raises(ImportFileError, match="IMPORT_MACRO_NOT_ALLOWED"):
        parse_import_file(
            "x.xlsx", "application/octet-stream", macro.getvalue(), max_rows=10, max_columns=10
        )

    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "ok")
        archive.writestr("xl/workbook.xml", "ok")
        archive.writestr("xl/worksheets/sheet1.xml", "0" * 2_000_000)
    with pytest.raises(ImportFileError, match="IMPORT_ARCHIVE_RATIO_LIMIT"):
        parse_import_file(
            "x.xlsx", "application/octet-stream", bomb.getvalue(), max_rows=10, max_columns=10
        )


def test_mapping_requires_known_unique_columns_and_required_fields() -> None:
    validate_mapping(
        "products", {"sku": "SKU", "name": "Name", "unit": "Unit"}, ["SKU", "Name", "Unit"]
    )
    with pytest.raises(ImportFileError, match="IMPORT_MAPPING_HEADER_NOT_FOUND"):
        validate_mapping(
            "products", {"sku": "SKU", "name": "Missing", "unit": "Unit"}, ["SKU", "Name", "Unit"]
        )
    with pytest.raises(ImportFileError, match="IMPORT_MAPPING_DUPLICATE_COLUMN"):
        validate_mapping("products", {"sku": "SKU", "name": "SKU", "unit": "Unit"}, ["SKU", "Unit"])
    with pytest.raises(ImportFileError, match="IMPORT_MAPPING_INVALID"):
        validate_mapping(
            "products",
            {"sku": "SKU", "name": "Name", "unit": "Unit", "supplier_id": "ID"},
            ["SKU", "Name", "Unit", "ID"],
        )


def test_product_normalization_uses_decimal_and_persian_units() -> None:
    mapping = {
        "sku": "کد",
        "name": "نام",
        "unit": "واحد",
        "purchase_cost": "خرید",
        "sale_price": "فروش",
        "is_active": "فعال",
    }
    normalized, errors = normalize_import_row(
        "products",
        {
            "کد": "P-1",
            "نام": "کالا",
            "واحد": "عدد",
            "خرید": "۱٬۲۵۰٫۵۰",
            "فروش": "2000",
            "فعال": "بله",
        },
        mapping,
        "IRT",
    )
    assert errors == []
    assert normalized == {
        "sku": "P-1",
        "name": "کالا",
        "unit": "piece",
        "purchase_cost": "1250.50",
        "sale_price": "2000.00",
        "is_active": True,
    }
    assert Decimal(normalized["purchase_cost"]) == Decimal("1250.50")


def test_supplier_price_normalization_rejects_currency_and_decimal_scale() -> None:
    mapping = {"raw_name": "نام", "unit_price": "قیمت", "unit": "واحد", "currency": "ارز"}
    normalized, errors = normalize_import_row(
        "supplier_prices",
        {"نام": "کالا", "قیمت": "10.123", "واحد": "kg", "ارز": "IRR"},
        mapping,
        "IRT",
    )
    assert normalized is None
    assert {item["code"] for item in errors} == {"MONEY_SCALE", "CURRENCY_MISMATCH"}


def test_duplicate_validation_matches_exact_database_uniqueness() -> None:
    rows = [
        (2, {"sku": "A-1", "name": "One"}, []),
        (3, {"sku": "A-1", "name": "Two"}, []),
        (4, {"sku": "B-1", "name": "Three"}, []),
    ]
    result = validate_duplicates("products", rows, {"b-1"})
    assert [item[2] for item in result] == ["valid", "duplicate", "valid"]


def test_error_report_neutralizes_spreadsheet_formulas() -> None:
    assert (
        _safe_spreadsheet_value('=HYPERLINK("https://example.test")')
        == '\'=HYPERLINK("https://example.test")'
    )
    assert _safe_spreadsheet_value("-1") == "'-1"
    assert _safe_spreadsheet_value("normal text") == "normal text"


def test_csv_and_xlsx_enforce_total_cell_limit() -> None:
    with pytest.raises(ImportFileError, match="IMPORT_TOO_MANY_CELLS"):
        parse_import_file(
            "x.csv",
            "text/csv",
            b"sku,name\n1,a\n2,b\n",
            max_rows=10,
            max_columns=10,
            max_cells=2,
        )
    data = _xlsx_bytes([["sku", "name"], ["1", "a"], ["2", "b"]])
    with pytest.raises(ImportFileError, match="IMPORT_TOO_MANY_CELLS"):
        parse_import_file(
            "x.xlsx",
            "application/octet-stream",
            data,
            max_rows=10,
            max_columns=10,
            max_cells=2,
        )
