from __future__ import annotations

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    ollama_host: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_HOST")
    ollama_model: str = Field(default="scb10x/typhoon-ocr1.5-3b", alias="OLLAMA_MODEL")
    app_env: str = Field(default="production", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    ocr_api_key: str = Field(default="", alias="OCR_API_KEY")
    max_concurrency: int = Field(default=1, alias="MAX_CONCURRENCY")
    max_upload_mb: int = Field(default=10, alias="MAX_UPLOAD_MB")
    request_timeout_seconds: float = Field(default=45.0, alias="REQUEST_TIMEOUT_SECONDS")
    ocr_timeout_seconds: float = Field(default=45.0, alias="OCR_TIMEOUT_SECONDS")
    ocr_retry_attempts: int = Field(default=1, alias="OCR_RETRY_ATTEMPTS")
    ocr_retry_backoff_seconds: float = Field(default=1.0, alias="OCR_RETRY_BACKOFF_SECONDS")
    image_download_timeout_seconds: float = Field(default=15.0, alias="IMAGE_DOWNLOAD_TIMEOUT_SECONDS")
    ocr_speed_preset: str = Field(default="balanced", alias="OCR_SPEED_PRESET")
    max_image_side_px: int = Field(default=1024, alias="MAX_IMAGE_SIDE_PX")
    image_jpeg_quality: int = Field(default=65, alias="IMAGE_JPEG_QUALITY")
    system_gpu_hint: str = Field(default="unknown", alias="SYSTEM_GPU_HINT")
    system_gpu_name: str = Field(default="", alias="SYSTEM_GPU_NAME")
    ollama_acceleration: str = Field(default="auto", alias="OLLAMA_ACCELERATION")
    require_gpu: bool = Field(default=False, alias="REQUIRE_GPU")
    allowed_mime_types: str = Field(
        default="image/jpeg,image/png,image/webp,application/pdf",
        alias="ALLOWED_MIME_TYPES",
    )
    ollama_keep_alive: str = Field(default="24h", alias="OLLAMA_KEEP_ALIVE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @computed_field
    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @computed_field
    @property
    def allowed_mime_types_set(self) -> set[str]:
        return {item.strip().lower() for item in self.allowed_mime_types.split(",") if item.strip()}

    @computed_field
    @property
    def allowed_extensions(self) -> set[str]:
        mapping = {
            "image/jpeg": {".jpg", ".jpeg"},
            "image/png": {".png"},
            "image/webp": {".webp"},
            "application/pdf": {".pdf"},
        }
        extensions: set[str] = set()
        for mime_type in self.allowed_mime_types_set:
            extensions.update(mapping.get(mime_type, set()))
        return extensions

    @computed_field
    @property
    def effective_max_image_side_px(self) -> int:
        if self.ocr_speed_preset.lower() == "fastest":
            return 768
        return self.max_image_side_px

    @computed_field
    @property
    def effective_image_jpeg_quality(self) -> int:
        if self.ocr_speed_preset.lower() == "fastest":
            return 55
        return self.image_jpeg_quality


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
