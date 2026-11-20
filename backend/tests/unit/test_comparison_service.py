from decimal import Decimal

from app.modules.comparison.service import PriceItem, build_comparison, normalize_match_name


def _item(
    item_id: int,
    name: str,
    price: str,
    *,
    sku: str | None = None,
    unit: str | None = "piece",
    product_id: int | None = None,
) -> PriceItem:
    return PriceItem(item_id, name, sku, Decimal(price), unit, product_id)


def test_sku_comparison_calculates_delta_and_percent_without_float() -> None:
    rows, summary = build_comparison(
        [_item(1, "Tape", "100.00", sku="T-1")],
        [_item(2, "Adhesive Tape", "125.00", sku="t-1")],
        "sku",
    )
    assert len(rows) == 1
    assert rows[0].match_type == "exact_sku"
    assert rows[0].price_delta == Decimal("25.00")
    assert rows[0].price_delta_pct == Decimal("25.0000")
    assert summary["increased"] == 1
    assert summary["matched"] == 1


def test_zero_base_price_has_delta_but_no_percentage() -> None:
    rows, _ = build_comparison(
        [_item(1, "Free", "0", sku="FREE")],
        [_item(2, "Free", "10", sku="FREE")],
        "sku",
    )
    assert rows[0].price_delta == Decimal("10")
    assert rows[0].price_delta_pct is None


def test_persian_arabic_name_normalization() -> None:
    arabic = "".join(chr(code) for code in (0x0643, 0x0627, 0x0644, 0x0627, 0x200C, 0x06CC))
    persian = "".join(chr(code) for code in (0x06A9, 0x0627, 0x0644, 0x0627, 0x06CC))
    assert normalize_match_name(arabic) == normalize_match_name(persian)
    with_joiner = "\u06a9\u200d\u0627\u0644\u0627\u06cc"
    without_joiner = "\u06a9\u0627\u0644\u0627\u06cc"
    assert normalize_match_name(with_joiner) == normalize_match_name(without_joiner)
    rows, summary = build_comparison(
        [_item(1, "packing-tape", "100")],
        [_item(2, "packing tape", "90")],
        "normalized_name",
    )
    assert rows[0].match_type == "exact_name"
    assert rows[0].price_delta == Decimal("-10")
    assert summary["decreased"] == 1


def test_sku_then_name_uses_name_only_when_sku_does_not_match() -> None:
    rows, summary = build_comparison(
        [_item(1, "Carton Box", "20", sku="OLD")],
        [_item(2, "carton-box", "22", sku="NEW")],
        "sku_then_name",
    )
    assert len(rows) == 1
    assert rows[0].match_type == "exact_name"
    assert summary["matched"] == 1


def test_ambiguous_normalized_names_are_not_arbitrarily_paired() -> None:
    rows, summary = build_comparison(
        [_item(1, "Packing Tape", "100"), _item(2, "Packing-Tape", "110")],
        [_item(3, "Packing Tape", "105")],
        "normalized_name",
    )
    assert len(rows) == 3
    assert all(row.match_type == "uncertain" for row in rows)
    assert all(row.status == "pending" for row in rows)
    assert all(row.price_delta is None for row in rows)
    assert summary["uncertain"] == 3
    assert summary["matched"] == 0


def test_unit_mismatch_is_uncertain_and_has_no_price_delta() -> None:
    rows, summary = build_comparison(
        [_item(1, "Rice", "100", sku="R-1", unit="kg")],
        [_item(2, "Rice", "200", sku="R-1", unit="box")],
        "sku",
    )
    assert rows[0].match_type == "uncertain"
    assert rows[0].status == "pending"
    assert rows[0].price_delta is None
    assert summary["uncertain"] == 1


def test_conflicting_existing_product_links_require_review() -> None:
    rows, summary = build_comparison(
        [_item(1, "Tape", "100", sku="T-1", product_id=10)],
        [_item(2, "Tape", "90", sku="T-1", product_id=11)],
        "sku",
    )
    assert rows[0].match_type == "uncertain"
    assert rows[0].status == "pending"
    assert rows[0].suggested_product_id is None
    assert rows[0].price_delta == Decimal("-10")
    assert summary["matched"] == 1
    assert summary["uncertain"] == 1
    assert summary["decreased"] == 0


def test_same_existing_product_link_is_confirmed() -> None:
    rows, _ = build_comparison(
        [_item(1, "Tape", "100", sku="T-1", product_id=10)],
        [_item(2, "Tape", "90", sku="T-1", product_id=10)],
        "sku",
    )
    assert rows[0].status == "confirmed"
    assert rows[0].confirmed_product_id == 10


def test_new_and_removed_items_are_explicitly_represented() -> None:
    rows, summary = build_comparison(
        [_item(1, "Old item", "10", sku="OLD")],
        [_item(2, "New item", "20", sku="NEW")],
        "sku",
    )
    assert {(row.base_price_id, row.target_price_id) for row in rows} == {(1, None), (None, 2)}
    assert summary["removed"] == 1
    assert summary["new"] == 1


def test_sku_strategy_does_not_fallback_to_name() -> None:
    rows, summary = build_comparison(
        [_item(1, "Tape", "100", sku="OLD")],
        [_item(2, "Tape", "90", sku="NEW")],
        "sku",
    )
    assert len(rows) == 2
    assert summary["new"] == summary["removed"] == 1


def test_missing_unit_is_never_assumed_comparable() -> None:
    rows, _ = build_comparison(
        [_item(1, "Unknown unit", "100", sku="U-1", unit=None)],
        [_item(2, "Unknown unit", "110", sku="U-1", unit="piece")],
        "sku",
    )
    assert rows[0].match_type == "uncertain"
    assert rows[0].price_delta is None
