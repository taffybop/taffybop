"""Bounded OCR escalation for font spans that recovery explicitly refused."""

from __future__ import annotations

import hashlib
import math
import multiprocessing
import os
import pickle
import signal
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.font_audit import FontAuditReport
from app.services.font_recovery import FontRecoveryReport
from app.services.ocr import (
    PDF_RENDER_CROP_PADDING_POINTS,
    OCRUnavailableError,
    ImageRegion,
    PdfRegionRequest,
    extract_rendered_pdf_ocr,
)


SELECTIVE_SPAN_OCR_SCHEMA_VERSION = "1.0"
SELECTIVE_RENDER_SCALE = 5.0
SELECTIVE_DPI = 360.0
SELECTIVE_PADDING_POINTS = PDF_RENDER_CROP_PADDING_POINTS
MAX_SELECTIVE_CROP_PIXELS = 4_000_000
MAX_SELECTIVE_PAGE_TARGETS = 16
MAX_SELECTIVE_DOCUMENT_TARGETS = 64
MAX_SELECTIVE_DOCUMENT_PIXELS = 32_000_000
MAX_SELECTIVE_PAGE_AREA_RATIO = 0.05
MAX_SELECTIVE_CROP_SECONDS = 30.0
MAX_SELECTIVE_DOCUMENT_SECONDS = 60.0
MAX_SELECTIVE_CANDIDATES_PER_CROP = 256
MAX_SELECTIVE_TOKENS_PER_CROP = 2_048
MAX_SELECTIVE_CONCERNS = 256
MAX_SELECTIVE_OUTCOMES = 512
MAX_SELECTIVE_IPC_BYTES = 8 * 1024 * 1024
TRANSFORM_TOLERANCE_POINTS = 0.01


