"""Two-phase, tenant-scoped CSV/XLSX import API."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import PurePath
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from openpyxl import Workbook  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.audit.models import IdempotencyKey
from app.modules.catalog.models import (
    Product,
    ProductVariant,
    Supplier,
    SupplierPrice,
    SupplierPriceList,
)
from app.modules.catalog.service import (
    add_audit,
    ensure_sku_available,
    lock_tenant,
    record_price_change,
)
from app.modules.imports.models import ImportBatch, ImportRow
from app.modules.imports.service import (
    ImportFileError,
    normalize_import_row,
    parse_import_file,
    validate_duplicates,
    validate_mapping,
)
from app.modules.tenancy.dependencies import TenantContext, require_permission

router = APIRouter(tags=["imports"])


class MappingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: dict[str, str | None] = Field(min_length=3, max_length=12)


def _batch_data(batch: ImportBatch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "kind": batch.kind,
        "status": batch.status,
        "file_name": batch.file_name,
        "file_hash": batch.file_hash,
        "file_size_bytes": batch.file_size_bytes,
        "mime_type": batch.mime_type,
        "sheet_name": batch.sheet_name,
        "column_headers": batch.column_headers,
        "mapping": batch.mapping,
        "stats": batch.stats,
        "supplier_id": batch.supplier_id,
        "price_list_title": batch.price_list_title,
        "received_at": batch.received_at.isoformat() if batch.received_at else None,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "confirmed_at": batch.confirmed_at.isoformat() if batch.confirmed_at else None,
    }


def _get_batch(db: Session, tenant_id: int, import_id: int, *, lock: bool = False) -> ImportBatch:
    query = select(ImportBatch).where(
        ImportBatch.id == import_id, ImportBatch.tenant_id == tenant_id
    )
    if lock:
        query = query.with_for_update()
    batch = db.scalar(query)
    if batch is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return batch


def _safe_filename(filename: str | None) -> str:
    name = re.split(r"[\\/]", filename or "upload.csv")[-1]
    name = "".join(
        char for char in name if unicodedata.category(char)[0] != "C" and char not in '<>:"|?*'
    )
    name = name.strip(" .")[:255]
    return name or "upload.csv"


def _file_error(exc: ImportFileError) -> HTTPException:
    return HTTPException(status_code=422, detail=exc.code)


@router.post("/imports", status_code=status.HTTP_201_CREATED)
def create_import(
    request: Request,
    kind: Literal["products", "supplier_prices", "sales"] = Form(...),
    file: UploadFile = File(...),
    supplier_id: int | None = Form(default=None, gt=0),
    price_list_title: str | None = Form(default=None, max_length=200),
    received_at: date | None = Form(default=None),
    sheet_name: str | None = Form(default=None, max_length=128),
    context: TenantContext = Depends(require_permission("import:execute")),
) -> dict[str, Any]:
    db = context.auth.db
    settings = get_settings()
    if kind == "sales":
        raise HTTPException(status_code=422, detail="IMPORT_KIND_NOT_READY")
    if kind == "supplier_prices":
        if supplier_id is None:
            raise HTTPException(status_code=422, detail="SUPPLIER_REQUIRED")
        if received_at is None:
            raise HTTPException(status_code=422, detail="RECEIVED_AT_REQUIRED")
        supplier = db.scalar(
            select(Supplier).where(
                Supplier.id == supplier_id,
                Supplier.tenant_id == context.tenant.id,
                Supplier.deleted_at.is_(None),
                Supplier.is_active.is_(True),
            )
        )
        if supplier is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
    elif supplier_id is not None or price_list_title is not None or received_at is not None:
        raise HTTPException(status_code=422, detail="IMPORT_METADATA_INVALID")

    max_bytes = settings.upload_max_mb * 1024 * 1024
    data = bytearray()
    try:
        while chunk := file.file.read(64 * 1024):
            if len(data) + len(chunk) > max_bytes:
                raise HTTPException(status_code=413, detail="UPLOAD_TOO_LARGE")
            data.extend(chunk)
    finally:
        file.file.close()
    if not data:
        raise HTTPException(status_code=422, detail="IMPORT_EMPTY_FILE")
    original_name = file.filename or "upload.csv"
    safe_name = _safe_filename(original_name)
    try:
        parsed = parse_import_file(
            original_name,
            file.content_type,
            bytes(data),
            max_rows=settings.import_max_rows,
            max_columns=settings.import_max_columns,
            max_cells=settings.import_max_cells,
            requested_sheet=sheet_name,
        )
    except ImportFileError as exc:
        raise _file_error(exc) from exc
    if not parsed.rows:
        raise HTTPException(status_code=422, detail="IMPORT_NO_DATA_ROWS")
    title = (
        (price_list_title or PurePath(safe_name).stem).strip()[:200]
        if kind == "supplier_prices"
        else None
    )
    if kind == "supplier_prices" and not title:
        raise HTTPException(status_code=422, detail="PRICE_LIST_TITLE_REQUIRED")

    batch = ImportBatch(
        tenant_id=context.tenant.id,
        created_by=context.auth.user.id,
        kind=kind,
        status="parsed",
        file_name=safe_name,
        file_hash=hashlib.sha256(data).hexdigest(),
        file_size_bytes=len(data),
        mime_type=(file.content_type or "application/octet-stream")[:128],
        sheet_name=parsed.sheet_name,
        column_headers=parsed.headers,
        mapping={},
        stats={
            "total_rows": len(parsed.rows),
            "valid_rows": 0,
            "error_rows": 0,
            "duplicate_rows": 0,
            "skipped_rows": 0,
            "committed_rows": 0,
        },
        supplier_id=supplier_id,
        price_list_title=title,
        received_at=received_at if kind == "supplier_prices" else None,
    )
    db.add(batch)
    try:
        db.flush()
        db.add_all(
            [
                ImportRow(
                    tenant_id=context.tenant.id, import_id=batch.id, row_number=row_number, raw=raw
                )
                for row_number, raw in parsed.rows
            ]
        )
        add_audit(
            db,
            request,
            user_id=context.auth.user.id,
            tenant_id=context.tenant.id,
            action="import.uploaded",
            entity_type="import",
            entity_id=batch.id,
            detail={
                "kind": kind,
                "file_size_bytes": len(data),
                "row_count": len(parsed.rows),
                "file_hash": batch.file_hash,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    db.refresh(batch)
    return {"data": _batch_data(batch)}


@router.get("/imports")
def list_imports(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    kind: Literal["products", "supplier_prices", "sales"] | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    context: TenantContext = Depends(require_permission("import:read")),
) -> dict[str, Any]:
    db = context.auth.db
    query = select(ImportBatch).where(ImportBatch.tenant_id == context.tenant.id)
    count_query = (
        select(func.count())
        .select_from(ImportBatch)
        .where(ImportBatch.tenant_id == context.tenant.id)
    )
    if kind:
        query = query.where(ImportBatch.kind == kind)
        count_query = count_query.where(ImportBatch.kind == kind)
    if status_filter:
        if status_filter not in {
            "uploaded",
            "parsed",
            "mapped",
            "validated",
            "awaiting_confirmation",
            "committed",
            "failed",
            "cancelled",
        }:
            raise HTTPException(status_code=422, detail="IMPORT_STATUS_INVALID")
        query = query.where(ImportBatch.status == status_filter)
        count_query = count_query.where(ImportBatch.status == status_filter)
    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [_batch_data(row) for row in rows],
        "meta": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


@router.get("/imports/{import_id}")
def get_import(
    import_id: int,
    context: TenantContext = Depends(require_permission("import:read")),
) -> dict[str, Any]:
    return {"data": _batch_data(_get_batch(context.auth.db, context.tenant.id, import_id))}


@router.patch("/imports/{import_id}/mapping")
def apply_import_mapping(
    import_id: int,
    payload: MappingPayload,
    request: Request,
    context: TenantContext = Depends(require_permission("import:execute")),
) -> dict[str, Any]:
    db = context.auth.db
    batch = _get_batch(db, context.tenant.id, import_id, lock=True)
    if batch.kind == "sales":
        raise HTTPException(status_code=422, detail="IMPORT_KIND_NOT_READY")
    if batch.status not in {"parsed", "mapped", "validated", "awaiting_confirmation"}:
        raise HTTPException(status_code=409, detail="IMPORT_STATE_INVALID")
    try:
        validate_mapping(batch.kind, payload.mapping, batch.column_headers)
    except ImportFileError as exc:
        raise _file_error(exc) from exc

    existing_skus: set[str] = set()
    if batch.kind == "products":
        existing_skus.update(
            value
            for value in db.scalars(
                select(Product.sku).where(
                    Product.tenant_id == context.tenant.id, Product.deleted_at.is_(None)
                )
            ).all()
        )
        existing_skus.update(
            value
            for value in db.scalars(
                select(ProductVariant.sku).where(
                    ProductVariant.tenant_id == context.tenant.id,
                    ProductVariant.deleted_at.is_(None),
                )
            ).all()
        )
    rows = db.scalars(
        select(ImportRow)
        .where(
            ImportRow.tenant_id == context.tenant.id,
            ImportRow.import_id == batch.id,
        )
        .order_by(ImportRow.row_number)
    ).all()
    normalized_rows = [
        (
            row.row_number,
            *normalize_import_row(
                batch.kind, row.raw, payload.mapping, context.tenant.currency_code
            ),
        )
        for row in rows
    ]
    validated = validate_duplicates(batch.kind, normalized_rows, existing_skus)
    counts = {
        "total_rows": len(validated),
        "valid_rows": 0,
        "error_rows": 0,
        "duplicate_rows": 0,
        "skipped_rows": 0,
        "committed_rows": 0,
    }
    preview: list[dict[str, Any]] = []
    for row, (row_number, normalized, row_status, errors) in zip(rows, validated, strict=True):
        row.normalized = normalized
        row.status = row_status
        row.errors = errors
        if row_status == "valid":
            counts["valid_rows"] += 1
        elif row_status == "duplicate":
            counts["duplicate_rows"] += 1
            counts["skipped_rows"] += 1
        else:
            counts["error_rows"] += 1
            counts["skipped_rows"] += 1
        if len(preview) < 25:
            preview.append(
                {
                    "row_number": row_number,
                    "status": row_status,
                    "normalized": normalized,
                    "errors": errors,
                }
            )
    batch.mapping = payload.mapping
    batch.status = "mapped"
    db.flush()
    batch.status = "validated"
    batch.stats = counts
    if counts["valid_rows"]:
        batch.status = "awaiting_confirmation"
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=context.tenant.id,
        action="import.validated",
        entity_type="import",
        entity_id=batch.id,
        detail={"kind": batch.kind, **counts},
    )
    db.commit()
    db.refresh(batch)
    return {"data": _batch_data(batch), "preview": preview}


@router.get("/imports/{import_id}/rows")
def list_import_rows(
    import_id: int,
    status_filter: Literal["pending", "valid", "error", "warning", "duplicate"] | None = Query(
        default=None, alias="status"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    context: TenantContext = Depends(require_permission("import:read")),
) -> dict[str, Any]:
    db = context.auth.db
    _get_batch(db, context.tenant.id, import_id)
    filters = [ImportRow.tenant_id == context.tenant.id, ImportRow.import_id == import_id]
    if status_filter:
        filters.append(ImportRow.status == status_filter)
    total = db.scalar(select(func.count()).select_from(ImportRow).where(*filters)) or 0
    rows = db.scalars(
        select(ImportRow)
        .where(*filters)
        .order_by(ImportRow.row_number)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [
            {
                "id": row.id,
                "row_number": row.row_number,
                "raw": row.raw,
                "normalized": row.normalized,
                "status": row.status,
                "errors": row.errors,
            }
            for row in rows
        ],
        "meta": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


def _safe_spreadsheet_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text_value = str(value)
    if text_value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text_value
    return text_value


@router.get("/imports/{import_id}/error-report.xlsx")
def download_import_error_report(
    import_id: int,
    context: TenantContext = Depends(require_permission("import:read")),
) -> StreamingResponse:
    db = context.auth.db
    _get_batch(db, context.tenant.id, import_id)
    rows = db.scalars(
        select(ImportRow)
        .where(
            ImportRow.tenant_id == context.tenant.id,
            ImportRow.import_id == import_id,
            ImportRow.status.in_(["error", "duplicate", "warning"]),
        )
        .order_by(ImportRow.row_number)
    ).all()
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Import errors")
    sheet.append(["row_number", "status", "errors", "raw_data"])
    for row in rows:
        sheet.append(
            [
                row.row_number,
                row.status,
                _safe_spreadsheet_value(json.dumps(row.errors, ensure_ascii=False)),
                _safe_spreadsheet_value(json.dumps(row.raw, ensure_ascii=False)),
            ]
        )
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="import-{import_id}-errors.xlsx"'},
    )


@router.delete("/imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import(
    import_id: int,
    request: Request,
    context: TenantContext = Depends(require_permission("import:execute")),
) -> None:
    db = context.auth.db
    batch = _get_batch(db, context.tenant.id, import_id, lock=True)
    if batch.status in {"committed", "cancelled"}:
        raise HTTPException(status_code=409, detail="IMPORT_STATE_INVALID")
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=context.tenant.id,
        action="import.deleted",
        entity_type="import",
        entity_id=batch.id,
        detail={"kind": batch.kind, "status": batch.status},
    )
    db.delete(batch)
    db.commit()


@router.post("/imports/{import_id}/confirm")
def confirm_import(
    import_id: int,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: TenantContext = Depends(require_permission("import:execute")),
) -> JSONResponse:
    db = context.auth.db
    settings = get_settings()
    if (
        idempotency_key is None
        or not idempotency_key.strip()
        or len(idempotency_key) > 255
        or any(ord(char) < 32 for char in idempotency_key)
    ):
        raise HTTPException(status_code=422, detail="IDEMPOTENCY_KEY_REQUIRED")
    lock_tenant(db, context.tenant.id)
    batch = _get_batch(db, context.tenant.id, import_id, lock=True)
    operation = "import.confirm"
    request_hash = hashlib.sha256(f"POST|{request.url.path}|{operation}|{{}}".encode()).hexdigest()
    now = func.clock_timestamp()
    insert_stmt = (
        pg_insert(IdempotencyKey)
        .values(
            tenant_id=context.tenant.id,
            user_id=context.auth.user.id,
            idempotency_key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            response_status=None,
            response_body=None,
            created_at=now,
            expires_at=now + func.make_interval(0, 0, 0, 0, settings.idempotency_ttl_hours, 0, 0),
        )
        .on_conflict_do_nothing(
            index_elements=[
                IdempotencyKey.tenant_id,
                IdempotencyKey.user_id,
                IdempotencyKey.idempotency_key,
            ]
        )
        .returning(IdempotencyKey.id)
    )
    idempotency_id = db.scalar(insert_stmt)
    if idempotency_id is None:
        idem = db.scalar(
            select(IdempotencyKey)
            .where(
                IdempotencyKey.tenant_id == context.tenant.id,
                IdempotencyKey.user_id == context.auth.user.id,
                IdempotencyKey.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        if idem is None:
            db.rollback()
            raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
        expired_id = db.scalar(
            select(IdempotencyKey.id).where(
                IdempotencyKey.id == idem.id,
                IdempotencyKey.expires_at <= func.clock_timestamp(),
            )
        )
        if expired_id is not None:
            db.execute(
                update(IdempotencyKey)
                .where(IdempotencyKey.id == idem.id)
                .values(
                    operation=operation,
                    request_hash=request_hash,
                    response_status=None,
                    response_body=None,
                    created_at=func.clock_timestamp(),
                    expires_at=func.clock_timestamp()
                    + func.make_interval(0, 0, 0, 0, settings.idempotency_ttl_hours, 0, 0),
                )
            )
            db.flush()
            db.refresh(idem)
        elif idem.operation != operation or idem.request_hash != request_hash:
            db.rollback()
            raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
        elif idem.response_status is not None and idem.response_body is not None:
            replay = JSONResponse(status_code=idem.response_status, content=idem.response_body)
            db.commit()
            return replay
        else:
            db.rollback()
            raise HTTPException(status_code=409, detail="IDEMPOTENCY_IN_PROGRESS")
        idempotency_id = idem.id
    idem = db.get(IdempotencyKey, idempotency_id)
    if idem is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
    if batch.status != "awaiting_confirmation":
        raise HTTPException(status_code=409, detail="IMPORT_STATE_INVALID")
    valid_rows = db.scalars(
        select(ImportRow)
        .where(
            ImportRow.tenant_id == context.tenant.id,
            ImportRow.import_id == batch.id,
            ImportRow.status == "valid",
        )
        .order_by(ImportRow.row_number)
        .with_for_update()
    ).all()
    if not valid_rows:
        raise HTTPException(status_code=409, detail="IMPORT_NO_VALID_ROWS")

    supplier_price_list_id: int | None = None
    try:
        if batch.kind == "products":
            for row in valid_rows:
                values = row.normalized
                if values is None:
                    raise HTTPException(status_code=409, detail="IMPORT_ROW_CORRUPT")
                ensure_sku_available(db, context.tenant.id, values["sku"])
                product = Product(
                    tenant_id=context.tenant.id,
                    sku=values["sku"],
                    name=values["name"],
                    description=values.get("description"),
                    unit=values["unit"],
                    sale_price=None,
                    purchase_cost=None,
                    is_active=values.get("is_active", True),
                )
                db.add(product)
                db.flush()
                for field, change_type in (("purchase_cost", "purchase"), ("sale_price", "sale")):
                    if field in values:
                        record_price_change(
                            db,
                            tenant_id=context.tenant.id,
                            product=product,
                            change_type=change_type,
                            new_price=Decimal(values[field]),
                            user_id=context.auth.user.id,
                            source="import",
                        )
        elif batch.kind == "supplier_prices":
            supplier = db.scalar(
                select(Supplier)
                .where(
                    Supplier.id == batch.supplier_id,
                    Supplier.tenant_id == context.tenant.id,
                    Supplier.deleted_at.is_(None),
                    Supplier.is_active.is_(True),
                )
                .with_for_update()
            )
            if supplier is None:
                raise HTTPException(status_code=404, detail="NOT_FOUND")
            price_list = SupplierPriceList(
                tenant_id=context.tenant.id,
                supplier_id=supplier.id,
                title=batch.price_list_title or batch.file_name,
                received_at=batch.received_at or date.today(),
                source="import",
                status="draft",
                created_by=context.auth.user.id,
            )
            db.add(price_list)
            db.flush()
            supplier_price_list_id = price_list.id
            for row in valid_rows:
                values = row.normalized
                if values is None:
                    raise HTTPException(status_code=409, detail="IMPORT_ROW_CORRUPT")
                db.add(
                    SupplierPrice(
                        tenant_id=context.tenant.id,
                        price_list_id=price_list.id,
                        product_id=None,
                        raw_name=values["raw_name"],
                        sku=values.get("sku"),
                        unit_price=Decimal(values["unit_price"]),
                        currency=context.tenant.currency_code,
                        unit=values["unit"],
                    )
                )
        else:
            raise HTTPException(status_code=422, detail="IMPORT_KIND_NOT_READY")

        skipped_rows = int(batch.stats.get("error_rows", 0)) + int(
            batch.stats.get("duplicate_rows", 0)
        )
        batch.status = "committed"
        batch.confirmed_at = db.scalar(select(func.clock_timestamp()))
        batch.stats = {
            **batch.stats,
            "committed_rows": len(valid_rows),
            "skipped_rows": skipped_rows,
        }
        response_body = {
            "data": {
                "id": batch.id,
                "status": batch.status,
                "kind": batch.kind,
                "committed_rows": len(valid_rows),
                "skipped_rows": skipped_rows,
                "supplier_price_list_id": supplier_price_list_id,
            }
        }
        add_audit(
            db,
            request,
            user_id=context.auth.user.id,
            tenant_id=context.tenant.id,
            action="import.committed",
            entity_type="import",
            entity_id=batch.id,
            detail={
                "kind": batch.kind,
                "committed_rows": len(valid_rows),
                "skipped_rows": skipped_rows,
                "supplier_price_list_id": supplier_price_list_id,
            },
        )
        idem.response_status = 200
        idem.response_body = response_body
        db.commit()
        return JSONResponse(status_code=200, content=response_body)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
