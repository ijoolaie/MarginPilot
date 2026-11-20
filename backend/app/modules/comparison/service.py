"""Deterministic supplier price-list comparison and match normalization."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal, Protocol

MatchType = Literal["exact_sku", "exact_name", "uncertain", "unmatched"]
MatchStatus = Literal["pending", "confirmed", "rejected"]


@dataclass(frozen=True)
class PriceItem:
    id: int
    raw_name: str
    sku: str | None
    unit_price: Decimal
    unit: str | None
    product_id: int | None


@dataclass(frozen=True)
class MatchResult:
    base_price_id: int | None
    target_price_id: int | None
    base_raw_name: str | None
    target_raw_name: str | None
    match_type: MatchType
    status: MatchStatus
    suggested_product_id: int | None
    confirmed_product_id: int | None
    price_delta: Decimal | None
    price_delta_pct: Decimal | None


def normalize_match_name(value: str) -> str:
    """Normalize Persian/Arabic and Latin names without fuzzy matching."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = (
        value.replace(chr(0x064A), chr(0x06CC))
        .replace(chr(0x0649), chr(0x06CC))
        .replace(chr(0x0643), chr(0x06A9))
        .replace(chr(0x06C0), chr(0x0647))
    )
    value = (
        value.replace(chr(0x200C), "")
        .replace(chr(0x200D), "")
        .replace(chr(0x200F), "")
        .replace(chr(0x200E), "")
    )
    value = "".join(char if unicodedata.category(char)[0] != "C" else " " for char in value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _sku_key(value: str | None) -> str | None:
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    return value or None


def _group(items: list[PriceItem], key_fn: object) -> dict[str, list[PriceItem]]:
    groups: dict[str, list[PriceItem]] = defaultdict(list)
    for item in items:
        key = key_fn(item)  # type: ignore[operator]
        if key:
            groups[key].append(item)
    return groups


def _pair_groups(
    base_items: list[PriceItem], target_items: list[PriceItem], key_fn: object
) -> tuple[list[tuple[PriceItem, PriceItem]], set[int], set[int]]:
    base_groups = _group(base_items, key_fn)
    target_groups = _group(target_items, key_fn)
    pairs: list[tuple[PriceItem, PriceItem]] = []
    ambiguous_base: set[int] = set()
    ambiguous_target: set[int] = set()
    for key in sorted(base_groups.keys() | target_groups.keys()):
        left = base_groups.get(key, [])
        right = target_groups.get(key, [])
        if len(left) == 1 and len(right) == 1:
            pairs.append((left[0], right[0]))
        elif (left and right) or len(left) > 1 or len(right) > 1:
            ambiguous_base.update(item.id for item in left)
            ambiguous_target.update(item.id for item in right)
    return pairs, ambiguous_base, ambiguous_target


def _matched_result(base: PriceItem, target: PriceItem, match_type: MatchType) -> MatchResult:
    suggested: int | None = None
    confirmed: int | None = None
    status: MatchStatus = "confirmed"
    if base.product_id is not None and target.product_id is not None:
        if base.product_id == target.product_id:
            suggested = confirmed = base.product_id
        else:
            match_type = "uncertain"
            status = "pending"
    elif base.product_id is not None or target.product_id is not None:
        suggested = base.product_id or target.product_id
        status = "pending"

    delta: Decimal | None = None
    delta_pct: Decimal | None = None
    if base.unit is None or target.unit is None or base.unit != target.unit:
        match_type = "uncertain"
        status = "pending"
    else:
        delta = target.unit_price - base.unit_price
        if base.unit_price != 0:
            with localcontext() as context:
                context.prec = 32
                delta_pct = ((delta / base.unit_price) * Decimal("100")).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
    return MatchResult(
        base_price_id=base.id,
        target_price_id=target.id,
        base_raw_name=base.raw_name,
        target_raw_name=target.raw_name,
        match_type=match_type,
        status=status,
        suggested_product_id=suggested,
        confirmed_product_id=confirmed,
        price_delta=delta,
        price_delta_pct=delta_pct,
    )


def calculate_price_delta(
    base_price: Decimal, target_price: Decimal
) -> tuple[Decimal, Decimal | None]:
    delta = target_price - base_price
    if base_price == 0:
        return delta, None
    with localcontext() as context:
        context.prec = 32
        percentage = ((delta / base_price) * Decimal("100")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    return delta, percentage


class MatchRecord(Protocol):
    @property
    def base_price_id(self) -> int | None: ...

    @property
    def target_price_id(self) -> int | None: ...

    @property
    def match_type(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def price_delta(self) -> Decimal | None: ...


def summarize_matches(rows: Iterable[MatchRecord]) -> dict[str, int]:
    records = list(rows)
    return {
        "base_items": sum(row.base_price_id is not None for row in records),
        "target_items": sum(row.target_price_id is not None for row in records),
        "matched": sum(
            row.base_price_id is not None and row.target_price_id is not None for row in records
        ),
        "new": sum(
            row.base_price_id is None
            and (row.match_type == "unmatched" or row.status == "rejected")
            for row in records
        ),
        "removed": sum(
            row.target_price_id is None
            and (row.match_type == "unmatched" or row.status == "rejected")
            for row in records
        ),
        "increased": sum(
            row.status == "confirmed" and row.price_delta is not None and row.price_delta > 0
            for row in records
        ),
        "decreased": sum(
            row.status == "confirmed" and row.price_delta is not None and row.price_delta < 0
            for row in records
        ),
        "unchanged": sum(row.status == "confirmed" and row.price_delta == 0 for row in records),
        "uncertain": sum(
            row.match_type == "uncertain" and row.status == "pending" for row in records
        ),
        "total_matches": len(records),
    }


def build_comparison(
    base_items: list[PriceItem],
    target_items: list[PriceItem],
    strategy: Literal["sku", "normalized_name", "sku_then_name"],
) -> tuple[list[MatchResult], dict[str, int]]:
    """Match two lists one-to-one; never guess when a normalized key is ambiguous."""
    used_base: set[int] = set()
    used_target: set[int] = set()
    ambiguous_base: set[int] = set()
    ambiguous_target: set[int] = set()
    blocked_base: set[int] = set()
    blocked_target: set[int] = set()
    pairs: list[tuple[PriceItem, PriceItem, MatchType]] = []

    if strategy in {"sku", "sku_then_name"}:
        sku_pairs, left_ambiguous, right_ambiguous = _pair_groups(
            base_items,
            target_items,
            lambda item: _sku_key(item.sku),
        )
        for left, right in sku_pairs:
            pairs.append((left, right, "exact_sku"))
            used_base.add(left.id)
            used_target.add(right.id)
        ambiguous_base.update(left_ambiguous)
        ambiguous_target.update(right_ambiguous)
        blocked_base.update(left_ambiguous)
        blocked_target.update(right_ambiguous)

    if strategy in {"normalized_name", "sku_then_name"}:
        remaining_base = [item for item in base_items if item.id not in used_base | blocked_base]
        remaining_target = [
            item for item in target_items if item.id not in used_target | blocked_target
        ]
        name_pairs, left_ambiguous, right_ambiguous = _pair_groups(
            remaining_base,
            remaining_target,
            lambda item: normalize_match_name(item.raw_name),
        )
        for left, right in name_pairs:
            pairs.append((left, right, "exact_name"))
            used_base.add(left.id)
            used_target.add(right.id)
        ambiguous_base.update(left_ambiguous)
        ambiguous_target.update(right_ambiguous)
        blocked_base.update(left_ambiguous)
        blocked_target.update(right_ambiguous)

    results = [_matched_result(left, right, kind) for left, right, kind in pairs]
    for item in base_items:
        if item.id not in used_base:
            kind: MatchType = "uncertain" if item.id in ambiguous_base else "unmatched"
            results.append(
                MatchResult(
                    base_price_id=item.id,
                    target_price_id=None,
                    base_raw_name=item.raw_name,
                    target_raw_name=None,
                    match_type=kind,
                    status="pending" if kind == "uncertain" else "confirmed",
                    suggested_product_id=item.product_id,
                    confirmed_product_id=item.product_id if kind == "unmatched" else None,
                    price_delta=None,
                    price_delta_pct=None,
                )
            )
    for item in target_items:
        if item.id not in used_target:
            kind = "uncertain" if item.id in ambiguous_target else "unmatched"
            results.append(
                MatchResult(
                    base_price_id=None,
                    target_price_id=item.id,
                    base_raw_name=None,
                    target_raw_name=item.raw_name,
                    match_type=kind,
                    status="pending" if kind == "uncertain" else "confirmed",
                    suggested_product_id=item.product_id,
                    confirmed_product_id=item.product_id if kind == "unmatched" else None,
                    price_delta=None,
                    price_delta_pct=None,
                )
            )

    results.sort(
        key=lambda row: (
            row.base_price_id is None,
            row.base_price_id if row.base_price_id is not None else row.target_price_id or 0,
            row.target_price_id or 0,
        )
    )
    summary = summarize_matches(results)
    return results, summary
