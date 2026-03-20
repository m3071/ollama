from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from io import BytesIO
from typing import Iterator

import httpx
from fastapi import UploadFile
from PIL import Image
from pypdfium2 import PdfDocument

from app.config import get_settings
from app.input_utils import (
    InputPayload,
    InputValidationError,
    parse_data_uri_base64,
    validate_file_metadata,
    validate_payload_size,
    validate_url_value,
)

PDF_MIME_TYPES = {"application/pdf"}


def _safe_suffix(filename: str, fallback: str = ".bin") -> str:
    suffix = os.path.splitext(filename)[1].lower()
    return suffix or fallback


def _guess_extension_from_mime(content_type: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }
    return mapping.get(content_type, ".bin")


def _guess_mime_from_bytes(payload: bytes) -> str:
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    if payload.startswith(b"%PDF"):
        return "application/pdf"
    return "application/octet-stream"


def _write_temp_file(content: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(content)
        return temp_file.name


def _resize_image_if_needed(
    payload: bytes,
    content_type: str,
    max_image_side_px: int,
    jpeg_quality: int,
) -> tuple[bytes, str]:
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        return payload, content_type

    try:
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
            longest_side = max(width, height)
            if image.mode not in {"L", "RGB"}:
                if "A" in image.mode:
                    background = Image.new("RGB", image.size, "white")
                    alpha = image.getchannel("A")
                    background.paste(image.convert("RGB"), mask=alpha)
                    image = background
                else:
                    image = image.convert("RGB")

            image = image.convert("L")

            if longest_side <= max_image_side_px:
                output = BytesIO()
                image.save(
                    output,
                    format="JPEG",
                    quality=jpeg_quality,
                    optimize=True,
                )
                return output.getvalue(), "image/jpeg"

            scale = max_image_side_px / float(longest_side)
            resized = image.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )
            output = BytesIO()
            resized.save(
                output,
                format="JPEG",
                quality=jpeg_quality,
                optimize=True,
            )
            return output.getvalue(), "image/jpeg"
    except OSError:
        return payload, content_type


def _render_pdf_first_page_to_png(pdf_bytes: bytes) -> tuple[bytes, str]:
    pdf_path = _write_temp_file(pdf_bytes, ".pdf")
    png_path = None
    try:
        pdf = PdfDocument(pdf_path)
        if len(pdf) == 0:
            raise InputValidationError("PDF file has no pages")
        bitmap = pdf[0].render(scale=2)
        image = bitmap.to_pil()
        png_path = _write_temp_file(b"", ".png")
        image.save(png_path, format="PNG")
        with open(png_path, "rb") as file_handle:
            return file_handle.read(), "image/png"
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        if png_path and os.path.exists(png_path):
            os.remove(png_path)


def normalize_payload(
    *,
    payload: bytes,
    filename: str,
    content_type: str,
) -> InputPayload:
    settings = get_settings()
    validate_payload_size(len(payload), settings.max_upload_size_bytes)
    detected_type = content_type or _guess_mime_from_bytes(payload)
    if detected_type == "application/octet-stream":
        detected_type = _guess_mime_from_bytes(payload)
    validate_file_metadata(
        filename=filename,
        content_type=detected_type,
        allowed_mime_types=settings.allowed_mime_types_set,
        allowed_extensions=settings.allowed_extensions,
    )

    normalized_content = payload
    normalized_type = detected_type
    normalized_name = filename

    if detected_type in PDF_MIME_TYPES or filename.lower().endswith(".pdf"):
        normalized_content, normalized_type = _render_pdf_first_page_to_png(payload)
        normalized_name = f"{os.path.splitext(filename)[0] or 'document'}.png"

    normalized_content, normalized_type = _resize_image_if_needed(
        normalized_content,
        normalized_type,
        settings.effective_max_image_side_px,
        settings.effective_image_jpeg_quality,
    )

    return InputPayload(
        content=normalized_content,
        filename=normalized_name,
        content_type=normalized_type,
        source=filename,
    )


async def payload_from_upload(file: UploadFile) -> InputPayload:
    settings = get_settings()
    filename = file.filename or "upload.bin"
    content_type = (file.content_type or "").split(";")[0].strip().lower() or "application/octet-stream"
    payload = await file.read()
    validate_payload_size(len(payload), settings.max_upload_size_bytes)
    return normalize_payload(payload=payload, filename=filename, content_type=content_type)


def payload_from_base64(raw_value: str) -> InputPayload:
    decoded, content_type = parse_data_uri_base64(raw_value)
    if content_type == "application/octet-stream":
        content_type = _guess_mime_from_bytes(decoded)
    extension = _guess_extension_from_mime(content_type)
    return normalize_payload(
        payload=decoded,
        filename=f"upload{extension}",
        content_type=content_type,
    )


def payload_from_url(url: str) -> InputPayload:
    settings = get_settings()
    validated_url = validate_url_value(url)

    with httpx.Client(timeout=settings.image_download_timeout_seconds, follow_redirects=True) as client:
        with client.stream("GET", validated_url) as response:
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if content_type and content_type not in settings.allowed_mime_types_set:
                raise InputValidationError(f"Unsupported content type: {content_type}")

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                validate_payload_size(total, settings.max_upload_size_bytes)
                chunks.append(chunk)

    filename = os.path.basename(httpx.URL(validated_url).path) or f"download{_guess_extension_from_mime(content_type)}"
    return normalize_payload(
        payload=b"".join(chunks),
        filename=filename,
        content_type=content_type or "application/octet-stream",
    )


@contextmanager
def temporary_payload_file(payload: InputPayload) -> Iterator[str]:
    temp_path = _write_temp_file(payload.content, _safe_suffix(payload.filename))
    try:
        yield temp_path
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
