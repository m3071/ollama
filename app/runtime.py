from __future__ import annotations

import asyncio

from app.config import get_settings

settings = get_settings()
ocr_semaphore = asyncio.Semaphore(settings.max_concurrency)
