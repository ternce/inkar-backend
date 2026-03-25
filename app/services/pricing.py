from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Product,
    PriceFormat,
    MarkupRange,
    UniversalList,
    ListItem,
    CompetitorPrice,
    PriceList,
    CalculatedPrice,
)
from .. import data


LIST_TYPE_FIXED_PRICE = "Фиксированная цена"
LIST_TYPE_MAX_MARKUP = "Максимальная наценка"
LIST_TYPE_MIN_PRICE = "Минимальная цена"
LIST_TYPE_GOV_PRICE = "Гос цены"
LIST_TYPE_FIXED_MARKUP = "Фикс наценка"


@dataclass(frozen=True)
class CompetitorResolved:
    competitor_price: Decimal | None
    applied_source: str


def _as_decimal(value: object, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def get_markup_percent_by_range(db: Session, price_format_id: int, cost: Decimal) -> Decimal:
    ranges = db.execute(
        select(MarkupRange)
        .where(MarkupRange.price_format_id == price_format_id)
        .order_by(MarkupRange.cost_from.asc())
    ).scalars().all()

    if not ranges:
        raise ValueError("Markup ranges are required")

    for r in ranges:
        cost_from = _as_decimal(r.cost_from, Decimal("0"))
        cost_to = _as_decimal(r.cost_to)
        if cost >= cost_from and (cost_to is None or cost <= cost_to):
            return _as_decimal(r.markup_percent, Decimal("0")) or Decimal("0")

    # если ничего не подошло — берём последний диапазон
    return _as_decimal(ranges[-1].markup_percent, Decimal("0")) or Decimal("0")


def resolve_competitor_price(db: Session, price_format_id: int, product_id: int) -> CompetitorResolved:
    # Схема: competitors_prices хранит
    # - записи-настройки источника: product_id IS NULL, fields: source_name, coefficient
    # - записи цен: product_id == product_id, fields: source_name, source_price

    config_rows = db.execute(
        select(CompetitorPrice)
        .where(CompetitorPrice.price_format_id == price_format_id)
        .where(CompetitorPrice.product_id.is_(None))
    ).scalars().all()

    if not config_rows:
        return CompetitorResolved(None, "нет ПЛК")

    best: Decimal | None = None
    best_source = ""

    for cfg in config_rows:
        source_name = cfg.source_name
        coefficient = _as_decimal(cfg.coefficient, Decimal("1")) or Decimal("1")

        price_row = db.execute(
            select(CompetitorPrice)
            .where(CompetitorPrice.price_format_id == price_format_id)
            .where(CompetitorPrice.product_id == product_id)
            .where(CompetitorPrice.source_name == source_name)
            .limit(1)
        ).scalars().first()

        if not price_row:
            continue

        source_price = _as_decimal(price_row.source_price)
        if source_price is None:
            continue

        computed = source_price * coefficient
        if best is None or computed < best:
            best = computed
            best_source = source_name

    if best is None:
        return CompetitorResolved(None, "нет цен ПЛК")

    return CompetitorResolved(best, best_source)


def _active_lists_query(db: Session, price_format_id: int, as_of: date):
    return (
        select(UniversalList)
        .where(UniversalList.status == "Активный")
        .where((UniversalList.price_format_id.is_(None)) | (UniversalList.price_format_id == price_format_id))
        .where((UniversalList.start_date.is_(None)) | (UniversalList.start_date <= as_of))
        .where((UniversalList.end_date.is_(None)) | (UniversalList.end_date >= as_of))
    )


def _find_item_value(
    db: Session, lists: list[UniversalList], product_id: int, list_type: str
) -> Decimal | None:
    list_ids = [l.id for l in lists if l.type == list_type]
    if not list_ids:
        return None

    row = db.execute(
        select(ListItem)
        .where(ListItem.universal_list_id.in_(list_ids))
        .where(ListItem.product_id == product_id)
        .limit(1)
    ).scalars().first()

    if not row:
        return None

    return _as_decimal(row.value)


def calculate_price_for_product(
    *,
    db: Session,
    product: Product,
    price_format: PriceFormat,
    as_of: date,
) -> tuple[Decimal, dict]:
    cost = _as_decimal(product.cost, Decimal("0")) or Decimal("0")

    markup_percent = get_markup_percent_by_range(db, price_format.id, cost)
    base_price = cost * (Decimal("1") + markup_percent)

    resolved = resolve_competitor_price(db, price_format.id, product.id)

    progib = _as_decimal(price_format.progib, Decimal("0")) or Decimal("0")
    # "Прогиб" по ТЗ — процент. Поддерживаем оба формата:
    # - 5   => 5%
    # - 0.05 => 5%
    progib_ratio = progib / Decimal("100") if progib > 1 else progib
    price_from_competitor = None
    if resolved.competitor_price is not None:
        price_from_competitor = resolved.competitor_price * (Decimal("1") - progib_ratio)

    # Базовая логика
    if price_from_competitor is None:
        price = base_price
        reason = "base_price"
    else:
        price = min(base_price, price_from_competitor)
        reason = "min(base, competitor-progib)"

    # Активные списки
    active_lists = db.execute(_active_lists_query(db, price_format.id, as_of)).scalars().all()

    # Универсальные списки: фикс наценка (перекрывает всё)
    fixed_markup = _find_item_value(db, active_lists, product.id, LIST_TYPE_FIXED_MARKUP)
    if fixed_markup is not None:
        price = cost * (Decimal("1") + fixed_markup)
        reason = "fixed_markup_list"

    # Ограничения
    fixed_price = _find_item_value(db, active_lists, product.id, LIST_TYPE_FIXED_PRICE)
    if fixed_price is not None:
        price = fixed_price
        reason = "fixed_price_list"

    max_markup = _find_item_value(db, active_lists, product.id, LIST_TYPE_MAX_MARKUP)
    if max_markup is not None:
        price = min(price, cost * (Decimal("1") + max_markup))
        reason = "max_markup_cap"

    min_price = _find_item_value(db, active_lists, product.id, LIST_TYPE_MIN_PRICE)
    if min_price is not None:
        price = max(price, min_price)
        reason = "min_price_floor"

    gov_price = _find_item_value(db, active_lists, product.id, LIST_TYPE_GOV_PRICE)
    if gov_price is not None:
        price = min(price, gov_price)
        reason = "gov_price_cap"

    # Округление
    price = price.quantize(Decimal("0.01"))

    # ЛП/ЗЛ/ПП
    zone = "no-data"
    deviation_pct: Decimal | None = None
    if resolved.competitor_price is not None and resolved.competitor_price != 0:
        deviation_pct = (price - resolved.competitor_price) / resolved.competitor_price
        if price < resolved.competitor_price:
            zone = "left"
        elif deviation_pct <= Decimal("0.03") and deviation_pct >= Decimal("0"):
            zone = "optimal"
        elif deviation_pct > Decimal("0.03"):
            zone = "right"

    debug = {
        "cost": cost,
        "markup_percent": markup_percent,
        "base_price": base_price,
        "competitor_price": resolved.competitor_price,
        "competitor_source": resolved.applied_source,
        "progib": progib,
        "progib_ratio": progib_ratio,
        "price_from_competitor": price_from_competitor,
        "final_price": price,
        "reason": reason,
        "zone": zone,
        "deviation_pct": deviation_pct,
    }

    return price, debug


def calculate_prices(
    *,
    db: Session,
    price_format_code: str,
    price_list_number: str,
    as_of: date,
    activation_date: date | None,
    user: str,
) -> int:
    pf = db.execute(select(PriceFormat).where(PriceFormat.code == price_format_code)).scalars().first()
    if not pf:
        # MVP: allow calculating on an empty DB by creating the price format from mock data.
        meta = next((x for x in data.PRICE_FORMATS if x.get("code") == price_format_code), None)
        pf = PriceFormat(
            code=price_format_code,
            name=(meta.get("name") if meta else None) or price_format_code,
            branch=(meta.get("branch") if meta else None),
        )

        defaults = data.PRICING_SETTINGS_BY_FORMAT.get(price_format_code) or data.PRICING_SETTINGS_BY_FORMAT.get(
            "ИПЛ_01_001"
        )
        if defaults and defaults.get("deflectionPercent") is not None:
            try:
                pf.progib = float(defaults["deflectionPercent"])
            except Exception:
                pass

        db.add(pf)
        db.flush()

    # Ensure markup ranges exist (seed from mock defaults if needed)
    ranges = db.execute(select(MarkupRange).where(MarkupRange.price_format_id == pf.id)).scalars().all()
    if not ranges:
        defaults = data.PRICING_SETTINGS_BY_FORMAT.get(price_format_code) or data.PRICING_SETTINGS_BY_FORMAT.get(
            "ИПЛ_01_001"
        )
        rec = (defaults or {}).get("recommendedMarkups") or []
        for row in rec:
            try:
                cost_from = float(row.get("lowerBound"))
                cost_to = float(row.get("upperBound")) if row.get("upperBound") is not None else None
                mp = float(row.get("markupPercent")) / 100.0
            except Exception:
                continue

            db.add(
                MarkupRange(
                    price_format_id=pf.id,
                    cost_from=cost_from,
                    cost_to=cost_to,
                    markup_percent=mp,
                )
            )

        db.flush()

    # Safety: if still no ranges, fail with clear message.
    ranges = db.execute(select(MarkupRange).where(MarkupRange.price_format_id == pf.id)).scalars().all()
    if not ranges:
        raise ValueError("Markup ranges are required")

    pl = db.execute(select(PriceList).where(PriceList.number == price_list_number)).scalars().first()
    if not pl:
        pl = PriceList(
            number=price_list_number,
            price_format_id=pf.id,
            activation_date=activation_date,
            user=user,
            status="Активен" if activation_date else "Черновик",
        )
        db.add(pl)
        db.flush()

    products = db.execute(select(Product)).scalars().all()
    if not products:
        # MVP: allow creating a price list before importing products.
        db.commit()
        return 0

    # upsert calculated_prices
    count = 0
    for p in products:
        price, debug = calculate_price_for_product(db=db, product=p, price_format=pf, as_of=as_of)

        existing = db.execute(
            select(CalculatedPrice)
            .where(CalculatedPrice.price_list_id == pl.id)
            .where(CalculatedPrice.product_id == p.id)
        ).scalars().first()

        cp = existing or CalculatedPrice(price_list_id=pl.id, product_id=p.id)
        cp.cost = float(debug["cost"])
        cp.base_price = float(debug["base_price"])
        cp.competitor_price = float(debug["competitor_price"]) if debug["competitor_price"] is not None else None
        cp.price_from_competitor = (
            float(debug["price_from_competitor"]) if debug["price_from_competitor"] is not None else None
        )
        cp.final_price = float(price)
        cp.applied_reason = str(debug["reason"])
        cp.zone = str(debug["zone"])

        if existing is None:
            db.add(cp)

        count += 1

    db.commit()
    return count
