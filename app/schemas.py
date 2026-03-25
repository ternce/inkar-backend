from __future__ import annotations

from datetime import date
from pydantic import BaseModel, Field


class UploadExcelResponse(BaseModel):
    price_formats: int = 0
    markup_ranges: int = 0
    products: int = 0
    universal_lists: int = 0
    list_items: int = 0
    competitor_sources: int = 0
    competitor_prices: int = 0


class CalculatePricesRequest(BaseModel):
    price_format_code: str
    price_list_number: str | None = None
    activation_date: date | None = None
    user: str = ""


class CalculatePricesResponse(BaseModel):
    price_list_number: str
    calculated_count: int


class PriceListRow(BaseModel):
    date: str
    number: str
    format: str
    activationDate: str
    user: str
    status: str
    branch: str


class PriceListProductRow(BaseModel):
    product: str
    price: float
    cost: float
    competitorPrice: float | None
    deviation: float | None
    source: str
    zone: str


class AnalyticsResponse(BaseModel):
    distribution: list[dict]
    products: list[PriceListProductRow]


class CompetitorPricesQuery(BaseModel):
    price_format_code: str
    product_code: str | None = None


class CompetitorPriceRow(BaseModel):
    product_code: str | None
    source_name: str
    supplier: str
    coefficient: float
    source_price: float | None
    price_date: date | None


class CreateUniversalListRequest(BaseModel):
    name: str = Field(..., min_length=1)
    type: str = Field("Фикс цена", min_length=1)
    status: str = Field("Черновик", min_length=1)
    start_date: date | None = None
    end_date: date | None = None
    price_format_code: str | None = None


class CreateUniversalListResponse(BaseModel):
    id: int
