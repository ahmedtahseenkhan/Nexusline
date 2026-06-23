"""Nexusline API application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nexusline")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience: ensure schema + RLS + seed exist on boot. In production,
    # disable by setting SEED_DATA=false and manage schema with Alembic.
    from app.db.init_db import init_models
    from app.db.seed import seed_if_empty

    try:
        await init_models()
        await seed_if_empty()
    except Exception:  # noqa: BLE001
        logger.exception("Startup DB initialization failed")
        raise
    yield


app = FastAPI(
    title="Nexusline API",
    version="0.1.0",
    description="Modern multi-tenant Governance, Risk & Compliance platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"service": "nexusline", "docs": "/docs", "health": "/health"}
