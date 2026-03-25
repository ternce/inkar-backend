from __future__ import annotations

from datetime import datetime, date
from sqlalchemy import (
    String,
    Integer,
    DateTime,
    Date,
    ForeignKey,
    Numeric,
    UniqueConstraint,
    Index,
    Boolean,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512))
    cost: Mapped[float] = mapped_column(Numeric(18, 4), default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PriceFormat(Base):
    __tablename__ = "price_formats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    branch: Mapped[str] = mapped_column(String(128), default="")

    pricing_rule: Mapped[str] = mapped_column(String(256), default="")
    progib: Mapped[float] = mapped_column(Numeric(18, 4), default=0)  # абсолютное значение (деньги)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    markup_ranges: Mapped[list[MarkupRange]] = relationship(
        back_populates="price_format", cascade="all, delete-orphan"
    )


class MarkupRange(Base):
    __tablename__ = "markup_ranges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price_format_id: Mapped[int] = mapped_column(ForeignKey("price_formats.id"), index=True)

    cost_from: Mapped[float] = mapped_column(Numeric(18, 4))
    cost_to: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    markup_percent: Mapped[float] = mapped_column(Numeric(18, 4))  # 0.10 == 10%

    price_format: Mapped[PriceFormat] = relationship(back_populates="markup_ranges")

    __table_args__ = (
        Index("ix_markup_ranges_pf_from_to", "price_format_id", "cost_from", "cost_to"),
    )


class PriceList(Base):
    __tablename__ = "price_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    price_format_id: Mapped[int] = mapped_column(ForeignKey("price_formats.id"), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    activation_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    user: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(64), default="Черновик")


class CompetitorPrice(Base):
    __tablename__ = "competitors_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    price_format_id: Mapped[int] = mapped_column(ForeignKey("price_formats.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)

    source_name: Mapped[str] = mapped_column(String(128))  # например: "Персентиль 10"
    supplier: Mapped[str] = mapped_column(String(256), default="")
    price_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    coefficient: Mapped[float] = mapped_column(Numeric(18, 6), default=1.0)
    source_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    # Если product_id is NULL, то это запись-настройка источника (коэффициент и т.п.)

    __table_args__ = (
        Index(
            "ix_competitors_prices_pf_source_product",
            "price_format_id",
            "source_name",
            "product_id",
        ),
    )


class UniversalList(Base):
    __tablename__ = "universal_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(512))

    status: Mapped[str] = mapped_column(String(64), default="Не активный")
    type: Mapped[str] = mapped_column(String(128))

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Список может быть привязан к ЦФ (если NULL — глобальный)
    price_format_id: Mapped[int | None] = mapped_column(ForeignKey("price_formats.id"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ListItem(Base):
    __tablename__ = "list_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    universal_list_id: Mapped[int] = mapped_column(ForeignKey("universal_lists.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)

    # Значение параметра зависит от типа списка:
    # - фикс цена: fixed price
    # - макс наценка: max markup percent (0.20 == 20%)
    # - мин цена: min price
    # - гос цена: government price
    # - фикс наценка: fixed markup percent (0.50 == 50%)
    value: Mapped[float] = mapped_column(Numeric(18, 6))

    __table_args__ = (
        UniqueConstraint("universal_list_id", "product_id", name="uq_list_items_list_product"),
    )


class CalculatedPrice(Base):
    __tablename__ = "calculated_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)

    cost: Mapped[float] = mapped_column(Numeric(18, 4))
    base_price: Mapped[float] = mapped_column(Numeric(18, 4))

    competitor_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_from_competitor: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    final_price: Mapped[float] = mapped_column(Numeric(18, 4))
    applied_reason: Mapped[str] = mapped_column(String(256), default="")

    zone: Mapped[str] = mapped_column(String(32), default="no-data")  # left|optimal|right|no-data

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("price_list_id", "product_id", name="uq_calculated_prices_pl_product"),
        Index("ix_calculated_prices_pl_zone", "price_list_id", "zone"),
    )
