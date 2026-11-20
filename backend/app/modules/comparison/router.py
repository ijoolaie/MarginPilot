"""Tenant-scoped supplier price comparison API."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.modules.audit.models import IdempotencyKey
from app.modules.catalog.models import Product, Supplier, SupplierPrice, SupplierPriceList
from app.modules.catalog.service import add_audit, lock_tenant
from app.modules.comparison.models import ComparisonMatch, ComparisonRun
from app.modules.comparison.service import (
    PriceItem,
    build_comparison,
    calculate_price_delta,
    summarize_matches,
)
from app.modules.tenancy.dependencies import TenantContext, require_permission

router = APIRouter(prefix="/comparison", tags=["comparison"])


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComparisonCreate(InputModel):
    base_list_id: int = Field(gt=0)
    target_list_id: int = Field(gt=0)
    match_strategy: Literal["sku", "normalized_name", "sku_then_name"] = "sku_then_name"

    @model_validator(mode="after")
    def distinct_lists(self) -> ComparisonCreate:
        if self.base_list_id == self.target_list_id:
            raise ValueError("base and target price lists must differ")
        return self


class MatchDecision(InputModel):
    match_id: int = Field(gt=0)
    decision: Literal["confirm", "reject"]
    product_id: int | None = Field(default=None, gt=0)
    peer_price_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def product_for_confirmation(self) -> MatchDecision:
        if self.decision == "confirm" and self.product_id is None:
            raise ValueError("product_id is required for confirmation")
        if self.decision == "reject" and (
            self.product_id is not None or self.peer_price_id is not None
        ):
            raise ValueError("product_id and peer_price_id are not accepted for rejection")
        return self


class ConfirmMatches(InputModel):
    decisions: list[MatchDecision] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_match_ids(self) -> ConfirmMatches:
        ids = [item.match_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("match_id values must be unique")
        return self


def _run_data(run: ComparisonRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "base_list_id": run.base_list_id,
        "target_list_id": run.target_list_id,
        "match_strategy": run.match_strategy,
        "status": run.status,
        "summary": run.summary,
        "created_at": run.created_at.isoformat(),
    }


def _price_data(price: SupplierPrice | None) -> dict[str, Any] | None:
    if price is None:
        return None
    return {
        "id": price.id,
        "sku": price.sku,
        "raw_name": price.raw_name,
        "unit_price": str(price.unit_price),
        "unit": price.unit,
        "currency": price.currency,
    }


def _match_data(match: ComparisonMatch, prices: dict[int, SupplierPrice]) -> dict[str, Any]:
    base_price = prices.get(match.base_price_id) if match.base_price_id is not None else None
    target_price = prices.get(match.target_price_id) if match.target_price_id is not None else None
    return {
        "id": match.id,
        "base_price_id": match.base_price_id,
        "target_price_id": match.target_price_id,
        "base_raw_name": match.base_raw_name,
        "target_raw_name": match.target_raw_name,
        "base_price": _price_data(base_price),
        "target_price": _price_data(target_price),
        "match_type": match.match_type,
        "status": match.status,
        "suggested_product_id": match.suggested_product_id,
        "confirmed_product_id": match.confirmed_product_id,
        "price_delta": str(match.price_delta) if match.price_delta is not None else None,
        "price_delta_pct": str(match.price_delta_pct)
        if match.price_delta_pct is not None
        else None,
    }


def _validate_idempotency_key(value: str | None) -> str:
    if value is None or not value.strip() or len(value) > 255 or any(ord(c) < 32 for c in value):
        raise HTTPException(status_code=422, detail="IDEMPOTENCY_KEY_REQUIRED")
    return value


def _reserve_idempotency(
    context: TenantContext, *, key: str, operation: str, request_hash: str
) -> tuple[int, JSONResponse | None]:
    db = context.auth.db
    settings = get_settings()
    now = func.clock_timestamp()
    statement = (
        pg_insert(IdempotencyKey)
        .values(
            tenant_id=context.tenant.id,
            user_id=context.auth.user.id,
            idempotency_key=key,
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
    inserted_id = db.scalar(statement)
    if inserted_id is not None:
        return inserted_id, None
    idem = db.scalar(
        select(IdempotencyKey)
        .where(
            IdempotencyKey.tenant_id == context.tenant.id,
            IdempotencyKey.user_id == context.auth.user.id,
            IdempotencyKey.idempotency_key == key,
        )
        .with_for_update()
    )
    if idem is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
    expired = db.scalar(
        select(IdempotencyKey.id).where(
            IdempotencyKey.id == idem.id,
            IdempotencyKey.expires_at <= func.clock_timestamp(),
        )
    )
    if expired is not None:
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
        return idem.id, None
    if idem.operation != operation or idem.request_hash != request_hash:
        db.rollback()
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
    if idem.response_status is not None and idem.response_body is not None:
        replay = JSONResponse(status_code=idem.response_status, content=idem.response_body)
        db.commit()
        return idem.id, replay
    db.rollback()
    raise HTTPException(status_code=409, detail="IDEMPOTENCY_IN_PROGRESS")


def _price_items(db: Any, tenant_id: int, list_id: int) -> list[PriceItem]:
    rows = db.execute(
        select(
            SupplierPrice.id,
            SupplierPrice.raw_name,
            SupplierPrice.sku,
            SupplierPrice.unit_price,
            SupplierPrice.unit,
            SupplierPrice.product_id,
        )
        .where(SupplierPrice.tenant_id == tenant_id, SupplierPrice.price_list_id == list_id)
        .order_by(SupplierPrice.id)
    ).all()
    return [
        PriceItem(
            id=row.id,
            raw_name=row.raw_name,
            sku=row.sku,
            unit_price=row.unit_price,
            unit=row.unit,
            product_id=row.product_id,
        )
        for row in rows
    ]


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_comparison(
    payload: ComparisonCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: TenantContext = Depends(require_permission("comparison:write")),
) -> JSONResponse:
    db = context.auth.db
    key = _validate_idempotency_key(idempotency_key)
    operation = "comparison.run.create"
    request_hash = hashlib.sha256(
        json.dumps(
            {"method": "POST", "path": request.url.path, "body": payload.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    lock_tenant(db, context.tenant.id)
    idempotency_id, replay = _reserve_idempotency(
        context, key=key, operation=operation, request_hash=request_hash
    )
    if replay is not None:
        return replay

    lists = db.scalars(
        select(SupplierPriceList)
        .where(
            SupplierPriceList.tenant_id == context.tenant.id,
            SupplierPriceList.id.in_([payload.base_list_id, payload.target_list_id]),
        )
        .order_by(SupplierPriceList.id)
        .with_for_update()
    ).all()
    if len(lists) != 2:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    by_id = {item.id: item for item in lists}
    base_list = by_id[payload.base_list_id]
    target_list = by_id[payload.target_list_id]
    if base_list.status != "final" or target_list.status != "final":
        raise HTTPException(status_code=409, detail="PRICE_LIST_NOT_FINAL")

    settings = get_settings()
    counts = db.execute(
        select(SupplierPrice.price_list_id, func.count(SupplierPrice.id))
        .where(
            SupplierPrice.tenant_id == context.tenant.id,
            SupplierPrice.price_list_id.in_([base_list.id, target_list.id]),
        )
        .group_by(SupplierPrice.price_list_id)
    ).all()
    if any(count > settings.comparison_max_rows_per_list for _, count in counts):
        raise HTTPException(status_code=422, detail="COMPARISON_LIST_TOO_LARGE")
    currency_mismatches = (
        db.scalar(
            select(func.count(SupplierPrice.id)).where(
                SupplierPrice.tenant_id == context.tenant.id,
                SupplierPrice.price_list_id.in_([base_list.id, target_list.id]),
                SupplierPrice.currency != context.tenant.currency_code,
            )
        )
        or 0
    )
    if currency_mismatches:
        raise HTTPException(status_code=409, detail="PRICE_LIST_CURRENCY_MISMATCH")

    base_items = _price_items(db, context.tenant.id, base_list.id)
    target_items = _price_items(db, context.tenant.id, target_list.id)
    if not base_items or not target_items:
        raise HTTPException(status_code=422, detail="PRICE_LIST_EMPTY")
    match_results, summary = build_comparison(base_items, target_items, payload.match_strategy)
    run_status = (
        "pending_confirmation"
        if any(item.status == "pending" for item in match_results)
        else "completed"
    )
    run = ComparisonRun(
        tenant_id=context.tenant.id,
        created_by=context.auth.user.id,
        base_list_id=base_list.id,
        target_list_id=target_list.id,
        match_strategy=payload.match_strategy,
        status=run_status,
        summary=summary,
    )
    db.add(run)
    try:
        db.flush()
        db.add_all(
            [
                ComparisonMatch(
                    tenant_id=context.tenant.id,
                    run_id=run.id,
                    base_price_id=item.base_price_id,
                    target_price_id=item.target_price_id,
                    base_raw_name=item.base_raw_name,
                    target_raw_name=item.target_raw_name,
                    match_type=item.match_type,
                    status=item.status,
                    suggested_product_id=item.suggested_product_id,
                    confirmed_product_id=item.confirmed_product_id,
                    price_delta=item.price_delta,
                    price_delta_pct=item.price_delta_pct,
                )
                for item in match_results
            ]
        )
        response_body = {
            "data": {
                **_run_data(run),
                "pending_matches": sum(item.status == "pending" for item in match_results),
            },
        }
        idem = db.get(IdempotencyKey, idempotency_id)
        if idem is None:
            raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
        idem.response_status = status.HTTP_201_CREATED
        idem.response_body = response_body
        add_audit(
            db,
            request,
            user_id=context.auth.user.id,
            tenant_id=context.tenant.id,
            action="comparison.run.created",
            entity_type="comparison_run",
            entity_id=run.id,
            detail={
                "base_list_id": base_list.id,
                "target_list_id": target_list.id,
                "match_strategy": payload.match_strategy,
                "summary": summary,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response_body)


@router.get("/runs")
def list_comparisons(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    context: TenantContext = Depends(require_permission("comparison:read")),
) -> dict[str, Any]:
    db = context.auth.db
    base = select(ComparisonRun).where(ComparisonRun.tenant_id == context.tenant.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(ComparisonRun.created_at.desc(), ComparisonRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [_run_data(item) for item in rows],
        "meta": {"page": page, "page_size": page_size, "total_items": total},
    }


@router.get("/runs/{run_id}")
def get_comparison(
    run_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    match_status: Literal["pending", "confirmed", "rejected"] | None = Query(default=None),
    context: TenantContext = Depends(require_permission("comparison:read")),
) -> dict[str, Any]:
    db = context.auth.db
    run = db.scalar(
        select(ComparisonRun).where(
            ComparisonRun.id == run_id, ComparisonRun.tenant_id == context.tenant.id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    query = select(ComparisonMatch).where(
        ComparisonMatch.tenant_id == context.tenant.id,
        ComparisonMatch.run_id == run.id,
    )
    if match_status is not None:
        query = query.where(ComparisonMatch.status == match_status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    matches = db.scalars(
        query.order_by(ComparisonMatch.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    price_ids = {
        price_id
        for item in matches
        for price_id in (item.base_price_id, item.target_price_id)
        if price_id is not None
    }
    price_rows = (
        db.scalars(
            select(SupplierPrice).where(
                SupplierPrice.tenant_id == context.tenant.id,
                SupplierPrice.id.in_(price_ids),
            )
        ).all()
        if price_ids
        else []
    )
    prices = {item.id: item for item in price_rows}
    list_rows = db.execute(
        select(
            SupplierPriceList.id,
            SupplierPriceList.title,
            SupplierPriceList.received_at,
            SupplierPriceList.supplier_id,
            Supplier.name,
        )
        .join(
            Supplier,
            (Supplier.tenant_id == SupplierPriceList.tenant_id)
            & (Supplier.id == SupplierPriceList.supplier_id),
        )
        .where(
            SupplierPriceList.tenant_id == context.tenant.id,
            SupplierPriceList.id.in_([run.base_list_id, run.target_list_id]),
        )
    ).all()
    list_data = {
        item.id: {
            "id": item.id,
            "title": item.title,
            "received_at": item.received_at.isoformat(),
            "supplier": {"id": item.supplier_id, "name": item.name},
        }
        for item in list_rows
    }
    return {
        "data": {
            **_run_data(run),
            "base_list": list_data[run.base_list_id],
            "target_list": list_data[run.target_list_id],
            "matches": [_match_data(item, prices) for item in matches],
        },
        "meta": {"page": page, "page_size": page_size, "total_items": total},
    }


@router.post("/runs/{run_id}/confirm-matches")
def confirm_matches(
    run_id: int,
    payload: ConfirmMatches,
    request: Request,
    context: TenantContext = Depends(require_permission("comparison:write")),
) -> dict[str, Any]:
    db = context.auth.db
    lock_tenant(db, context.tenant.id)
    run = db.scalar(
        select(ComparisonRun)
        .where(ComparisonRun.id == run_id, ComparisonRun.tenant_id == context.tenant.id)
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")

    decision_ids = [item.match_id for item in payload.decisions]
    matches = db.scalars(
        select(ComparisonMatch)
        .where(
            ComparisonMatch.tenant_id == context.tenant.id,
            ComparisonMatch.run_id == run.id,
            ComparisonMatch.id.in_(decision_ids),
        )
        .order_by(ComparisonMatch.id)
        .with_for_update()
    ).all()
    if len(matches) != len(decision_ids):
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    by_id = {item.id: item for item in matches}
    confirmed = 0
    rejected = 0

    for decision in payload.decisions:
        match = by_id[decision.match_id]
        if match.status != "pending":
            same_replay = (
                decision.decision == "confirm"
                and match.status == "confirmed"
                and match.confirmed_product_id == decision.product_id
                and (
                    decision.peer_price_id is None
                    or decision.peer_price_id in {match.base_price_id, match.target_price_id}
                )
            ) or (decision.decision == "reject" and match.status == "rejected")
            if same_replay:
                continue
            raise HTTPException(status_code=409, detail="MATCH_STATE_INVALID")

        if decision.decision == "reject":
            if (
                match.match_type == "uncertain"
                and match.base_price_id is not None
                and match.target_price_id is not None
            ):
                price_rows = db.scalars(
                    select(SupplierPrice)
                    .where(
                        SupplierPrice.tenant_id == context.tenant.id,
                        SupplierPrice.id.in_([match.base_price_id, match.target_price_id]),
                    )
                    .order_by(SupplierPrice.id)
                    .with_for_update()
                ).all()
                if len(price_rows) != 2:
                    raise HTTPException(status_code=404, detail="NOT_FOUND")
                price_by_id = {item.id: item for item in price_rows}
                base_price = price_by_id[match.base_price_id]
                target_price = price_by_id[match.target_price_id]
                target_only = ComparisonMatch(
                    tenant_id=context.tenant.id,
                    run_id=run.id,
                    target_price_id=target_price.id,
                    target_raw_name=target_price.raw_name,
                    match_type="unmatched",
                    status="confirmed",
                    suggested_product_id=target_price.product_id,
                    confirmed_product_id=target_price.product_id,
                )
                match.target_price_id = None
                match.target_raw_name = None
                match.match_type = "unmatched"
                match.status = "confirmed"
                match.suggested_product_id = base_price.product_id
                match.confirmed_product_id = base_price.product_id
                match.price_delta = None
                match.price_delta_pct = None
                db.flush()
                db.add(target_only)
            else:
                match.status = "rejected"
            rejected += 1
            continue

        product = db.scalar(
            select(Product)
            .where(
                Product.tenant_id == context.tenant.id,
                Product.id == decision.product_id,
                Product.deleted_at.is_(None),
                Product.is_active.is_(True),
            )
            .with_for_update()
        )
        if product is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        if match.match_type == "uncertain" and (
            match.base_price_id is None or match.target_price_id is None
        ):
            if decision.peer_price_id is None:
                raise HTTPException(status_code=422, detail="PEER_PRICE_REQUIRED")
        elif decision.peer_price_id is not None:
            raise HTTPException(status_code=422, detail="PEER_PRICE_NOT_ALLOWED")

        if decision.peer_price_id is not None:
            expected_list_id = (
                run.target_list_id if match.base_price_id is not None else run.base_list_id
            )
            peer = db.scalars(
                select(SupplierPrice)
                .where(
                    SupplierPrice.tenant_id == context.tenant.id,
                    SupplierPrice.id == decision.peer_price_id,
                    SupplierPrice.price_list_id == expected_list_id,
                )
                .with_for_update()
            ).first()
            if peer is None:
                raise HTTPException(status_code=404, detail="NOT_FOUND")
            peer_match = db.scalars(
                select(ComparisonMatch)
                .where(
                    ComparisonMatch.tenant_id == context.tenant.id,
                    ComparisonMatch.run_id == run.id,
                    or_(
                        ComparisonMatch.base_price_id == peer.id,
                        ComparisonMatch.target_price_id == peer.id,
                    ),
                )
                .with_for_update()
            ).first()
            if peer_match is not None:
                if peer_match.id in decision_ids or peer_match.status == "rejected":
                    raise HTTPException(status_code=409, detail="PEER_PRICE_ALREADY_MATCHED")
                if peer_match.base_price_id is not None and peer_match.target_price_id is not None:
                    raise HTTPException(status_code=409, detail="PEER_PRICE_ALREADY_MATCHED")
                db.delete(peer_match)
                db.flush()
            if match.base_price_id is not None:
                match.target_price_id = peer.id
                match.target_raw_name = peer.raw_name
            else:
                match.base_price_id = peer.id
                match.base_raw_name = peer.raw_name

        price_ids = [
            value for value in (match.base_price_id, match.target_price_id) if value is not None
        ]
        price_rows = db.scalars(
            select(SupplierPrice)
            .where(
                SupplierPrice.tenant_id == context.tenant.id,
                SupplierPrice.id.in_(price_ids),
            )
            .order_by(SupplierPrice.id)
            .with_for_update()
        ).all()
        if len(price_rows) != len(price_ids):
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        for price in price_rows:
            if price.unit is None:
                raise HTTPException(status_code=422, detail="PRICE_UNIT_REQUIRED")
            if price.unit != product.unit:
                raise HTTPException(status_code=422, detail="PRODUCT_UNIT_MISMATCH")
            if price.product_id is not None and price.product_id != product.id:
                raise HTTPException(status_code=409, detail="PRICE_ALREADY_LINKED_TO_PRODUCT")
        for price in price_rows:
            price.product_id = product.id
        if match.base_price_id is not None and match.target_price_id is not None:
            base_price = next(row for row in price_rows if row.id == match.base_price_id)
            target_price = next(row for row in price_rows if row.id == match.target_price_id)
            if base_price.unit != target_price.unit:
                raise HTTPException(status_code=422, detail="PRICE_UNIT_MISMATCH")
            match.price_delta, match.price_delta_pct = calculate_price_delta(
                base_price.unit_price, target_price.unit_price
            )
        match.suggested_product_id = product.id
        match.confirmed_product_id = product.id
        match.status = "confirmed"
        confirmed += 1

    db.flush()
    all_matches = db.scalars(
        select(ComparisonMatch).where(
            ComparisonMatch.tenant_id == context.tenant.id,
            ComparisonMatch.run_id == run.id,
        )
    ).all()
    run.summary = summarize_matches(all_matches)
    pending_count = sum(item.status == "pending" for item in all_matches)
    run.status = "pending_confirmation" if pending_count else "completed"
    if confirmed or rejected:
        add_audit(
            db,
            request,
            user_id=context.auth.user.id,
            tenant_id=context.tenant.id,
            action="comparison.matches.reviewed",
            entity_type="comparison_run",
            entity_id=run.id,
            detail={"confirmed": confirmed, "rejected": rejected, "pending": pending_count},
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    return {
        "data": {
            "run_id": run.id,
            "status": run.status,
            "confirmed": confirmed,
            "rejected": rejected,
            "pending": pending_count,
        }
    }
