"""Local document extraction pipeline and normalized document assembly."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import re
import shutil
import threading
import time
import unicodedata
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pypdfium2 as pdfium

from app.config import Settings
from app.errors import (
    DocumentProcessingError,
    ExtractionEngineUnavailableError,
    InvalidPdfError,
    PageLimitExceededError,
)
from app.models import (
    ParseResult,
    _canonical_presentation_sha256,
    _trusted_table_validation_context,
)
from app.services.input_documents import (
    InputKind,
    LoadedDocument,
    load_document,
    load_document_via_adapter,
)
from app.services.ocr import (
    OCRUnavailableError,
    ImageRegion,
    PdfRegionRequest,
    extract_image_ocr,
    extract_raster_ocr,
    extract_rendered_pdf_ocr,
)
from app.services.spatial_tokens import (
    geometry_aware_line_values_with_selection,
    geometry_aware_unique_line_values,
    project_ocr_token_occurrences,
)
from app.services.tables import RawTable, extract_vector_tables


SCHEMA_VERSION = "1.0"
_PAGE_NUMBER_RE = re.compile(r"\bPage\s+([A-Za-z0-9.-]+)\s+of\s+\d+\b", re.I)
_NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+\S")
_PARENTHETICAL_HEADING_RE = re.compile(
    r"^[A-Z][A-Za-z0-9 /&'-]{1,40}\s+\([^)]{1,80}\)$"
)
_TOC_ENTRY_RE = re.compile(r"^\s*\d+(?:\.\d+)*\s+\S.*(?:\.{2,}|\s{2,})\s*\d+\s*$")
_WHITESPACE_RE = re.compile(r"\s+")
_CHART_CLASSIFICATIONS = frozenset(
    {
        "bar_chart",
        "box_plot",
        "heatmap",
        "line_chart",
        "other_chart",
        "pie_chart",
        "scatter_chart",
        "scatter_plot",
        "stacked_bar_chart",
        "stratigraphic_chart",
    }
)
_DIAGRAM_CLASSIFICATIONS = frozenset(
    {
        "cad_drawing",
        "electrical_diagram",
        "engineering_drawing",
        "flow_chart",
    }
)
_TEXTUAL_VISUAL_CLASSIFICATIONS = frozenset(
    {
        "full_page_image",
        "page_thumbnail",
        "screenshot",
        "screenshot_from_computer",
        "screenshot_from_manual",
        "signature",
        "stamp",
        "table",
    }
)
_P04_US01_TABLE_EVIDENCE_KEYS = frozenset(
    {
        "policy_id",
        "version",
        "scope",
        "status",
        "table_id",
        "candidate_id",
        "page_index",
        "grid",
        "slots",
        "source_objects",
        "evidence",
        "span_decisions",
        "representation_custody",
        "reconciliation",
        "gate",
        "continuation",
        "concerns",
    }
)
_P03_MANUAL_CANONICAL_OVERLAY_KEYS = frozenset(
    {
        "caption_ids",
        "caption_of",
        "contains_ids",
        "contained_items",
        "footnote_ids",
        "footnote_of",
        "layout_source_notes_projected",
        "layout_visual_relationships_projected",
        "relationship_basis",
        "relationship_id",
        "relationship_type",
        "source_note_ids",
        "source_note_of",
    }
)
_PICTURE_DESCRIPTION_REPO_ID = "HuggingFaceTB/SmolVLM-256M-Instruct"
_DOCLING_CONVERSION_LOCK = threading.Lock()
_TABLE_SPAN_FIDELITY_ACTIVE_DEADLINE_KEY = (
    "_p04_active_document_deadline"
)
_TABLE_SPAN_FIDELITY_SUSPENDED_AT_KEY = "_p04_suspended_at"
_SOURCE_CONTRADICTED_PRIMARY_OCR_REASON = (
    "source_contradicted_primary_ocr"
)
@dataclass(slots=True)
class SharedAnalysisContext:
    """Format-neutral evidence passed through the common analysis stages."""

    pages: list[dict[str, Any]]
    native_texts: list[str]
    raw_docling: Mapping[str, Any]
    image_regions: dict[int, list[ImageRegion]]
    vector_tables: Mapping[int, Sequence[RawTable]]
    table_repair_words: Mapping[int, Sequence[Mapping[str, Any]]]
    settings: Settings
    coordinate_unit: str
    source_document_identity: str
    source_text_evidence: Any | None = None
    table_span_fidelity_document_deadline: float | None = None
    table_span_fidelity_page_deadlines: dict[int, float] | None = None
    table_span_fidelity_state: dict[str, Any] | None = None
    source_text_alignment_summary: dict[str, Any] | None = None
    selected_vector_representations: dict[
        int, list[dict[str, Any]]
    ] | None = None


def _round(value: float) -> float:
    return round(float(value), 3)


def _bbox(
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict[str, Any]:
    normalized_width = _round(max(width, 0.0))
    normalized_height = _round(max(height, 0.0))
    return {
        "x": _round(x),
        "y": _round(y),
        # ``w``/``h`` match the supplied reference JSON; the descriptive
        # aliases make the public schema self-explanatory for new clients.
        "w": normalized_width,
        "h": normalized_height,
        "width": normalized_width,
        "height": normalized_height,
        "unit": "pt",
    }


def _coerce_bbox(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        return _bbox(
            float(value["x"]),
            float(value["y"]),
            float(value.get("width", value.get("w"))),
            float(value.get("height", value.get("h"))),
        )
    except (KeyError, OverflowError, TypeError, ValueError):
        return None


def _bbox_from_prov(
    item: Mapping[str, Any],
    page_heights: Mapping[int, float],
) -> tuple[int, dict[str, Any] | None]:
    provenance = item.get("prov") or []
    if not provenance:
        return 1, None
    prov = provenance[0]
    page_index = 1
    try:
        page_index = int(prov.get("page_no") or 1)
        raw = prov.get("bbox") or {}
        left = float(raw["l"])
        top = float(raw["t"])
        right = float(raw["r"])
        bottom = float(raw["b"])
        if str(raw.get("coord_origin", "BOTTOMLEFT")).upper() == "TOPLEFT":
            y = top
            height = bottom - top
        else:
            y = float(page_heights.get(page_index, 0.0)) - top
            height = top - bottom
        box = _bbox(left, y, right - left, height)
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return page_index, None
    return page_index, box


def _bbox_union(boxes: Iterable[Mapping[str, Any] | None]) -> dict[str, Any] | None:
    valid = [box for box in boxes if box]
    if not valid:
        return None
    left = min(float(box["x"]) for box in valid)
    top = min(float(box["y"]) for box in valid)
    right = max(float(box["x"]) + float(box["width"]) for box in valid)
    bottom = max(float(box["y"]) + float(box["height"]) for box in valid)
    return _bbox(left, top, right - left, bottom - top)


def _intersection_area(
    first: Mapping[str, Any] | None,
    second: Mapping[str, Any] | None,
) -> float:
    if not first or not second:
        return 0.0
    left = max(float(first["x"]), float(second["x"]))
    top = max(float(first["y"]), float(second["y"]))
    right = min(
        float(first["x"]) + float(first["width"]),
        float(second["x"]) + float(second["width"]),
    )
    bottom = min(
        float(first["y"]) + float(first["height"]),
        float(second["y"]) + float(second["height"]),
    )
    return max(right - left, 0.0) * max(bottom - top, 0.0)


def _area(box: Mapping[str, Any] | None) -> float:
    if not box:
        return 0.0
    return float(box["width"]) * float(box["height"])


def _overlap_of_smaller(
    first: Mapping[str, Any] | None,
    second: Mapping[str, Any] | None,
) -> float:
    smaller = min(_area(first), _area(second))
    return _intersection_area(first, second) / smaller if smaller else 0.0


def _center_inside(
    inner: Mapping[str, Any] | None,
    outer: Mapping[str, Any] | None,
) -> bool:
    if not inner or not outer:
        return False
    center_x = float(inner["x"]) + float(inner["width"]) / 2
    center_y = float(inner["y"]) + float(inner["height"]) / 2
    return float(outer["x"]) <= center_x <= float(outer["x"]) + float(
        outer["width"]
    ) and float(outer["y"]) <= center_y <= float(outer["y"]) + float(outer["height"])


def _normalized_search_text(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", value.casefold()).strip()


def _is_native(value: str, native_page_text: str) -> bool:
    needle = _normalized_search_text(value)
    haystack = _normalized_search_text(native_page_text)
    if not needle:
        return False
    if needle in haystack:
        return True
    # OCR/layout engines occasionally change one punctuation-adjacent space.
    compact_needle = needle.replace(" ", "")
    return len(compact_needle) >= 8 and compact_needle in haystack.replace(" ", "")


def _native_pdf_pages(
    pdf_bytes: bytes,
    *,
    max_pages: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        document = pdfium.PdfDocument(pdf_bytes)
    except Exception as exc:
        raise InvalidPdfError(
            details={"reason": "pdf_open_failed", "engine": "pdfium"}
        ) from exc

    try:
        page_count = len(document)
        if page_count > max_pages:
            raise PageLimitExceededError(
                details={"page_count": page_count, "max_pages": max_pages}
            )
        pages: list[dict[str, Any]] = []
        texts: list[str] = []
        for page_offset in range(page_count):
            page = document[page_offset]
            try:
                width, height = (float(value) for value in page.get_size())
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_bounded() or ""
                finally:
                    text_page.close()
                pdf_label = (document.get_page_label(page_offset) or "").strip()
            except Exception as exc:
                raise InvalidPdfError(
                    details={
                        "reason": "pdf_page_read_failed",
                        "page_index": page_offset + 1,
                    }
                ) from exc
            finally:
                page.close()

            printed_match = _PAGE_NUMBER_RE.search(text)
            page_label = (
                pdf_label
                or (printed_match.group(1) if printed_match else "")
                or str(page_offset + 1)
            )
            page_number: int | str = (
                int(page_label) if page_label.isdigit() else page_label
            )
            pages.append(
                {
                    "page_index": page_offset + 1,
                    "page_number": page_number,
                    "page_label": page_label,
                    "page_width": width,
                    "page_height": height,
                    "unit": "pt",
                    "success": True,
                    "items": [],
                    "warnings": [],
                }
            )
            texts.append(text)
        return pages, texts
    finally:
        document.close()


def _build_pdf_converter(
    languages: tuple[str, ...],
    tesseract_cmd: str,
    tesseract_data_path: str | None,
    artifacts_path: str | None,
    timeout_seconds: float,
    classify_pictures: bool = False,
    describe_pictures: bool = False,
    picture_description_prompt: str | None = None,
) -> tuple[Any, threading.Lock]:
    """Build one heavyweight local Docling converter per engine configuration."""

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        raise ExtractionEngineUnavailableError(
            details={"component": "docling", "reason": "not_installed"}
        ) from exc

    options = _docling_pipeline_options(
        languages,
        tesseract_cmd,
        tesseract_data_path,
        artifacts_path,
        timeout_seconds,
        classify_pictures=classify_pictures,
        describe_pictures=describe_pictures,
        picture_description_prompt=picture_description_prompt,
    )
    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
        },
    )
    return converter, _DOCLING_CONVERSION_LOCK


@lru_cache(maxsize=4)
def _converter_and_lock(
    languages: tuple[str, ...],
    tesseract_cmd: str,
    tesseract_data_path: str | None,
    artifacts_path: str | None,
    timeout_seconds: float,
    classify_pictures: bool = False,
    describe_pictures: bool = False,
    picture_description_prompt: str | None = None,
) -> tuple[Any, threading.Lock]:
    """Retain the predecessor's lazy, cached PDF converter path."""

    return _build_pdf_converter(
        languages,
        tesseract_cmd,
        tesseract_data_path,
        artifacts_path,
        timeout_seconds,
        classify_pictures,
        describe_pictures,
        picture_description_prompt,
    )


def _docling_pipeline_options(
    languages: tuple[str, ...],
    tesseract_cmd: str,
    tesseract_data_path: str | None,
    artifacts_path: str | None,
    timeout_seconds: float,
    *,
    classify_pictures: bool = False,
    describe_pictures: bool = False,
    picture_description_prompt: str | None = None,
) -> Any:
    try:
        from docling.datamodel.pipeline_options import (
            HeadingHierarchyOptions,
            PdfPipelineOptions,
            TableFormerMode,
            TesseractCliOcrOptions,
        )
    except ImportError as exc:
        raise ExtractionEngineUnavailableError(
            details={"component": "docling", "reason": "not_installed"}
        ) from exc

    options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        document_timeout=timeout_seconds,
        enable_remote_services=False,
        artifacts_path=Path(artifacts_path) if artifacts_path else None,
        ocr_options=TesseractCliOcrOptions(
            lang=list(languages),
            tesseract_cmd=tesseract_cmd,
            path=tesseract_data_path,
            force_full_page_ocr=False,
            bitmap_area_threshold=0.05,
            psm=3,
        ),
        heading_hierarchy_options=HeadingHierarchyOptions(
            enabled=True,
            use_bookmarks=True,
            use_numbering=True,
            use_style=True,
        ),
    )
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.do_picture_classification = classify_pictures
    if classify_pictures:
        # Keep the service deployable in slim CPU containers that intentionally
        # omit a C++ toolchain. Eager model execution is deterministic and
        # avoids torch.compile/Inductor failures during requests.
        options.picture_classification_options.engine_options.compile_model = False
    options.do_picture_description = describe_pictures
    if describe_pictures:
        from docling.datamodel.pipeline_options import (
            PictureDescriptionVlmEngineOptions,
        )

        description_options = PictureDescriptionVlmEngineOptions.from_preset("smolvlm")
        if picture_description_prompt:
            description_options = description_options.model_copy(
                update={"prompt": picture_description_prompt}
            )
        # A batch of one bounds peak memory for an interactive single-document
        # API. Multi-picture pages are still processed in reading order.
        options.picture_description_options = description_options.model_copy(
            update={"batch_size": 1}
        )
    return options


def _picture_classifier_model_available(
    artifacts_path: str | None,
) -> bool:
    """Return whether configured local artifacts include the optional classifier.

    Without an explicit artifacts path, Docling retains its established
    cache/download behavior. With one configured, Docling refuses to fall back
    to its cache and raises when the classifier directory is absent, so skip
    only that optional stage while retaining layout, OCR, and table parsing.
    """

    if not artifacts_path:
        return True

    try:
        from docling.datamodel.picture_classification_options import (
            DocumentPictureClassifierOptions,
        )
    except ImportError:
        return False

    options = DocumentPictureClassifierOptions.from_preset(
        "document_figure_classifier_v2"
    )
    return (Path(artifacts_path) / options.repo_cache_folder).exists()


def _picture_description_model_available(
    artifacts_path: str | None,
) -> bool:
    """Check for a complete local captioning snapshot without downloading it."""

    if artifacts_path:
        model_path = Path(artifacts_path) / _PICTURE_DESCRIPTION_REPO_ID.replace(
            "/", "--"
        )
        return (model_path / "config.json").is_file() and any(
            model_path.glob("*.safetensors")
        )

    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            _PICTURE_DESCRIPTION_REPO_ID,
            local_files_only=True,
        )
    except Exception:
        return False
    return True


def _build_image_converter(
    languages: tuple[str, ...],
    tesseract_cmd: str,
    tesseract_data_path: str | None,
    artifacts_path: str | None,
    timeout_seconds: float,
    classify_pictures: bool,
    describe_pictures: bool = False,
    picture_description_prompt: str | None = None,
) -> tuple[Any, threading.Lock]:
    """Build a native-image Docling converter without changing the PDF cache."""

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import (
            DocumentConverter,
            ImageFormatOption,
        )
    except ImportError as exc:
        raise ExtractionEngineUnavailableError(
            details={"component": "docling", "reason": "not_installed"}
        ) from exc

    options = _docling_pipeline_options(
        languages,
        tesseract_cmd,
        tesseract_data_path,
        artifacts_path,
        timeout_seconds,
        classify_pictures=classify_pictures,
        describe_pictures=describe_pictures,
        picture_description_prompt=picture_description_prompt,
    )
    converter = DocumentConverter(
        allowed_formats=[InputFormat.IMAGE],
        format_options={
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
        },
    )
    return converter, _DOCLING_CONVERSION_LOCK


@lru_cache(maxsize=4)
def _image_converter_and_lock(
    languages: tuple[str, ...],
    tesseract_cmd: str,
    tesseract_data_path: str | None,
    artifacts_path: str | None,
    timeout_seconds: float,
    classify_pictures: bool,
    describe_pictures: bool = False,
    picture_description_prompt: str | None = None,
) -> tuple[Any, threading.Lock]:
    """Retain the predecessor's lazy, cached image converter path."""

    return _build_image_converter(
        languages,
        tesseract_cmd,
        tesseract_data_path,
        artifacts_path,
        timeout_seconds,
        classify_pictures,
        describe_pictures,
        picture_description_prompt,
    )


def _convert_with_docling(
    document_bytes: bytes,
    filename: str,
    settings: Settings,
    *,
    input_kind: InputKind = InputKind.PDF,
    parser_worker: Any | None = None,
) -> tuple[dict[str, Any], list[str]]:
    try:
        from docling.datamodel.base_models import (
            ConversionStatus,
            DocumentStream,
        )
    except ImportError as exc:
        raise ExtractionEngineUnavailableError(
            details={"component": "docling", "reason": "not_installed"}
        ) from exc

    if settings.parser_latency_prewarm_enabled:
        if parser_worker is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        (
            picture_classifier_enabled,
            picture_description_enabled,
        ) = parser_worker.optional_model_decisions()
        converter, converter_lock = parser_worker.converter_for(input_kind)
    else:
        picture_classifier_enabled = _picture_classifier_model_available(
            settings.docling_artifacts_path
        )
        picture_description_enabled = (
            settings.image_captioning_enabled
            and _picture_description_model_available(settings.docling_artifacts_path)
        )
        converter_args = (
            tuple(settings.ocr_languages),
            settings.tesseract_cmd,
            settings.tesseract_data_path,
            settings.docling_artifacts_path,
            settings.document_timeout_seconds,
            picture_classifier_enabled,
        )
        if input_kind is InputKind.PDF:
            if picture_description_enabled:
                converter, converter_lock = _converter_and_lock(
                    *converter_args,
                    describe_pictures=True,
                    picture_description_prompt=settings.image_captioning_prompt,
                )
            else:
                converter, converter_lock = _converter_and_lock(*converter_args)
        else:
            if picture_description_enabled:
                converter, converter_lock = _image_converter_and_lock(
                    *converter_args,
                    describe_pictures=True,
                    picture_description_prompt=settings.image_captioning_prompt,
                )
            else:
                converter, converter_lock = _image_converter_and_lock(*converter_args)
    try:
        conversion_guard = converter_lock
        if (
            parser_worker is not None
            and getattr(
                parser_worker,
                "conversion_lock_held_by_current_thread",
                lambda: False,
            )()
        ):
            conversion_guard = nullcontext()
        with conversion_guard:
            result = converter.convert(
                DocumentStream(
                    name=filename or "document.pdf",
                    stream=io.BytesIO(document_bytes),
                ),
                raises_on_error=False,
                max_num_pages=settings.max_pages,
                # The upload limit was already enforced on the original
                # bytes. Orientation normalization can make an internal
                # lossless raster representation larger than its upload.
                max_file_size=max(
                    settings.max_upload_bytes,
                    len(document_bytes),
                ),
            )
    except TimeoutError:
        raise
    except Exception as exc:
        raise DocumentProcessingError(
            details={"component": "docling", "reason": type(exc).__name__}
        ) from exc

    if result.status not in {
        ConversionStatus.SUCCESS,
        ConversionStatus.PARTIAL_SUCCESS,
    }:
        raise DocumentProcessingError(
            details={
                "component": "docling",
                "status": str(result.status.value),
                "errors": [str(error) for error in result.errors[:10]],
            }
        )

    warnings = []
    if settings.docling_artifacts_path and not picture_classifier_enabled:
        warnings.append(
            "Picture classification was skipped because its model is "
            "unavailable in the configured local Docling artifacts."
        )
    if settings.image_captioning_enabled and not picture_description_enabled:
        warnings.append(
            "Semantic picture captioning was requested but skipped because "
            "the local SmolVLM model snapshot is unavailable or incomplete."
        )
    if result.status is ConversionStatus.PARTIAL_SUCCESS:
        warnings.append("Docling completed with partial success.")
    warnings.extend(str(error) for error in result.errors)
    return (
        result.document.export_to_dict(
            mode="json",
            by_alias=True,
            exclude_none=True,
            coord_precision=3,
            confid_precision=4,
        ),
        warnings,
    )


def _table_repair_candidate_page_index(
    table: Any,
    *,
    maximum_slot_count: int,
) -> int | None:
    """Return the sole page for a bounded table-repair grid envelope."""

    if (
        type(maximum_slot_count) is not int
        or not 1 <= maximum_slot_count <= 65_536
    ):
        raise ValueError("table repair slot envelope differs")
    if type(table) is not dict:
        return None
    provenance = table.get("prov")
    if type(provenance) is not list or len(provenance) != 1:
        return None
    provenance_item = provenance[0]
    if type(provenance_item) is not dict:
        return None
    page_index = provenance_item.get("page_no")
    if type(page_index) is not int or not 1 <= page_index <= 100:
        return None

    data = table.get("data")
    if type(data) is not dict:
        return None
    row_count = data.get("num_rows")
    column_count = data.get("num_cols")
    if (
        type(row_count) is not int
        or not 2 <= row_count <= 4_096
        or type(column_count) is not int
        or not 1 <= column_count <= 16
        or row_count > 65_536 // column_count
    ):
        return None
    cells = data.get("table_cells")
    expected_cell_count = row_count * column_count
    if (
        expected_cell_count > maximum_slot_count
        or type(cells) is not list
        or not cells
        or len(cells) > expected_cell_count
    ):
        return None

    # Page discovery is deliberately constant-time per table. Exact cell,
    # span, header, reference, text, and geometry validation remains in the
    # deadline-bound table-local transaction. Walking every cell here would
    # permit 4,096 x 65,536 pre-deadline inspections and let an earlier large
    # candidate starve a later eligible physical page.
    return page_index


def _table_repair_recovery_page_index(table: Any) -> int | None:
    """Return the page for optional source-word recovery up to 512 slots."""

    return _table_repair_candidate_page_index(
        table,
        maximum_slot_count=512,
    )


def _table_repair_mixed_row_page_indexes(
    tables: Sequence[Any],
) -> set[int]:
    """Find predecessor mixed-row pages with at most 4,096 cell visits."""

    page_indexes: set[int] = set()
    remaining_cell_visits = 4_096
    for table in tables:
        page_index = _table_repair_candidate_page_index(
            table,
            maximum_slot_count=65_536,
        )
        if page_index is None:
            continue
        cells = table["data"]["table_cells"]
        if len(cells) > remaining_cell_visits:
            # Preserve the P03 repair possibility without an unbounded
            # pre-extraction walk. The page receives bounded predecessor word
            # geometry, but not the optional P04 typography evidence.
            page_indexes.add(page_index)
            continue
        remaining_cell_visits -= len(cells)
        row_header_states: dict[int, int] = {}
        malformed = False
        for cell in cells:
            if type(cell) is not dict:
                malformed = True
                break
            row = cell.get("start_row_offset_idx")
            if type(row) is not int:
                malformed = True
                break
            state = row_header_states.get(row, 0)
            state |= 1 if bool(cell.get("column_header")) else 2
            row_header_states[row] = state
        if malformed or 3 in row_header_states.values():
            page_indexes.add(page_index)
    return page_indexes


def _table_repair_recovery_page_indexes(
    tables: Sequence[Any],
) -> set[int]:
    return {
        page_index
        for table in tables
        if (page_index := _table_repair_recovery_page_index(table)) is not None
    }


def _table_repair_page_indexes(
    raw: Mapping[str, Any],
    *,
    table_span_fidelity_enabled: bool = False,
) -> set[int]:
    if not table_span_fidelity_enabled:
        page_indexes: set[int] = set()
        for table in raw.get("tables") or []:
            if not isinstance(table, Mapping):
                continue
            cells_by_row: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
            for cell in (table.get("data") or {}).get("table_cells") or []:
                if isinstance(cell, Mapping):
                    cells_by_row[int(cell.get("start_row_offset_idx") or 0)].append(
                        cell
                    )
            has_mixed_row = any(
                any(bool(cell.get("column_header")) for cell in row_cells)
                and any(not bool(cell.get("column_header")) for cell in row_cells)
                for row_cells in cells_by_row.values()
            )
            if not has_mixed_row:
                continue
            provenance = table.get("prov") or []
            if not provenance:
                continue
            try:
                page_indexes.add(int(provenance[0].get("page_no") or 1))
            except (AttributeError, TypeError, ValueError):
                continue
        return page_indexes

    tables = raw.get("tables")
    if tables is None:
        return set()
    if type(tables) is not list or len(tables) > 4_096:
        raise ValueError("table repair table limit exceeded")

    return _table_repair_recovery_page_indexes(
        tables
    ) | _table_repair_mixed_row_page_indexes(tables)


def _complete_table_span_fidelity_page_segment(
    page_deadlines: dict[int, float],
    active_page_index: int | None,
    segment_started: float,
    segment_finished: float,
    document_deadline: float,
) -> None:
    """Charge one page segment without charging other physical pages."""

    if (
        type(page_deadlines) is not dict
        or len(page_deadlines) > 100
        or (
            active_page_index is not None
            and (
                type(active_page_index) is not int
                or not 1 <= active_page_index <= 100
            )
        )
        or isinstance(segment_started, bool)
        or not isinstance(segment_started, (int, float))
        or not math.isfinite(float(segment_started))
        or isinstance(segment_finished, bool)
        or not isinstance(segment_finished, (int, float))
        or not math.isfinite(float(segment_finished))
        or float(segment_finished) < float(segment_started)
        or isinstance(document_deadline, bool)
        or not isinstance(document_deadline, (int, float))
        or not math.isfinite(float(document_deadline))
        or (
            active_page_index is not None
            and active_page_index not in page_deadlines
        )
    ):
        raise ValueError("table span-fidelity page segment differs")
    if float(segment_finished) > float(document_deadline):
        raise TimeoutError("table span-fidelity document deadline exceeded")
    elapsed = float(segment_finished) - float(segment_started)
    validated_deadlines: dict[int, float] = {}
    for page_index, page_deadline in tuple(page_deadlines.items()):
        if (
            type(page_index) is not int
            or not 1 <= page_index <= 100
            or isinstance(page_deadline, bool)
            or not isinstance(page_deadline, (int, float))
            or not math.isfinite(float(page_deadline))
            or float(page_deadline) > float(document_deadline)
        ):
            raise ValueError("table span-fidelity page segment differs")
        validated_deadlines[page_index] = float(page_deadline)
    for page_index, page_deadline in validated_deadlines.items():
        if page_index != active_page_index:
            page_deadlines[page_index] = min(
                float(document_deadline),
                page_deadline + elapsed,
            )
    if (
        active_page_index is not None
        and float(segment_finished) > validated_deadlines[active_page_index]
    ):
        raise TimeoutError("table span-fidelity page deadline exceeded")


def _extract_table_repair_page_words(
    page: Any,
    page_index: int,
    page_count: int,
    deadline: float,
    page_deadline: float,
    total_word_count: int,
    source_text_bytes: int,
    *,
    require_typography: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    if type(require_typography) is not bool:
        raise ValueError("table repair typography policy differs")
    if not 1 <= page_index <= page_count:
        raise ValueError("table repair page index is unavailable")
    extraction_options: dict[str, Any] = {
        "x_tolerance": 2,
        "y_tolerance": 2,
        "keep_blank_chars": False,
        "use_text_flow": False,
    }
    if require_typography:
        extraction_options["extra_attrs"] = ["fontname"]
    words = page.extract_words(
        **extraction_options,
    )
    current_time = time.perf_counter()
    if current_time > deadline:
        raise TimeoutError(
            "table repair word extraction document deadline exceeded"
        )
    if current_time > page_deadline:
        raise TimeoutError(
            "table repair word extraction page deadline exceeded"
        )
    if type(words) is not list:
        raise ValueError("table repair word records are not sized")
    page_word_count = len(words)
    if page_word_count > 16_384:
        raise ValueError("table repair word page limit exceeded")
    if total_word_count + page_word_count > 65_536:
        raise ValueError("table repair word document limit exceeded")

    retained_words: list[dict[str, Any]] = []
    page_text_bytes = 0
    processed_word_count = 0
    for word in words:
        current_time = time.perf_counter()
        if current_time > deadline:
            raise TimeoutError(
                "table repair word extraction document deadline exceeded"
            )
        if current_time > page_deadline:
            raise TimeoutError(
                "table repair word extraction page deadline exceeded"
            )
        processed_word_count += 1
        if processed_word_count > page_word_count:
            raise ValueError("table repair word page limit exceeded")
        if type(word) is not dict:
            raise ValueError("table repair word record is malformed")
        text = word.get("text")
        if not isinstance(text, str):
            raise ValueError("table repair word text is malformed")
        if len(text) > 16_384:
            raise ValueError("table repair word text limit exceeded")
        encoded_text = text.encode("utf-8")
        if len(encoded_text) > 16_384:
            raise ValueError("table repair word text limit exceeded")
        page_text_bytes += len(encoded_text)
        if source_text_bytes + page_text_bytes > 8_388_608:
            raise ValueError("table repair text document limit exceeded")
        if any(
            ord(character) < 32 or ord(character) == 127
            for character in text
        ):
            raise ValueError("table repair word text is malformed")
        if not text.strip():
            continue
        fontname = word.get("fontname")
        if require_typography:
            if not isinstance(fontname, str) or not fontname:
                raise ValueError("table repair word typography is malformed")
            try:
                encoded_fontname = fontname.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError(
                    "table repair word typography is malformed"
                ) from None
            if len(encoded_fontname) > 256:
                raise ValueError("table repair word typography is malformed")
            if any(
                ord(character) < 32 or ord(character) == 127
                for character in fontname
            ):
                raise ValueError("table repair word typography is malformed")
        coordinates = (
            word.get("x0"),
            word.get("x1"),
            word.get("top"),
            word.get("bottom"),
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in coordinates
        ):
            raise ValueError("table repair word geometry is malformed")
        x0, x1, top, bottom = (float(value) for value in coordinates)
        if x1 <= x0 or bottom <= top:
            raise ValueError("table repair word geometry is malformed")
        retained_word = {
            "text": text,
            "x0": x0,
            "x1": x1,
            "top": top,
            "bottom": bottom,
        }
        if require_typography:
            retained_word["font_name"] = fontname
            retained_word["bold"] = "bold" in fontname.casefold()
        retained_words.append(retained_word)
    if processed_word_count != page_word_count:
        raise ValueError("table repair word page limit differs")
    return retained_words, page_word_count, page_text_bytes


def _extract_table_repair_words(
    pdf_bytes: bytes,
    raw: Mapping[str, Any],
    *,
    table_span_fidelity_enabled: bool = False,
    table_span_fidelity_document_deadline: float | None = None,
    table_span_fidelity_page_deadlines: dict[int, float] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """Extract word geometry only for page-local recoverable table grids."""

    page_indexes = _table_repair_page_indexes(
        raw,
        table_span_fidelity_enabled=table_span_fidelity_enabled,
    )
    if not page_indexes:
        return {}

    import pdfplumber

    if not table_span_fidelity_enabled:
        return _extract_predecessor_table_repair_words(
            pdf_bytes,
            page_indexes,
        )

    recovery_page_indexes = _table_repair_recovery_page_indexes(
        raw["tables"]
    )

    started = time.perf_counter()
    deadline = (
        started + 5.0
        if table_span_fidelity_document_deadline is None
        else table_span_fidelity_document_deadline
    )
    if (
        isinstance(deadline, bool)
        or not isinstance(deadline, (int, float))
        or not math.isfinite(float(deadline))
        or float(deadline) > started + 5.0
        or float(deadline) <= started
    ):
        raise TimeoutError("table repair word extraction deadline exceeded")
    deadline = float(deadline)
    page_deadlines = (
        {}
        if table_span_fidelity_page_deadlines is None
        else table_span_fidelity_page_deadlines
    )
    if type(page_deadlines) is not dict or len(page_deadlines) > 100:
        raise ValueError("table repair page deadline map differs")
    total_word_count = 0
    source_text_bytes = 0
    words_by_page: dict[int, list[dict[str, Any]]] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        for page_index in sorted(page_indexes):
            current_time = time.perf_counter()
            if current_time > deadline:
                raise TimeoutError("table repair word extraction deadline exceeded")
            page_deadline = page_deadlines.get(page_index)
            if page_deadline is None:
                page_deadline = min(deadline, current_time + 0.5)
                page_deadlines[page_index] = page_deadline
            elif (
                isinstance(page_deadline, bool)
                or not isinstance(page_deadline, (int, float))
                or not math.isfinite(float(page_deadline))
                or float(page_deadline) > deadline
                or float(page_deadline) <= current_time
            ):
                raise TimeoutError(
                    "table repair word extraction page deadline exceeded"
                )
            page_deadline = float(page_deadline)
            segment_started = current_time
            try:
                retained_words, page_word_count, page_text_bytes = (
                    _extract_table_repair_page_words(
                        document.pages[page_index - 1]
                        if 1 <= page_index <= len(document.pages)
                        else None,
                        page_index,
                        len(document.pages),
                        deadline,
                        page_deadline,
                        total_word_count,
                        source_text_bytes,
                        require_typography=(
                            page_index in recovery_page_indexes
                        ),
                    )
                )
                total_word_count += page_word_count
                source_text_bytes += page_text_bytes
                words_by_page[page_index] = retained_words
            except TimeoutError:
                raise
            except Exception:
                _complete_table_span_fidelity_page_segment(
                    page_deadlines,
                    page_index,
                    segment_started,
                    time.perf_counter(),
                    deadline,
                )
                raise
            else:
                _complete_table_span_fidelity_page_segment(
                    page_deadlines,
                    page_index,
                    segment_started,
                    time.perf_counter(),
                    deadline,
                )
    if time.perf_counter() > deadline:
        raise TimeoutError("table repair word extraction deadline exceeded")
    return words_by_page


def _extract_predecessor_table_repair_words(
    pdf_bytes: bytes,
    page_indexes: set[int],
) -> dict[int, list[dict[str, Any]]]:
    """Run the exact P03 mixed-row extraction for selected physical pages."""

    if not page_indexes:
        return {}
    import pdfplumber

    words_by_page: dict[int, list[dict[str, Any]]] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        for page_index in sorted(page_indexes):
            if not 1 <= page_index <= len(document.pages):
                continue
            words = document.pages[page_index - 1].extract_words(
                x_tolerance=2,
                y_tolerance=2,
                keep_blank_chars=False,
                use_text_flow=False,
            )
            words_by_page[page_index] = [
                {
                    "text": str(word.get("text") or ""),
                    "x0": float(word["x0"]),
                    "x1": float(word["x1"]),
                    "top": float(word["top"]),
                    "bottom": float(word["bottom"]),
                }
                for word in words
                if str(word.get("text") or "").strip()
            ]
    return words_by_page


def _extract_partitioned_table_repair_words(
    pdf_bytes: bytes,
    raw: Mapping[str, Any],
    document_deadline: float,
    page_deadlines: dict[int, float],
    state: dict[str, Any],
) -> tuple[dict[int, list[dict[str, Any]]], float, str | None]:
    """Extract legacy and optional P04 word evidence on separate clocks.

    The exact P03 mixed-row path is suspended from the P04 candidate budget.
    Only recovery-eligible pages run through the typography/resource path. Any
    optional failure disables P04 document-wide and retries the unchanged
    predecessor extractor; a successful retry is intentionally warning-free.
    """

    _suspend_table_span_fidelity_budget(state)

    def predecessor_fallback(
        failure: Exception,
    ) -> tuple[dict[int, list[dict[str, Any]]], float, str | None]:
        state["span_fidelity_disabled"] = True
        state["span_fidelity_failure_reason"] = (
            "table_word_geometry_unavailable"
        )
        if isinstance(failure, TimeoutError):
            state["timed_out"] = True
        try:
            predecessor_words = _extract_table_repair_words(
                pdf_bytes,
                raw,
                table_span_fidelity_enabled=False,
            )
        except Exception as predecessor_failure:
            return {}, document_deadline, type(predecessor_failure).__name__
        return predecessor_words, document_deadline, None

    try:
        legacy_pages = _table_repair_page_indexes(
            raw,
            table_span_fidelity_enabled=False,
        )
        tables = raw.get("tables")
        if tables is None:
            recovery_candidates: list[Any] = []
        elif type(tables) is not list or len(tables) > 4_096:
            raise ValueError("table repair table limit exceeded")
        else:
            recovery_candidates = [
                table
                for table in tables
                if _table_repair_recovery_page_index(table) is not None
            ]
        recovery_pages = _table_repair_recovery_page_indexes(
            recovery_candidates
        )
        predecessor_words = _extract_predecessor_table_repair_words(
            pdf_bytes,
            legacy_pages - recovery_pages,
        )
    except Exception as failure:
        return predecessor_fallback(failure)

    if not recovery_candidates:
        return predecessor_words, document_deadline, None

    try:
        document_deadline = _resume_table_span_fidelity_budget(
            document_deadline,
            page_deadlines,
            state,
        )
        recovery_words = _extract_table_repair_words(
            pdf_bytes,
            {"tables": recovery_candidates},
            table_span_fidelity_enabled=True,
            table_span_fidelity_document_deadline=document_deadline,
            table_span_fidelity_page_deadlines=page_deadlines,
        )
    except Exception as failure:
        _suspend_table_span_fidelity_budget(state)
        return predecessor_fallback(failure)
    _suspend_table_span_fidelity_budget(state)
    predecessor_words.update(recovery_words)
    return predecessor_words, document_deadline, None


def _resume_table_span_fidelity_budget(
    document_deadline: float,
    page_deadlines: dict[int, float],
    state: dict[str, Any],
) -> float:
    """Resume one cumulative P04 budget after unrelated parser work."""

    now = time.perf_counter()
    if (
        isinstance(document_deadline, bool)
        or not isinstance(document_deadline, (int, float))
        or not math.isfinite(float(document_deadline))
        or type(page_deadlines) is not dict
        or len(page_deadlines) > 100
        or type(state) is not dict
    ):
        raise ValueError("table span-fidelity budget state differs")
    current_deadline = state.get(
        _TABLE_SPAN_FIDELITY_ACTIVE_DEADLINE_KEY,
        float(document_deadline),
    )
    if (
        isinstance(current_deadline, bool)
        or not isinstance(current_deadline, (int, float))
        or not math.isfinite(float(current_deadline))
    ):
        raise ValueError("table span-fidelity budget state differs")
    current_deadline = float(current_deadline)
    suspended_at = state.pop(
        _TABLE_SPAN_FIDELITY_SUSPENDED_AT_KEY,
        None,
    )
    if suspended_at is not None:
        if (
            isinstance(suspended_at, bool)
            or not isinstance(suspended_at, (int, float))
            or not math.isfinite(float(suspended_at))
            or float(suspended_at) > now
        ):
            raise ValueError("table span-fidelity budget state differs")
        excluded_seconds = now - float(suspended_at)
        current_deadline += excluded_seconds
        for page_index, page_deadline in tuple(page_deadlines.items()):
            if (
                type(page_index) is not int
                or page_index < 1
                or isinstance(page_deadline, bool)
                or not isinstance(page_deadline, (int, float))
                or not math.isfinite(float(page_deadline))
            ):
                raise ValueError("table span-fidelity budget state differs")
            page_deadlines[page_index] = (
                float(page_deadline) + excluded_seconds
            )
    state[_TABLE_SPAN_FIDELITY_ACTIVE_DEADLINE_KEY] = current_deadline
    return current_deadline


def _suspend_table_span_fidelity_budget(state: dict[str, Any]) -> None:
    if type(state) is not dict:
        raise ValueError("table span-fidelity budget state differs")
    if state.get("timed_out") is not True:
        state[_TABLE_SPAN_FIDELITY_SUSPENDED_AT_KEY] = time.perf_counter()


def _run_table_custody_document_segment(
    document_deadline: float,
    page_deadlines: dict[int, float],
    state: dict[str, Any],
    operation: Any,
) -> Any:
    """Charge custody only to the caller-owned cumulative document clock."""

    from app.services.opaque_group_custody import (
        OpaqueGroupCustodyTimeoutError,
    )

    if state.get("timed_out") is True or not callable(operation):
        raise OpaqueGroupCustodyTimeoutError(
            "table custody document deadline exceeded"
        )
    active_deadline = _resume_table_span_fidelity_budget(
        document_deadline,
        page_deadlines,
        state,
    )
    segment_started = time.perf_counter()
    try:
        if segment_started > active_deadline:
            raise OpaqueGroupCustodyTimeoutError(
                "table custody document deadline exceeded"
            )
        result = operation(active_deadline)
        if time.perf_counter() > active_deadline:
            raise OpaqueGroupCustodyTimeoutError(
                "table custody document deadline exceeded"
            )
        return result
    except OpaqueGroupCustodyTimeoutError:
        state["timed_out"] = True
        raise
    finally:
        segment_elapsed = max(time.perf_counter() - segment_started, 0.0)
        # Custody is document-wide; it must not consume any page's 500 ms
        # budget.  The document deadline is deliberately not extended.
        for page_index, page_deadline in tuple(page_deadlines.items()):
            if type(page_index) is int and type(page_deadline) in (int, float):
                page_deadlines[page_index] = min(
                    float(page_deadline) + segment_elapsed,
                    active_deadline,
                )
        _suspend_table_span_fidelity_budget(state)


def _finish_table_span_fidelity_budget(state: dict[str, Any]) -> None:
    if type(state) is not dict:
        return
    state.pop(_TABLE_SPAN_FIDELITY_ACTIVE_DEADLINE_KEY, None)
    state.pop(_TABLE_SPAN_FIDELITY_SUSPENDED_AT_KEY, None)


def _drop_optional_null_shape(value: Any) -> Any:
    """Normalize only explicit optional-null mapping fields for IR comparison."""

    if isinstance(value, Mapping):
        return {
            key: _drop_optional_null_shape(member)
            for key, member in value.items()
            if member is not None
        }
    if isinstance(value, list):
        return [_drop_optional_null_shape(member) for member in value]
    return value


_CANONICAL_BLOCK_IDENTITY_KEYS = (
    "id",
    "page_id",
    "primary_element_id",
    "primary_element_type",
    "scope",
)
_CANONICAL_BLOCK_MUTABLE_KEYS = frozenset(
    {
        "markdown",
        "text",
        "contributing_element_ids",
        "relationship_ids",
        "excluded_contributions",
    }
)
_CANONICAL_BLOCK_REQUIRED_KEYS = frozenset(
    (*_CANONICAL_BLOCK_IDENTITY_KEYS, *_CANONICAL_BLOCK_MUTABLE_KEYS)
)
_P03_TARGET_OVERLAY_ID_FIELDS = (
    "caption_ids",
    "contains_ids",
    "footnote_ids",
    "source_note_ids",
)


def _canonical_exclusion_map(
    values: Any,
) -> dict[tuple[str, str], set[str]]:
    """Return one exact, mergeable exclusion map or reject the block."""

    if type(values) is not list:
        raise ValueError("terminal table canonical exclusions differ")
    output: dict[tuple[str, str], set[str]] = {}
    for value in values:
        if type(value) is not dict or set(value) != {
            "element_id",
            "reason",
            "relationship_ids",
        }:
            raise ValueError("terminal table canonical exclusion differs")
        element_id = value.get("element_id")
        reason = value.get("reason")
        relationship_ids = value.get("relationship_ids")
        if (
            type(element_id) is not str
            or not element_id
            or type(reason) is not str
            or not reason
            or type(relationship_ids) is not list
            or any(type(member) is not str or not member for member in relationship_ids)
            or len(relationship_ids) != len(set(relationship_ids))
        ):
            raise ValueError("terminal table canonical exclusion differs")
        key = (element_id, reason)
        if key in output:
            raise ValueError("terminal table canonical exclusion repeats")
        output[key] = set(relationship_ids)
    return output


def _canonical_exclusions_from_map(
    values: Mapping[tuple[str, str], set[str]],
) -> list[dict[str, Any]]:
    return [
        {
            "element_id": element_id,
            "reason": reason,
            "relationship_ids": sorted(relationship_ids),
        }
        for (element_id, reason), relationship_ids in sorted(values.items())
    ]


def _context_free_visual_placeholder_transition(
    baseline_block: Mapping[str, Any],
    predecessor_block: Mapping[str, Any],
    candidate_block: Mapping[str, Any],
    public_item: Mapping[str, Any],
    *,
    owner_primary_id: str,
    owner_public_id: str,
    public_primary_by_id: Mapping[str, str],
) -> tuple[int, str]:
    """Validate one closed included-placeholder/omitted-visual transition."""

    omitted_keys = _CANONICAL_BLOCK_REQUIRED_KEYS | {"omission_reason"}
    if not (
        set(baseline_block) == _CANONICAL_BLOCK_REQUIRED_KEYS
        and set(predecessor_block) == omitted_keys
        and set(candidate_block) == omitted_keys
        and dict(candidate_block) == dict(predecessor_block)
        and all(
            baseline_block.get(key) == predecessor_block.get(key)
            for key in _CANONICAL_BLOCK_IDENTITY_KEYS
        )
    ):
        raise ValueError("terminal table visual placeholder shape differs")

    try:
        from app.models import (
            ContentItem,
            _context_free_visual_ledger_mode_payload,
            _context_free_visual_ocr_predecessor_is_closed,
            _context_free_visual_source_sensitive_children,
        )

        item = ContentItem.model_validate(dict(public_item))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "terminal table visual placeholder owner differs"
        ) from exc

    ledger_mode = _context_free_visual_ledger_mode_payload(
        item.model_extra or {}
    )
    source_sensitive_children = (
        _context_free_visual_source_sensitive_children(item)
    )
    expected_omission_reason = (
        "empty_visual"
        if ledger_mode == "empty"
        else "unsupported_primary_ocr"
        if ledger_mode in {"nonempty", "nonempty_deduplicated"}
        else None
    )
    if not (
        _context_free_visual_ocr_predecessor_is_closed(item)
        and bool(source_sensitive_children)
        and expected_omission_reason is not None
        and item.id == owner_public_id
        and public_primary_by_id.get(owner_public_id) == owner_primary_id
        and baseline_block.get("primary_element_id") == owner_primary_id
        and type(baseline_block.get("primary_element_type")) is str
        and baseline_block.get("primary_element_type").casefold()
        == item.type.casefold()
        and baseline_block.get("scope") == "body"
        and baseline_block.get("markdown") == item.md
        and baseline_block.get("text") == item.md
        and baseline_block.get("contributing_element_ids")
        == [owner_primary_id]
        and predecessor_block.get("markdown") == ""
        and predecessor_block.get("text") == ""
        and predecessor_block.get("contributing_element_ids") == []
        and predecessor_block.get("omission_reason")
        == expected_omission_reason
    ):
        raise ValueError(
            "terminal table visual placeholder transition differs"
        )
    return len(source_sensitive_children), ledger_mode


def _singleton_evidence_only_relationship_endpoints(
    exclusions: Mapping[tuple[str, str], set[str]],
    relationship_ids: set[str],
) -> dict[str, str]:
    """Bind each source-alternative edge to one exact excluded endpoint."""

    uses: dict[str, list[tuple[tuple[str, str], set[str]]]] = defaultdict(list)
    for key, members in exclusions.items():
        for relationship_id in members:
            uses[relationship_id].append((key, members))

    endpoints: dict[str, str] = {}
    for relationship_id in relationship_ids:
        matches = uses.get(relationship_id, [])
        if len(matches) != 1:
            raise ValueError(
                "terminal table visual source-alternative exclusion differs"
            )
        (element_id, reason), members = matches[0]
        if (
            reason != "evidence_only_relationship"
            or members != {relationship_id}
            or element_id in endpoints.values()
        ):
            raise ValueError(
                "terminal table visual source-alternative exclusion differs"
            )
        endpoints[relationship_id] = element_id
    return endpoints


def _declared_target_overlay_ids(
    public_item: Mapping[str, Any],
) -> tuple[set[str], set[str]]:
    """Extract only the closed public P03 target-overlay declarations."""

    contributor_ids: set[str] = set()
    for field in _P03_TARGET_OVERLAY_ID_FIELDS:
        raw = public_item.get(field, [])
        if type(raw) is not list or any(
            type(value) is not str or not value for value in raw
        ) or len(raw) != len(set(raw)):
            raise ValueError("terminal table canonical overlay declaration differs")
        contributor_ids.update(raw)

    relationship_ids: set[str] = set()
    relationships = public_item.get("relationships", [])
    if type(relationships) is not list:
        raise ValueError("terminal table canonical overlay relationships differ")
    for relationship in relationships:
        if type(relationship) is not dict:
            raise ValueError("terminal table canonical overlay relationship differs")
        relationship_id = relationship.get("id")
        if type(relationship_id) is not str or not relationship_id:
            raise ValueError("terminal table canonical overlay relationship differs")
        relationship_ids.add(relationship_id)

    for group_name, member_names in (
        ("form_group", ("contributor_element_ids",)),
        (
            "outline_group",
            (
                "member_element_ids",
                "continuation_element_ids",
                "canonical_contributor_element_ids",
            ),
        ),
    ):
        group = public_item.get(group_name)
        if group is None:
            continue
        if type(group) is not dict:
            raise ValueError("terminal table canonical overlay group differs")
        for member_name in member_names:
            raw = group.get(member_name, [])
            if type(raw) is not list or any(
                type(value) is not str or not value for value in raw
            ) or len(raw) != len(set(raw)):
                raise ValueError("terminal table canonical overlay group differs")
            contributor_ids.update(raw)
    return contributor_ids, relationship_ids


def _allowed_target_overlay_relationship_ids(
    owner_id: str,
    contributor_ids: set[str],
    declared_relationship_ids: set[str],
) -> set[str]:
    """Close canonical raw/public relationship identities for declared peers."""

    from app.services.opaque_group_custody import stable_id

    allowed = set(declared_relationship_ids)
    child_source_types = (
        "caption_of",
        "source_note_of",
        "footnote_of",
        "legend_of",
        "axis_of",
        "annotation_of",
    )
    child_source_fields = (
        "children",
        "captions",
        "caption",
        "source_notes",
        "source_note",
        "footnotes",
        "footnote",
        "legends",
        "legend",
        "axes",
        "axis",
        "annotations",
        "comments",
    )
    for contributor_id in contributor_ids:
        for relationship_type in child_source_types:
            for field in child_source_fields:
                allowed.add(
                    stable_id(
                        "rel",
                        relationship_type,
                        contributor_id,
                        owner_id,
                        field,
                    )
                )
        for field in ("children", "references"):
            allowed.add(
                stable_id(
                    "rel",
                    "contains" if field == "children" else "references",
                    owner_id,
                    contributor_id,
                    field,
                )
            )
        allowed.add(
            stable_id(
                "rel",
                "contains",
                owner_id,
                contributor_id,
                "parent",
            )
        )
    return allowed


def _terminal_visual_caption_source_primary_id(
    caption: Mapping[str, Any],
    *,
    owner_public_id: str,
    document_id: str,
    public_primary_by_id: Mapping[str, str],
) -> str:
    """Recover the canonical source identity carried by one public caption.

    P03 intentionally gives a projected visual caption a public-only ID.  Its
    source raw-ref remains recoverable from the bounded, deterministic caption
    proof.  The P04 terminal splice needs that identity only to decide which
    already-validated P03 relationship may survive into the public canonical
    graph; it must never treat every predecessor raw edge as public authority.
    """

    public_id = caption.get("id")
    if type(public_id) is not str or not public_id:
        raise ValueError("terminal table visual caption identity differs")
    if re.fullmatch(r"layout-caption-[0-9a-f]{20}", public_id) is None:
        primary_id = public_primary_by_id.get(public_id)
        if type(primary_id) is not str or not primary_id:
            raise ValueError("terminal table visual caption binding differs")
        return primary_id

    value = caption.get("value")
    bbox = caption.get("bbox")
    if type(value) is not str or type(bbox) is not dict:
        raise ValueError("terminal table visual caption proof differs")
    caption_box: dict[str, Any] = {}
    for field in ("x", "y", "width", "height"):
        number = bbox.get(field)
        if (
            isinstance(number, bool)
            or type(number) not in {int, float}
            or not math.isfinite(float(number))
        ):
            raise ValueError("terminal table visual caption geometry differs")
        caption_box[field] = number
    if caption_box["width"] <= 0 or caption_box["height"] <= 0:
        raise ValueError("terminal table visual caption geometry differs")
    if bbox.get("unit") not in {"pt", "px", "logical"}:
        raise ValueError("terminal table visual caption geometry differs")
    caption_box["unit"] = bbox["unit"]

    from app.models import _MAX_CONTEXT_FREE_RAW_REF_ORDINALS, _canonical_ir_id

    normalized_text = re.sub(r"\s+", " ", value).strip().casefold()
    if not normalized_text:
        raise ValueError("terminal table visual caption proof differs")
    matched_ref: str | None = None
    for ordinal in range(_MAX_CONTEXT_FREE_RAW_REF_ORDINALS):
        raw_ref = f"#/texts/{ordinal}"
        digest = hashlib.sha256(
            json.dumps(
                (
                    "P03-US02",
                    "caption",
                    owner_public_id,
                    [raw_ref],
                    normalized_text,
                    caption_box,
                ),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        if public_id != f"layout-caption-{digest[:20]}":
            continue
        if matched_ref is not None:
            raise ValueError("terminal table visual caption proof repeats")
        matched_ref = raw_ref
    if matched_ref is None:
        raise ValueError("terminal table visual caption proof differs")
    return _canonical_ir_id("el", document_id, "raw_ref", matched_ref)


def _rebind_terminal_non_target_visual_overlay(
    baseline_block: Mapping[str, Any],
    predecessor_block: Mapping[str, Any],
    candidate_block: Mapping[str, Any],
    public_item: Mapping[str, Any],
    *,
    document_id: str,
    public_items_by_id: Mapping[str, Mapping[str, Any]],
    public_primary_by_id: Mapping[str, str],
) -> dict[str, Any]:
    """Rebind a P03 visual overlay without restoring private raw edges.

    The fresh candidate block is reconstructed from the exact public item.
    P03 may add a bounded layout overlay on top of that graph, but its earlier
    canonical block can also contain raw visual-child audit edges that the
    public projection deliberately did not retain.  Only relationships bound
    to public overlay declarations are carried forward.
    """

    if not all(
        type(value) is dict
        for value in (baseline_block, predecessor_block, candidate_block, public_item)
    ):
        raise ValueError("terminal table visual overlay block differs")
    if public_item.get("layout_visual_relationships_projected") is not True:
        raise ValueError("terminal table visual overlay declaration differs")
    if _drop_optional_null_shape(candidate_block) != _drop_optional_null_shape(
        predecessor_block
    ):
        raise ValueError("terminal table visual overlay predecessor differs")

    owner_primary_id = baseline_block.get("primary_element_id")
    owner_public_id = public_item.get("id")
    if (
        type(owner_primary_id) is not str
        or not owner_primary_id
        or type(owner_public_id) is not str
        or not owner_public_id
    ):
        raise ValueError("terminal table visual overlay owner differs")

    expected_keys = set(candidate_block)
    same_disposition = (
        set(predecessor_block) == expected_keys
        and set(baseline_block) == expected_keys
        and all(
            baseline_block.get(key) == candidate_block.get(key)
            for key in (
                *_CANONICAL_BLOCK_IDENTITY_KEYS,
                "omission_reason",
                "suppressed_by_element_id",
            )
        )
    )
    placeholder_transition: tuple[int, str] | None = None
    if not same_disposition:
        placeholder_transition = _context_free_visual_placeholder_transition(
            baseline_block,
            predecessor_block,
            candidate_block,
            public_item,
            owner_primary_id=owner_primary_id,
            owner_public_id=owner_public_id,
            public_primary_by_id=public_primary_by_id,
        )

    contributor_ids, declared_relationship_ids = _declared_target_overlay_ids(
        dict(public_item)
    )
    canonical_contributor_ids: set[str] = set()
    projected_caption_source_ids: set[str] = set()
    caption_ids = public_item.get("caption_ids", [])
    if type(caption_ids) is not list:
        raise ValueError("terminal table visual caption declaration differs")
    caption_id_set = set(caption_ids)
    for contributor_id in contributor_ids:
        linked = public_items_by_id.get(contributor_id)
        if contributor_id in caption_id_set:
            if linked is None:
                raise ValueError("terminal table visual caption binding differs")
            caption_source_id = _terminal_visual_caption_source_primary_id(
                linked,
                owner_public_id=owner_public_id,
                document_id=document_id,
                public_primary_by_id=public_primary_by_id,
            )
            canonical_contributor_ids.add(caption_source_id)
            if re.fullmatch(r"layout-caption-[0-9a-f]{20}", contributor_id):
                projected_caption_source_ids.add(caption_source_id)
        else:
            canonical_contributor_ids.add(
                public_primary_by_id.get(contributor_id, contributor_id)
            )
    allowed_overlay_relationship_ids = _allowed_target_overlay_relationship_ids(
        owner_primary_id,
        canonical_contributor_ids,
        declared_relationship_ids,
    )

    baseline_relationships = baseline_block.get("relationship_ids")
    predecessor_relationships = predecessor_block.get("relationship_ids")
    candidate_relationships = candidate_block.get("relationship_ids")
    if not all(
        type(value) is list
        and value == sorted(value)
        and len(value) == len(set(value))
        and all(type(member) is str and member for member in value)
        for value in (
            baseline_relationships,
            predecessor_relationships,
            candidate_relationships,
        )
    ):
        raise ValueError("terminal table visual overlay relationships differ")
    predecessor_relationship_set = set(predecessor_relationships)
    baseline_relationship_set = set(baseline_relationships)
    if candidate_relationships != predecessor_relationships:
        raise ValueError("terminal table visual overlay predecessor differs")
    baseline_exclusions = _canonical_exclusion_map(
        baseline_block.get("excluded_contributions")
    )
    predecessor_exclusions = _canonical_exclusion_map(
        predecessor_block.get("excluded_contributions")
    )
    predecessor_only_relationship_ids: set[str] = set()
    if placeholder_transition is None:
        if not predecessor_relationship_set.issubset(
            baseline_relationship_set
        ):
            raise ValueError(
                "terminal table visual overlay predecessor differs"
            )
    else:
        source_sensitive_count, ledger_mode = placeholder_transition
        predecessor_only_relationship_ids = (
            predecessor_relationship_set - baseline_relationship_set
        )
        baseline_source_alternative_ids = (
            baseline_relationship_set - predecessor_relationship_set
        ) - allowed_overlay_relationship_ids
        if not (
            len(predecessor_only_relationship_ids)
            == len(baseline_source_alternative_ids)
            == source_sensitive_count
            and predecessor_only_relationship_ids.isdisjoint(
                allowed_overlay_relationship_ids
            )
        ):
            raise ValueError(
                "terminal table visual source-alternative graph differs"
            )
        predecessor_endpoints = (
            _singleton_evidence_only_relationship_endpoints(
                predecessor_exclusions,
                predecessor_only_relationship_ids,
            )
        )
        baseline_endpoints = _singleton_evidence_only_relationship_endpoints(
            baseline_exclusions,
            baseline_source_alternative_ids,
        )
        if set(predecessor_endpoints.values()) & set(
            baseline_endpoints.values()
        ):
            raise ValueError(
                "terminal table visual source-alternative owner differs"
            )
        if ledger_mode == "empty" and any(
            reason != "evidence_only_relationship"
            for _element_id, reason in predecessor_exclusions
        ):
            raise ValueError(
                "terminal table empty visual OCR residue differs"
            )
    retained_relationship_ids = predecessor_relationship_set | (
        (baseline_relationship_set - predecessor_relationship_set)
        & allowed_overlay_relationship_ids
    )

    # A projected caption deliberately exposes a public-only item ID while its
    # bounded source identity remains absent from the reconstructed public IR.
    # The strict public validator independently recovers that same identity and
    # requires one owner-to-source containment edge.  It may be absent from both
    # the predecessor and a later P05 baseline, so synthesize only this exact,
    # proof-bound public edge instead of restoring arbitrary private raw edges.
    from app.services.opaque_group_custody import stable_id

    projected_caption_relationships = {
        source_id: stable_id(
            "rel",
            "contains",
            owner_primary_id,
            source_id,
            "parent",
        )
        for source_id in projected_caption_source_ids
    }
    if not set(projected_caption_relationships.values()).issubset(
        allowed_overlay_relationship_ids
    ):
        raise ValueError("terminal table visual caption relationship differs")
    retained_relationship_ids.update(projected_caption_relationships.values())

    filtered_exclusions: dict[tuple[str, str], set[str]] = {}
    for key, relationship_ids in baseline_exclusions.items():
        retained = relationship_ids & retained_relationship_ids
        if retained:
            filtered_exclusions[key] = retained
    for key, relationship_ids in predecessor_exclusions.items():
        replacement = relationship_ids & predecessor_only_relationship_ids
        if not replacement:
            continue
        if key in filtered_exclusions or any(
            existing_key[0] == key[0]
            for existing_key in filtered_exclusions
        ):
            raise ValueError(
                "terminal table visual source-alternative exclusion conflicts"
            )
        filtered_exclusions[key] = replacement
    for source_id, relationship_id in projected_caption_relationships.items():
        exact_key = (source_id, "evidence_only_relationship")
        if any(
            relationship_id in relationship_ids and key != exact_key
            for key, relationship_ids in baseline_exclusions.items()
        ):
            raise ValueError("terminal table visual caption exclusion differs")
        filtered_exclusions.setdefault(exact_key, set()).add(relationship_id)

    # P03 owns the visual's normalized primary text and its decision to keep
    # every nested OCR occurrence subordinate.  Preserve that public content
    # contract while replacing only the stale graph members identified above.
    output = deepcopy(dict(baseline_block))
    output["relationship_ids"] = sorted(retained_relationship_ids)
    output["excluded_contributions"] = _canonical_exclusions_from_map(
        filtered_exclusions
    )
    return output


def _rebind_terminal_non_target_running_region(
    baseline_block: Mapping[str, Any],
    candidate_block: Mapping[str, Any],
    public_item: Mapping[str, Any],
) -> dict[str, Any]:
    """Restore the closed canonical ownership of one running-region item."""

    if not all(
        type(value) is dict
        for value in (baseline_block, candidate_block, public_item)
    ):
        raise ValueError("terminal table running-region block differs")
    descriptor = public_item.get("running_region")
    if type(descriptor) is not dict:
        raise ValueError("terminal table running-region declaration differs")
    for key in (
        *_CANONICAL_BLOCK_IDENTITY_KEYS,
        "markdown",
        "text",
        "omission_reason",
        "suppressed_by_element_id",
    ):
        if baseline_block.get(key) != candidate_block.get(key):
            raise ValueError("terminal table running-region content differs")
    primary_id = baseline_block.get("primary_element_id")
    if (
        type(primary_id) is not str
        or not primary_id
        or descriptor.get("source_element_id") != primary_id
        or descriptor.get("canonical_block_id") != baseline_block.get("id")
        or descriptor.get("canonical_scope") != baseline_block.get("scope")
    ):
        raise ValueError("terminal table running-region binding differs")
    baseline_contributors = baseline_block.get("contributing_element_ids")
    candidate_contributors = candidate_block.get("contributing_element_ids")
    if (
        type(baseline_contributors) is not list
        or not baseline_contributors
        or baseline_contributors[0] != primary_id
        or type(candidate_contributors) is not list
        or not candidate_contributors
        or candidate_contributors[0] != primary_id
    ):
        raise ValueError("terminal table running-region ownership differs")

    output = deepcopy(dict(baseline_block))
    output["contributing_element_ids"] = [primary_id]
    output["relationship_ids"] = []
    output["excluded_contributions"] = []
    return output


def _compose_terminal_target_p03_overlay(
    baseline_block: Mapping[str, Any],
    predecessor_block: Mapping[str, Any],
    candidate_block: Mapping[str, Any],
    public_item: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply one validated public-P03 delta to a raw-free P04 table block."""

    if not all(type(value) is dict for value in (
        baseline_block,
        predecessor_block,
        candidate_block,
        public_item,
    )):
        raise ValueError("terminal table canonical target block differs")
    expected_keys = set(predecessor_block)
    if set(baseline_block) != expected_keys or set(candidate_block) != expected_keys:
        raise ValueError("terminal table canonical target block shape differs")
    if expected_keys != {
        *_CANONICAL_BLOCK_IDENTITY_KEYS,
        *_CANONICAL_BLOCK_MUTABLE_KEYS,
        "omission_reason",
        "suppressed_by_element_id",
    }:
        # `exclude_none=True` omits the final two optional keys on included
        # blocks.  Admit only that exact omission, never an unknown member.
        if expected_keys != {
            *_CANONICAL_BLOCK_IDENTITY_KEYS,
            *_CANONICAL_BLOCK_MUTABLE_KEYS,
        }:
            raise ValueError("terminal table canonical target block shape differs")

    for key in _CANONICAL_BLOCK_IDENTITY_KEYS:
        if not (
            baseline_block.get(key)
            == predecessor_block.get(key)
            == candidate_block.get(key)
        ):
            raise ValueError("terminal table canonical target identity differs")
    for key in ("omission_reason", "suppressed_by_element_id"):
        if not (
            baseline_block.get(key)
            == predecessor_block.get(key)
            == candidate_block.get(key)
        ):
            raise ValueError("terminal table canonical target disposition differs")
    if (
        baseline_block.get("primary_element_type") != "table"
        or baseline_block.get("scope") != "body"
        or baseline_block.get("omission_reason") is not None
    ):
        raise ValueError("terminal table canonical target authority differs")

    baseline_contributors = baseline_block.get("contributing_element_ids")
    predecessor_contributors = predecessor_block.get("contributing_element_ids")
    candidate_contributors = candidate_block.get("contributing_element_ids")
    if not all(type(value) is list and value for value in (
        baseline_contributors,
        predecessor_contributors,
        candidate_contributors,
    )) or any(
        any(type(member) is not str or not member for member in value)
        or len(value) != len(set(value))
        for value in (
            baseline_contributors,
            predecessor_contributors,
            candidate_contributors,
        )
    ):
        raise ValueError("terminal table canonical target contributors differ")
    owner_id = str(baseline_block["primary_element_id"])
    if any(value[0] != owner_id for value in (
        baseline_contributors,
        predecessor_contributors,
        candidate_contributors,
    )):
        raise ValueError("terminal table canonical target owner differs")
    predecessor_tail = predecessor_contributors[1:]
    if predecessor_tail:
        if baseline_contributors[-len(predecessor_tail) :] != predecessor_tail:
            raise ValueError("terminal table canonical predecessor tail differs")
        overlay_contributors = baseline_contributors[
            1 : -len(predecessor_tail)
        ]
    else:
        overlay_contributors = baseline_contributors[1:]
    declared_contributors, declared_relationship_ids = (
        _declared_target_overlay_ids(public_item)
    )
    if (
        not set(overlay_contributors).issubset(declared_contributors)
        or set(overlay_contributors).intersection(candidate_contributors[1:])
    ):
        raise ValueError("terminal table canonical overlay contributors differ")

    baseline_relationships = baseline_block.get("relationship_ids")
    predecessor_relationships = predecessor_block.get("relationship_ids")
    candidate_relationships = candidate_block.get("relationship_ids")
    if not all(type(value) is list for value in (
        baseline_relationships,
        predecessor_relationships,
        candidate_relationships,
    )) or any(
        any(type(member) is not str or not member for member in value)
        or len(value) != len(set(value))
        or value != sorted(value)
        for value in (
            baseline_relationships,
            predecessor_relationships,
            candidate_relationships,
        )
    ):
        raise ValueError("terminal table canonical target relationships differ")
    if not set(predecessor_relationships).issubset(baseline_relationships):
        raise ValueError("terminal table canonical predecessor relationships differ")
    overlay_relationships = set(baseline_relationships) - set(
        predecessor_relationships
    )
    allowed_relationships = _allowed_target_overlay_relationship_ids(
        owner_id,
        set(overlay_contributors),
        declared_relationship_ids,
    )
    if not overlay_relationships.issubset(allowed_relationships):
        raise ValueError("terminal table canonical overlay relationships differ")

    predecessor_exclusions = _canonical_exclusion_map(
        predecessor_block.get("excluded_contributions")
    )
    baseline_exclusions = _canonical_exclusion_map(
        baseline_block.get("excluded_contributions")
    )
    candidate_exclusions = _canonical_exclusion_map(
        candidate_block.get("excluded_contributions")
    )
    overlay_exclusions: dict[tuple[str, str], set[str]] = {}
    for key, relationship_ids in baseline_exclusions.items():
        predecessor_ids = predecessor_exclusions.get(key, set())
        if not predecessor_ids.issubset(relationship_ids):
            raise ValueError("terminal table canonical predecessor exclusion differs")
        delta = relationship_ids - predecessor_ids
        if delta:
            overlay_exclusions[key] = delta
    if any(
        key not in baseline_exclusions
        for key in predecessor_exclusions
    ):
        raise ValueError("terminal table canonical predecessor exclusion differs")
    if any(
        element_id not in declared_contributors
        or not relationship_ids.issubset(overlay_relationships)
        for (element_id, _reason), relationship_ids in overlay_exclusions.items()
    ):
        raise ValueError("terminal table canonical overlay exclusion differs")
    for key, relationship_ids in overlay_exclusions.items():
        candidate_exclusions.setdefault(key, set()).update(relationship_ids)

    output = deepcopy(dict(candidate_block))
    output["contributing_element_ids"] = [
        owner_id,
        *overlay_contributors,
        *candidate_contributors[1:],
    ]
    if len(output["contributing_element_ids"]) != len(
        set(output["contributing_element_ids"])
    ):
        raise ValueError("terminal table canonical target contributor repeats")
    output["relationship_ids"] = sorted(
        set(candidate_relationships) | overlay_relationships
    )
    output["excluded_contributions"] = _canonical_exclusions_from_map(
        candidate_exclusions
    )

    scalar_delta = False
    for field in ("markdown", "text"):
        baseline_scalar = baseline_block.get(field)
        predecessor_scalar = predecessor_block.get(field)
        candidate_scalar = candidate_block.get(field)
        if not all(type(value) is str for value in (
            baseline_scalar,
            predecessor_scalar,
            candidate_scalar,
        )) or not predecessor_scalar:
            raise ValueError("terminal table canonical target scalar differs")
        if baseline_scalar == predecessor_scalar:
            output[field] = candidate_scalar
            continue
        suffix = "\n\n" + predecessor_scalar
        if not baseline_scalar.endswith(suffix):
            raise ValueError("terminal table canonical overlay scalar differs")
        prefix = baseline_scalar[: -len(suffix)]
        if not prefix or prefix != prefix.strip():
            raise ValueError("terminal table canonical overlay scalar differs")
        output[field] = f"{prefix}\n\n{candidate_scalar}"
        scalar_delta = True
    if not (
        overlay_contributors
        or overlay_relationships
        or overlay_exclusions
        or scalar_delta
    ):
        raise ValueError("terminal table canonical target overlay is absent")
    return output


def _terminal_table_target_closure_public_ids(
    canonical: Any,
    candidate: Mapping[str, Any],
    target_public_item_ids: set[str],
) -> set[str]:
    """Resolve the public block closure owned by marked table targets."""

    if (
        type(canonical) is not dict
        or type(candidate) is not dict
        or type(target_public_item_ids) is not set
        or any(
            type(public_item_id) is not str or not public_item_id
            for public_item_id in target_public_item_ids
        )
    ):
        raise ValueError("terminal table target closure input differs")
    canonical_pages = canonical.get("pages")
    public_pages = candidate.get("pages")
    if (
        type(canonical_pages) is not list
        or type(public_pages) is not list
        or len(canonical_pages) != len(public_pages)
    ):
        raise ValueError("terminal table target closure pages differ")
    closure_public_ids: set[str] = set()
    seen_target_ids: set[str] = set()
    for canonical_page, public_page in zip(
        canonical_pages,
        public_pages,
        strict=True,
    ):
        if (
            type(canonical_page) is not dict
            or type(canonical_page.get("blocks")) is not list
            or type(public_page) is not dict
            or type(public_page.get("items")) is not list
            or len(canonical_page["blocks"]) != len(public_page["items"])
            or canonical_page.get("page_index") != public_page.get("page_index")
        ):
            raise ValueError("terminal table target closure page differs")
        blocks = canonical_page["blocks"]
        items = public_page["items"]
        primary_to_public: dict[str, str] = {}
        target_primary_ids: set[str] = set()
        for block, public_item in zip(blocks, items, strict=True):
            if type(block) is not dict or type(public_item) is not dict:
                raise ValueError("terminal table target closure block differs")
            primary_id = block.get("primary_element_id")
            public_item_id = public_item.get("id")
            if (
                type(primary_id) is not str
                or not primary_id
                or type(public_item_id) is not str
                or not public_item_id
                or primary_id in primary_to_public
            ):
                raise ValueError("terminal table target closure identity differs")
            primary_to_public[primary_id] = public_item_id
            if public_item_id in target_public_item_ids:
                target_primary_ids.add(primary_id)
                seen_target_ids.add(public_item_id)

        closure_primary_ids = set(target_primary_ids)
        for _closure_step in range(len(blocks) + 1):
            additions_for_step: set[str] = set()
            for block in blocks:
                primary_id = block["primary_element_id"]
                contributors = block.get("contributing_element_ids")
                suppressed_by = block.get("suppressed_by_element_id")
                if (
                    type(contributors) is not list
                    or any(
                        type(contributor_id) is not str or not contributor_id
                        for contributor_id in contributors
                    )
                    or (
                        suppressed_by is not None
                        and (type(suppressed_by) is not str or not suppressed_by)
                    )
                ):
                    raise ValueError(
                        "terminal table target closure contribution differs"
                    )
                if primary_id in closure_primary_ids:
                    additions = set(contributors) & set(primary_to_public)
                elif suppressed_by in closure_primary_ids:
                    additions = {primary_id}
                else:
                    additions = set()
                additions_for_step.update(additions - closure_primary_ids)
            if not additions_for_step:
                break
            closure_primary_ids.update(additions_for_step)
        else:
            raise ValueError("terminal table target closure did not converge")
        closure_public_ids.update(
            primary_to_public[primary_id]
            for primary_id in closure_primary_ids
        )
    if seen_target_ids != target_public_item_ids:
        raise ValueError("terminal table target closure coverage differs")
    return closure_public_ids


def _splice_terminal_table_canonical(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    canonical: dict[str, Any],
    transaction: tuple[Any, ...],
    diagnostic_relationship_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Keep exact P03 representation outside marked table target blocks."""

    baseline_canonical = baseline.get("canonical_presentation")
    if not isinstance(baseline_canonical, Mapping):
        return canonical
    if type(canonical) is not dict:
        raise ValueError("terminal table canonical projection differs")
    protected_diagnostic_ids = (
        set()
        if diagnostic_relationship_ids is None
        else diagnostic_relationship_ids
    )
    if (
        type(protected_diagnostic_ids) is not set
        or any(
            type(relationship_id) is not str or not relationship_id
            for relationship_id in protected_diagnostic_ids
        )
    ):
        raise ValueError("terminal table canonical diagnostic input differs")
    baseline_pages = baseline_canonical.get("pages")
    canonical_pages = canonical.get("pages")
    baseline_public_pages = baseline.get("pages")
    public_pages = candidate.get("pages")
    try:
        from app.services.ir import DocumentIR, build_document_ir
        from app.services.presentation import (
            _build_canonical_presentation_from_validated,
        )

        predecessor_public = {
            "document": deepcopy(baseline.get("document")),
            "pages": deepcopy(baseline_public_pages),
        }
        predecessor_ir = build_document_ir(predecessor_public)
        if type(predecessor_ir) is not DocumentIR:
            raise ValueError(
                "terminal table canonical predecessor IR differs"
            )
        predecessor_canonical = (
            _build_canonical_presentation_from_validated(
                predecessor_ir
            ).model_dump(mode="json", exclude_none=True)
        )
        # The canonical JSON is independently owned.  Release the direct,
        # fully validated producer result and its private input before the
        # document-wide splice walks the remaining public/canonical graphs.
        del predecessor_ir, predecessor_public
        predecessor_pages = predecessor_canonical.get("pages")
    except (MemoryError, RecursionError, TypeError, ValueError) as exc:
        raise ValueError(
            "terminal table canonical predecessor reconstruction differs"
        ) from exc
    if not all(type(value) is list for value in (
        baseline_pages,
        canonical_pages,
        baseline_public_pages,
        public_pages,
        predecessor_pages,
    )) or not (
        len(baseline_pages)
        == len(canonical_pages)
        == len(baseline_public_pages)
        == len(public_pages)
        == len(predecessor_pages)
    ):
        raise ValueError("terminal table canonical page closure differs")
    target_ids = {
        record[3]
        for record in transaction
        if type(record) is tuple and len(record) == 7 and type(record[3]) is str
    }
    if len(target_ids) != len(transaction):
        raise ValueError("terminal table canonical target identity differs")
    target_closure_public_ids = _terminal_table_target_closure_public_ids(
        canonical,
        candidate,
        target_ids,
    )
    public_items_by_id: dict[str, Mapping[str, Any]] = {}
    public_primary_by_id: dict[str, str] = {}
    for baseline_public_page, baseline_canonical_page in zip(
        baseline_public_pages,
        baseline_pages,
        strict=True,
    ):
        if (
            type(baseline_public_page) is not dict
            or type(baseline_canonical_page) is not dict
            or type(baseline_public_page.get("items")) is not list
            or type(baseline_canonical_page.get("blocks")) is not list
            or len(baseline_public_page["items"])
            != len(baseline_canonical_page["blocks"])
        ):
            raise ValueError("terminal table canonical public binding differs")
        for public_item, canonical_block in zip(
            baseline_public_page["items"],
            baseline_canonical_page["blocks"],
            strict=True,
        ):
            if type(public_item) is not dict or type(canonical_block) is not dict:
                raise ValueError("terminal table canonical public binding differs")
            public_id = public_item.get("id")
            primary_id = canonical_block.get("primary_element_id")
            if (
                type(public_id) is not str
                or not public_id
                or type(primary_id) is not str
                or not primary_id
                or public_id in public_items_by_id
                or public_id in public_primary_by_id
            ):
                raise ValueError("terminal table canonical public identity differs")
            public_items_by_id[public_id] = public_item
            public_primary_by_id[public_id] = primary_id
    source_sha256 = (baseline.get("document") or {}).get("sha256")
    if type(source_sha256) is not str or not source_sha256:
        raise ValueError("terminal table canonical document identity differs")
    from app.models import _canonical_ir_id

    document_id = _canonical_ir_id("doc", source_sha256)
    # These primary IDs are the only indirect manual-overlay classification.
    # The baseline was fully ParseResult-validated before this function is
    # called, and the final candidate is validated again after the splice.
    # Consequently these declarations are public P03 authority, never raw
    # custody.  Keep this extraction identical to the model's manual-overlay
    # classifier.
    declared_replacement_primary_ids: set[str] = set()
    for baseline_public_page in baseline_public_pages:
        if type(baseline_public_page) is not dict:
            raise ValueError("terminal table canonical public page differs")
        baseline_public_items = baseline_public_page.get("items")
        if type(baseline_public_items) is not list:
            raise ValueError("terminal table canonical public items differ")
        for baseline_public_item in baseline_public_items:
            if type(baseline_public_item) is not dict:
                raise ValueError("terminal table canonical public item differs")
            form_group = baseline_public_item.get("form_group")
            if type(form_group) is dict and form_group.get(
                "canonical_mode"
            ) == "replace":
                contributor_ids = form_group.get("contributor_element_ids")
                if type(contributor_ids) is not list or any(
                    type(value) is not str or not value
                    for value in contributor_ids
                ):
                    raise ValueError(
                        "terminal table canonical form declaration differs"
                    )
                declared_replacement_primary_ids.update(contributor_ids)
            outline_group = baseline_public_item.get("outline_group")
            if type(outline_group) is dict:
                for name in (
                    "member_element_ids",
                    "continuation_element_ids",
                    "canonical_contributor_element_ids",
                ):
                    contributor_ids = outline_group.get(name, [])
                    if type(contributor_ids) is not list or any(
                        type(value) is not str or not value
                        for value in contributor_ids
                    ):
                        raise ValueError(
                            "terminal table canonical outline declaration differs"
                        )
                    declared_replacement_primary_ids.update(contributor_ids)

    page_view_names = ("full", "body", "header", "footer")
    seen_target_ids: set[str] = set()
    for (
        baseline_page,
        canonical_page,
        baseline_public_page,
        public_page,
        predecessor_page,
    ) in zip(
        baseline_pages,
        canonical_pages,
        baseline_public_pages,
        public_pages,
        predecessor_pages,
        strict=True,
    ):
        if not all(type(value) is dict for value in (
            baseline_page,
            canonical_page,
            baseline_public_page,
            public_page,
            predecessor_page,
        )):
            raise ValueError("terminal table canonical page shape differs")
        baseline_blocks = baseline_page.get("blocks")
        canonical_blocks = canonical_page.get("blocks")
        baseline_public_items = baseline_public_page.get("items")
        public_items = public_page.get("items")
        predecessor_blocks = predecessor_page.get("blocks")
        if not all(type(value) is list for value in (
            baseline_blocks,
            canonical_blocks,
            baseline_public_items,
            public_items,
            predecessor_blocks,
        )) or not (
            len(baseline_blocks)
            == len(canonical_blocks)
            == len(baseline_public_items)
            == len(public_items)
            == len(predecessor_blocks)
        ):
            raise ValueError("terminal table canonical block closure differs")
        baseline_public_metadata = {
            key: value
            for key, value in baseline_public_page.items()
            if key != "items"
        }
        candidate_public_metadata = {
            key: value for key, value in public_page.items() if key != "items"
        }
        if baseline_public_metadata != candidate_public_metadata:
            raise ValueError("terminal table canonical public page drifted")
        baseline_metadata = {
            key: value
            for key, value in baseline_page.items()
            if key not in {"blocks", *page_view_names}
        }
        candidate_metadata = {
            key: value
            for key, value in canonical_page.items()
            if key not in {"blocks", *page_view_names}
        }
        if _drop_optional_null_shape(baseline_metadata) != (
            _drop_optional_null_shape(candidate_metadata)
        ):
            raise ValueError("terminal table canonical page metadata drifted")
        for key, value in baseline_metadata.items():
            canonical_page[key] = deepcopy(value)

        page_has_target = False
        for offset, (
            baseline_block,
            candidate_block,
            baseline_public_item,
            public_item,
            predecessor_block,
        ) in enumerate(
            zip(
                baseline_blocks,
                canonical_blocks,
                baseline_public_items,
                public_items,
                predecessor_blocks,
                strict=True,
            )
        ):
            if not all(type(value) is dict for value in (
                baseline_block,
                candidate_block,
                baseline_public_item,
                public_item,
                predecessor_block,
            )):
                raise ValueError("terminal table canonical block shape differs")
            if public_item.get("id") in target_ids:
                if (
                    baseline_public_item.get("id") != public_item.get("id")
                    or public_item.get("type") != "table"
                    or candidate_block.get("primary_element_type") != "table"
                ):
                    raise ValueError("terminal table canonical target differs")
                seen_target_ids.add(public_item["id"])
                page_has_target = True
                table_evidence = public_item.get("table_evidence")
                nonvalid_target = (
                    type(table_evidence) is dict
                    and table_evidence.get("status")
                    in {"unresolved", "structural_failure"}
                )
                if nonvalid_target:
                    # A nonvalid sidecar is diagnostic-only.  Its public item
                    # must be the exact P03 item once that sidecar is removed,
                    # and its canonical block must use only relationships that
                    # can be reconstructed from that public item.  Historical
                    # raw-graph audit edges remain available in the custody
                    # sidecar but cannot be grandfathered onto this changed,
                    # marked target.
                    public_predecessor = deepcopy(public_item)
                    public_predecessor.pop("table_evidence", None)
                    if _drop_optional_null_shape(public_predecessor) != (
                        _drop_optional_null_shape(baseline_public_item)
                    ):
                        raise ValueError(
                            "terminal table canonical nonvalid target drifted"
                        )
                has_manual_overlay = bool(
                    _P03_MANUAL_CANONICAL_OVERLAY_KEYS.intersection(
                        baseline_public_item
                    )
                    or baseline_block.get("primary_element_id")
                    in declared_replacement_primary_ids
                    or baseline_public_item.get("running_region") is not None
                    or type(baseline_public_item.get("outline_group")) is dict
                    or (
                        type(baseline_public_item.get("form_group")) is dict
                        and baseline_public_item["form_group"].get(
                            "canonical_mode"
                        )
                        in ("inert", "replace")
                    )
                )
                if has_manual_overlay:
                    if _drop_optional_null_shape(candidate_block) == (
                        _drop_optional_null_shape(predecessor_block)
                    ):
                        canonical_blocks[offset] = deepcopy(baseline_block)
                    elif _drop_optional_null_shape(baseline_block) != (
                        _drop_optional_null_shape(predecessor_block)
                    ):
                        canonical_blocks[offset] = (
                            _compose_terminal_target_p03_overlay(
                                baseline_block,
                                predecessor_block,
                                candidate_block,
                                baseline_public_item,
                            )
                        )
                if nonvalid_target:
                    # Compose any independently validated P03 semantic
                    # presentation first, then retain only the relationship
                    # graph reproducible from the fresh public target.  The
                    # content/contributor contract must stay byte-equivalent
                    # to the P03 target.
                    selected_block = canonical_blocks[offset]
                    baseline_core = deepcopy(baseline_block)
                    selected_core = deepcopy(selected_block)
                    for block_core in (baseline_core, selected_core):
                        block_core.pop("relationship_ids", None)
                        block_core.pop("excluded_contributions", None)
                    if _drop_optional_null_shape(selected_core) != (
                        _drop_optional_null_shape(baseline_core)
                    ):
                        raise ValueError(
                            "terminal table canonical nonvalid target content drifted"
                        )
                    # The already-validated P03 target is the only positive
                    # semantic authority for a nonvalid P04 sidecar.  Restore
                    # its exact graph here; the subsequent custody pass may
                    # only subtract the exact relationship IDs pinned by the
                    # frozen diagnostic sidecar.
                    selected_block["relationship_ids"] = deepcopy(
                        baseline_block.get("relationship_ids")
                    )
                    selected_block["excluded_contributions"] = deepcopy(
                        baseline_block.get("excluded_contributions")
                    )
                continue
            if baseline_public_item != public_item:
                raise ValueError(
                    "terminal table canonical non-target public item drifted"
                )
            if public_item.get("id") in target_closure_public_ids:
                # This block is a contribution/suppression member of the
                # marked table's independently reconstructed public graph.
                # Keep the fresh authoritative block so its consumption
                # relationships remain closed with the fresh target.
                continue
            if protected_diagnostic_ids.intersection(
                baseline_block.get("relationship_ids") or []
            ) or any(
                protected_diagnostic_ids.intersection(
                    exclusion.get("relationship_ids") or []
                )
                for exclusion in baseline_block.get(
                    "excluded_contributions"
                )
                or []
                if type(exclusion) is dict
            ):
                raise ValueError(
                    "terminal table diagnostic relationship reached non-target"
                )
            if public_item.get("layout_visual_relationships_projected") is True:
                canonical_blocks[offset] = (
                    _rebind_terminal_non_target_visual_overlay(
                        baseline_block,
                        predecessor_block,
                        candidate_block,
                        public_item,
                        document_id=document_id,
                        public_items_by_id=public_items_by_id,
                        public_primary_by_id=public_primary_by_id,
                    )
                )
                continue
            if public_item.get("running_region") is not None:
                canonical_blocks[offset] = (
                    _rebind_terminal_non_target_running_region(
                        baseline_block,
                        candidate_block,
                        public_item,
                    )
                )
                continue
            has_manual_overlay = bool(
                _P03_MANUAL_CANONICAL_OVERLAY_KEYS.intersection(public_item)
                or baseline_block.get("primary_element_id")
                in declared_replacement_primary_ids
                or public_item.get("running_region") is not None
                or type(public_item.get("outline_group")) is dict
                or (
                    type(public_item.get("form_group")) is dict
                    and public_item["form_group"].get("canonical_mode")
                    in ("inert", "replace")
                )
            )
            if not has_manual_overlay and (
                _drop_optional_null_shape(predecessor_block)
                != _drop_optional_null_shape(candidate_block)
            ):
                raise ValueError(
                    "terminal table canonical non-target predecessor drifted"
                )
            canonical_blocks[offset] = deepcopy(baseline_block)

        from app.models import _canonical_views_from_blocks

        rebuilt_views = _canonical_views_from_blocks(canonical_page)
        if page_has_target:
            for name in ("full", "body"):
                canonical_page[name] = rebuilt_views[name]
            for name in ("header", "footer"):
                canonical_page[name] = deepcopy(baseline_page[name])
        else:
            for name in page_view_names:
                canonical_page[name] = deepcopy(baseline_page[name])

    if seen_target_ids != target_ids:
        raise ValueError("terminal table canonical target coverage differs")

    document_metadata_keys = set(canonical) - {"pages", *page_view_names}
    baseline_document_metadata = {
        key: value
        for key, value in baseline_canonical.items()
        if key not in {"pages", *page_view_names}
    }
    candidate_document_metadata = {
        key: canonical[key] for key in document_metadata_keys
    }
    if _drop_optional_null_shape(baseline_document_metadata) != (
        _drop_optional_null_shape(candidate_document_metadata)
    ):
        raise ValueError("terminal table canonical document metadata drifted")
    for key, value in baseline_document_metadata.items():
        canonical[key] = deepcopy(value)

    from app.models import _canonical_document_views

    rebuilt_document_views = _canonical_document_views(canonical_pages)
    for name in ("full", "body"):
        canonical[name] = rebuilt_document_views[name]
    for name in ("header", "footer"):
        canonical[name] = deepcopy(baseline_canonical[name])
    return canonical


def _remove_terminal_diagnostic_canonical_edges(
    canonical: Any,
    diagnostic_relationship_ids: set[str],
    candidate: Mapping[str, Any],
    target_public_item_ids: set[str],
) -> dict[str, Any]:
    """Move raw-only audit edges out of canonical blocks into custody only.

    This operation has negative authority only: it can remove an exactly
    frozen diagnostic relationship from a changed table target, never
    introduce content, structure, or an alternative relationship.  A matching
    ID on an unrelated P03 block rejects the transaction instead of changing
    that block.  The default-off path never calls it and keeps the exact P03
    response.
    """

    if (
        type(canonical) is not dict
        or type(diagnostic_relationship_ids) is not set
        or type(candidate) is not dict
        or type(target_public_item_ids) is not set
        or any(
            type(relationship_id) is not str or not relationship_id
            for relationship_id in diagnostic_relationship_ids
        )
        or any(
            type(public_item_id) is not str or not public_item_id
            for public_item_id in target_public_item_ids
        )
    ):
        raise ValueError("terminal table diagnostic canonical input differs")
    pages = canonical.get("pages")
    public_pages = candidate.get("pages")
    if (
        type(pages) is not list
        or type(public_pages) is not list
        or len(pages) != len(public_pages)
    ):
        raise ValueError("terminal table diagnostic canonical pages differ")
    mutable_public_item_ids = _terminal_table_target_closure_public_ids(
        canonical,
        candidate,
        target_public_item_ids,
    )
    seen_target_ids: set[str] = set()
    for page, public_page in zip(pages, public_pages, strict=True):
        if (
            type(page) is not dict
            or type(page.get("blocks")) is not list
            or type(public_page) is not dict
            or type(public_page.get("items")) is not list
            or len(page["blocks"]) != len(public_page["items"])
            or page.get("page_index") != public_page.get("page_index")
        ):
            raise ValueError("terminal table diagnostic canonical page differs")
        for block, public_item in zip(
            page["blocks"],
            public_page["items"],
            strict=True,
        ):
            if type(block) is not dict or type(public_item) is not dict:
                raise ValueError("terminal table diagnostic canonical block differs")
            public_item_id = public_item.get("id")
            is_target = public_item_id in target_public_item_ids
            is_mutable = public_item_id in mutable_public_item_ids
            if is_target:
                seen_target_ids.add(public_item_id)
            relationship_ids = block.get("relationship_ids")
            exclusions = block.get("excluded_contributions")
            if (
                type(relationship_ids) is not list
                or any(
                    type(relationship_id) is not str or not relationship_id
                    for relationship_id in relationship_ids
                )
                or len(relationship_ids) != len(set(relationship_ids))
                or type(exclusions) is not list
            ):
                raise ValueError(
                    "terminal table diagnostic canonical relationship differs"
                )
            diagnostic_block_ids = {
                relationship_id
                for relationship_id in relationship_ids
                if relationship_id in diagnostic_relationship_ids
            }
            diagnostic_block_ids.update(
                relationship_id
                for exclusion in exclusions
                if type(exclusion) is dict
                and type(exclusion.get("relationship_ids")) is list
                for relationship_id in exclusion["relationship_ids"]
                if relationship_id in diagnostic_relationship_ids
            )
            if diagnostic_block_ids and not is_mutable:
                raise ValueError(
                    "terminal table diagnostic relationship reached non-target"
                )
            block["relationship_ids"] = [
                relationship_id
                for relationship_id in relationship_ids
                if relationship_id not in diagnostic_relationship_ids
            ]
            retained_exclusions: list[dict[str, Any]] = []
            for exclusion in exclusions:
                if (
                    type(exclusion) is not dict
                    or set(exclusion)
                    != {"element_id", "reason", "relationship_ids"}
                    or type(exclusion.get("element_id")) is not str
                    or not exclusion["element_id"]
                    or type(exclusion.get("reason")) is not str
                    or not exclusion["reason"]
                    or type(exclusion.get("relationship_ids")) is not list
                    or any(
                        type(relationship_id) is not str
                        or not relationship_id
                        for relationship_id in exclusion["relationship_ids"]
                    )
                    or len(exclusion["relationship_ids"])
                    != len(set(exclusion["relationship_ids"]))
                ):
                    raise ValueError(
                        "terminal table diagnostic canonical exclusion differs"
                    )
                retained_relationship_ids = [
                    relationship_id
                    for relationship_id in exclusion["relationship_ids"]
                    if relationship_id not in diagnostic_relationship_ids
                ]
                if not retained_relationship_ids:
                    continue
                retained_exclusion = deepcopy(exclusion)
                retained_exclusion["relationship_ids"] = (
                    retained_relationship_ids
                )
                retained_exclusions.append(retained_exclusion)
            block["excluded_contributions"] = retained_exclusions

    if seen_target_ids != target_public_item_ids:
        raise ValueError("terminal table diagnostic target coverage differs")

    remaining_ids = {
        relationship_id
        for page in pages
        for block in page["blocks"]
        for relationship_id in block["relationship_ids"]
    }
    remaining_ids.update(
        relationship_id
        for page in pages
        for block in page["blocks"]
        for exclusion in block["excluded_contributions"]
        for relationship_id in exclusion["relationship_ids"]
    )
    if remaining_ids & diagnostic_relationship_ids:
        raise ValueError("terminal table diagnostic relationship reached canonical")
    return canonical


def _owned_terminal_table_custody_ir_projection(
    baseline_ir: Any,
    authoritative_ir: Any,
    transaction: tuple[Any, ...],
) -> dict[str, Any]:
    """Project one private JSON value for terminal table-custody rebinding."""

    from app.services.ir import DocumentIR

    if (
        type(baseline_ir) is not DocumentIR
        or type(authoritative_ir) is not DocumentIR
        or type(transaction) is not tuple
        or len(transaction) > 65536
    ):
        raise ValueError("terminal table custody IR input differs")
    target_ids: set[str] = set()
    for record in transaction:
        if (
            type(record) is not tuple
            or len(record) != 7
            or type(record[3]) is not str
            or not record[3]
            or record[3] in target_ids
        ):
            raise ValueError("terminal table custody transaction differs")
        target_ids.add(record[3])

    authoritative_by_public_id: dict[str, Any] = {}
    for element in authoritative_ir.elements:
        legacy = element.properties.get("legacy_item")
        public_id = legacy.get("id") if isinstance(legacy, Mapping) else None
        if not isinstance(public_id, str) or public_id not in target_ids:
            continue
        if public_id in authoritative_by_public_id:
            raise ValueError("terminal table custody public binding repeats")
        authoritative_by_public_id[public_id] = element

    # `model_dump(mode="json")` is the single independently owned working
    # projection. The terminal DocumentIR validation below copies it into the
    # returned model, so neither input IR can alias the result.
    working = baseline_ir.model_dump(mode="json")
    elements = working.get("elements") if type(working) is dict else None
    if type(elements) is not list:
        raise ValueError("terminal table custody IR projection differs")
    rebound_ids: set[str] = set()
    for element in elements:
        if type(element) is not dict:
            raise ValueError("terminal table custody element differs")
        properties = element.get("properties")
        if type(properties) is not dict:
            raise ValueError("terminal table custody properties differ")
        legacy = properties.get("legacy_item")
        public_id = legacy.get("id") if isinstance(legacy, Mapping) else None
        if public_id not in target_ids:
            continue
        authoritative = authoritative_by_public_id.get(public_id)
        if authoritative is None or authoritative.id != element.get("id"):
            raise ValueError("terminal table custody public binding differs")
        authoritative_projection = authoritative.model_dump(mode="json")
        if type(authoritative_projection) is not dict:
            raise ValueError("terminal table custody authority differs")
        authoritative_properties = authoritative_projection.get("properties")
        if type(authoritative_properties) is not dict:
            raise ValueError("terminal table custody authority differs")
        element["type"] = authoritative_projection.get("type")
        element["value"] = authoritative_projection.get("value")
        element["markdown"] = authoritative_projection.get("markdown")
        element["presentation_role"] = authoritative_projection.get(
            "presentation_role"
        )
        retained_properties = {
            key: value
            for key, value in properties.items()
            if key != "legacy_item"
        }
        retained_properties["legacy_item"] = authoritative_properties.get(
            "legacy_item"
        )
        element["properties"] = retained_properties
        rebound_ids.add(public_id)
    if rebound_ids != target_ids:
        raise ValueError("terminal table custody target coverage differs")
    return working


def _rebind_terminal_table_custody_ir(
    baseline_ir: Any,
    authoritative_ir: Any,
    transaction: tuple[Any, ...],
) -> Any:
    """Bind target content to public P04 while retaining frozen raw edges."""

    from app.services.ir import DocumentIR

    owned_projection = _owned_terminal_table_custody_ir_projection(
        baseline_ir,
        authoritative_ir,
        transaction,
    )
    return DocumentIR.model_validate(owned_projection)


_TERMINAL_TABLE_CUSTODY_CLOSURE_MAX_BYTES = 128 * 1024 * 1024


def _terminal_table_custody_closure_identity(
    custody_ir: Any,
    detached_custody: Any,
    *,
    deadline: float,
) -> tuple[str, int]:
    """Hash the exact diagnostic relationships and their endpoint records.

    The custody sealer is deliberately non-authoritative, but it is still an
    integration boundary.  This bounded, streaming identity prevents a sealer
    callback from changing the IR/frozen evidence during that call and then
    returning a superficially valid sidecar.
    """

    from app.services.ir import DocumentIR
    from app.services.opaque_group_custody import (
        DetachedOpaqueGroupEdges,
        FrozenRawAssertion,
        FrozenRawDefinition,
        FrozenRelevantRawClosure,
        MAX_RECORDS,
        OpaqueGroupCustodyIntegrityError,
        OpaqueGroupCustodyResourceError,
        OpaqueGroupCustodyTimeoutError,
    )

    if (
        type(custody_ir) is not DocumentIR
        or type(detached_custody) is not DetachedOpaqueGroupEdges
        or type(detached_custody.original_relationship_ids) is not tuple
        or type(detached_custody.detached) is not tuple
        or len(detached_custody.detached) > MAX_RECORDS
        or type(detached_custody.raw_closure) is not FrozenRelevantRawClosure
    ):
        raise OpaqueGroupCustodyIntegrityError(
            "terminal table custody closure type differs"
        )

    digest = hashlib.sha256()
    encoded_size = 0
    encoder = json.JSONEncoder(
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    def feed(value: Any) -> None:
        nonlocal encoded_size
        if time.perf_counter() > deadline:
            raise OpaqueGroupCustodyTimeoutError(
                "terminal table custody closure deadline exceeded"
            )
        delimiter = b"\x1e"
        encoded_size += len(delimiter)
        if encoded_size > _TERMINAL_TABLE_CUSTODY_CLOSURE_MAX_BYTES:
            raise OpaqueGroupCustodyResourceError(
                "terminal table custody closure exceeds its byte cap"
            )
        digest.update(delimiter)
        for chunk in encoder.iterencode(value):
            if time.perf_counter() > deadline:
                raise OpaqueGroupCustodyTimeoutError(
                    "terminal table custody closure deadline exceeded"
                )
            encoded = chunk.encode("utf-8")
            encoded_size += len(encoded)
            if encoded_size > _TERMINAL_TABLE_CUSTODY_CLOSURE_MAX_BYTES:
                raise OpaqueGroupCustodyResourceError(
                    "terminal table custody closure exceeds its byte cap"
                )
            digest.update(encoded)

    try:
        original_ids = detached_custody.original_relationship_ids
        if (
            any(type(value) is not str or not value for value in original_ids)
            or len(original_ids) != len(set(original_ids))
        ):
            raise OpaqueGroupCustodyIntegrityError(
                "terminal table custody original relationship identity differs"
            )

        detached_ids: list[str] = []
        endpoint_ids: set[str] = set()
        feed({"original_relationship_ids": original_ids})
        for offset, value in enumerate(detached_custody.detached):
            if (
                type(value) is not tuple
                or len(value) != 2
                or type(value[0]) is not int
                or value[0] < 0
                or not hasattr(value[1], "model_dump")
            ):
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table frozen relationship closure differs"
                )
            original_index, relationship = value
            relationship_json = relationship.model_dump(mode="json")
            relationship_id = relationship_json.get("id")
            source_id = relationship_json.get("source_id")
            target_id = relationship_json.get("target_id")
            if (
                type(relationship_id) is not str
                or not relationship_id
                or type(source_id) is not str
                or not source_id
                or type(target_id) is not str
                or not target_id
            ):
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table frozen relationship identity differs"
                )
            detached_ids.append(relationship_id)
            endpoint_ids.update((source_id, target_id))
            feed(
                {
                    "detached_offset": offset,
                    "original_index": original_index,
                    "relationship": relationship_json,
                }
            )
        if len(detached_ids) != len(set(detached_ids)):
            raise OpaqueGroupCustodyIntegrityError(
                "terminal table frozen relationship repeats"
            )

        raw_closure = detached_custody.raw_closure
        if (
            type(raw_closure.definitions) is not tuple
            or type(raw_closure.assertions) is not tuple
            or type(raw_closure.closure_sha256) is not str
            or len(raw_closure.closure_sha256) != 64
            or type(raw_closure.closure_size_bytes) is not int
            or raw_closure.closure_size_bytes < 0
        ):
            raise OpaqueGroupCustodyIntegrityError(
                "terminal table frozen raw closure differs"
            )
        feed(
            {
                "raw_closure_sha256": raw_closure.closure_sha256,
                "raw_closure_size_bytes": raw_closure.closure_size_bytes,
            }
        )
        for offset, definition in enumerate(raw_closure.definitions):
            if type(definition) is not FrozenRawDefinition:
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table frozen raw definition differs"
                )
            feed(
                {
                    "definition_offset": offset,
                    "raw_ref": definition.raw_ref,
                    "collection": definition.collection,
                    "collection_index": definition.collection_index,
                    "label": definition.label,
                    "selected_source_sha256": definition.selected_source_sha256,
                }
            )
        for offset, assertion in enumerate(raw_closure.assertions):
            if type(assertion) is not FrozenRawAssertion:
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table frozen raw assertion differs"
                )
            feed(
                {
                    "assertion_offset": offset,
                    "owner_order": assertion.owner_order,
                    "owner_raw_ref": assertion.owner_raw_ref,
                    "literal_target_raw_ref": assertion.literal_target_raw_ref,
                    "relationship_field": assertion.relationship_field,
                    "raw_slot_index": assertion.raw_slot_index,
                    "raw_target_slot_index": assertion.raw_target_slot_index,
                    "relationship_type": assertion.relationship_type,
                    "source_raw_ref": assertion.source_raw_ref,
                    "target_raw_ref": assertion.target_raw_ref,
                    "raw_assertion_sha256": assertion.raw_assertion_sha256,
                }
            )

        detached_id_set = set(detached_ids)
        observed_ids: list[str] = []
        for offset, relationship in enumerate(custody_ir.relationships):
            relationship_id = getattr(relationship, "id", None)
            if relationship_id not in detached_id_set:
                continue
            relationship_json = relationship.model_dump(mode="json")
            observed_ids.append(relationship_id)
            endpoint_ids.update(
                (relationship_json.get("source_id"), relationship_json.get("target_id"))
            )
            feed(
                {
                    "custody_relationship_offset": offset,
                    "relationship": relationship_json,
                }
            )
        if set(observed_ids) != detached_id_set or len(observed_ids) != len(
            detached_ids
        ):
            raise OpaqueGroupCustodyIntegrityError(
                "terminal table custody relationship coverage differs"
            )
        if any(type(value) is not str or not value for value in endpoint_ids):
            raise OpaqueGroupCustodyIntegrityError(
                "terminal table custody endpoint identity differs"
            )

        observed_endpoints: list[str] = []
        for offset, element in enumerate(custody_ir.elements):
            element_id = getattr(element, "id", None)
            if element_id not in endpoint_ids:
                continue
            observed_endpoints.append(element_id)
            feed(
                {
                    "custody_element_offset": offset,
                    "element": element.model_dump(mode="json"),
                }
            )
        if set(observed_endpoints) != endpoint_ids or len(observed_endpoints) != len(
            endpoint_ids
        ):
            raise OpaqueGroupCustodyIntegrityError(
                "terminal table custody endpoint coverage differs"
            )
        feed(
            {
                "element_count": len(custody_ir.elements),
                "relationship_count": len(custody_ir.relationships),
            }
        )
    except (
        OpaqueGroupCustodyIntegrityError,
        OpaqueGroupCustodyResourceError,
        OpaqueGroupCustodyTimeoutError,
    ):
        raise
    except (MemoryError, RecursionError) as exc:
        raise OpaqueGroupCustodyResourceError(
            "terminal table custody closure exhausted resources"
        ) from exc
    except (AttributeError, OverflowError, TypeError, UnicodeError, ValueError) as exc:
        raise OpaqueGroupCustodyIntegrityError(
            "terminal table custody closure is not strict data"
        ) from exc
    return digest.hexdigest(), encoded_size


def _apply_terminal_table_authority(
    baseline: dict[str, Any],
    baseline_ir: Any,
    transaction: tuple[Any, ...],
    settings: Settings,
    *,
    raw_graph: Mapping[str, Any] | None,
    native_texts: Sequence[str],
    text_run_evidence: Any | None,
    form_evidence: Any | None,
    outline_evidence: Any | None,
    source_pdf_bytes: bytes | None,
    input_kind: InputKind,
    document_deadline: float,
    page_deadlines: dict[int, float],
    state: dict[str, Any],
    table_dependency_predecessor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Commit P04 table authority once, or return the exact P03 baseline."""

    del (
        native_texts,
        text_run_evidence,
        form_evidence,
        outline_evidence,
        source_pdf_bytes,
        input_kind,
    )
    from app.services.opaque_group_custody import (
        OpaqueGroupCustodyIntegrityError,
        OpaqueGroupCustodyResourceError,
        OpaqueGroupCustodyTimeoutError,
        capture_opaque_group_edges,
        has_literal_table_marker,
        seal_diagnostic_custody,
    )

    if type(baseline) is not dict or type(transaction) is not tuple:
        raise ValueError("terminal table authority input differs")
    baseline_result = ParseResult.model_validate(deepcopy(baseline))
    rollback_baseline = (
        table_dependency_predecessor
        if table_dependency_predecessor is not None
        else baseline
    )
    if not isinstance(rollback_baseline, dict):
        raise ValueError("terminal table dependency predecessor differs")
    rollback_result = (
        ParseResult.model_validate(deepcopy(rollback_baseline))
        if rollback_baseline is not baseline
        else baseline_result
    )
    if not transaction:
        state["_p04_validated_parse_result"] = baseline_result
        return baseline
    if (
        not settings.table_span_fidelity_enabled
        or state.get("timed_out") is True
        or state.get("span_fidelity_disabled") is True
        or state.get("custody_rejected") is True
    ):
        state["_p04_validated_parse_result"] = rollback_result
        return rollback_baseline

    def commit(active_deadline: float) -> tuple[dict[str, Any], ParseResult]:
        try:
            from app.services.ir import DocumentIR, build_document_ir
            from app.services.table_semantics import (
                finalize_table_pages,
                rebind_table_overlays_after_phase03,
            )

            candidate = {
                key: deepcopy(value)
                for key, value in baseline.items()
                if key
                not in {
                    "pages",
                    "canonical_presentation",
                    "canonical_source_custody",
                }
            }
            candidate["pages"] = rebind_table_overlays_after_phase03(
                baseline.get("pages"),
                transaction,
                deadline=active_deadline,
                transaction_is_owned=True,
            )
            finalize_table_pages(
                candidate.get("pages"),
                str((candidate.get("document") or {}).get("sha256") or ""),
                table_span_fidelity_enabled=True,
                table_span_fidelity_document_deadline=active_deadline,
                # The outer document segment shifts every page clock exactly
                # once; finalization itself is document-wide.
                table_span_fidelity_page_deadlines=None,
                table_span_fidelity_state=state,
            )
            if not has_literal_table_marker(candidate):
                if state.get("timed_out") is True:
                    raise OpaqueGroupCustodyTimeoutError(
                        "terminal table finalization exceeded its deadline"
                    )
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table finalization rejected the overlay"
                )
            authoritative_ir = build_document_ir(candidate)
            if type(authoritative_ir) is not DocumentIR:
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table authoritative IR differs"
                )
            target_public_item_ids = {record[3] for record in transaction}
            target_element_ids = frozenset(
                element.id
                for element in authoritative_ir.elements
                if isinstance(
                    (legacy_item := element.properties.get("legacy_item")),
                    Mapping,
                )
                and legacy_item.get("id") in target_public_item_ids
            )
            if len(target_element_ids) != len(target_public_item_ids):
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table custody target identity differs"
                )
            frozen_custody = capture_opaque_group_edges(
                baseline_ir,
                raw_graph or {},
                target_element_ids=target_element_ids,
                deadline=active_deadline,
            )
            custody_ir = _rebind_terminal_table_custody_ir(
                baseline_ir,
                authoritative_ir,
                transaction,
            )
            custody_closure_identity = (
                _terminal_table_custody_closure_identity(
                    custody_ir,
                    frozen_custody,
                    deadline=active_deadline,
                )
            )
            sealed_custody, diagnostic_relationship_ids = (
                seal_diagnostic_custody(
                    candidate,
                    custody_ir,
                    raw_graph=raw_graph or {},
                    detached_custody=frozen_custody,
                    deadline=active_deadline,
                )
            )
            if _terminal_table_custody_closure_identity(
                custody_ir,
                frozen_custody,
                deadline=active_deadline,
            ) != custody_closure_identity:
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table custody closure changed during sealing"
                )
            # The post-seal identity has closed every relationship and
            # endpoint record used by the sealer.  The complete custody IR is
            # no longer needed while canonical/final ParseResult models are
            # allocated below.
            del custody_ir
            from app.models import CanonicalSourceCustody

            if (
                type(sealed_custody) is not CanonicalSourceCustody
                or type(diagnostic_relationship_ids) is not tuple
                or any(
                    type(relationship_id) is not str or not relationship_id
                    for relationship_id in diagnostic_relationship_ids
                )
            ):
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table diagnostic custody result differs"
                )
            # `seal_diagnostic_custody` returns an exact, fully validated
            # CanonicalSourceCustody.  Retain one owned JSON projection for
            # the terminal canonical digest instead of validating the same
            # pre-digest sidecar a second time.  The completed sidecar and the
            # final ParseResult remain independently validated below.
            source_custody = sealed_custody.model_dump(mode="json")
            del sealed_custody
            diagnostic_relationship_id_set = set(
                diagnostic_relationship_ids
            )
            sidecar_relationship_ids = {
                record["relationship_id"]
                for record in source_custody["records"]
            }
            frozen_relationship_ids = {
                relationship.id
                for _index, relationship in frozen_custody.detached
            }
            del frozen_custody
            if (
                len(diagnostic_relationship_id_set)
                != len(diagnostic_relationship_ids)
                or diagnostic_relationship_id_set
                != sidecar_relationship_ids
                or diagnostic_relationship_id_set
                != frozen_relationship_ids
            ):
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table diagnostic relationship identity differs"
                )
            authoritative_relationship_ids = {
                relationship.id for relationship in authoritative_ir.relationships
            }
            diagnostic_group_ids = {
                record["group_element_id"]
                for record in source_custody["records"]
            }
            authoritative_element_ids = {
                element.id for element in authoritative_ir.elements
            }
            authoritative_relationship_endpoints = {
                endpoint_id
                for relationship in authoritative_ir.relationships
                for endpoint_id in (relationship.source_id, relationship.target_id)
            }
            if diagnostic_relationship_id_set & authoritative_relationship_ids:
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table diagnostic relationship reached authority"
                )
            if diagnostic_group_ids & (
                authoritative_element_ids | authoritative_relationship_endpoints
            ):
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table diagnostic endpoint reached authority"
                )
            from app.services.presentation import build_canonical_presentation

            # Rebinding and diagnostic isolation consume the authoritative IR
            # before presentation.  Keep the public builder's independent
            # JSON projection and validation at this seam so a hostile or
            # accidentally mutated intermediate cannot gain presentation
            # authority.
            canonical = build_canonical_presentation(
                authoritative_ir
            ).model_dump(mode="json", exclude_none=True)
            del authoritative_ir
            try:
                canonical = _splice_terminal_table_canonical(
                    baseline,
                    candidate,
                    canonical,
                    transaction,
                    diagnostic_relationship_id_set,
                )
                canonical = _remove_terminal_diagnostic_canonical_edges(
                    canonical,
                    diagnostic_relationship_id_set,
                    candidate,
                    target_public_item_ids,
                )
            except (TypeError, ValueError) as exc:
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table canonical splice differs"
                ) from exc
            source_custody["canonical_presentation_sha256"] = (
                _canonical_presentation_sha256(canonical)
            )
            completed_custody = CanonicalSourceCustody.model_validate(
                source_custody
            )
            source_custody = completed_custody.model_dump(mode="json")
            candidate["canonical_presentation"] = canonical
            candidate["canonical_source_custody"] = source_custody
            try:
                validated = ParseResult.model_validate(
                    candidate,
                    context=_trusted_table_validation_context(
                        baseline_result,
                        completed_custody,
                    ),
                )
            except (TypeError, ValueError) as exc:
                raise OpaqueGroupCustodyIntegrityError(
                    "terminal table ParseResult closure differs"
                ) from exc
            return candidate, validated
        except (MemoryError, RecursionError) as exc:
            raise OpaqueGroupCustodyResourceError(
                "terminal table authority exhausted its resource envelope"
            ) from exc
        except (OpaqueGroupCustodyIntegrityError,
                OpaqueGroupCustodyResourceError,
                OpaqueGroupCustodyTimeoutError):
            raise
        except TimeoutError as exc:
            raise OpaqueGroupCustodyTimeoutError(
                "terminal table authority exceeded its deadline"
            ) from exc
        except Exception as exc:
            raise OpaqueGroupCustodyIntegrityError(
                "terminal table authority integration differs"
            ) from exc

    try:
        candidate, validated_result = _run_table_custody_document_segment(
            document_deadline,
            page_deadlines,
            state,
            commit,
        )
    except OpaqueGroupCustodyTimeoutError:
        state["timed_out"] = True
        state.pop("_p04_validated_parse_result", None)
        state["_p04_validated_parse_result"] = rollback_result
        return rollback_baseline
    except (OpaqueGroupCustodyIntegrityError, OpaqueGroupCustodyResourceError):
        state["custody_rejected"] = True
        state.pop("_p04_validated_parse_result", None)
        state["_p04_validated_parse_result"] = rollback_result
        return rollback_baseline
    state["_p04_validated_parse_result"] = validated_result
    return candidate


def _reference_map(raw: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    refs: dict[str, Mapping[str, Any]] = {}
    for collection in (
        "groups",
        "texts",
        "pictures",
        "tables",
        "key_value_items",
        "form_items",
    ):
        for item in raw.get(collection) or []:
            if isinstance(item, Mapping) and item.get("self_ref"):
                refs[str(item["self_ref"])] = item
    return refs


def _reference_value(value: Mapping[str, Any] | None) -> str:
    """Read either legacy ``cref`` or current JSON-Schema ``$ref`` links."""

    if not value:
        return ""
    return str(value.get("cref") or value.get("$ref") or "")


def _heading_level(value: str, raw_level: Any) -> int:
    number_match = _NUMBERED_HEADING_RE.match(value)
    if number_match:
        return min(number_match.group(1).count(".") + 1, 6)
    try:
        return min(max(int(raw_level or 1), 1), 6)
    except (TypeError, ValueError):
        return 1


def _text_item(
    raw_item: Mapping[str, Any],
    page_heights: Mapping[int, float],
    native_texts: Sequence[str],
) -> tuple[int, dict[str, Any]]:
    page_index, box = _bbox_from_prov(raw_item, page_heights)
    value = _WHITESPACE_RE.sub(" ", str(raw_item.get("text") or "")).strip()
    label = str(raw_item.get("label") or "text")
    source = (
        "native"
        if 0 < page_index <= len(native_texts)
        and _is_native(value, native_texts[page_index - 1])
        else "ocr"
    )

    if label in {"section_header", "title"} or (
        label == "text" and _PARENTHETICAL_HEADING_RE.match(value)
    ):
        item_type = "heading"
    elif label == "code":
        item_type = "code"
    elif label == "formula":
        item_type = "formula"
    else:
        item_type = "text"

    item: dict[str, Any] = {
        "type": item_type,
        "value": value,
        "md": value,
        "bbox": box,
        "source": source,
        "confidence": None,
        "label": label,
    }
    if item_type == "heading":
        item["level"] = _heading_level(value, raw_item.get("level"))
        item["md"] = f"{'#' * item['level']} {value}"
    if label == "checkbox_selected":
        item["value"] = f"[x] {value}".rstrip()
        item["md"] = item["value"]
    elif label == "checkbox_unselected":
        item["value"] = f"[ ] {value}".rstrip()
        item["md"] = item["value"]
    return page_index, item


_SOURCE_PROVEN_FUSED_TEXT_PARTITION_POLICY = (
    "source_proven_fused_text_partition_v1"
)
_SOURCE_PROVEN_FUSED_TEXT_MAX_CODEPOINTS = 16_384
_SOURCE_PROVEN_FUSED_TEXT_GEOMETRY_EPSILON = 0.5
_SOURCE_PROVEN_FUSED_TEXT_MAX_PAGES = 100
_SOURCE_PROVEN_FUSED_TEXT_MAX_RAW_REFERENCES = 512
_SOURCE_PROVEN_FUSED_TEXT_MAX_HEADING_CODEPOINTS = 2_048
_ANNOTATION_BACKED_TABLE_NOTE_PARTITION_POLICY = (
    "annotation_backed_cross_page_table_note_partition_v1"
)
_ANNOTATION_BACKED_VISUAL_NOTE_PARTITION_POLICY = (
    "annotation_backed_cross_page_visual_note_partition_v1"
)
_ANNOTATION_BACKED_TABLE_NOTE_MAX_GAP_PT = 72.0
_ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT = 0.1
_ANNOTATION_BACKED_NOTE_MIN_OVERLAP = 0.80


def _source_bbox_mapping(value: Any) -> dict[str, Any] | None:
    """Coerce one immutable source-evidence box without trusting duck types."""

    try:
        unit = getattr(value, "unit")
        result = {
            "x": float(getattr(value, "x")),
            "y": float(getattr(value, "y")),
            "width": float(getattr(value, "width")),
            "height": float(getattr(value, "height")),
            "unit": str(unit),
        }
    except (AttributeError, OverflowError, TypeError, ValueError):
        return None
    if (
        result["unit"] != "pt"
        or not all(
            math.isfinite(result[key])
            for key in ("x", "y", "width", "height")
        )
        or result["width"] <= 0
        or result["height"] <= 0
    ):
        return None
    return result


def _source_partition_skeleton(value: str) -> str:
    # Spacing and compatibility presentation may differ between the layout
    # contributor and the source line. Geometry, page identity, charspan
    # coverage, and unique source ownership remain mandatory as well.
    return "".join(
        character
        for character in unicodedata.normalize("NFC", value).casefold()
        if not character.isspace()
    )


def _source_partition_case_sensitive_skeleton(value: str) -> str:
    """Normalize source spacing without changing case-sensitive content."""

    return "".join(
        character
        for character in unicodedata.normalize("NFC", value)
        if not character.isspace()
    )


def _annotation_source_note_owner_contribution_matches(
    source_text: str,
    contribution: str,
    *,
    source_line_texts: Sequence[str],
) -> bool:
    """Match one owner with narrow one-way PDF typography compatibility."""

    source_skeleton = _source_partition_skeleton(source_text)
    contribution_skeleton = _source_partition_skeleton(contribution)
    if source_skeleton == contribution_skeleton:
        return True

    if (
        not isinstance(source_line_texts, Sequence)
        or isinstance(source_line_texts, (str, bytes, bytearray))
        or not source_line_texts
        or len(source_line_texts) > 10_000
        or any(not isinstance(line, str) for line in source_line_texts)
    ):
        return False

    line_skeletons = [
        _source_partition_skeleton(line) for line in source_line_texts
    ]
    removed_line_wrap_hyphen = False
    for line_index in range(len(line_skeletons) - 1):
        line = line_skeletons[line_index]
        next_line = line_skeletons[line_index + 1]
        if (
            len(line) >= 2
            and next_line
            and line.endswith("-")
            and line[-2].isalpha()
            and next_line[0].isalpha()
        ):
            line_skeletons[line_index] = line[:-1]
            removed_line_wrap_hyphen = True
    source_skeleton = "".join(line_skeletons)
    if len(source_skeleton) != len(contribution_skeleton):
        return False

    substituted_minus = False
    quote_depth = 0
    substituted_quote = False
    for source_character, contribution_character in zip(
        source_skeleton,
        contribution_skeleton,
        strict=True,
    ):
        if source_character == contribution_character:
            continue
        if (
            source_character == "\N{MINUS SIGN}"
            and contribution_character == "-"
        ):
            substituted_minus = True
            continue
        if (
            source_character == "\N{LEFT DOUBLE QUOTATION MARK}"
            and contribution_character == "'"
        ):
            quote_depth += 1
            substituted_quote = True
            continue
        if (
            source_character == "\N{RIGHT DOUBLE QUOTATION MARK}"
            and contribution_character == "'"
            and quote_depth > 0
        ):
            quote_depth -= 1
            substituted_quote = True
            continue
        return False
    return bool(
        quote_depth == 0
        and (
            removed_line_wrap_hyphen
            or substituted_minus
            or substituted_quote
        )
    )


def _box_fraction_inside(
    inner: Mapping[str, Any],
    outer: Mapping[str, Any],
) -> float:
    inner_area = _area(inner)
    return _intersection_area(inner, outer) / inner_area if inner_area else 0.0


def _source_lines_for_partition_box(
    source_page: Any,
    box: Mapping[str, Any],
) -> list[tuple[Any, dict[str, Any]]]:
    candidates: list[tuple[Any, dict[str, Any]]] = []
    lines = getattr(source_page, "lines", ())
    if (
        not isinstance(lines, Sequence)
        or isinstance(lines, (str, bytes, bytearray))
        or len(lines) > 10_000
    ):
        return []
    source_page_index = getattr(source_page, "page_index", None)
    if type(source_page_index) is not int or source_page_index < 1:
        return []
    for line_index in range(len(lines)):
        try:
            line = lines[line_index]
        except (IndexError, KeyError, TypeError):
            return []
        line_page_index = getattr(line, "page_index", None)
        if (
            type(line_page_index) is not int
            or line_page_index != source_page_index
        ):
            return []
        line_box = _source_bbox_mapping(getattr(line, "bbox", None))
        if line_box is None or _box_fraction_inside(line_box, box) < 0.75:
            continue
        line_text = getattr(line, "text", None)
        line_id = getattr(line, "id", None)
        if (
            not isinstance(line_text, str)
            or not line_text.strip()
            or not isinstance(line_id, str)
            or not line_id
        ):
            return []
        candidates.append((line, line_box))
    candidates.sort(
        key=lambda value: (
            float(value[1]["y"]),
            float(value[1]["x"]),
            str(getattr(value[0], "id", "")),
        )
    )
    return candidates


def _partition_mapping_box(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        result = {
            "x": float(value["x"]),
            "y": float(value["y"]),
            "width": float(value["width"]),
            "height": float(value["height"]),
            "unit": str(value["unit"]),
        }
    except (KeyError, OverflowError, TypeError, ValueError):
        return None
    if (
        result["unit"] != "pt"
        or not all(
            math.isfinite(result[key])
            for key in ("x", "y", "width", "height")
        )
        or result["width"] <= 0
        or result["height"] <= 0
    ):
        return None
    return result


def _partition_provenance_origin_is_supported(record: Any) -> bool:
    if not isinstance(record, Mapping):
        return False
    raw_box = record.get("bbox")
    return bool(
        isinstance(raw_box, Mapping)
        and raw_box.get("coord_origin") in {"TOPLEFT", "BOTTOMLEFT"}
    )


def _annotation_backed_source_note_partition(
    *,
    raw_item: Mapping[str, Any],
    raw_value: str,
    provenance_records: Sequence[Mapping[str, Any]],
    parsed: Sequence[tuple[int, int, int, dict[str, Any]]],
    page_heights: Mapping[int, float],
    native_texts: Sequence[str],
    source_text_evidence: Any,
    raw_reference_entries: Sequence[tuple[str, Mapping[str, Any]]],
    source_document_identity: str,
) -> list[tuple[int, dict[str, Any]]] | None:
    """Preserve one exact cross-page structured-owner note independently.

    This path is intentionally narrower than the ordinary same-page source
    partition.  It requires a unique source-visible PDF annotation and a
    unique bounded raw table or captioned visual owner on the contribution
    page. A failure at any layer leaves the original fused predecessor
    untouched.
    """

    if len(parsed) != 2 or len(provenance_records) != 2:
        return None
    if any(
        not _partition_provenance_origin_is_supported(record)
        for record in provenance_records
    ):
        return None
    owner_page = provenance_records[0].get("page_no")
    detached_page = provenance_records[1].get("page_no")
    if (
        type(owner_page) is not int
        or type(detached_page) is not int
        or detached_page != owner_page + 1
    ):
        return None

    source_sha256 = getattr(source_text_evidence, "source_sha256", None)
    raw_ref = raw_item.get("self_ref")
    if (
        not isinstance(raw_ref, str)
        or not raw_ref
        or not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        or source_sha256 != source_document_identity
    ):
        return None

    evidence_pages = getattr(source_text_evidence, "pages", ())
    if (
        not isinstance(evidence_pages, Sequence)
        or isinstance(evidence_pages, (str, bytes, bytearray))
        or len(evidence_pages) > _SOURCE_PROVEN_FUSED_TEXT_MAX_PAGES
    ):
        return None
    source_pages_by_index: dict[int, Any] = {}
    for page_offset in range(len(evidence_pages)):
        try:
            source_page = evidence_pages[page_offset]
        except (IndexError, KeyError, TypeError):
            return None
        page_index = getattr(source_page, "page_index", None)
        if (
            type(page_index) is not int
            or page_index < 1
            or page_index in source_pages_by_index
        ):
            return None
        source_pages_by_index[page_index] = source_page

    source_line_groups: list[list[tuple[Any, dict[str, Any]]]] = []
    lineage_groups: list[tuple[list[str], list[str]]] = []
    all_source_line_ids: set[str] = set()
    all_source_character_ids: set[str] = set()
    for contribution_index, (provenance_index, start, end, box) in enumerate(
        parsed
    ):
        page_index = provenance_records[provenance_index].get("page_no")
        if type(page_index) is not int:
            return None
        source_page = source_pages_by_index.get(page_index)
        if source_page is None:
            return None
        try:
            expected_height = float(page_heights[page_index])
            source_width = float(getattr(source_page, "page_width"))
            source_height = float(getattr(source_page, "page_height"))
        except (KeyError, TypeError, ValueError):
            return None
        if (
            getattr(source_page, "unit", None) != "pt"
            or not all(
                math.isfinite(value) and value > 0
                for value in (expected_height, source_width, source_height)
            )
            or abs(source_height - expected_height) > 0.05
            or float(box["x"]) < 0
            or float(box["y"]) < 0
            or float(box["x"]) + float(box["width"])
            > source_width + 0.05
            or float(box["y"]) + float(box["height"])
            > source_height + 0.05
        ):
            return None
        contribution = raw_value[start:end].strip()
        lines = _source_lines_for_partition_box(source_page, box)
        if any(
            float(line_box["x"])
            < -_ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT
            or float(line_box["y"])
            < -_ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT
            or float(line_box["x"]) + float(line_box["width"])
            > source_width + _ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT
            or float(line_box["y"]) + float(line_box["height"])
            > source_height + _ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT
            for _line, line_box in lines
        ):
            return None
        source_text = " ".join(
            str(getattr(line, "text", "")).strip()
            for line, _line_box in lines
        )
        source_matches = (
            _annotation_source_note_owner_contribution_matches(
                source_text,
                contribution,
                source_line_texts=[
                    str(getattr(line, "text", ""))
                    for line, _line_box in lines
                ],
            )
            if contribution_index == 0
            else _source_partition_case_sensitive_skeleton(source_text)
            == _source_partition_case_sensitive_skeleton(contribution)
        )
        if (
            not contribution
            or not lines
            or not source_matches
        ):
            return None
        line_ids: list[str] = []
        character_ids: list[str] = []
        for line, _line_box in lines:
            line_id = getattr(line, "id", None)
            raw_character_ids = getattr(line, "source_character_ids", None)
            if (
                not isinstance(line_id, str)
                or not line_id
                or line_id in all_source_line_ids
                or not isinstance(raw_character_ids, Sequence)
                or isinstance(raw_character_ids, (str, bytes, bytearray))
                or not raw_character_ids
                or len(raw_character_ids)
                > _SOURCE_PROVEN_FUSED_TEXT_MAX_CODEPOINTS
            ):
                return None
            try:
                bounded_character_ids = [
                    raw_character_ids[index]
                    for index in range(len(raw_character_ids))
                ]
            except (IndexError, KeyError, TypeError):
                return None
            if (
                any(
                    not isinstance(character_id, str) or not character_id
                    for character_id in bounded_character_ids
                )
                or len(set(bounded_character_ids))
                != len(bounded_character_ids)
                or any(
                    character_id in all_source_character_ids
                    for character_id in bounded_character_ids
                )
                or len(all_source_character_ids) + len(bounded_character_ids)
                > _SOURCE_PROVEN_FUSED_TEXT_MAX_CODEPOINTS
            ):
                return None
            all_source_line_ids.add(line_id)
            all_source_character_ids.update(bounded_character_ids)
            line_ids.append(line_id)
            character_ids.extend(bounded_character_ids)
        source_line_groups.append(lines)
        lineage_groups.append((line_ids, character_ids))

    if len(source_line_groups[1]) != 1:
        return None
    _detached_line, detached_source_box = source_line_groups[1][0]
    detached_box = parsed[1][3]
    if (
        _box_fraction_inside(detached_source_box, detached_box) < 0.75
        or _box_fraction_inside(detached_box, detached_source_box) < 0.75
    ):
        return None
    detached_value = raw_value[parsed[1][1] : parsed[1][2]].strip()

    try:
        from app.services.layout_source_notes import (
            safe_http_annotation_target,
        )
    except ImportError:
        return None

    annotation_matches: list[
        tuple[
            str,
            Mapping[str, Any],
            dict[str, Any],
            dict[str, Any],
        ]
    ] = []
    for reference, candidate in raw_reference_entries:
        if candidate is raw_item or reference == raw_ref:
            continue
        if (
            candidate.get("self_ref") != reference
            or str(candidate.get("label") or "").casefold() != "annotation"
        ):
            continue
        candidate_text = candidate.get("text")
        if (
            candidate.get("source") != "native"
            or candidate.get("evidence_methods") != ["native"]
            or not isinstance(candidate_text, str)
            or candidate_text != detached_value
            or candidate.get("hyperlink") != detached_value
            or safe_http_annotation_target(candidate.get("hyperlink"))
            != detached_value
        ):
            continue
        candidate_provenance = candidate.get("prov")
        annotation_charspan = (
            candidate_provenance[0].get("charspan")
            if isinstance(candidate_provenance, Sequence)
            and not isinstance(candidate_provenance, (str, bytes, bytearray))
            and len(candidate_provenance) == 1
            and isinstance(candidate_provenance[0], Mapping)
            else None
        )
        if (
            not isinstance(candidate_provenance, Sequence)
            or isinstance(candidate_provenance, (str, bytes, bytearray))
            or len(candidate_provenance) != 1
            or not isinstance(candidate_provenance[0], Mapping)
            or not _partition_provenance_origin_is_supported(
                candidate_provenance[0]
            )
            or type(candidate_provenance[0].get("page_no")) is not int
            or candidate_provenance[0].get("page_no") != detached_page
            or type(annotation_charspan) is not list
            or len(annotation_charspan) != 2
            or any(type(offset) is not int for offset in annotation_charspan)
            or annotation_charspan != [0, len(candidate_text)]
        ):
            continue
        annotation_page, annotation_box = _bbox_from_prov(
            candidate,
            page_heights,
        )
        raw_meta = candidate.get("meta")
        marker = (
            raw_meta.get("layout_source_note_pdf_annotation")
            if isinstance(raw_meta, Mapping)
            else None
        )
        marker_box = (
            _partition_mapping_box(marker.get("bbox"))
            if isinstance(marker, Mapping)
            else None
        )
        if (
            annotation_page != detached_page
            or annotation_box is None
            or annotation_box.get("unit") != "pt"
            or not isinstance(marker, Mapping)
            or marker.get("source_visible") is not True
            or marker_box is None
            or any(
                abs(float(marker_box[key]) - float(annotation_box[key]))
                > _ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT
                for key in ("x", "y", "width", "height")
            )
            or _box_fraction_inside(detached_box, annotation_box)
            < _ANNOTATION_BACKED_NOTE_MIN_OVERLAP
            or _box_fraction_inside(annotation_box, detached_box)
            < _ANNOTATION_BACKED_NOTE_MIN_OVERLAP
        ):
            continue
        annotation_matches.append(
            (reference, candidate, annotation_box, marker_box)
        )
    if len(annotation_matches) != 1:
        return None
    annotation_ref, _annotation, annotation_box, marker_box = (
        annotation_matches[0]
    )

    from app.services.ir import _validated_raw_table_grid_topology

    raw_references_by_id = dict(raw_reference_entries)
    detached_source_page = source_pages_by_index.get(detached_page)
    try:
        detached_page_width = float(
            getattr(detached_source_page, "page_width")
        )
        detached_page_height = float(
            getattr(detached_source_page, "page_height")
        )
    except (AttributeError, OverflowError, TypeError, ValueError):
        return None
    if not all(
        math.isfinite(value) and value > 0
        for value in (detached_page_width, detached_page_height)
    ):
        return None

    def box_is_on_detached_page(box: Mapping[str, Any]) -> bool:
        try:
            x = float(box["x"])
            y = float(box["y"])
            width = float(box["width"])
            height = float(box["height"])
        except (KeyError, OverflowError, TypeError, ValueError):
            return False
        return bool(
            all(math.isfinite(value) for value in (x, y, width, height))
            and width > 0
            and height > 0
            and x >= -_ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT
            and y >= -_ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT
            and x + width
            <= detached_page_width
            + _ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT
            and y + height
            <= detached_page_height
            + _ANNOTATION_BACKED_TABLE_NOTE_BBOX_EPSILON_PT
        )

    if not box_is_on_detached_page(
        annotation_box
    ) or not box_is_on_detached_page(marker_box):
        return None

    owner_matches: list[
        tuple[str, Mapping[str, Any], str, str | None]
    ] = []
    for reference, candidate in raw_reference_entries:
        candidate_label = str(candidate.get("label") or "").casefold()
        caption_ref: str | None = None
        if (
            reference.startswith("#/tables/")
            and candidate.get("self_ref") == reference
            and candidate_label == "table"
            and _validated_raw_table_grid_topology(candidate) is not None
        ):
            candidate_owner_kind = "table"
        elif (
            reference.startswith("#/pictures/")
            and candidate.get("self_ref") == reference
            and candidate_label in {"picture", "image", "chart", "diagram"}
        ):
            candidate_owner_kind = "visual"
            caption_claims = candidate.get("captions")
            if (
                type(caption_claims) is not list
                or len(caption_claims) != 1
                or not isinstance(caption_claims[0], Mapping)
            ):
                continue
            raw_caption_ref = caption_claims[0].get("$ref")
            caption = raw_references_by_id.get(raw_caption_ref)
            caption_provenance = (
                caption.get("prov") if isinstance(caption, Mapping) else None
            )
            caption_text = (
                caption.get("text") if isinstance(caption, Mapping) else None
            )
            if (
                not isinstance(raw_caption_ref, str)
                or not raw_caption_ref.startswith("#/texts/")
                or not isinstance(caption, Mapping)
                or caption.get("self_ref") != raw_caption_ref
                or str(caption.get("label") or "").casefold() != "caption"
                or not isinstance(caption_text, str)
                or not caption_text.strip()
                or len(caption_text) > 2_048
                or not isinstance(caption_provenance, Sequence)
                or isinstance(caption_provenance, (str, bytes, bytearray))
                or len(caption_provenance) != 1
                or not isinstance(caption_provenance[0], Mapping)
                or not _partition_provenance_origin_is_supported(
                    caption_provenance[0]
                )
                or type(caption_provenance[0].get("page_no")) is not int
                or caption_provenance[0].get("page_no") != detached_page
            ):
                continue
            caption_ref = raw_caption_ref
        else:
            continue
        candidate_provenance = candidate.get("prov")
        if (
            not isinstance(candidate_provenance, Sequence)
            or isinstance(candidate_provenance, (str, bytes, bytearray))
            or len(candidate_provenance) != 1
            or not isinstance(candidate_provenance[0], Mapping)
            or not _partition_provenance_origin_is_supported(
                candidate_provenance[0]
            )
            or type(candidate_provenance[0].get("page_no")) is not int
            or candidate_provenance[0].get("page_no") != detached_page
        ):
            continue
        owner_page, owner_box = _bbox_from_prov(candidate, page_heights)
        if (
            owner_page != detached_page
            or owner_box is None
            or not box_is_on_detached_page(owner_box)
        ):
            continue
        owner_bottom = float(owner_box["y"]) + float(owner_box["height"])
        horizontal_width = max(
            min(
                float(annotation_box["x"])
                + float(annotation_box["width"]),
                float(owner_box["x"]) + float(owner_box["width"]),
            )
            - max(
                float(annotation_box["x"]),
                float(owner_box["x"]),
            ),
            0.0,
        )
        horizontal_overlap = horizontal_width / max(
            min(
                float(annotation_box["width"]),
                float(owner_box["width"]),
            ),
            1e-9,
        )
        gap = float(annotation_box["y"]) - owner_bottom
        if (
            _intersection_area(annotation_box, owner_box) > 0
            or gap < 0
            or gap > _ANNOTATION_BACKED_TABLE_NOTE_MAX_GAP_PT
            or horizontal_overlap < 0.20
        ):
            continue
        if candidate_owner_kind == "visual":
            assert caption_ref is not None
            caption = raw_references_by_id[caption_ref]
            caption_page, caption_box = _bbox_from_prov(
                caption,
                page_heights,
            )
            if (
                caption_page != detached_page
                or caption_box is None
                or not box_is_on_detached_page(caption_box)
            ):
                continue
            caption_horizontal_width = max(
                min(
                    float(caption_box["x"]) + float(caption_box["width"]),
                    float(owner_box["x"]) + float(owner_box["width"]),
                )
                - max(float(caption_box["x"]), float(owner_box["x"])),
                0.0,
            )
            caption_horizontal_overlap = caption_horizontal_width / max(
                min(
                    float(caption_box["width"]),
                    float(owner_box["width"]),
                ),
                1e-9,
            )
            caption_above_gap = float(owner_box["y"]) - (
                float(caption_box["y"]) + float(caption_box["height"])
            )
            caption_below_gap = float(caption_box["y"]) - owner_bottom
            caption_gap = max(caption_above_gap, caption_below_gap)
            if (
                _intersection_area(caption_box, owner_box) > 0
                or _intersection_area(caption_box, annotation_box) > 0
                or caption_gap < 0
                or caption_gap > _ANNOTATION_BACKED_TABLE_NOTE_MAX_GAP_PT
                or caption_horizontal_overlap < 0.20
            ):
                continue
        owner_matches.append(
            (reference, candidate, candidate_owner_kind, caption_ref)
        )
    if len(owner_matches) != 1:
        return None
    owner_ref, _owner, owner_kind, owner_caption_ref = owner_matches[0]

    if owner_kind == "table":
        partition_policy = _ANNOTATION_BACKED_TABLE_NOTE_PARTITION_POLICY
        detached_role = "detached_table_note"
        owner_reference_field = "table_raw_ref"
    else:
        partition_policy = _ANNOTATION_BACKED_VISUAL_NOTE_PARTITION_POLICY
        detached_role = "detached_visual_note"
        owner_reference_field = "visual_raw_ref"

    results: list[tuple[int, dict[str, Any]]] = []
    roles = ("retained_owner", detached_role)
    for contribution_index, (
        provenance_index,
        start,
        end,
        _box,
    ) in enumerate(parsed):
        selected_text = raw_value[start:end].strip()
        partitioned_raw = dict(raw_item)
        partitioned_raw["text"] = selected_text
        partitioned_raw["orig"] = selected_text
        partitioned_raw["prov"] = [
            deepcopy(provenance_records[provenance_index])
        ]
        normalized_page, item = _text_item(
            partitioned_raw,
            page_heights,
            native_texts,
        )
        if contribution_index == 1:
            item["type"] = "footnote"
            item["md"] = selected_text
            item["links"] = [
                {"kind": "hyperlink", "target": detached_value}
            ]
        source_line_ids, source_character_ids = lineage_groups[
            contribution_index
        ]
        item["source_partition"] = {
            "policy": partition_policy,
            "role": roles[contribution_index],
            "raw_ref": raw_ref,
            "provenance_index": provenance_index,
            "charspan": [start, end],
            "source_line_ids": source_line_ids,
            "source_character_ids": source_character_ids,
            "source_sha256": source_sha256,
            "annotation_raw_ref": annotation_ref,
            owner_reference_field: owner_ref,
        }
        if owner_caption_ref is not None:
            item["source_partition"]["caption_raw_ref"] = owner_caption_ref
        results.append((normalized_page, item))
    return results


def _partition_source_proven_text_item(
    raw_item: Mapping[str, Any],
    page_heights: Mapping[int, float],
    native_texts: Sequence[str],
    source_text_evidence: Any | None,
    *,
    coordinate_unit: str,
    raw_references: Mapping[str, Mapping[str, Any]] | None = None,
    source_document_identity: str | None = None,
) -> list[tuple[int, dict[str, Any]]]:
    """Partition one erroneously fused raw text node when source proof is exact.

    The first provenance record remains the canonical layout owner. Exactly
    one later, same-page contribution may become an independent public item
    only when complete charspans, disjoint columns, and unique native source
    lines all agree. Every malformed or ambiguous case returns the unchanged
    normalized predecessor.
    """

    predecessor = [_text_item(raw_item, page_heights, native_texts)]
    raw_value = raw_item.get("text")
    provenance = raw_item.get("prov")
    if (
        coordinate_unit != "pt"
        or source_text_evidence is None
        or getattr(source_text_evidence, "usable", False) is not True
        or not isinstance(raw_value, str)
        or not raw_value.strip()
        or len(raw_value) > _SOURCE_PROVEN_FUSED_TEXT_MAX_CODEPOINTS
        or not isinstance(provenance, Sequence)
        or isinstance(provenance, (str, bytes, bytearray))
        or len(provenance) != 2
        or not isinstance(raw_references, Mapping)
        or not isinstance(source_document_identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_document_identity) is None
    ):
        return predecessor
    try:
        raw_reference_count = len(raw_references)
    except (OverflowError, TypeError, ValueError):
        return predecessor
    if raw_reference_count > _SOURCE_PROVEN_FUSED_TEXT_MAX_RAW_REFERENCES:
        return predecessor
    raw_reference_entries: list[tuple[str, Mapping[str, Any]]] = []
    try:
        for entry_index, entry in enumerate(raw_references.items()):
            if entry_index >= _SOURCE_PROVEN_FUSED_TEXT_MAX_RAW_REFERENCES:
                return predecessor
            reference, candidate = entry
            if (
                not isinstance(reference, str)
                or not reference
                or not isinstance(candidate, Mapping)
            ):
                return predecessor
            raw_reference_entries.append((reference, candidate))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return predecessor
    if len(raw_reference_entries) != raw_reference_count:
        return predecessor

    try:
        provenance_records = [provenance[index] for index in range(2)]
    except (IndexError, KeyError, TypeError):
        return predecessor

    parsed: list[tuple[int, int, int, dict[str, Any]]] = []
    for provenance_index, record in enumerate(provenance_records):
        if not isinstance(record, Mapping):
            return predecessor
        charspan = record.get("charspan")
        if (
            not isinstance(charspan, Sequence)
            or isinstance(charspan, (str, bytes, bytearray))
            or len(charspan) != 2
            or any(
                not isinstance(offset, int) or isinstance(offset, bool)
                for offset in charspan
            )
        ):
            return predecessor
        start, end = charspan
        if not 0 <= start < end <= len(raw_value):
            return predecessor
        raw_page_index = record.get("page_no")
        if type(raw_page_index) is not int or raw_page_index < 1:
            return predecessor
        page_index = raw_page_index
        try:
            raw_page_height = float(page_heights[page_index])
        except (KeyError, TypeError, ValueError):
            return predecessor
        if not math.isfinite(raw_page_height) or raw_page_height <= 0:
            return predecessor
        record_page, record_box = _bbox_from_prov(
            {"prov": [record]},
            page_heights,
        )
        if (
            record_page != page_index
            or record_box is None
            or record_box.get("unit") != coordinate_unit
            or not all(
                math.isfinite(float(record_box[field]))
                for field in ("x", "y", "width", "height")
            )
            or float(record_box["width"]) <= 0
            or float(record_box["height"]) <= 0
        ):
            return predecessor
        parsed.append((provenance_index, start, end, record_box))

    if (
        parsed[0][1] != 0
        or parsed[0][2] > parsed[1][1]
        or raw_value[parsed[0][2] : parsed[1][1]].strip()
        or raw_value[parsed[1][2] :].strip()
    ):
        return predecessor

    try:
        annotation_backed_partition = _annotation_backed_source_note_partition(
            raw_item=raw_item,
            raw_value=raw_value,
            provenance_records=provenance_records,
            parsed=parsed,
            page_heights=page_heights,
            native_texts=native_texts,
            source_text_evidence=source_text_evidence,
            raw_reference_entries=raw_reference_entries,
            source_document_identity=source_document_identity,
        )
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return predecessor
    if annotation_backed_partition is not None:
        return annotation_backed_partition

    page_indexes = {record["page_no"] for record in provenance_records}
    if len(page_indexes) != 1:
        return predecessor
    page_index = next(iter(page_indexes))

    evidence_pages = getattr(source_text_evidence, "pages", ())
    if (
        not isinstance(evidence_pages, Sequence)
        or isinstance(evidence_pages, (str, bytes, bytearray))
        or len(evidence_pages) > _SOURCE_PROVEN_FUSED_TEXT_MAX_PAGES
    ):
        return predecessor
    source_pages: list[Any] = []
    for source_page_index in range(len(evidence_pages)):
        try:
            source_page_candidate = evidence_pages[source_page_index]
        except (IndexError, KeyError, TypeError):
            return predecessor
        source_page_identity = getattr(
            source_page_candidate,
            "page_index",
            None,
        )
        if type(source_page_identity) is not int or source_page_identity < 1:
            return predecessor
        if source_page_identity == page_index:
            source_pages.append(source_page_candidate)
    if len(source_pages) != 1:
        return predecessor
    source_page = source_pages[0]
    try:
        expected_height = float(page_heights[page_index])
        source_height = float(getattr(source_page, "page_height"))
        source_width = float(getattr(source_page, "page_width"))
    except (KeyError, TypeError, ValueError):
        return predecessor
    if (
        getattr(source_page, "unit", None) != coordinate_unit
        or not math.isfinite(source_width)
        or source_width <= 0
        or not math.isfinite(source_height)
        or source_height <= 0
        or not math.isfinite(expected_height)
        or expected_height <= 0
        or abs(source_height - expected_height) > 0.05
    ):
        return predecessor

    owner_box = parsed[0][3]
    detached_box = parsed[1][3]

    # The detached contributor must be the unique label immediately above a
    # source graph heading in the same column. This prevents an ordinary
    # two-column paragraph continuation from being split merely because both
    # provenance boxes are valid.
    heading_anchors: list[tuple[str, dict[str, Any]]] = []
    for reference, candidate in raw_reference_entries:
        if candidate is raw_item or reference == raw_item.get("self_ref"):
            continue
        if str(candidate.get("label") or "").casefold() not in {
            "title",
            "section_header",
        }:
            continue
        candidate_text = candidate.get("text")
        if (
            not isinstance(candidate_text, str)
            or not candidate_text.strip()
            or len(candidate_text)
            > _SOURCE_PROVEN_FUSED_TEXT_MAX_HEADING_CODEPOINTS
        ):
            continue
        candidate_provenance = candidate.get("prov")
        if (
            not isinstance(candidate_provenance, Sequence)
            or isinstance(candidate_provenance, (str, bytes, bytearray))
            or len(candidate_provenance) != 1
            or not isinstance(candidate_provenance[0], Mapping)
        ):
            continue
        anchor_page_identity = candidate_provenance[0].get("page_no")
        if type(anchor_page_identity) is not int or anchor_page_identity < 1:
            continue
        anchor_page, anchor_box = _bbox_from_prov(candidate, page_heights)
        if anchor_page != page_index or anchor_box is None:
            continue
        horizontal_overlap = max(
            min(
                float(detached_box["x"]) + float(detached_box["width"]),
                float(anchor_box["x"]) + float(anchor_box["width"]),
            )
            - max(float(detached_box["x"]), float(anchor_box["x"])),
            0.0,
        ) / max(float(detached_box["width"]), 1e-9)
        vertical_gap = float(anchor_box["y"]) - (
            float(detached_box["y"]) + float(detached_box["height"])
        )
        if (
            horizontal_overlap >= 0.70
            and -_SOURCE_PROVEN_FUSED_TEXT_GEOMETRY_EPSILON <= vertical_gap
            <= max(24.0, float(detached_box["height"]) * 4.0)
            and float(anchor_box["width"])
            >= float(detached_box["width"]) * 0.90
        ):
            heading_anchors.append((str(reference), anchor_box))
    if len(heading_anchors) != 1:
        return predecessor
    heading_anchor_ref, heading_anchor_box = heading_anchors[0]

    for reference, candidate in raw_reference_entries:
        if reference in {raw_item.get("self_ref"), heading_anchor_ref}:
            continue
        if not isinstance(candidate, Mapping) or not str(
            candidate.get("text") or ""
        ).strip():
            continue
        candidate_page, candidate_box = _bbox_from_prov(candidate, page_heights)
        if candidate_page != page_index or candidate_box is None:
            continue
        between_overlap = max(
            min(
                float(detached_box["x"]) + float(detached_box["width"]),
                float(candidate_box["x"]) + float(candidate_box["width"]),
            )
            - max(float(detached_box["x"]), float(candidate_box["x"])),
            0.0,
        ) / max(float(detached_box["width"]), 1e-9)
        if (
            _overlap_of_smaller(candidate_box, detached_box) >= 0.50
            or (
            between_overlap >= 0.70
            and float(candidate_box["y"])
            >= float(detached_box["y"])
            + float(detached_box["height"])
            - _SOURCE_PROVEN_FUSED_TEXT_GEOMETRY_EPSILON
            and float(candidate_box["y"])
            < float(heading_anchor_box["y"])
            - _SOURCE_PROVEN_FUSED_TEXT_GEOMETRY_EPSILON
            )
        ):
            return predecessor

    if (
        _intersection_area(owner_box, detached_box) > 0
        or _vertical_overlap_of_smaller(owner_box, detached_box) > 0
        or (
            max(
                min(
                    float(owner_box["x"]) + float(owner_box["width"]),
                    float(detached_box["x"]) + float(detached_box["width"]),
                )
                - max(
                    float(owner_box["x"]),
                    float(detached_box["x"]),
                ),
                0.0,
            )
            / max(
                min(
                    float(owner_box["width"]),
                    float(detached_box["width"]),
                ),
                1e-9,
            )
            >= 0.10
        )
        or any(
            float(box[key]) < 0
            for box in (owner_box, detached_box)
            for key in ("x", "y")
        )
        or any(
            float(box["x"]) + float(box["width"]) > source_width + 0.05
            or float(box["y"]) + float(box["height"]) > source_height + 0.05
            for box in (owner_box, detached_box)
        )
    ):
        return predecessor

    source_line_groups: list[list[tuple[Any, dict[str, Any]]]] = []
    for _provenance_index, start, end, box in parsed:
        contribution = raw_value[start:end].strip()
        lines = _source_lines_for_partition_box(source_page, box)
        source_text = " ".join(
            str(getattr(line, "text", "")).strip()
            for line, _line_box in lines
        )
        if (
            not contribution
            or not lines
            or _source_partition_skeleton(source_text)
            != _source_partition_skeleton(contribution)
        ):
            return predecessor
        source_line_groups.append(lines)

    # A detached contribution is one source line, not an arbitrary aggregate
    # from a second paragraph or column. Repeated/overlapping candidates make
    # ownership ambiguous and preserve the fused predecessor.
    if len(source_line_groups[1]) != 1:
        return predecessor
    _detached_line, detached_source_box = source_line_groups[1][0]
    if (
        _box_fraction_inside(detached_source_box, detached_box) < 0.75
        or _box_fraction_inside(detached_box, detached_source_box) < 0.75
    ):
        return predecessor

    lineage_groups: list[tuple[list[str], list[str]]] = []
    all_source_line_ids: set[str] = set()
    all_source_character_ids: set[str] = set()
    for lines in source_line_groups:
        line_ids: list[str] = []
        character_ids: list[str] = []
        for line, _line_box in lines:
            line_id = getattr(line, "id", None)
            raw_character_ids = getattr(
                line,
                "source_character_ids",
                None,
            )
            if (
                not isinstance(line_id, str)
                or not line_id
                or line_id in all_source_line_ids
                or not isinstance(raw_character_ids, Sequence)
                or isinstance(
                    raw_character_ids,
                    (str, bytes, bytearray),
                )
                or not raw_character_ids
                or len(raw_character_ids)
                > _SOURCE_PROVEN_FUSED_TEXT_MAX_CODEPOINTS
            ):
                return predecessor
            bounded_character_ids: list[Any] = []
            try:
                for character_index in range(len(raw_character_ids)):
                    bounded_character_ids.append(
                        raw_character_ids[character_index]
                    )
            except (IndexError, KeyError, TypeError):
                return predecessor
            if (
                any(
                    not isinstance(character_id, str)
                    or not character_id
                    for character_id in bounded_character_ids
                )
                or len(set(bounded_character_ids))
                != len(bounded_character_ids)
                or any(
                    character_id in all_source_character_ids
                    for character_id in bounded_character_ids
                )
                or len(all_source_character_ids)
                + len(bounded_character_ids)
                > _SOURCE_PROVEN_FUSED_TEXT_MAX_CODEPOINTS
            ):
                return predecessor
            all_source_line_ids.add(line_id)
            all_source_character_ids.update(bounded_character_ids)
            line_ids.append(line_id)
            character_ids.extend(bounded_character_ids)
        lineage_groups.append((line_ids, character_ids))

    raw_ref = raw_item.get("self_ref")
    source_sha256 = getattr(source_text_evidence, "source_sha256", None)
    if (
        not isinstance(raw_ref, str)
        or not raw_ref
        or not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        or source_sha256 != source_document_identity
    ):
        return predecessor

    results: list[tuple[int, dict[str, Any]]] = []
    roles = ("retained_owner", "detached_contributor")
    for contribution_index, (
        provenance_index,
        start,
        end,
        _box_value,
    ) in enumerate(parsed):
        lines = source_line_groups[contribution_index]
        selected_text = (
            raw_value[start:end].strip()
            if contribution_index == 0
            else " ".join(
                str(getattr(line, "text", "")).strip()
                for line, _line_box in lines
            )
        )
        partitioned_raw = dict(raw_item)
        partitioned_raw["text"] = selected_text
        partitioned_raw["orig"] = selected_text
        partitioned_raw["prov"] = [
            deepcopy(provenance_records[provenance_index])
        ]
        normalized_page, item = _text_item(
            partitioned_raw,
            page_heights,
            native_texts,
        )
        source_line_ids, source_character_ids = lineage_groups[
            contribution_index
        ]
        item["source_partition"] = {
            "policy": _SOURCE_PROVEN_FUSED_TEXT_PARTITION_POLICY,
            "role": roles[contribution_index],
            "raw_ref": raw_ref,
            "provenance_index": provenance_index,
            "charspan": [start, end],
            "source_line_ids": source_line_ids,
            "source_character_ids": source_character_ids,
            "source_sha256": source_sha256,
            "heading_anchor_raw_ref": heading_anchor_ref,
        }
        results.append((normalized_page, item))
    return results


def _graph_item(
    raw_item: Mapping[str, Any],
    page_heights: Mapping[int, float],
    native_texts: Sequence[str],
) -> tuple[int, dict[str, Any]]:
    """Normalize Docling's explicit form/key-value graph without inference."""

    page_index, item_box = _bbox_from_prov(raw_item, page_heights)
    graph = raw_item.get("graph") or {}
    raw_cells = [
        cell for cell in (graph.get("cells") or []) if isinstance(cell, Mapping)
    ]
    cells: list[dict[str, Any]] = []
    cells_by_id: dict[int, dict[str, Any]] = {}
    for raw_cell in raw_cells:
        try:
            cell_id = int(raw_cell["cell_id"])
        except (KeyError, TypeError, ValueError):
            continue
        cell_page, cell_box = _bbox_from_prov(raw_cell, page_heights)
        if not raw_item.get("prov") and cell_box is not None:
            page_index = cell_page
        text = _WHITESPACE_RE.sub(
            " ",
            str(raw_cell.get("text") or raw_cell.get("orig") or ""),
        ).strip()
        source = (
            "native"
            if 0 < cell_page <= len(native_texts)
            and _is_native(text, native_texts[cell_page - 1])
            else "ocr"
        )
        cell: dict[str, Any] = {
            "cell_id": cell_id,
            "label": str(raw_cell.get("label") or "unspecified"),
            "text": text,
            "original_text": str(raw_cell.get("orig") or ""),
            "bbox": cell_box,
            "source": source,
            "confidence": None,
        }
        item_ref = raw_cell.get("item_ref")
        if item_ref:
            cell["item_ref"] = item_ref
        cells.append(cell)
        cells_by_id[cell_id] = cell

    links: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    linked_cell_ids: set[int] = set()
    parse_concerns: list[str] = []
    seen_field_pairs: set[tuple[int, int]] = set()
    for raw_link in graph.get("links") or []:
        if not isinstance(raw_link, Mapping):
            continue
        try:
            source_id = int(raw_link["source_cell_id"])
            target_id = int(raw_link["target_cell_id"])
        except (KeyError, TypeError, ValueError):
            parse_concerns.append("invalid_form_graph_link")
            continue
        link = {
            "label": str(raw_link.get("label") or "unspecified"),
            "source_cell_id": source_id,
            "target_cell_id": target_id,
        }
        links.append(link)
        source_cell = cells_by_id.get(source_id)
        target_cell = cells_by_id.get(target_id)
        if source_cell is None or target_cell is None:
            parse_concerns.append("unresolved_form_graph_link")
            continue

        key_cell: dict[str, Any] | None = None
        value_cell: dict[str, Any] | None = None
        if source_cell["label"] == "key" and target_cell["label"] != "key":
            key_cell, value_cell = source_cell, target_cell
        elif target_cell["label"] == "key" and source_cell["label"] != "key":
            key_cell, value_cell = target_cell, source_cell
        if key_cell is None or value_cell is None:
            continue

        pair = (int(key_cell["cell_id"]), int(value_cell["cell_id"]))
        if pair in seen_field_pairs:
            continue
        seen_field_pairs.add(pair)
        linked_cell_ids.update(pair)
        fields.append(
            {
                "key": key_cell["text"],
                "value": value_cell["text"],
                "key_cell_id": pair[0],
                "value_cell_id": pair[1],
                "relation": link["label"],
            }
        )

    unlinked_cells = [
        cell
        for cell in cells
        if int(cell["cell_id"]) not in linked_cell_ids and cell["text"]
    ]
    markdown_lines = [
        (
            f"**{field['key']}:** {field['value']}".rstrip()
            if field["key"]
            else str(field["value"])
        )
        for field in fields
        if field["key"] or field["value"]
    ]
    markdown_lines.extend(str(cell["text"]) for cell in unlinked_cells)
    item_type = (
        "form"
        if str(raw_item.get("label") or "") == "form"
        or str(raw_item.get("self_ref") or "").startswith("#/form_items/")
        else "key_value"
    )
    sources = {str(cell.get("source") or "") for cell in cells}
    source = (
        next(iter(sources)) if len(sources) == 1 else "mixed" if sources else "derived"
    )
    value: dict[str, Any] = {
        "fields": fields,
        "unlinked_cells": [
            {
                "cell_id": cell["cell_id"],
                "label": cell["label"],
                "text": cell["text"],
            }
            for cell in unlinked_cells
        ],
    }
    item = {
        "type": item_type,
        "value": value,
        "md": "\n\n".join(markdown_lines),
        "bbox": item_box or _bbox_union(cell.get("bbox") for cell in cells),
        "source": source,
        "confidence": None,
        "label": str(raw_item.get("label") or item_type),
        "cells": cells,
        "links": links,
        "fields": fields,
        "parse_concerns": list(dict.fromkeys(parse_concerns)),
    }
    return page_index, item


def _cell_bbox(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        left = float(raw["l"])
        top = float(raw["t"])
        right = float(raw["r"])
        bottom = float(raw["b"])
    except (KeyError, TypeError, ValueError):
        return None
    return _bbox(left, top, right - left, bottom - top)


def _word_bbox(words: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    boxes: list[dict[str, Any]] = []
    for word in words:
        try:
            left = float(word["x0"])
            top = float(word["top"])
            right = float(word["x1"])
            bottom = float(word["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        boxes.append(_bbox(left, top, right - left, bottom - top))
    return _bbox_union(boxes)


def _words_text(words: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        words,
        key=lambda word: (
            float(word.get("top", 0.0)),
            float(word.get("x0", 0.0)),
        ),
    )
    return " ".join(
        str(word.get("text") or "").strip()
        for word in ordered
        if str(word.get("text") or "").strip()
    )


def _words_inside_bbox(
    words: Sequence[Mapping[str, Any]],
    box: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    left = float(box["x"])
    top = float(box["y"])
    right = left + float(box["width"])
    bottom = top + float(box["height"])
    return [
        word
        for word in words
        if (
            left
            <= (float(word.get("x0", 0.0)) + float(word.get("x1", 0.0))) / 2
            <= right
            and top
            <= (float(word.get("top", 0.0)) + float(word.get("bottom", 0.0))) / 2
            <= bottom
        )
    ]


def _split_mixed_header_body_row(
    rows: list[list[str]],
    cells: list[dict[str, Any]],
    row_index: int,
    page_words: Sequence[Mapping[str, Any]],
) -> bool:
    """Split a header cell that geometrically absorbs the first body row.

    Some borderless tables place their final header line very close to the
    first data row. Layout models can then return one mixed row: a body label
    beside cells containing both column headers and first-row values. The
    body-label geometry supplies the split boundary, so this repair does not
    depend on dates, currencies, or document-specific wording.
    """

    indexed_row_cells = [
        (cell_index, cell)
        for cell_index, cell in enumerate(cells)
        if int(cell.get("row", 0)) == row_index
    ]
    header_cells = [
        (cell_index, cell)
        for cell_index, cell in indexed_row_cells
        if cell.get("column_header")
    ]
    body_cells = [
        cell for _, cell in indexed_row_cells if not cell.get("column_header")
    ]
    body_boxes = [cell.get("bbox") for cell in body_cells if cell.get("bbox")]
    if not header_cells or not body_cells or not body_boxes or not page_words:
        return False
    if any(max(int(cell.get("row_span", 1)), 1) != 1 for _, cell in indexed_row_cells):
        return False

    body_top = min(float(box["y"]) for box in body_boxes)
    body_bottom = max(float(box["y"]) + float(box["height"]) for box in body_boxes)
    split_parts: dict[int, tuple[str, str, dict[str, Any], dict[str, Any]]] = {}

    for cell_index, cell in header_cells:
        if max(int(cell.get("col_span", 1)), 1) != 1:
            continue
        box = cell.get("bbox")
        if not box:
            continue
        cell_top = float(box["y"])
        cell_bottom = cell_top + float(box["height"])
        if cell_top >= body_top - 0.5 or cell_bottom <= body_top + 0.5:
            continue

        cell_words = _words_inside_bbox(page_words, box)
        upper_words = [
            word
            for word in cell_words
            if (float(word.get("top", 0.0)) + float(word.get("bottom", 0.0))) / 2
            < body_top
        ]
        lower_words = [
            word
            for word in cell_words
            if body_top
            <= (float(word.get("top", 0.0)) + float(word.get("bottom", 0.0))) / 2
            <= body_bottom + 1.0
        ]
        upper_text = _words_text(upper_words)
        lower_text = _words_text(lower_words)
        upper_box = _word_bbox(upper_words)
        lower_box = _word_bbox(lower_words)
        if not upper_text or not lower_text or not upper_box or not lower_box:
            continue

        original_text = _WHITESPACE_RE.sub(" ", str(cell.get("text") or "")).strip()
        reconstructed = _WHITESPACE_RE.sub(" ", f"{upper_text} {lower_text}").strip()
        if original_text.casefold() != reconstructed.casefold():
            continue
        split_parts[cell_index] = (
            upper_text,
            lower_text,
            upper_box,
            lower_box,
        )

    if not split_parts:
        return False

    column_count = max(
        max((len(row) for row in rows), default=0),
        max(
            (
                int(cell.get("column", 0)) + max(int(cell.get("col_span", 1)), 1)
                for _, cell in indexed_row_cells
            ),
            default=0,
        ),
    )
    header_row = ["" for _ in range(column_count)]
    body_row = ["" for _ in range(column_count)]

    original_cell_count = len(cells)
    for cell_index in range(original_cell_count):
        cell = cells[cell_index]
        cell_row = int(cell.get("row", 0))
        if cell_row > row_index:
            cell["row"] = cell_row + 1
            continue
        if cell_row != row_index:
            continue

        column = max(int(cell.get("column", 0)), 0)
        if cell.get("column_header"):
            if cell_index in split_parts:
                upper_text, lower_text, upper_box, lower_box = split_parts[cell_index]
                original_text = str(cell.get("text") or "")
                original_box = dict(cell.get("bbox") or {})
                cell["text"] = upper_text
                cell["bbox"] = upper_box
                cell["split_from_text"] = original_text
                cell["split_from_bbox"] = original_box
                header_row[column] = upper_text
                body_row[column] = lower_text
                cells.append(
                    {
                        "row": row_index + 1,
                        "column": column,
                        "row_span": 1,
                        "col_span": 1,
                        "text": lower_text,
                        "column_header": False,
                        "row_header": False,
                        "row_section": False,
                        "bbox": lower_box,
                        "source": cell.get("source") or "native",
                        "split_from_text": original_text,
                        "split_from_bbox": original_box,
                    }
                )
            else:
                header_row[column] = str(cell.get("text") or "")
        else:
            cell["row"] = row_index + 1
            body_row[column] = str(cell.get("text") or "")

    rows[row_index] = header_row
    rows.insert(row_index + 1, body_row)
    return True


def _repair_docling_table_rows(
    rows: list[list[str]],
    cells: list[dict[str, Any]],
    page_words: Sequence[Mapping[str, Any]],
) -> None:
    while True:
        repaired = False
        for row_index in sorted({int(cell.get("row", 0)) for cell in cells}):
            if _split_mixed_header_body_row(
                rows,
                cells,
                row_index,
                page_words,
            ):
                repaired = True
                break
        if not repaired:
            return


def _table_html(
    rows: Sequence[Sequence[str]],
    cells: Sequence[Mapping[str, Any]],
) -> str:
    lines = ["<table>"]
    if cells:
        by_position: dict[tuple[int, int], Mapping[str, Any]] = {}
        by_row: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        row_count = len(rows)
        column_count = max((len(row) for row in rows), default=0)
        for cell in cells:
            row = max(int(cell.get("row", 0)), 0)
            column = max(int(cell.get("column", 0)), 0)
            row_span = max(int(cell.get("row_span", 1)), 1)
            col_span = max(int(cell.get("col_span", 1)), 1)
            by_position.setdefault((row, column), cell)
            by_row[row].append(cell)
            row_count = max(row_count, row + row_span)
            column_count = max(column_count, column + col_span)

        # Only a contiguous leading run of pure column-header rows belongs in
        # ``thead``. A mixed row is body content even if one cell was
        # accidentally tagged as a column header.
        header_row_count = 0
        for row_index in range(row_count):
            explicit = by_row.get(row_index, [])
            if explicit and all(bool(cell.get("column_header")) for cell in explicit):
                header_row_count += 1
            else:
                break

        covered: set[tuple[int, int]] = set()

        def render_row(row_index: int, *, header_row: bool) -> list[str]:
            rendered = ["    <tr>"]
            for column_index in range(column_count):
                if (row_index, column_index) in covered:
                    continue

                cell = by_position.get((row_index, column_index))
                if cell is None:
                    tag = "th" if header_row else "td"
                    rendered.append(f"      <{tag}></{tag}>")
                    continue

                row_span = max(int(cell.get("row_span", 1)), 1)
                col_span = max(int(cell.get("col_span", 1)), 1)
                for row_offset in range(row_span):
                    for column_offset in range(col_span):
                        if row_offset or column_offset:
                            covered.add(
                                (
                                    row_index + row_offset,
                                    column_index + column_offset,
                                )
                            )

                tag = "th" if header_row or cell.get("column_header") else "td"
                attributes: list[str] = []
                if row_span > 1:
                    attributes.append(f' rowspan="{row_span}"')
                if col_span > 1:
                    attributes.append(f' colspan="{col_span}"')
                value = html.escape(str(cell.get("text") or "")).replace("\n", "<br>")
                rendered.append(f"      <{tag}{''.join(attributes)}>{value}</{tag}>")
            rendered.append("    </tr>")
            return rendered

        if header_row_count:
            lines.append("  <thead>")
            for row_index in range(header_row_count):
                lines.extend(render_row(row_index, header_row=True))
            lines.append("  </thead>")

        if row_count > header_row_count:
            lines.append("  <tbody>")
            for row_index in range(header_row_count, row_count):
                lines.extend(render_row(row_index, header_row=False))
            lines.append("  </tbody>")
    else:
        column_count = max((len(row) for row in rows), default=0)
        spanning_title = (
            len(rows) >= 3
            and column_count >= 3
            and len(rows[0]) == column_count
            and bool(str(rows[0][0] or "").strip())
            and all(not str(value or "").strip() for value in rows[0][1:])
            and len(rows[1]) == column_count
            and all(bool(str(value or "").strip()) for value in rows[1])
        )
        if spanning_title:
            title = html.escape(str(rows[0][0])).replace("\n", "<br>")
            lines.extend(
                [
                    "  <thead>",
                    "    <tr>",
                    f'      <th colspan="{column_count}">{title}</th>',
                    "    </tr>",
                    "    <tr>",
                ]
            )
            for value in rows[1]:
                escaped = html.escape(str(value or "")).replace("\n", "<br>")
                lines.append(f"      <th>{escaped}</th>")
            lines.extend(["    </tr>", "  </thead>", "  <tbody>"])
            for row in rows[2:]:
                lines.append("    <tr>")
                for value in row:
                    escaped = html.escape(str(value or "")).replace(
                        "\n", "<br>"
                    )
                    lines.append(f"      <td>{escaped}</td>")
                lines.append("    </tr>")
            lines.append("  </tbody>")
        else:
            for row_index, row in enumerate(rows):
                tag = "th" if row_index == 0 and len(rows) > 1 else "td"
                lines.append("  <tr>")
                for value in row:
                    escaped = html.escape(str(value or "")).replace(
                        "\n", "<br>"
                    )
                    lines.append(f"    <{tag}>{escaped}</{tag}>")
                lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _table_csv(rows: Sequence[Sequence[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().rstrip("\n")


def _refresh_table_serializations(table: dict[str, Any]) -> None:
    rows = [[str(value or "") for value in row] for row in (table.get("rows") or [])]
    cells = table.get("cells") or []
    table["rows"] = rows
    # Geometry-only grids are useful reconciliation evidence, especially when
    # a typed chart owns the same vector region, but an all-empty grid has no
    # user-facing table content.  Preserve its rows/bboxes in JSON so the gate
    # remains auditable while keeping raw/rendered Markdown free of phantom
    # blank tables.  A later image/OCR attachment that supplies cell text calls
    # this helper again and restores the normal serializations.
    if not any(value.strip() for row in rows for value in row):
        table["html"] = ""
        table["md"] = ""
        table["csv"] = ""
        table["value"] = rows
        return
    rendered = _table_html(rows, cells)
    table["html"] = rendered
    table["md"] = rendered
    table["csv"] = _table_csv(rows)
    table["value"] = rows


def _build_docling_table_predecessor(
    raw_item: Mapping[str, Any],
    page_heights: Mapping[int, float],
    page_words_by_page: Mapping[int, Sequence[Mapping[str, Any]]] | None = None,
    native_texts: Sequence[str] | None = None,
    image_regions: Mapping[int, Sequence[ImageRegion]] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Build the exact generic predecessor without retaining the raw graph."""

    page_index, box = _bbox_from_prov(raw_item, page_heights)
    data = raw_item.get("data") or {}
    row_count = int(data.get("num_rows") or 0)
    column_count = int(data.get("num_cols") or 0)
    rows = [["" for _ in range(column_count)] for _ in range(row_count)]
    cells: list[dict[str, Any]] = []

    for raw_cell in data.get("table_cells") or []:
        row = int(raw_cell.get("start_row_offset_idx") or 0)
        column = int(raw_cell.get("start_col_offset_idx") or 0)
        row_span = int(raw_cell.get("row_span") or 1)
        col_span = int(raw_cell.get("col_span") or 1)
        text = str(raw_cell.get("text") or "").strip()
        if row < row_count and column < column_count:
            rows[row][column] = text
        cells.append(
            {
                "row": row,
                "column": column,
                "row_span": row_span,
                "col_span": col_span,
                "text": text,
                "column_header": bool(raw_cell.get("column_header")),
                "row_header": bool(raw_cell.get("row_header")),
                "row_section": bool(raw_cell.get("row_section")),
                "bbox": _cell_bbox(raw_cell.get("bbox")),
                "source": "native",
            }
        )

    _repair_docling_table_rows(
        rows,
        cells,
        (page_words_by_page or {}).get(page_index, []),
    )
    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    table_text = _normalized_search_text(
        " ".join(str(cell or "") for row in rows for cell in row)
    )
    native_page_text = (
        native_texts[page_index - 1]
        if native_texts is not None and 1 <= page_index <= len(native_texts)
        else ""
    )
    table_tokens = table_text.split()
    native_tokens = set(_normalized_search_text(native_page_text).split())
    native_coverage = (
        sum(token in native_tokens for token in table_tokens) / len(table_tokens)
        if table_tokens
        else 0.0
    )
    table_source = "native" if native_texts is None or native_coverage >= 0.5 else "ocr"
    for cell in cells:
        cell["source"] = table_source

    item: dict[str, Any] = {
        "type": "table",
        "bbox": box,
        "source": table_source,
        "confidence": None,
        "rows": rows,
        "cells": cells,
        "row_count": row_count,
        "column_count": column_count,
        "parse_concerns": [],
        "engine": "docling",
        "embedded_images": [],
    }
    if image_regions is not None:
        # Phase 03 confidence is predecessor data.  Apply it before P04-US01
        # computes representation custody so diagnostic overlays remain byte-
        # equivalent to the predecessor while valid canonical cells stay
        # closed under the new schema.
        _enrich_ocr_confidence(
            [{"page_index": page_index, "items": [item]}],
            image_regions,
        )
    _refresh_table_serializations(item)
    return page_index, item


def _docling_table_item(
    raw_item: Mapping[str, Any],
    page_heights: Mapping[int, float],
    page_words_by_page: Mapping[int, Sequence[Mapping[str, Any]]] | None = None,
    native_texts: Sequence[str] | None = None,
    source_document_identity: str | None = None,
    image_regions: Mapping[int, Sequence[ImageRegion]] | None = None,
    *,
    table_span_fidelity_enabled: bool = False,
    table_span_fidelity_deadline: float | None = None,
    table_span_fidelity_document_deadline: float | None = None,
) -> tuple[int, dict[str, Any]]:
    if not table_span_fidelity_enabled:
        return _build_docling_table_predecessor(
            raw_item,
            page_heights,
            page_words_by_page,
            native_texts,
            None,
        )

    from app.services.table_semantics import (
        _orchestrate_docling_table_projection,
    )

    return _orchestrate_docling_table_projection(
        raw_item,
        page_heights,
        page_words_by_page,
        native_texts,
        source_document_identity,
        image_regions,
        table_span_fidelity_deadline=table_span_fidelity_deadline,
        table_span_fidelity_document_deadline=(
            table_span_fidelity_document_deadline
        ),
    )


def _vector_table_item(
    table: RawTable | Mapping[str, Any],
    *,
    table_span_fidelity_enabled: bool = False,
) -> dict[str, Any]:
    from app.services.table_semantics import prepare_vector_table

    if isinstance(table, Mapping):
        raw_rows = table.get("rows", [])
        raw_row_boxes = table.get("row_bboxes", [])
        raw_bbox = table.get("bbox")
        raw_parse_concerns = table.get("parse_concerns", [])
    else:
        raw_rows = table.rows
        raw_row_boxes = table.row_bboxes
        raw_bbox = table.bbox
        raw_parse_concerns = table.parse_concerns
    rows = [
        [str(value or "").strip() for value in row]
        for row in raw_rows
    ]
    row_boxes = [
        box
        for box in (_coerce_bbox(value) for value in raw_row_boxes)
        if box is not None
    ]
    box = _coerce_bbox(raw_bbox)
    item: dict[str, Any] = {
        "type": "table",
        "bbox": box,
        "source": "native",
        "confidence": None,
        "rows": rows,
        "cells": [],
        "row_bboxes": row_boxes,
        "row_count": len(rows),
        "column_count": max((len(row) for row in rows), default=0),
        "parse_concerns": list(raw_parse_concerns or []),
        "engine": "pdfplumber",
        "embedded_images": [],
    }
    _refresh_table_serializations(item)
    item = prepare_vector_table(
        item,
        table,
        table_span_fidelity_enabled=table_span_fidelity_enabled,
    )
    return item


def _ocr_line_primary_decision(
    line: Any,
    settings: Settings,
) -> tuple[bool, str | None]:
    """Decide whether raster OCR is reliable enough for primary image text."""

    text = str(getattr(line, "text", "") or "").strip()
    normalized = _normalized_search_text(text)
    alnum_count = sum(character.isalnum() for character in text)
    confidence = getattr(line, "confidence", None)
    if (
        isinstance(confidence, (int, float))
        and confidence < settings.image_primary_ocr_min_confidence
    ):
        relaxed_floor = settings.image_primary_ocr_min_confidence * 0.65
        if (
            alnum_count >= settings.image_low_confidence_min_alnum_chars
            and confidence >= relaxed_floor
        ):
            return True, "accepted_informative_low_confidence_text"
        return False, "low_confidence"
    if not normalized:
        return False, "unsupported_glyph_only"
    return True, None


def _ocr_line_diagnostic(
    line: Any,
    settings: Settings,
) -> dict[str, Any]:
    accepted, reason = _ocr_line_primary_decision(line, settings)
    diagnostic = {
        "value": line.text,
        "text": line.text,
        "bbox": _coerce_bbox(line.bbox),
        "confidence": line.confidence,
        "word_count": getattr(line, "word_count", None),
        "source": "ocr",
        "accepted": accepted,
        "rejection_reason": None if accepted else reason,
    }
    if accepted and reason:
        diagnostic["acceptance_note"] = reason
    return diagnostic


def _region_role(region: ImageRegion) -> str:
    """Resolve a visual region's semantic role independently of file format."""

    if region.region_role in {"page_source", "content_region"}:
        return region.region_role
    if region.content_type in {"page_image", "page_render"}:
        return "page_source"
    # A near-full-page image object is page provenance for both an uploaded
    # raster and a scanned/searchable PDF. Smaller objects are document
    # content such as photographs, screenshots, charts, or signatures.
    return "page_source" if region.area_ratio >= 0.85 else "content_region"


def _image_item(
    region: ImageRegion,
    settings: Settings | None = None,
    source_document_identity: str | None = None,
) -> dict[str, Any]:
    quality_settings = settings or Settings()
    box = _coerce_bbox(region.bbox)
    lines = [_ocr_line_diagnostic(line, quality_settings) for line in region.lines]
    cleaned_ocr_text = "\n".join(
        str(line["text"])
        for line in lines
        if line["accepted"] and str(line["text"]).strip()
    )
    rejected_candidates = []
    for candidate in region.rejected_lines:
        normalized_candidate = dict(candidate)
        if isinstance(candidate.get("bbox"), Mapping):
            normalized_candidate["bbox"] = _coerce_bbox(candidate["bbox"])
        normalized_candidate.setdefault("source", "ocr")
        rejected_candidates.append(normalized_candidate)
    role = _region_role(region)
    normalized_content_type = (
        "page_image"
        if role == "page_source" and region.content_type == "image"
        else region.content_type
    )
    spatial_occurrences: list[dict[str, Any]] = []
    spatial_summary: dict[str, Any] | None = None
    if quality_settings.ocr_spatial_token_preservation_enabled:
        spatial_occurrences, spatial_summary = project_ocr_token_occurrences(
            page_index=region.page_index,
            owner_identity={
                "kind": "ocr_region",
                "source_document_identity": source_document_identity,
                "object_index": region.object_index,
                "region_origin": region.region_origin,
                "region_role": role,
            },
            owner_bbox=box,
            owner_content_type=normalized_content_type,
            coordinate_unit=region.coordinate_unit or "pt",
            lines=region.lines,
            line_diagnostics=lines,
            rejected_lines=region.rejected_lines,
            include_ocr_in_primary=True,
            primary_confidence_threshold=(
                quality_settings.image_primary_ocr_min_confidence
            ),
            owner_region_role=role,
        )
    item = {
        "type": "image",
        "value": cleaned_ocr_text,
        "ocr_text": cleaned_ocr_text,
        "cleaned_ocr_text": cleaned_ocr_text,
        "raw_ocr_text": region.text,
        "md": cleaned_ocr_text,
        "bbox": box,
        "source": "ocr",
        "confidence": region.confidence,
        "detected_text": bool(cleaned_ocr_text),
        "pixel_width": region.pixel_width,
        "pixel_height": region.pixel_height,
        "area_ratio": region.area_ratio,
        "items": lines,
        "warnings": list(region.warnings),
        "region_role": role,
        "region_origin": region.region_origin,
        "rejected_ocr_candidates": rejected_candidates,
    }
    if spatial_summary is not None:
        item["ocr_occurrence_summary"] = spatial_summary
        if not spatial_summary.get("fail_closed_overflow"):
            item["ocr_token_occurrences"] = spatial_occurrences
        if any(
            bool(spatial_summary.get(key))
            for key in (
                "source_token_limit_reached",
                "occurrence_limit_reached",
                "short_alternative_limit_reached",
                "serialized_byte_limit_reached",
            )
        ):
            item["parse_concerns"] = ["spatial_ocr_occurrences_truncated"]
    if region.coordinate_unit:
        item["coordinate_unit"] = region.coordinate_unit
    if normalized_content_type != "image":
        item["content_type"] = normalized_content_type
    if region.metadata:
        item["metadata"] = dict(region.metadata)
    return item


def _list_group_item(
    raw_group: Mapping[str, Any],
    refs: Mapping[str, Mapping[str, Any]],
    page_heights: Mapping[int, float],
    native_texts: Sequence[str],
) -> list[tuple[int, dict[str, Any]]]:
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for child in raw_group.get("children") or []:
        raw_child = refs.get(_reference_value(child))
        if not raw_child or "text" not in raw_child:
            continue
        page_index, normalized = _text_item(raw_child, page_heights, native_texts)
        marker = str(raw_child.get("text") or "").strip()
        by_page[page_index].append(
            {
                "value": normalized["value"],
                "bbox": normalized["bbox"],
                "source": normalized["source"],
                "marker": marker,
                "level": 0,
            }
        )

    ordered = str(raw_group.get("label")) == "ordered_list"
    results: list[tuple[int, dict[str, Any]]] = []
    for page_index, entries in by_page.items():
        results.append(
            (
                page_index,
                {
                    "type": "list",
                    "value": [entry["value"] for entry in entries],
                    "items": entries,
                    "ordered": ordered,
                    "md": "\n".join(
                        (
                            f"{index}. {entry['value']}"
                            if ordered
                            else f"- {entry['value']}"
                        )
                        for index, entry in enumerate(entries, start=1)
                    ),
                    "bbox": _bbox_union(entry["bbox"] for entry in entries),
                    "source": (
                        "native"
                        if all(entry["source"] == "native" for entry in entries)
                        else "mixed"
                    ),
                    "confidence": None,
                },
            )
        )
    return results


def _header_footer_items(
    raw: Mapping[str, Any],
    page_heights: Mapping[int, float],
    native_texts: Sequence[str],
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    grouped: dict[str, dict[int, list[dict[str, Any]]]] = {
        "header": defaultdict(list),
        "footer": defaultdict(list),
    }
    for raw_item in raw.get("texts") or []:
        label = str(raw_item.get("label") or "")
        if label not in {"page_header", "page_footer"}:
            continue
        page_index, item = _text_item(raw_item, page_heights, native_texts)
        kind = "header" if label == "page_header" else "footer"
        grouped[kind][page_index].append(item)

    output: dict[str, dict[int, dict[str, Any]]] = {
        "header": {},
        "footer": {},
    }
    for kind in ("header", "footer"):
        for page_index, children in grouped[kind].items():
            children.sort(
                key=lambda item: (
                    float((item.get("bbox") or {}).get("y", 0.0)),
                    float((item.get("bbox") or {}).get("x", 0.0)),
                )
            )
            output[kind][page_index] = {
                "type": kind,
                "value": "\n".join(str(child.get("value") or "") for child in children),
                "md": "\n\n".join(str(child.get("value") or "") for child in children),
                "items": children,
                "bbox": _bbox_union(child.get("bbox") for child in children),
                "source": (
                    "native"
                    if all(child.get("source") == "native" for child in children)
                    else "mixed"
                ),
                "confidence": None,
            }
    return output["header"], output["footer"]


def _ocr_lines_in_box(
    image_regions: Mapping[int, Sequence[ImageRegion]],
    page_index: int,
    box: Mapping[str, Any] | None,
) -> list[Any]:
    if not box:
        return []
    return [
        line
        for region in image_regions.get(page_index, [])
        for line in region.lines
        if _center_inside(_coerce_bbox(line.bbox), box)
    ]


def _ocr_rejected_lines_in_box(
    image_regions: Mapping[int, Sequence[ImageRegion]],
    page_index: int,
    box: Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    if not box:
        return []
    return [
        candidate
        for region in image_regions.get(page_index, [])
        for candidate in region.rejected_lines
        if isinstance(candidate, Mapping)
        and _center_inside(_coerce_bbox(candidate.get("bbox")), box)
    ]


def _line_confidence(lines: Sequence[Any]) -> float | None:
    weighted = [
        (
            float(line.confidence),
            max(int(getattr(line, "word_count", 1) or 1), 1),
        )
        for line in lines
        if getattr(line, "confidence", None) is not None
    ]
    if not weighted:
        return None
    denominator = sum(weight for _, weight in weighted)
    return round(
        sum(confidence * weight for confidence, weight in weighted) / denominator,
        4,
    )


def _picture_classification(
    raw_item: Mapping[str, Any],
) -> dict[str, Any] | None:
    predictions: list[Mapping[str, Any]] = []
    meta = raw_item.get("meta")
    if isinstance(meta, Mapping):
        classification = meta.get("classification")
        if isinstance(classification, Mapping):
            predictions.extend(
                prediction
                for prediction in (classification.get("predictions") or [])
                if isinstance(prediction, Mapping)
            )
    for annotation in raw_item.get("annotations") or []:
        if (
            isinstance(annotation, Mapping)
            and annotation.get("kind") == "classification"
        ):
            predictions.extend(
                prediction
                for prediction in (annotation.get("predicted_classes") or [])
                if isinstance(prediction, Mapping)
            )
    if not predictions:
        return None

    def confidence(prediction: Mapping[str, Any]) -> float:
        try:
            return float(prediction.get("confidence"))
        except (TypeError, ValueError):
            return -1.0

    best = max(predictions, key=confidence)
    class_name = str(best.get("class_name") or best.get("label") or "").strip()
    score = confidence(best)
    if not class_name:
        return None
    return {
        "class_name": class_name,
        "confidence": score if score >= 0 else None,
    }


def _picture_description(
    raw_item: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return a model description with explicit provenance when available."""

    meta = raw_item.get("meta")
    if isinstance(meta, Mapping):
        description = meta.get("description")
        if isinstance(description, Mapping):
            text = _WHITESPACE_RE.sub(
                " ",
                str(description.get("text") or ""),
            ).strip()
            if text:
                return {
                    "text": text,
                    "created_by": (
                        str(description.get("created_by") or "").strip()
                        or "picture_description_model"
                    ),
                    "confidence": description.get("confidence"),
                }

    for annotation in raw_item.get("annotations") or []:
        if not isinstance(annotation, Mapping):
            continue
        if str(annotation.get("kind") or "").casefold() not in {
            "description",
            "picture_description",
        }:
            continue
        text = _WHITESPACE_RE.sub(
            " ",
            str(annotation.get("text") or ""),
        ).strip()
        if text:
            return {
                "text": text,
                "created_by": (
                    str(annotation.get("provenance") or "").strip()
                    or "picture_description_model"
                ),
                "confidence": annotation.get("confidence"),
            }
    return None


def _visual_content_type(
    raw_item: Mapping[str, Any],
    label: str,
    *,
    classification_threshold: float = 0.6,
) -> tuple[str, dict[str, Any] | None]:
    classification = _picture_classification(raw_item)
    if label == "chart":
        return "chart", classification
    if label == "diagram":
        return "diagram", classification
    if classification is None:
        return "image", None
    confidence = classification.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or confidence < classification_threshold
    ):
        return "image", classification
    class_name = str(classification["class_name"])
    if class_name in _CHART_CLASSIFICATIONS:
        return "chart", classification
    if class_name in _DIAGRAM_CLASSIFICATIONS:
        return "diagram", classification
    return "image", classification


def _visual_item(
    raw_item: Mapping[str, Any],
    label: str,
    refs: Mapping[str, Mapping[str, Any]],
    page_heights: Mapping[int, float],
    image_regions: Mapping[int, Sequence[ImageRegion]],
    settings: Settings | None = None,
    source_document_identity: str | None = None,
    coordinate_unit: str = "pt",
    source_text_evidence: Any | None = None,
) -> tuple[int, dict[str, Any]]:
    quality_settings = settings or Settings()
    page_index, picture_box = _bbox_from_prov(raw_item, page_heights)
    lines = _ocr_lines_in_box(image_regions, page_index, picture_box)
    child_values: list[str] = []
    native_visual_children: list[dict[str, Any]] = []
    for key in ("captions", "children"):
        for child in raw_item.get(key) or []:
            raw_child = refs.get(_reference_value(child))
            value = _WHITESPACE_RE.sub(
                " ",
                str((raw_child or {}).get("text") or ""),
            ).strip()
            if value and value not in child_values:
                child_values.append(value)
            if key == "children" and value and isinstance(raw_child, Mapping):
                child_page_index, child_box = _bbox_from_prov(
                    raw_child,
                    page_heights,
                )
                native_visual_children.append(
                    {
                        "id": str(raw_child.get("self_ref") or ""),
                        "text": value,
                        "bbox": child_box,
                        "page_index": child_page_index,
                    }
                )

    line_diagnostics = [_ocr_line_diagnostic(line, quality_settings) for line in lines]
    retained_accepted_line_indexes: frozenset[int] = frozenset()
    compact_primary_lines: list[OCRLine] = []
    if quality_settings.ocr_spatial_token_preservation_enabled:
        accepted_entries = [
            (line_index, str(diagnostic["text"]), line.bbox)
            for line_index, (line, diagnostic) in enumerate(
                zip(lines, line_diagnostics, strict=True)
            )
            if diagnostic["accepted"]
        ]
        (
            accepted_line_values,
            retained_accepted_positions,
        ) = geometry_aware_line_values_with_selection(
            ((text, bbox) for _line_index, text, bbox in accepted_entries),
            coordinate_unit=coordinate_unit,
        )
        retained_accepted_line_indexes = frozenset(
            accepted_entries[position][0] for position in retained_accepted_positions
        )
        compact_primary_lines = [
            line
            for line_index, line in enumerate(lines)
            if line_index in retained_accepted_line_indexes
        ]
        raw_line_values = geometry_aware_unique_line_values(
            ((str(line.text), line.bbox) for line in lines if str(line.text).strip()),
            coordinate_unit=coordinate_unit,
        )
        accepted_ocr_text = "\n".join(accepted_line_values)
        raw_ocr_text = "\n".join(raw_line_values)
    else:
        accepted_line_values = [
            str(line["text"]).strip()
            for line in line_diagnostics
            if line["accepted"] and str(line["text"]).strip()
        ]
        raw_line_values = [
            str(line.text).strip() for line in lines if str(line.text).strip()
        ]
        accepted_ocr_text = "\n".join(dict.fromkeys(accepted_line_values))
        raw_ocr_text = "\n".join(dict.fromkeys(raw_line_values))
        compact_entries = [
            (line_index, str(diagnostic["text"]), line.bbox)
            for line_index, (line, diagnostic) in enumerate(
                zip(lines, line_diagnostics, strict=True)
            )
            if diagnostic["accepted"]
        ]
        (
            compact_values,
            compact_positions,
        ) = geometry_aware_line_values_with_selection(
            ((text, bbox) for _line_index, text, bbox in compact_entries),
            coordinate_unit=coordinate_unit,
        )
        if "\n".join(compact_values) == accepted_ocr_text:
            compact_primary_lines = [
                lines[compact_entries[position][0]]
                for position in compact_positions
            ]
    content_type, classification = _visual_content_type(
        raw_item,
        label,
        classification_threshold=(
            quality_settings.image_picture_classification_threshold
        ),
    )
    generated_description = _picture_description(raw_item)
    document_caption = "\n".join(child_values) or None
    caption = document_caption or (
        str(generated_description["text"])
        if generated_description is not None
        else None
    )
    caption_source = (
        "document_caption"
        if document_caption
        else (
            str(generated_description["created_by"])
            if generated_description is not None
            else None
        )
    )
    classification_name = (
        str(classification.get("class_name") or "").casefold()
        if classification is not None
        else ""
    )
    accepted_word_count = sum(
        int(line.get("word_count") or 0)
        for line in line_diagnostics
        if line["accepted"]
    )
    accepted_ocr_confidence = _line_confidence(
        [
            line
            for line, diagnostic in zip(
                lines,
                line_diagnostics,
                strict=True,
            )
            if diagnostic["accepted"]
        ]
    )
    rejected_ocr_lines = _ocr_rejected_lines_in_box(
        image_regions,
        page_index,
        picture_box,
    )
    compact_ocr_evidence: dict[str, Any] | None = None
    owned_native_source_text: dict[str, Any] | None = None
    visual_probe = {
        "type": content_type,
        "content_type": content_type,
        "bbox": picture_box,
        "region_role": "content_region",
    }
    if coordinate_unit == "pt" and content_type == "image":
        try:
            from app.services.visual_source_text import (
                compact_visual_ocr_primary_evidence,
                recover_owned_visual_source_text,
            )

            owned_native_source_text = recover_owned_visual_source_text(
                visual_probe,
                native_visual_children,
                source_text_evidence=source_text_evidence,
                source_document_identity=source_document_identity,
                page_index=page_index,
            )
            compact_ocr_evidence = compact_visual_ocr_primary_evidence(
                visual_probe,
                native_visual_children,
                compact_primary_lines,
                rejected_ocr_lines,
                accepted_ocr_text,
                source_text_evidence=source_text_evidence,
                source_document_identity=source_document_identity,
                page_index=page_index,
                classification=classification,
                confidence_floor=max(
                    quality_settings.image_primary_ocr_min_confidence,
                    quality_settings.image_picture_classification_threshold,
                ),
            )
        except (MemoryError, TypeError, ValueError):
            # Optional visual-label evidence is item-local and fail-closed.
            compact_ocr_evidence = None
            owned_native_source_text = None
    # Charts, diagrams, screenshots, signatures, and similar document-like
    # visuals contain intentional text. Natural photographs keep OCR as
    # subordinate diagnostics so incidental branding does not become prose.
    # When the optional picture classifier is unavailable, require the
    # aggregate OCR confidence to clear the same conservative floor used for
    # source-backed visual classification. A large photograph can otherwise
    # accumulate several individually admissible fragments and be mistaken
    # for a text-bearing document visual.
    include_ocr_in_primary = (
        content_type in {"chart", "diagram"}
        or classification_name in _TEXTUAL_VISUAL_CLASSIFICATIONS
        or compact_ocr_evidence is not None
        or (
            classification is None
            and len(accepted_line_values) >= 2
            and accepted_word_count >= 4
            and accepted_ocr_confidence is not None
            and accepted_ocr_confidence
            >= max(
                quality_settings.image_primary_ocr_min_confidence,
                quality_settings.image_picture_classification_threshold,
            )
        )
    )
    primary_values = [
        value
        for value in (
            caption,
            accepted_ocr_text if include_ocr_in_primary else None,
        )
        if value
    ]
    primary_text = "\n".join(dict.fromkeys(primary_values))
    parse_concerns: list[str] = []
    if content_type == "chart":
        parse_concerns.append("chart_values_not_structured")
    elif content_type == "diagram":
        parse_concerns.append("diagram_relationships_not_structured")
    if generated_description is not None and not document_caption:
        parse_concerns.append("model_generated_visual_description")

    spatial_occurrences: list[dict[str, Any]] = []
    spatial_summary: dict[str, Any] | None = None
    if quality_settings.ocr_spatial_token_preservation_enabled:
        spatial_occurrences, spatial_summary = project_ocr_token_occurrences(
            page_index=page_index,
            owner_identity={
                "kind": "docling_visual",
                "source_document_identity": source_document_identity,
                "self_ref": raw_item.get("self_ref"),
                "label": label,
            },
            owner_bbox=picture_box,
            owner_content_type=content_type,
            coordinate_unit=coordinate_unit,
            lines=lines,
            line_diagnostics=line_diagnostics,
            rejected_lines=_ocr_rejected_lines_in_box(
                image_regions, page_index, picture_box
            ),
            include_ocr_in_primary=include_ocr_in_primary,
            primary_confidence_threshold=(
                quality_settings.image_primary_ocr_min_confidence
            ),
            owner_region_role="content_region",
            primary_line_selections=[
                (
                    include_ocr_in_primary
                    and line_index in retained_accepted_line_indexes
                )
                for line_index in range(len(lines))
            ],
        )
        if any(
            bool(spatial_summary.get(key))
            for key in (
                "source_token_limit_reached",
                "occurrence_limit_reached",
                "short_alternative_limit_reached",
                "serialized_byte_limit_reached",
            )
        ):
            parse_concerns.append("spatial_ocr_occurrences_truncated")

    if primary_text:
        warnings: list[str] = []
    elif accepted_ocr_text:
        warnings = [
            "OCR detected inside this visual region and was retained as "
            "image-level metadata."
        ]
    else:
        warnings = ["No reliable text or visual structure was detected."]

    item: dict[str, Any] = {
        "type": content_type,
        "content_type": content_type,
        "value": primary_text,
        "ocr_text": accepted_ocr_text,
        "raw_ocr_text": raw_ocr_text,
        "md": (
            primary_text
            or (f"[{content_type.capitalize()} detected; no reliable text extracted.]")
        ),
        "bbox": picture_box,
        "source": (
            "derived"
            if generated_description is not None and not document_caption
            else ("ocr" if primary_text else "derived")
        ),
        "confidence": accepted_ocr_confidence,
        "detected_text": bool(accepted_ocr_text),
        "items": line_diagnostics,
        "caption": caption,
        "caption_source": caption_source,
        "caption_generated": bool(
            generated_description is not None and not document_caption
        ),
        "caption_confidence": (
            generated_description.get("confidence")
            if generated_description is not None and not document_caption
            else None
        ),
        "include_ocr_in_primary": include_ocr_in_primary,
        "region_role": "content_region",
        "parse_concerns": parse_concerns,
        "warnings": warnings,
    }
    if spatial_summary is not None:
        item["ocr_occurrence_summary"] = spatial_summary
        if not spatial_summary.get("fail_closed_overflow"):
            item["ocr_token_occurrences"] = spatial_occurrences
    # Preserve model-supplied metadata without interpreting it as facts.
    for key in ("annotations", "meta"):
        if raw_item.get(key) is not None:
            item[key] = raw_item[key]
    if classification is not None:
        item["classification"] = classification
    if compact_ocr_evidence is not None:
        raw_meta = item.get("meta")
        item_meta = dict(raw_meta) if isinstance(raw_meta, Mapping) else {}
        item_meta["compact_visual_ocr_primary"] = compact_ocr_evidence
        item["meta"] = item_meta
    if owned_native_source_text is not None:
        from app.services.visual_source_text import attach_visual_source_text

        item = attach_visual_source_text(
            item,
            owned_native_source_text,
            promote_primary=True,
        )
    return page_index, item


def _normalize_docling_body(
    raw: Mapping[str, Any],
    page_heights: Mapping[int, float],
    native_texts: Sequence[str],
    image_regions: Mapping[int, Sequence[ImageRegion]],
    page_words_by_page: Mapping[int, Sequence[Mapping[str, Any]]] | None = None,
    *,
    preserve_visual_items: bool = False,
    preserve_graph_items: bool = False,
    quality_settings: Settings | None = None,
    source_document_identity: str | None = None,
    coordinate_unit: str = "pt",
    source_text_evidence: Any | None = None,
    table_span_fidelity_enabled: bool = False,
    table_span_fidelity_document_deadline: float | None = None,
    table_span_fidelity_page_deadlines: dict[int, float] | None = None,
    table_span_fidelity_state: dict[str, Any] | None = None,
    table_decision_views_sink: dict[
        int, list[dict[str, Any]]
    ]
    | None = None,
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
    refs = _reference_map(raw)
    body_items: dict[int, list[dict[str, Any]]] = defaultdict(list)
    tables: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen_refs: set[str] = set()
    if table_span_fidelity_page_deadlines is None:
        table_span_fidelity_page_deadlines = {}
    if table_span_fidelity_state is None:
        table_span_fidelity_state = {}
    table_span_fidelity_page_attempts: dict[int, list[dict[str, Any]]] = (
        defaultdict(list)
    )
    table_span_fidelity_disabled_pages: set[int] = set()
    table_decision_by_identity: dict[int, dict[str, Any]] = {}
    sequence = 0

    def stamp(item: dict[str, Any]) -> dict[str, Any]:
        nonlocal sequence
        item["_sequence"] = sequence
        sequence += 1
        return item

    def append_table(page_index: int, item: dict[str, Any]) -> None:
        """Capture the private P03 view at the table-mint boundary."""

        has_evidence = "table_evidence" in item
        has_snapshot = "_p04_predecessor_snapshot" in item
        if has_evidence != has_snapshot:
            raise ValueError("table predecessor decision marker differs")
        decision_view = item
        if has_evidence:
            snapshot = item.get("_p04_predecessor_snapshot")
            if type(item.get("table_evidence")) is not dict or (
                type(snapshot) is not dict
                or snapshot is item
                or "table_evidence" in snapshot
                or "_p04_predecessor_snapshot" in snapshot
            ):
                raise ValueError("table predecessor decision identity differs")
            sequence_value = item.get("_sequence")
            if type(sequence_value) is not int or sequence_value < 0:
                raise ValueError("table predecessor sequence identity differs")
            # `stamp` is the sole mutation between predecessor minting and
            # this private boundary. Mirror its exact P03-owned value once so
            # any later page-atomic replay is byte/order-equivalent to flag-off.
            snapshot["_sequence"] = sequence_value
            decision_view = snapshot
        tables[page_index].append(item)
        table_decision_by_identity[id(item)] = decision_view

    def rollback_table_attempts(page_keys: set[int]) -> None:
        selected_attempts = [
            prior
            for page_key in sorted(page_keys)
            for prior in table_span_fidelity_page_attempts.get(page_key, [])
        ]
        for prior in selected_attempts:
            prior_item = prior.get("item")
            prior_page_index = prior.get("page_index")
            if type(prior_item) is dict and type(prior_page_index) is int:
                table_decision_by_identity.pop(id(prior_item), None)
                page_tables = tables.get(prior_page_index)
                if type(page_tables) is list:
                    page_tables[:] = [
                        candidate
                        for candidate in page_tables
                        if candidate is not prior_item
                    ]
        for prior in selected_attempts:
            fallback_page_index, fallback = _docling_table_item(
                prior["raw_item"],
                page_heights,
                page_words_by_page,
                native_texts,
                source_document_identity,
                image_regions,
                table_span_fidelity_enabled=False,
            )
            prior_sequence = prior.get("sequence")
            if type(prior_sequence) is int:
                fallback["_sequence"] = prior_sequence
            else:
                fallback = stamp(fallback)
            prior.update(
                {
                    "item": fallback,
                    "page_index": fallback_page_index,
                    "sequence": fallback["_sequence"],
                }
            )
            append_table(fallback_page_index, fallback)

    def visit(reference: str) -> None:
        nonlocal table_span_fidelity_document_deadline
        if reference in seen_refs:
            return
        seen_refs.add(reference)
        raw_item = refs.get(reference)
        if not raw_item:
            return
        label = str(raw_item.get("label") or "")

        if reference.startswith("#/groups/"):
            if label in {"list", "ordered_list"}:
                for page_index, item in _list_group_item(
                    raw_item, refs, page_heights, native_texts
                ):
                    body_items[page_index].append(stamp(item))
                return
            for child in raw_item.get("children") or []:
                visit(_reference_value(child))
            return

        if label in {"page_header", "page_footer"}:
            return

        if reference.startswith("#/tables/") or label == "table":
            if not table_span_fidelity_enabled:
                page_index, item = _docling_table_item(
                    raw_item,
                    page_heights,
                    page_words_by_page,
                    native_texts,
                    source_document_identity,
                    image_regions,
                    table_span_fidelity_enabled=False,
                )
                append_table(page_index, stamp(item))
                return

            if (
                table_span_fidelity_state.get("timed_out") is True
                or table_span_fidelity_state.get(
                    "span_fidelity_disabled"
                )
                is True
            ):
                page_index, item = _docling_table_item(
                    raw_item,
                    page_heights,
                    page_words_by_page,
                    native_texts,
                    source_document_identity,
                    image_regions,
                    table_span_fidelity_enabled=False,
                )
                append_table(page_index, stamp(item))
                return

            table_budget_active = False
            page_segment_started: float | None = None
            active_page_index: int | None = None
            page_deadline_key = -1
            try:
                from app.services import table_semantics

                table_span_fidelity_document_deadline = (
                    _resume_table_span_fidelity_budget(
                        table_span_fidelity_document_deadline,
                        table_span_fidelity_page_deadlines,
                        table_span_fidelity_state,
                    )
                )
                table_budget_active = True
                page_segment_started = time.perf_counter()
                try:
                    provenance = raw_item.get("prov")
                    raw_page_index = (
                        provenance[0].get("page_no")
                        if type(provenance) is list
                        and provenance
                        and type(provenance[0]) is dict
                        else None
                    )
                    page_deadline_key = (
                        raw_page_index
                        if type(raw_page_index) is int
                        and raw_page_index >= 1
                        else -1
                    )
                    attempts = table_span_fidelity_page_attempts[
                        page_deadline_key
                    ]
                    attempt: dict[str, Any] = {
                        "raw_item": raw_item,
                        "item": None,
                        "page_index": None,
                        "sequence": None,
                    }
                    attempts.append(attempt)

                    if not 1 <= page_deadline_key <= 100:
                        raise ValueError(
                            "table span-fidelity page identity differs"
                        )

                    if (
                        page_deadline_key
                        in table_span_fidelity_disabled_pages
                    ):
                        page_index, item = _docling_table_item(
                            raw_item,
                            page_heights,
                            page_words_by_page,
                            native_texts,
                            source_document_identity,
                            image_regions,
                            table_span_fidelity_enabled=False,
                        )
                        stamped = stamp(item)
                        attempt.update(
                            {
                                "item": stamped,
                                "page_index": page_index,
                                "sequence": stamped["_sequence"],
                            }
                        )
                        append_table(page_index, stamped)
                        return

                    table_span_fidelity_deadline = (
                        table_span_fidelity_page_deadlines.get(page_deadline_key)
                    )
                    if table_span_fidelity_deadline is None:
                        table_span_fidelity_deadline = (
                            table_semantics.table_span_fidelity_page_deadline(
                                table_span_fidelity_document_deadline
                            )
                        )
                        table_span_fidelity_deadline = min(
                            table_span_fidelity_deadline,
                            page_segment_started + 0.5,
                        )
                        table_span_fidelity_page_deadlines[page_deadline_key] = (
                            table_span_fidelity_deadline
                        )
                    active_page_index = page_deadline_key
                    page_index, item = _docling_table_item(
                        raw_item,
                        page_heights,
                        page_words_by_page,
                        native_texts,
                        source_document_identity,
                        image_regions,
                        table_span_fidelity_enabled=True,
                        table_span_fidelity_deadline=(
                            table_span_fidelity_deadline
                        ),
                        table_span_fidelity_document_deadline=(
                            table_span_fidelity_document_deadline
                        ),
                    )
                    if page_index != page_deadline_key:
                        raise ValueError(
                            "table span-fidelity page identity differs"
                        )
                finally:
                    _complete_table_span_fidelity_page_segment(
                        table_span_fidelity_page_deadlines,
                        active_page_index,
                        page_segment_started,
                        time.perf_counter(),
                        table_span_fidelity_document_deadline,
                    )
            except (TimeoutError, TypeError, ValueError):
                # US01 is a page transaction.  If one table exhausts the
                # shared budget or rejects its evidence, rebuild every table
                # already attempted on that physical page through the exact
                # flag-off path.  No partial marker or private snapshot may
                # survive, and unrelated pages remain independently eligible.
                rollback_keys = {page_deadline_key}
                if (
                    table_span_fidelity_document_deadline is not None
                    and table_semantics.perf_counter()
                    > table_span_fidelity_document_deadline
                ):
                    rollback_keys = set(table_span_fidelity_page_attempts)
                    table_span_fidelity_state["timed_out"] = True
                table_span_fidelity_disabled_pages.update(rollback_keys)
                rollback_table_attempts(rollback_keys)
                return
            finally:
                if table_budget_active:
                    _suspend_table_span_fidelity_budget(
                        table_span_fidelity_state
                    )

            stamped = stamp(item)
            attempt.update(
                {
                    "item": stamped,
                    "page_index": page_index,
                    "sequence": stamped["_sequence"],
                }
            )
            append_table(page_index, stamped)
            return

        if (
            reference.startswith("#/form_items/")
            or reference.startswith("#/key_value_items/")
            or label in {"form", "key_value_region"}
        ):
            if preserve_graph_items:
                page_index, item = _graph_item(
                    raw_item,
                    page_heights,
                    native_texts,
                )
                body_items[page_index].append(stamp(item))
            return

        if reference.startswith("#/pictures/") or label in {
            "picture",
            "chart",
            "diagram",
        }:
            if preserve_visual_items:
                page_index, item = _visual_item(
                    raw_item,
                    label,
                    refs,
                    page_heights,
                    image_regions,
                    quality_settings,
                    source_document_identity,
                    coordinate_unit,
                    source_text_evidence,
                )
                body_items[page_index].append(stamp(item))
                for key in ("captions", "children"):
                    for child in raw_item.get(key) or []:
                        child_ref = _reference_value(child)
                        if child_ref:
                            seen_refs.add(child_ref)
                return

            page_index, picture_box = _bbox_from_prov(raw_item, page_heights)
            matched_images = [
                _coerce_bbox(region.bbox)
                for region in image_regions.get(page_index, [])
            ]
            child_count = 0
            for child in raw_item.get("children") or []:
                child_ref = _reference_value(child)
                raw_child = refs.get(child_ref)
                if not raw_child or "text" not in raw_child:
                    continue
                seen_refs.add(child_ref)
                child_page, item = _text_item(raw_child, page_heights, native_texts)
                if any(
                    _overlap_of_smaller(item.get("bbox"), image_box) >= 0.55
                    for image_box in matched_images
                ):
                    continue
                body_items[child_page].append(stamp(item))
                child_count += 1
            if not child_count and not matched_images:
                body_items[page_index].append(
                    stamp(
                        {
                            "type": "image",
                            "value": "",
                            "ocr_text": "",
                            "md": "",
                            "bbox": picture_box,
                            "source": "derived",
                            "confidence": None,
                            "detected_text": False,
                            "items": [],
                            "warnings": [
                                "No embedded raster or OCR text was available."
                            ],
                        }
                    )
                )
            return

        if "text" in raw_item:
            for page_index, item in _partition_source_proven_text_item(
                raw_item,
                page_heights,
                native_texts,
                source_text_evidence,
                coordinate_unit=coordinate_unit,
                raw_references=refs,
                source_document_identity=source_document_identity,
            ):
                if item["value"]:
                    body_items[page_index].append(stamp(item))

    for child in (raw.get("body") or {}).get("children") or []:
        visit(_reference_value(child))
    if table_decision_views_sink is not None:
        captured: dict[int, list[dict[str, Any]]] = {}
        for page_index, page_tables in tables.items():
            page_views = []
            for item in page_tables:
                decision_view = table_decision_by_identity.get(id(item))
                if type(decision_view) is not dict:
                    raise ValueError("table predecessor decision map differs")
                page_views.append(decision_view)
            captured[page_index] = page_views
        table_decision_views_sink.clear()
        table_decision_views_sink.update(captured)
    return body_items, tables


def _vertical_overlap_of_smaller(
    first: Mapping[str, Any] | None,
    second: Mapping[str, Any] | None,
) -> float:
    if not first or not second:
        return 0.0
    first_top = float(first["y"])
    first_bottom = first_top + float(first["height"])
    second_top = float(second["y"])
    second_bottom = second_top + float(second["height"])
    overlap = max(
        min(first_bottom, second_bottom) - max(first_top, second_top),
        0.0,
    )
    smaller = min(
        float(first["height"]),
        float(second["height"]),
    )
    return overlap / smaller if smaller else 0.0


def _reconcile_fragmented_layout_with_page_ocr(
    body_items: dict[int, list[dict[str, Any]]],
    image_regions: Mapping[int, Sequence[ImageRegion]],
    settings: Settings,
) -> None:
    """Join layout fragments when one confident page-OCR line covers them.

    Layout engines occasionally split a date, title, or wrapped line into
    several items. This repair is geometry/text driven and never replaces
    machine-readable native PDF text.
    """

    for page_index, regions in image_regions.items():
        page_items = body_items.get(page_index, [])
        if len(page_items) < 2:
            continue
        for region in regions:
            if _region_role(region) != "page_source":
                continue
            for line in region.lines:
                accepted, _reason = _ocr_line_primary_decision(line, settings)
                if not accepted:
                    continue
                line_text = str(line.text or "").strip()
                line_normalized = _normalized_search_text(line_text)
                line_box = _coerce_bbox(line.bbox)
                if not line_normalized or not line_box:
                    continue

                fragments = [
                    item
                    for item in page_items
                    if item.get("type") in {"text", "heading"}
                    and item.get("source") != "native"
                    and isinstance(item.get("bbox"), Mapping)
                    and (
                        _overlap_of_smaller(item.get("bbox"), line_box) >= 0.2
                        or (
                            _vertical_overlap_of_smaller(
                                item.get("bbox"),
                                line_box,
                            )
                            >= 0.65
                            and _intersection_area(
                                item.get("bbox"),
                                line_box,
                            )
                            > 0
                        )
                    )
                ]
                if len(fragments) < 2:
                    continue

                fragment_text = " ".join(
                    str(item.get("value") or "")
                    for item in sorted(
                        fragments,
                        key=lambda item: (
                            float((item.get("bbox") or {}).get("x", 0.0)),
                            float((item.get("bbox") or {}).get("y", 0.0)),
                        ),
                    )
                )
                fragment_normalized = _normalized_search_text(fragment_text)
                if not fragment_normalized:
                    continue
                line_tokens = line_normalized.split()
                fragment_tokens = fragment_normalized.split()
                line_token_set = set(line_tokens)
                fragment_token_set = set(fragment_tokens)
                line_coverage = sum(
                    token in fragment_token_set for token in line_tokens
                ) / len(line_tokens)
                fragment_coverage = sum(
                    token in line_token_set for token in fragment_tokens
                ) / len(fragment_tokens)
                similarity = SequenceMatcher(
                    None,
                    line_normalized,
                    fragment_normalized,
                ).ratio()
                if min(line_coverage, fragment_coverage) < 0.9 or similarity < 0.72:
                    continue

                # Preserve the semantic type of the fragment carrying the
                # most useful text, and retain the earliest layout sequence.
                anchor = max(
                    fragments,
                    key=lambda item: (
                        len(
                            _normalized_search_text(
                                str(item.get("value") or "")
                            ).split()
                        ),
                        len(str(item.get("value") or "")),
                    ),
                )
                old_values = [str(item.get("value") or "") for item in fragments]
                anchor["value"] = line_text
                if anchor.get("type") == "heading":
                    level = min(
                        max(int(anchor.get("level") or 1), 1),
                        6,
                    )
                    anchor["md"] = f"{'#' * level} {line_text}"
                else:
                    anchor["md"] = line_text
                anchor["bbox"] = line_box
                anchor["source"] = "ocr"
                anchor["confidence"] = line.confidence
                anchor["_sequence"] = min(
                    (
                        float(item["_sequence"])
                        for item in fragments
                        if isinstance(item.get("_sequence"), (int, float))
                    ),
                    default=float(anchor.get("_sequence") or 0),
                )
                anchor["layout_fragments"] = old_values
                concerns = list(anchor.get("parse_concerns") or [])
                if "layout_fragments_reconciled_by_page_ocr" not in concerns:
                    concerns.append("layout_fragments_reconciled_by_page_ocr")
                anchor["parse_concerns"] = concerns
                fragment_ids = {id(item) for item in fragments if item is not anchor}
                page_items[:] = [
                    item for item in page_items if id(item) not in fragment_ids
                ]


def _phase03_table_decision_views(
    tables: Mapping[int, Sequence[dict[str, Any]]],
    captured_views: Mapping[int, Sequence[dict[str, Any]]] | None = None,
    table_span_fidelity_state: dict[str, Any] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """Carry the mint-time positional map or replay a whole affected page.

    This seam deliberately performs only constant-time identity and marker
    checks.  Full graph admission belongs to minting and the later atomic
    detacher; no new deadline or recursive validator is introduced before a
    Phase 03 semantic consumer.
    """

    resolved: dict[int, list[dict[str, Any]]] = {}
    extra_pages = (
        set(captured_views) - set(tables)
        if captured_views is not None
        else set()
    )
    force_protected_replay = bool(extra_pages) and type(
        table_span_fidelity_state
    ) is not dict
    for page_index, page_tables_sequence in tables.items():
        if type(page_tables_sequence) is not list:
            raise TypeError("table decision page container differs")
        page_tables = page_tables_sequence
        supplied = (
            captured_views.get(page_index)
            if captured_views is not None
            else None
        )
        aligned = (
            type(supplied) is list
            and len(supplied) == len(page_tables)
            and page_index not in extra_pages
            and not force_protected_replay
        )
        page_views: list[dict[str, Any]] = []
        if aligned:
            for table, decision_view in zip(
                page_tables,
                supplied,
                strict=True,
            ):
                if type(table) is not dict or type(decision_view) is not dict:
                    aligned = False
                    break
                has_evidence = "table_evidence" in table
                has_snapshot = "_p04_predecessor_snapshot" in table
                if has_evidence != has_snapshot:
                    aligned = False
                    break
                if has_evidence:
                    snapshot = table.get("_p04_predecessor_snapshot")
                    if (
                        type(table.get("table_evidence")) is not dict
                        or type(snapshot) is not dict
                        or snapshot is table
                        or decision_view is not snapshot
                    ):
                        aligned = False
                        break
                    page_views.append(snapshot)
                elif decision_view is table:
                    page_views.append(table)
                else:
                    aligned = False
                    break
        elif not force_protected_replay and supplied is None and not any(
            type(table) is dict
            and (
                "table_evidence" in table
                or "_p04_predecessor_snapshot" in table
            )
            for table in page_tables
        ):
            # Default-off and pre-P04 callers need no private side map.
            aligned = True
            page_views = list(page_tables)

        if aligned:
            resolved[page_index] = page_views
            continue

        # Stage the exact predecessor replay for every marked table on this
        # page. Commit the positional list only after every snapshot identity
        # is suitable, so failure cannot produce a mixed/duplicated page.
        replayed: list[dict[str, Any]] = []
        for table in page_tables:
            if type(table) is not dict:
                raise TypeError("table decision source differs")
            has_evidence = "table_evidence" in table
            has_snapshot = "_p04_predecessor_snapshot" in table
            if has_evidence or has_snapshot:
                snapshot = table.get("_p04_predecessor_snapshot")
                if (
                    not has_evidence
                    or not has_snapshot
                    or type(snapshot) is not dict
                    or snapshot is table
                    or "table_evidence" in snapshot
                    or "_p04_predecessor_snapshot" in snapshot
                ):
                    raise ValueError("table predecessor replay differs")
                replayed.append(deepcopy(snapshot))
            else:
                replayed.append(table)
        page_tables[:] = replayed
        if type(table_span_fidelity_state) is dict:
            table_span_fidelity_state["custody_rejected"] = True
        if type(captured_views) is dict:
            captured_views[page_index] = list(replayed)
        resolved[page_index] = list(replayed)

    if extra_pages:
        if type(table_span_fidelity_state) is dict:
            table_span_fidelity_state["custody_rejected"] = True
        for page_index in extra_pages:
            if type(captured_views) is dict:
                captured_views.pop(page_index, None)
    return resolved


def _supplement_unrepresented_raster_ocr(
    body_items: dict[int, list[dict[str, Any]]],
    tables: Mapping[int, Sequence[dict[str, Any]]],
    image_regions: Mapping[int, Sequence[ImageRegion]],
    decorations: Mapping[int, Sequence[dict[str, Any]]] | None = None,
    settings: Settings | None = None,
    *,
    source_document_identity: str | None = None,
    table_decision_views: Mapping[
        int, Sequence[dict[str, Any]]
    ]
    | None = None,
    table_span_fidelity_state: dict[str, Any] | None = None,
) -> None:
    """Restore page-source OCR omitted by layout without duplicating text.

    A page-source raster can come from a direct image upload, a scanned PDF
    image object, or a selectively rendered PDF page. Nearby native/layout
    items remain authoritative. Content-region OCR is handled by the shared
    visual normalizer and never leaks into page prose through this fallback.
    """

    quality_settings = settings or Settings()
    # Resolve the governed table side map so a malformed P04 predecessor still
    # fails closed at its existing custody boundary.  Supplemental OCR is not
    # deleted here merely because it lies inside a table region: complete
    # source-line/cell ownership is proved later by terminal source alignment.
    _phase03_table_decision_views(
        tables,
        table_decision_views,
        table_span_fidelity_state,
    )
    for page_index, regions in image_regions.items():
        representations: list[tuple[dict[str, Any] | None, str]] = []
        subordinate_visual_boxes: list[dict[str, Any]] = []
        for item in body_items.get(page_index, []):
            if (
                item.get("region_role") == "content_region"
                and not item.get("include_ocr_in_primary")
                and isinstance(item.get("bbox"), Mapping)
            ):
                subordinate_visual_boxes.append(item["bbox"])
            text = "\n".join(
                str(value or "")
                for value in (
                    item.get("value"),
                    item.get("ocr_text"),
                    item.get("caption"),
                )
                if value
            )
            if text:
                representations.append((item.get("bbox"), text))
        for item in (decorations or {}).get(page_index, []):
            text = str(item.get("value") or "")
            if text:
                representations.append((item.get("bbox"), text))

        for region in regions:
            if _region_role(region) != "page_source":
                continue
            for line_index, line in enumerate(region.lines):
                line_text = str(line.text or "").strip()
                line_box = _coerce_bbox(line.bbox)
                accepted, _reason = _ocr_line_primary_decision(
                    line,
                    quality_settings,
                )
                if not accepted:
                    continue
                if any(
                    _center_inside(line_box, visual_box)
                    for visual_box in subordinate_visual_boxes
                ):
                    continue
                needle = _normalized_search_text(line_text)
                if not needle:
                    continue

                nearby_text = " ".join(
                    text
                    for box, text in representations
                    if (
                        box is None
                        or line_box is None
                        or _overlap_of_smaller(line_box, box) >= 0.5
                        or _vertical_overlap_of_smaller(line_box, box) >= 0.7
                    )
                )
                haystack = _normalized_search_text(nearby_text)
                compact_needle = needle.replace(" ", "")
                compact_haystack = haystack.replace(" ", "")
                needle_tokens = needle.split()
                haystack_tokens = set(haystack.split())
                token_coverage = (
                    sum(token in haystack_tokens for token in needle_tokens)
                    / len(needle_tokens)
                    if needle_tokens
                    else 0.0
                )
                if (
                    needle in haystack
                    or (len(compact_needle) >= 4 and compact_needle in compact_haystack)
                    or (len(needle_tokens) >= 4 and token_coverage >= 0.8)
                    or (2 <= len(needle_tokens) < 4 and token_coverage >= 0.85)
                ):
                    continue

                fallback = {
                    "type": "text",
                    "value": line_text,
                    "md": line_text,
                    "bbox": line_box,
                    "source": "ocr",
                    "confidence": line.confidence,
                    "label": "ocr_text",
                    "raw_ocr_text": line_text,
                    "parse_concerns": ["layout_omission_recovered_by_ocr"],
                }
                if source_document_identity is not None:
                    from app.services.source_text_alignment import (
                        build_supplemental_ocr_contributor,
                    )

                    contributor = build_supplemental_ocr_contributor(
                        source_document_identity=source_document_identity,
                        page_index=page_index,
                        region_object_index=region.object_index,
                        region_origin=str(region.region_origin or ""),
                        region_role=_region_role(region),
                        line_index=line_index,
                        ocr_pass=str(line.ocr_pass or "standard"),
                        coordinate_unit=str(
                            region.coordinate_unit or "pt"
                        ),
                        bbox=line_box,
                        raw_text=line_text,
                        confidence=line.confidence,
                    )
                    if contributor is not None:
                        fallback["ocr_contributor"] = contributor
                body_items[page_index].append(fallback)
                representations.append((line_box, line_text))


def _infer_image_headings(
    body_items: Mapping[int, Sequence[dict[str, Any]]],
    page_heights: Mapping[int, float],
    settings: Settings,
) -> None:
    """Promote only conspicuously large, confident recovered raster text."""

    for page_index, items in body_items.items():
        page_height = max(float(page_heights.get(page_index, 0.0)), 1.0)
        text_heights = sorted(
            float(item["bbox"]["height"])
            for item in items
            if item.get("type") == "text"
            and isinstance(item.get("bbox"), Mapping)
            and float(item["bbox"].get("height", 0.0)) > 0
        )
        if not text_heights:
            continue
        middle = len(text_heights) // 2
        median_height = (
            text_heights[middle]
            if len(text_heights) % 2
            else (text_heights[middle - 1] + text_heights[middle]) / 2
        )

        for item in items:
            if (
                item.get("type") != "text"
                or item.get("label") != "ocr_text"
                or not isinstance(item.get("bbox"), Mapping)
            ):
                continue
            value = _WHITESPACE_RE.sub(
                " ",
                str(item.get("value") or ""),
            ).strip()
            box = item["bbox"]
            confidence = item.get("confidence")
            try:
                confidence_value = float(confidence)
                height = float(box["height"])
                y = float(box["y"])
            except (KeyError, TypeError, ValueError):
                continue
            words = value.split()
            if (
                confidence_value < settings.image_heading_min_confidence
                or not 1 <= len(words) <= 14
                or len(value) > 160
                or value.endswith(":")
                or y > page_height * 0.8
            ):
                continue

            relative_to_body = (
                median_height > 0
                and height >= median_height * settings.image_heading_height_ratio
            )
            conspicuous_page_height = (
                height / page_height >= settings.image_heading_min_page_height_ratio * 2
            )
            if not (relative_to_body or conspicuous_page_height):
                continue

            item["type"] = "heading"
            item["level"] = 1
            item["label"] = "inferred_heading"
            item["md"] = f"# {value}"
            concerns = list(item.get("parse_concerns") or [])
            if "heading_inferred_from_image_geometry" not in concerns:
                concerns.append("heading_inferred_from_image_geometry")
            item["parse_concerns"] = concerns


def _reconcile_image_decorations(
    headers: Mapping[int, dict[str, Any]],
    footers: Mapping[int, dict[str, Any]],
    image_regions: Mapping[int, Sequence[ImageRegion]],
) -> None:
    """Prefer page OCR for a near-identical non-native header/footer."""

    for decorations in (headers, footers):
        for page_index, item in decorations.items():
            if item.get("source") == "native":
                continue
            item_box = item.get("bbox")
            matching = [
                line
                for region in image_regions.get(page_index, [])
                if _region_role(region) == "page_source"
                for line in region.lines
                if _overlap_of_smaller(
                    _coerce_bbox(line.bbox),
                    item_box,
                )
                >= 0.8
            ]
            if not matching:
                continue
            matching.sort(
                key=lambda line: (
                    float(line.bbox.get("y", 0.0)),
                    float(line.bbox.get("x", 0.0)),
                )
            )
            ocr_text = "\n".join(
                line.text.strip() for line in matching if line.text.strip()
            )
            layout_text = str(item.get("value") or "").strip()
            ocr_normalized = _normalized_search_text(ocr_text)
            layout_normalized = _normalized_search_text(layout_text)
            if not ocr_normalized or not layout_normalized:
                continue
            similarity = SequenceMatcher(
                None,
                ocr_normalized,
                layout_normalized,
            ).ratio()
            if similarity < 0.9 or ocr_text == layout_text:
                continue

            item["layout_value"] = layout_text
            item["value"] = ocr_text
            item["md"] = ocr_text
            item["source"] = "ocr"
            item["confidence"] = _line_confidence(matching)
            item.setdefault("parse_concerns", []).append(
                "layout_text_corrected_by_full_page_ocr"
            )


def _merge_tables(
    docling_tables: Mapping[int, Sequence[dict[str, Any]]],
    vector_tables: Mapping[int, Sequence[RawTable]],
    *,
    table_span_fidelity_enabled: bool = False,
    table_evidence_reconciliation_enabled: bool = False,
    table_decision_views: Mapping[
        int, Sequence[dict[str, Any]]
    ]
    | None = None,
    table_decision_views_sink: dict[
        int, list[dict[str, Any]]
    ]
    | None = None,
    table_span_fidelity_state: dict[str, Any] | None = None,
    selected_vector_sink: dict[int, list[dict[str, Any]]] | None = None,
    selected_vector_source_sha256: str | None = None,
) -> dict[int, list[dict[str, Any]]]:
    from app.services.table_semantics import reconcile_table_candidates
    merged: dict[int, list[dict[str, Any]]] = defaultdict(list)
    page_indexes = set(docling_tables) | set(vector_tables)
    owned_docling = {
        page_index: list(docling_tables.get(page_index, []))
        for page_index in page_indexes
    }
    source_decisions = _phase03_table_decision_views(
        owned_docling,
        table_decision_views,
        table_span_fidelity_state,
    )
    copied_docling: dict[int, list[dict[str, Any]]] = {}
    copied_docling_decisions: dict[int, list[dict[str, Any]]] = {}
    for page_index in page_indexes:
        copied_page = []
        copied_views = []
        for item, decision_view in zip(
            owned_docling.get(page_index, []),
            source_decisions.get(page_index, []),
            strict=True,
        ):
            copied = dict(item)
            copied_page.append(copied)
            copied_views.append(
                copied if decision_view is item else decision_view
            )
        copied_docling[page_index] = copied_page
        copied_docling_decisions[page_index] = copied_views
    merged_decisions: dict[int, list[dict[str, Any]]] = {}
    for page_index in page_indexes:
        page_docling = copied_docling.get(page_index, [])
        page_decisions = copied_docling_decisions.get(page_index, [])
        decision_by_identity: dict[int, dict[str, Any]] = {
            id(table): decision
            for table, decision in zip(
                page_docling,
                page_decisions,
                strict=True,
            )
        }
        merged[page_index].extend(page_docling)
        for raw_table in vector_tables.get(page_index, []):
            candidate = _vector_table_item(
                raw_table,
                table_span_fidelity_enabled=table_span_fidelity_enabled,
            )
            if any(
                decision is not None
                and _overlap_of_smaller(
                    candidate.get("bbox"), decision.get("bbox")
                )
                >= 0.55
                for decision in page_decisions
            ) and not table_evidence_reconciliation_enabled:
                continue
            merged[page_index].append(candidate)
            decision_by_identity[id(candidate)] = candidate

        def decision_sort_key(item: dict[str, Any]) -> tuple[float, float]:
            decision = decision_by_identity.get(id(item))
            if decision is None:
                raise ValueError("table decision identity differs")
            box = decision.get("bbox")
            return (
                float((box or {}).get("y", 0.0)),
                float((box or {}).get("x", 0.0)),
            )

        merged[page_index].sort(
            key=decision_sort_key
        )
        merged_decisions[page_index] = []
        for item in merged[page_index]:
            decision = decision_by_identity.get(id(item))
            if decision is None:
                raise ValueError("table decision identity differs")
            merged_decisions[page_index].append(decision)
    reconciliation_options: dict[str, Any] = {
        "table_span_fidelity_enabled": table_span_fidelity_enabled,
        "table_evidence_reconciliation_enabled": (
            table_evidence_reconciliation_enabled
        ),
    }
    if selected_vector_sink is not None:
        reconciliation_options["selected_vector_sink"] = selected_vector_sink
        reconciliation_options["selected_vector_source_sha256"] = (
            selected_vector_source_sha256
        )
    merged = reconcile_table_candidates(
        merged,
        docling_tables,
        vector_tables,
        **reconciliation_options,
    )
    if table_evidence_reconciliation_enabled:
        merged_decisions = {}
        for page_index, page_tables in merged.items():
            page_views = []
            for item in page_tables:
                snapshot = item.get("_p04_predecessor_snapshot")
                page_views.append(
                    snapshot
                    if type(item.get("table_evidence")) is dict
                    and type(snapshot) is dict
                    else item
                )
            merged_decisions[page_index] = page_views
    if table_decision_views_sink is not None:
        table_decision_views_sink.clear()
        table_decision_views_sink.update(
            _phase03_table_decision_views(
                merged,
                merged_decisions,
                table_span_fidelity_state,
            )
        )
    return merged


def _attach_image_to_table(
    table: dict[str, Any],
    image: dict[str, Any],
) -> None:
    predecessor_snapshot = table.get("_p04_predecessor_snapshot")
    if type(predecessor_snapshot) is dict:
        _attach_image_to_table(predecessor_snapshot, deepcopy(image))
    table.setdefault("embedded_images", []).append(image)
    row_boxes = table.get("row_bboxes") or []
    target_row: int | None = None
    for row_index, row_box in enumerate(row_boxes):
        if _center_inside(image.get("bbox"), row_box):
            target_row = row_index
            break

    rows: list[list[str]] = table.get("rows") or []
    image_text = str(
        image.get("cleaned_ocr_text") or image.get("ocr_text") or ""
    ).strip()
    if image_text:
        if target_row is None or target_row >= len(rows):
            width = max(int(table.get("column_count") or 1), 1)
            rows.append([image_text] + [""] * (width - 1))
        else:
            if not rows[target_row]:
                rows[target_row].append(image_text)
            elif rows[target_row][0]:
                rows[target_row][0] = f"{rows[target_row][0]}\n{image_text}"
            else:
                rows[target_row][0] = image_text
        table["source"] = "mixed"
        table["row_count"] = len(rows)
        table["rows"] = rows
        # Spanned Docling cells cannot safely be mutated using a row-only
        # insertion, so supplemental rows use the dense renderer here.
        if target_row is None:
            table["cells"] = []
        _refresh_table_serializations(table)


def _merge_body_items(
    pages: list[dict[str, Any]],
    body_items: Mapping[int, Sequence[dict[str, Any]]],
    tables: Mapping[int, Sequence[dict[str, Any]]],
    image_regions: Mapping[int, Sequence[ImageRegion]],
    headers: Mapping[int, dict[str, Any]],
    footers: Mapping[int, dict[str, Any]],
    settings: Settings | None = None,
    source_document_identity: str | None = None,
    *,
    table_decision_views: Mapping[
        int, Sequence[dict[str, Any]]
    ]
    | None = None,
    table_span_fidelity_state: dict[str, Any] | None = None,
) -> None:
    quality_settings = settings or Settings()
    resolved_table_views = _phase03_table_decision_views(
        tables,
        table_decision_views,
        table_span_fidelity_state,
    )
    for page in pages:
        page_index = int(page["page_index"])
        page_tables = [dict(item) for item in tables.get(page_index, [])]
        page_table_views = list(resolved_table_views.get(page_index, []))
        if len(page_table_views) != len(page_tables):
            raise ValueError("table decision view count differs")
        decision_by_identity = {
            id(table): decision
            for table, decision in zip(
                page_tables,
                page_table_views,
                strict=True,
            )
        }
        page_body = [dict(item) for item in body_items.get(page_index, [])]

        unconsumed_images: list[dict[str, Any]] = []
        detected_images: list[dict[str, Any]] = []
        normalized_images = [
            (
                image_number,
                region,
                _image_item(
                    region,
                    quality_settings,
                    source_document_identity,
                ),
            )
            for image_number, region in enumerate(
                image_regions.get(page_index, []),
                start=1,
            )
        ]
        if normalized_images and any(
            "table_evidence" in table
            or "_p04_predecessor_snapshot" in table
            for table in page_tables
        ):
            # Build and sort the page OCR index once. Images are complete P03
            # values before any marked table mirrors one into its predecessor
            # snapshot; the normal later document pass remains idempotent.
            _enrich_ocr_confidence(
                [
                    {
                        "page_index": page_index,
                        "items": [entry[2] for entry in normalized_images],
                    }
                ],
                image_regions,
            )
        for image_number, region, image in normalized_images:
            detected_images.append(
                {
                    **image,
                    "id": f"p{page_index}-image{image_number}",
                }
            )
            page["warnings"].extend(region.warnings)
            if _region_role(region) == "page_source":
                # The raster/render is page provenance, not an embedded
                # content object. Residual OCR lines have already been merged
                # individually, so adding the full page would duplicate all
                # recognized text as one synthetic item.
                continue
            # A layout-detected visual and its OCR region describe the same
            # content object. Keep the normalized visual in reading order and
            # the OCR evidence in ``detected_images``.
            represented_as_visual = any(
                item.get("region_role") == "content_region"
                and _overlap_of_smaller(
                    item.get("bbox"),
                    image.get("bbox"),
                )
                >= 0.55
                for item in page_body
            )
            if represented_as_visual:
                continue
            containing = next(
                (
                    table
                    for table, table_view in zip(
                        page_tables,
                        page_table_views,
                        strict=True,
                    )
                    if _center_inside(
                        image.get("bbox"), table_view.get("bbox")
                    )
                ),
                None,
            )
            if containing is not None:
                _attach_image_to_table(containing, image)
            else:
                unconsumed_images.append(image)
        page["detected_images"] = detected_images

        content = page_body + page_tables + unconsumed_images

        def decision_bbox(item: Mapping[str, Any]) -> Any:
            if id(item) not in decision_by_identity:
                return item.get("bbox")
            decision = decision_by_identity[id(item)]
            return decision.get("bbox")

        sequenced = [
            item for item in content if isinstance(item.get("_sequence"), (int, float))
        ]
        by_vertical_position = sorted(
            (
                (
                    float((decision_bbox(item) or {}).get("y", 0.0)),
                    float(item["_sequence"]),
                )
                for item in sequenced
            ),
            key=lambda value: value[0],
        )

        def reading_key(item: Mapping[str, Any]) -> tuple[float, float, int]:
            if isinstance(item.get("_sequence"), (int, float)):
                order = float(item["_sequence"])
            elif by_vertical_position:
                item_y = float((decision_bbox(item) or {}).get("y", 0.0))
                following = next(
                    (
                        sequence_value
                        for y, sequence_value in by_vertical_position
                        if y > item_y
                    ),
                    None,
                )
                order = (
                    following - 0.25
                    if following is not None
                    else max(value for _, value in by_vertical_position) + 0.25
                )
            else:
                order = 0.0
            return (
                order,
                float((decision_bbox(item) or {}).get("x", 0.0)),
                0 if item.get("type") == "table" else 1,
            )

        content.sort(key=reading_key)

        # A key-value region can appear immediately before its visual key in
        # Docling's hierarchy. Repair the common same-line case using geometry
        # (for example, a left-hand ``Defect ID:`` followed by its value).
        for index in range(len(content) - 1):
            value_item = content[index]
            key_item = content[index + 1]
            value_box = value_item.get("bbox")
            key_box = key_item.get("bbox")
            key_text = str(key_item.get("value") or "").strip()
            if (
                value_item.get("type") == "text"
                and key_item.get("type") == "text"
                and key_text.endswith(":")
                and value_box
                and key_box
                and float(key_box["x"]) < float(value_box["x"])
            ):
                overlap_height = _intersection_area(
                    {
                        "x": 0.0,
                        "y": float(value_box["y"]),
                        "width": 1.0,
                        "height": float(value_box["height"]),
                    },
                    {
                        "x": 0.0,
                        "y": float(key_box["y"]),
                        "width": 1.0,
                        "height": float(key_box["height"]),
                    },
                )
                smaller_height = min(
                    float(value_box["height"]), float(key_box["height"])
                )
                if smaller_height and overlap_height / smaller_height >= 0.5:
                    content[index], content[index + 1] = key_item, value_item

        if page_index in headers:
            content.insert(0, dict(headers[page_index]))
        if page_index in footers:
            content.append(dict(footers[page_index]))

        for reading_order, item in enumerate(content):
            item.pop("_sequence", None)
            item["id"] = f"p{page_index}-i{reading_order + 1}"
            item["reading_order"] = reading_order
            predecessor_snapshot = item.get("_p04_predecessor_snapshot")
            if type(predecessor_snapshot) is dict:
                predecessor_snapshot.pop("_sequence", None)
                predecessor_snapshot["id"] = item["id"]
                predecessor_snapshot["reading_order"] = reading_order
        page["items"] = content


def _normalize_table_of_contents(
    page: dict[str, Any],
    native_text: str,
) -> None:
    lines = [line.strip() for line in native_text.splitlines() if line.strip()]
    try:
        heading_index = next(
            index
            for index, line in enumerate(lines)
            if line.casefold() == "table of contents"
        )
    except StopIteration:
        return

    entries = [line for line in lines[heading_index + 1 :] if _TOC_ENTRY_RE.match(line)]
    if len(entries) < 3:
        return

    existing_content = [
        item for item in page["items"] if item.get("type") not in {"header", "footer"}
    ]
    content_box = _bbox_union(item.get("bbox") for item in existing_content)
    heading_box = next(
        (
            item.get("bbox")
            for item in existing_content
            if str(item.get("value") or "").casefold() == "table of contents"
        ),
        content_box,
    )
    normalized_entries = []
    for entry in entries:
        number = entry.split(maxsplit=1)[0]
        normalized_entries.append(
            {
                "value": entry,
                "level": max(number.count("."), 0),
                "source": "native",
                "bbox": None,
            }
        )

    replacement = [
        {
            "type": "heading",
            "value": "Table of Contents",
            "md": "# Table of Contents",
            "level": 1,
            "bbox": heading_box,
            "source": "native",
            "confidence": None,
        },
        {
            "type": "list",
            "value": entries,
            "items": normalized_entries,
            "ordered": False,
            "md": "\n".join(
                f"{'  ' * entry['level']}- {entry['value']}"
                for entry in normalized_entries
            ),
            "bbox": content_box,
            "source": "native",
            "confidence": None,
        },
    ]
    header = [item for item in page["items"] if item.get("type") == "header"]
    footer = [item for item in page["items"] if item.get("type") == "footer"]
    page["items"] = header + replacement + footer
    for reading_order, item in enumerate(page["items"]):
        item["id"] = f"p{page['page_index']}-i{reading_order + 1}"
        item["reading_order"] = reading_order


def _enrich_ocr_confidence(
    pages: list[dict[str, Any]],
    image_regions: Mapping[int, Sequence[ImageRegion]],
) -> None:
    """Attach matched OCR confidence without changing source coordinates."""

    def candidate_text(value: Mapping[str, Any]) -> tuple[str, str] | None:
        candidate = value.get("value")
        if not isinstance(candidate, str):
            candidate = value.get("text")
        if not isinstance(candidate, str):
            return None
        normalized_candidate = _normalized_search_text(candidate)
        if not normalized_candidate:
            return None
        return normalized_candidate, normalized_candidate.replace(" ", "")

    def text_matches(
        candidate: tuple[str, str] | None,
        normalized_line: str,
        compact_line: str,
    ) -> bool:
        if candidate is None or not normalized_line:
            return False
        normalized_candidate, compact_candidate = candidate
        if (
            normalized_candidate in normalized_line
            or normalized_line in normalized_candidate
        ):
            return True
        return min(len(compact_candidate), len(compact_line)) >= 4 and (
            compact_candidate in compact_line or compact_line in compact_candidate
        )

    def update_value(
        value: Any,
        page_lines: Sequence[tuple[float, float, int, Any, str, str]],
        page_line_centers_y: Sequence[float],
        active_container_ids: set[int] | None = None,
        depth: int = 0,
    ) -> None:
        if depth > 128:
            return
        if active_container_ids is None:
            active_container_ids = set()
        if isinstance(value, list):
            container_id = id(value)
            if container_id in active_container_ids:
                return
            active_container_ids.add(container_id)
            try:
                for entry in value:
                    update_value(
                        entry,
                        page_lines,
                        page_line_centers_y,
                        active_container_ids,
                        depth + 1,
                    )
            finally:
                active_container_ids.remove(container_id)
            return
        if not isinstance(value, dict):
            return
        container_id = id(value)
        if container_id in active_container_ids:
            return
        active_container_ids.add(container_id)

        try:
            table_evidence = value.get("table_evidence")
            p04_us01_cells_are_custodied = (
                type(table_evidence) is dict
                and frozenset(table_evidence) == _P04_US01_TABLE_EVIDENCE_KEYS
                and table_evidence.get("policy_id") == "p04-table-evidence-v1"
                and table_evidence.get("version") == "1.1"
                and type(table_evidence.get("scope")) is list
                and table_evidence.get("scope")
                in (
                    ["P04-US01"],
                    ["P04-US01", "P04-US02"],
                    ["P04-US01", "P04-US02", "P04-US04"],
                    [
                        "P04-US01",
                        "P04-US02",
                        "P04-US04",
                        "P04-US03",
                    ],
                )
                and type(table_evidence.get("status")) is str
                and table_evidence.get("status")
                in {"valid", "unresolved", "structural_failure"}
                and type(value.get("cells")) is list
            )

            box = value.get("bbox")
            normalized_box = (
                _coerce_bbox(box)
                if isinstance(box, Mapping)
                and value.get("confidence") is None
                and page_lines
                else None
            )
            if (
                normalized_box is not None
                and value.get("confidence") is None
                and page_lines
            ):
                left = float(normalized_box["x"])
                top = float(normalized_box["y"])
                right = left + float(normalized_box["width"])
                bottom = top + float(normalized_box["height"])
                first = bisect_left(page_line_centers_y, top)
                last = bisect_right(page_line_centers_y, bottom)
                candidate = candidate_text(value)
                matching_records = [
                    record
                    for record in page_lines[first:last]
                    if left <= record[1] <= right
                    and text_matches(candidate, record[4], record[5])
                ]
                # The spatial index is ordered by vertical center. Restore the
                # source OCR order before calculating the weighted confidence so
                # predecessor floating-point summation and rounding stay exact.
                matching_records.sort(key=lambda record: record[2])
                confidence = _line_confidence(
                    [record[3] for record in matching_records]
                )
                if confidence is not None:
                    value["confidence"] = confidence
                    value["confidence_source"] = "matched_page_ocr"

            for key, nested in value.items():
                # Docling metadata and annotations are intentionally opaque. Keep
                # their coordinates, provenance, and source labels byte-for-byte
                # equivalent to the engine payload instead of treating them as
                # normalized content geometry.
                if key in {"annotations", "meta", "metadata"}:
                    continue
                # P04 private graphs and public evidence are custody records,
                # never shared confidence targets. Treat them as opaque even
                # when a hostile marker is cyclic; replay remains responsible
                # for accepting or removing the marker.
                if key == "table_evidence" or (
                    type(key) is str and key.startswith("_p04_")
                ):
                    continue
                # P04-US01 hashes the exact cell dictionaries before this shared
                # Phase 03 confidence pass. Keep the entire public cell
                # projection immutable for an exactly shaped custody marker.
                if p04_us01_cells_are_custodied and key == "cells":
                    continue
                update_value(
                    nested,
                    page_lines,
                    page_line_centers_y,
                    active_container_ids,
                    depth + 1,
                )
        finally:
            active_container_ids.remove(container_id)

    for page in pages:
        page_index = int(page["page_index"])
        indexed_page_lines: list[tuple[float, float, int, Any, str, str]] = []
        for source_index, line in enumerate(
            line
            for region in image_regions.get(page_index, [])
            for line in region.lines
        ):
            box = _coerce_bbox(getattr(line, "bbox", None))
            if box is None:
                continue
            normalized_line = _normalized_search_text(
                str(getattr(line, "text", "") or "")
            )
            indexed_page_lines.append(
                (
                    float(box["y"]) + float(box["height"]) / 2,
                    float(box["x"]) + float(box["width"]) / 2,
                    source_index,
                    line,
                    normalized_line,
                    normalized_line.replace(" ", ""),
                )
            )
        indexed_page_lines.sort(key=lambda record: record[0])
        update_value(
            page,
            indexed_page_lines,
            [record[0] for record in indexed_page_lines],
        )


def _apply_image_provenance_and_units(
    pages: list[dict[str, Any]],
    image_regions: Mapping[int, Sequence[ImageRegion]],
) -> None:
    """Finalize direct-raster provenance after shared confidence enrichment."""

    def update_value(value: Any) -> None:
        if isinstance(value, list):
            for entry in value:
                update_value(entry)
            return
        if not isinstance(value, dict):
            return

        if {"x", "y", "width", "height"}.issubset(value):
            value["unit"] = "px"

        source = value.get("source")
        if source in {"native", "mixed"}:
            value["source"] = "ocr"

        for key, nested in value.items():
            if key in {"annotations", "meta", "metadata"}:
                continue
            update_value(nested)

    _enrich_ocr_confidence(pages, image_regions)
    for page in pages:
        page["unit"] = "px"
        update_value(page)


def _clean_image_checkbox_markers(
    pages: Sequence[dict[str, Any]],
) -> None:
    marker_pattern = re.compile(
        r"^(?:\[\s*(?:x)?\s*\]\s*)+",
        re.IGNORECASE,
    )
    for page in pages:
        for item in page.get("items") or []:
            label = str(item.get("label") or "")
            if label not in {"checkbox_selected", "checkbox_unselected"}:
                continue
            value = str(item.get("value") or "")
            cleaned = marker_pattern.sub("", value).strip()
            marker = "[x]" if label == "checkbox_selected" else "[ ]"
            normalized = f"{marker} {cleaned}".rstrip()
            item["value"] = normalized
            item["md"] = normalized


# Canonical shared-service names. The older image-prefixed names remain as
# private compatibility aliases for downstream tests/extensions.
_supplement_unrepresented_page_ocr = _supplement_unrepresented_raster_ocr
_infer_recovered_headings = _infer_image_headings
_reconcile_page_decorations = _reconcile_image_decorations
_clean_checkbox_markers = _clean_image_checkbox_markers


def _analyze_shared_pages(context: SharedAnalysisContext) -> None:
    """Run all format-neutral analysis and reconciliation stages in one place."""

    from app.services import table_semantics
    from app.services.table_semantics import (
        seal_table_pages,
        table_span_fidelity_document_deadline,
    )

    if context.table_span_fidelity_page_deadlines is None:
        context.table_span_fidelity_page_deadlines = {}
    if context.table_span_fidelity_state is None:
        context.table_span_fidelity_state = {}
    if (
        context.settings.table_span_fidelity_enabled
        and context.table_span_fidelity_document_deadline is None
    ):
        context.table_span_fidelity_document_deadline = (
            table_span_fidelity_document_deadline()
        )
    if (
        context.settings.table_span_fidelity_enabled
        and context.table_span_fidelity_document_deadline is not None
        and _TABLE_SPAN_FIDELITY_SUSPENDED_AT_KEY
        not in context.table_span_fidelity_state
        and table_semantics.perf_counter()
        > context.table_span_fidelity_document_deadline
    ):
        context.table_span_fidelity_state["timed_out"] = True
    span_fidelity_enabled = (
        context.settings.table_span_fidelity_enabled
        and context.table_span_fidelity_state.get("timed_out") is not True
        and context.table_span_fidelity_state.get(
            "span_fidelity_disabled"
        )
        is not True
    )
    page_heights = {
        int(page["page_index"]): float(page["page_height"]) for page in context.pages
    }
    docling_table_decision_views: dict[
        int, list[dict[str, Any]]
    ] = {}
    body_items, docling_tables = _normalize_docling_body(
        context.raw_docling,
        page_heights,
        context.native_texts,
        context.image_regions,
        context.table_repair_words,
        preserve_visual_items=True,
        preserve_graph_items=True,
        quality_settings=context.settings,
        source_document_identity=context.source_document_identity,
        coordinate_unit=context.coordinate_unit,
        source_text_evidence=context.source_text_evidence,
        table_span_fidelity_enabled=span_fidelity_enabled,
        table_span_fidelity_document_deadline=(
            context.table_span_fidelity_document_deadline
        ),
        table_span_fidelity_page_deadlines=(
            context.table_span_fidelity_page_deadlines
        ),
        table_span_fidelity_state=context.table_span_fidelity_state,
        table_decision_views_sink=docling_table_decision_views,
    )
    table_decision_views: dict[
        int, list[dict[str, Any]]
    ] = {}
    if context.selected_vector_representations is None:
        context.selected_vector_representations = {}
    else:
        context.selected_vector_representations.clear()
    preliminary_selected_vector_representations: dict[
        int, list[dict[str, Any]]
    ] = {}
    tables = _merge_tables(
        docling_tables,
        context.vector_tables,
        table_span_fidelity_enabled=span_fidelity_enabled,
        table_evidence_reconciliation_enabled=context.settings.table_evidence_reconciliation_enabled,
        table_decision_views=docling_table_decision_views,
        table_decision_views_sink=table_decision_views,
        table_span_fidelity_state=context.table_span_fidelity_state,
        selected_vector_sink=preliminary_selected_vector_representations,
        selected_vector_source_sha256=context.source_document_identity,
    )
    tables = table_semantics.gate_table_candidates(
        tables,
        body_items,
        context.image_regions,
        context.raw_docling,
        context.source_document_identity,
        table_span_fidelity_enabled=span_fidelity_enabled,
        table_evidence_reconciliation_enabled=(
            context.settings.table_evidence_reconciliation_enabled
        ),
        table_candidate_gate_enabled=context.settings.table_candidate_gate_enabled,
    )
    table_semantics.finalize_selected_vector_representations(
        tables,
        preliminary_selected_vector_representations,
        context.source_document_identity,
        context.selected_vector_representations,
        table_span_fidelity_enabled=span_fidelity_enabled,
        table_evidence_reconciliation_enabled=(
            context.settings.table_evidence_reconciliation_enabled
        ),
        table_candidate_gate_enabled=(
            context.settings.table_candidate_gate_enabled
        ),
    )
    if context.settings.table_candidate_gate_enabled:
        gated_decision_views: dict[int, list[dict[str, Any]]] = {}
        for page_index, page_tables in tables.items():
            gated_decision_views[page_index] = [
                (
                    table["_p04_predecessor_snapshot"]
                    if type(table.get("table_evidence")) is dict
                    and type(table.get("_p04_predecessor_snapshot")) is dict
                    else table
                )
                for table in page_tables
            ]
        table_decision_views.clear()
        table_decision_views.update(gated_decision_views)
    headers, footers = _header_footer_items(
        context.raw_docling,
        page_heights,
        context.native_texts,
    )

    _reconcile_page_decorations(
        headers,
        footers,
        context.image_regions,
    )
    decorations: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for page_index, item in headers.items():
        decorations[page_index].append(item)
    for page_index, item in footers.items():
        decorations[page_index].append(item)

    _reconcile_fragmented_layout_with_page_ocr(
        body_items,
        context.image_regions,
        context.settings,
    )
    _supplement_unrepresented_page_ocr(
        body_items,
        tables,
        context.image_regions,
        decorations,
        context.settings,
        source_document_identity=context.source_document_identity,
        table_decision_views=table_decision_views,
        table_span_fidelity_state=context.table_span_fidelity_state,
    )
    _infer_recovered_headings(body_items, page_heights, context.settings)
    _merge_body_items(
        context.pages,
        body_items,
        tables,
        context.image_regions,
        headers,
        footers,
        context.settings,
        context.source_document_identity,
        table_decision_views=table_decision_views,
        table_span_fidelity_state=context.table_span_fidelity_state,
    )
    for page, native_text in zip(
        context.pages,
        context.native_texts,
        strict=True,
    ):
        _normalize_table_of_contents(page, native_text)
    _clean_checkbox_markers(context.pages)
    _enrich_ocr_confidence(context.pages, context.image_regions)
    seal_enabled = (
        span_fidelity_enabled
        and context.table_span_fidelity_state.get("timed_out") is not True
        and context.table_span_fidelity_state.get(
            "span_fidelity_disabled"
        )
        is not True
    )
    if seal_enabled:
        context.table_span_fidelity_document_deadline = (
            _resume_table_span_fidelity_budget(
                context.table_span_fidelity_document_deadline,
                context.table_span_fidelity_page_deadlines,
                context.table_span_fidelity_state,
            )
        )
    try:
        seal_table_pages(
            context.pages,
            context.source_document_identity,
            context.native_texts,
            table_span_fidelity_enabled=seal_enabled,
            table_evidence_reconciliation_enabled=context.settings.table_evidence_reconciliation_enabled,
            table_candidate_gate_enabled=context.settings.table_candidate_gate_enabled,
            table_multi_page_merge_enabled=context.settings.table_multi_page_merge_enabled,
            table_span_fidelity_document_deadline=(
                context.table_span_fidelity_document_deadline
            ),
            table_span_fidelity_page_deadlines=(
                context.table_span_fidelity_page_deadlines
            ),
            table_span_fidelity_state=context.table_span_fidelity_state,
        )
    finally:
        if seal_enabled:
            _suspend_table_span_fidelity_budget(
                context.table_span_fidelity_state
            )
    table_semantics.merge_continued_tables(
        context.pages,
        context.source_document_identity,
        table_span_fidelity_enabled=seal_enabled,
        table_evidence_reconciliation_enabled=context.settings.table_evidence_reconciliation_enabled,
        table_candidate_gate_enabled=context.settings.table_candidate_gate_enabled,
        table_multi_page_merge_enabled=context.settings.table_multi_page_merge_enabled,
    )


def _raw_layout_text_by_page(
    raw_docling: Mapping[str, Any],
) -> dict[int, str]:
    values: dict[int, list[str]] = defaultdict(list)
    for raw_item in raw_docling.get("texts") or []:
        if not isinstance(raw_item, Mapping):
            continue
        text = str(raw_item.get("text") or "").strip()
        if not text:
            continue
        provenance = raw_item.get("prov") or []
        try:
            page_index = int(provenance[0].get("page_no") or 1)
        except (AttributeError, IndexError, TypeError, ValueError):
            page_index = 1
        values[page_index].append(text)

    return {
        page_index: "\n".join(page_values)
        for page_index, page_values in values.items()
    }


def _normalized_token_coverage(reference: str, candidate: str) -> float:
    reference_tokens = _normalized_search_text(reference).split()
    if not reference_tokens:
        return 1.0
    candidate_tokens = set(_normalized_search_text(candidate).split())
    return sum(token in candidate_tokens for token in reference_tokens) / len(
        reference_tokens
    )


def _select_pdf_render_requests(
    pages: Sequence[Mapping[str, Any]],
    native_texts: Sequence[str],
    raw_docling: Mapping[str, Any],
    image_regions: Mapping[int, Sequence[ImageRegion]],
    settings: Settings,
) -> list[PdfRegionRequest]:
    """Choose only PDF pages/regions needing additional visual evidence."""

    if not settings.pdf_visual_analysis_enabled:
        return []

    page_heights = {
        int(page["page_index"]): float(page["page_height"])
        for page in pages
    }
    raw_text_by_page = _raw_layout_text_by_page(raw_docling)
    requests: list[PdfRegionRequest] = []
    full_render_pages: set[int] = set()

    for page, native_text in zip(pages, native_texts, strict=True):
        page_index = int(page["page_index"])
        page_regions = image_regions.get(page_index, [])
        if any(_region_role(region) == "page_source" for region in page_regions):
            continue
        native_alnum = sum(character.isalnum() for character in native_text)
        text_layout_coverage = _normalized_token_coverage(
            native_text,
            raw_text_by_page.get(page_index, ""),
        )
        sparse_native_text = (
            native_alnum < settings.pdf_render_ocr_min_native_alnum_chars
        )
        needs_page_render = (
            native_alnum == 0
            or sparse_native_text
            and text_layout_coverage < 0.95
            or text_layout_coverage
            < settings.pdf_render_ocr_min_layout_coverage
        )
        if not needs_page_render:
            continue
        requests.append(
            PdfRegionRequest(
                page_index=page_index,
                bbox={
                    "x": 0.0,
                    "y": 0.0,
                    "width": float(page["page_width"]),
                    "height": float(page["page_height"]),
                },
                content_type="page_render",
                region_role="page_source",
                metadata={
                    "render_reason": (
                        "little_or_no_native_text"
                        if sparse_native_text
                        else "layout_text_coverage_below_threshold"
                    )
                },
            )
        )
        full_render_pages.add(page_index)

    def already_covered(
        page_index: int,
        box: Mapping[str, Any] | None,
    ) -> bool:
        return any(
            _overlap_of_smaller(
                box,
                _coerce_bbox(region.bbox),
            )
            >= 0.55
            for region in image_regions.get(page_index, [])
        )

    candidates: list[tuple[Mapping[str, Any], str]] = []
    candidates.extend(
        (raw_item, str(raw_item.get("label") or "picture"))
        for raw_item in (raw_docling.get("pictures") or [])
        if isinstance(raw_item, Mapping)
    )
    # Empty/structurally unusable table detections get a rendered OCR fallback;
    # reliable native/Docling tables continue through the normal table path.
    for raw_table in raw_docling.get("tables") or []:
        if not isinstance(raw_table, Mapping):
            continue
        data = raw_table.get("data") or {}
        cells = data.get("table_cells") or []
        has_useful_cells = any(
            isinstance(cell, Mapping)
            and str(cell.get("text") or "").strip()
            for cell in cells
        )
        if has_useful_cells:
            continue
        candidates.append((raw_table, "table"))

    for raw_item, label in candidates:
        try:
            page_index, box = _bbox_from_prov(raw_item, page_heights)
        except Exception:
            continue
        if (
            page_index in full_render_pages
            or not box
            or already_covered(page_index, box)
        ):
            continue
        content_type = label if label in {"chart", "diagram", "table"} else "image"
        requests.append(
            PdfRegionRequest(
                page_index=page_index,
                bbox=box,
                content_type=content_type,
                region_role="content_region",
                metadata={"render_reason": "layout_visual_without_embedded_raster"},
            )
        )
    if settings.layout_source_notes_enabled:
        from app.services.layout_source_notes import (
            plan_source_note_zone_requests,
            record_source_note_evidence_concerns,
        )

        source_note_plan = plan_source_note_zone_requests(
            pages,
            raw_docling,
        )
        requests.extend(source_note_plan.requests)
        if source_note_plan.concerns and isinstance(raw_docling, dict):
            record_source_note_evidence_concerns(
                raw_docling,
                source_note_plan.concerns,
            )
    return requests


def _parse_loaded_document(
    loaded: LoadedDocument,
    settings: Settings,
    *,
    parser_worker: Any | None = None,
) -> ParseResult:
    started = time.perf_counter()
    if (
        not settings.tesseract_cmd.strip()
        or shutil.which(settings.tesseract_cmd) is None
    ):
        raise ExtractionEngineUnavailableError(
            details={
                "component": "tesseract",
                "reason": "executable_not_found",
            }
        )

    font_audit: Mapping[str, Any] | None = None
    font_recovery: Mapping[str, Any] | None = None
    selective_span_ocr: Mapping[str, Any] | None = None
    if loaded.kind is InputKind.PDF and settings.text_integrity_font_audit_enabled:
        from app.services.font_audit import audit_pdf_fonts

        font_audit = audit_pdf_fonts(loaded.processing_bytes).model_dump(
            mode="json", exclude_none=True
        )
        if settings.text_integrity_font_recovery_enabled and font_audit.get("findings"):
            from app.services.font_recovery import recover_pdf_font_text

            font_recovery = recover_pdf_font_text(
                loaded.processing_bytes,
                font_audit,
            ).model_dump(mode="json", exclude_none=True)

    if loaded.kind is InputKind.PDF:
        pages, native_texts = _native_pdf_pages(
            loaded.processing_bytes,
            max_pages=settings.max_pages,
        )
    else:
        pages = [page.page_model(loaded.source_format) for page in loaded.pages]
        native_texts = ["" for _ in pages]

    if (
        loaded.kind is InputKind.PDF
        and settings.text_integrity_selective_span_ocr_enabled
        and font_audit is not None
        and font_recovery is not None
    ):
        from app.services.selective_span_ocr import run_selective_span_ocr

        page_sizes = {
            int(page.get("page_index") or index): (
                float(page.get("page_width") or 0),
                float(page.get("page_height") or 0),
            )
            for index, page in enumerate(pages, 1)
        }
        selective_span_ocr = run_selective_span_ocr(
            loaded.processing_bytes,
            font_audit,
            font_recovery,
            page_sizes,
            tesseract_cmd=settings.tesseract_cmd,
            languages=settings.ocr_languages,
            tessdata_path=settings.tesseract_data_path,
            **(
                {"numeric_cleanup_v2_enabled": True}
                if settings.ocr_numeric_cleanup_v2_enabled
                else {}
            ),
            **(
                {"spatial_token_preservation_enabled": True}
                if settings.ocr_spatial_token_preservation_enabled
                else {}
            ),
        ).model_dump(mode="json", exclude_none=True)

    if settings.parser_latency_prewarm_enabled:
        raw_docling, processing_warnings = _convert_with_docling(
            loaded.processing_bytes,
            loaded.processing_filename,
            settings,
            input_kind=loaded.kind,
            parser_worker=parser_worker,
        )
    else:
        raw_docling, processing_warnings = _convert_with_docling(
            loaded.processing_bytes,
            loaded.processing_filename,
            settings,
            input_kind=loaded.kind,
            parser_worker=parser_worker,
        )
    text_run_evidence: Any | None = None
    if loaded.kind is InputKind.PDF and settings.layout_text_run_semantics_enabled:
        try:
            from app.services.text_run_semantics import (
                extract_text_run_evidence,
            )

            text_run_evidence = extract_text_run_evidence(
                loaded.original_bytes,
                max_pages=settings.max_pages,
            )
        except Exception:
            # The enabled semantic overlay owns its bounded, content-free
            # fail-closed concern. It must not turn an otherwise valid parse
            # into an API failure or disclose source content in a warning.
            text_run_evidence = None
    form_evidence: Any | None = None
    form_extraction_ms = 0.0
    if loaded.kind is InputKind.PDF and settings.layout_forms_enabled:
        form_extraction_started = time.perf_counter()
        try:
            from app.services.form_semantics import extract_form_evidence

            form_evidence = extract_form_evidence(
                loaded.original_bytes,
                max_pages=settings.max_pages,
            )
        except Exception:
            # Form semantics is a bounded, default-off semantic overlay.
            # Source-report refusal fails the overlay closed without exposing
            # source text, paths, URLs, or raw PDF metadata.
            form_evidence = None
        finally:
            form_extraction_ms = round(
                (time.perf_counter() - form_extraction_started) * 1000.0,
                3,
            )
    outline_evidence: Any | None = None
    outline_extraction_ms = 0.0
    if loaded.kind is InputKind.PDF and settings.layout_outline_structure_enabled:
        outline_extraction_started = time.perf_counter()
        try:
            from app.services.outline_structure import (
                extract_outline_evidence,
            )

            outline_evidence = extract_outline_evidence(
                loaded.original_bytes,
                max_pages=settings.max_pages,
            )
        except Exception:
            # Outline structure is a bounded, default-off semantic overlay.
            # Evidence unavailability is represented by its closed summary
            # and concern without exposing source text or parser internals.
            outline_evidence = None
        finally:
            outline_extraction_ms = round(
                (time.perf_counter() - outline_extraction_started) * 1000.0,
                3,
            )
    source_text_evidence: Any | None = None
    if (
        loaded.kind is InputKind.PDF
        and settings.text_integrity_source_alignment_enabled
    ):
        try:
            from app.services.source_text_alignment import (
                extract_source_text_evidence,
            )

            source_text_evidence = extract_source_text_evidence(
                loaded.processing_bytes,
                max_pages=settings.max_pages,
            )
        except Exception as exc:
            # Source alignment is an additive, fail-closed evidence layer.
            # A bounded extraction refusal must not make an otherwise valid
            # document unavailable or expose source content in diagnostics.
            processing_warnings.append(
                f"Source text alignment was unavailable: {type(exc).__name__}."
            )

    try:
        if loaded.kind is InputKind.PDF:
            image_regions = extract_image_ocr(
                loaded.processing_bytes,
                tesseract_cmd=settings.tesseract_cmd,
                languages=settings.ocr_languages,
                timeout_seconds=settings.targeted_ocr_timeout_seconds,
                render_scale=settings.targeted_ocr_scale,
                max_render_pixels=settings.targeted_ocr_max_pixels,
                tessdata_path=settings.tesseract_data_path,
                **(
                    {"numeric_cleanup_v2_enabled": True}
                    if settings.ocr_numeric_cleanup_v2_enabled
                    else {}
                ),
                **(
                    {"spatial_token_preservation_enabled": True}
                    if settings.ocr_spatial_token_preservation_enabled
                    else {}
                ),
                **(
                    {"shared_visual_service_enabled": True}
                    if settings.adapters_image_parity_enabled
                    else {}
                ),
            )
            render_requests = _select_pdf_render_requests(
                pages,
                native_texts,
                raw_docling,
                image_regions,
                settings,
            )
            rendered_regions = extract_rendered_pdf_ocr(
                loaded.processing_bytes,
                render_requests,
                tesseract_cmd=settings.tesseract_cmd,
                languages=settings.ocr_languages,
                timeout_seconds=settings.targeted_ocr_timeout_seconds,
                render_scale=settings.targeted_ocr_scale,
                max_render_pixels=settings.targeted_ocr_max_pixels,
                tessdata_path=settings.tesseract_data_path,
                **(
                    {"numeric_cleanup_v2_enabled": True}
                    if settings.ocr_numeric_cleanup_v2_enabled
                    else {}
                ),
                **(
                    {"spatial_token_preservation_enabled": True}
                    if settings.ocr_spatial_token_preservation_enabled
                    else {}
                ),
                **(
                    {"shared_visual_service_enabled": True}
                    if settings.adapters_image_parity_enabled
                    else {}
                ),
            )
            for page_index, regions in rendered_regions.items():
                image_regions.setdefault(page_index, []).extend(regions)
            if settings.layout_source_notes_enabled:
                from app.services.layout_source_notes import (
                    augment_source_note_evidence,
                    discard_source_note_zone_regions,
                    record_source_note_evidence_concerns,
                )

                try:
                    augment_source_note_evidence(
                        raw_docling,
                        image_regions,
                        pdf_bytes=loaded.processing_bytes,
                        accept_ocr_line=lambda line: _ocr_line_primary_decision(
                            line, settings
                        )[0],
                    )
                except Exception as exc:
                    # Source-note evidence is additive.  Its private rendered
                    # strips must never enter public image/prose analysis even
                    # when augmentation refuses an unexpected adapter value.
                    discard_source_note_zone_regions(image_regions)
                    record_source_note_evidence_concerns(
                        raw_docling,
                        (
                            {
                                "code": ("layout_source_note_evidence_unavailable"),
                                "error_type": type(exc).__name__,
                            },
                        ),
                    )
        else:
            image_regions = extract_raster_ocr(
                loaded.pages,
                tesseract_cmd=settings.tesseract_cmd,
                languages=settings.ocr_languages,
                timeout_seconds=settings.targeted_ocr_timeout_seconds,
                max_render_pixels=settings.targeted_ocr_max_pixels,
                tessdata_path=settings.tesseract_data_path,
                **(
                    {"numeric_cleanup_v2_enabled": True}
                    if settings.ocr_numeric_cleanup_v2_enabled
                    else {}
                ),
                **(
                    {"spatial_token_preservation_enabled": True}
                    if settings.ocr_spatial_token_preservation_enabled
                    else {}
                ),
                **(
                    {"shared_visual_service_enabled": True}
                    if settings.adapters_image_parity_enabled
                    else {}
                ),
            )
    except OCRUnavailableError as exc:
        raise ExtractionEngineUnavailableError(
            details={
                "component": "tesseract",
                "reason": "executable_not_found",
            }
        ) from exc
    except Exception as exc:
        raise DocumentProcessingError(
            details={
                "component": "targeted_image_ocr",
                "reason": type(exc).__name__,
            }
        ) from exc

    try:
        vector_tables = (
            extract_vector_tables(
                loaded.processing_bytes,
                preserve_cell_geometry=settings.table_span_fidelity_enabled,
            )
            if loaded.kind is InputKind.PDF
            else {}
        )
    except Exception as exc:
        vector_tables = {}
        processing_warnings.append(
            f"Supplemental vector table extraction failed: {type(exc).__name__}."
        )

    table_span_fidelity_document_deadline_value: float | None = None
    table_span_fidelity_page_deadlines: dict[int, float] = {}
    table_span_fidelity_state: dict[str, Any] = {}
    if settings.table_span_fidelity_enabled:
        from app.services.table_semantics import (
            table_span_fidelity_document_deadline,
        )

        table_span_fidelity_document_deadline_value = (
            table_span_fidelity_document_deadline()
        )
    table_repair_words: dict[int, list[dict[str, Any]]] = {}
    table_repair_warning_type: str | None = None
    if settings.table_span_fidelity_enabled:
        if loaded.kind is InputKind.PDF:
            (
                table_repair_words,
                table_span_fidelity_document_deadline_value,
                table_repair_warning_type,
            ) = _extract_partitioned_table_repair_words(
                loaded.processing_bytes,
                raw_docling,
                table_span_fidelity_document_deadline_value,
                table_span_fidelity_page_deadlines,
                table_span_fidelity_state,
            )
        else:
            # No PDF word path applies, so the P04 clock remains suspended
            # until the first table-owned analysis segment.
            _suspend_table_span_fidelity_budget(table_span_fidelity_state)
    elif loaded.kind is InputKind.PDF:
        try:
            table_repair_words = _extract_table_repair_words(
                loaded.processing_bytes,
                raw_docling,
                table_span_fidelity_enabled=False,
            )
        except Exception as exc:
            table_repair_warning_type = type(exc).__name__
    if table_repair_warning_type is not None:
        processing_warnings.append(
            "Table word-geometry repair was unavailable: "
            f"{table_repair_warning_type}."
        )

    context = SharedAnalysisContext(
        pages,
        native_texts,
        raw_docling,
        image_regions,
        vector_tables,
        table_repair_words,
        settings,
        "px" if loaded.kind is InputKind.IMAGE else "pt",
        hashlib.sha256(loaded.original_bytes).hexdigest(),
        source_text_evidence,
        table_span_fidelity_document_deadline_value,
        table_span_fidelity_page_deadlines,
        table_span_fidelity_state,
    )
    _analyze_shared_pages(context)
    if loaded.kind is InputKind.IMAGE:
        _apply_image_provenance_and_units(pages, image_regions)

    duration_ms = max(round((time.perf_counter() - started) * 1000), 0)
    document_metadata: dict[str, Any] = {
        "filename": loaded.original_filename or "document.pdf",
        "mime_type": loaded.mime_type,
        "sha256": hashlib.sha256(loaded.original_bytes).hexdigest(),
        "page_count": len(pages),
        "image_count": sum(
            1
            for regions in image_regions.values()
            for region in regions
            if region.region_origin != "pdf_page_render"
        ),
    }
    processing_metadata: dict[str, Any] = {
        "engine": "docling",
        "ocr_engine": "tesseract",
        "ocr_languages": list(settings.ocr_languages),
        "duration_ms": duration_ms,
        "native_text_engine": "pypdfium2",
        "table_engines": ["docling", "pdfplumber"],
        "local_processing": True,
        "input_format": loaded.kind.value,
        "visual_analysis": {
            "shared_pipeline": True,
            "primary_ocr_min_confidence": (settings.image_primary_ocr_min_confidence),
            "low_confidence_min_alnum_chars": (
                settings.image_low_confidence_min_alnum_chars
            ),
            "heading_min_confidence": (settings.image_heading_min_confidence),
            "heading_height_ratio": settings.image_heading_height_ratio,
            "picture_classification_threshold": (
                settings.image_picture_classification_threshold
            ),
            "pdf_selective_rendering_enabled": (settings.pdf_visual_analysis_enabled),
        },
        "picture_captioning": {
            "requested": settings.image_captioning_enabled,
            "local_model_available": (
                _picture_description_model_available(settings.docling_artifacts_path)
                if settings.image_captioning_enabled
                else False
            ),
        },
    }
    content_regions = [
        item
        for page in pages
        for item in page.get("items") or []
        if item.get("region_role") == "content_region"
    ]
    document_metadata.update(
        {
            "source_format": loaded.source_format,
            "page_source_region_count": sum(
                1
                for regions in image_regions.values()
                for region in regions
                if _region_role(region) == "page_source"
            ),
            "rendered_visual_region_count": sum(
                1
                for regions in image_regions.values()
                for region in regions
                if region.region_origin == "pdf_page_render"
            ),
            "content_region_count": len(content_regions),
            "content_region_types": dict(
                sorted(
                    {
                        content_type: sum(
                            1
                            for item in content_regions
                            if item.get("content_type") == content_type
                        )
                        for content_type in {
                            str(item.get("content_type") or "image")
                            for item in content_regions
                        }
                    }.items()
                )
            ),
        }
    )
    if loaded.kind is InputKind.IMAGE:
        document_metadata.update(
            {
                "orientation_corrected_pages": [
                    page.page_index for page in loaded.pages if page.orientation_applied
                ],
                "page_source_image_count": sum(
                    len(page.get("detected_images") or []) for page in pages
                ),
            }
        )
        processing_metadata.update(
            {
                "input_format": "image",
                "page_loader": "pillow",
                "native_text_engine": None,
                "table_engines": ["docling"],
                "image_quality": {
                    "primary_ocr_min_confidence": (
                        settings.image_primary_ocr_min_confidence
                    ),
                    "low_confidence_min_alnum_chars": (
                        settings.image_low_confidence_min_alnum_chars
                    ),
                    "heading_min_confidence": (settings.image_heading_min_confidence),
                    "heading_height_ratio": (settings.image_heading_height_ratio),
                    "picture_classification_threshold": (
                        settings.image_picture_classification_threshold
                    ),
                },
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "document": document_metadata,
        "pages": pages,
        "processing": processing_metadata,
        "warnings": processing_warnings,
    }
    if settings.visual_structure_schema_enabled:
        from app.services.visual_semantics import apply_visual_semantics

        payload = dict(
            apply_visual_semantics(
                payload,
                settings,
                source_document_bytes=loaded.processing_bytes,
                input_kind=loaded.kind,
                raw_graph=raw_docling,
            )
        )
    if settings.visual_models_contract_enabled:
        # Phase 06 is an optional transaction over the complete Phase 05
        # visual result.  Its orchestrator owns every skip/failure rollback;
        # the shared-IR and canonical paths below therefore receive either a
        # fully validated additive candidate or the exact Phase 05 payload.
        from app.services.visual_models import apply_optional_visual_models

        payload = apply_optional_visual_models(
            payload,
            settings,
            source_document_bytes=loaded.processing_bytes,
            input_kind=loaded.kind,
        )
    p04_internal_ir_sink: dict[str, Any] = {}
    p04_table_transaction: tuple[Any, ...] = ()
    if settings.table_span_fidelity_enabled:
        from app.services.opaque_group_custody import (
            OpaqueGroupCustodyIntegrityError,
            OpaqueGroupCustodyResourceError,
            OpaqueGroupCustodyTimeoutError,
            has_literal_table_marker,
        )
        from app.services.table_semantics import (
            _restore_all_table_predecessors,
            detach_table_overlays_for_phase03,
        )

        state = context.table_span_fidelity_state
        if has_literal_table_marker(payload) and state is not None:
            try:
                def detach_public_tables(active_deadline: float) -> tuple[Any, ...]:
                    try:
                        return detach_table_overlays_for_phase03(
                            payload.get("pages"),
                            deadline=active_deadline,
                        )
                    except TimeoutError as exc:
                        raise OpaqueGroupCustodyTimeoutError(
                            "table overlay detachment exceeded its deadline"
                        ) from exc
                    except (MemoryError, RecursionError) as exc:
                        raise OpaqueGroupCustodyResourceError(
                            "table overlay detachment exhausted resources"
                        ) from exc
                    except (TypeError, ValueError) as exc:
                        error_type = (
                            OpaqueGroupCustodyResourceError
                            if "limit" in str(exc).casefold()
                            or "resource" in str(exc).casefold()
                            else OpaqueGroupCustodyIntegrityError
                        )
                        raise error_type(
                            "table overlay detachment failed closed"
                        ) from exc

                p04_table_transaction = _run_table_custody_document_segment(
                    context.table_span_fidelity_document_deadline,
                    context.table_span_fidelity_page_deadlines,
                    state,
                    detach_public_tables,
                )
            except OpaqueGroupCustodyTimeoutError:
                state["timed_out"] = True
            except (
                OpaqueGroupCustodyIntegrityError,
                OpaqueGroupCustodyResourceError,
            ):
                state["custody_rejected"] = True

            if not p04_table_transaction:
                # The detacher is atomic, so every marker still has its sealed
                # predecessor. Restore it without manufacturing a timeout for
                # an integrity/resource refusal before P03 sees the payload.
                _restore_all_table_predecessors(
                    payload.get("pages"),
                    time.perf_counter() + 0.500,
                )
        if has_literal_table_marker(payload):
            raise ValueError("literal P04 marker reached the Phase 03 boundary")

    compatibility_options: dict[str, Any] = {
        "raw_graph": raw_docling,
        "native_texts": native_texts,
        "font_audit": font_audit,
        "font_recovery": font_recovery,
        "selective_span_ocr": selective_span_ocr,
        "text_run_evidence": text_run_evidence,
        "form_evidence": form_evidence,
        "form_extraction_ms": form_extraction_ms,
        "outline_evidence": outline_evidence,
        "outline_extraction_ms": outline_extraction_ms,
    }
    if settings.table_span_fidelity_enabled:
        compatibility_options["internal_ir_sink"] = p04_internal_ir_sink
    if settings.layout_running_regions_enabled:
        compatibility_options.update(
            {
                "source_pdf_bytes": loaded.original_bytes,
                "input_kind": loaded.kind,
            }
        )
    payload = _apply_shared_ir_compatibility_projection(
        payload,
        settings,
        **compatibility_options,
    )
    terminal_options: dict[str, Any] = {
        "source_text_evidence": source_text_evidence,
        "source_sha256": hashlib.sha256(loaded.original_bytes).hexdigest(),
        "input_kind": loaded.kind,
        "raw_graph": raw_docling,
        "native_texts": native_texts,
        "text_run_evidence": text_run_evidence,
        "form_evidence": form_evidence,
        "outline_evidence": outline_evidence,
    }
    if settings.table_span_fidelity_enabled:
        terminal_options["internal_ir_sink"] = p04_internal_ir_sink
        if p04_table_transaction:
            terminal_options["authoritative_table_views"] = (
                _table_authority_views_from_transaction(
                    p04_table_transaction
                )
            )
        elif context.selected_vector_representations:
            terminal_options["selected_vector_representations"] = (
                context.selected_vector_representations
            )
    if (
        settings.layout_running_regions_enabled
        or terminal_options.get("selected_vector_representations")
    ):
        terminal_options["source_pdf_bytes"] = loaded.original_bytes
    table_source_alignment_predecessor = (
        payload if p04_table_transaction else None
    )
    payload = _apply_terminal_source_text_alignment(
        payload,
        settings,
        **terminal_options,
    )
    if settings.table_span_fidelity_enabled and p04_table_transaction:
        baseline_ir = p04_internal_ir_sink.get("ir")
        if baseline_ir is None:
            raise ValueError("table terminal predecessor IR is unavailable")
        payload = _apply_terminal_table_authority(
            payload,
            baseline_ir,
            p04_table_transaction,
            settings,
            raw_graph=raw_docling,
            native_texts=native_texts,
            text_run_evidence=text_run_evidence,
            form_evidence=form_evidence,
            outline_evidence=outline_evidence,
            source_pdf_bytes=loaded.original_bytes,
            input_kind=loaded.kind,
            document_deadline=context.table_span_fidelity_document_deadline,
            page_deadlines=context.table_span_fidelity_page_deadlines,
            state=context.table_span_fidelity_state,
            table_dependency_predecessor=(
                table_source_alignment_predecessor
                if table_source_alignment_predecessor is not None
                and _has_table_owned_source_suppression(payload)
                else None
            ),
        )
    validated_result = (
        context.table_span_fidelity_state.pop(
            "_p04_validated_parse_result",
            None,
        )
        if context.table_span_fidelity_state is not None
        else None
    )
    if context.table_span_fidelity_state is not None:
        _finish_table_span_fidelity_budget(context.table_span_fidelity_state)
    if isinstance(validated_result, ParseResult):
        return validated_result
    return ParseResult.model_validate(payload)


def _apply_shared_ir_compatibility_projection(
    payload: dict[str, Any],
    settings: Settings,
    *,
    source_pdf_bytes: bytes | None = None,
    input_kind: InputKind | None = None,
    raw_graph: Mapping[str, Any] | None = None,
    native_texts: Sequence[str] = (),
    font_audit: Mapping[str, Any] | None = None,
    font_recovery: Mapping[str, Any] | None = None,
    selective_span_ocr: Mapping[str, Any] | None = None,
    text_run_evidence: Any | None = None,
    form_evidence: Any | None = None,
    form_extraction_ms: float = 0.0,
    outline_evidence: Any | None = None,
    outline_extraction_ms: float = 0.0,
    table_span_fidelity_document_deadline: float | None = None,
    table_span_fidelity_page_deadlines: dict[int, float] | None = None,
    table_span_fidelity_state: dict[str, Any] | None = None,
    internal_ir_sink: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Exercise the internal IR only when its default-off flag is enabled."""

    if not settings.shared_ir_enabled:
        return payload

    # P01-US01 keeps the IR internal and immediately exercises the lossless v1
    # compatibility projection. Public fields remain unchanged.
    from app.services.ir import round_trip_document

    reconciliation_options = (
        {"text_reconciliation_enabled": True}
        if settings.text_reconciliation_enabled
        else {}
    )
    custody_runner: Any | None = None
    if settings.table_span_fidelity_enabled:
        from app.services.opaque_group_custody import has_literal_table_marker

        if has_literal_table_marker(payload):
            if (
                table_span_fidelity_document_deadline is None
                or table_span_fidelity_page_deadlines is None
                or table_span_fidelity_state is None
            ):
                raise ValueError("table custody budget state is unavailable")

            def custody_runner(operation: Any) -> Any:
                return _run_table_custody_document_segment(
                    table_span_fidelity_document_deadline,
                    table_span_fidelity_page_deadlines,
                    table_span_fidelity_state,
                    operation,
                )
    form_metrics: dict[str, float] | None = (
        {"extraction_ms": form_extraction_ms} if settings.layout_forms_enabled else None
    )
    outline_metrics: dict[str, Any] | None = (
        {"extraction_ms": outline_extraction_ms}
        if settings.layout_outline_structure_enabled
        else None
    )
    layout_enabled = (
        settings.layout_table_captions_enabled
        or settings.layout_visual_relationships_enabled
        or settings.layout_source_notes_enabled
        or settings.layout_relationship_order_enabled
        or settings.layout_text_run_semantics_enabled
        or settings.layout_forms_enabled
        or settings.layout_outline_structure_enabled
    )
    if layout_enabled:
        reconciliation_options["layout_settings"] = settings
    if settings.layout_text_run_semantics_enabled:
        reconciliation_options["text_run_evidence"] = text_run_evidence
    if settings.layout_forms_enabled:
        reconciliation_options["form_evidence"] = form_evidence
        reconciliation_options["form_metrics"] = form_metrics
    if settings.layout_outline_structure_enabled:
        reconciliation_options["outline_evidence"] = outline_evidence
        reconciliation_options["outline_metrics"] = outline_metrics
    if settings.shared_ir_normalization_enabled:
        if settings.table_span_fidelity_enabled:
            reconciliation_options["table_span_fidelity_enabled"] = True
            if custody_runner is not None:
                reconciliation_options["table_custody_runner"] = custody_runner
        if font_audit is None:
            projected, internal_ir = round_trip_document(
                payload,
                raw_graph=raw_graph,
                native_texts=native_texts,
                **reconciliation_options,
            )
        else:
            if font_recovery is None:
                projected, internal_ir = round_trip_document(
                    payload,
                    raw_graph=raw_graph,
                    native_texts=native_texts,
                    font_audit=font_audit,
                    **reconciliation_options,
                )
            elif selective_span_ocr is None:
                projected, internal_ir = round_trip_document(
                    payload,
                    raw_graph=raw_graph,
                    native_texts=native_texts,
                    font_audit=font_audit,
                    font_recovery=font_recovery,
                    **reconciliation_options,
                )
            else:
                projected, internal_ir = round_trip_document(
                    payload,
                    raw_graph=raw_graph,
                    native_texts=native_texts,
                    font_audit=font_audit,
                    font_recovery=font_recovery,
                    selective_span_ocr=selective_span_ocr,
                    **reconciliation_options,
                )
    else:
        # Retain the original US01 call shape on the compatibility-only path.
        # Besides keeping the default path minimal, this preserves observers
        # and adapters that wrap the one-argument round trip.
        projected, internal_ir = round_trip_document(
            payload,
            **reconciliation_options,
        )
    if settings.canonical_serialization_enabled:
        from app.services.presentation import build_canonical_presentation

        projected["canonical_presentation"] = build_canonical_presentation(
            internal_ir
        ).model_dump(
            mode="json",
            exclude_none=True,
        )
    if settings.layout_forms_enabled:
        from app.services.form_semantics import form_processing_summary

        projected.setdefault("processing", {})["form_semantics"] = (
            form_processing_summary(form_metrics)
        )
    if settings.layout_outline_structure_enabled:
        from app.services.outline_structure import (
            outline_processing_summary,
        )

        projected.setdefault("processing", {})["outline_structure"] = (
            outline_processing_summary(outline_metrics)
        )
    if settings.layout_running_regions_enabled:
        import json

        from app.services.running_regions import (
            POLICY_ID as RUNNING_REGION_POLICY_ID,
            RunningRegionSourceOutcomeError,
            prepare_source_projection_authority,
            project_running_regions,
        )

        def nonprojecting_running_regions(
            predecessor: Mapping[str, Any],
            *,
            status: str,
            reason: str,
        ) -> dict[str, Any]:
            result = deepcopy(dict(predecessor))
            result.setdefault("processing", {})["running_regions"] = {
                "policy_id": RUNNING_REGION_POLICY_ID,
                "status": status,
                "reason": reason,
                "source_page_count": 0,
                "identity_count": 0,
                "detected_label_count": 0,
                "embedded_label_count": 0,
                "legacy_fallback_count": 0,
                "candidate_count": 0,
                "comparison_count": 0,
                "running_region_count": 0,
                "header_count": 0,
                "footer_count": 0,
                "top_navigation_count": 0,
                "bottom_navigation_count": 0,
                "concern_count": 1,
                "extraction_ms": 0.0,
                "projection_ms": 0.0,
                "total_ms": 0.0,
            }
            result["running_region_concerns"] = [{"code": reason}]
            return result

        if input_kind is InputKind.IMAGE:
            projected.setdefault("processing", {})["running_regions"] = {
                "policy_id": RUNNING_REGION_POLICY_ID,
                "status": "not_applicable",
                "reason": "running_region_input_not_applicable",
                "source_page_count": 0,
                "identity_count": 0,
                "detected_label_count": 0,
                "embedded_label_count": 0,
                "legacy_fallback_count": 0,
                "candidate_count": 0,
                "comparison_count": 0,
                "running_region_count": 0,
                "header_count": 0,
                "footer_count": 0,
                "top_navigation_count": 0,
                "bottom_navigation_count": 0,
                "concern_count": 0,
                "extraction_ms": 0.0,
                "projection_ms": 0.0,
                "total_ms": 0.0,
            }
        else:
            try:
                if not isinstance(source_pdf_bytes, bytes) or not source_pdf_bytes:
                    raise RunningRegionSourceOutcomeError(
                        "running_region_source_evidence_unavailable"
                    )
                authority = prepare_source_projection_authority(
                    {
                        "public": projected,
                        "ir": internal_ir.model_dump(mode="json", exclude_none=True),
                    },
                    source_pdf_bytes,
                )
            except RunningRegionSourceOutcomeError as exc:
                projected = nonprojecting_running_regions(
                    projected,
                    status="unavailable",
                    reason=exc.code,
                )
            except Exception:
                projected = nonprojecting_running_regions(
                    projected,
                    status="failed_closed",
                    reason="running_region_projection_failed_closed",
                )
            else:
                predecessor_snapshot: bytes | None = None
                try:
                    predecessor_snapshot = json.dumps(
                        projected,
                        allow_nan=False,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    projected, internal_ir = project_running_regions(
                        projected,
                        internal_ir,
                        authority,
                    )
                except Exception:
                    predecessor = (
                        json.loads(predecessor_snapshot)
                        if predecessor_snapshot is not None
                        else projected
                    )
                    if not isinstance(predecessor, Mapping):
                        raise ValueError(
                            "running-region predecessor snapshot differs"
                        )
                    projected = nonprojecting_running_regions(
                        predecessor,
                        status="failed_closed",
                        reason="running_region_projection_failed_closed",
                    )
    if internal_ir_sink is not None:
        internal_ir_sink["ir"] = internal_ir
    return projected


_SOURCE_ALIGNMENT_SUMMARY_KEYS = frozenset(
    {
        "schema_version",
        "policy_id",
        "source_sha256",
        "status",
        "considered_count",
        "selected_count",
        "unchanged_count",
        "unresolved_count",
        "selections",
        "concerns",
        "elapsed_ms",
    }
)
_TABLE_OWNED_SOURCE_ALIGNMENT_TERMINAL_REASONS = frozenset(
    {
        "table_owned_complete_source_line_duplicate",
        "table_owned_rotated_source_glyph_cell_duplicate",
    }
)


def _source_alignment_terminal_summary(
    *,
    policy_id: str,
    source_sha256: str,
    status: str,
    reason: str | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    concern = (
        {
            "status": "unresolved",
            "reason": reason,
            **({"error_type": error_type} if error_type else {}),
        }
        if reason is not None
        else None
    )
    return {
        "schema_version": "1.0",
        "policy_id": policy_id,
        "source_sha256": source_sha256,
        "status": status,
        "considered_count": 1 if concern is not None else 0,
        "selected_count": 0,
        "unchanged_count": 0,
        "unresolved_count": 1 if concern is not None else 0,
        "selections": [],
        "concerns": [concern] if concern is not None else [],
        "elapsed_ms": 0.0,
    }


def _validate_source_alignment_summary(
    summary: Mapping[str, Any],
    *,
    policy_id: str,
    source_sha256: str,
) -> None:
    if set(summary) != _SOURCE_ALIGNMENT_SUMMARY_KEYS:
        raise ValueError("source alignment summary schema mismatch")
    if summary.get("schema_version") != "1.0":
        raise ValueError("source alignment summary version mismatch")
    if summary.get("policy_id") != policy_id:
        raise ValueError("source alignment policy identity mismatch")
    if summary.get("source_sha256") != source_sha256:
        raise ValueError("source alignment source identity mismatch")
    counts: dict[str, int] = {}
    for name in (
        "considered_count",
        "selected_count",
        "unchanged_count",
        "unresolved_count",
    ):
        value = summary.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("source alignment summary count is invalid")
        counts[name] = value
    selections = summary.get("selections")
    concerns = summary.get("concerns")
    if not isinstance(selections, list) or not isinstance(concerns, list):
        raise ValueError("source alignment summary lists are invalid")
    if len(selections) != counts["selected_count"]:
        raise ValueError("source alignment selection count mismatch")
    if len(concerns) != counts["unresolved_count"]:
        raise ValueError("source alignment concern count mismatch")
    if any(
        not isinstance(concern, Mapping) or concern.get("status") != "unresolved"
        for concern in concerns
    ):
        raise ValueError("source alignment concern is invalid")
    if counts["considered_count"] != (
        counts["selected_count"]
        + counts["unchanged_count"]
        + counts["unresolved_count"]
    ):
        raise ValueError("source alignment terminal counts do not balance")
    status = summary.get("status")
    if status == "selected":
        if counts["selected_count"] == 0:
            raise ValueError("selected source alignment has no selection")
    elif status == "unchanged":
        if counts["selected_count"] != 0:
            raise ValueError("unchanged source alignment has a selection")
    elif status == "refused":
        if (
            counts["selected_count"] != 0
            or counts["unchanged_count"] != 0
            or counts["unresolved_count"] == 0
        ):
            raise ValueError("refused source alignment counts are invalid")
    else:
        raise ValueError("source alignment status is invalid")
    elapsed_ms = summary.get("elapsed_ms")
    if (
        not isinstance(elapsed_ms, (int, float))
        or isinstance(elapsed_ms, bool)
        or not math.isfinite(float(elapsed_ms))
        or float(elapsed_ms) < 0
    ):
        raise ValueError("source alignment elapsed time is invalid")


def _source_alignment_item_strings(item: Mapping[str, Any]) -> list[str]:
    strings: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, Mapping):
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(item.get("value"))
    if item.get("type") == "table":
        rows = item.get("rows") or item.get("value") or []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, list):
                    strings.append(" ".join(str(cell) for cell in row))
    return strings


def _validate_terminal_source_alignment(
    payload: Mapping[str, Any],
    summary: Mapping[str, Any],
    *,
    source_text_evidence: Any | None = None,
    authoritative_table_views: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None = None,
    selected_vector_representations: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None = None,
    prevalidated_selections: Sequence[Mapping[str, Any]] | None = None,
    canonical_ocr_omission_owner_ids: Sequence[str] = (),
) -> None:
    items: dict[str, Mapping[str, Any]] = {}
    all_strings: list[str] = []
    for page in payload.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        for item in page.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            if item.get("source_alignment_suppressed") is True:
                raise ValueError(
                    "source alignment left a test-only suppressed item "
                    "in the public projection"
                )
            identifier = item.get("id")
            if isinstance(identifier, str) and identifier:
                if identifier in items:
                    raise ValueError("source alignment produced duplicate owner IDs")
                items[identifier] = item
            all_strings.extend(_source_alignment_item_strings(item))
    public_text = "\n".join(all_strings)
    raw_selections = summary.get("selections") or []
    if not isinstance(raw_selections, Sequence) or isinstance(
        raw_selections,
        (str, bytes, bytearray),
    ):
        raise ValueError("source alignment selections are invalid")
    selections_to_validate = list(raw_selections)
    if prevalidated_selections is not None:
        if (
            isinstance(prevalidated_selections, (str, bytes, bytearray))
            or not isinstance(prevalidated_selections, Sequence)
            or list(raw_selections[: len(prevalidated_selections)])
            != list(prevalidated_selections)
        ):
            raise ValueError(
                "prevalidated source alignment selections differ"
            )
        selections_to_validate = list(
            raw_selections[len(prevalidated_selections) :]
        )
    omission_owner_ids = [
        selection.get("owner_id")
        for selection in selections_to_validate
        if isinstance(selection, Mapping)
        and selection.get("terminal_reason")
        == _SOURCE_CONTRADICTED_PRIMARY_OCR_REASON
    ]
    if (
        isinstance(canonical_ocr_omission_owner_ids, (str, bytes, bytearray))
        or not isinstance(canonical_ocr_omission_owner_ids, Sequence)
        or list(canonical_ocr_omission_owner_ids) != omission_owner_ids
        or len(omission_owner_ids) != len(set(omission_owner_ids))
    ):
        raise ValueError("canonical OCR omission validation differs")
    table_owned_selections = [
        selection
        for selection in selections_to_validate
        if isinstance(selection, Mapping)
        and selection.get("terminal_reason")
        in _TABLE_OWNED_SOURCE_ALIGNMENT_TERMINAL_REASONS
    ]
    if table_owned_selections:
        from app.services.source_text_alignment import (
            validate_table_owned_suppressions,
        )

        if (
            source_text_evidence is None
            or not validate_table_owned_suppressions(
                table_owned_selections,
                source_text_evidence,
                authoritative_table_views,
            )
        ):
            raise ValueError("table-owned source alignment proof differs")
    from app.services.source_text_alignment import (
        SELECTED_VECTOR_REPRESENTATION_REASON,
    )
    selected_vector_selections = [
        selection
        for selection in selections_to_validate
        if isinstance(selection, Mapping)
        and selection.get("terminal_reason")
        == SELECTED_VECTOR_REPRESENTATION_REASON
    ]
    if selected_vector_selections:
        from app.services.source_text_alignment import (
            validate_selected_vector_suppressions,
        )

        if (
            source_text_evidence is None
            or not validate_selected_vector_suppressions(
                selected_vector_selections,
                source_text_evidence,
                selected_vector_representations,
                payload.get("pages") or [],
            )
        ):
            raise ValueError("selected-vector source alignment proof differs")
    for selection in selections_to_validate:
        if not isinstance(selection, Mapping):
            raise ValueError("source alignment selection is not an object")
        owner_id = selection.get("owner_id")
        original_text = selection.get("original_text")
        selected_text = selection.get("selected_text")
        if (
            not isinstance(owner_id, str)
            or not owner_id
            or not isinstance(original_text, str)
            or not isinstance(selected_text, str)
            or original_text == selected_text
        ):
            raise ValueError("source alignment selection is incomplete")
        owner = items.get(owner_id)
        if (
            owner is None
            and selection.get("owner_type") == "table_cell"
            and ":r" in owner_id
        ):
            owner = items.get(owner_id.split(":r", 1)[0])
        table_owned_suppression = (
            selection.get("terminal_reason")
            in _TABLE_OWNED_SOURCE_ALIGNMENT_TERMINAL_REASONS
            or selection.get("terminal_reason")
            == SELECTED_VECTOR_REPRESENTATION_REASON
        )
        canonical_ocr_omission = (
            selection.get("terminal_reason")
            == _SOURCE_CONTRADICTED_PRIMARY_OCR_REASON
        )
        if canonical_ocr_omission:
            rejected = selection.get("rejected_ocr_alternative")
            owner_snapshot = (
                rejected.get("owner_snapshot")
                if isinstance(rejected, Mapping)
                else None
            )
            if (
                owner is None
                or selected_text != ""
                or owner_snapshot != owner
                or not isinstance(selection.get("owner_type"), str)
                or selection["owner_type"].casefold()
                not in {"text", "heading"}
            ):
                raise ValueError(
                    "canonical OCR omission retained owner differs"
                )
        elif table_owned_suppression:
            if (
                owner is not None
                or selected_text != ""
            ):
                raise ValueError(
                    "table-owned source alignment proof differs"
                )
        elif owner is not None:
            owner_text = "\n".join(_source_alignment_item_strings(owner))
            if not selected_text or selected_text not in owner_text:
                raise ValueError(
                    "source alignment selection is absent from its terminal owner"
                )
        elif selection.get("rejected_ocr_alternative") is None:
            raise ValueError(
                "source alignment removed an owner without retaining "
                "the rejected alternative"
            )
        if selected_text and selected_text not in public_text:
            raise ValueError(
                "source alignment selection is absent from the "
                "terminal public projection"
            )
        if (
            not table_owned_suppression
            and not canonical_ocr_omission
            and not selected_text
            and original_text in public_text
        ):
            raise ValueError(
                "source alignment rejected text remains in the "
                "terminal public projection"
            )


def _apply_terminal_canonical_ocr_omission(
    candidate: dict[str, Any],
    terminal_ir: Any,
    summary: dict[str, Any],
    *,
    source_text_evidence: Any | None,
    selected_vector_representations: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None,
    source_pdf_bytes: bytes | None,
    authoritative_table_views: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Locally commit a validated canonical-only OCR omission.

    Failure in this optional lane must never roll back the already validated
    public/IR source-alignment transaction.
    """

    try:
        if (
            not selected_vector_representations
            or authoritative_table_views is not None
            or terminal_ir is None
            or not isinstance(source_pdf_bytes, bytes)
            or not source_pdf_bytes
            or source_text_evidence is None
            or candidate.get("canonical_presentation") is None
        ):
            return candidate, summary
        raw_core_selections = summary.get("selections")
        if type(raw_core_selections) is not list or any(
            not isinstance(value, Mapping) for value in raw_core_selections
        ):
            return candidate, summary
        # The omission service is independently tested to be non-mutating.
        # Keep only a shallow structural prefix here: the production report can
        # approach the bounded 8 MiB limit, and duplicating it would add large
        # optional-lane latency before the service's own resource deadline.
        core_selections = list(raw_core_selections)
        from app.services.canonical_ocr_omission import (
            apply_source_contradicted_primary_ocr_omissions,
            validate_source_contradicted_primary_ocr_omissions,
        )

        projected, projected_summary = (
            apply_source_contradicted_primary_ocr_omissions(
                candidate,
                terminal_ir,
                summary,
                source_text_evidence,
                selected_vector_representations,
                source_pdf_bytes,
            )
        )
        if summary.get("selections") != core_selections:
            return candidate, summary
        if projected is candidate and projected_summary is summary:
            return candidate, summary
        if type(projected) is not dict or type(projected_summary) is not dict:
            return candidate, summary
        raw_projected_selections = projected_summary.get("selections")
        if (
            type(raw_projected_selections) is not list
            or raw_projected_selections[: len(core_selections)]
            != core_selections
        ):
            return candidate, summary
        omission_selections = raw_projected_selections[len(core_selections) :]
        omission_owner_ids = [
            selection.get("owner_id")
            for selection in omission_selections
            if isinstance(selection, Mapping)
            and selection.get("terminal_reason")
            == _SOURCE_CONTRADICTED_PRIMARY_OCR_REASON
        ]
        if (
            not omission_selections
            or len(omission_selections) != len(omission_owner_ids)
            or any(
                type(value) is not str or not value
                for value in omission_owner_ids
            )
            or len(omission_owner_ids) != len(set(omission_owner_ids))
        ):
            return candidate, summary
        if set(projected) != set(candidate) or any(
            projected.get(key) != candidate.get(key)
            for key in candidate
            if key not in {"canonical_presentation", "processing"}
        ):
            return candidate, summary
        prior_processing = candidate.get("processing")
        projected_processing = projected.get("processing")
        if (
            not isinstance(prior_processing, Mapping)
            or not isinstance(projected_processing, Mapping)
            or projected_processing.get("source_text_alignment")
            != projected_summary
            or {
                key: value
                for key, value in projected_processing.items()
                if key != "source_text_alignment"
            }
            != {
                key: value
                for key, value in prior_processing.items()
                if key != "source_text_alignment"
            }
        ):
            return candidate, summary
        if not validate_source_contradicted_primary_ocr_omissions(
            projected,
            terminal_ir,
            projected_summary,
            source_text_evidence,
            selected_vector_representations,
            source_pdf_bytes,
        ):
            return candidate, summary
        _validate_terminal_source_alignment(
            projected,
            projected_summary,
            source_text_evidence=source_text_evidence,
            authoritative_table_views=authoritative_table_views,
            selected_vector_representations=selected_vector_representations,
            prevalidated_selections=core_selections,
            canonical_ocr_omission_owner_ids=omission_owner_ids,
        )
        committed = dict(candidate)
        committed["canonical_presentation"] = deepcopy(
            projected["canonical_presentation"]
        )
        committed_summary = deepcopy(projected_summary)
        committed_processing = dict(prior_processing)
        committed_processing["source_text_alignment"] = committed_summary
        committed["processing"] = committed_processing
        return committed, committed_summary
    except Exception:
        return candidate, summary


_TERMINAL_RUNNING_REGION_SIDECAR_KEYS = frozenset(
    {
        "layout_running_region_projected",
        "running_region_policy",
        "running_region",
    }
)


def _terminal_running_alignment_owner_closure(
    payload: Mapping[str, Any],
    owner_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Freeze exact aligned owners across the US08 terminal replay.

    Running-region replay is authorized to restore only its three public
    sidecars.  In particular, authorization by owner ID must not mask changes
    to source-aligned value/Markdown, nested contributors, provenance, or any
    other public owner field.
    """

    if (
        isinstance(owner_ids, (str, bytes, bytearray))
        or not isinstance(owner_ids, Sequence)
        or any(not isinstance(value, str) or not value for value in owner_ids)
        or len(owner_ids) != len(set(owner_ids))
    ):
        raise ValueError("terminal running-region owner closure differs")
    expected = set(owner_ids)
    closures: dict[str, dict[str, Any]] = {}
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise ValueError("terminal running-region owner pages differ")
    for page in pages:
        if not isinstance(page, Mapping):
            raise ValueError("terminal running-region owner page differs")
        items = page.get("items")
        if not isinstance(items, list):
            raise ValueError("terminal running-region owner items differ")
        for item in items:
            if not isinstance(item, Mapping):
                continue
            owner_id = item.get("id")
            if owner_id not in expected:
                continue
            if owner_id in closures:
                raise ValueError("terminal running-region owner repeats")
            closures[owner_id] = {
                key: deepcopy(value)
                for key, value in item.items()
                if key not in _TERMINAL_RUNNING_REGION_SIDECAR_KEYS
            }
    if set(closures) != expected:
        raise ValueError("terminal running-region owner coverage differs")
    return closures


def _terminal_running_alignment_dependencies_are_closed(
    payload: Mapping[str, Any],
    terminal_ir: Any,
    owner_ids: Sequence[str],
) -> bool:
    """Bind replay-issued descriptor evidence to the rebuilt typed IR."""

    expected = set(owner_ids)
    if len(expected) != len(owner_ids):
        return False
    elements = getattr(terminal_ir, "elements", None)
    evidence = getattr(terminal_ir, "evidence", None)
    if not isinstance(elements, list) or not isinstance(evidence, list):
        return False
    elements_by_id = {
        getattr(element, "id", None): element
        for element in elements
        if isinstance(getattr(element, "id", None), str)
    }
    evidence_by_id = {
        getattr(record, "id", None): record
        for record in evidence
        if isinstance(getattr(record, "id", None), str)
    }
    if len(elements_by_id) != len(elements) or len(evidence_by_id) != len(evidence):
        return False

    observed: set[str] = set()
    for page in payload.get("pages") or []:
        if not isinstance(page, Mapping):
            return False
        for item in page.get("items") or []:
            if not isinstance(item, Mapping) or item.get("id") not in expected:
                continue
            owner_id = str(item["id"])
            if owner_id in observed:
                return False
            observed.add(owner_id)
            descriptor = item.get("running_region")
            if not isinstance(descriptor, Mapping):
                return False
            source_element_id = descriptor.get("source_element_id")
            evidence_ids = descriptor.get("evidence_ids")
            bbox_id = descriptor.get("bbox_id")
            if (
                not isinstance(source_element_id, str)
                or not source_element_id
                or not isinstance(evidence_ids, list)
                or not evidence_ids
                or any(
                    not isinstance(value, str) or not value
                    for value in evidence_ids
                )
                or not isinstance(bbox_id, str)
                or not bbox_id
            ):
                return False
            element = elements_by_id.get(source_element_id)
            running_region = getattr(element, "running_region", None)
            element_evidence_ids = list(getattr(element, "evidence_ids", ()))
            if (
                element is None
                or len(element_evidence_ids) != len(set(element_evidence_ids))
                or len(evidence_ids) != len(set(evidence_ids))
                or not set(evidence_ids).issubset(element_evidence_ids)
                or running_region is None
                or running_region.model_dump(mode="json") != dict(descriptor)
            ):
                return False
            for evidence_id in evidence_ids:
                record = evidence_by_id.get(evidence_id)
                method = getattr(record, "method", None)
                method_value = getattr(method, "value", method)
                if (
                    record is None
                    or getattr(record, "element_id", None) != source_element_id
                    or getattr(record, "bbox_id", None) != bbox_id
                    or getattr(record, "value", None) != item.get("value")
                    or method_value != "native"
                ):
                    return False
    return observed == expected


def _terminal_running_alignment_identity_matches(
    baseline: Mapping[str, Any],
    replayed: Mapping[str, Any],
    owner_ids: Sequence[str],
) -> bool:
    """Normalize only deterministic descriptor identities of aligned owners."""

    expected = set(owner_ids)
    if len(expected) != len(owner_ids):
        return False
    normalized = deepcopy(dict(replayed))
    baseline_regions = baseline.get("regions")
    replayed_regions = normalized.get("regions")
    if not isinstance(baseline_regions, list) or not isinstance(
        replayed_regions, list
    ) or len(baseline_regions) != len(replayed_regions):
        return False
    group_transitions: dict[str | None, str | None] = {}
    reverse_group_transitions: dict[str | None, str | None] = {}
    observed: set[str] = set()
    for baseline_region, replayed_region in zip(
        baseline_regions,
        replayed_regions,
        strict=True,
    ):
        if not isinstance(baseline_region, Mapping) or not isinstance(
            replayed_region, Mapping
        ):
            return False
        baseline_descriptor = baseline_region.get("descriptor")
        replayed_descriptor = replayed_region.get("descriptor")
        if not isinstance(baseline_descriptor, Mapping) or not isinstance(
            replayed_descriptor, dict
        ):
            return False
        owner_id = replayed_descriptor.get("source_public_item_id")
        if owner_id not in expected:
            continue
        if owner_id in observed:
            return False
        observed.add(owner_id)
        if (
            baseline_descriptor.get("source_public_item_id") != owner_id
            or len(baseline_descriptor.get("evidence_ids") or [])
            != len(replayed_descriptor.get("evidence_ids") or [])
            or baseline_descriptor.get("repetition_page_indexes")
            != replayed_descriptor.get("repetition_page_indexes")
        ):
            return False
        old_group = baseline_descriptor.get("repetition_group_id")
        new_group = replayed_descriptor.get("repetition_group_id")
        if old_group in group_transitions and group_transitions[old_group] != new_group:
            return False
        if (
            new_group in reverse_group_transitions
            and reverse_group_transitions[new_group] != old_group
        ):
            return False
        group_transitions[old_group] = new_group
        reverse_group_transitions[new_group] = old_group
        replayed_descriptor["evidence_ids"] = deepcopy(
            baseline_descriptor["evidence_ids"]
        )
        replayed_descriptor["repetition_group_id"] = old_group
    return observed == expected and normalized == baseline


def _outline_replay_identity(
    payload: Mapping[str, Any],
) -> tuple[
    tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    ...,
]:
    """Return the exact projected outline graph identity for terminal replay."""

    identities: list[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = []
    for page in payload.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        for item in page.get("items") or []:
            if not isinstance(item, Mapping) or (
                item.get("layout_outline_structure_projected") is not True
            ):
                continue
            group = item.get("outline_group")
            if not isinstance(group, Mapping):
                raise ValueError("projected outline group is unavailable")
            group_id = group.get("id")
            members = group.get("member_element_ids")
            continuations = group.get("continuation_element_ids")
            relationships = group.get("relationship_ids")
            if (
                not isinstance(group_id, str)
                or not group_id
                or not isinstance(members, list)
                or not isinstance(continuations, list)
                or not isinstance(relationships, list)
                or any(
                    not isinstance(value, str) or not value
                    for values in (members, continuations, relationships)
                    for value in values
                )
            ):
                raise ValueError("projected outline graph identity differs")
            identities.append(
                (
                    group_id,
                    tuple(members),
                    tuple(continuations),
                    tuple(relationships),
                )
            )
    if len({value[0] for value in identities}) != len(identities):
        raise ValueError("projected outline group identity repeats")
    return tuple(identities)


def _table_authority_views_from_transaction(
    transaction: tuple[Any, ...],
) -> dict[int, list[Mapping[str, Any]]]:
    """Expose only held, snapshot-free P04 overlays as read-only views."""

    if not isinstance(transaction, tuple):
        raise ValueError("table authority transaction differs")
    views: dict[int, list[Mapping[str, Any]]] = {}
    for record in transaction:
        if not isinstance(record, tuple) or len(record) != 7:
            raise ValueError("table authority transaction record differs")
        page_index = record[1]
        overlay = record[5]
        if (
            not isinstance(page_index, int)
            or isinstance(page_index, bool)
            or page_index < 1
            or not isinstance(overlay, Mapping)
            or overlay.get("type") != "table"
            or "_p04_predecessor_snapshot" in overlay
        ):
            raise ValueError("table authority transaction view differs")
        views.setdefault(page_index, []).append(overlay)
    return views


def _has_table_owned_source_suppression(payload: Mapping[str, Any]) -> bool:
    from app.services.source_text_alignment import (
        TABLE_OWNED_TERMINAL_REASONS,
    )
    summary = (payload.get("processing") or {}).get(
        "source_text_alignment"
    )
    return bool(
        isinstance(summary, Mapping)
        and any(
            isinstance(selection, Mapping)
            and selection.get("terminal_reason")
            in TABLE_OWNED_TERMINAL_REASONS
            for selection in summary.get("selections") or []
        )
    )


def _selected_vector_terminal_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 8 * 1024 * 1024:
        raise ValueError("selected vector terminal binding exceeds size limit")
    return hashlib.sha256(encoded).hexdigest()


_SELECTED_VECTOR_RAW_COLLECTIONS = (
    "groups",
    "texts",
    "pictures",
    "tables",
    "key_value_items",
    "form_items",
    "field_regions",
    "field_items",
)
_SELECTED_VECTOR_RAW_MAX_RECORDS = 2_048
_SELECTED_VECTOR_RAW_MAX_PUBLIC_ITEMS = 10_000
_SELECTED_VECTOR_RAW_MAX_IR_RECORDS = 50_000
_SELECTED_VECTOR_RAW_MAX_JSON_NODES = 250_000
_SELECTED_VECTOR_RAW_MAX_JSON_DEPTH = 64
_SELECTED_VECTOR_RAW_MAX_STRING_CODEPOINTS = 1_048_576


def _selected_vector_bounded_json_preflight(
    value: Any,
    *,
    deadline: float,
) -> int:
    """Bound JSON scalars/depth before ``JSONEncoder`` can emit a huge chunk."""

    stack: list[tuple[bool, Any, int]] = [(False, value, 0)]
    active_containers: set[int] = set()
    node_count = 0
    string_bytes = 0

    def account_string(candidate: str) -> None:
        nonlocal string_bytes
        if len(candidate) > _SELECTED_VECTOR_RAW_MAX_STRING_CODEPOINTS:
            raise ValueError("selected vector JSON string limit")
        for start in range(0, len(candidate), 4_096):
            if time.perf_counter() > deadline:
                raise TimeoutError("selected vector JSON preflight deadline")
            string_bytes += len(candidate[start : start + 4_096].encode("utf-8"))
            if string_bytes > 8 * 1024 * 1024:
                raise ValueError("selected vector JSON string byte limit")

    while stack:
        exiting, candidate, depth = stack.pop()
        if exiting:
            active_containers.remove(id(candidate))
            continue
        node_count += 1
        if node_count > _SELECTED_VECTOR_RAW_MAX_JSON_NODES:
            raise ValueError("selected vector JSON node limit")
        if node_count % 256 == 0 and time.perf_counter() > deadline:
            raise TimeoutError("selected vector JSON preflight deadline")
        if depth > _SELECTED_VECTOR_RAW_MAX_JSON_DEPTH:
            raise ValueError("selected vector JSON depth limit")
        if type(candidate) is str:
            account_string(candidate)
            continue
        if candidate is None or type(candidate) is bool:
            continue
        if type(candidate) is int:
            if candidate.bit_length() > 4_096:
                raise ValueError("selected vector JSON integer limit")
            continue
        if type(candidate) is float:
            if not math.isfinite(candidate):
                raise ValueError("selected vector JSON numeric value differs")
            continue
        if type(candidate) not in (dict, list):
            raise ValueError("selected vector JSON value differs")
        container_id = id(candidate)
        if container_id in active_containers:
            raise ValueError("selected vector JSON cycle differs")
        active_containers.add(container_id)
        stack.append((True, candidate, depth))
        if type(candidate) is dict:
            if len(candidate) > _SELECTED_VECTOR_RAW_MAX_JSON_NODES:
                raise ValueError("selected vector JSON mapping limit")
            for key, child in candidate.items():
                if type(key) is not str:
                    raise ValueError("selected vector JSON key differs")
                account_string(key)
                stack.append((False, child, depth + 1))
        else:
            if len(candidate) > _SELECTED_VECTOR_RAW_MAX_JSON_NODES:
                raise ValueError("selected vector JSON sequence limit")
            for child in reversed(candidate):
                stack.append((False, child, depth + 1))
    return string_bytes


def _selected_vector_raw_reference_context(
    payload: Mapping[str, Any],
    raw_graph: Mapping[str, Any] | None,
    native_texts: Sequence[str],
    *,
    deadline: float,
) -> dict[str, Any] | None:
    """Rebuild a bounded independent IR witness for raw table provenance."""

    if raw_graph is None or not raw_graph:
        return None
    if type(raw_graph) is not dict or type(payload) is not dict:
        raise ValueError("selected vector raw graph differs")
    if time.perf_counter() > deadline:
        raise TimeoutError("selected vector raw graph deadline")
    references: dict[str, Mapping[str, Any]] = {}
    raw_record_count = 0
    for collection_name in _SELECTED_VECTOR_RAW_COLLECTIONS:
        values = raw_graph.get(collection_name) or []
        if type(values) is not list:
            raise ValueError("selected vector raw collection differs")
        raw_record_count += len(values)
        if raw_record_count > _SELECTED_VECTOR_RAW_MAX_RECORDS:
            raise ValueError("selected vector raw record limit")
        for record_index, record in enumerate(values):
            if record_index % 128 == 0 and time.perf_counter() > deadline:
                raise TimeoutError("selected vector raw graph deadline")
            if type(record) is not dict:
                raise ValueError("selected vector raw record differs")
            raw_ref = record.get("self_ref")
            if (
                type(raw_ref) is not str
                or not raw_ref
                or len(raw_ref.encode("utf-8")) > 512
                or raw_ref in references
            ):
                raise ValueError("selected vector raw reference differs")
            references[raw_ref] = record
    roots: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for root_name in ("body", "furniture"):
        root = raw_graph.get(root_name)
        if root is None:
            continue
        if type(root) is not dict:
            raise ValueError("selected vector raw root differs")
        root_ref = root.get("self_ref", f"#/{root_name}")
        children = root.get("children") or []
        if (
            type(root_ref) is not str
            or not root_ref
            or root_ref in roots
            or type(children) is not list
            or len(children) > _SELECTED_VECTOR_RAW_MAX_RECORDS
        ):
            raise ValueError("selected vector raw root differs")
        for child_index, child in enumerate(children):
            if child_index % 128 == 0 and time.perf_counter() > deadline:
                raise TimeoutError("selected vector raw graph deadline")
            if (
                type(child) is not dict
                or set(child) != {"$ref"}
                or type(child.get("$ref")) is not str
                or not child["$ref"]
            ):
                raise ValueError("selected vector raw root child differs")
        roots[root_ref] = (root_name, root)
    _selected_vector_bounded_json_preflight(
        raw_graph,
        deadline=deadline,
    )
    raw_digest = hashlib.sha256()
    raw_bytes = 0
    encoder = json.JSONEncoder(
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        for chunk_index, chunk in enumerate(encoder.iterencode(raw_graph)):
            if chunk_index % 128 == 0 and time.perf_counter() > deadline:
                raise TimeoutError("selected vector raw graph deadline")
            encoded = chunk.encode("utf-8")
            raw_bytes += len(encoded)
            if raw_bytes > 8 * 1024 * 1024:
                raise ValueError("selected vector raw graph byte limit")
            raw_digest.update(encoded)
    except UnicodeEncodeError:
        raise ValueError("selected vector raw graph encoding differs") from None
    raw_graph_sha256 = raw_digest.hexdigest()
    pages = payload.get("pages")
    if type(pages) is not list or len(pages) > 100:
        raise ValueError("selected vector raw public pages differ")
    public_item_count = 0
    for page_index, page in enumerate(pages):
        if page_index % 16 == 0 and time.perf_counter() > deadline:
            raise TimeoutError("selected vector raw graph deadline")
        items = page.get("items") if type(page) is dict else None
        if type(items) is not list:
            raise ValueError("selected vector raw public page differs")
        public_item_count += len(items)
        if public_item_count > _SELECTED_VECTOR_RAW_MAX_PUBLIC_ITEMS:
            raise ValueError("selected vector raw public item limit")
    _selected_vector_bounded_json_preflight(pages, deadline=deadline)
    public_bytes = 0
    try:
        for chunk_index, chunk in enumerate(encoder.iterencode(pages)):
            if chunk_index % 128 == 0 and time.perf_counter() > deadline:
                raise TimeoutError("selected vector raw public deadline")
            public_bytes += len(chunk.encode("utf-8"))
            if public_bytes > 8 * 1024 * 1024:
                raise ValueError("selected vector raw public byte limit")
    except UnicodeEncodeError:
        raise ValueError("selected vector raw public encoding differs") from None
    if (
        isinstance(native_texts, (str, bytes, bytearray))
        or not isinstance(native_texts, Sequence)
        or len(native_texts) > 100
        or any(type(value) is not str for value in native_texts)
    ):
        raise ValueError("selected vector native text witness differs")
    _selected_vector_bounded_json_preflight(
        list(native_texts),
        deadline=deadline,
    )
    if time.perf_counter() > deadline:
        raise TimeoutError("selected vector raw graph deadline")
    from app.services.ir import build_document_ir

    reference_ir = build_document_ir(
        payload,
        raw_graph=raw_graph,
        native_texts=tuple(native_texts),
    )
    if time.perf_counter() > deadline:
        raise TimeoutError("selected vector raw graph deadline")
    record_count = sum(
        len(records)
        for records in (
            reference_ir.coordinate_systems,
            reference_ir.pages,
            reference_ir.regions,
            reference_ir.elements,
            reference_ir.evidence,
            reference_ir.bboxes,
            reference_ir.text_rules,
            reference_ir.text_runs,
            reference_ir.relationships,
            reference_ir.concerns,
        )
    )
    if record_count > _SELECTED_VECTOR_RAW_MAX_IR_RECORDS:
        raise ValueError("selected vector raw reference IR limit")
    return {
        "ir": reference_ir,
        "references": references,
        "roots": roots,
        "raw_graph_sha256": raw_graph_sha256,
    }


def _bind_selected_vector_terminal_representations(
    payload: Mapping[str, Any],
    internal_ir: Any,
    representations: Mapping[int, Sequence[Mapping[str, Any]]] | None,
    source_sha256: str,
    *,
    raw_graph: Mapping[str, Any] | None = None,
    native_texts: Sequence[str] = (),
) -> dict[int, list[dict[str, Any]]]:
    """Bind optional vector authority to exact public, IR, and canonical owners."""

    if not representations:
        return {}
    deadline = time.perf_counter() + 2.0
    comparisons = 0

    def check_deadline() -> None:
        if time.perf_counter() > deadline:
            raise TimeoutError("selected vector terminal binding deadline")

    try:
        from app.services.ir import DocumentIR
        from app.services.table_semantics import (
            admit_selected_vector_representation,
        )

        if (
            type(representations) not in (dict, defaultdict)
            or len(representations) > 100
            or type(payload) is not dict
            or type(internal_ir) is not DocumentIR
            or internal_ir.source_sha256 != source_sha256
            or (payload.get("document") or {}).get("sha256") != source_sha256
        ):
            return {}
        raw_reference_context = _selected_vector_raw_reference_context(
            payload,
            raw_graph,
            native_texts,
            deadline=deadline,
        )
        pages = payload.get("pages")
        canonical = payload.get("canonical_presentation")
        canonical_pages = (
            canonical.get("pages") if type(canonical) is dict else None
        )
        if type(pages) is not list or type(canonical_pages) is not list:
            return {}
        pages_by_index: dict[int, Mapping[str, Any]] = {}
        for page in pages:
            check_deadline()
            if type(page) is not dict:
                return {}
            page_index = page.get("page_index")
            if (
                type(page_index) is not int
                or page_index < 1
                or page_index in pages_by_index
            ):
                return {}
            pages_by_index[page_index] = page
        canonical_by_index: dict[int, Mapping[str, Any]] = {}
        canonical_block_ids: list[str] = []
        for page in canonical_pages:
            check_deadline()
            if type(page) is not dict:
                return {}
            page_index = page.get("page_index")
            if (
                type(page_index) is not int
                or page_index < 1
                or page_index in canonical_by_index
            ):
                return {}
            canonical_by_index[page_index] = page
            page_id = page.get("page_id")
            blocks = page.get("blocks")
            if type(page_id) is not str or not page_id or type(blocks) is not list:
                return {}
            for block in blocks:
                if type(block) is not dict:
                    return {}
                block_id = block.get("id")
                if type(block_id) is not str or not block_id:
                    return {}
                canonical_block_ids.append(block_id)
        if len(canonical_block_ids) != len(set(canonical_block_ids)):
            return {}
        ir_record_collections = (
            internal_ir.coordinate_systems,
            internal_ir.pages,
            internal_ir.regions,
            internal_ir.elements,
            internal_ir.evidence,
            internal_ir.bboxes,
            internal_ir.text_rules,
            internal_ir.text_runs,
            internal_ir.relationships,
        )
        ir_record_ids: list[str] = []
        for records in ir_record_collections:
            check_deadline()
            for record in records:
                identifier = getattr(record, "id", None)
                if type(identifier) is not str or not identifier:
                    return {}
                ir_record_ids.append(identifier)
        if len(ir_record_ids) != len(set(ir_record_ids)):
            return {}
        ir_pages_by_index = {page.page_index: page for page in internal_ir.pages}
        if len(ir_pages_by_index) != len(internal_ir.pages):
            return {}
        bboxes_by_id = {bbox.id: bbox for bbox in internal_ir.bboxes}
        coordinates_by_id = {
            coordinate.id: coordinate
            for coordinate in internal_ir.coordinate_systems
        }
        evidence_by_id = {
            evidence.id: evidence for evidence in internal_ir.evidence
        }
        elements_by_legacy_id: dict[str, list[Any]] = defaultdict(list)
        ir_elements_by_id = {element.id: element for element in internal_ir.elements}
        for element in internal_ir.elements:
            check_deadline()
            legacy = element.properties.get("legacy_item")
            if type(legacy) is dict and type(legacy.get("id")) is str:
                elements_by_legacy_id[legacy["id"]].append(element)
        reference_elements_by_legacy_id: dict[str, list[Any]] = defaultdict(list)
        reference_elements_by_id: dict[str, Any] = {}
        reference_bboxes_by_id: dict[str, Any] = {}
        reference_evidence_by_id: dict[str, Any] = {}
        reference_relationships_by_id: dict[str, Any] = {}
        reference_coordinates_by_id: dict[str, Any] = {}
        if raw_reference_context is not None:
            reference_ir = raw_reference_context["ir"]
            if reference_ir.source_sha256 != source_sha256:
                return {}
            reference_elements_by_id = {
                element.id: element for element in reference_ir.elements
            }
            reference_bboxes_by_id = {
                bbox.id: bbox for bbox in reference_ir.bboxes
            }
            reference_evidence_by_id = {
                evidence.id: evidence for evidence in reference_ir.evidence
            }
            reference_relationships_by_id = {
                relationship.id: relationship
                for relationship in reference_ir.relationships
            }
            reference_coordinates_by_id = {
                coordinate.id: coordinate
                for coordinate in reference_ir.coordinate_systems
            }
            if any(
                len(records) != len(index)
                for records, index in (
                    (reference_ir.elements, reference_elements_by_id),
                    (reference_ir.bboxes, reference_bboxes_by_id),
                    (reference_ir.evidence, reference_evidence_by_id),
                    (reference_ir.relationships, reference_relationships_by_id),
                    (reference_ir.coordinate_systems, reference_coordinates_by_id),
                )
            ):
                return {}
            for element in reference_ir.elements:
                check_deadline()
                legacy = element.properties.get("legacy_item")
                if type(legacy) is dict and type(legacy.get("id")) is str:
                    reference_elements_by_legacy_id[legacy["id"]].append(element)
        expected_legacy_reading_pairs: set[tuple[str, str]] = set()
        for ir_page in internal_ir.pages:
            ordered = []
            for element_id in ir_page.presentation_element_ids:
                element = ir_elements_by_id.get(element_id)
                source_position = (
                    element.properties.get("source_position")
                    if element is not None
                    and type(element.properties) is dict
                    else None
                )
                if (
                    element is None
                    or element.page_id != ir_page.id
                    or type(element.reading_order) is not int
                    or type(source_position) is not int
                ):
                    return {}
                ordered.append(
                    (element.reading_order, source_position, element.id)
                )
            ordered.sort()
            expected_legacy_reading_pairs.update(
                (first[2], second[2])
                for first, second in zip(ordered, ordered[1:])
            )
        observed_legacy_reading_pairs: list[tuple[str, str]] = []
        for relationship in internal_ir.relationships:
            if str(relationship.type.value) != "reading_before":
                continue
            if relationship.metadata == {"basis": "legacy_reading_order"}:
                if relationship.evidence_ids != []:
                    return {}
                observed_legacy_reading_pairs.append(
                    (relationship.source_id, relationship.target_id)
                )
                continue
            # The IR builder deterministically coalesces a source-grounded raw
            # reading edge with the legacy edge when both describe the same
            # adjacent public pair.  Count that exact reference-replayed form
            # in the legacy chain while retaining its raw evidence/metadata for
            # the selected-table custody proof below.
            metadata = relationship.metadata
            reference_metadata = (
                metadata.get("reference_metadata")
                if type(metadata) is dict
                else None
            )
            reference_relationship = reference_relationships_by_id.get(
                relationship.id
            )
            if (
                type(metadata) is dict
                and set(metadata) == {"basis", "reference_metadata"}
                and metadata.get("basis") == "legacy_reading_order"
                and type(reference_metadata) is list
                and len(reference_metadata) == 1
                and type(reference_metadata[0]) is dict
                and set(reference_metadata[0])
                == {
                    "root_container",
                    "source_child_index",
                    "target_child_index",
                }
                and reference_metadata[0].get("root_container")
                in {"#/body", "#/furniture"}
                and type(reference_metadata[0].get("source_child_index")) is int
                and type(reference_metadata[0].get("target_child_index")) is int
                and reference_metadata[0]["target_child_index"]
                == reference_metadata[0]["source_child_index"] + 1
                and relationship.source_id in ir_elements_by_id
                and relationship.target_id in ir_elements_by_id
                and bool(relationship.evidence_ids)
                and len(relationship.evidence_ids)
                == len(set(relationship.evidence_ids))
                and all(
                    identifier in evidence_by_id
                    for identifier in relationship.evidence_ids
                )
                and reference_relationship is not None
                and relationship.model_dump(mode="json")
                == reference_relationship.model_dump(mode="json")
            ):
                observed_legacy_reading_pairs.append(
                    (relationship.source_id, relationship.target_id)
                )
        if (
            len(observed_legacy_reading_pairs)
            != len(set(observed_legacy_reading_pairs))
            or set(observed_legacy_reading_pairs)
            != expected_legacy_reading_pairs
        ):
            return {}

        base_element_property_keys = {
            "legacy_item",
            "generated",
            "region_role",
            "content_type",
            "source_position",
        }
        raw_table_property_keys = base_element_property_keys | {
            "raw_refs",
            "raw_label",
            "raw_metadata",
            "root_containers",
        }

        def raw_provenance_custody(
            element: Any,
            *,
            public_id: str,
            page_index: int,
            prior_running_projection: Any = None,
        ) -> dict[str, Any] | None:
            """Return one exact, source-replayed raw table custody seal."""

            if set(element.properties) == base_element_property_keys:
                if raw_reference_context is not None:
                    reference_matches = reference_elements_by_legacy_id.get(
                        public_id, []
                    )
                    if (
                        len(reference_matches) != 1
                        or set(reference_matches[0].properties)
                        != base_element_property_keys
                    ):
                        raise ValueError(
                            "selected vector raw table provenance is missing"
                        )
                return None
            if (
                set(element.properties) != raw_table_property_keys
                or raw_reference_context is None
            ):
                raise ValueError("selected vector raw table properties differ")
            reference_matches = reference_elements_by_legacy_id.get(public_id, [])
            if len(reference_matches) != 1:
                raise ValueError("selected vector raw table reference differs")
            reference_element = reference_matches[0]
            if (
                element.model_dump(mode="json")
                != reference_element.model_dump(mode="json")
            ):
                raise ValueError("selected vector raw table IR differs")
            raw_refs = element.properties.get("raw_refs")
            raw_ref = raw_refs[0] if type(raw_refs) is list and len(raw_refs) == 1 else None
            references = raw_reference_context["references"]
            raw_table = references.get(raw_ref)
            roots = element.properties.get("root_containers")
            root = roots[0] if type(roots) is list and len(roots) == 1 else None
            root_ref = root.get("ref") if type(root) is dict else None
            root_record = raw_reference_context["roots"].get(root_ref)
            raw_provenance = raw_table.get("prov") if type(raw_table) is dict else None
            expected_raw_metadata = {
                key: deepcopy(raw_table[key])
                for key in ("annotations", "meta")
                if raw_table.get(key) is not None
            } if type(raw_table) is dict else None
            if (
                type(raw_ref) is not str
                or not raw_ref.startswith("#/tables/")
                or type(raw_table) is not dict
                or raw_table.get("self_ref") != raw_ref
                or raw_table.get("label") != "table"
                or type(raw_provenance) is not list
                or len(raw_provenance) != 1
                or type(raw_provenance[0]) is not dict
                or type(raw_provenance[0].get("page_no")) is not int
                or raw_provenance[0].get("page_no") != page_index
                or expected_raw_metadata is None
                or not expected_raw_metadata
                or element.properties.get("raw_label") != "table"
                or element.properties.get("raw_metadata")
                != {raw_ref: expected_raw_metadata}
                or type(root) is not dict
                or set(root) != {"name", "ref", "child_index"}
                or root.get("name") != "body"
                or root_ref != "#/body"
                or type(root.get("child_index")) is not int
                or root.get("child_index") < 0
                or root_record is None
                or root_record[0] != "body"
            ):
                raise ValueError("selected vector raw table source differs")
            body = root_record[1]
            children = body.get("children")
            child_index = root["child_index"]
            if (
                type(children) is not list
                or child_index + 1 >= len(children)
                or children[child_index] != {"$ref": raw_ref}
                or type(children[child_index + 1]) is not dict
                or set(children[child_index + 1]) != {"$ref"}
            ):
                raise ValueError("selected vector raw table adjacency differs")
            target_ref = children[child_index + 1]["$ref"]
            target_raw = references.get(target_ref)
            if type(target_ref) is not str or type(target_raw) is not dict:
                raise ValueError("selected vector raw target differs")

            if (
                element.bbox_ids != reference_element.bbox_ids
                or element.evidence_ids != reference_element.evidence_ids
                or len(element.bbox_ids) != 2
                or len(element.evidence_ids) != 3
            ):
                raise ValueError("selected vector raw table record closure differs")
            raw_bbox = bboxes_by_id.get(element.bbox_ids[1])
            reference_raw_bbox = reference_bboxes_by_id.get(element.bbox_ids[1])
            raw_coordinate = (
                coordinates_by_id.get(raw_bbox.coordinate_system_id)
                if raw_bbox is not None
                else None
            )
            primary_bbox = bboxes_by_id.get(element.bbox_ids[0])
            reference_raw_coordinate = (
                reference_coordinates_by_id.get(raw_bbox.coordinate_system_id)
                if raw_bbox is not None
                else None
            )
            raw_evidence_candidates = [
                evidence_by_id.get(identifier)
                for identifier in element.evidence_ids
                if evidence_by_id.get(identifier) is not None
                and str(evidence_by_id[identifier].method.value) == "derived"
            ]
            if (
                raw_bbox is None
                or reference_raw_bbox is None
                or raw_bbox.role != "child"
                or raw_bbox.model_dump(mode="json")
                != reference_raw_bbox.model_dump(mode="json")
                or raw_coordinate is None
                or reference_raw_coordinate is None
                or primary_bbox is None
                or raw_coordinate.id == primary_bbox.coordinate_system_id
                or raw_coordinate.page_id != element.page_id
                or raw_coordinate.model_dump(mode="json")
                != reference_raw_coordinate.model_dump(mode="json")
                or len(raw_evidence_candidates) != 1
            ):
                raise ValueError("selected vector raw table evidence differs")
            raw_evidence = raw_evidence_candidates[0]
            reference_raw_evidence = reference_evidence_by_id.get(raw_evidence.id)
            if (
                reference_raw_evidence is None
                or raw_evidence.model_dump(mode="json")
                != reference_raw_evidence.model_dump(mode="json")
                or raw_evidence.element_id != element.id
                or raw_evidence.bbox_id != raw_bbox.id
                or raw_evidence.value is not None
                or raw_evidence.confidence.model_dump(mode="json")
                != {
                    "scope": "evidence",
                    "score": None,
                    "unavailable_reason": "not_reported_by_source",
                }
                or raw_evidence.metadata
                != {
                    "raw_ref": raw_ref,
                    "raw_label": "table",
                    "provenance_index": 0,
                }
            ):
                raise ValueError("selected vector raw table evidence differs")

            incident = {
                relationship.id: relationship
                for relationship in internal_ir.relationships
                if element.id in {relationship.source_id, relationship.target_id}
            }
            reference_incident = {
                relationship.id: relationship
                for relationship in raw_reference_context["ir"].relationships
                if reference_element.id
                in {relationship.source_id, relationship.target_id}
            }
            if (
                set(incident) != set(reference_incident)
                or any(
                    incident[identifier].model_dump(mode="json")
                    != reference_incident[identifier].model_dump(mode="json")
                    for identifier in incident
                )
            ):
                raise ValueError("selected vector raw relationship differs")
            raw_relationships = [
                relationship
                for relationship in incident.values()
                if relationship.metadata != {"basis": "legacy_reading_order"}
            ]
            if len(raw_relationships) != 1:
                raise ValueError("selected vector raw relationship differs")
            raw_relationship = raw_relationships[0]
            expected_relationship_metadata = {
                "field": "body.children.reading_order",
                "source_ref": raw_ref,
                "target_ref": target_ref,
                "normalization_origin": "docling_reference_graph",
                "reference_metadata": [
                    {
                        "root_container": root_ref,
                        "source_child_index": child_index,
                        "target_child_index": child_index + 1,
                    }
                ],
            }
            expected_merged_relationship_metadata = {
                "basis": "legacy_reading_order",
                "reference_metadata": expected_relationship_metadata[
                    "reference_metadata"
                ],
            }
            if (
                str(raw_relationship.type.value) != "reading_before"
                or raw_relationship.source_id != element.id
                or (
                    raw_relationship.metadata != expected_relationship_metadata
                    and raw_relationship.metadata
                    != expected_merged_relationship_metadata
                )
            ):
                raise ValueError("selected vector raw relationship differs")
            target = ir_elements_by_id.get(raw_relationship.target_id)
            reference_target = reference_elements_by_id.get(
                raw_relationship.target_id
            )
            running_projection_keys = {
                "schema_version",
                "policy_id",
                "descriptor_id",
                "source_method",
                "predecessor_item_sha256",
                "descriptor_stable_sha256",
                "predecessor_stable_sha256",
            }
            if prior_running_projection is not None and (
                type(prior_running_projection) is not dict
                or set(prior_running_projection) != running_projection_keys
                or prior_running_projection.get("schema_version") != "1.0"
                or prior_running_projection.get("policy_id")
                != "p02-selected-vector-running-target-v1"
                or type(prior_running_projection.get("descriptor_id")) is not str
                or not prior_running_projection["descriptor_id"]
                or type(prior_running_projection.get("source_method")) is not str
                or not prior_running_projection["source_method"]
                or prior_running_projection["source_method"]
                == "extracted_source_contribution"
                or any(
                    re.fullmatch(r"[0-9a-f]{64}", value or "") is None
                    for value in (
                        prior_running_projection.get("predecessor_item_sha256"),
                        prior_running_projection.get("descriptor_stable_sha256"),
                        prior_running_projection.get("predecessor_stable_sha256"),
                    )
                )
            ):
                raise ValueError("selected vector prior running target differs")
            target_running_projection: dict[str, Any] | None = (
                deepcopy(prior_running_projection)
                if prior_running_projection is not None
                else None
            )
            if (
                target is None
                or reference_target is None
                or target.properties.get("raw_refs") != [target_ref]
                or target.properties.get("raw_label") != target_raw.get("label")
                or target.properties.get("root_containers")
                != [
                    {
                        "name": "body",
                        "ref": root_ref,
                        "child_index": child_index + 1,
                    }
                ]
                or raw_relationship.evidence_ids != target.evidence_ids
            ):
                raise ValueError("selected vector raw target custody differs")
            target_dump = target.model_dump(mode="json")
            reference_target_dump = reference_target.model_dump(mode="json")
            if target.running_region is None and reference_target.running_region is None:
                if target_dump != reference_target_dump:
                    raise ValueError("selected vector raw target custody differs")
            else:
                from app.services.running_regions import (
                    POLICY_ID as RUNNING_REGION_POLICY_ID,
                    _compact_public_item_payload,
                    _sha256_json,
                )

                descriptor = target.running_region
                reference_descriptor = reference_target.running_region
                target_legacy = target.properties.get("legacy_item")
                reference_legacy = reference_target.properties.get("legacy_item")
                descriptor_payload = (
                    descriptor.model_dump(mode="json")
                    if descriptor is not None
                    else None
                )
                page_items = pages_by_index[page_index].get("items")
                target_legacy_id = (
                    target_legacy.get("id")
                    if type(target_legacy) is dict
                    else None
                )
                public_matches = [
                    (position, item)
                    for position, item in enumerate(page_items or [])
                    if type(item) is dict and item.get("id") == target_legacy_id
                ]
                reference_sidecars = (
                    set(reference_legacy).intersection(
                        _TERMINAL_RUNNING_REGION_SIDECAR_KEYS
                    )
                    if type(reference_legacy) is dict
                    else set()
                )
                if (
                    descriptor is None
                    or reference_descriptor != descriptor
                    or type(descriptor_payload) is not dict
                    or descriptor.source_method == "extracted_source_contribution"
                    or type(target_legacy) is not dict
                    or type(reference_legacy) is not dict
                    or set(target_legacy).intersection(
                        _TERMINAL_RUNNING_REGION_SIDECAR_KEYS
                    )
                    or reference_sidecars
                    != set(_TERMINAL_RUNNING_REGION_SIDECAR_KEYS)
                    or len(public_matches) != 1
                    or public_matches[0][1] != reference_legacy
                    or reference_legacy.get("layout_running_region_projected")
                    is not True
                    or reference_legacy.get("running_region_policy")
                    != RUNNING_REGION_POLICY_ID
                    or reference_legacy.get("running_region")
                    != descriptor_payload
                    or reference_legacy.get("type") != descriptor.role
                    or target_legacy.get("type") != descriptor.predecessor_type
                    or descriptor.source_public_item_id != target_legacy_id
                    or descriptor.source_element_id != target.id
                    or descriptor.page_id != target.page_id
                    or descriptor.physical_page_index != page_index
                    or descriptor.source_public_path
                    != ["pages", page_index - 1, "items", public_matches[0][0]]
                    or target.reading_order != public_matches[0][0]
                    or target.properties.get("source_position")
                    != public_matches[0][0]
                    or target_legacy.get("reading_order")
                    != public_matches[0][0]
                    or reference_legacy.get("reading_order")
                    != public_matches[0][0]
                    or type(descriptor.predecessor_item_sha256) is not str
                    or len(descriptor.predecessor_item_sha256) != 64
                    or any(
                        value not in "0123456789abcdef"
                        for value in descriptor.predecessor_item_sha256
                    )
                ):
                    raise ValueError(
                        "selected vector raw running target differs"
                    )
                normalized_reference_legacy = deepcopy(reference_legacy)
                for key in _TERMINAL_RUNNING_REGION_SIDECAR_KEYS:
                    normalized_reference_legacy.pop(key)
                normalized_reference_legacy["type"] = descriptor.predecessor_type
                normalized_reference_target = deepcopy(reference_target_dump)
                normalized_reference_target["properties"]["legacy_item"] = (
                    normalized_reference_legacy
                )
                if (
                    normalized_reference_legacy != target_legacy
                    or normalized_reference_target != target_dump
                ):
                    raise ValueError(
                        "selected vector raw running target custody differs"
                    )
                current_predecessor_sha256 = _sha256_json(
                    _compact_public_item_payload(normalized_reference_legacy)
                )
                if (
                    descriptor.predecessor_item_sha256
                    != current_predecessor_sha256
                ):
                    raise ValueError(
                        "selected vector raw running predecessor differs"
                    )
                stable_descriptor = deepcopy(descriptor_payload)
                stable_descriptor.pop("source_public_path")
                projection_predecessor_sha256 = current_predecessor_sha256
                if prior_running_projection is not None:
                    projection_predecessor_sha256 = prior_running_projection[
                        "predecessor_item_sha256"
                    ]
                    stable_descriptor["predecessor_item_sha256"] = (
                        projection_predecessor_sha256
                    )
                stable_predecessor = deepcopy(target_legacy)
                stable_predecessor.pop("reading_order")
                observed_running_projection = {
                    "schema_version": "1.0",
                    "policy_id": "p02-selected-vector-running-target-v1",
                    "descriptor_id": descriptor.id,
                    "source_method": descriptor.source_method,
                    "predecessor_item_sha256": projection_predecessor_sha256,
                    "descriptor_stable_sha256": (
                        _selected_vector_terminal_sha256(stable_descriptor)
                    ),
                    "predecessor_stable_sha256": (
                        _selected_vector_terminal_sha256(stable_predecessor)
                    ),
                }
                if (
                    prior_running_projection is not None
                    and prior_running_projection != observed_running_projection
                ):
                    raise ValueError(
                        "selected vector raw running predecessor differs"
                    )
                target_running_projection = observed_running_projection
            target_incident = {
                relationship.id: relationship
                for relationship in internal_ir.relationships
                if target.id
                in {relationship.source_id, relationship.target_id}
            }
            reference_target_incident = {
                relationship.id: relationship
                for relationship in raw_reference_context["ir"].relationships
                if reference_target.id
                in {relationship.source_id, relationship.target_id}
            }
            if (
                set(target_incident) != set(reference_target_incident)
                or any(
                    target_incident[identifier].model_dump(mode="json")
                    != reference_target_incident[identifier].model_dump(
                        mode="json"
                    )
                    for identifier in target_incident
                )
            ):
                raise ValueError("selected vector raw target relationship differs")
            target_bboxes = [
                bboxes_by_id.get(identifier) for identifier in target.bbox_ids
            ]
            target_evidence = [
                evidence_by_id.get(identifier) for identifier in target.evidence_ids
            ]
            closure_bboxes = [
                bboxes_by_id.get(identifier) for identifier in element.bbox_ids
            ] + target_bboxes
            closure_coordinates_by_id = {
                value.coordinate_system_id: coordinates_by_id.get(
                    value.coordinate_system_id
                )
                for value in closure_bboxes
                if value is not None
            }
            if (
                not target_bboxes
                or not target_evidence
                or any(value is None for value in (*target_bboxes, *target_evidence))
                or any(
                    value.model_dump(mode="json")
                    != reference_bboxes_by_id[value.id].model_dump(mode="json")
                    for value in target_bboxes
                    if value.id in reference_bboxes_by_id
                )
                or any(
                    value.id not in reference_bboxes_by_id for value in target_bboxes
                )
                or any(
                    value.model_dump(mode="json")
                    != reference_evidence_by_id[value.id].model_dump(mode="json")
                    for value in target_evidence
                    if value.id in reference_evidence_by_id
                )
                or any(
                    value.id not in reference_evidence_by_id
                    for value in target_evidence
                )
                or any(
                    set(relationship.evidence_ids).intersection(
                        set(element.evidence_ids) | set(target.evidence_ids)
                    )
                    and relationship.id != raw_relationship.id
                    for relationship in internal_ir.relationships
                )
                or any(
                    coordinate is None
                    or coordinate.page_id != element.page_id
                    or coordinate_id not in reference_coordinates_by_id
                    or coordinate.model_dump(mode="json")
                    != reference_coordinates_by_id[coordinate_id].model_dump(
                        mode="json"
                    )
                    for coordinate_id, coordinate in closure_coordinates_by_id.items()
                )
            ):
                raise ValueError("selected vector raw target evidence differs")
            custody_ids = {
                element.id,
                target.id,
                raw_bbox.id,
                raw_evidence.id,
                raw_relationship.id,
                *target.bbox_ids,
                *target.evidence_ids,
                *closure_coordinates_by_id,
            }
            custody_refs = {raw_ref, target_ref}
            if any(
                concern.source_ref in custody_ids | custody_refs
                or concern.target_ref in custody_ids | custody_refs
                for concern in internal_ir.concerns
            ):
                raise ValueError("selected vector raw concern differs")
            target_raw_properties = {
                key: deepcopy(target.properties[key])
                for key in (
                    "raw_refs",
                    "raw_label",
                    "raw_metadata",
                    "root_containers",
                )
                if key in target.properties
            }
            custody = {
                "schema_version": "1.0",
                "policy_id": "p02-selected-vector-raw-provenance-v1",
                "source_sha256": source_sha256,
                "page_index": page_index,
                "raw_graph_sha256": raw_reference_context[
                    "raw_graph_sha256"
                ],
                "table_raw_ref": raw_ref,
                "table_raw_node_sha256": _selected_vector_terminal_sha256(
                    raw_table
                ),
                "table_raw_properties": {
                    key: deepcopy(element.properties[key])
                    for key in (
                        "raw_refs",
                        "raw_label",
                        "raw_metadata",
                        "root_containers",
                    )
                },
                "table_raw_bbox": raw_bbox.model_dump(mode="json"),
                "table_raw_coordinate": raw_coordinate.model_dump(mode="json"),
                "table_raw_evidence": raw_evidence.model_dump(mode="json"),
                # The builder may merge this raw edge with the identical
                # legacy-reading pair after public deletions.  Both concrete
                # forms were compared byte-for-byte with the freshly rebuilt
                # reference IR above; seal the invariant source-grounded edge
                # without its representation-dependent relationship id/basis.
                "raw_relationship": {
                    "type": "reading_before",
                    "source_id": raw_relationship.source_id,
                    "target_id": raw_relationship.target_id,
                    "evidence_ids": list(raw_relationship.evidence_ids),
                    "metadata": expected_relationship_metadata,
                },
                "target_raw_ref": target_ref,
                "target_raw_node_sha256": _selected_vector_terminal_sha256(
                    target_raw
                ),
                "target_element_id": target.id,
                "target_page_id": target.page_id,
                "target_type": target.type,
                "target_value": deepcopy(target.value),
                "target_markdown": target.markdown,
                "target_raw_properties": target_raw_properties,
                "target_running_projection": target_running_projection,
                "target_bboxes": [
                    value.model_dump(mode="json") for value in target_bboxes
                ],
                "target_evidence": [
                    value.model_dump(mode="json") for value in target_evidence
                ],
                "target_coordinates": [
                    closure_coordinates_by_id[identifier].model_dump(mode="json")
                    for identifier in sorted(closure_coordinates_by_id)
                ],
            }
            custody["custody_sha256"] = _selected_vector_terminal_sha256(
                custody
            )
            return custody

        output: dict[int, list[dict[str, Any]]] = {}
        table_count = 0
        slot_count = 0
        for page_index, page_records in tuple(representations.items()):
            page = pages_by_index.get(page_index)
            canonical_page = canonical_by_index.get(page_index)
            ir_page = ir_pages_by_index.get(page_index)
            if (
                type(page_index) is not int
                or page_index < 1
                or type(page_records) is not list
                or len(page_records) > 128
                or type(page) is not dict
                or type(canonical_page) is not dict
                or ir_page is None
            ):
                return {}
            page_width = page.get("page_width")
            page_height = page.get("page_height")
            items = page.get("items")
            blocks = canonical_page.get("blocks")
            if (
                type(page_width) not in (int, float)
                or type(page_width) is bool
                or not math.isfinite(float(page_width))
                or float(page_width) <= 0
                or type(page_height) not in (int, float)
                or type(page_height) is bool
                or not math.isfinite(float(page_height))
                or float(page_height) <= 0
                or type(items) is not list
                or type(blocks) is not list
            ):
                return {}
            page_tables = [
                (position, item)
                for position, item in enumerate(items)
                if type(item) is dict and item.get("type") == "table"
            ]
            page_tables_by_candidate: dict[
                str, list[tuple[int, int, Mapping[str, Any]]]
            ] = defaultdict(list)
            for table_ordinal, (item_position, table) in enumerate(page_tables):
                reconciliation = table.get("table_reconciliation")
                candidate_id = (
                    reconciliation.get("selected_candidate_id")
                    if type(reconciliation) is dict
                    else None
                )
                if type(candidate_id) is str and candidate_id:
                    page_tables_by_candidate[candidate_id].append(
                        (table_ordinal, item_position, table)
                    )
            bound_page = []
            consumed_item_positions: set[int] = set()
            seen_representation_keys: set[tuple[int, str]] = set()
            for representation in page_records:
                check_deadline()
                if type(representation) is not dict:
                    return {}
                base_representation = deepcopy(representation)
                base_representation.pop("terminal_binding", None)
                base_representation.pop("terminal_authority_sha256", None)
                representation_key = (
                    representation.get("output_position"),
                    representation.get("candidate_id"),
                )
                if (
                    type(representation_key[0]) is not int
                    or type(representation_key[1]) is not str
                    or representation_key in seen_representation_keys
                ):
                    return {}
                seen_representation_keys.add(representation_key)
                matches = []
                for table_ordinal, item_position, table in (
                    page_tables_by_candidate.get(representation_key[1], ())
                ):
                    comparisons += 1
                    if comparisons > 16_384:
                        raise ValueError(
                            "selected vector terminal comparison limit"
                        )
                    check_deadline()
                    admitted = admit_selected_vector_representation(
                        base_representation,
                        table,
                        source_sha256,
                        page_width,
                        page_height,
                        deadline=deadline,
                    )
                    if admitted is not None:
                        matches.append(
                            (table_ordinal, item_position, table, admitted)
                        )
                if len(matches) != 1:
                    return {}
                table_ordinal, item_position, table, admitted = matches[0]
                if (
                    item_position in consumed_item_positions
                    or table_ordinal != representation.get("output_position")
                ):
                    return {}
                consumed_item_positions.add(item_position)
                public_id = table.get("id")
                element_matches = elements_by_legacy_id.get(public_id, [])
                if len(element_matches) != 1:
                    return {}
                element = element_matches[0]
                legacy = element.properties.get("legacy_item")
                element_bbox_ids = element.bbox_ids
                element_evidence_ids = element.evidence_ids
                element_bbox = (
                    bboxes_by_id.get(element_bbox_ids[0])
                    if element_bbox_ids
                    else None
                )
                element_evidence = [
                    evidence_by_id.get(identifier)
                    for identifier in element_evidence_ids
                ]
                raw_custody = raw_provenance_custody(
                    element,
                    public_id=public_id,
                    page_index=page_index,
                    prior_running_projection=(
                        (
                            (
                                representation.get("terminal_binding") or {}
                            ).get("ir_raw_provenance")
                            or {}
                        ).get("target_running_projection")
                        if type(representation.get("terminal_binding")) is dict
                        else None
                    ),
                )
                primary_element_evidence = [
                    value
                    for value in element_evidence
                    if value is not None
                    and str(value.method.value) in {"native", "vector"}
                ]
                table_bbox = table.get("bbox")
                expected_evidence_value = table.get("rows")
                element_properties = element.properties
                element_coordinate = next(
                    (
                        coordinate
                        for coordinate in internal_ir.coordinate_systems
                        if coordinate.id == element_bbox.coordinate_system_id
                    ),
                    None,
                ) if element_bbox is not None else None
                incident_relationships = [
                    relationship
                    for relationship in internal_ir.relationships
                    if element.id
                    in {relationship.source_id, relationship.target_id}
                ]
                if (
                    type(legacy) is not dict
                    or legacy != table
                    or element.type != "table"
                    or element.value != table.get("value")
                    or element.markdown != table.get("md")
                    or element.reading_order != table.get("reading_order")
                    or element.presentation_role != "primary"
                    or element.presentation.accepted is not True
                    or element.presentation.include_subordinate_ocr is not None
                    or element.text_run_ids != []
                    or element.form_semantics is not None
                    or element.outline_group is not None
                    or element.outline_item is not None
                    or element.running_region is not None
                    or element.visual_model_evidence is not None
                    or frozenset(element_properties)
                    not in {
                        frozenset(base_element_property_keys),
                        frozenset(raw_table_property_keys),
                    }
                    or element_properties.get("generated") is not False
                    or element_properties.get("region_role") is not None
                    or element_properties.get("content_type") is not None
                    or element_properties.get("source_position") != item_position
                    or element.page_id != ir_page.id
                    or ir_page.element_ids.count(element.id) != 1
                    or ir_page.presentation_element_ids.count(element.id) != 1
                    or len(element_bbox_ids) != (2 if raw_custody else 1)
                    or element_bbox is None
                    or element_bbox.role != "element"
                    or element_coordinate is None
                    or element_coordinate.page_id != ir_page.id
                    or element_coordinate.id != ir_page.coordinate_system_id
                    or type(table_bbox) is not dict
                    or any(
                        abs(float(observed) - float(expected)) > 0.000001
                        for observed, expected in (
                            (element_bbox.x, table_bbox.get("x")),
                            (element_bbox.y, table_bbox.get("y")),
                            (element_bbox.width, table_bbox.get("width")),
                            (element_bbox.height, table_bbox.get("height")),
                        )
                    )
                    or len(element_evidence) != (3 if raw_custody else 2)
                    or any(value is None for value in element_evidence)
                    or {
                        str(value.method.value) for value in primary_element_evidence
                    }
                    != {"native", "vector"}
                    or len(primary_element_evidence) != 2
                    or any(
                        value.element_id != element.id
                        or value.bbox_id != element_bbox.id
                        or value.value != expected_evidence_value
                        or value.confidence.model_dump(mode="json")
                        != {
                            "scope": "evidence",
                            "score": None,
                            "unavailable_reason": "not_reported_by_source",
                        }
                        or value.metadata
                        != {
                            "source": "native",
                            "engine": "pdfplumber",
                        }
                        for value in primary_element_evidence
                    )
                    or (
                        raw_custody is None
                        and any(
                            str(relationship.type.value) != "reading_before"
                            or relationship.evidence_ids != []
                            or relationship.metadata
                            != {"basis": "legacy_reading_order"}
                            for relationship in incident_relationships
                        )
                    )
                    or any(
                        concern.source_ref
                        in {
                            element.id,
                            element_bbox.id,
                            *element_evidence_ids,
                        }
                        or concern.target_ref
                        in {
                            element.id,
                            element_bbox.id,
                            *element_evidence_ids,
                        }
                        for concern in internal_ir.concerns
                    )
                ):
                    return {}
                owning_regions = [
                    region
                    for region in internal_ir.regions
                    if element.id in region.element_ids
                ]
                if (
                    len(owning_regions) != 1
                    or owning_regions[0].page_id != ir_page.id
                    or owning_regions[0].role != "page"
                    or owning_regions[0].element_ids.count(element.id) != 1
                ):
                    return {}
                block_matches = [
                    (position, block)
                    for position, block in enumerate(blocks)
                    if type(block) is dict
                    and block.get("primary_element_id") == element.id
                ]
                if len(block_matches) != 1:
                    return {}
                block_position, block = block_matches[0]
                contributors = block.get("contributing_element_ids")
                full_ids = (canonical_page.get("full") or {}).get("block_ids")
                body_ids = (canonical_page.get("body") or {}).get("block_ids")
                header_ids = (canonical_page.get("header") or {}).get("block_ids")
                footer_ids = (canonical_page.get("footer") or {}).get("block_ids")
                rows = table.get("value")
                canonical_table_text = (
                    "\n".join(
                        "\t".join(str(cell or "").strip() for cell in row).rstrip()
                        for row in rows
                    ).strip()
                    if type(rows) is list
                    and all(type(row) is list for row in rows)
                    else None
                )
                if (
                    canonical_page.get("page_id") != ir_page.id
                    or block.get("page_id") != ir_page.id
                    or block.get("primary_element_type") != "table"
                    or block.get("scope") != "body"
                    or block.get("omission_reason") is not None
                    or contributors != [element.id]
                    or block.get("relationship_ids") != []
                    or block.get("excluded_contributions") != []
                    or block.get("markdown") != table.get("md")
                    or block.get("text") != canonical_table_text
                    or any(type(values) is not list for values in (
                        full_ids,
                        body_ids,
                        header_ids,
                        footer_ids,
                    ))
                    or full_ids.count(block.get("id")) != 1
                    or body_ids.count(block.get("id")) != 1
                    or block.get("id") in header_ids
                    or block.get("id") in footer_ids
                ):
                    return {}
                binding = {
                    "schema_version": "1.0",
                    "policy_id": "p02-selected-vector-terminal-binding-v1",
                    "source_sha256": source_sha256,
                    "page_index": page_index,
                    "public_item_position": item_position,
                    "public_table_ordinal": table_ordinal,
                    "public_table_id": public_id,
                    "public_table_sha256": _selected_vector_terminal_sha256(
                        table
                    ),
                    "ir_page_id": ir_page.id,
                    "ir_element_id": element.id,
                    "ir_legacy_item_sha256": _selected_vector_terminal_sha256(
                        legacy
                    ),
                    "ir_element_sha256": _selected_vector_terminal_sha256(
                        element.model_dump(mode="json")
                    ),
                    "ir_bbox_sha256": _selected_vector_terminal_sha256(
                        element_bbox.model_dump(mode="json")
                    ),
                    "ir_evidence_sha256": _selected_vector_terminal_sha256(
                        [value.model_dump(mode="json") for value in element_evidence]
                    ),
                    "ir_coordinate_sha256": _selected_vector_terminal_sha256(
                        element_coordinate.model_dump(mode="json")
                    ),
                    "ir_region_id": owning_regions[0].id,
                    "ir_region_bbox_id": owning_regions[0].bbox_id,
                    "canonical_page_id": canonical_page.get("page_id"),
                    "canonical_block_position": block_position,
                    "canonical_block_id": block.get("id"),
                    "canonical_block_sha256": _selected_vector_terminal_sha256(
                        block
                    ),
                    "canonical_markdown_sha256": hashlib.sha256(
                        block["markdown"].encode("utf-8")
                    ).hexdigest(),
                    "canonical_text_sha256": hashlib.sha256(
                        block["text"].encode("utf-8")
                    ).hexdigest(),
                    **(
                        {"ir_raw_provenance": raw_custody}
                        if raw_custody is not None
                        else {}
                    ),
                }
                bound = {
                    **base_representation,
                    "terminal_binding": binding,
                }
                bound["terminal_authority_sha256"] = (
                    _selected_vector_terminal_sha256(
                        [
                            "p02-selected-vector-terminal-binding-v1",
                            base_representation,
                            binding,
                        ]
                    )
                )
                if admit_selected_vector_representation(
                    bound,
                    table,
                    source_sha256,
                    page_width,
                    page_height,
                    deadline=deadline,
                ) is None:
                    return {}
                table_count += 1
                slot_count += len(bound["rows"]) * len(bound["rows"][0])
                if table_count > 128 or slot_count > 10_000:
                    return {}
                bound_page.append(bound)
            if bound_page:
                output[page_index] = bound_page
        _selected_vector_terminal_sha256(
            [[page_index, output[page_index]] for page_index in sorted(output)]
        )
        return output
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        TimeoutError,
        TypeError,
        UnicodeError,
        ValueError,
        AttributeError,
    ):
        return {}


def _validate_selected_vector_ir_transition(
    baseline_ir: Any,
    terminal_ir: Any,
    selections: Sequence[Mapping[str, Any]],
    terminal_payload: Mapping[str, Any],
) -> None:
    """Prove that vector suppression removed only closed OCR owner records."""

    from app.services.ir import DocumentIR

    deadline = time.perf_counter() + 2.0

    def check_deadline() -> None:
        if time.perf_counter() > deadline:
            raise TimeoutError("selected-vector IR transition deadline")

    if (
        type(baseline_ir) is not DocumentIR
        or type(terminal_ir) is not DocumentIR
        or not selections
        or isinstance(selections, (str, bytes, bytearray))
        or len(selections) > 2_048
        or not isinstance(terminal_payload, Mapping)
        or baseline_ir.id != terminal_ir.id
        or baseline_ir.source_sha256 != terminal_ir.source_sha256
    ):
        raise ValueError("selected-vector IR transition differs")

    bounded_collections = (
        baseline_ir.coordinate_systems,
        terminal_ir.coordinate_systems,
        baseline_ir.pages,
        terminal_ir.pages,
        baseline_ir.regions,
        terminal_ir.regions,
        baseline_ir.elements,
        terminal_ir.elements,
        baseline_ir.bboxes,
        terminal_ir.bboxes,
        baseline_ir.evidence,
        terminal_ir.evidence,
        baseline_ir.text_rules,
        terminal_ir.text_rules,
        baseline_ir.text_runs,
        terminal_ir.text_runs,
        baseline_ir.relationships,
        terminal_ir.relationships,
        baseline_ir.concerns,
        terminal_ir.concerns,
    )
    if any(len(records) > 100_000 for records in bounded_collections) or sum(
        len(records) for records in bounded_collections
    ) > 500_000:
        raise ValueError("selected-vector IR transition exceeds record limits")

    def records_by_id(records: Sequence[Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for index, record in enumerate(records):
            if index % 256 == 0:
                check_deadline()
            identifier = record.id
            if (
                type(identifier) is not str
                or not identifier
                or identifier in output
            ):
                raise ValueError("selected-vector IR identity differs")
            output[identifier] = record
        return output

    baseline_elements = records_by_id(baseline_ir.elements)
    terminal_elements = records_by_id(terminal_ir.elements)
    baseline_bboxes = records_by_id(baseline_ir.bboxes)
    terminal_bboxes = records_by_id(terminal_ir.bboxes)
    baseline_evidence = records_by_id(baseline_ir.evidence)
    terminal_evidence = records_by_id(terminal_ir.evidence)
    baseline_pages = records_by_id(baseline_ir.pages)
    terminal_pages = records_by_id(terminal_ir.pages)
    baseline_regions = records_by_id(baseline_ir.regions)
    terminal_regions = records_by_id(terminal_ir.regions)
    baseline_relationships = records_by_id(baseline_ir.relationships)
    terminal_relationships = records_by_id(terminal_ir.relationships)
    baseline_coordinates = records_by_id(baseline_ir.coordinate_systems)

    baseline_elements_by_legacy_id: dict[str, list[Any]] = defaultdict(list)
    for index, element in enumerate(baseline_ir.elements):
        if index % 256 == 0:
            check_deadline()
        legacy = element.properties.get("legacy_item")
        legacy_id = legacy.get("id") if isinstance(legacy, Mapping) else None
        if isinstance(legacy_id, str) and legacy_id:
            baseline_elements_by_legacy_id[legacy_id].append(element)

    terminal_public_positions: dict[str, tuple[int, int, Mapping[str, Any]]] = {}
    raw_terminal_pages = terminal_payload.get("pages")
    if not isinstance(raw_terminal_pages, list) or len(raw_terminal_pages) > 100:
        raise ValueError("selected-vector terminal public pages differ")
    for page_offset, public_page in enumerate(raw_terminal_pages):
        check_deadline()
        if not isinstance(public_page, Mapping):
            raise ValueError("selected-vector terminal public page differs")
        page_index = public_page.get("page_index")
        items = public_page.get("items")
        if (
            type(page_index) is not int
            or page_index < 1
            or not isinstance(items, list)
            or len(items) > 100_000
        ):
            raise ValueError("selected-vector terminal public page differs")
        for item_position, item in enumerate(items):
            if item_position % 256 == 0:
                check_deadline()
            public_id = item.get("id") if isinstance(item, Mapping) else None
            if (
                not isinstance(public_id, str)
                or not public_id
                or public_id in terminal_public_positions
            ):
                raise ValueError("selected-vector terminal public item differs")
            terminal_public_positions[public_id] = (
                page_index,
                item_position,
                item,
            )

    selected_element_ids: set[str] = set()
    selected_bbox_ids: set[str] = set()
    selected_evidence_ids: set[str] = set()
    selected_by_page: dict[str, set[str]] = defaultdict(set)
    selected_by_region: dict[str, set[str]] = defaultdict(set)
    seen_public_ids: set[str] = set()
    for selection_index, selection in enumerate(selections):
        if selection_index % 64 == 0:
            check_deadline()
        rejected = selection.get("rejected_ocr_alternative")
        snapshot = rejected.get("owner_snapshot") if isinstance(rejected, Mapping) else None
        canonical_owner = (
            rejected.get("canonical_owner")
            if isinstance(rejected, Mapping)
            else None
        )
        public_id = selection.get("owner_id")
        if (
            not isinstance(snapshot, Mapping)
            or snapshot.get("id") != public_id
            or not isinstance(public_id, str)
            or public_id in seen_public_ids
            or not isinstance(canonical_owner, Mapping)
        ):
            raise ValueError("selected-vector IR owner differs")
        seen_public_ids.add(public_id)
        matches = baseline_elements_by_legacy_id.get(public_id, [])
        if len(matches) != 1:
            raise ValueError("selected-vector IR owner binding differs")
        element = matches[0]
        legacy = element.properties.get("legacy_item")
        if (
            dict(legacy) != dict(snapshot)
            or element.type != snapshot.get("type")
            or element.value != snapshot.get("value")
            or element.markdown != snapshot.get("md")
            or element.reading_order != snapshot.get("reading_order")
            or element.presentation_role != "primary"
            or element.presentation.accepted is not True
            or element.presentation.include_subordinate_ocr is not None
            or element.text_run_ids != []
            or element.form_semantics is not None
            or element.outline_group is not None
            or element.outline_item is not None
            or element.running_region is not None
            or element.visual_model_evidence is not None
            or set(element.properties)
            != {
                "legacy_item",
                "generated",
                "region_role",
                "content_type",
                "source_position",
            }
            or element.properties.get("generated") is not False
            or element.properties.get("region_role") is not None
            or element.properties.get("content_type") is not None
            or type(element.properties.get("source_position")) is not int
            or element.properties.get("source_position")
            != canonical_owner.get("owner_item_position")
            or len(element.bbox_ids) != 1
            or len(element.evidence_ids) != 1
        ):
            raise ValueError("selected-vector IR owner custody differs")
        bbox = baseline_bboxes.get(element.bbox_ids[0])
        evidence = baseline_evidence.get(element.evidence_ids[0])
        source_box = snapshot.get("bbox")
        coordinate = (
            baseline_coordinates.get(bbox.coordinate_system_id)
            if bbox is not None
            else None
        )
        if (
            bbox is None
            or bbox.role != "element"
            or coordinate is None
            or coordinate.page_id != element.page_id
            or coordinate.unit != "pt"
            or not isinstance(source_box, Mapping)
            or source_box.get("unit") != "pt"
            or any(
                abs(float(observed) - float(expected)) > 0.000001
                for observed, expected in (
                    (bbox.x, source_box.get("x")),
                    (bbox.y, source_box.get("y")),
                    (bbox.width, source_box.get("width")),
                    (bbox.height, source_box.get("height")),
                )
            )
            or evidence is None
            or str(evidence.method.value) != "ocr"
            or evidence.element_id != element.id
            or evidence.bbox_id != bbox.id
            or evidence.value != snapshot.get("raw_ocr_text")
            or evidence.confidence.model_dump(mode="json")
            != {
                "scope": "evidence",
                "score": float(snapshot["confidence"]),
                "unavailable_reason": None,
            }
            or evidence.metadata != {"source": "ocr", "engine": None}
        ):
            raise ValueError("selected-vector IR owner evidence differs")
        owning_pages = [
            page
            for page in baseline_ir.pages
            if page.element_ids.count(element.id) == 1
            and page.presentation_element_ids.count(element.id) == 1
        ]
        owning_regions = [
            region
            for region in baseline_ir.regions
            if region.element_ids.count(element.id) == 1
        ]
        if (
            len(owning_pages) != 1
            or len(owning_regions) != 1
            or owning_pages[0].id != element.page_id
            or owning_pages[0].page_index != selection.get("page_index")
            or owning_pages[0].page_index != canonical_owner.get("page_index")
            or owning_regions[0].page_id != element.page_id
            or owning_regions[0].role != "page"
        ):
            raise ValueError("selected-vector IR owner membership differs")
        selected_element_ids.add(element.id)
        selected_bbox_ids.add(bbox.id)
        selected_evidence_ids.add(evidence.id)
        selected_by_page[element.page_id].add(element.id)
        selected_by_region[owning_regions[0].id].add(element.id)

    selected_refs = selected_element_ids | selected_bbox_ids | selected_evidence_ids
    for relationship in baseline_ir.relationships:
        if relationship.source_id in selected_element_ids or relationship.target_id in selected_element_ids:
            if (
                str(relationship.type.value) != "reading_before"
                or relationship.evidence_ids != []
                or relationship.metadata != {"basis": "legacy_reading_order"}
            ):
                raise ValueError("selected-vector IR semantic relationship differs")
    if any(
        concern.source_ref in selected_refs or concern.target_ref in selected_refs
        for concern in baseline_ir.concerns
    ):
        raise ValueError("selected-vector IR concern reference differs")
    if any(
        set(relationship.evidence_ids).intersection(selected_evidence_ids)
        for relationship in baseline_ir.relationships
    ):
        raise ValueError("selected-vector IR relationship evidence differs")
    if any(
        identifier in selected_refs
        for record in (*baseline_ir.text_rules, *baseline_ir.text_runs)
        for identifier in json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
        ).split('"')
    ):
        raise ValueError("selected-vector IR text reference differs")

    def exact_survivors(
        baseline: Mapping[str, Any],
        terminal: Mapping[str, Any],
        removed: set[str],
    ) -> bool:
        if set(terminal) != set(baseline) - removed:
            return False
        return all(
            terminal[identifier].model_dump(mode="json")
            == record.model_dump(mode="json")
            for identifier, record in baseline.items()
            if identifier not in removed
        )

    def exact_surviving_elements() -> bool:
        if set(terminal_elements) != set(baseline_elements) - selected_element_ids:
            return False
        terminal_pages_by_id = {
            page.id: page for page in terminal_ir.pages
        }
        for index, (identifier, baseline_element) in enumerate(
            baseline_elements.items()
        ):
            if index % 128 == 0:
                check_deadline()
            if identifier in selected_element_ids:
                continue
            terminal_element = terminal_elements.get(identifier)
            if terminal_element is None:
                return False
            baseline_dump = baseline_element.model_dump(mode="json")
            terminal_dump = terminal_element.model_dump(mode="json")
            baseline_properties = baseline_dump.get("properties")
            terminal_properties = terminal_dump.get("properties")
            if not isinstance(baseline_properties, dict) or not isinstance(
                terminal_properties, dict
            ):
                return False
            terminal_source_position = terminal_properties.get("source_position")
            terminal_reading_order = terminal_dump.get("reading_order")
            legacy = terminal_properties.get("legacy_item")
            legacy_id = legacy.get("id") if isinstance(legacy, Mapping) else None
            legacy_reading_order = (
                legacy.get("reading_order") if isinstance(legacy, Mapping) else None
            )
            if not isinstance(legacy_id, str) or not legacy_id:
                # Subordinate/generated IR-only elements are not public list
                # members and therefore do not participate in positional
                # compaction.  Their full records remain byte-exact.
                if terminal_dump != baseline_dump:
                    return False
                continue
            public_record = terminal_public_positions.get(legacy_id)
            owning_page = terminal_pages_by_id.get(terminal_element.page_id)
            if (
                type(terminal_source_position) is not int
                or public_record is None
                or owning_page is None
                or public_record[0] != owning_page.page_index
                or public_record[1] != terminal_source_position
                or type(terminal_reading_order) is not int
                or terminal_reading_order != public_record[1]
                or type(legacy_reading_order) is not int
                or legacy_reading_order != public_record[1]
                or dict(public_record[2]) != dict(legacy)
            ):
                return False
            # Re-entry deterministically compacts only these internal
            # positional fields after selected public owners are removed.  The
            # public/legacy reading order must equal the exact terminal item
            # position before normalization; no other survivor field may
            # change.
            terminal_properties["source_position"] = baseline_properties.get(
                "source_position"
            )
            terminal_dump["reading_order"] = baseline_dump.get("reading_order")
            baseline_legacy = baseline_properties.get("legacy_item")
            if not isinstance(baseline_legacy, Mapping):
                return False
            terminal_properties["legacy_item"]["reading_order"] = (
                baseline_legacy.get("reading_order")
            )
            if terminal_dump != baseline_dump:
                return False
        return True

    def exact_or_resolved_concerns() -> bool:
        """Permit only an exactly proved anchor-cap concern resolution."""

        expected_terminal: list[dict[str, Any]] = []
        resolved_page_ids: set[str] = set()
        for index, concern in enumerate(baseline_ir.concerns):
            if index % 128 == 0:
                check_deadline()
            value = concern.model_dump(mode="json")
            metadata = value.get("metadata")
            is_anchor_limit = (
                set(value)
                == {"code", "message", "source_ref", "target_ref", "metadata"}
                and value.get("code") == "relationship_order_page_limit"
                and value.get("message")
                == "Relationship-aware reading order failed closed."
                and value.get("source_ref") is None
                and value.get("target_ref") is None
                and type(metadata) is dict
                and set(metadata) == {"page_id", "anchor_count", "limit"}
                and type(metadata.get("page_id")) is str
                and bool(metadata["page_id"])
                and type(metadata.get("anchor_count")) is int
                and type(metadata.get("limit")) is int
                and metadata["limit"] == 512
            )
            if not is_anchor_limit:
                expected_terminal.append(value)
                continue
            page_id = metadata["page_id"]
            baseline_page = baseline_pages.get(page_id)
            terminal_page = terminal_pages.get(page_id)
            baseline_anchor_count = metadata["anchor_count"]
            removed_count = len(selected_by_page.get(page_id, set()))
            if (
                page_id in resolved_page_ids
                or baseline_page is None
                or terminal_page is None
                or baseline_anchor_count
                != len(baseline_page.presentation_element_ids)
                or baseline_anchor_count <= metadata["limit"]
                or len(terminal_page.presentation_element_ids)
                != baseline_anchor_count - removed_count
                or len(terminal_page.presentation_element_ids) > metadata["limit"]
            ):
                expected_terminal.append(value)
                continue
            resolved_page_ids.add(page_id)
        return [
            value.model_dump(mode="json") for value in terminal_ir.concerns
        ] == expected_terminal

    if (
        not exact_surviving_elements()
        or not exact_survivors(baseline_bboxes, terminal_bboxes, selected_bbox_ids)
        or not exact_survivors(baseline_evidence, terminal_evidence, selected_evidence_ids)
        or [value.model_dump(mode="json") for value in baseline_ir.coordinate_systems]
        != [value.model_dump(mode="json") for value in terminal_ir.coordinate_systems]
        or [value.model_dump(mode="json") for value in baseline_ir.text_rules]
        != [value.model_dump(mode="json") for value in terminal_ir.text_rules]
        or [value.model_dump(mode="json") for value in baseline_ir.text_runs]
        != [value.model_dump(mode="json") for value in terminal_ir.text_runs]
        or not exact_or_resolved_concerns()
    ):
        raise ValueError("selected-vector IR surviving custody differs")
    if set(terminal_pages) != set(baseline_pages) or set(terminal_regions) != set(
        baseline_regions
    ):
        raise ValueError("selected-vector IR page/region identity differs")
    for page_id, baseline_page in baseline_pages.items():
        check_deadline()
        terminal_page = terminal_pages.get(page_id)
        expected = baseline_page.model_dump(mode="json")
        removed = selected_by_page.get(page_id, set())
        expected["element_ids"] = [
            value for value in expected["element_ids"] if value not in removed
        ]
        expected["presentation_element_ids"] = [
            value
            for value in expected["presentation_element_ids"]
            if value not in removed
        ]
        if terminal_page is None or terminal_page.model_dump(mode="json") != expected:
            raise ValueError("selected-vector IR page custody differs")
    for region_id, baseline_region in baseline_regions.items():
        check_deadline()
        terminal_region = terminal_regions.get(region_id)
        expected = baseline_region.model_dump(mode="json")
        removed = selected_by_region.get(region_id, set())
        expected["element_ids"] = [
            value for value in expected["element_ids"] if value not in removed
        ]
        if terminal_region is None or terminal_region.model_dump(mode="json") != expected:
            raise ValueError("selected-vector IR region custody differs")

    def reading_relationships(
        document_ir: Any,
    ) -> tuple[set[tuple[str, str]], dict[str, Any]]:
        elements = {element.id: element for element in document_ir.elements}
        evidence_ids = {record.id for record in document_ir.evidence}
        expected: set[tuple[str, str]] = set()
        for page in document_ir.pages:
            check_deadline()
            ordered = sorted(
                (
                    elements[identifier].reading_order,
                    elements[identifier].properties.get("source_position"),
                    identifier,
                )
                for identifier in page.presentation_element_ids
            )
            expected.update(
                (first[2], second[2])
                for first, second in zip(ordered, ordered[1:])
            )
        observed_values: list[tuple[str, str]] = []
        raw_values: dict[str, Any] = {}
        for relationship in document_ir.relationships:
            if len(observed_values) % 256 == 0:
                check_deadline()
            if str(relationship.type.value) != "reading_before":
                continue
            if relationship.metadata == {"basis": "legacy_reading_order"}:
                if (
                    relationship.evidence_ids != []
                    or relationship.source_id not in elements
                    or relationship.target_id not in elements
                ):
                    raise ValueError("selected-vector IR reading edge differs")
                observed_values.append(
                    (relationship.source_id, relationship.target_id)
                )
                continue
            metadata = relationship.metadata
            reference_metadata = (
                metadata.get("reference_metadata")
                if type(metadata) is dict
                else None
            )
            if (
                type(metadata) is not dict
                or set(metadata)
                != {
                    "field",
                    "source_ref",
                    "target_ref",
                    "normalization_origin",
                    "reference_metadata",
                }
                or metadata.get("field")
                not in {
                    "body.children.reading_order",
                    "furniture.children.reading_order",
                }
                or metadata.get("normalization_origin")
                != "docling_reference_graph"
                or type(metadata.get("source_ref")) is not str
                or not metadata["source_ref"]
                or type(metadata.get("target_ref")) is not str
                or not metadata["target_ref"]
                or type(reference_metadata) is not list
                or len(reference_metadata) != 1
                or type(reference_metadata[0]) is not dict
                or set(reference_metadata[0])
                != {
                    "root_container",
                    "source_child_index",
                    "target_child_index",
                }
                or reference_metadata[0].get("root_container")
                not in {"#/body", "#/furniture"}
                or type(reference_metadata[0].get("source_child_index"))
                is not int
                or type(reference_metadata[0].get("target_child_index"))
                is not int
                or reference_metadata[0]["target_child_index"]
                != reference_metadata[0]["source_child_index"] + 1
                or relationship.source_id not in elements
                or relationship.target_id not in elements
                or len(relationship.evidence_ids)
                != len(set(relationship.evidence_ids))
                or any(
                    identifier not in evidence_ids
                    for identifier in relationship.evidence_ids
                )
                or relationship.id in raw_values
            ):
                raise ValueError("selected-vector IR raw reading edge differs")
            raw_values[relationship.id] = relationship
        observed = set(observed_values)
        if (
            len(observed_values) != len(observed)
            or len(observed) != len(expected)
            or observed != expected
        ):
            raise ValueError("selected-vector IR reading chain differs")
        return observed, raw_values

    _baseline_pairs, baseline_raw_reading = reading_relationships(baseline_ir)
    _terminal_pairs, terminal_raw_reading = reading_relationships(terminal_ir)
    if not exact_survivors(
        baseline_raw_reading,
        terminal_raw_reading,
        set(),
    ):
        raise ValueError("selected-vector IR raw relationship custody differs")
    baseline_nonreading = {
        identifier: record
        for identifier, record in baseline_relationships.items()
        if str(record.type.value) != "reading_before"
    }
    terminal_nonreading = {
        identifier: record
        for identifier, record in terminal_relationships.items()
        if str(record.type.value) != "reading_before"
    }
    if not exact_survivors(baseline_nonreading, terminal_nonreading, set()):
        raise ValueError("selected-vector IR relationship custody differs")

def _apply_terminal_source_text_alignment(
    payload: dict[str, Any],
    settings: Settings,
    *,
    source_pdf_bytes: bytes | None = None,
    source_text_evidence: Any | None,
    source_sha256: str,
    input_kind: InputKind,
    raw_graph: Mapping[str, Any] | None = None,
    native_texts: Sequence[str] = (),
    text_run_evidence: Any | None = None,
    form_evidence: Any | None = None,
    outline_evidence: Any | None = None,
    table_span_fidelity_document_deadline: float | None = None,
    table_span_fidelity_page_deadlines: dict[int, float] | None = None,
    table_span_fidelity_state: dict[str, Any] | None = None,
    internal_ir_sink: dict[str, Any] | None = None,
    authoritative_table_views: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None = None,
    selected_vector_representations: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None = None,
) -> dict[str, Any]:
    """Apply source selection after all reconciliation and commit atomically."""

    if not settings.text_integrity_source_alignment_enabled:
        return payload

    from app.services.source_text_alignment import (
        SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        align_pages_to_source,
    )

    policy_id = SOURCE_TEXT_ALIGNMENT_POLICY_ID
    custody_runner: Any | None = None
    if (
        settings.table_span_fidelity_enabled
        and table_span_fidelity_document_deadline is not None
        and table_span_fidelity_page_deadlines is not None
        and table_span_fidelity_state is not None
    ):

        def custody_runner(operation: Any) -> Any:
            return _run_table_custody_document_segment(
                table_span_fidelity_document_deadline,
                table_span_fidelity_page_deadlines,
                table_span_fidelity_state,
                operation,
            )
    if input_kind is InputKind.IMAGE:
        projected = deepcopy(payload)
        projected.setdefault("processing", {})["source_text_alignment"] = (
            _source_alignment_terminal_summary(
                policy_id=policy_id,
                source_sha256=source_sha256,
                status="not_applicable",
            )
        )
        return projected

    if source_text_evidence is None or not bool(
        getattr(source_text_evidence, "usable", False)
    ):
        reason = (
            str(getattr(source_text_evidence, "refusal_code", "") or "")
            or "source_evidence_extraction_unavailable"
        )
        projected = deepcopy(payload)
        projected.setdefault("processing", {})["source_text_alignment"] = (
            _source_alignment_terminal_summary(
                policy_id=policy_id,
                source_sha256=source_sha256,
                status="unavailable",
                reason=reason,
            )
        )
        return projected

    predecessor = deepcopy(payload)
    try:
        candidate = deepcopy(payload)
        baseline_ir = (
            internal_ir_sink.get("ir")
            if type(internal_ir_sink) is dict
            else None
        )
        selected_vector_transition_baseline_ir = baseline_ir
        bound_selected_vector_representations: dict[
            int, list[dict[str, Any]]
        ] = {}
        if (
            selected_vector_representations
            and authoritative_table_views is None
            and baseline_ir is not None
            and (
                settings.canonical_serialization_enabled
                or settings.layout_relationship_order_enabled
            )
        ):
            bound_selected_vector_representations = (
                _bind_selected_vector_terminal_representations(
                    candidate,
                    baseline_ir,
                    selected_vector_representations,
                    source_sha256,
                    raw_graph=raw_graph,
                    native_texts=native_texts,
                )
            )
        prior_outline_identity = (
            _outline_replay_identity(payload)
            if settings.layout_outline_structure_enabled
            else ()
        )
        previous_running_timing = (
            deepcopy((candidate.get("processing") or {}).get("running_regions"))
            if settings.layout_running_regions_enabled
            else None
        )
        running_replay_required = bool(
            settings.layout_running_regions_enabled
            and isinstance(previous_running_timing, Mapping)
            and previous_running_timing.get("status") == "projected"
        )
        prior_running_identity: Mapping[str, Any] | None = None
        if running_replay_required:
            from app.services.running_regions import (
                running_region_replay_identity,
            )

            # Capture before any strip or alignment mutation.  The terminal
            # transaction may commit only an identity-equivalent replay.
            prior_running_identity = running_region_replay_identity(payload)
        reentry_required = (
            settings.canonical_serialization_enabled
            or settings.layout_relationship_order_enabled
        )
        prepared_terminal_source: dict[str, Any] | None = None
        terminal_preparation_error: Exception | None = None
        if reentry_required:
            try:
                if running_replay_required:
                    from app.services.running_regions import strip_running_regions

                    if bound_selected_vector_representations:
                        (
                            prepared_terminal_source,
                            selected_vector_transition_baseline_ir,
                        ) = strip_running_regions(payload, baseline_ir)
                    else:
                        prepared_terminal_source = strip_running_regions(payload)
                    if prepared_terminal_source is payload:
                        prepared_terminal_source = deepcopy(payload)
                else:
                    prepared_terminal_source = deepcopy(payload)
                if settings.layout_outline_structure_enabled:
                    from app.services.outline_structure import (
                        strip_outline_structure_public,
                    )

                    prepared_terminal_source = strip_outline_structure_public(
                        prepared_terminal_source
                    )
                    for page in prepared_terminal_source.get("pages") or []:
                        if not isinstance(page, Mapping):
                            continue
                        for item in page.get("items") or []:
                            if not isinstance(item, Mapping):
                                continue
                            if (
                                item.get("layout_outline_structure_projected") is True
                                or item.get("outline_policy")
                                == "p03-outline-structure-v1"
                                or any(
                                    key in item
                                    for key in (
                                        "outline_group",
                                        "outline_items",
                                        "outline_continuations",
                                    )
                                )
                                or any(
                                    isinstance(value, Mapping)
                                    and value.get("outline_policy")
                                    == "p03-outline-structure-v1"
                                    for value in item.get("relationships") or []
                                )
                            ):
                                raise ValueError(
                                    "outline sidecar could not be safely "
                                    "stripped before terminal re-entry"
                                )
                if settings.layout_forms_enabled:
                    from app.services.form_semantics import (
                        strip_form_semantics_public,
                    )

                    prepared_terminal_source = strip_form_semantics_public(
                        prepared_terminal_source
                    )
                prepared_terminal_source.pop(
                    "canonical_presentation",
                    None,
                )
                if settings.table_span_fidelity_enabled:
                    prepared_terminal_source.pop(
                        "canonical_source_custody",
                        None,
                    )
            except Exception as exc:
                prepared_terminal_source = None
                terminal_preparation_error = exc

        alignment_source = prepared_terminal_source or candidate
        alignment_predecessor_pages = alignment_source.get("pages") or []
        if not isinstance(alignment_predecessor_pages, list):
            raise ValueError("source alignment pages differ")
        working_pages = deepcopy(alignment_predecessor_pages)
        alignment_arguments: dict[str, Any] = {}
        if authoritative_table_views is not None:
            alignment_arguments["authoritative_table_views"] = (
                authoritative_table_views
            )
        elif bound_selected_vector_representations:
            alignment_arguments["selected_vector_representations"] = (
                bound_selected_vector_representations
            )
        summary = align_pages_to_source(
            working_pages,
            source_text_evidence,
            **alignment_arguments,
        ).to_dict()
        _validate_source_alignment_summary(
            summary,
            policy_id=policy_id,
            source_sha256=source_sha256,
        )
        selection_reasons = {
            selection.get("terminal_reason")
            for selection in summary.get("selections") or []
            if isinstance(selection, Mapping)
        }
        selected_vector_reason = (
            "selected_vector_source_owned_table_duplicate"
        )
        if selected_vector_reason in selection_reasons and any(
            reason != selected_vector_reason for reason in selection_reasons
        ):
            # The strict vector IR transition intentionally permits no other
            # public/IR mutation.  Deterministically rerun once from the exact
            # predecessor without optional vector authority so an unrelated
            # source correction is never lost or broadly normalized.
            working_pages = deepcopy(alignment_predecessor_pages)
            summary = align_pages_to_source(
                working_pages,
                source_text_evidence,
            ).to_dict()
            _validate_source_alignment_summary(
                summary,
                policy_id=policy_id,
                source_sha256=source_sha256,
            )
            if any(
                isinstance(selection, Mapping)
                and selection.get("terminal_reason") == selected_vector_reason
                for selection in summary.get("selections") or []
            ):
                raise ValueError(
                    "generic-only source alignment retained vector authority"
                )
            bound_selected_vector_representations = {}
        if int(summary.get("selected_count") or 0) == 0:
            if working_pages != alignment_predecessor_pages:
                raise ValueError("zero-selection source alignment mutated public pages")
            candidate.setdefault("processing", {})["source_text_alignment"] = summary
            if bound_selected_vector_representations and (
                _bind_selected_vector_terminal_representations(
                    candidate,
                    baseline_ir,
                    selected_vector_representations,
                    source_sha256,
                    raw_graph=raw_graph,
                    native_texts=native_texts,
                )
                != bound_selected_vector_representations
            ):
                raise ValueError(
                    "zero-selection selected-vector authority differs"
                )
            _validate_terminal_source_alignment(
                candidate,
                summary,
                source_text_evidence=source_text_evidence,
                authoritative_table_views=authoritative_table_views,
                selected_vector_representations=(
                    bound_selected_vector_representations
                ),
            )
            if (
                settings.canonical_serialization_enabled
                and baseline_ir is not None
                and bound_selected_vector_representations
            ):
                candidate, summary = _apply_terminal_canonical_ocr_omission(
                    candidate,
                    baseline_ir,
                    summary,
                    source_text_evidence=source_text_evidence,
                    selected_vector_representations=(
                        bound_selected_vector_representations
                    ),
                    source_pdf_bytes=source_pdf_bytes,
                    authoritative_table_views=authoritative_table_views,
                )
            return candidate

        if reentry_required and prepared_terminal_source is None:
            if terminal_preparation_error is not None:
                raise terminal_preparation_error
            raise ValueError("terminal source preparation is unavailable")
        candidate["pages"] = working_pages
        candidate.setdefault("processing", {})["source_text_alignment"] = summary

        # Canonical presentation is derived from the internal IR. Re-enter
        # once without candidate reconciliation so the aligned projection is
        # the terminal source of both v1 and canonical serialization.
        if reentry_required:
            from app.services.ir import round_trip_document

            previous_form_timing = (
                deepcopy((candidate.get("processing") or {}).get("form_semantics"))
                if settings.layout_forms_enabled
                else None
            )
            terminal_form_metrics: dict[str, float] | None = (
                {} if settings.layout_forms_enabled else None
            )
            previous_outline_timing = (
                deepcopy((candidate.get("processing") or {}).get("outline_structure"))
                if settings.layout_outline_structure_enabled
                else None
            )
            terminal_outline_metrics: dict[str, Any] | None = (
                {} if settings.layout_outline_structure_enabled else None
            )
            assert prepared_terminal_source is not None
            terminal_source = prepared_terminal_source
            terminal_source["pages"] = working_pages
            terminal_source.setdefault("processing", {})["source_text_alignment"] = (
                summary
            )
            terminal_projected, terminal_ir = round_trip_document(
                terminal_source,
                raw_graph=raw_graph,
                native_texts=native_texts,
                **(
                    {"text_reconciliation_enabled": True}
                    if settings.text_reconciliation_enabled
                    else {}
                ),
                layout_settings=(
                    settings
                    if (
                        settings.layout_table_captions_enabled
                        or settings.layout_visual_relationships_enabled
                        or settings.layout_source_notes_enabled
                        or settings.layout_relationship_order_enabled
                        or settings.layout_text_run_semantics_enabled
                        or settings.layout_forms_enabled
                        or settings.layout_outline_structure_enabled
                    )
                    else None
                ),
                text_run_evidence=(
                    text_run_evidence
                    if settings.layout_text_run_semantics_enabled
                    else None
                ),
                **(
                    {
                        "form_evidence": form_evidence,
                        "form_metrics": terminal_form_metrics,
                    }
                    if settings.layout_forms_enabled
                    else {}
                ),
                **(
                    {
                        "outline_evidence": outline_evidence,
                        "outline_metrics": terminal_outline_metrics,
                    }
                    if settings.layout_outline_structure_enabled
                    else {}
                ),
                **(
                    {"table_span_fidelity_enabled": True}
                    if settings.table_span_fidelity_enabled
                    else {}
                ),
                **(
                    {"table_custody_runner": custody_runner}
                    if custody_runner is not None
                    else {}
                ),
            )
            candidate = terminal_projected
            if settings.layout_forms_enabled:
                from app.services.form_semantics import (
                    form_processing_summary,
                )

                current_form_timing = form_processing_summary(terminal_form_metrics)
                prior_form_timing = form_processing_summary(previous_form_timing)
                combined_projection_ms = (
                    prior_form_timing["projection_ms"]
                    + current_form_timing["projection_ms"]
                )
                candidate.setdefault("processing", {})["form_semantics"] = (
                    form_processing_summary(
                        {
                            "extraction_ms": prior_form_timing["extraction_ms"],
                            "projection_ms": combined_projection_ms,
                            "total_ms": (
                                prior_form_timing["extraction_ms"]
                                + combined_projection_ms
                            ),
                        }
                    )
                )
            if settings.layout_outline_structure_enabled:
                from app.services.outline_structure import (
                    outline_processing_summary,
                )

                current_outline_timing = outline_processing_summary(
                    terminal_outline_metrics
                )
                prior_outline_timing = outline_processing_summary(
                    previous_outline_timing
                )
                current_outline_identity = _outline_replay_identity(candidate)
                if prior_outline_identity and (
                    current_outline_timing["status"] != "projected"
                    or current_outline_identity != prior_outline_identity
                    or current_outline_timing["group_count"]
                    != len(prior_outline_identity)
                    or current_outline_timing["node_count"]
                    != sum(len(value[1]) for value in prior_outline_identity)
                    or current_outline_timing["relationship_count"]
                    != sum(len(value[3]) for value in prior_outline_identity)
                ):
                    raise ValueError(
                        "terminal outline replay did not preserve the projected graph"
                    )
                candidate.setdefault("processing", {})["outline_structure"] = (
                    outline_processing_summary(
                        {
                            **current_outline_timing,
                            "extraction_ms": prior_outline_timing["extraction_ms"],
                            "projection_ms": round(
                                prior_outline_timing["projection_ms"]
                                + current_outline_timing["projection_ms"],
                                3,
                            ),
                        }
                    )
                )
            candidate.setdefault("processing", {})["source_text_alignment"] = summary
            if settings.canonical_serialization_enabled:
                from app.services.presentation import (
                    build_canonical_presentation,
                )

                candidate["canonical_presentation"] = (
                    build_canonical_presentation(terminal_ir).model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                )
            vector_ir_selections = [
                selection
                for selection in summary.get("selections") or []
                if isinstance(selection, Mapping)
                and selection.get("terminal_reason")
                == "selected_vector_source_owned_table_duplicate"
            ]
            selected_vector_transition_validated = False
            if bound_selected_vector_representations:
                pre_replay_bound_selected_vectors = (
                    _bind_selected_vector_terminal_representations(
                        candidate,
                        terminal_ir,
                        bound_selected_vector_representations,
                        source_sha256,
                        raw_graph=raw_graph,
                        native_texts=native_texts,
                    )
                )
                if (
                    pre_replay_bound_selected_vectors
                    != bound_selected_vector_representations
                ):
                    raise ValueError(
                        "selected-vector pre-replay table authority differs"
                    )
                if vector_ir_selections:
                    _validate_selected_vector_ir_transition(
                        selected_vector_transition_baseline_ir,
                        terminal_ir,
                        vector_ir_selections,
                        candidate,
                    )
                    selected_vector_transition_validated = True
            if running_replay_required:
                from app.services.running_regions import (
                    replay_running_regions,
                    replay_running_regions_identity_locked,
                    running_region_replay_identity,
                )

                if not isinstance(source_pdf_bytes, bytes) or not source_pdf_bytes:
                    raise ValueError("running-region replay source is unavailable")
                if prior_running_identity is None or (
                    vector_ir_selections and baseline_ir is None
                ):
                    raise ValueError(
                        "running-region replay baseline authority is unavailable"
                    )
                authorized_owner_ids: list[str] = []
                authorized_owner_ids_by_page: dict[int, list[str]] = defaultdict(list)
                aligned_running_owner_ids: list[str] = []
                predecessor_owner_pages: dict[str, list[int]] = defaultdict(list)
                for predecessor_page in predecessor.get("pages") or []:
                    if not isinstance(predecessor_page, Mapping):
                        raise ValueError(
                            "terminal running-region predecessor page differs"
                        )
                    predecessor_page_index = predecessor_page.get("page_index")
                    if (
                        type(predecessor_page_index) is not int
                        or predecessor_page_index < 1
                    ):
                        raise ValueError(
                            "terminal running-region predecessor page differs"
                        )
                    for predecessor_item in predecessor_page.get("items") or []:
                        predecessor_owner_id = (
                            predecessor_item.get("id")
                            if isinstance(predecessor_item, Mapping)
                            else None
                        )
                        if isinstance(predecessor_owner_id, str) and predecessor_owner_id:
                            predecessor_owner_pages[predecessor_owner_id].append(
                                predecessor_page_index
                            )
                for selection in summary.get("selections") or []:
                    if not isinstance(selection, Mapping):
                        raise ValueError(
                            "terminal running-region alignment selection differs"
                        )
                    owner_id = selection.get("owner_id")
                    owner_type = selection.get("owner_type")
                    selection_page_index = selection.get("page_index")
                    if not isinstance(owner_id, str) or not owner_id:
                        raise ValueError(
                            "terminal running-region alignment owner differs"
                        )
                    owner_pages = predecessor_owner_pages.get(owner_id, [])
                    if selection_page_index is None and len(owner_pages) == 1:
                        selection_page_index = owner_pages[0]
                    if (
                        type(selection_page_index) is not int
                        or selection_page_index < 1
                        or owner_pages != [selection_page_index]
                    ):
                        raise ValueError(
                            "terminal running-region alignment page differs"
                        )
                    authorized_owner_ids.append(owner_id)
                    authorized_owner_ids_by_page[selection_page_index].append(
                        owner_id
                    )
                    if owner_type in {"header", "footer"}:
                        aligned_running_owner_ids.append(owner_id)
                if len(authorized_owner_ids) != len(set(authorized_owner_ids)):
                    raise ValueError("terminal running-region alignment owner repeats")
                aligned_running_owner_closure = (
                    _terminal_running_alignment_owner_closure(
                        candidate,
                        aligned_running_owner_ids,
                    )
                )
                if vector_ir_selections:
                    assert baseline_ir is not None
                    candidate, terminal_ir = (
                        replay_running_regions_identity_locked(
                            candidate,
                            terminal_ir,
                            source_pdf_bytes,
                            baseline_projected_public=payload,
                            baseline_projected_ir=baseline_ir,
                            baseline_identity=prior_running_identity,
                            alignment_authorized_owner_ids_by_page=(
                                authorized_owner_ids_by_page
                            ),
                            alignment_selections=vector_ir_selections,
                            prior_summary=previous_running_timing,
                        )
                    )
                else:
                    candidate, terminal_ir = replay_running_regions(
                        candidate,
                        terminal_ir,
                        source_pdf_bytes,
                        prior_summary=previous_running_timing,
                    )
                replay_summary = (candidate.get("processing") or {}).get(
                    "running_regions"
                )
                if (
                    not isinstance(replay_summary, Mapping)
                    or replay_summary.get("status") != "projected"
                    or prior_running_identity is None
                ):
                    raise ValueError("terminal running-region replay was not projected")
                if _terminal_running_alignment_owner_closure(
                    candidate,
                    aligned_running_owner_ids,
                ) != aligned_running_owner_closure:
                    raise ValueError(
                        "terminal running-region aligned owner closure differs"
                    )
                replay_identity = running_region_replay_identity(
                    candidate,
                    baseline_identity=prior_running_identity,
                    alignment_authorized_owner_ids_by_page=(
                        authorized_owner_ids_by_page
                    ),
                )
                if not _terminal_running_alignment_dependencies_are_closed(
                    candidate,
                    terminal_ir,
                    aligned_running_owner_ids,
                ):
                    raise ValueError(
                        "terminal running-region aligned owner dependencies differ"
                    )
                if not _terminal_running_alignment_identity_matches(
                    prior_running_identity,
                    replay_identity,
                    aligned_running_owner_ids,
                ):
                    raise ValueError("terminal running-region replay identity differs")

        final_bound_selected_vector_representations: dict[
            int, list[dict[str, Any]]
        ] = {}
        if bound_selected_vector_representations:
            final_bound_selected_vector_representations = (
                _bind_selected_vector_terminal_representations(
                    candidate,
                    terminal_ir,
                    bound_selected_vector_representations,
                    source_sha256,
                    raw_graph=raw_graph,
                    native_texts=native_texts,
                )
            )
            if (
                final_bound_selected_vector_representations
                != bound_selected_vector_representations
            ):
                raise ValueError(
                    "selected-vector terminal table authority differs"
                )
            if vector_ir_selections and not selected_vector_transition_validated:
                raise ValueError(
                    "selected-vector IR transition was not independently validated"
                )
        _validate_terminal_source_alignment(
            candidate,
            summary,
            source_text_evidence=source_text_evidence,
            authoritative_table_views=authoritative_table_views,
            selected_vector_representations=(
                final_bound_selected_vector_representations
            ),
        )
        if (
            settings.canonical_serialization_enabled
            and final_bound_selected_vector_representations
        ):
            candidate, summary = _apply_terminal_canonical_ocr_omission(
                candidate,
                terminal_ir,
                summary,
                source_text_evidence=source_text_evidence,
                selected_vector_representations=(
                    final_bound_selected_vector_representations
                ),
                source_pdf_bytes=source_pdf_bytes,
                authoritative_table_views=authoritative_table_views,
            )
        if internal_ir_sink is not None:
            internal_ir_sink["ir"] = terminal_ir
        return candidate
    except Exception as exc:
        if settings.table_span_fidelity_enabled and table_span_fidelity_state is not None:
            from app.services.opaque_group_custody import (
                OpaqueGroupCustodyResourceError,
                OpaqueGroupCustodyTimeoutError,
            )

            if isinstance(exc, OpaqueGroupCustodyTimeoutError):
                table_span_fidelity_state["timed_out"] = True
            elif isinstance(exc, OpaqueGroupCustodyResourceError):
                table_span_fidelity_state["custody_rejected"] = True
        predecessor.setdefault("processing", {})["source_text_alignment"] = (
            _source_alignment_terminal_summary(
                policy_id=policy_id,
                source_sha256=source_sha256,
                status="unavailable",
                reason="source_alignment_failed_closed",
                error_type=type(exc).__name__,
            )
        )
        predecessor.setdefault("warnings", []).append(
            f"Source text alignment failed closed: {type(exc).__name__}."
        )
        return predecessor


def _parse_document_without_stage_telemetry(
    document_bytes: bytes,
    filename: str,
    settings: Settings,
    *,
    parser_worker: Any | None = None,
    office_renderer: Any | None = None,
) -> ParseResult:
    """Parse one supported document into the shared normalized model."""

    office_flags = {
        ".docx": (settings.adapters_docx_native_enabled, "docx"),
        ".pptx": (settings.adapters_pptx_native_enabled, "pptx"),
        ".xlsx": (settings.adapters_xlsx_native_enabled, "xlsx"),
    }
    suffix = Path(filename).suffix.casefold()
    office = office_flags.get(suffix)
    if office is not None and office[0]:
        from app.services.adapter_contracts import (
            AdapterDispatchError,
            builtin_adapter_registry,
        )
        from app.services.ooxml_intake import (
            OoxmlIntakeError,
            OoxmlResourceLimitError,
            intake_ooxml,
            limits_from_settings,
        )

        try:
            media_type = {
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }[office[1]]
            # Native Office formats enter through the same fail-closed
            # registration and dispatch boundary as PDF/raster.  The adapter
            # itself owns bounded intake and native parsing.
            payload = builtin_adapter_registry(settings).dispatch(
                document_bytes,
                filename,
                media_type,
                settings,
            )
            if settings.adapters_office_charts_enabled and office[1] in {
                "pptx",
                "xlsx",
            }:
                from app.services.office_charts import apply_office_charts

                # Chart reconciliation needs read-only part access after the
                # native adapter has completed.  Reopening the immutable
                # package repeats the same bounded, non-executing intake gate.
                package = intake_ooxml(
                    document_bytes,
                    filename,
                    media_type,
                    limits=limits_from_settings(settings),
                )
                payload = apply_office_charts(payload, package, settings)
            if settings.adapters_office_fallback_enabled:
                from app.services.office_fallback import apply_office_visual_fallback

                payload = apply_office_visual_fallback(
                    payload,
                    settings,
                    renderer=office_renderer,
                    source_bytes=document_bytes,
                )
            return ParseResult.model_validate(payload)
        except OoxmlResourceLimitError as exc:
            from app.errors import OoxmlLimitExceededError

            raise OoxmlLimitExceededError(
                details={
                    "reason": exc.code,
                    "stage": exc.stage,
                    **exc.details,
                }
            ) from exc
        except OoxmlIntakeError as exc:
            from app.errors import InvalidOoxmlError

            raise InvalidOoxmlError(
                details={
                    "reason": exc.code,
                    "stage": exc.stage,
                    **exc.details,
                }
            ) from exc
        except AdapterDispatchError as exc:
            from app.errors import InvalidOoxmlError

            raise InvalidOoxmlError(
                details={"reason": exc.code, **exc.details}
            ) from exc
        except Exception as exc:
            # Native format adapters use their own small, reason-coded error
            # hierarchy after the shared package boundary.  Convert those
            # refusals to the same stable public 413/422 envelopes without
            # swallowing unrelated implementation failures.
            from app.services.office_native import (
                OfficeNativeError,
                OfficeNativeLimitError,
            )

            if isinstance(exc, OfficeNativeLimitError):
                from app.errors import OoxmlLimitExceededError

                raise OoxmlLimitExceededError(
                    details={"reason": exc.code, **exc.details}
                ) from exc
            if isinstance(exc, OfficeNativeError):
                from app.errors import InvalidOoxmlError

                raise InvalidOoxmlError(
                    details={"reason": exc.code, **exc.details}
                ) from exc
            raise

    loaded = (
        load_document_via_adapter(document_bytes, filename, settings)
        if settings.adapters_conformance_enabled
        else load_document(document_bytes, filename, settings)
    )
    if settings.parser_latency_prewarm_enabled:
        return _parse_loaded_document(
            loaded,
            settings,
            parser_worker=parser_worker,
        )
    return _parse_loaded_document(loaded, settings, parser_worker=parser_worker)


def parse_document(
    document_bytes: bytes,
    filename: str,
    settings: Settings,
    *,
    parser_worker: Any | None = None,
    office_renderer: Any | None = None,
) -> ParseResult:
    """Parse one supported document with optional common stage telemetry.

    The release-first trace intentionally treats dispatch as the aggregate
    shipped processing boundary.  More detailed resource reconciliation is
    deferred; this wrapper only supplies common lifecycle, elapsed-duration,
    and error signals without changing either implementation path.
    """

    from app.services.stage_telemetry import StageLifecycle

    lifecycle = StageLifecycle(settings, filename=filename)
    with lifecycle.stage("complete"):
        with lifecycle.stage("dispatch"):
            try:
                result = _parse_document_without_stage_telemetry(
                    document_bytes,
                    filename,
                    settings,
                    parser_worker=parser_worker,
                    office_renderer=office_renderer,
                )
            except Exception as exc:
                from app.errors import AppError
                from app.services.quality_telemetry import (
                    observe_deterministic_failure,
                )

                observe_deterministic_failure(
                    settings,
                    validation=isinstance(exc, AppError),
                )
                raise
            if settings.deterministic_confidence_enabled:
                from app.services.deterministic_confidence import (
                    apply_deterministic_confidence,
                )

                result = apply_deterministic_confidence(result, enabled=True)
            if settings.review_escalation_enabled:
                from app.services.review_routing import (
                    route_parse_result_for_review,
                )

                result = route_parse_result_for_review(
                    result,
                    enabled=True,
                ).result
            from app.services.quality_telemetry import (
                observe_deterministic_result,
            )

            observe_deterministic_result(result, settings)
            return result
