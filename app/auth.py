from __future__ import annotations

from fastapi import Header

from app.config import get_settings


def verify_api_key(apikey: str | None = Header(default=None)) -> None:
    settings = get_settings()
    configured_key = settings.ocr_api_key.strip()
    if not configured_key:
        return
    if apikey != configured_key:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid API key")
