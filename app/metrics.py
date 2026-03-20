from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "ocr_api_requests_total",
    "Total number of OCR API requests",
    ["endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "ocr_api_request_latency_seconds",
    "OCR API request latency in seconds",
    ["endpoint"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
OCR_COUNT = Counter(
    "ocr_jobs_total",
    "Total number of OCR executions",
    ["status"],
)
OCR_LATENCY = Histogram(
    "ocr_job_latency_seconds",
    "OCR execution latency in seconds",
    buckets=(1, 2, 5, 10, 30, 60, 120, 300, 600),
)
IN_FLIGHT = Gauge(
    "ocr_in_flight_requests",
    "Number of OCR requests currently being processed",
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
