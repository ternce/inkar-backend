from __future__ import annotations

from functools import lru_cache
from pydantic import BaseModel
from dotenv import load_dotenv
import os


class Settings(BaseModel):
    environment: str
    cors_allow_origins: list[str]
    phcenter_token: str | None
    phcenter_base_url: str


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    environment = os.getenv("ENVIRONMENT", "dev")

    cors_allow_origins_raw = os.getenv("CORS_ALLOW_ORIGINS")
    cors_allow_origins = (
        [x.strip() for x in cors_allow_origins_raw.split(",") if x.strip()]
        if cors_allow_origins_raw
        else ["http://localhost:5173"]
    )

    return Settings(
        environment=environment,
        cors_allow_origins=cors_allow_origins,
        phcenter_token=os.getenv("PHCENTER_TOKEN"),
        phcenter_base_url=os.getenv("PHCENTER_BASE_URL", "https://ph.center"),
    )