class _SelectiveModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SelectiveOCRBBox(_SelectiveModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["pt"] = "pt"


class SelectiveOCRPixelBBox(_SelectiveModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    w: float = Field(gt=0)
    h: float = Field(gt=0)
    unit: Literal["px"] = "px"


class SelectiveOCRToken(_SelectiveModel):
    evidence_id: str
    text: str
    bbox: SelectiveOCRBBox
    crop_pixel_bbox: SelectiveOCRPixelBBox
    confidence: float | None = Field(default=None, ge=0, le=1)
    ocr_pass: Literal["standard", "sparse"]
    word_index: int = Field(ge=0)
    method: Literal["tesseract_tsv"] = "tesseract_tsv"


class SelectiveOCRCandidate(_SelectiveModel):
    evidence_id: str
    span_id: str
    text: str
    bbox: SelectiveOCRBBox
    crop_pixel_bbox: SelectiveOCRPixelBBox
    confidence: float | None = Field(default=None, ge=0, le=1)
    word_count: int = Field(ge=0)
    ocr_pass: Literal["standard", "sparse"]
    tokens: list[SelectiveOCRToken] = Field(
        max_length=MAX_SELECTIVE_TOKENS_PER_CROP
    )
    selected: Literal[False] = False
    method: Literal["selective_pdf_tesseract_tsv"] = (
        "selective_pdf_tesseract_tsv"
    )


class SelectiveOCRCost(_SelectiveModel):
    requested_scale: float = Field(gt=0)
    requested_dpi: float = Field(gt=0)
    page_width_points: float = Field(gt=0)
    page_height_points: float = Field(gt=0)
    actual_dpi_x: float = Field(gt=0)
    actual_dpi_y: float = Field(gt=0)
    pixel_width: int = Field(ge=1)
    pixel_height: int = Field(ge=1)
    pixel_count: int = Field(ge=1)
    rendered_area_points2: float = Field(gt=0)
    page_area_ratio: float = Field(gt=0, le=1)
    requested_page_area_ratio: float = Field(gt=0, le=1)
    realized_crop_bbox: SelectiveOCRBBox
    elapsed_ms: float = Field(ge=0)
    timeout_budget_seconds: float = Field(gt=0)
    crop_to_page_transform: list[float] = Field(min_length=6, max_length=6)
    page_to_crop_transform: list[float] = Field(min_length=6, max_length=6)
    padding_points: float = Field(ge=0)
    padding_clipped: bool
    engine: Literal["tesseract"] = "tesseract"
    engine_version: str | None = None
    languages: list[str] = Field(max_length=16)
    passes_attempted: list[Literal["standard", "sparse"]] = Field(
        max_length=2
    )
    passes_completed: list[Literal["standard", "sparse"]] = Field(
        max_length=2
    )
    psm_by_pass: dict[str, int]
    transform_valid: Literal[True] = True


class SelectiveOCRPassAttempt(_SelectiveModel):
    ocr_pass: Literal["standard", "sparse"]
    psm: Literal[3, 11]
    timeout_seconds: float = Field(gt=0)
    status: Literal[
        "scheduled",
        "completed",
        "timed_out",
        "failed",
        "not_run",
    ]


class SelectiveOCRAttempt(_SelectiveModel):
    requested_scale: float = Field(gt=0)
    requested_dpi: float = Field(gt=0)
    page_width_points: float = Field(gt=0)
    page_height_points: float = Field(gt=0)
    estimated_pixel_width: int = Field(ge=1)
    estimated_pixel_height: int = Field(ge=1)
    estimated_pixel_count: int = Field(ge=1)
    timeout_budget_seconds: float = Field(gt=0)
    elapsed_ms: float | None = Field(default=None, ge=0)
    actual_pixel_width: int | None = Field(default=None, ge=1)
    actual_pixel_height: int | None = Field(default=None, ge=1)
    actual_pixel_count: int | None = Field(default=None, ge=1)
    rendered_area_points2: float | None = Field(default=None, gt=0)
    realized_crop_bbox: SelectiveOCRBBox | None = None
    raw_crop_to_page_transform: list[float] | None = Field(
        default=None,
        min_length=6,
        max_length=6,
    )
    transform_valid: bool | None = None
    passes: list[SelectiveOCRPassAttempt] = Field(
        min_length=2,
        max_length=2,
    )
    status: Literal[
        "started",
        "rendered",
        "completed",
        "timed_out",
        "failed",
    ]


class SelectiveOCRSpanOutcome(_SelectiveModel):
    span_id: str
    page_index: int = Field(ge=1)
    font_ref: str
    font_object_id: int | None = Field(default=None, ge=1)
    audit_run_index: int = Field(ge=1)
    refusal_reason_code: str
    source_bbox: SelectiveOCRBBox
    crop_bbox: SelectiveOCRBBox | None = None
    status: Literal[
        "candidate",
        "no_text",
        "refused",
        "failed",
    ]
    reason_code: str | None = None
    reason_message: str | None = None
    attempt: SelectiveOCRAttempt | None = None
    cost: SelectiveOCRCost | None = None
    candidates: list[SelectiveOCRCandidate] = Field(
        max_length=MAX_SELECTIVE_CANDIDATES_PER_CROP
    )


class SelectiveOCRConcern(_SelectiveModel):
    code: str
    message: str
    span_id: str | None = None
    page_index: int | None = Field(default=None, ge=1)
    font_ref: str | None = None


class SelectiveSpanOCRReport(_SelectiveModel):
    schema_version: Literal["1.0"] = SELECTIVE_SPAN_OCR_SCHEMA_VERSION
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["complete", "partial", "unavailable"]
    known_span_count: int = Field(ge=0)
    terminal_outcome_count: int = Field(ge=0)
    rendered_span_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    token_count: int = Field(ge=0)
    rendered_pixel_count: int = Field(ge=0)
    rendered_area_points2: float = Field(ge=0)
    elapsed_ms: float = Field(ge=0)
    outcomes: list[SelectiveOCRSpanOutcome] = Field(
        max_length=MAX_SELECTIVE_OUTCOMES
    )
    concerns: list[SelectiveOCRConcern] = Field(
        max_length=MAX_SELECTIVE_CONCERNS
    )

    @model_validator(mode="after")
    def validate_bounded_evidence_counts(self) -> "SelectiveSpanOCRReport":
        if self.terminal_outcome_count != len(self.outcomes):
            raise ValueError(
                "terminal_outcome_count must match retained outcomes"
            )
        if self.known_span_count < self.terminal_outcome_count:
            raise ValueError(
                "known_span_count cannot be smaller than retained outcomes"
            )
        candidates = [
            candidate
            for outcome in self.outcomes
            for candidate in outcome.candidates
        ]
        tokens = [
            token
            for candidate in candidates
            for token in candidate.tokens
        ]
        if len(candidates) > (
            MAX_SELECTIVE_DOCUMENT_TARGETS
            * MAX_SELECTIVE_CANDIDATES_PER_CROP
        ):
            raise ValueError(
                "candidate evidence exceeds the document retention bound"
            )
        if len(tokens) > (
            MAX_SELECTIVE_DOCUMENT_TARGETS
            * MAX_SELECTIVE_TOKENS_PER_CROP
        ):
            raise ValueError(
                "token evidence exceeds the document retention bound"
            )
        if self.candidate_count != len(candidates):
            raise ValueError(
                "candidate_count must match retained candidate evidence"
            )
        if self.token_count != len(tokens):
            raise ValueError(
                "token_count must match retained token evidence"
            )
        span_ids = [outcome.span_id for outcome in self.outcomes]
        candidate_ids = [
            candidate.evidence_id for candidate in candidates
        ]
        token_ids = [token.evidence_id for token in tokens]
        if (
            len(span_ids) != len(set(span_ids))
            or len(candidate_ids) != len(set(candidate_ids))
            or len(token_ids) != len(set(token_ids))
        ):
            raise ValueError(
                "selective OCR evidence identities must be unique"
            )
        if any(
            candidate.span_id != outcome.span_id
            for outcome in self.outcomes
            for candidate in outcome.candidates
        ):
            raise ValueError(
                "candidate span identity must match its outcome"
            )
        return self


@dataclass(slots=True)
class _PlannedTarget:
    outcome_index: int
    request: PdfRegionRequest
    crop_bbox: SelectiveOCRBBox
    estimated_pixel_width: int
    estimated_pixel_height: int
    estimated_pixel_count: int
    page_area_ratio: float
    padding_clipped: bool


RenderFunction = Callable[..., dict[int, list[ImageRegion]]]
_DEFAULT_RENDER_FUNCTION = extract_rendered_pdf_ocr


def _bound_worker_result(
    result: Mapping[int, Sequence[ImageRegion]],
    *,
    page_index: int,
) -> dict[int, list[ImageRegion]]:
    """Apply retention limits before a render result crosses IPC."""

    regions = result.get(page_index) or []
    if not isinstance(regions, Sequence) or isinstance(
        regions,
        (str, bytes, bytearray),
    ):
        return {page_index: []}
    retained_regions = [
        region for region in regions[:1] if isinstance(region, ImageRegion)
    ]
    token_budget = MAX_SELECTIVE_TOKENS_PER_CROP
    for region in retained_regions:
        region.text = str(region.text)[:10_000]
        region.warnings = [
            str(warning)[:500]
            for warning in region.warnings[:MAX_SELECTIVE_CONCERNS]
        ]
        region.rejected_lines = []
        retained_lines = []
        for line in region.lines[:MAX_SELECTIVE_CANDIDATES_PER_CROP]:
            line.text = str(line.text)[:10_000]
            retained_tokens = []
            for token in line.tokens[:token_budget]:
                token.text = str(token.text)[:4_096]
                retained_tokens.append(token)
            token_budget -= len(retained_tokens)
            line.tokens = retained_tokens
            retained_lines.append(line)
        region.lines = retained_lines
    return {page_index: retained_regions}


def _default_render_worker(
    connection: Any,
    pdf_bytes: bytes,
    request: PdfRegionRequest,
    render_kwargs: Mapping[str, Any],
) -> None:
    """Run PDFium and Tesseract outside the API worker's process."""

    try:
        if os.name == "posix":
            os.setsid()
        result = _DEFAULT_RENDER_FUNCTION(
            pdf_bytes,
            [request],
            **dict(render_kwargs),
        )
        payload: tuple[Any, ...] = (
            "ok",
            _bound_worker_result(
                result,
                page_index=request.page_index,
            ),
        )
    except BaseException as exc:
        payload = (
            "error",
            type(exc).__name__,
            str(exc)[:500],
        )
    serialized = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    if len(serialized) > MAX_SELECTIVE_IPC_BYTES:
        serialized = pickle.dumps(
            (
                "error",
                "BoundedOutputError",
                "Selective OCR worker output exceeded its IPC bound.",
            ),
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    try:
        connection.send_bytes(serialized)
    finally:
        connection.close()


def _terminate_process(
    process: multiprocessing.Process,
    *,
    terminate_group: bool = False,
) -> None:
    if process.pid is None:
        return
    process_group_id: int | None = None
    if terminate_group and os.name == "posix":
        try:
            observed_group = os.getpgid(process.pid)
            if observed_group == process.pid:
                process_group_id = observed_group
        except ProcessLookupError:
            pass
    if not process.is_alive():
        process.join(timeout=0.1)
        if process_group_id is not None:
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return
    if process_group_id is not None:
        os.killpg(process_group_id, signal.SIGTERM)
    else:
        process.terminate()
    process.join(timeout=1.0)
    if process.is_alive():
        if process_group_id is not None:
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.join(timeout=1.0)


def _invoke_render(
    render_function: RenderFunction,
    pdf_bytes: bytes,
    request: PdfRegionRequest,
    *,
    timeout_seconds: float,
    render_kwargs: Mapping[str, Any],
) -> dict[int, list[ImageRegion]]:
    """Invoke the production renderer with an enforceable wall deadline."""

    if render_function is not _DEFAULT_RENDER_FUNCTION:
        return render_function(
            pdf_bytes,
            [request],
            **dict(render_kwargs),
        )

    context = multiprocessing.get_context("spawn")
    receive_connection, send_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_default_render_worker,
        args=(
            send_connection,
            pdf_bytes,
            request,
            dict(render_kwargs),
        ),
        daemon=True,
    )
    try:
        process.start()
        send_connection.close()
        receive_result: dict[str, Any] = {}

        def receive_payload() -> None:
            try:
                serialized = receive_connection.recv_bytes(
                    maxlength=MAX_SELECTIVE_IPC_BYTES + 1
                )
                receive_result["payload"] = pickle.loads(serialized)
            except BaseException as exc:
                receive_result["error"] = exc

        receiver = threading.Thread(
            target=receive_payload,
            name="selective-ocr-ipc-receiver",
            daemon=True,
        )
        receiver.start()
        receiver.join(timeout_seconds)
        if receiver.is_alive():
            _terminate_process(process, terminate_group=True)
            receiver.join(timeout=1.0)
            raise subprocess.TimeoutExpired(
                cmd="selective-pdf-render-ocr",
                timeout=timeout_seconds,
            )
        if "error" in receive_result:
            raise RuntimeError(
                "Selective OCR worker exited without a result."
            ) from receive_result["error"]
        payload = receive_result.get("payload")
    finally:
        receive_connection.close()
        send_connection.close()
        _terminate_process(process)

    if (
        not isinstance(payload, tuple)
        or len(payload) < 2
        or payload[0] not in {"ok", "error"}
    ):
        raise RuntimeError("Selective OCR worker returned a malformed result.")
    if payload[0] == "ok":
        return payload[1]
    exception_name = str(payload[1])
    detail = str(payload[2]) if len(payload) > 2 else ""
    if exception_name == "OCRUnavailableError":
        raise OCRUnavailableError(detail)
    if exception_name == "TimeoutExpired":
        raise subprocess.TimeoutExpired(
            cmd="tesseract",
            timeout=timeout_seconds,
        )
    raise RuntimeError(
        f"Selective OCR worker failed with {exception_name}: {detail}"
    )


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return prefix + "-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _bbox_payload(value: Mapping[str, Any]) -> SelectiveOCRBBox:
    width_value = value.get("width", value.get("w"))
    height_value = value.get("height", value.get("h"))
    numbers = (
        float(value["x"]),
        float(value["y"]),
        float(width_value),
        float(height_value),
    )
    if not all(math.isfinite(number) for number in numbers):
        raise ValueError("bbox_non_finite")
    return SelectiveOCRBBox(
        x=numbers[0],
        y=numbers[1],
        width=numbers[2],
        height=numbers[3],
    )


def _page_bbox(value: Mapping[str, Any]) -> SelectiveOCRBBox:
    return _bbox_payload(value)


def _crop_pixel_bbox(
    page_bbox: SelectiveOCRBBox,
    page_to_crop_transform: Sequence[float],
) -> SelectiveOCRPixelBBox:
    left, top = _apply_affine(
        page_to_crop_transform,
        page_bbox.x,
        page_bbox.y,
    )
    right, bottom = _apply_affine(
        page_to_crop_transform,
        page_bbox.x + page_bbox.width,
        page_bbox.y + page_bbox.height,
    )
    return SelectiveOCRPixelBBox(
        x=round(left, 3),
        y=round(top, 3),
        w=round(right - left, 3),
        h=round(bottom - top, 3),
    )


def _apply_affine(transform: Sequence[float], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = transform
    return a * x + c * y + e, b * x + d * y + f


def _transforms(
    crop: SelectiveOCRBBox,
    pixel_width: int,
    pixel_height: int,
) -> tuple[list[float], list[float], float, float]:
    scale_x = crop.width / pixel_width
    scale_y = crop.height / pixel_height
    crop_to_page = [
        scale_x,
        0.0,
        0.0,
        scale_y,
        crop.x,
        crop.y,
    ]
    page_to_crop = [
        1.0 / scale_x,
        0.0,
        0.0,
        1.0 / scale_y,
        -crop.x / scale_x,
        -crop.y / scale_y,
    ]
    for point in (
        (0.0, 0.0),
        (float(pixel_width), 0.0),
        (0.0, float(pixel_height)),
        (float(pixel_width), float(pixel_height)),
    ):
        page_point = _apply_affine(crop_to_page, *point)
        round_trip = _apply_affine(page_to_crop, *page_point)
        if (
            abs(round_trip[0] - point[0]) * scale_x
            > TRANSFORM_TOLERANCE_POINTS
            or abs(round_trip[1] - point[1]) * scale_y
            > TRANSFORM_TOLERANCE_POINTS
        ):
            raise ValueError("transform_mismatch")
    return (
        [round(value, 12) for value in crop_to_page],
        [round(value, 12) for value in page_to_crop],
        pixel_width / crop.width * 72.0,
        pixel_height / crop.height * 72.0,
    )


def _validated_affine_transforms(
    transform: Sequence[float],
    pixel_width: int,
    pixel_height: int,
) -> tuple[list[float], list[float], float, float]:
    if len(transform) != 6:
        raise ValueError("transform_mismatch")
    values = tuple(float(value) for value in transform)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("transform_mismatch")
    a, b, c, d, e, f = values
    determinant = a * d - b * c
    if abs(determinant) <= 1e-15:
        raise ValueError("transform_mismatch")
    inverse = (
        d / determinant,
        -b / determinant,
        -c / determinant,
        a / determinant,
        (c * f - d * e) / determinant,
        (b * e - a * f) / determinant,
    )
    for point in (
        (0.0, 0.0),
        (float(pixel_width), 0.0),
        (0.0, float(pixel_height)),
        (float(pixel_width), float(pixel_height)),
    ):
        page_point = _apply_affine(values, *point)
        round_trip = _apply_affine(inverse, *page_point)
        if (
            math.hypot(
                round_trip[0] - point[0],
                round_trip[1] - point[1],
            )
            * max(
                math.hypot(a, b),
                math.hypot(c, d),
            )
            > TRANSFORM_TOLERANCE_POINTS
        ):
            raise ValueError("transform_mismatch")
    x_points_per_pixel = math.hypot(a, b)
    y_points_per_pixel = math.hypot(c, d)
    if x_points_per_pixel <= 0 or y_points_per_pixel <= 0:
        raise ValueError("transform_mismatch")
    return (
        [round(value, 12) for value in values],
        [round(value, 12) for value in inverse],
        72.0 / x_points_per_pixel,
        72.0 / y_points_per_pixel,
    )


def _bbox_matches(
    actual: Mapping[str, Any],
    expected: SelectiveOCRBBox,
    *,
    tolerance: float = TRANSFORM_TOLERANCE_POINTS,
) -> bool:
    try:
        observed = _bbox_payload(actual)
    except (KeyError, TypeError, ValueError):
        return False
    return all(
        abs(first - second) <= tolerance
        for first, second in (
            (observed.x, expected.x),
            (observed.y, expected.y),
            (observed.width, expected.width),
            (observed.height, expected.height),
        )
    )


def _pixel_bbox_within(
    bbox: SelectiveOCRPixelBBox,
    pixel_width: int,
    pixel_height: int,
) -> bool:
    tolerance = 0.01
    return (
        bbox.x + bbox.w <= pixel_width + tolerance
        and bbox.y + bbox.h <= pixel_height + tolerance
    )


def _pixel_bbox_matches_page_bbox(
    pixel_bbox: SelectiveOCRPixelBBox,
    page_bbox: SelectiveOCRBBox,
    crop_to_page: Sequence[float],
) -> bool:
    left, top = _apply_affine(
        crop_to_page,
        pixel_bbox.x,
        pixel_bbox.y,
    )
    right, bottom = _apply_affine(
        crop_to_page,
        pixel_bbox.x + pixel_bbox.w,
        pixel_bbox.y + pixel_bbox.h,
    )
    tolerance = TRANSFORM_TOLERANCE_POINTS
    return all(
        abs(first - second) <= tolerance
        for first, second in (
            (left, page_bbox.x),
            (top, page_bbox.y),
            (right - left, page_bbox.width),
            (bottom - top, page_bbox.height),
        )
    )


def _render_contract_matches(
    region: ImageRegion,
    *,
    outcome: SelectiveOCRSpanOutcome,
    crop_bbox: SelectiveOCRBBox,
    page_size: tuple[float, float] | None,
    pixel_width: int,
    pixel_height: int,
    require_crop_metadata: bool,
) -> bool:
    if (
        region.page_index != outcome.page_index
        or region.region_origin != "pdf_page_render"
        or region.coordinate_unit != "pt"
        or not _bbox_matches(region.bbox, outcome.source_bbox)
    ):
        return False
    raw_crop = region.rendered_crop_bbox
    raw_page = region.rendered_page_size
    raw_transform = region.pixel_to_page_transform
    if require_crop_metadata and (
        not isinstance(raw_crop, Mapping)
        or not isinstance(raw_page, tuple)
        or raw_transform is None
    ):
        return False
    if isinstance(raw_page, tuple):
        if page_size is None:
            return False
        try:
            observed_width = float(raw_page[0])
            observed_height = float(raw_page[1])
        except (IndexError, TypeError, ValueError):
            return False
        if (
            not math.isfinite(observed_width)
            or not math.isfinite(observed_height)
            or abs(observed_width - page_size[0])
            > TRANSFORM_TOLERANCE_POINTS
            or abs(observed_height - page_size[1])
            > TRANSFORM_TOLERANCE_POINTS
        ):
            return False
    if isinstance(raw_crop, Mapping):
        try:
            realized = _bbox_payload(raw_crop)
        except (KeyError, TypeError, ValueError):
            return False
        if raw_transform is None or len(raw_transform) != 6:
            return False
        try:
            transform = tuple(float(value) for value in raw_transform)
        except (TypeError, ValueError):
            return False
        if not all(math.isfinite(value) for value in transform):
            return False
        left, top = _apply_affine(transform, 0.0, 0.0)
        right, bottom = _apply_affine(
            transform,
            float(pixel_width),
            float(pixel_height),
        )
        if any(
            abs(first - second) > TRANSFORM_TOLERANCE_POINTS
            for first, second in (
                (left, realized.x),
                (top, realized.y),
                (right - left, realized.width),
                (bottom - top, realized.height),
            )
        ):
            return False
        quantization_tolerance = max(
            math.hypot(transform[0], transform[1]),
            math.hypot(transform[2], transform[3]),
        ) + TRANSFORM_TOLERANCE_POINTS
        if any(
            abs(first - second) > quantization_tolerance
            for first, second in (
                (realized.x, crop_bbox.x),
                (realized.y, crop_bbox.y),
                (realized.x + realized.width, crop_bbox.x + crop_bbox.width),
                (realized.y + realized.height, crop_bbox.y + crop_bbox.height),
            )
        ):
            return False
    return True


def _engine_version(command: str) -> str | None:
    executable = shutil.which(command.strip()) if command.strip() else None
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first_line = completed.stdout.decode("utf-8", errors="replace").splitlines()
    return first_line[0][:80] if first_line else None


def _concern(
    concerns: list[SelectiveOCRConcern],
    *,
    code: str,
    message: str,
    outcome: SelectiveOCRSpanOutcome | None = None,
) -> None:
    if len(concerns) >= MAX_SELECTIVE_CONCERNS:
        return
    concerns.append(
        SelectiveOCRConcern(
            code=code,
            message=message[:500],
            span_id=outcome.span_id if outcome is not None else None,
            page_index=outcome.page_index if outcome is not None else None,
            font_ref=outcome.font_ref if outcome is not None else None,
        )
    )


def _empty_report(
    source_sha256: str,
    *,
    status: Literal["complete", "partial", "unavailable"],
    code: str | None = None,
    message: str | None = None,
) -> SelectiveSpanOCRReport:
    concerns = (
        [SelectiveOCRConcern(code=code, message=message or code)]
        if code is not None
        else []
    )
    return SelectiveSpanOCRReport(
        source_sha256=source_sha256,
        status=status,
        known_span_count=0,
        terminal_outcome_count=0,
        rendered_span_count=0,
        candidate_count=0,
        token_count=0,
        rendered_pixel_count=0,
        rendered_area_points2=0.0,
        elapsed_ms=0.0,
        outcomes=[],
        concerns=concerns,
    )


def _recovery_provenance_error(
    audit: Mapping[str, Any],
    recovery: Mapping[str, Any],
) -> str | None:
    recovered_refs = {
        str(run.get("font_ref") or "")
        for run in (recovery.get("runs") or [])
        if isinstance(run, Mapping) and run.get("font_ref")
    }
    refusals: dict[
        str,
        tuple[int | None, tuple[int, ...], str, str],
    ] = {}
    for refusal in recovery.get("refusals") or []:
        if not isinstance(refusal, Mapping):
            continue
        font_ref = str(refusal.get("font_ref") or "")
        if not font_ref:
            continue
        raw_pages = refusal.get("page_indexes") or []
        if any(
            isinstance(page_index, bool)
            or not isinstance(page_index, int)
            or page_index < 1
            for page_index in raw_pages
        ):
            return f"Recovery refusal {font_ref} has invalid page scope."
        signature = (
            refusal.get("font_object_id"),
            tuple(sorted(set(raw_pages))),
            str(refusal.get("reason_code") or ""),
            str(refusal.get("message") or ""),
        )
        previous = refusals.get(font_ref)
        if previous is not None and previous != signature:
            return f"Recovery has conflicting refusal records for {font_ref}."
        refusals[font_ref] = signature

    contradictory_refs = sorted(recovered_refs.intersection(refusals))
    if contradictory_refs:
        return (
            "Recovery marks a font both recovered and refused: "
            + contradictory_refs[0]
            + "."
        )

    for finding in audit.get("findings") or []:
        if not isinstance(finding, Mapping):
            continue
        font_ref = str(finding.get("font_ref") or "")
        refusal = refusals.get(font_ref)
        if refusal is None:
            continue
        refusal_object_id, refusal_pages, _, _ = refusal
        if refusal_object_id != finding.get("font_object_id"):
            return (
                "Recovery refusal object identity does not match the audit "
                f"finding for {font_ref}."
            )
        refusal_page_set = set(refusal_pages)
        for run in finding.get("runs") or []:
            if not isinstance(run, Mapping):
                continue
            page_index = run.get("page_index")
            if page_index not in refusal_page_set:
                return (
                    "Recovery refusal page scope does not authorize audited "
                    f"run page {page_index} for {font_ref}."
                )
    return None


def _plan_targets(
    *,
    source_sha256: str,
    audit: Mapping[str, Any],
    recovery: Mapping[str, Any],
    page_sizes: Mapping[int, tuple[float, float]],
) -> tuple[
    list[SelectiveOCRSpanOutcome],
    list[_PlannedTarget],
    list[SelectiveOCRConcern],
    int,
]:
    refusals = {
        str(refusal.get("font_ref")): refusal
        for refusal in (recovery.get("refusals") or [])
        if isinstance(refusal, Mapping) and refusal.get("font_ref")
    }
    outcomes: list[SelectiveOCRSpanOutcome] = []
    planned: list[_PlannedTarget] = []
    concerns: list[SelectiveOCRConcern] = []
    seen_targets: dict[tuple[object, ...], str] = {}
    scheduled_per_page: dict[int, int] = {}
    scheduled_area_per_page: dict[int, float] = {}
    scheduled_pixels = 0
    scheduled_targets = 0
    known_span_count = 0

    for finding in audit.get("findings") or []:
        if not isinstance(finding, Mapping):
            continue
        font_ref = str(finding.get("font_ref") or "")
        refusal = refusals.get(font_ref)
        if refusal is None:
            continue
        refusal_code = str(refusal.get("reason_code") or "recovery_refused")
        font_object_id = finding.get("font_object_id")
        if isinstance(font_object_id, bool) or not isinstance(font_object_id, int):
            font_object_id = None
        retained_runs = finding.get("runs") or []
        declared_run_count = finding.get("run_count")
        if isinstance(declared_run_count, bool) or not isinstance(
            declared_run_count,
            int,
        ):
            declared_run_count = len(retained_runs)
        declared_run_count = max(declared_run_count, len(retained_runs))
        known_span_count += declared_run_count
        if bool(finding.get("runs_truncated")) or (
            declared_run_count > len(retained_runs)
        ):
            _concern(
                concerns,
                code="audit_runs_truncated",
                message=(
                    f"Audit retained {len(retained_runs)} of "
                    f"{declared_run_count} unresolved runs for {font_ref}; "
                    "unretained geometry cannot be rendered."
                ),
            )
        for run_index, raw_run in enumerate(retained_runs, 1):
            if not isinstance(raw_run, Mapping):
                continue
            if len(outcomes) >= MAX_SELECTIVE_OUTCOMES:
                if not any(
                    concern.code == "outcome_retention_limit"
                    for concern in concerns
                ):
                    _concern(
                        concerns,
                        code="outcome_retention_limit",
                        message=(
                            "Selective OCR outcome evidence exceeded its "
                            "retention bound; remaining runs were not rendered."
                        ),
                    )
                break
            page_index_value = raw_run.get("page_index")
            try:
                if isinstance(page_index_value, bool):
                    raise ValueError("page_index_boolean")
                page_index = int(page_index_value)
                if page_index < 1:
                    raise ValueError("page_index_out_of_range")
                source_bbox = _bbox_payload(raw_run.get("bbox") or {})
            except (KeyError, TypeError, ValueError):
                # Invalid geometry still receives a stable terminal outcome.
                fallback_bbox = SelectiveOCRBBox(
                    x=0.0,
                    y=0.0,
                    width=0.001,
                    height=0.001,
                )
                span_id = _stable_id(
                    "selective-span",
                    source_sha256,
                    font_ref,
                    page_index_value,
                    run_index,
                    "invalid",
                )
                try:
                    fallback_page_index = max(int(page_index_value or 1), 1)
                except (TypeError, ValueError):
                    fallback_page_index = 1
                outcome = SelectiveOCRSpanOutcome(
                    span_id=span_id,
                    page_index=fallback_page_index,
                    font_ref=font_ref,
                    font_object_id=font_object_id,
                    audit_run_index=run_index,
                    refusal_reason_code=refusal_code,
                    source_bbox=fallback_bbox,
                    status="refused",
                    reason_code="invalid_source_bbox",
                    reason_message="Audit run bbox is missing, non-finite, or invalid.",
                    candidates=[],
                )
                outcomes.append(outcome)
                _concern(
                    concerns,
                    code="invalid_source_bbox",
                    message=outcome.reason_message or "",
                    outcome=outcome,
                )
                continue

            span_id = _stable_id(
                "selective-span",
                source_sha256,
                font_ref,
                page_index,
                run_index,
                source_bbox.model_dump_json(),
            )
            outcome = SelectiveOCRSpanOutcome(
                span_id=span_id,
                page_index=page_index,
                font_ref=font_ref,
                font_object_id=font_object_id,
                audit_run_index=run_index,
                refusal_reason_code=refusal_code,
                source_bbox=source_bbox,
                status="refused",
                candidates=[],
            )
            outcomes.append(outcome)

            page_size = page_sizes.get(page_index)
            if page_size is None:
                outcome.reason_code = "page_geometry_unavailable"
                outcome.reason_message = "No declared page geometry exists for the span."
            else:
                page_width, page_height = page_size
                if (
                    not math.isfinite(page_width)
                    or not math.isfinite(page_height)
                    or page_width <= 0
                    or page_height <= 0
                ):
                    outcome.reason_code = "page_geometry_invalid"
                    outcome.reason_message = "Declared page geometry is invalid."
                elif (
                    source_bbox.x < 0
                    or source_bbox.y < 0
                    or source_bbox.x + source_bbox.width > page_width + 1e-6
                    or source_bbox.y + source_bbox.height > page_height + 1e-6
                ):
                    outcome.reason_code = "source_bbox_off_page"
                    outcome.reason_message = "Source bbox is outside declared page bounds."
                else:
                    crop_left = max(source_bbox.x - SELECTIVE_PADDING_POINTS, 0.0)
                    crop_top = max(source_bbox.y - SELECTIVE_PADDING_POINTS, 0.0)
                    crop_right = min(
                        source_bbox.x
                        + source_bbox.width
                        + SELECTIVE_PADDING_POINTS,
                        page_width,
                    )
                    crop_bottom = min(
                        source_bbox.y
                        + source_bbox.height
                        + SELECTIVE_PADDING_POINTS,
                        page_height,
                    )
                    crop = SelectiveOCRBBox(
                        x=round(crop_left, 6),
                        y=round(crop_top, 6),
                        width=round(crop_right - crop_left, 6),
                        height=round(crop_bottom - crop_top, 6),
                    )
                    outcome.crop_bbox = crop
                    pixel_width = max(math.ceil(crop.width * SELECTIVE_RENDER_SCALE), 1)
                    pixel_height = max(
                        math.ceil(crop.height * SELECTIVE_RENDER_SCALE),
                        1,
                    )
                    pixel_count = pixel_width * pixel_height
                    page_area_ratio = (
                        crop.width * crop.height / (page_width * page_height)
                    )
                    duplicate_key = (
                        page_index,
                        round(crop.x, 6),
                        round(crop.y, 6),
                        round(crop.width, 6),
                        round(crop.height, 6),
                    )
                    if duplicate_key in seen_targets:
                        outcome.reason_code = "duplicate_target"
                        outcome.reason_message = (
                            "An identical selective crop was already scheduled as "
                            + seen_targets[duplicate_key]
                            + "."
                        )
                    elif pixel_count > MAX_SELECTIVE_CROP_PIXELS:
                        outcome.reason_code = "crop_pixel_limit"
                        outcome.reason_message = "Crop exceeds the per-crop pixel bound."
                    elif (
                        scheduled_area_per_page.get(page_index, 0.0)
                        + page_area_ratio
                        > MAX_SELECTIVE_PAGE_AREA_RATIO + 1e-12
                    ):
                        outcome.reason_code = "page_area_limit"
                        outcome.reason_message = (
                            "Selective crops exceed the per-page area bound."
                        )
                    elif (
                        scheduled_per_page.get(page_index, 0)
                        >= MAX_SELECTIVE_PAGE_TARGETS
                    ):
                        outcome.reason_code = "page_target_limit"
                        outcome.reason_message = (
                            "Selective targets exceed the per-page count bound."
                        )
                    elif scheduled_targets >= MAX_SELECTIVE_DOCUMENT_TARGETS:
                        outcome.reason_code = "document_target_limit"
                        outcome.reason_message = (
                            "Selective targets exceed the document count bound."
                        )
                    elif (
                        scheduled_pixels + pixel_count
                        > MAX_SELECTIVE_DOCUMENT_PIXELS
                    ):
                        outcome.reason_code = "document_pixel_limit"
                        outcome.reason_message = (
                            "Selective crops exceed the document pixel bound."
                        )
                    else:
                        outcome.reason_code = None
                        outcome.reason_message = None
                        seen_targets[duplicate_key] = span_id
                        scheduled_targets += 1
                        scheduled_pixels += pixel_count
                        scheduled_per_page[page_index] = (
                            scheduled_per_page.get(page_index, 0) + 1
                        )
                        scheduled_area_per_page[page_index] = (
                            scheduled_area_per_page.get(page_index, 0.0)
                            + page_area_ratio
                        )
                        request = PdfRegionRequest(
                            page_index=page_index,
                            # The shared renderer applies the policy's
                            # three-point padding around this source box.
                            bbox=source_bbox.model_dump(mode="json"),
                            content_type="text",
                            region_role="content_region",
                            metadata={
                                "render_reason": "unresolved_font_span",
                                "selective_span_id": span_id,
                                "font_ref": font_ref,
                                "audit_run_index": run_index,
                            },
                        )
                        planned.append(
                            _PlannedTarget(
                                outcome_index=len(outcomes) - 1,
                                request=request,
                                crop_bbox=crop,
                                estimated_pixel_width=pixel_width,
                                estimated_pixel_height=pixel_height,
                                estimated_pixel_count=pixel_count,
                                page_area_ratio=page_area_ratio,
                                padding_clipped=(
                                    crop.x
                                    != source_bbox.x - SELECTIVE_PADDING_POINTS
                                    or crop.y
                                    != source_bbox.y - SELECTIVE_PADDING_POINTS
                                    or crop.x + crop.width
                                    != source_bbox.x
                                    + source_bbox.width
                                    + SELECTIVE_PADDING_POINTS
                                    or crop.y + crop.height
                                    != source_bbox.y
                                    + source_bbox.height
                                    + SELECTIVE_PADDING_POINTS
                                ),
                            )
                        )

            if outcome.reason_code is not None:
                _concern(
                    concerns,
                    code=outcome.reason_code,
                    message=outcome.reason_message or outcome.reason_code,
                    outcome=outcome,
                )
    return outcomes, planned, concerns, known_span_count


def run_selective_span_ocr(
    pdf_bytes: bytes,
    audit_report: FontAuditReport | Mapping[str, Any],
    recovery_report: FontRecoveryReport | Mapping[str, Any],
    page_sizes: Mapping[int, tuple[float, float]],
    *,
    tesseract_cmd: str = "tesseract",
    languages: Sequence[str] = ("eng",),
    tessdata_path: str | None = None,
    numeric_cleanup_v2_enabled: bool = False,
    spatial_token_preservation_enabled: bool = False,
    render_function: RenderFunction = _DEFAULT_RENDER_FUNCTION,
    clock: Callable[[], float] = time.perf_counter,
) -> SelectiveSpanOCRReport:
    """OCR explicit recovery refusals without changing primary text."""

    started = clock()
    source_sha256 = (
        hashlib.sha256(pdf_bytes).hexdigest()
        if isinstance(pdf_bytes, bytes)
        else hashlib.sha256(b"").hexdigest()
    )
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
        return _empty_report(
            source_sha256,
            status="unavailable",
            code="invalid_pdf_input",
            message="Selective span OCR requires non-empty immutable PDF bytes.",
        )
    try:
        audit = FontAuditReport.model_validate(
            audit_report.model_dump(mode="json", exclude_none=True)
            if isinstance(audit_report, FontAuditReport)
            else dict(audit_report)
        ).model_dump(mode="json", exclude_none=True)
        recovery = FontRecoveryReport.model_validate(
            recovery_report.model_dump(mode="json", exclude_none=True)
            if isinstance(recovery_report, FontRecoveryReport)
            else dict(recovery_report)
        ).model_dump(mode="json", exclude_none=True)
    except Exception as exc:
        return _empty_report(
            source_sha256,
            status="unavailable",
            code="invalid_source_report",
            message=f"Selective OCR source report is invalid: {type(exc).__name__}.",
        )
    if audit.get("source_sha256") != source_sha256:
        return _empty_report(
            source_sha256,
            status="unavailable",
            code="audit_source_mismatch",
            message="Font-audit source identity does not match the OCR PDF.",
        )
    if audit.get("status") != "complete":
        return _empty_report(
            source_sha256,
            status="unavailable",
            code="audit_incomplete",
            message="Selective span OCR requires a complete font audit.",
        )
    if recovery.get("source_sha256") != source_sha256:
        return _empty_report(
            source_sha256,
            status="unavailable",
            code="recovery_source_mismatch",
            message="Font-recovery source identity does not match the OCR PDF.",
        )
    if recovery.get("status") == "unavailable":
        return _empty_report(
            source_sha256,
            status="unavailable",
            code="recovery_unavailable",
            message="Font recovery was unavailable; explicit refusals are required.",
        )
    provenance_error = _recovery_provenance_error(audit, recovery)
    if provenance_error is not None:
        return _empty_report(
            source_sha256,
            status="unavailable",
            code="invalid_source_report",
            message=(
                "Selective OCR recovery provenance is inconsistent: "
                + provenance_error
            ),
        )

    outcomes, planned, concerns, known_span_count = _plan_targets(
        source_sha256=source_sha256,
        audit=audit,
        recovery=recovery,
        page_sizes=page_sizes,
    )
    if not outcomes and known_span_count == 0:
        report = _empty_report(source_sha256, status="complete")
        report.elapsed_ms = max((clock() - started) * 1000.0, 0.0)
        return report

    deadline = started + MAX_SELECTIVE_DOCUMENT_SECONDS
    engine_version = _engine_version(tesseract_cmd)
    configured_languages = [
        language.strip()
        for language in languages
        if isinstance(language, str) and language.strip()
    ]
    rendered_pixels = 0
    rendered_area = 0.0
    rendered_area_per_page: dict[int, float] = {}
    rendered_spans = 0
    for target in planned:
        outcome = outcomes[target.outcome_index]
        if rendered_pixels >= MAX_SELECTIVE_DOCUMENT_PIXELS:
            outcome.status = "refused"
            outcome.reason_code = "document_pixel_limit"
            outcome.reason_message = (
                "Prior realized crops exhausted the document pixel budget."
            )
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        if (
            rendered_area_per_page.get(outcome.page_index, 0.0)
            >= MAX_SELECTIVE_PAGE_AREA_RATIO
        ):
            outcome.status = "refused"
            outcome.reason_code = "page_area_limit"
            outcome.reason_message = (
                "Prior realized crops exhausted the page area budget."
            )
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        remaining = deadline - clock()
        if remaining <= 0:
            outcome.status = "refused"
            outcome.reason_code = "selective_ocr_deadline"
            outcome.reason_message = "Selective OCR exceeded its document deadline."
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        crop_budget = min(MAX_SELECTIVE_CROP_SECONDS, remaining)
        per_pass_timeout = max(min(crop_budget / 2.0, 15.0), 0.001)
        crop_started = clock()
        page_width, page_height = page_sizes[outcome.page_index]
        outcome.attempt = SelectiveOCRAttempt(
            requested_scale=SELECTIVE_RENDER_SCALE,
            requested_dpi=SELECTIVE_DPI,
            page_width_points=page_width,
            page_height_points=page_height,
            estimated_pixel_width=target.estimated_pixel_width,
            estimated_pixel_height=target.estimated_pixel_height,
            estimated_pixel_count=target.estimated_pixel_count,
            timeout_budget_seconds=crop_budget,
            passes=[
                SelectiveOCRPassAttempt(
                    ocr_pass="standard",
                    psm=3,
                    timeout_seconds=per_pass_timeout,
                    status="scheduled",
                ),
                SelectiveOCRPassAttempt(
                    ocr_pass="sparse",
                    psm=11,
                    timeout_seconds=per_pass_timeout,
                    status="scheduled",
                ),
            ],
            status="started",
        )
        try:
            rendered = _invoke_render(
                render_function,
                pdf_bytes,
                target.request,
                timeout_seconds=crop_budget,
                render_kwargs={
                    "tesseract_cmd": tesseract_cmd,
                    "languages": configured_languages,
                    "timeout_seconds": per_pass_timeout,
                    "render_scale": SELECTIVE_RENDER_SCALE,
                    "max_render_pixels": MAX_SELECTIVE_CROP_PIXELS,
                    "tessdata_path": tessdata_path,
                    **(
                        {"numeric_cleanup_v2_enabled": True}
                        if numeric_cleanup_v2_enabled
                        else {}
                    ),
                    **(
                        {"spatial_token_preservation_enabled": True}
                        if spatial_token_preservation_enabled
                        else {}
                    ),
                },
            )
        except OCRUnavailableError:
            outcome.attempt.elapsed_ms = max(
                (clock() - crop_started) * 1000.0,
                0.0,
            )
            outcome.attempt.status = "failed"
            for pass_attempt in outcome.attempt.passes:
                pass_attempt.status = "not_run"
            outcome.status = "failed"
            outcome.reason_code = "selective_ocr_unavailable"
            outcome.reason_message = "Configured Tesseract became unavailable."
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        except subprocess.TimeoutExpired:
            outcome.attempt.elapsed_ms = max(
                (clock() - crop_started) * 1000.0,
                0.0,
            )
            outcome.attempt.status = "timed_out"
            for pass_attempt in outcome.attempt.passes:
                pass_attempt.status = "timed_out"
            outcome.status = "failed"
            outcome.reason_code = "selective_ocr_timeout"
            outcome.reason_message = "Selective OCR exceeded its crop timeout."
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        except Exception as exc:
            outcome.attempt.elapsed_ms = max(
                (clock() - crop_started) * 1000.0,
                0.0,
            )
            outcome.attempt.status = "failed"
            for pass_attempt in outcome.attempt.passes:
                pass_attempt.status = "not_run"
            outcome.status = "failed"
            outcome.reason_code = "selective_ocr_failed"
            outcome.reason_message = (
                "Selective OCR failed without changing native evidence: "
                f"{type(exc).__name__}."
            )
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue

        elapsed_ms = max((clock() - crop_started) * 1000.0, 0.0)
        outcome.attempt.elapsed_ms = elapsed_ms
        try:
            regions = rendered.get(outcome.page_index) or []
            region = regions[0] if regions else None
        except (AttributeError, IndexError, KeyError, TypeError):
            region = None
        pixel_width = (
            getattr(region, "render_pixel_width", None)
            or getattr(region, "pixel_width", None)
        )
        pixel_height = (
            getattr(region, "render_pixel_height", None)
            or getattr(region, "pixel_height", None)
        )
        if (
            region is None
            or isinstance(pixel_width, bool)
            or not isinstance(pixel_width, int)
            or pixel_width < 1
            or isinstance(pixel_height, bool)
            or not isinstance(pixel_height, int)
            or pixel_height < 1
        ):
            outcome.attempt.status = "failed"
            for pass_attempt in outcome.attempt.passes:
                pass_attempt.status = "not_run"
            outcome.status = "failed"
            outcome.reason_code = "selective_render_unavailable"
            outcome.reason_message = "Selective render produced no bounded region."
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        actual_pixel_count = pixel_width * pixel_height
        outcome.attempt.actual_pixel_width = pixel_width
        outcome.attempt.actual_pixel_height = pixel_height
        outcome.attempt.actual_pixel_count = actual_pixel_count
        raw_region_transform = getattr(
            region,
            "pixel_to_page_transform",
            None,
        )
        if (
            isinstance(raw_region_transform, Sequence)
            and not isinstance(
                raw_region_transform,
                (str, bytes, bytearray),
            )
            and len(raw_region_transform) == 6
        ):
            try:
                outcome.attempt.raw_crop_to_page_transform = [
                    float(value) for value in raw_region_transform
                ]
            except (TypeError, ValueError):
                pass
        warnings = " ".join(
            str(warning)
            for warning in (getattr(region, "warnings", None) or [])
        ).casefold()
        raw_pass_statuses = getattr(
            region,
            "ocr_pass_statuses",
            None,
        )
        if isinstance(raw_pass_statuses, Mapping) and raw_pass_statuses:
            standard_status = str(
                raw_pass_statuses.get("standard") or "not_run"
            )
            sparse_status = str(
                raw_pass_statuses.get("sparse") or "not_run"
            )
        else:
            primary_failure_warning = (
                "rendered-region ocr failed:" in warnings
            )
            primary_timeout_warning = (
                "tesseract timed out" in warnings
                and "sparse-text ocr timed out" not in warnings
            )
            standard_status = (
                "timed_out"
                if primary_timeout_warning
                else ("failed" if primary_failure_warning else "completed")
            )
            if standard_status != "completed":
                sparse_status = "not_run"
            elif "sparse-text ocr timed out" in warnings:
                sparse_status = "timed_out"
            elif "sparse-text ocr failed" in warnings:
                sparse_status = "failed"
            else:
                sparse_status = "completed"
        allowed_pass_statuses = {
            "scheduled",
            "completed",
            "timed_out",
            "failed",
            "not_run",
        }
        if (
            standard_status not in allowed_pass_statuses
            or sparse_status not in allowed_pass_statuses
        ):
            standard_status = "failed"
            sparse_status = "not_run"
        outcome.attempt.passes[0].status = standard_status
        outcome.attempt.passes[1].status = sparse_status
        primary_failure = standard_status == "failed"
        primary_timeout = standard_status == "timed_out"
        sparse_timeout = sparse_status == "timed_out"
        sparse_failure = sparse_status == "failed"
        passes_completed: list[Literal["standard", "sparse"]] = [
            pass_name
            for pass_name, status in (
                ("standard", standard_status),
                ("sparse", sparse_status),
            )
            if status == "completed"
        ]
        passes_attempted: list[Literal["standard", "sparse"]] = [
            pass_name
            for pass_name, status in (
                ("standard", standard_status),
                ("sparse", sparse_status),
            )
            if status != "not_run"
        ]
        raw_realized_crop = getattr(region, "rendered_crop_bbox", None)
        try:
            realized_crop = (
                _bbox_payload(raw_realized_crop)
                if isinstance(raw_realized_crop, Mapping)
                else target.crop_bbox
            )
        except (KeyError, TypeError, ValueError):
            realized_crop = target.crop_bbox
        outcome.attempt.realized_crop_bbox = realized_crop
        outcome.attempt.rendered_area_points2 = (
            realized_crop.width * realized_crop.height
        )
        outcome.attempt.status = "rendered"
        rendered_spans += 1
        rendered_pixels += actual_pixel_count
        rendered_area += outcome.attempt.rendered_area_points2
        realized_page_area_ratio = (
            outcome.attempt.rendered_area_points2
            / (page_width * page_height)
        )
        rendered_area_per_page[outcome.page_index] = (
            rendered_area_per_page.get(outcome.page_index, 0.0)
            + realized_page_area_ratio
        )
        actual_page_area_exceeded = (
            rendered_area_per_page[outcome.page_index]
            > MAX_SELECTIVE_PAGE_AREA_RATIO + 1e-12
        )
        actual_pixel_budget_exceeded = (
            actual_pixel_count > MAX_SELECTIVE_CROP_PIXELS
            or rendered_pixels > MAX_SELECTIVE_DOCUMENT_PIXELS
        )
        if not _render_contract_matches(
            region,
            outcome=outcome,
            crop_bbox=target.crop_bbox,
            page_size=page_sizes.get(outcome.page_index),
            pixel_width=pixel_width,
            pixel_height=pixel_height,
            require_crop_metadata=(
                render_function is _DEFAULT_RENDER_FUNCTION
            ),
        ):
            outcome.attempt.status = "failed"
            outcome.attempt.transform_valid = False
            outcome.status = "failed"
            outcome.reason_code = "transform_mismatch"
            outcome.reason_message = (
                "Rendered crop metadata does not match the audited span."
            )
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        elapsed_budget_exceeded = (
            elapsed_ms / 1000.0 > crop_budget + 1e-9
        )
        try:
            raw_transform = getattr(
                region,
                "pixel_to_page_transform",
                None,
            )
            if raw_transform is None:
                (
                    crop_to_page,
                    page_to_crop,
                    actual_dpi_x,
                    actual_dpi_y,
                ) = _transforms(
                    target.crop_bbox,
                    pixel_width,
                    pixel_height,
                )
            else:
                (
                    crop_to_page,
                    page_to_crop,
                    actual_dpi_x,
                    actual_dpi_y,
                ) = _validated_affine_transforms(
                    raw_transform,
                    pixel_width,
                    pixel_height,
                )
        except ValueError:
            outcome.attempt.status = "failed"
            outcome.attempt.transform_valid = False
            outcome.status = "failed"
            outcome.reason_code = "transform_mismatch"
            outcome.reason_message = "Crop/page transform failed round-trip validation."
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        outcome.attempt.transform_valid = True

        pixel_count = actual_pixel_count
        cost = SelectiveOCRCost(
            requested_scale=SELECTIVE_RENDER_SCALE,
            requested_dpi=SELECTIVE_DPI,
            page_width_points=page_width,
            page_height_points=page_height,
            actual_dpi_x=actual_dpi_x,
            actual_dpi_y=actual_dpi_y,
            pixel_width=pixel_width,
            pixel_height=pixel_height,
            pixel_count=pixel_count,
            rendered_area_points2=(
                outcome.attempt.rendered_area_points2
                or target.crop_bbox.width * target.crop_bbox.height
            ),
            page_area_ratio=(
                (
                    outcome.attempt.rendered_area_points2
                    or target.crop_bbox.width * target.crop_bbox.height
                )
                / (page_width * page_height)
            ),
            requested_page_area_ratio=target.page_area_ratio,
            realized_crop_bbox=(
                outcome.attempt.realized_crop_bbox
                or target.crop_bbox
            ),
            elapsed_ms=elapsed_ms,
            timeout_budget_seconds=crop_budget,
            crop_to_page_transform=crop_to_page,
            page_to_crop_transform=page_to_crop,
            padding_points=SELECTIVE_PADDING_POINTS,
            padding_clipped=target.padding_clipped,
            engine_version=engine_version,
            languages=configured_languages,
            passes_attempted=passes_attempted,
            passes_completed=passes_completed,
            psm_by_pass={"standard": 3, "sparse": 11},
        )
        outcome.cost = cost
        if actual_page_area_exceeded:
            outcome.attempt.status = "failed"
            outcome.status = "failed"
            outcome.reason_code = "actual_page_area_limit"
            outcome.reason_message = (
                "Realized selective crops exceeded the page area budget."
            )
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        if actual_pixel_budget_exceeded:
            outcome.attempt.status = "failed"
            outcome.status = "failed"
            outcome.reason_code = "actual_render_pixel_limit"
            outcome.reason_message = (
                "Selective render output exceeded its recorded pixel budget."
            )
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        if elapsed_budget_exceeded:
            outcome.attempt.status = "timed_out"
            outcome.status = "failed"
            outcome.reason_code = "selective_ocr_timeout"
            outcome.reason_message = "Selective OCR exceeded its crop timeout."
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue
        if primary_failure:
            outcome.attempt.status = "failed"
            outcome.status = "failed"
            outcome.reason_code = "selective_ocr_failed"
            outcome.reason_message = (
                "Selective OCR failed after the bounded crop was rendered."
            )
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
            continue

        tokens_retained = 0
        raw_lines = getattr(region, "lines", None)
        if not isinstance(raw_lines, Sequence) or isinstance(
            raw_lines,
            (str, bytes, bytearray),
        ):
            raw_lines = []
            _concern(
                concerns,
                code="invalid_ocr_output",
                message="Selective OCR returned a malformed line collection.",
                outcome=outcome,
            )
        for line_index, line in enumerate(
            raw_lines[:MAX_SELECTIVE_CANDIDATES_PER_CROP]
        ):
            try:
                line_bbox = _page_bbox(line.bbox)
            except (AttributeError, KeyError, TypeError, ValueError):
                _concern(
                    concerns,
                    code="invalid_ocr_candidate",
                    message=(
                        "Selective OCR discarded a candidate with malformed "
                        "geometry."
                    ),
                    outcome=outcome,
                )
                continue
            candidate_id = _stable_id(
                "selective-ocr",
                outcome.span_id,
                line_index,
                line.text,
                line_bbox.model_dump_json(),
            )
            candidate_tokens: list[SelectiveOCRToken] = []
            for token in getattr(line, "tokens", []):
                if tokens_retained >= MAX_SELECTIVE_TOKENS_PER_CROP:
                    break
                try:
                    token_bbox = _page_bbox(token.bbox)
                    token_pixel_bbox = SelectiveOCRPixelBBox.model_validate(
                        dict(token.crop_pixel_bbox)
                    )
                    if (
                        not _pixel_bbox_within(
                            token_pixel_bbox,
                            pixel_width,
                            pixel_height,
                        )
                        or not _pixel_bbox_matches_page_bbox(
                            token_pixel_bbox,
                            token_bbox,
                            crop_to_page,
                        )
                    ):
                        raise ValueError("token_transform_mismatch")
                    token_pass = (
                        "sparse"
                        if getattr(token, "ocr_pass", "standard") == "sparse"
                        else "standard"
                    )
                    token_model = SelectiveOCRToken(
                        evidence_id=_stable_id(
                            "selective-token",
                            candidate_id,
                            token.word_index,
                            token.text,
                        ),
                        text=token.text,
                        bbox=token_bbox,
                        crop_pixel_bbox=token_pixel_bbox,
                        confidence=token.confidence,
                        ocr_pass=token_pass,
                        word_index=token.word_index,
                    )
                except (AttributeError, TypeError, ValueError):
                    _concern(
                        concerns,
                        code="invalid_ocr_token",
                        message=(
                            "Selective OCR discarded a token whose pixel and "
                            "page geometry did not agree."
                        ),
                        outcome=outcome,
                    )
                    continue
                candidate_tokens.append(token_model)
                tokens_retained += 1
            line_pass: Literal["standard", "sparse"] = (
                "sparse"
                if getattr(line, "ocr_pass", "standard") == "sparse"
                else "standard"
            )
            try:
                candidate_pixel_bbox = _crop_pixel_bbox(
                    line_bbox,
                    page_to_crop,
                )
                if not _pixel_bbox_within(
                    candidate_pixel_bbox,
                    pixel_width,
                    pixel_height,
                ):
                    raise ValueError("candidate_transform_mismatch")
                candidate = SelectiveOCRCandidate(
                    evidence_id=candidate_id,
                    span_id=outcome.span_id,
                    text=line.text,
                    bbox=line_bbox,
                    crop_pixel_bbox=candidate_pixel_bbox,
                    confidence=line.confidence,
                    word_count=line.word_count,
                    ocr_pass=line_pass,
                    tokens=candidate_tokens,
                )
            except (AttributeError, TypeError, ValueError):
                _concern(
                    concerns,
                    code="invalid_ocr_candidate",
                    message=(
                        "Selective OCR discarded a candidate that violated "
                        "the bounded evidence contract."
                    ),
                    outcome=outcome,
                )
                continue
            outcome.candidates.append(candidate)

        if outcome.candidates:
            outcome.attempt.status = (
                "timed_out"
                if primary_timeout or sparse_timeout
                else ("failed" if sparse_failure else "completed")
            )
            outcome.status = "candidate"
            if sparse_timeout:
                outcome.reason_code = "selective_ocr_partial_timeout"
                outcome.reason_message = (
                    "A supplemental OCR pass timed out; retained candidates "
                    "remain unselected."
                )
                _concern(
                    concerns,
                    code=outcome.reason_code,
                    message=outcome.reason_message,
                    outcome=outcome,
                )
            elif sparse_failure:
                outcome.reason_code = "selective_ocr_partial_failure"
                outcome.reason_message = (
                    "A supplemental OCR pass failed; standard candidates "
                    "remain unselected."
                )
                _concern(
                    concerns,
                    code=outcome.reason_code,
                    message=outcome.reason_message,
                    outcome=outcome,
                )
        elif primary_timeout:
            outcome.attempt.status = "timed_out"
            outcome.status = "failed"
            outcome.reason_code = "selective_ocr_timeout"
            outcome.reason_message = "Selective OCR timed out without a candidate."
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
        elif sparse_timeout or sparse_failure:
            outcome.attempt.status = (
                "timed_out" if sparse_timeout else "failed"
            )
            outcome.status = "no_text"
            outcome.reason_code = (
                "selective_ocr_partial_timeout"
                if sparse_timeout
                else "selective_ocr_partial_failure"
            )
            outcome.reason_message = (
                "A supplemental OCR pass did not complete; the standard pass "
                "retained no text."
            )
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )
        else:
            outcome.attempt.status = "completed"
            outcome.status = "no_text"
            outcome.reason_code = "selective_ocr_no_text"
            outcome.reason_message = "Selective OCR returned no text candidate."
            _concern(
                concerns,
                code=outcome.reason_code,
                message=outcome.reason_message,
                outcome=outcome,
            )

    terminal_count = len(outcomes)
    candidate_count = sum(len(outcome.candidates) for outcome in outcomes)
    token_count = sum(
        len(candidate.tokens)
        for outcome in outcomes
        for candidate in outcome.candidates
    )
    partial = terminal_count < known_span_count or any(
        outcome.status in {"refused", "failed"}
        or outcome.reason_code
        in {
            "selective_ocr_partial_timeout",
            "selective_ocr_partial_failure",
        }
        for outcome in outcomes
    ) or any(
        concern.code
        in {
            "invalid_ocr_output",
            "invalid_ocr_candidate",
            "invalid_ocr_token",
        }
        for concern in concerns
    )
    return SelectiveSpanOCRReport(
        source_sha256=source_sha256,
        status="partial" if partial else "complete",
        known_span_count=known_span_count,
        terminal_outcome_count=terminal_count,
        rendered_span_count=rendered_spans,
        candidate_count=candidate_count,
        token_count=token_count,
        rendered_pixel_count=rendered_pixels,
        rendered_area_points2=round(rendered_area, 6),
        elapsed_ms=max((clock() - started) * 1000.0, 0.0),
        outcomes=outcomes,
        concerns=concerns[:MAX_SELECTIVE_CONCERNS],
    )
