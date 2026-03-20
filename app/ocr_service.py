from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from typing import Any

import ollama

from app.config import get_settings
from app.metrics import OCR_COUNT, OCR_LATENCY

OCR_PROMPT = "Extract printed text only. Return plain text with line breaks. No descriptions."

logger = logging.getLogger("ocr-service")


class OCRService:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.ollama_client = ollama.Client(host=settings.ollama_host)

    def extract_from_bytes(self, file_bytes: bytes, filename: str | None = None) -> str:
        suffix = os.path.splitext(filename or "")[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            temp_path = tmp_file.name
            tmp_file.write(file_bytes)

        try:
            return self.extract_from_path(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def extract_text_from_bytes(self, file_bytes: bytes, filename: str | None = None) -> str:
        return self.extract_from_bytes(file_bytes, filename)

    def extract_from_path(self, image_path: str) -> str:
        started = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(1, self.settings.ocr_retry_attempts + 1):
            try:
                response = self.ollama_client.chat(
                    model=self.settings.ollama_model,
                    keep_alive=self.settings.ollama_keep_alive,
                    messages=[
                        {
                            "role": "user",
                            "content": OCR_PROMPT,
                            "images": [image_path],
                        }
                    ],
                )
                break
            except ollama.ResponseError as exc:
                normalized = self._map_response_error(exc)
                if isinstance(normalized, (ModelNotInstalledError, InsufficientMemoryError)):
                    OCR_COUNT.labels(status="failed").inc()
                    raise normalized from exc
                last_error = normalized
            except Exception as exc:
                last_error = OCRProcessingError(str(exc))

            if attempt < self.settings.ocr_retry_attempts:
                time.sleep(self.settings.ocr_retry_backoff_seconds * attempt)
        else:
            OCR_COUNT.labels(status="failed").inc()
            raise last_error or OCRProcessingError("OCR failed without a detailed error.")

        content = self._clean_output(response["message"]["content"])
        if not content:
            OCR_COUNT.labels(status="failed").inc()
            raise OCRProcessingError("Model response is empty.")

        OCR_COUNT.labels(status="success").inc()
        OCR_LATENCY.observe(time.perf_counter() - started)
        return content

    def get_model_status(self) -> dict[str, Any]:
        installed_models: list[str] = []
        running_models: list[str] = []
        running_model_name = ""
        running_size_bytes = 0
        running_size_vram_bytes = 0

        try:
            models_response = self.ollama_client.list()
            installed_models = [model.model for model in models_response.models]
        except Exception:
            installed_models = []

        try:
            running_response = self.ollama_client.ps()
            running_models = [model.model for model in running_response.models]
            for model in running_response.models:
                if model.model.startswith(self.settings.ollama_model):
                    running_model_name = model.model
                    running_size_bytes = int(getattr(model, "size", 0) or 0)
                    running_size_vram_bytes = int(getattr(model, "size_vram", 0) or 0)
                    break
        except Exception:
            running_models = []

        configured_model = self.settings.ollama_model
        installed = any(name.startswith(configured_model) for name in installed_models)
        running = any(name.startswith(configured_model) for name in running_models)
        gpu_active = running_size_vram_bytes > 0
        processor_summary = "gpu" if gpu_active else ("cpu" if running else "idle")

        return {
            "backend": "ollama",
            "configured_model": configured_model,
            "installed": installed,
            "running": running,
            "installed_models": installed_models,
            "running_models": running_models,
            "device": "ollama",
            "acceleration": self.settings.ollama_acceleration,
            "gpu_hint": self.settings.system_gpu_hint,
            "gpu_name": self.settings.system_gpu_name,
            "running_model": running_model_name,
            "running_size_bytes": running_size_bytes,
            "running_size_vram_bytes": running_size_vram_bytes,
            "gpu_active": gpu_active,
            "processor_summary": processor_summary,
            "gpu_required": self.settings.require_gpu,
            "gpu_requirement_met": (not self.settings.require_gpu) or gpu_active,
            "ready_reason": self._build_ready_reason(
                installed=installed,
                running=running,
                gpu_active=gpu_active,
            ),
        }

    def warmup(self) -> dict[str, Any]:
        try:
            return self.get_model_status()
        except Exception as exc:
            logger.warning("warmup_failed", extra={"extra_fields": {"error": str(exc)}})
            raise

    def _clean_output(self, text: str) -> str:
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        cleaned = re.sub(r"<figure>.*?</figure>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"</?page_number>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _map_response_error(self, exc: ollama.ResponseError) -> Exception:
        message = str(exc)
        lowered = message.lower()

        if "not found" in lowered:
            return ModelNotInstalledError(
                f"Configured model '{self.settings.ollama_model}' is not installed in Ollama."
            )
        if "requires more system memory" in lowered:
            return InsufficientMemoryError(message)
        if "timed out" in lowered or "timeout" in lowered:
            return OCRTimeoutError(message)

        return OCRProcessingError(message)

    def _build_ready_reason(self, installed: bool, running: bool, gpu_active: bool) -> str:
        if not installed:
            return "model_not_installed"
        if self.settings.require_gpu and not gpu_active:
            if running:
                return "gpu_required_but_model_running_on_cpu"
            return "gpu_required_but_model_not_loaded_on_gpu"
        if running:
            return "ready"
        return "model_installed_not_running"


class OCRProcessingError(Exception):
    """Base OCR processing error."""


class ModelNotInstalledError(OCRProcessingError):
    """Raised when the configured Ollama model is missing."""


class InsufficientMemoryError(OCRProcessingError):
    """Raised when the system does not have enough free memory."""


class OCRTimeoutError(OCRProcessingError):
    """Raised when OCR processing exceeds the configured timeout."""
