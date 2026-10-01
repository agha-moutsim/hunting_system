"""
eBay Hunter — FastAPI application entry point.

Run locally (from this directory):
    cd backend
    uvicorn main:app --reload

Interactive docs:
    http://localhost:8000/docs
"""

import logging
import os
import sys

# Ensure this directory is on sys.path so existing modules
# (config, scrapers, db, ...) import exactly as before.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import (
    analyze,
    bulk,
    dashboard,
    deep_search,
    export_api,
    extension,
    filters,
    history,
    hunter,
    status,
    tracker,
    watchlist,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ebay-hunter")

app = FastAPI(
    title="eBay Hunter API",
    description="Product sourcing intelligence for eBay UK resellers.",
    version="1.0.0",
)

# CORS — Vercel frontend + local Next.js dev
_origins = [
    "https://ebay-hunter.vercel.app",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
_extra = os.getenv("CORS_ORIGINS", "")
if _extra:
    _origins.extend([o.strip() for o in _extra.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(status.router, tags=["status"])
app.include_router(analyze.router, prefix="/api", tags=["analyze"])
app.include_router(deep_search.router, prefix="/api", tags=["deep-search"])
app.include_router(bulk.router, prefix="/api", tags=["bulk"])
app.include_router(hunter.router, prefix="/api", tags=["hunter"])
app.include_router(tracker.router, prefix="/api", tags=["tracker"])
app.include_router(watchlist.router, prefix="/api", tags=["watchlist"])
app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
app.include_router(history.router, prefix="/api", tags=["history"])
app.include_router(filters.router, prefix="/api", tags=["filters"])
app.include_router(export_api.router, prefix="/api", tags=["export"])
app.include_router(extension.router, prefix="/api", tags=["extension"])


@app.get("/api/health", tags=["status"])
def health():
    return {"status": "ok"}
