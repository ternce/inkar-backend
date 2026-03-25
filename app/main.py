from __future__ import annotations

from datetime import date, datetime

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
import io
import csv
from pathlib import Path

from .config import get_settings
from . import data
from .db import init_db
from .deps import get_db
from .models import (
    CalculatedPrice,
    CompetitorPrice,
    ListItem,
    MarkupRange,
    PriceFormat,
    PriceList,
    Product,
    UniversalList,
)
from .schemas import (
    CalculatePricesRequest,
    CalculatePricesResponse,
    CreateUniversalListRequest,
    CreateUniversalListResponse,
    UploadExcelResponse,
)
from .services.excel_import import import_excel
from .services.pricing import resolve_competitor_price, calculate_prices


app = FastAPI(title="aptekaopt-backend", version="0.1.0")

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins if settings.environment != "dev" else ["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"] ,
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%d.%m.%Y %H:%M")


def _fmt_d(d: date | None) -> str:
    if not d:
        return ""
    return d.strftime("%d.%m.%Y")


def _frontend_dist_dir() -> Path | None:
    # Optionally override in Railway via FRONTEND_DIST.
    # Default is repoRoot/front/dist (works in our Docker build).
    import os

    override = os.getenv("FRONTEND_DIST")
    if override:
        p = Path(override).resolve()
        return p if p.exists() else None

    repo_root = Path(__file__).resolve().parents[2]
    dist = repo_root / "front" / "dist"
    return dist if dist.exists() else None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard")
def get_dashboard():
    return data.DASHBOARD


@app.get("/api/price-formats")
def get_price_formats(db: Session = Depends(get_db)):
    rows = db.execute(select(PriceFormat).order_by(PriceFormat.code.asc())).scalars().all()
    if not rows:
        return data.PRICE_FORMATS

    return [{"name": x.name, "code": x.code, "branch": x.branch} for x in rows]


