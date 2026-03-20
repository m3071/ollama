from __future__ import annotations

from app.models import OCRSpaceParsedResult, OCRSpaceResponse


def build_success_response(parsed_text: str, elapsed_ms: int) -> OCRSpaceResponse:
    return OCRSpaceResponse(
        ParsedResults=[
            OCRSpaceParsedResult(
                TextOverlay=None,
                FileParseExitCode=1,
                ParsedText=parsed_text,
                StructuredData=None,
                ErrorMessage="",
                ErrorDetails="",
                TextOrientation="0",
            )
        ],
        OCRExitCode=1,
        IsErroredOnProcessing=False,
        ErrorMessage=None,
        ErrorDetails=None,
        ProcessingTimeInMilliseconds=str(elapsed_ms),
    )


def build_error_response(
    *,
    message: str,
    details: str,
    elapsed_ms: int = 0,
    file_exit_code: int = -10,
    ocr_exit_code: int = 3,
) -> OCRSpaceResponse:
    return OCRSpaceResponse(
        ParsedResults=[
            OCRSpaceParsedResult(
                TextOverlay=None,
                FileParseExitCode=file_exit_code,
                ParsedText=None,
                StructuredData=None,
                ErrorMessage=message,
                ErrorDetails=details,
                TextOrientation="0",
            )
        ],
        OCRExitCode=ocr_exit_code,
        IsErroredOnProcessing=True,
        ErrorMessage=message,
        ErrorDetails=details,
        ProcessingTimeInMilliseconds=str(elapsed_ms),
    )
