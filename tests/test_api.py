from __future__ import annotations

import base64
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

import api
import app.transport as transport
from app.config import get_settings
from app.ocr_service import OCRService


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl3WJcAAAAASUVORK5CYII="
)


class StubOCRService(OCRService):
    def __init__(self) -> None:
        pass

    def warmup(self) -> dict:
        return {"ready": True}

    def get_model_status(self) -> dict:
        return {
            "configured_model": "stub-model",
            "installed": True,
            "running": True,
            "installed_models": ["stub-model"],
            "running_models": ["stub-model"],
            "gpu_active": True,
            "gpu_required": False,
            "gpu_requirement_met": True,
            "ready_reason": "ready",
        }

    def extract_from_bytes(self, file_bytes: bytes, filename: str | None = None) -> str:
        return f"RAW OCR {filename or 'stub'}\nTotal 70.00"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("OCR_API_KEY", "secret-key")
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    api.settings = get_settings()
    api.ocr_service = StubOCRService()
    with TestClient(api.app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_file_upload_success(client: TestClient) -> None:
    response = client.post(
        "/parse/image",
        headers={"apikey": "secret-key"},
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["OCRExitCode"] == 1
    assert body["ParsedResults"][0]["ParsedText"]
    assert body["ParsedResults"][0]["StructuredData"] is None


def test_url_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api,
        "payload_from_url",
        lambda url: transport.normalize_payload(
            payload=PNG_BYTES,
            filename="remote.png",
            content_type="image/png",
        ),
    )
    response = client.post(
        "/parse/image",
        headers={"apikey": "secret-key"},
        data={"url": "https://example.com/test.png"},
    )
    assert response.status_code == 200
    assert response.json()["OCRExitCode"] == 1


def test_base64_success(client: TestClient) -> None:
    response = client.post(
        "/parse/image",
        headers={"apikey": "secret-key"},
        data={"base64Image": f"data:image/png;base64,{base64.b64encode(PNG_BYTES).decode()}"},
    )
    assert response.status_code == 200
    assert response.json()["OCRExitCode"] == 1


def test_multiple_inputs_rejected(client: TestClient) -> None:
    response = client.post(
        "/parse/image",
        headers={"apikey": "secret-key"},
        data={"url": "https://example.com/test.png"},
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
    )
    body = response.json()
    assert response.status_code == 400
    assert body["OCRExitCode"] == 3


def test_missing_input_rejected(client: TestClient) -> None:
    response = client.post("/parse/image", headers={"apikey": "secret-key"})
    assert response.status_code == 400
    assert response.json()["OCRExitCode"] == 3


def test_bad_apikey_rejected(client: TestClient) -> None:
    response = client.post(
        "/parse/image",
        headers={"apikey": "wrong"},
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 401
    assert response.json()["ErrorDetails"] == "Invalid API key"


def test_oversized_file_rejected(client: TestClient) -> None:
    response = client.post(
        "/parse/image",
        headers={"apikey": "secret-key"},
        files={"file": ("large.png", b"x" * (2 * 1024 * 1024), "image/png")},
    )
    assert response.status_code == 400
    assert "too large" in response.json()["ErrorDetails"].lower()


def test_invalid_base64_rejected(client: TestClient) -> None:
    response = client.post(
        "/parse/image",
        headers={"apikey": "secret-key"},
        data={"base64Image": "data:image/png;base64,not-valid"},
    )
    assert response.status_code == 400
    assert "base64" in response.json()["ErrorDetails"].lower()


def test_ready_fails_when_gpu_required_but_not_active(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRE_GPU", "true")
    get_settings.cache_clear()
    api.settings = get_settings()

    class CpuOnlyStub(StubOCRService):
        def get_model_status(self) -> dict:
            status = super().get_model_status()
            status["gpu_active"] = False
            status["gpu_required"] = True
            status["gpu_requirement_met"] = False
            status["ready_reason"] = "gpu_required_but_model_running_on_cpu"
            return status

    api.ocr_service = CpuOnlyStub()

    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["ready_reason"] == "gpu_required_but_model_running_on_cpu"


def test_parse_rejected_when_gpu_required_but_not_active(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRE_GPU", "true")
    get_settings.cache_clear()
    api.settings = get_settings()

    class CpuOnlyStub(StubOCRService):
        def get_model_status(self) -> dict:
            status = super().get_model_status()
            status["gpu_active"] = False
            status["gpu_required"] = True
            status["gpu_requirement_met"] = False
            status["ready_reason"] = "gpu_required_but_model_running_on_cpu"
            return status

    api.ocr_service = CpuOnlyStub()

    response = client.post(
        "/parse/image",
        headers={"apikey": "secret-key"},
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 503
    assert "gpu is required" in response.json()["ErrorDetails"].lower()