@app.get("/api/price-lists")
def get_price_lists(
    format_code: str | None = None,
    status: str | None = None,
    branch: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = (
        select(PriceList, PriceFormat)
        .join(PriceFormat, PriceFormat.id == PriceList.price_format_id)
        .order_by(PriceList.created_at.desc())
    )

    if format_code:
        stmt = stmt.where(PriceFormat.code == format_code)
    if status and status != "Все":
        stmt = stmt.where(PriceList.status == status)
    if branch and branch != "Все":
        stmt = stmt.where(PriceFormat.branch == branch)

    rows = db.execute(stmt).all()
    if not rows:
        items = list(data.GENERATED_PRICE_LISTS)
        if format_code:
            items = [x for x in items if x.get("format") == format_code or x.get("code") == format_code]
        if status and status != "Все":
            items = [x for x in items if x.get("status") == status]
        if branch and branch != "Все":
            items = [x for x in items if x.get("branch") == branch]
        return items

    return [
        {
            "date": _fmt_dt(pl.created_at),
            "number": pl.number,
            "format": pf.code,
            "activationDate": _fmt_d(pl.activation_date),
            "user": pl.user,
            "status": pl.status,
            "branch": pf.branch,
        }
        for (pl, pf) in rows
    ]


@app.get("/api/price-lists/{price_list_id}/analysis")
def get_price_list_analysis(price_list_id: str, db: Session = Depends(get_db)):
    pl_pf = db.execute(
        select(PriceList, PriceFormat)
        .join(PriceFormat, PriceFormat.id == PriceList.price_format_id)
        .where(PriceList.number == price_list_id)
    ).first()

    if not pl_pf:
        meta = next((x for x in data.GENERATED_PRICE_LISTS if x["number"] == price_list_id), None)
        return {
            "id": price_list_id,
            "meta": meta
            or {
                "date": "",
                "number": price_list_id,
                "format": "",
                "activationDate": "",
                "user": "",
                "status": "",
                "branch": "",
            },
            "distribution": [
                {"name": "Левое плечо", "value": 234, "fill": "#EF4444"},
                {"name": "Зона логичности", "value": 1456, "fill": "#10B981"},
                {"name": "Правое плечо", "value": 189, "fill": "#F59E0B"},
            ],
            "products": [],
        }

    pl, pf = pl_pf

    calc_rows = db.execute(
        select(CalculatedPrice, Product)
        .join(Product, Product.id == CalculatedPrice.product_id)
        .where(CalculatedPrice.price_list_id == pl.id)
        .order_by(Product.name.asc())
    ).all()

    if not calc_rows:
        # fallback to mocks
        meta = next((x for x in data.GENERATED_PRICE_LISTS if x["number"] == price_list_id), None)
        return {
            "id": price_list_id,
            "meta": meta
            or {
                "date": _fmt_dt(pl.created_at),
                "number": pl.number,
                "format": pf.code,
                "activationDate": _fmt_d(pl.activation_date),
                "user": pl.user,
                "status": pl.status,
                "branch": pf.branch,
            },
            "distribution": [
                {"name": "Левое плечо", "value": 0, "fill": "#EF4444"},
                {"name": "Зона логичности", "value": 0, "fill": "#10B981"},
                {"name": "Правое плечо", "value": 0, "fill": "#F59E0B"},
            ],
            "products": [],
        }

    def _zone_name(z: str) -> str:
        if z == "left":
            return "Левое плечо"
        if z == "optimal":
            return "Зона логичности"
        if z == "right":
            return "Правое плечо"
        return "no-data"

    zone_counts = {"left": 0, "optimal": 0, "right": 0}
    products: list[dict] = []
    for cp, product in calc_rows:
        resolved = resolve_competitor_price(db, pf.id, product.id)
        competitor_price = float(resolved.competitor_price) if resolved.competitor_price is not None else None
        deviation = None
        if competitor_price not in (None, 0):
            deviation = (float(cp.final_price) - competitor_price) / competitor_price * 100

        zone = cp.zone
        if zone in zone_counts:
            zone_counts[zone] += 1

        products.append(
            {
                "product": product.name,
                "price": float(cp.final_price),
                "cost": float(cp.cost),
                "competitorPrice": competitor_price,
                "deviation": deviation,
                "source": resolved.applied_source if competitor_price is not None else "Наценка по ЦФ",
                "zone": zone,
            }
        )

    distribution = [
        {"name": _zone_name("left"), "value": zone_counts["left"], "fill": "#EF4444"},
        {"name": _zone_name("optimal"), "value": zone_counts["optimal"], "fill": "#10B981"},
        {"name": _zone_name("right"), "value": zone_counts["right"], "fill": "#F59E0B"},
    ]

    return {
        "id": price_list_id,
        "meta": {
            "date": _fmt_dt(pl.created_at),
            "number": pl.number,
            "format": pf.code,
            "activationDate": _fmt_d(pl.activation_date),
            "user": pl.user,
            "status": pl.status,
            "branch": pf.branch,
        },
        "distribution": distribution,
        "products": products,
    }


@app.get("/api/competitors")
def get_competitors_available():
    return data.COMPETITORS_AVAILABLE


@app.get("/api/price-formats/{format_code}/competitors")
def get_competitors_assigned(format_code: str):
    assigned_ids = data.COMPETITORS_ASSIGNED_BY_FORMAT.get(format_code, [])
    assigned = [x for x in data.COMPETITORS_AVAILABLE if x["id"] in assigned_ids]
    return {"format": format_code, "assigned": assigned, "assignedIds": assigned_ids}


@app.post("/api/price-formats/{format_code}/competitors")
def set_competitors_assigned(format_code: str, payload: dict, db: Session = Depends(get_db)):
    ids = payload.get("assignedIds")
    if not isinstance(ids, list) or not all(isinstance(x, int) for x in ids):
        raise HTTPException(status_code=400, detail="assignedIds must be list[int]")
    data.COMPETITORS_ASSIGNED_BY_FORMAT[format_code] = ids

    # Persist selection to DB so pricing uses the selected sources.
    # We map competitor.id -> competitor.name as source_name.
    pf = db.execute(select(PriceFormat).where(PriceFormat.code == format_code)).scalars().first()
    if pf is None:
        pf = PriceFormat(code=format_code, name=format_code)
        db.add(pf)
        db.flush()

    selected = [x for x in data.COMPETITORS_AVAILABLE if x.get("id") in ids]
    selected_source_names = {str(x.get("name") or "").strip() for x in selected if str(x.get("name") or "").strip()}

    # Delete configs that are no longer selected
    existing_cfg = db.execute(
        select(CompetitorPrice)
        .where(CompetitorPrice.price_format_id == pf.id)
        .where(CompetitorPrice.product_id.is_(None))
    ).scalars().all()

    for row in existing_cfg:
        if (row.source_name or "") not in selected_source_names:
            db.delete(row)

    # Upsert selected configs
    for comp in selected:
        source_name = str(comp.get("name") or "").strip()
        if not source_name:
            continue

        coeff = comp.get("coefficient")
        coefficient = float(coeff) if isinstance(coeff, (int, float)) else 1.0
        supplier = str(comp.get("supplier") or "").strip() or None

        cfg = db.execute(
            select(CompetitorPrice)
            .where(CompetitorPrice.price_format_id == pf.id)
            .where(CompetitorPrice.product_id.is_(None))
            .where(CompetitorPrice.source_name == source_name)
        ).scalars().first()

        if cfg is None:
            cfg = CompetitorPrice(
                price_format_id=pf.id,
                product_id=None,
                source_name=source_name,
                coefficient=coefficient,
            )
            db.add(cfg)

        cfg.coefficient = coefficient
        cfg.supplier = supplier

    db.commit()
    return {"format": format_code, "assignedIds": ids}


@app.get("/api/price-formats/{format_code}/lists")
def get_lists_for_format(format_code: str):
    return data.LISTS_BY_FORMAT.get(format_code, [])


@app.get("/api/price-formats/{format_code}/counterparties")
def get_counterparties_for_format(format_code: str):
    return data.COUNTERPARTIES_BY_FORMAT.get(format_code, [])


@app.get("/api/price-formats/{format_code}/settings")
def get_settings_for_format(format_code: str, db: Session = Depends(get_db)):
    pf = db.execute(select(PriceFormat).where(PriceFormat.code == format_code)).scalars().first()
    if not pf:
        return data.PRICING_SETTINGS_BY_FORMAT.get(format_code) or data.PRICING_SETTINGS_BY_FORMAT.get(
            "ИПЛ_01_001"
        )

    ranges = db.execute(
        select(MarkupRange)
        .where(MarkupRange.price_format_id == pf.id)
        .order_by(MarkupRange.cost_from.asc())
    ).scalars().all()

    return {
        "name": pf.code,
        "branch": pf.branch,
        "pricingRule": pf.pricing_rule or "",
        "deflectionPercent": float(pf.progib or 0),
        "includeVAT": True,
        "useMinCompetitor": True,
        "considerStock": False,
        "recommendedMarkups": [
            {
                "id": idx + 1,
                "lowerBound": float(r.cost_from),
                "upperBound": float(r.cost_to) if r.cost_to is not None else 99999999,
                "markupPercent": float(r.markup_percent) * 100,
            }
            for idx, r in enumerate(ranges)
        ],
    }


@app.put("/api/price-formats/{format_code}/settings")
def put_settings_for_format(format_code: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    pf = db.execute(select(PriceFormat).where(PriceFormat.code == format_code)).scalars().first()
    if pf is None:
        pf = PriceFormat(code=format_code, name=payload.get("name") or format_code)
        db.add(pf)
        db.flush()

    if isinstance(payload.get("branch"), str):
        pf.branch = payload["branch"]
    if isinstance(payload.get("pricingRule"), str):
        pf.pricing_rule = payload["pricingRule"]

    deflection = payload.get("deflectionPercent")
    if deflection is not None:
        try:
            pf.progib = float(deflection)
        except Exception:
            pass

    # Replace markup ranges
    rec = payload.get("recommendedMarkups")
    if isinstance(rec, list):
        db.execute(delete(MarkupRange).where(MarkupRange.price_format_id == pf.id))
        for row in rec:
            if not isinstance(row, dict):
                continue
            lb = row.get("lowerBound")
            ub = row.get("upperBound")
            mp = row.get("markupPercent")
            try:
                lb_f = float(lb)
                ub_f = float(ub) if ub is not None else None
                mp_f = float(mp)
            except Exception:
                continue

            db.add(
                MarkupRange(
                    price_format_id=pf.id,
                    cost_from=lb_f,
                    cost_to=ub_f,
                    markup_percent=mp_f / 100.0,
                )
            )

    db.commit()
    return get_settings_for_format(format_code=format_code, db=db)


@app.post("/upload-excel", response_model=UploadExcelResponse)
async def upload_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")

    try:
        counts = import_excel(db=db, content=content)
        return UploadExcelResponse(**counts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/upload-excel", response_model=UploadExcelResponse)
async def upload_excel_api(file: UploadFile = File(...), db: Session = Depends(get_db)):
    return await upload_excel(file=file, db=db)


@app.post("/calculate-prices", response_model=CalculatePricesResponse)
def calculate_prices_endpoint(payload: CalculatePricesRequest, db: Session = Depends(get_db)):
    as_of = payload.activation_date or date.today()
    price_list_number = payload.price_list_number or f"{payload.price_format_code}_{as_of.isoformat()}"

    try:
        count = calculate_prices(
            db=db,
            price_format_code=payload.price_format_code,
            price_list_number=price_list_number,
            as_of=as_of,
            activation_date=payload.activation_date,
            user=payload.user,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return CalculatePricesResponse(price_list_number=price_list_number, calculated_count=count)


@app.post("/api/calculate-prices", response_model=CalculatePricesResponse)
def calculate_prices_api(payload: CalculatePricesRequest, db: Session = Depends(get_db)):
    return calculate_prices_endpoint(payload=payload, db=db)


@app.get("/competitor-prices")
def competitor_prices(
    price_format_code: str = Query(...),
    product_code: str | None = Query(None),
    db: Session = Depends(get_db),
):
    pf = db.execute(select(PriceFormat).where(PriceFormat.code == price_format_code)).scalars().first()
    if not pf:
        raise HTTPException(status_code=404, detail="price format not found")

    stmt = select(Product.code, CompetitorPrice).join(
        Product, Product.id == CompetitorPrice.product_id, isouter=True
    ).where(CompetitorPrice.price_format_id == pf.id)

    if product_code:
        stmt = stmt.where(Product.code == product_code)

    rows = db.execute(stmt).all()
    return [
        {
            "product_code": code,
            "source_name": cp.source_name,
            "supplier": cp.supplier,
            "coefficient": float(cp.coefficient or 1.0),
            "source_price": float(cp.source_price) if cp.source_price is not None else None,
            "price_date": cp.price_date,
        }
        for (code, cp) in rows
    ]


@app.get("/price-list")
def get_price_list(price_list_number: str = Query(...), db: Session = Depends(get_db)):
    pl = db.execute(select(PriceList).where(PriceList.number == price_list_number)).scalars().first()
    if not pl:
        raise HTTPException(status_code=404, detail="price list not found")

    rows = db.execute(
        select(CalculatedPrice, Product)
        .join(Product, Product.id == CalculatedPrice.product_id)
        .where(CalculatedPrice.price_list_id == pl.id)
        .order_by(Product.name.asc())
    ).all()

    return [
        {
            "product": p.name,
            "price": float(cp.final_price),
            "cost": float(cp.cost),
            "zone": cp.zone,
        }
        for (cp, p) in rows
    ]


@app.get("/analytics")
def analytics(price_list_number: str = Query(...), db: Session = Depends(get_db)):
    # reuse analysis response shape for now
    return get_price_list_analysis(price_list_id=price_list_number, db=db)


@app.get("/api/universal-lists")
def get_universal_lists(db: Session = Depends(get_db)):
    rows = db.execute(select(UniversalList).order_by(UniversalList.created_at.desc())).scalars().all()
    if not rows:
        # Заглушка: отдаём как в текущем UI
        return [
            {
                "id": 1,
                "name": "Прямые контракты",
                "type": "Фикс цена",
                "status": "Активен",
                "period": "01.03.2026 - 31.03.2026",
                "itemsCount": 0,
            },
            {
                "id": 2,
                "name": "Ограничения сверху",
                "type": "Макс. наценка",
                "status": "Неактивен",
                "period": "01.01.2026 - 01.01.2027",
                "itemsCount": 0,
            },
        ]

    counts = dict(
        db.execute(
            select(ListItem.universal_list_id, func.count(ListItem.id))
            .group_by(ListItem.universal_list_id)
        ).all()
    )

    def _map_status(s: str) -> str:
        s_l = (s or "").strip().lower()
        if s_l.startswith("актив"):
            return "Активен"
        if s_l.startswith("черн"):
            return "Черновик"
        return "Неактивен"

    return [
        {
            "id": ul.id,
            "name": ul.name,
            "type": ul.type,
            "status": _map_status(ul.status),
            "period": f"{_fmt_d(ul.start_date)} - {_fmt_d(ul.end_date)}".strip(),
            "itemsCount": int(counts.get(ul.id, 0)),
        }
        for ul in rows
    ]


@app.post("/api/universal-lists", response_model=CreateUniversalListResponse)
def create_universal_list(payload: CreateUniversalListRequest = Body(...), db: Session = Depends(get_db)):
    price_format_id: int | None = None
    if payload.price_format_code:
        pf = (
            db.execute(select(PriceFormat).where(PriceFormat.code == payload.price_format_code))
            .scalars()
            .first()
        )
        if not pf:
            raise HTTPException(status_code=404, detail="price format not found")
        price_format_id = pf.id

    ul = UniversalList(
        code=None,
        name=payload.name.strip(),
        status=payload.status.strip(),
        type=payload.type.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        price_format_id=price_format_id,
    )

    db.add(ul)
    db.flush()  # получаем ul.id

    if not ul.code:
        ul.code = f"UL_{ul.id:06d}"

    db.commit()
    return CreateUniversalListResponse(id=ul.id)


@app.delete("/api/universal-lists/{list_id}")
def delete_universal_list(list_id: int, db: Session = Depends(get_db)):
    ul = db.execute(select(UniversalList).where(UniversalList.id == list_id)).scalars().first()
    if not ul:
        raise HTTPException(status_code=404, detail="list not found")

    db.execute(delete(ListItem).where(ListItem.universal_list_id == ul.id))
    db.execute(delete(UniversalList).where(UniversalList.id == ul.id))
    db.commit()
    return {"status": "ok"}


@app.get("/api/universal-lists/{list_id}")
def get_universal_list_details(list_id: int, db: Session = Depends(get_db)):
    ul = db.execute(select(UniversalList).where(UniversalList.id == list_id)).scalars().first()
    if not ul:
        raise HTTPException(status_code=404, detail="list not found")

    items = db.execute(
        select(ListItem, Product)
        .join(Product, Product.id == ListItem.product_id)
        .where(ListItem.universal_list_id == ul.id)
        .order_by(Product.name.asc())
    ).all()

    status_l = (ul.status or "").strip().lower()
    status_ui = "Активен" if status_l.startswith("актив") else "Неактивен"

    return {
        "id": ul.id,
        "name": ul.name,
        "type": ul.type,
        "status": status_ui,
        "period": {"start": _fmt_d(ul.start_date), "end": _fmt_d(ul.end_date)},
        "items": [
            {
                "code": p.code,
                "name": p.name,
                "value": f"{float(li.value):.2f}",
            }
            for (li, p) in items
        ],
        "linkedPriceLists": [],
    }


@app.get("/api/price-lists/{price_list_id}/export.csv")
def export_price_list_csv(price_list_id: str, db: Session = Depends(get_db)):
    pl = db.execute(select(PriceList).where(PriceList.number == price_list_id)).scalars().first()
    if not pl:
        raise HTTPException(status_code=404, detail="price list not found")

    rows = db.execute(
        select(CalculatedPrice, Product)
        .join(Product, Product.id == CalculatedPrice.product_id)
        .where(CalculatedPrice.price_list_id == pl.id)
        .order_by(Product.code.asc())
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", lineterminator="\n")
    writer.writerow([
        "price_list_number",
        "product_code",
        "product_name",
        "cost",
        "final_price",
        "competitor_price",
        "zone",
        "applied_reason",
    ])

    for cp, product in rows:
        writer.writerow([
            pl.number,
            product.code,
            product.name,
            f"{float(cp.cost):.2f}",
            f"{float(cp.final_price):.2f}",
            "" if cp.competitor_price is None else f"{float(cp.competitor_price):.2f}",
            cp.zone or "",
            cp.applied_reason or "",
        ])

    buffer.seek(0)
    filename = f"{pl.number}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )


@app.get("/api/phcenter/prices-analysis")
async def phcenter_prices_analysis(
    region: int = Query(...),
    price_mode: int = Query(...),
    distributors: int = Query(...),
):
    token = settings.phcenter_token
    if not token:
        raise HTTPException(status_code=500, detail="PHCENTER_TOKEN is not configured")

    authorization = token if token.lower().startswith("bearer ") else f"Bearer {token}"

    url = f"{settings.phcenter_base_url.rstrip('/')}/api/Report/PricesAnalysis"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            params={"region": region, "price_mode": price_mode, "distributors": distributors},
            headers={"Authorization": authorization},
        )

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    # Возвращаем как есть (обычно JSON)
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    # Serve SPA build when present (Railway / production). In dev, Vite serves UI.
    dist = _frontend_dist_dir()
    if dist is None:
        raise HTTPException(status_code=404, detail="frontend is not built")

    # Don't turn missing API endpoints into index.html.
    if full_path.startswith("api/") or full_path in {"openapi.json", "docs", "redoc", "health"}:
        raise HTTPException(status_code=404, detail="not found")

    requested = (dist / full_path).resolve()
    # Prevent path traversal.
    if dist not in requested.parents and requested != dist:
        raise HTTPException(status_code=404, detail="not found")

    if requested.is_file():
        return FileResponse(requested)

    index = dist / "index.html"
    if index.exists():
        return FileResponse(index)

    raise HTTPException(status_code=404, detail="index.html not found")
