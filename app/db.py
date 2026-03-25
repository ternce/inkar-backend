from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os


class Base(DeclarativeBase):
    pass


def _default_sqlite_url() -> str:
    # backend/app.db рядом с backend/
    return "sqlite:///./app.db"


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", _default_sqlite_url())

    # Railway (and some other platforms) commonly provide Postgres URLs as:
    #   postgresql://user:pass@host:port/db
    # SQLAlchemy's default driver for "postgresql://" is psycopg2.
    # This project uses psycopg (v3), so we normalize to the explicit driver.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    return url


engine = create_engine(
    get_database_url(),
    connect_args={"check_same_thread": False} if get_database_url().startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    # Импорт моделей важен, чтобы Base увидел таблицы
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
