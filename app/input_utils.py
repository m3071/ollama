from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import UploadFile


class InputValidationError(ValueError):
    """Raised when OCR request input is invalid."""


@dataclass
class InputPayload:
    content: bytes
    filename: str
    content_type: str
    source: str


def normalize_bool(value: bool | str | int | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise InputValidationError(f"Invalid boolean value: {value}")


def ensure_exactly_one_input(
    file: UploadFile | None,
    url: str | None,
    base64_image: str | None,
) -> str:
    provided = [("file", file is not None), ("url", bool(url)), ("base64Image", bool(base64_image))]
    selected = [name for name, exists in provided if exists]
    if len(selected) != 1:
        raise InputValidationError("Exactly one of file, url, or base64Image is required")
    return selected[0]


def validate_url_value(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise InputValidationError("Only http and https URLs are allowed")
    if not parsed.netloc:
        raise InputValidationError("URL must include a host")
    return url


def parse_data_uri_base64(raw_value: str) -> tuple[bytes, str]:
    content_type = "application/octet-stream"
    payload = raw_value.strip()

    if payload.startswith("data:"):
        header, _, data = payload.partition(",")
        if not data or ";base64" not in header.lower():
            raise InputValidationError("base64Image must be a valid base64 payload")
        payload = data
        content_type = header[5:].split(";")[0] or content_type

    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InputValidationError("base64Image is not valid base64 data") from exc

    if not decoded:
        raise InputValidationError("base64Image is empty")

    return decoded, content_type


def get_extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def validate_file_metadata(
    filename: str,
    content_type: str,
    allowed_mime_types: set[str],
    allowed_extensions: set[str],
) -> None:
    extension = get_extension(filename)
    if extension not in allowed_extensions:
        raise InputValidationError(f"Unsupported file extension: {extension or 'unknown'}")
    if content_type and content_type != "application/octet-stream" and content_type not in allowed_mime_types:
        raise InputValidationError(f"Unsupported content type: {content_type}")


def validate_payload_size(size_bytes: int, max_size_bytes: int) -> None:
    if size_bytes > max_size_bytes:
        raise InputValidationError(f"Input file is too large. Max allowed size is {max_size_bytes} bytes")
