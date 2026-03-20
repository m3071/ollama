from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth import verify_api_key
from app.config import get_settings
from app.input_utils import InputValidationError, ensure_exactly_one_input, normalize_bool
from app.logging_config import configure_logging
from app.metrics import IN_FLIGHT, metrics_response
from app.middleware import RequestContextMiddleware, ResponseHeadersMiddleware
from app.models import OCRSpaceResponse
from app.ocr_service import (
    InsufficientMemoryError,
    ModelNotInstalledError,
    OCRProcessingError,
    OCRService,
    OCRTimeoutError,
)
from app.response_builders import build_error_response, build_success_response
from app.runtime import ocr_semaphore
from app.transport import payload_from_base64, payload_from_upload, payload_from_url

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("ocr-api")

ocr_service = OCRService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "api_startup",
        extra={"extra_fields": {"backend": "ollama", "ollama_host": settings.ollama_host, "model": settings.ollama_model}},
    )
    await run_in_threadpool(ocr_service.warmup)
    yield


app = FastAPI(title="Typhoon OCR API", version="2.0.0", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(ResponseHeadersMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    started_at = getattr(request.state, "started_at", None)
    elapsed_ms = _elapsed_ms(started_at)
    if exc.status_code == 401:
        payload = build_error_response(message="Unauthorized", details=str(exc.detail), elapsed_ms=elapsed_ms)
    else:
        payload = build_error_response(message="Bad request", details=str(exc.detail), elapsed_ms=elapsed_ms)
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


@app.exception_handler(InputValidationError)
async def input_validation_exception_handler(request: Request, exc: InputValidationError) -> JSONResponse:
    payload = build_error_response(
        message="Bad request",
        details=str(exc),
        elapsed_ms=_elapsed_ms(getattr(request.state, "started_at", None)),
    )
    return JSONResponse(status_code=400, content=payload.model_dump())


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    payload = build_error_response(
        message="Bad request",
        details=str(exc),
        elapsed_ms=_elapsed_ms(getattr(request.state, "started_at", None)),
    )
    return JSONResponse(status_code=400, content=payload.model_dump())


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "typhoon-ocr-api", "environment": settings.app_env}


@app.get("/health/model")
async def health_model() -> dict:
    return ocr_service.get_model_status()


@app.get("/models")
async def models() -> dict:
    status = ocr_service.get_model_status()
    return {
        "configured_model": status["configured_model"],
        "installed_models": status["installed_models"],
        "running_models": status["running_models"],
    }


@app.get("/ready")
async def readiness() -> dict:
    status = ocr_service.get_model_status()
    healthy = status["installed"] and status.get("gpu_requirement_met", True)
    return {"ready": healthy, **status}


@app.get("/metrics")
async def metrics() -> Response:
    return metrics_response()


@app.post("/parse/image", response_model=OCRSpaceResponse)
async def parse_image(
    request: Request,
    _: None = Depends(verify_api_key),
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    base64Image: str | None = Form(default=None),
    language: str = Form(default="eng"),
    OCREngine: str | int = Form(default="2"),
    isOverlayRequired: bool | str | int = Form(default=False),
    detectOrientation: bool | str | int = Form(default=False),
    scale: bool | str | int = Form(default=False),
    isTable: bool | str | int = Form(default=False),
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)

    selected_input = ensure_exactly_one_input(file=file, url=url, base64_image=base64Image)
    overlay_required = normalize_bool(isOverlayRequired, default=False)
    detect_orientation = normalize_bool(detectOrientation, default=False)
    scale_requested = normalize_bool(scale, default=False)
    table_requested = normalize_bool(isTable, default=False)

    logger.info(
        "ocr_request_received",
        extra={
            "request_id": request_id,
            "extra_fields": {
                "input_type": selected_input,
                "language": language,
                "ocr_engine": str(OCREngine),
                "overlay_required": overlay_required,
                "detect_orientation": detect_orientation,
                "scale": scale_requested,
                "is_table": table_requested,
            },
        },
    )

    try:
        if selected_input == "file":
            payload = await payload_from_upload(file)  # type: ignore[arg-type]
        elif selected_input == "url":
            payload = await run_in_threadpool(payload_from_url, url)
        else:
            payload = await run_in_threadpool(payload_from_base64, base64Image)
    except httpx.HTTPError as exc:
        payload = build_error_response(
            message="Bad request",
            details=f"Failed to download URL: {exc}",
            elapsed_ms=_elapsed_ms(request.state.started_at),
        )
        return JSONResponse(status_code=400, content=payload.model_dump())

    try:
        status = ocr_service.get_model_status()
        if settings.require_gpu and not status.get("gpu_active", False):
            return _json_error_response(
                status_code=503,
                message="Service unavailable",
                details="GPU is required for this service, but the configured model is not running on GPU.",
                request=request,
            )

        async with ocr_semaphore:
            IN_FLIGHT.inc()
            try:
                parsed_text = await asyncio.wait_for(
                    run_in_threadpool(ocr_service.extract_from_bytes, payload.content, payload.filename),
                    timeout=settings.request_timeout_seconds,
                )
            finally:
                IN_FLIGHT.dec()
    except ModelNotInstalledError as exc:
        return _json_error_response(status_code=500, message="Processing error", details=str(exc), request=request)
    except InsufficientMemoryError as exc:
        return _json_error_response(status_code=500, message="Processing error", details=str(exc), request=request)
    except (OCRTimeoutError, asyncio.TimeoutError) as exc:
        return _json_error_response(status_code=504, message="Processing error", details=str(exc), request=request)
    except OCRProcessingError as exc:
        return _json_error_response(status_code=500, message="Processing error", details=str(exc), request=request)
    except Exception as exc:
        logger.exception("parse_image_failed", extra={"request_id": request_id})
        return _json_error_response(status_code=500, message="Processing error", details=str(exc), request=request)

    response_model = build_success_response(
        parsed_text=parsed_text,
        elapsed_ms=_elapsed_ms(request.state.started_at),
    )
    response = JSONResponse(status_code=200, content=response_model.model_dump())
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def _json_error_response(status_code: int, message: str, details: str, request: Request) -> JSONResponse:
    payload = build_error_response(
        message=message,
        details=details,
        elapsed_ms=_elapsed_ms(getattr(request.state, "started_at", None)),
    )
    response = JSONResponse(status_code=status_code, content=payload.model_dump())
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def _elapsed_ms(started_at: float | None) -> int:
    if started_at is None:
        return 0
    return int((time.perf_counter() - started_at) * 1000)
