"""Pricing suggestion API."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from app.modules.catalog.models import Product
from app.modules.pricing.engine import FORMULA_VERSION, suggest_price
from app.modules.pricing.service import _record
from app.modules.tenancy.dependencies import TenantContext, require_permission

router = APIRouter(prefix="/pricing", tags=["pricing"])


class PriceSuggestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int | None = Field(default=None, gt=0)
    cost: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2, strict=True)
    target_margin: Decimal = Field(ge=0, lt=1, max_digits=12, decimal_places=6, strict=True)
    include_fees: bool = False

    @field_validator("cost", "target_margin", mode="before")
    @classmethod
    def parse_decimal_strings(cls, value: Any) -> Any:
        if value is None or isinstance(value, Decimal):
            return value
        if isinstance(value, str):
            try:
                return Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("invalid decimal value") from exc
        raise ValueError("financial values must be decimal strings; JSON numbers are rejected")

    @model_validator(mode="after")
    def validate_cost_source(self) -> PriceSuggestionInput:
        if (self.product_id is None) == (self.cost is None):
            raise ValueError("provide exactly one of product_id or cost")
        return self


@router.post("/suggest")
def suggest_product_price(
    payload: PriceSuggestionInput,
    context: TenantContext = Depends(require_permission("pricing:read")),
) -> dict[str, Any]:
    if payload.include_fees:
        raise HTTPException(status_code=422, detail="INCLUDE_FEES_POLICY_UNDEFINED")
    db, tenant_id = context.auth.db, context.tenant.id
    cost = payload.cost
    product_snapshot: dict[str, Any] | None = None
    if payload.product_id is not None:
        product = db.scalar(
            select(Product).where(
                Product.id == payload.product_id,
                Product.tenant_id == tenant_id,
                Product.deleted_at.is_(None),
                Product.is_active.is_(True),
            )
        )
        if product is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        if product.purchase_cost is None:
            raise HTTPException(status_code=422, detail="COST_UNKNOWN")
        cost = product.purchase_cost
        product_snapshot = {
            "product_id": product.id,
            "sku": product.sku,
            "purchase_cost": str(product.purchase_cost),
        }
    if cost is None:
        raise HTTPException(status_code=422, detail="COST_UNKNOWN")
    try:
        price = suggest_price(cost, payload.target_margin)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="PRICING_INPUT_INVALID") from exc
    output = {
        "currency": context.tenant.currency_code,
        "total_cost": cost,
        "target_margin": str(payload.target_margin),
        "suggested_price": price,
        "fees_included": False,
    }
    calculation = _record(
        db,
        tenant_id=tenant_id,
        user_id=context.auth.user.id,
        calc_type="price_suggestion",
        input_data={
            "formula_version": FORMULA_VERSION,
            "product": product_snapshot,
            "cost": str(cost),
            "target_margin": str(payload.target_margin),
            "include_fees": False,
        },
        output_data=output,
        warnings=[],
        source="system" if payload.product_id is not None else "manual",
    )
    output = calculation.output
    db.commit()
    output.update(
        {
            "formula_version": FORMULA_VERSION,
            "calculation_id": calculation.id,
            "warnings": [],
        }
    )
    return {"data": output}
