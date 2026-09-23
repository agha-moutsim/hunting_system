"""System status endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/status")
def get_status():
    """DB / Ollama / eBay API health."""
    # Database
    db_ok = False
    try:
        from db.database import SessionLocal
        from sqlalchemy import text

        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_ok = True
    except Exception:
        db_ok = False

    # Ollama
    ollama_ok = False
    ollama_model = ""
    try:
        import httpx
        from config import OLLAMA_BASE_URL, OLLAMA_MODEL

        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3.0)
        ollama_ok = resp.status_code == 200
        ollama_model = OLLAMA_MODEL
    except Exception:
        ollama_ok = False

    # eBay keys
    try:
        from config import EBAY_CLIENT_ID

        ebay_ok = bool(EBAY_CLIENT_ID)
    except Exception:
        ebay_ok = False

    return {
        "db": db_ok,
        "ollama": ollama_ok,
        "ollama_model": ollama_model,
        "ebay_api": ebay_ok,
    }
