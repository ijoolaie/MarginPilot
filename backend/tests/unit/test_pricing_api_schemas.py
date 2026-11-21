from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.pricing.models import Calculation
from app.modules.pricing.router import PriceSuggestionInput
from app.modules.pricing.service import _rounded_output


def test_price_suggestion_accepts_decimal_strings() -> None:
    payload = PriceSuggestionInput.model_validate({"cost": "100.00", "target_margin": "0.25"})
    assert payload.cost == Decimal("100.00")
    assert payload.target_margin == Decimal("0.25")


def test_price_suggestion_rejects_json_float_values() -> None:
    with pytest.raises(ValidationError):
        PriceSuggestionInput.model_validate({"cost": 100.0, "target_margin": "0.25"})


def test_price_suggestion_requires_exactly_one_cost_source() -> None:
    with pytest.raises(ValidationError):
        PriceSuggestionInput.model_validate({"target_margin": "0.25"})
    with pytest.raises(ValidationError):
        PriceSuggestionInput.model_validate(
            {"cost": "10", "product_id": 1, "target_margin": "0.25"}
        )


def test_price_suggestion_rejects_margin_one() -> None:
    with pytest.raises(ValidationError):
        PriceSuggestionInput.model_validate({"cost": "100", "target_margin": "1"})


def test_calculation_journal_supports_product_scope() -> None:
    constraint = next(
        item
        for item in Calculation.__table__.constraints
        if item.name == "ck_calculations_calc_type_allowed"
    )
    assert "'product'" in str(constraint.sqltext)


def test_calculation_output_preserves_fractional_quantities() -> None:
    output = _rounded_output(
        {
            "revenue": Decimal("100.75"),
            "units_sold": Decimal("1.250"),
            "returned_units": Decimal("0.250"),
            "margin_pct": Decimal("12.345"),
        }
    )
    assert output == {
        "revenue": "101",
        "units_sold": "1.250",
        "returned_units": "0.250",
        "margin_pct": "12.35",
    }
