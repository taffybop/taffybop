"""Bounded native-first visual fallback for unresolved Office regions.

The service deliberately does not bundle or auto-discover a renderer.  A
renderer must be supplied through the small approved protocol below, which
keeps the default production path deterministic and native-only.  Returned
pixels and semantic observations are validated before an atomic, additive
merge; every refusal preserves the native document and records a concern.
"""

from __future__ import annotations

import hashlib
import io
import math
import multiprocessing
import os
import signal
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from PIL import Image, UnidentifiedImageError

from app.config import Settings


FALLBACK_SCHEMA_VERSION = "1.0"
_MAX_RENDER_ITEMS = 256
_MAX_RENDER_TEXT_BYTES = 64 * 1024


class OfficeFallbackError(ValueError):
    """A deterministic, content-free fallback refusal."""

    code = "office_fallback_failed"

    def __init__(self, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(self.code)


class OfficeRendererUnavailableError(OfficeFallbackError):
    code = "office_renderer_unavailable"


class OfficeRendererTimeoutError(OfficeFallbackError):
    code = "office_renderer_timeout"


class OfficeRendererLimitError(OfficeFallbackError):
    code = "office_renderer_resource_limit"


@dataclass(frozen=True, slots=True)
class OfficeRenderRequest:
    schema_version: str
    document_sha256: str
    input_format: str
    logical_index: int
    logical_label: str
    placeholder_id: str
    source_part: str
    source_xml_path: str | None
    max_width: int
    max_height: int
    max_pixels: int
    max_renderer_bytes: int
    timeout_seconds: float
    target_unit: str
    source_bytes: bytes | None = None

    def __post_init__(self) -> None:
        if self.schema_version != FALLBACK_SCHEMA_VERSION:
            raise ValueError("office render request schema version differs")
        if (
            len(self.document_sha256) != 64
            or any(value not in "0123456789abcdef" for value in self.document_sha256)
        ):
            raise ValueError("office render request document identity differs")
        if self.input_format not in {"docx", "pptx", "xlsx"}:
            raise ValueError("office render request format differs")
        if self.logical_index < 1 or not self.logical_label:
            raise ValueError("office render request logical identity differs")
        if not self.placeholder_id or not self.source_part:
            raise ValueError("office render request source locator differs")
        if self.target_unit not in {"pt", "logical"}:
            raise ValueError("office render request target unit differs")
        if (
            self.max_width < 1
            or self.max_height < 1
            or self.max_pixels < 1
            or isinstance(self.max_renderer_bytes, bool)
            or not isinstance(self.max_renderer_bytes, int)
            or self.max_renderer_bytes < 1
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("office render request bounds differ")


@dataclass(frozen=True, slots=True)
class OfficeRenderResult:
    png_bytes: bytes
    width: int
    height: int
    renderer_name: str
    renderer_version: str
    semantic_items: tuple[Mapping[str, Any], ...] = ()
    transform: tuple[float, float, float, float, float, float] = (
        1.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
    )


@runtime_checkable
class OfficeRenderer(Protocol):
    """Approved renderer boundary used by the fallback transaction."""

    name: str
    version: str
    approved: bool

    def render(self, request: OfficeRenderRequest) -> OfficeRenderResult:
        ...


class UnavailableOfficeRenderer:
    name = "unavailable"
    version = "0"
    approved = False

    def render(self, request: OfficeRenderRequest) -> OfficeRenderResult:
        del request
        raise OfficeRendererUnavailableError()


class DeterministicOfficeRenderer:
    """Small injectable renderer for functional tests and local integrations."""

    name = "deterministic-office-renderer"
    version = "1.0.0"
    approved = True

    def __init__(
        self,
        result: OfficeRenderResult | Callable[[OfficeRenderRequest], OfficeRenderResult],
    ) -> None:
        self._result = result
        self.requests: list[OfficeRenderRequest] = []

    def render(self, request: OfficeRenderRequest) -> OfficeRenderResult:
        self.requests.append(request)
        return self._render_without_recording(request)

    def _render_without_recording(
        self,
        request: OfficeRenderRequest,
    ) -> OfficeRenderResult:
        if callable(self._result):
            return self._result(request)
        return self._result


def _validate_renderer_transport_result(
    result: Any,
    request: OfficeRenderRequest,
) -> OfficeRenderResult:
    """Bound renderer-owned bytes before IPC, decoding, or shared services."""

    if not isinstance(result, OfficeRenderResult):
        raise OfficeFallbackError("office_renderer_result_malformed")
    if type(result.png_bytes) is not bytes:
        raise OfficeFallbackError("office_renderer_image_malformed")
    if len(result.png_bytes) > request.max_renderer_bytes:
        raise OfficeRendererLimitError()
    return result


def _renderer_process_entry(
    renderer: OfficeRenderer,
    request: OfficeRenderRequest,
    connection: Any,
) -> None:
    """Run one renderer call in a disposable, process-group-owned worker."""

    isolated_group = False
    if hasattr(os, "setsid"):
        try:
            os.setsid()
            isolated_group = True
        except OSError:
            isolated_group = False
    try:
        connection.send(("ready", isolated_group))
        result = (
            renderer._render_without_recording(request)
            if isinstance(renderer, DeterministicOfficeRenderer)
            else renderer.render(request)
        )
        # Refuse oversized renderer-owned payloads in the disposable child so
        # they never cross the process pipe. The parent repeats this check
        # before accepting the result as a defense against transport defects.
        result = _validate_renderer_transport_result(result, request)
        connection.send(("ok", result))
    except TimeoutError:
        connection.send(("timeout", None))
    except OfficeFallbackError as error:
        connection.send(("office_error", error.code))
    except BaseException:
        # Renderer exceptions and their messages are private to the isolated
        # worker. The parent receives one stable, content-free failure state.
        try:
            connection.send(("error", None))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def _terminate_renderer_process(
    process: multiprocessing.Process,
    *,
    isolated_group: bool,
) -> None:
    """Stop and reap a renderer worker without leaving descendant work."""

    if not process.is_alive():
        process.join()
        return
    terminated_group = False
    if isolated_group and hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            terminated_group = True
        except (OSError, ProcessLookupError):
            terminated_group = False
    if not terminated_group:
        process.terminate()
    process.join(0.25)
    if isolated_group and hasattr(os, "killpg"):
        # Kill the whole private group even if its leader honored SIGTERM;
        # renderer-created descendants must not outlive the refusal.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            if process.is_alive():
                process.kill()
    elif process.is_alive():
        process.kill()
    if process.is_alive():
        process.join()


def _clean_finished_renderer_group(process_pid: int) -> None:
    """Remove background descendants left by an otherwise finished renderer."""

    if hasattr(os, "killpg"):
        try:
            os.killpg(process_pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass


def _receive_before_deadline(
    connection: Any,
    deadline: float,
) -> tuple[str, Any]:
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not connection.poll(remaining):
        raise OfficeRendererTimeoutError()
    try:
        message = connection.recv()
    except (EOFError, OSError) as exc:
        raise OfficeFallbackError("office_renderer_failed") from exc
    if (
        not isinstance(message, tuple)
        or len(message) != 2
        or not isinstance(message[0], str)
    ):
        raise OfficeFallbackError("office_renderer_failed")
    return message


def _invoke_renderer_isolated(
    renderer: OfficeRenderer,
    request: OfficeRenderRequest,
) -> OfficeRenderResult:
    """Invoke one approved renderer behind a hard, cancellable deadline."""

    if not bool(getattr(renderer, "approved", False)) or not callable(
        getattr(renderer, "render", None)
    ):
        raise OfficeRendererUnavailableError()
    # Preserve the deterministic test/integration double's observable request
    # log in the parent; mutable child state is intentionally discarded.
    if isinstance(renderer, DeterministicOfficeRenderer):
        renderer.requests.append(request)

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_renderer_process_entry,
        args=(renderer, request, sender),
        daemon=True,
        name="office-renderer-isolate",
    )
    deadline = time.monotonic() + request.timeout_seconds
    started = False
    isolated_group = False
    try:
        try:
            process.start()
            started = True
        except (OSError, RuntimeError, TypeError) as exc:
            raise OfficeFallbackError("office_renderer_failed") from exc
        finally:
            sender.close()

        status, payload = _receive_before_deadline(receiver, deadline)
        if status != "ready" or not isinstance(payload, bool):
            raise OfficeFallbackError("office_renderer_failed")
        isolated_group = payload
        status, payload = _receive_before_deadline(receiver, deadline)

        remaining = max(deadline - time.monotonic(), 0.0)
        process.join(remaining)
        if process.is_alive():
            raise OfficeRendererTimeoutError()
        if status == "timeout":
            raise OfficeRendererTimeoutError()
        if status == "office_error" and isinstance(payload, str):
            raise OfficeFallbackError(payload)
        if status != "ok" or not isinstance(payload, OfficeRenderResult):
            raise OfficeFallbackError("office_renderer_failed")
        return _validate_renderer_transport_result(payload, request)
    finally:
        receiver.close()
        sender.close()
        if started and process.is_alive():
            _terminate_renderer_process(
                process,
                isolated_group=isolated_group,
            )
        elif started and isolated_group:
            _clean_finished_renderer_group(process.pid)


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _item_text(item: Mapping[str, Any]) -> str:
    return str(
        item.get("text")
        or item.get("value")
        or item.get("ocr_text")
        or item.get("md")
        or ""
    ).strip()


def _placeholder(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in ("office_placeholder", "native_placeholder", "placeholder"):
        candidate = item.get(key)
        if isinstance(candidate, Mapping):
            status = str(candidate.get("status") or "unsupported").casefold()
            if status in {"unsupported", "unresolved", "deferred"}:
                return candidate
    if item.get("fallback_eligible") is True:
        return item
    return None


def _append_concern(item: dict[str, Any], code: str) -> None:
    concerns = item.setdefault("parse_concerns", [])
    if code not in concerns:
        concerns.append(code)


def _validate_render_transform(
    transform: Sequence[float],
    *,
    width: int,
    height: int,
) -> None:
    """Reject singular/overflowing matrices and non-finite image corners."""

    a, b, c, d, e, f = (float(value) for value in transform)
    diagonal_product = a * d
    cross_product = b * c
    determinant = diagonal_product - cross_product
    if (
        not math.isfinite(diagonal_product)
        or not math.isfinite(cross_product)
        or not math.isfinite(determinant)
        or abs(determinant) <= 1e-12
    ):
        raise OfficeFallbackError("office_renderer_transform_invalid")
    for x, y in (
        (0.0, 0.0),
        (float(width), 0.0),
        (0.0, float(height)),
        (float(width), float(height)),
    ):
        projected_x = a * x + c * y + e
        projected_y = b * x + d * y + f
        if not math.isfinite(projected_x) or not math.isfinite(projected_y):
            raise OfficeFallbackError("office_renderer_transform_invalid")


def _validate_result(
    result: OfficeRenderResult,
    request: OfficeRenderRequest,
) -> tuple[dict[str, Any], ...]:
    result = _validate_renderer_transport_result(result, request)
    if (
        not result.renderer_name.strip()
        or not result.renderer_version.strip()
        or result.width < 1
        or result.height < 1
        or result.width > request.max_width
        or result.height > request.max_height
        or result.width * result.height > request.max_pixels
    ):
        raise OfficeRendererLimitError()
    if not result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise OfficeFallbackError("office_renderer_image_malformed")
    try:
        with Image.open(io.BytesIO(result.png_bytes)) as image:
            if image.format != "PNG" or image.size != (result.width, result.height):
                raise OfficeFallbackError("office_renderer_image_malformed")
            image.verify()
    except OfficeFallbackError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise OfficeFallbackError("office_renderer_image_malformed") from exc
    if len(result.semantic_items) > _MAX_RENDER_ITEMS:
        raise OfficeRendererLimitError()
    if len(result.transform) != 6 or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in result.transform
    ):
        raise OfficeFallbackError("office_renderer_transform_invalid")
    _validate_render_transform(
        result.transform,
        width=result.width,
        height=result.height,
    )

    validated: list[dict[str, Any]] = []
    total_text_bytes = 0
    for index, raw in enumerate(result.semantic_items):
        if not isinstance(raw, Mapping):
            raise OfficeFallbackError("office_renderer_semantics_malformed")
        item_type = str(raw.get("type") or "text").strip().casefold()
        text = _item_text(raw)
        if item_type not in {
            "text",
            "heading",
            "table",
            "image",
            "chart",
            "diagram",
        } or not text:
            raise OfficeFallbackError("office_renderer_semantics_malformed")
        total_text_bytes += len(text.encode("utf-8"))
        if total_text_bytes > _MAX_RENDER_TEXT_BYTES:
            raise OfficeRendererLimitError()
        validated.append(
            {
                "id": str(
                    raw.get("id")
                    or f"{request.placeholder_id}:rendered:{index}"
                ),
                "type": item_type,
                "text": text,
                "origin": "rendered",
                "evidence_method": str(raw.get("evidence_method") or "ocr"),
                "relationships": deepcopy(raw.get("relationships") or []),
                "concerns": sorted(
                    {
                        str(value)
                        for value in raw.get("concerns") or []
                        if isinstance(value, str) and value
                    }
                ),
            }
        )
    return _validate_shared_visual_observations(result, request, validated)


def _validate_shared_visual_observations(
    result: OfficeRenderResult,
    request: OfficeRenderRequest,
    items: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Admit Office-render observations through the P07-US02 contract."""

    from app.services.adapter_contracts import AdapterCoordinateTransform
    from app.services.visual_parity import (
        SharedVisualServiceRequest,
        VisualParityElement,
        VisualParityEnvelope,
        VisualParityRelationship,
        VisualParitySource,
        normalize_visual_semantics,
        run_shared_visual_service,
    )

    image_sha256 = hashlib.sha256(result.png_bytes).hexdigest()
    source_id = f"office-render-{image_sha256[:24]}"
    try:
        source = VisualParitySource(
            source_id=source_id,
            variant="office_render",
            content_origin="office_rendered_region",
            page_index=request.logical_index,
            page_label=request.logical_label,
            source_width=float(result.width),
            source_height=float(result.height),
            source_sha256=image_sha256,
            transform_to_common=AdapterCoordinateTransform(
                id=f"{source_id}-identity",
                source_unit="px",
                target_unit="px",
                matrix=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            ),
        )
        elements = [
            VisualParityElement(
                id=str(item["id"]),
                ordinal=index,
                page_index=request.logical_index,
                type=str(item["type"]),
                text=str(item["text"]),
                role="primary",
                bbox=None,
                content_origin="rendered",
                evidence_methods=[str(item["evidence_method"])],
                source_locator=request.source_part,
            )
            for index, item in enumerate(items)
        ]
        relationships = [
            VisualParityRelationship.model_validate(dict(relationship), strict=True)
            for item in items
            for relationship in item.get("relationships") or []
        ]
        envelope = VisualParityEnvelope(
            source=source,
            elements=elements,
            relationships=relationships,
            concerns=sorted(
                {
                    str(concern)
                    for item in items
                    for concern in item.get("concerns") or []
                }
            ),
        )
        shared_request = SharedVisualServiceRequest(
            request_id=f"request-{image_sha256[:24]}",
            source=source,
            raster_width=result.width,
            raster_height=result.height,
            raster_byte_length=len(result.png_bytes),
            raster_sha256=image_sha256,
            raster_bytes=result.png_bytes,
            evidence_ids=[],
        )
        admitted = run_shared_visual_service(
            shared_request,
            lambda _request: envelope,
        )
        normalized = normalize_visual_semantics(admitted)
        if len(normalized.elements) != len(items):
            raise ValueError("shared visual observation count differs")
    except (TypeError, ValueError) as exc:
        raise OfficeFallbackError("office_renderer_semantics_malformed") from exc
    return tuple(deepcopy(dict(item)) for item in items)


def _fallback_sidecar(
    *,
    request: OfficeRenderRequest,
    result: OfficeRenderResult | None,
    status: str,
    reason: str | None,
    semantic_items: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "schema_version": FALLBACK_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "native_authority": True,
        "placeholder_id": request.placeholder_id,
        "source_part": request.source_part,
        "source_xml_path": request.source_xml_path,
        "logical_index": request.logical_index,
        "logical_label": request.logical_label,
        "renderer": (
            {
                "name": result.renderer_name,
                "version": result.renderer_version,
                "image_sha256": hashlib.sha256(result.png_bytes).hexdigest(),
                "width": result.width,
                "height": result.height,
            }
            if result is not None
            else None
        ),
        "transform": list(result.transform) if result is not None else None,
        "transform_source_unit": "px" if result is not None else None,
        "transform_target_unit": request.target_unit if result is not None else None,
        "items": [deepcopy(dict(item)) for item in semantic_items],
    }


def _validated_fallback_sidecar(
    *,
    request: OfficeRenderRequest,
    result: OfficeRenderResult | None,
    status: str,
    reason: str | None,
    semantic_items: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Close public-model bounds before a region transaction is committed."""

    from pydantic import ValidationError

    from app.models import OfficeVisualFallback

    raw = _fallback_sidecar(
        request=request,
        result=result,
        status=status,
        reason=reason,
        semantic_items=semantic_items,
    )
    try:
        validated = OfficeVisualFallback.model_validate(raw, strict=True)
    except ValidationError as exc:
        raise OfficeFallbackError("office_renderer_result_malformed") from exc
    return validated.model_dump(mode="json")


def _validated_processing_summary(
    *,
    rendered_count: int,
    merged_count: int,
    duplicate_count: int,
    failed_count: int,
) -> dict[str, Any]:
    """Keep service counters within the same typed bounds as the API model."""

    from pydantic import ValidationError

    from app.models import OfficeFallbackProcessingSummary

    raw = {
        "schema_version": FALLBACK_SCHEMA_VERSION,
        "status": "completed" if failed_count == 0 else "completed_with_concerns",
        "rendered_region_count": rendered_count,
        "merged_item_count": merged_count,
        "deduplicated_item_count": duplicate_count,
        "failed_region_count": failed_count,
        "native_authority": True,
    }
    try:
        validated = OfficeFallbackProcessingSummary.model_validate(raw, strict=True)
    except ValidationError as exc:
        raise OfficeFallbackError("office_fallback_summary_invalid") from exc
    return validated.model_dump(mode="json")


def apply_office_visual_fallback(
    payload: Mapping[str, Any],
    settings: Settings,
    *,
    renderer: OfficeRenderer | None = None,
    source_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Add validated visual evidence only to unresolved Office placeholders."""

    predecessor = deepcopy(dict(payload))
    if not settings.adapters_office_fallback_enabled:
        return predecessor

    candidate = deepcopy(predecessor)
    active_renderer: OfficeRenderer = renderer or UnavailableOfficeRenderer()
    document = candidate.get("document")
    input_format = str(
        (candidate.get("processing") or {}).get("input_format")
        or (document or {}).get("source_format")
        or ""
    ).casefold()
    if input_format not in {"docx", "pptx", "xlsx"}:
        return predecessor
    document_sha256 = str((document or {}).get("sha256") or "")
    if len(document_sha256) != 64:
        return predecessor

    rendered_count = 0
    merged_count = 0
    duplicate_count = 0
    failed_count = 0
    remaining_pixels = settings.adapters_office_fallback_max_total_pixels
    existing_semantics: set[tuple[int, str, str]] = set()
    for page in candidate.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        page_index = int(page.get("page_index") or 0)
        for item in page.get("items") or []:
            if isinstance(item, Mapping) and _placeholder(item) is None:
                text = _normalized_text(_item_text(item))
                if text:
                    existing_semantics.add(
                        (
                            page_index,
                            str(item.get("type") or "text").casefold(),
                            text,
                        )
                    )

    for page in candidate.get("pages") or []:
        if not isinstance(page, dict):
            continue
        logical_index = int(page.get("page_index") or 0)
        logical_label = str(page.get("page_label") or logical_index)
        target_unit = str(page.get("unit") or "logical").casefold()
        for item in page.get("items") or []:
            if not isinstance(item, dict):
                continue
            placeholder = _placeholder(item)
            office_chart = item.get("office_chart")
            if placeholder is None or (
                isinstance(office_chart, Mapping)
                and office_chart.get("status") == "structured"
            ):
                continue
            if rendered_count >= settings.adapters_office_fallback_max_regions:
                _append_concern(item, "office_renderer_region_limit")
                projected_failed = min(failed_count + 1, 1_000_000)
                _validated_processing_summary(
                    rendered_count=rendered_count,
                    merged_count=merged_count,
                    duplicate_count=duplicate_count,
                    failed_count=projected_failed,
                )
                failed_count = projected_failed
                continue
            if remaining_pixels <= 0:
                _append_concern(item, "office_renderer_resource_limit")
                projected_failed = min(failed_count + 1, 1_000_000)
                _validated_processing_summary(
                    rendered_count=rendered_count,
                    merged_count=merged_count,
                    duplicate_count=duplicate_count,
                    failed_count=projected_failed,
                )
                failed_count = projected_failed
                continue
            source_part = str(
                placeholder.get("source_part")
                or placeholder.get("part")
                or item.get("source_part")
                or (
                    (item.get("native_provenance") or {}).get("part")
                    if isinstance(item.get("native_provenance"), Mapping)
                    else None
                )
                or "unknown"
            )
            request = OfficeRenderRequest(
                schema_version=FALLBACK_SCHEMA_VERSION,
                document_sha256=document_sha256,
                input_format=input_format,
                logical_index=logical_index,
                logical_label=logical_label,
                placeholder_id=str(item.get("id") or f"item-{logical_index}"),
                source_part=source_part,
                source_xml_path=(
                    str(
                        placeholder.get("source_xml_path")
                        or placeholder.get("xml_path")
                        or (
                            (item.get("native_provenance") or {}).get("xml_path")
                            if isinstance(item.get("native_provenance"), Mapping)
                            else None
                        )
                    )
                    if placeholder.get("source_xml_path")
                    or placeholder.get("xml_path")
                    or (
                        (item.get("native_provenance") or {}).get("xml_path")
                        if isinstance(item.get("native_provenance"), Mapping)
                        else None
                    )
                    else None
                ),
                max_width=settings.adapters_office_fallback_max_width,
                max_height=settings.adapters_office_fallback_max_height,
                max_pixels=min(
                    remaining_pixels,
                    settings.adapters_office_fallback_max_width
                    * settings.adapters_office_fallback_max_height,
                ),
                max_renderer_bytes=(
                    settings.adapters_office_fallback_max_renderer_bytes
                ),
                timeout_seconds=settings.adapters_office_fallback_timeout_seconds,
                target_unit=target_unit,
                source_bytes=source_bytes,
            )
            rendered_count += 1
            failure_code: str | None = None
            try:
                result = _invoke_renderer_isolated(active_renderer, request)
                semantics = _validate_result(result, request)
                unique: list[dict[str, Any]] = []
                unique_identities: set[tuple[int, str, str]] = set()
                region_duplicate_count = 0
                for semantic in semantics:
                    identity = (
                        logical_index,
                        str(semantic["type"]).casefold(),
                        _normalized_text(semantic["text"]),
                    )
                    if (
                        identity in existing_semantics
                        or identity in unique_identities
                    ):
                        region_duplicate_count += 1
                        continue
                    unique_identities.add(identity)
                    unique.append(semantic)
                sidecar = _validated_fallback_sidecar(
                    request=request,
                    result=result,
                    status="merged",
                    reason=None,
                    semantic_items=unique,
                )
                _validated_processing_summary(
                    rendered_count=rendered_count,
                    merged_count=merged_count + len(unique),
                    duplicate_count=duplicate_count + region_duplicate_count,
                    failed_count=failed_count,
                )

                # Commit every observable mutation only after both public
                # contracts accept the complete region transaction.
                item["office_visual_fallback"] = sidecar
                remaining_pixels -= result.width * result.height
                existing_semantics.update(unique_identities)
                merged_count += len(unique)
                duplicate_count += region_duplicate_count
                if not unique:
                    _append_concern(item, "office_renderer_no_new_semantics")
            except TimeoutError:
                failure_code = OfficeRendererTimeoutError.code
            except OfficeFallbackError as error:
                failure_code = error.code
            except Exception:
                failure_code = "office_renderer_failed"

            if failure_code is not None:
                try:
                    failure_sidecar = _validated_fallback_sidecar(
                        request=request,
                        result=None,
                        status="unavailable",
                        reason=failure_code,
                    )
                except OfficeFallbackError:
                    # Invalid renderer-provided metadata must not leak through
                    # a malformed public sidecar or fail the entire parse.
                    failure_code = "office_renderer_result_malformed"
                    try:
                        failure_sidecar = _validated_fallback_sidecar(
                            request=request,
                            result=None,
                            status="unavailable",
                            reason=failure_code,
                        )
                    except OfficeFallbackError:
                        failure_sidecar = None
                projected_failed = min(failed_count + 1, 1_000_000)
                try:
                    _validated_processing_summary(
                        rendered_count=rendered_count,
                        merged_count=merged_count,
                        duplicate_count=duplicate_count,
                        failed_count=projected_failed,
                    )
                except OfficeFallbackError:
                    failure_code = "office_fallback_summary_invalid"
                    failure_sidecar = _validated_fallback_sidecar(
                        request=request,
                        result=None,
                        status="unavailable",
                        reason=failure_code,
                    )
                if failure_sidecar is not None:
                    item["office_visual_fallback"] = failure_sidecar
                _append_concern(item, failure_code)
                failed_count = projected_failed

    summary = _validated_processing_summary(
        rendered_count=rendered_count,
        merged_count=merged_count,
        duplicate_count=duplicate_count,
        failed_count=failed_count,
    )
    candidate.setdefault("processing", {})["office_fallback"] = summary
    return candidate


# Stable short alias used by integrations.
apply_office_fallback = apply_office_visual_fallback
