"""Bounded, source-grounded form and key/value semantics (P03-US06).

The extractor deliberately retains a small immutable description of PDF
source objects.  Projection is a separate operation over the compatibility
IR so disabling the feature performs no PDF work and a failed projection can
be rolled back without mutating its predecessor.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import re
import time
from bisect import bisect_left, bisect_right
from collections import Counter
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import (
    dataclass,
    field as dataclass_field,
    fields as dataclass_fields,
    is_dataclass,
    replace,
)
from io import BytesIO
from typing import Any, Literal, Mapping, MutableMapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from app.services.acroform import AcroFormPageInput, inspect_acroform
from app.services.acroform_raw import audit_acroform_raw
from app.services.ir import (
    ConfidenceRecord,
    DocumentIR,
    ElementRecord,
    EvidenceMethod,
    EvidenceRecord,
    FormControlSemanticDescriptor,
    FormFieldSemanticDescriptor,
    FormGroupSemanticDescriptor,
    FormKeyValuePairSemanticDescriptor,
    FormLabelSemanticDescriptor,
    FormValueRegionSemanticDescriptor,
    IRBoundingBox,
    IRConcern,
    MAX_FORM_CLASS_RECORDS_PER_DOCUMENT,
    MAX_FORM_CLASS_RECORDS_PER_PAGE,
    MAX_FORM_CONCERNS_PER_GROUP,
    MAX_FORM_CONTROLS_PER_GROUP,
    MAX_FORM_FIELDS_PER_GROUP,
    MAX_FORM_GROUPS_PER_DOCUMENT,
    MAX_FORM_GROUPS_PER_PAGE,
    MAX_FORM_KEY_VALUE_PAIRS_PER_GROUP,
    MAX_FORM_LABELS_PER_GROUP,
    MAX_FORM_RELATIONSHIPS_PER_DOCUMENT,
    MAX_FORM_RELATIONSHIPS_PER_PAGE,
    MAX_FORM_SEMANTIC_RECORDS_PER_DOCUMENT,
    MAX_FORM_SEMANTIC_RECORDS_PER_PAGE,
    MAX_FORM_VALUE_REGIONS_PER_GROUP,
    RelationshipRecord,
    RelationshipType,
)


POLICY_ID = "p03-form-semantics-v1"
REPORT_VERSION = "p03-form-source-evidence-v1"

MAX_SOURCE_CHARACTERS = 500_000
MAX_WORDS_PER_PAGE = 16_384
MAX_WORDS_PER_DOCUMENT = 100_000
MAX_VECTOR_OBJECTS_PER_PAGE = 16_384
MAX_VECTOR_OBJECTS_PER_DOCUMENT = 262_144
MAX_CURVE_POINTS_PER_OBJECT = 512
MAX_CURVE_POINTS_PER_PAGE = 65_536
MAX_CURVE_POINTS_PER_DOCUMENT = 500_000
MAX_ANNOTATIONS_PER_PAGE = 2_048
MAX_ANNOTATIONS_PER_DOCUMENT = 10_000
MAX_CANDIDATE_SHAPES_PER_PAGE = 4_096
MAX_COMPARISONS_PER_PAGE = 65_536
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_PUBLIC_GROUP_BYTES = 256 * 1024
MAX_TEXT_BYTES = 16 * 1024
MAX_PRESENTATION_TEXT_BYTES_PER_PAGE = 1 * 1024 * 1024
MAX_PRESENTATION_TEXT_BYTES_PER_DOCUMENT = 8 * 1024 * 1024
DEADLINE_SECONDS = 2.0
_MAX_SPATIAL_BUCKET_SPAN = 64

_ID_LIMIT = 256
_JSON_STRING_ESCAPE_RE = re.compile(r'[\x00-\x1f"\\]')
_SourceIdentity = tuple[str, int | str, int | None]
_ALLOWED_CONCERNS = frozenset(
    {
        "form_source_evidence_unavailable",
        "form_source_limit",
        "form_interactivity_unknown",
        "form_transform_unavailable",
        "form_candidate_limit",
        "form_relationship_limit",
        "form_geometry_ambiguous",
        "form_value_boundary_implicit",
        "form_value_state_ambiguous",
        "form_control_state_ambiguous",
        "form_table_ownership_ambiguous",
        "form_projection_failed_closed",
        "form_concerns_truncated",
    }
)
_FORM_GROUP_ROLE_LIMITS: Mapping[str, int] = {
    "field": MAX_FORM_FIELDS_PER_GROUP,
    "label": MAX_FORM_LABELS_PER_GROUP,
    "value_region": MAX_FORM_VALUE_REGIONS_PER_GROUP,
    "control": MAX_FORM_CONTROLS_PER_GROUP,
    "key_value_pair": MAX_FORM_KEY_VALUE_PAIRS_PER_GROUP,
}


@dataclass(frozen=True, slots=True)
class SourceChar:
    index: int
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    font_name: str
    size: float


@dataclass(frozen=True, slots=True)
class SourceWord:
    index: int
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    font_name: str
    size: float
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class SourceVector:
    kind: Literal["line", "rect", "curve"]
    index: int
    x0: float
    top: float
    x1: float
    bottom: float
    fill: bool


@dataclass(frozen=True, slots=True)
class SourceAnnotation:
    index: int
    subtype: str
    x0: float
    top: float
    x1: float
    bottom: float
    object_ref_digest: str


@dataclass(frozen=True, slots=True)
class SourceInteractiveControl:
    annotation_index: int
    bbox: tuple[float, float, float, float]
    widget_ref_digest: str
    field_ref_digest: str
    field_name: str | None
    control_type: Literal["checkbox", "radio", "unknown"]
    state: Literal["checked", "unchecked", "not_applicable", "ambiguous"]
    concern_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FormSourcePage:
    page_index: int
    width: float
    height: float
    chars: tuple[SourceChar, ...]
    words: tuple[SourceWord, ...]
    vectors: tuple[SourceVector, ...]
    annotations: tuple[SourceAnnotation, ...]
    interactivity: Literal["none", "static", "interactive", "mixed", "unknown"]
    interactive_controls: tuple[SourceInteractiveControl, ...] = ()
    concern_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FormEvidenceReport:
    report_version: Literal["p03-form-source-evidence-v1"]
    policy_id: Literal["p03-form-semantics-v1"]
    source_sha256: str
    pages: tuple[FormSourcePage, ...]
    interactivity: Literal["none", "static", "interactive", "mixed", "unknown"]
    concern_codes: tuple[str, ...]
    extraction_ms: float


@dataclass(slots=True)
class _ExtractionBudget:
    started_at: float
    comparisons: int = 0

    def check_deadline(self) -> None:
        if time.perf_counter() - self.started_at > DEADLINE_SECONDS:
            raise TimeoutError(
                "form source extraction exceeded its deadline"
            )

    def account_comparison(self) -> None:
        self.comparisons += 1
        if self.comparisons > MAX_COMPARISONS_PER_PAGE:
            raise ValueError(
                "form source comparison limit exceeded"
            )
        if self.comparisons % 256 == 0:
            self.check_deadline()


def _iter_compact_json(value: Any) -> Any:
    """Yield the exact compact/sorted JSON representation without copying."""

    if is_dataclass(value) and not isinstance(value, type):
        yield "{"
        ordered_fields = sorted(
            dataclass_fields(value),
            key=lambda record_field: record_field.name,
        )
        for index, record_field in enumerate(ordered_fields):
            if index:
                yield ","
            yield json.dumps(
                record_field.name,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield ":"
            yield from _iter_compact_json(
                getattr(value, record_field.name)
            )
        yield "}"
        return
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("form source report mapping keys must be strings")
        yield "{"
        for index, key in enumerate(sorted(value)):
            if index:
                yield ","
            yield json.dumps(
                key,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield ":"
            yield from _iter_compact_json(value[key])
        yield "}"
        return
    if isinstance(value, (list, tuple)):
        yield "["
        for index, item in enumerate(value):
            if index:
                yield ","
            yield from _iter_compact_json(item)
        yield "]"
        return
    try:
        yield json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("form source report value is not serializable") from exc


def _compact_json_size(value: Any, *, limit: int | None = None) -> int:
    """Return exact compact JSON bytes with bounded, allocation-free descent."""

    total = 0
    string_size_cache: dict[str, int] = {}

    def string_size(current: str) -> int:
        cached = string_size_cache.get(current)
        if cached is not None:
            return cached
        size = _compact_json_string_size(current)
        if len(string_size_cache) < 4_096:
            string_size_cache[current] = size
        return size

    def add(size: int) -> bool:
        nonlocal total
        total += size
        return limit is not None and total > limit

    def visit(current: Any) -> bool:
        if is_dataclass(current) and not isinstance(current, type):
            fields = dataclass_fields(current)
            if add(2 + max(0, len(fields) - 1)):
                return True
            for record_field in fields:
                if add(
                    string_size(record_field.name) + 1
                ) or visit(getattr(current, record_field.name)):
                    return True
            return False
        if isinstance(current, Mapping):
            if not all(isinstance(key, str) for key in current):
                raise ValueError(
                    "form source report mapping keys must be strings"
                )
            if add(2 + max(0, len(current) - 1)):
                return True
            for key, item in current.items():
                if add(string_size(key) + 1) or visit(
                    item
                ):
                    return True
            return False
        if isinstance(current, (list, tuple)):
            if add(2 + max(0, len(current) - 1)):
                return True
            for item in current:
                if visit(item):
                    return True
            return False
        if isinstance(current, str):
            return add(string_size(current))
        if current is None:
            return add(4)
        if current is True:
            return add(4)
        if current is False:
            return add(5)
        if isinstance(current, int):
            return add(len(str(current)))
        if isinstance(current, float):
            return add(_compact_json_float_size(current))
        try:
            encoded = json.dumps(
                current,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "form source report value is not serializable"
            ) from exc
        return add(len(encoded))

    try:
        visit(value)
    except UnicodeError as exc:
        raise ValueError("form source report value is not encodable") from exc
    return total


def _compact_json_string_size(value: str) -> int:
    if _JSON_STRING_ESCAPE_RE.search(value) is None:
        if value.isascii():
            return len(value) + 2
        try:
            return len(value.encode("utf-8")) + 2
        except UnicodeError as exc:
            raise ValueError(
                "form source report value is not encodable"
            ) from exc
    try:
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except UnicodeError as exc:
        raise ValueError("form source report value is not encodable") from exc


def _compact_json_string_array_size(values: Sequence[str]) -> int:
    return (
        2
        + sum(_compact_json_string_size(value) for value in values)
        + max(0, len(values) - 1)
    )


def _compact_json_float_size(value: float) -> int:
    if not math.isfinite(value):
        raise ValueError("form source report value is not finite")
    return len(repr(value))


def _compact_public_sidecar_size(
    sidecar: Mapping[str, Any],
    *,
    limit: int,
) -> int:
    """Measure a bounded public sidecar one validated record at a time."""

    total = 2 + max(0, len(sidecar) - 1)
    for key, value in sidecar.items():
        total += _compact_json_string_size(key) + 1
        if total > limit:
            return total
        if isinstance(value, list):
            total += 2 + max(0, len(value) - 1)
            if total > limit:
                return total
            values = value
        else:
            values = (value,)
        for item in values:
            try:
                total += len(
                    json.dumps(
                        item,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
            except (TypeError, ValueError, UnicodeError) as exc:
                raise ValueError(
                    "form public sidecar value is not serializable"
                ) from exc
            if total > limit:
                return total
    return total


@dataclass(slots=True)
class _RetainedReportBudget:
    """Bound report growth before a large dataclass graph can accumulate."""

    current_record_bytes: Counter[type] = dataclass_field(
        default_factory=Counter
    )
    current_record_counts: Counter[type] = dataclass_field(
        default_factory=Counter
    )
    all_record_bytes: int = 0
    page_payload_bytes: int = 0
    page_count: int = 0

    def account_record(self, record: Any) -> None:
        if isinstance(record, SourceChar):
            size = (
                88
                + _compact_json_string_size(record.text)
                - 2
                + _compact_json_string_size(record.font_name)
                - 2
                + len(str(record.index))
                - 1
                + sum(
                    _compact_json_float_size(value) - 3
                    for value in (
                        record.bottom,
                        record.size,
                        record.top,
                        record.x0,
                        record.x1,
                    )
                )
            )
        elif isinstance(record, SourceWord):
            size = (
                116
                + _compact_json_string_size(record.text)
                - 2
                + _compact_json_string_size(record.font_name)
                - 2
                + sum(
                    len(str(value)) - 1
                    for value in (
                        record.index,
                        record.char_start,
                        record.char_end,
                    )
                )
                + sum(
                    _compact_json_float_size(value) - 3
                    for value in (
                        record.bottom,
                        record.size,
                        record.top,
                        record.x0,
                        record.x1,
                    )
                )
            )
        elif isinstance(record, SourceVector):
            size = (
                74
                + _compact_json_string_size(record.kind)
                - 2
                + len(str(record.index))
                - 1
                + (0 if record.fill else 1)
                + sum(
                    _compact_json_float_size(value) - 3
                    for value in (
                        record.bottom,
                        record.top,
                        record.x0,
                        record.x1,
                    )
                )
            )
        elif isinstance(record, SourceAnnotation):
            size = (
                88
                + _compact_json_string_size(record.subtype)
                - 2
                + _compact_json_string_size(record.object_ref_digest)
                - 2
                + len(str(record.index))
                - 1
                + sum(
                    _compact_json_float_size(value) - 3
                    for value in (
                        record.bottom,
                        record.top,
                        record.x0,
                        record.x1,
                    )
                )
            )
        elif isinstance(record, SourceInteractiveControl):
            size = (
                156
                + len(str(record.annotation_index))
                - 1
                + sum(
                    _compact_json_float_size(value) - 3
                    for value in record.bbox
                )
                + _compact_json_string_array_size(
                    record.concern_codes
                )
                - 2
                + sum(
                    _compact_json_string_size(value) - 2
                    for value in (
                        record.widget_ref_digest,
                        record.field_ref_digest,
                        record.control_type,
                        record.state,
                    )
                )
                + (
                    2
                    if record.field_name is None
                    else _compact_json_string_size(record.field_name) - 2
                )
            )
        else:  # pragma: no cover - the extraction record set is closed
            raise TypeError("unsupported form source report record")
        self.current_record_bytes[type(record)] += size
        self.current_record_counts[type(record)] += 1
        self.all_record_bytes += size
        if self.all_record_bytes > MAX_REPORT_BYTES:
            raise ValueError("form source report limit exceeded")

    def account_page(self, page: FormSourcePage) -> None:
        page_size = (
            157
            + len(str(page.page_index))
            - 1
            + _compact_json_float_size(page.height)
            - 3
            + _compact_json_float_size(page.width)
            - 3
            + _compact_json_string_size(page.interactivity)
            - 2
            + _compact_json_string_array_size(page.concern_codes)
            - 2
        )
        for record_type in (
            SourceAnnotation,
            SourceChar,
            SourceInteractiveControl,
            SourceVector,
            SourceWord,
        ):
            page_size += self.current_record_bytes[record_type]
            page_size += max(
                0,
                self.current_record_counts[record_type] - 1,
            )
        self.page_payload_bytes += page_size
        self.page_count += 1
        self.current_record_bytes.clear()
        self.current_record_counts.clear()
        if (
            self.page_payload_bytes + max(0, self.page_count - 1)
            > MAX_REPORT_BYTES
        ):
            raise ValueError("form source report limit exceeded")


class _ProjectionPageLimitError(ValueError):
    def __init__(self, page_index: int) -> None:
        super().__init__("form projection page comparison limit exceeded")
        self.page_index = page_index


class _ProjectionDocumentLimitError(ValueError):
    pass


@dataclass(slots=True)
class _ProjectionBudget:
    started_at: float
    comparisons_by_page: dict[int, int]

    def check_deadline(self) -> None:
        if time.perf_counter() - self.started_at > DEADLINE_SECONDS:
            raise TimeoutError("form projection exceeded its deadline")

    def begin_comparisons(self, page_index: int) -> int:
        self.check_deadline()
        return self.comparisons_by_page.get(page_index, 0)

    def account_comparisons(self, page_index: int, count: int) -> None:
        if count <= 0:
            return
        current = self.comparisons_by_page.get(page_index, 0)
        updated = current + count
        if updated > MAX_COMPARISONS_PER_PAGE:
            raise _ProjectionPageLimitError(page_index)
        self.comparisons_by_page[page_index] = updated
        if current // 256 != updated // 256:
            self.check_deadline()

    def checkpoint(
        self,
        page_index: int,
        baseline: int,
        local_comparisons: int,
    ) -> None:
        current = self.comparisons_by_page.get(page_index, 0)
        if current < baseline:
            raise RuntimeError("form projection comparison ledger regressed")
        if current + local_comparisons > MAX_COMPARISONS_PER_PAGE:
            raise _ProjectionPageLimitError(page_index)
        if local_comparisons % 256 == 0:
            self.check_deadline()

    def commit_comparisons(
        self,
        page_index: int,
        baseline: int,
        local_comparisons: int,
    ) -> None:
        self.checkpoint(page_index, baseline, local_comparisons)
        self.comparisons_by_page[page_index] = (
            self.comparisons_by_page.get(page_index, 0)
            + local_comparisons
        )
        self.check_deadline()


_PROJECTION_BUDGET: ContextVar[_ProjectionBudget | None] = ContextVar(
    "form_projection_budget",
    default=None,
)
_PROJECTION_CANONICAL_OWNERS: ContextVar[
    dict[int, frozenset[str]] | None
] = ContextVar("form_projection_canonical_owners", default=None)


@dataclass(frozen=True, slots=True)
class _ProjectionIRLookup:
    elements: Mapping[str, ElementRecord]
    bboxes: Mapping[str, IRBoundingBox]
    pages_by_index: Mapping[int, Any]


_PROJECTION_IR_LOOKUPS: ContextVar[
    dict[int, _ProjectionIRLookup] | None
] = ContextVar("form_projection_ir_lookups", default=None)


@dataclass(frozen=True, slots=True)
class _PresentationCandidate:
    source_order: int
    element: ElementRecord
    legacy: Mapping[str, Any]
    bbox: tuple[float, float, float, float]


@dataclass(slots=True)
class _ProjectionPresentationIndex:
    page_index: int
    records: tuple[_PresentationCandidate, ...]
    records_by_top: tuple[_PresentationCandidate, ...]
    tops: tuple[float, ...]
    records_by_bottom: tuple[_PresentationCandidate, ...]
    bottoms: tuple[float, ...]
    vertical_cache: dict[
        tuple[float, float],
        tuple[_PresentationCandidate, ...],
    ]
    intersection_cache: dict[
        tuple[float, float, float, float],
        tuple[_PresentationCandidate, ...],
    ]
    dense_table_cache: dict[
        tuple[float, float],
        tuple[float, float, float, float] | None,
    ]

    @classmethod
    def build(
        cls,
        ir: DocumentIR,
        page_index: int,
    ) -> "_ProjectionPresentationIndex":
        lookup = _projection_ir_lookup(ir)
        page = lookup.pages_by_index.get(page_index)
        if page is None:
            return cls(
                page_index=page_index,
                records=(),
                records_by_top=(),
                tops=(),
                records_by_bottom=(),
                bottoms=(),
                vertical_cache={},
                intersection_cache={},
                dense_table_cache={},
            )
        _charge_projection_comparisons(
            page_index,
            len(page.presentation_element_ids),
        )
        records: list[_PresentationCandidate] = []
        budget = _PROJECTION_BUDGET.get()
        for source_order, element_id in enumerate(
            page.presentation_element_ids
        ):
            element = lookup.elements.get(element_id)
            legacy = _legacy_item(element) if element is not None else None
            bbox = (
                _bbox_tuple(element, lookup.bboxes)
                if element is not None
                else None
            )
            if element is not None and legacy is not None and bbox is not None:
                records.append(
                    _PresentationCandidate(
                        source_order=source_order,
                        element=element,
                        legacy=legacy,
                        bbox=bbox,
                    )
                )
            if budget is not None and source_order % 256 == 0:
                budget.check_deadline()
        by_top = tuple(
            sorted(
                records,
                key=lambda value: (
                    value.bbox[1],
                    value.source_order,
                ),
            )
        )
        by_bottom = tuple(
            sorted(
                records,
                key=lambda value: (
                    value.bbox[1] + value.bbox[3],
                    value.source_order,
                ),
            )
        )
        return cls(
            page_index=page_index,
            records=tuple(records),
            records_by_top=by_top,
            tops=tuple(value.bbox[1] for value in by_top),
            records_by_bottom=by_bottom,
            bottoms=tuple(
                value.bbox[1] + value.bbox[3]
                for value in by_bottom
            ),
            vertical_cache={},
            intersection_cache={},
            dense_table_cache={},
        )

    def vertical_candidates(
        self,
        top: float,
        bottom: float,
    ) -> tuple[_PresentationCandidate, ...]:
        cache_key = (top, bottom)
        if cache_key in self.vertical_cache:
            return self.vertical_cache[cache_key]
        upper = bisect_right(self.tops, bottom)
        lower = bisect_left(self.bottoms, top)
        prefix_count = upper
        suffix_count = len(self.records_by_bottom) - lower
        _charge_projection_comparisons(
            self.page_index,
            2 + min(prefix_count, suffix_count),
        )
        if prefix_count <= suffix_count:
            result = tuple(
                value
                for value in self.records_by_top[:upper]
                if value.bbox[1] + value.bbox[3] >= top
            )
        else:
            result = tuple(
                value
                for value in self.records_by_bottom[lower:]
                if value.bbox[1] <= bottom
            )
        result = tuple(sorted(result, key=lambda value: value.source_order))
        self.vertical_cache[cache_key] = result
        return result

    def intersecting(
        self,
        bbox: tuple[float, float, float, float],
    ) -> tuple[_PresentationCandidate, ...]:
        if bbox in self.intersection_cache:
            return self.intersection_cache[bbox]
        candidates = self.vertical_candidates(
            bbox[1],
            bbox[1] + bbox[3],
        )
        _charge_projection_comparisons(
            self.page_index,
            len(candidates),
        )
        result = tuple(
            value
            for value in candidates
            if _intersects(value.bbox, bbox)
        )
        self.intersection_cache[bbox] = result
        return result

    def dense_table_bbox(
        self,
        page_width: float,
        page_height: float,
    ) -> tuple[float, float, float, float] | None:
        cache_key = (page_width, page_height)
        if cache_key in self.dense_table_cache:
            return self.dense_table_cache[cache_key]
        _charge_projection_comparisons(
            self.page_index,
            len(self.records),
        )
        candidates = tuple(
            value.bbox
            for value in self.records
            if value.element.type.casefold() == "table"
            and value.bbox[2] >= 0.8 * page_width
            and value.bbox[3] >= 0.25 * page_height
        )
        result = max(
            candidates,
            key=lambda value: value[2] * value[3],
            default=None,
        )
        self.dense_table_cache[cache_key] = result
        return result


_PROJECTION_PRESENTATION_INDEXES: ContextVar[
    dict[tuple[int, int], _ProjectionPresentationIndex] | None
] = ContextVar("form_projection_presentation_indexes", default=None)


def _projection_ir_lookup(ir: DocumentIR) -> _ProjectionIRLookup:
    cache = _PROJECTION_IR_LOOKUPS.get()
    cache_key = id(ir)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    budget = _PROJECTION_BUDGET.get()
    elements: dict[str, ElementRecord] = {}
    for index, element in enumerate(ir.elements):
        elements[element.id] = element
        if budget is not None and index % 256 == 0:
            budget.check_deadline()
    bboxes: dict[str, IRBoundingBox] = {}
    for index, bbox in enumerate(ir.bboxes):
        bboxes[bbox.id] = bbox
        if budget is not None and index % 256 == 0:
            budget.check_deadline()
    pages_by_index: dict[int, Any] = {}
    for index, page in enumerate(ir.pages):
        pages_by_index[page.page_index] = page
        if budget is not None and index % 256 == 0:
            budget.check_deadline()
    lookup = _ProjectionIRLookup(
        elements=elements,
        bboxes=bboxes,
        pages_by_index=pages_by_index,
    )
    if budget is not None:
        budget.check_deadline()
    if cache is not None:
        cache[cache_key] = lookup
    return lookup


def _projection_presentation_index(
    ir: DocumentIR,
    page_index: int,
) -> _ProjectionPresentationIndex:
    cache = _PROJECTION_PRESENTATION_INDEXES.get()
    cache_key = (id(ir), page_index)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    index = _ProjectionPresentationIndex.build(ir, page_index)
    if cache is not None:
        cache[cache_key] = index
    return index


def _charge_projection_comparisons(page_index: int, count: int) -> None:
    if count <= 0:
        return
    budget = _PROJECTION_BUDGET.get()
    if budget is None:
        return
    budget.account_comparisons(page_index, count)


@dataclass(frozen=True, slots=True)
class _SourceCharIndex:
    chars: tuple[SourceChar, ...]
    tops: tuple[float, ...]

    @classmethod
    def build(
        cls,
        chars: Sequence[SourceChar],
        *,
        budget: _ExtractionBudget,
    ) -> "_SourceCharIndex":
        ordered = tuple(
            sorted(chars, key=lambda char: (char.top, char.x0, char.index))
        )
        budget.check_deadline()
        return cls(
            chars=ordered,
            tops=tuple(char.top for char in ordered),
        )

    def contained_indexes(
        self,
        *,
        x0: float,
        top: float,
        x1: float,
        bottom: float,
        budget: _ExtractionBudget,
    ) -> tuple[int, ...]:
        lower = bisect_left(self.tops, top - 0.05)
        upper = bisect_right(self.tops, bottom + 0.05)
        owned: list[int] = []
        for index in range(lower, upper):
            char = self.chars[index]
            budget.account_comparison()
            if (
                char.x0 >= x0 - 0.05
                and char.x1 <= x1 + 0.05
                and char.top >= top - 0.05
                and char.bottom <= bottom + 0.05
            ):
                owned.append(char.index)
        return tuple(owned)


@dataclass(frozen=True, slots=True)
class _ProjectionSpatialIndex:
    page_index: int
    chars_by_y: Mapping[int, tuple[SourceChar, ...]]
    char_centers_by_y: Mapping[int, tuple[float, ...]]
    words_by_y: Mapping[int, tuple[SourceWord, ...]]
    word_centers_by_y: Mapping[int, tuple[float, ...]]
    intersecting_chars_by_y_x0: Mapping[int, tuple[SourceChar, ...]]
    intersecting_char_x0s_by_y: Mapping[int, tuple[float, ...]]
    intersecting_chars_by_y_x1: Mapping[int, tuple[SourceChar, ...]]
    intersecting_char_x1s_by_y: Mapping[int, tuple[float, ...]]
    long_intersecting_chars: tuple[SourceChar, ...]
    contained_char_cache: dict[
        tuple[tuple[float, float, float, float], float],
        tuple[SourceChar, ...],
    ]
    centered_char_cache: dict[
        tuple[tuple[float, float, float, float], float],
        tuple[SourceChar, ...],
    ]
    centered_word_cache: dict[
        tuple[tuple[float, float, float, float], float],
        tuple[SourceWord, ...],
    ]
    intersecting_char_cache: dict[
        tuple[float, float, float, float],
        tuple[SourceChar, ...],
    ]

    @classmethod
    def build(cls, page: FormSourcePage) -> "_ProjectionSpatialIndex":
        char_buckets: dict[int, list[SourceChar]] = {}
        word_buckets: dict[int, list[SourceWord]] = {}
        intersecting_char_buckets: dict[int, list[SourceChar]] = {}
        long_intersecting_chars: list[SourceChar] = []
        budget = _PROJECTION_BUDGET.get()
        _charge_projection_comparisons(
            page.page_index,
            len(page.chars) + len(page.words),
        )
        for index, char in enumerate(page.chars):
            key = math.floor(((char.top + char.bottom) / 2) / 4)
            char_buckets.setdefault(key, []).append(char)
            y_bucket_range = cls._bucket_range(
                char.top,
                char.bottom,
            )
            if len(y_bucket_range) > _MAX_SPATIAL_BUCKET_SPAN:
                _charge_projection_comparisons(page.page_index, 1)
                long_intersecting_chars.append(char)
            else:
                _charge_projection_comparisons(
                    page.page_index,
                    len(y_bucket_range),
                )
                for y_bucket in y_bucket_range:
                    intersecting_char_buckets.setdefault(
                        y_bucket,
                        [],
                    ).append(char)
            if budget is not None and index % 256 == 0:
                budget.check_deadline()
        for index, word in enumerate(page.words):
            key = math.floor(((word.top + word.bottom) / 2) / 4)
            word_buckets.setdefault(key, []).append(word)
            if budget is not None and index % 256 == 0:
                budget.check_deadline()
        if budget is not None:
            budget.check_deadline()
        ordered_chars_by_y = {
            key: tuple(
                sorted(
                    values,
                    key=lambda value: (
                        (value.x0 + value.x1) / 2,
                        value.index,
                    ),
                )
            )
            for key, values in char_buckets.items()
        }
        ordered_words_by_y = {
            key: tuple(
                sorted(
                    values,
                    key=lambda value: (
                        (value.x0 + value.x1) / 2,
                        value.index,
                    ),
                )
            )
            for key, values in word_buckets.items()
        }
        intersecting_by_x0 = {
            key: tuple(
                sorted(
                    values,
                    key=lambda value: (value.x0, value.index),
                )
            )
            for key, values in intersecting_char_buckets.items()
        }
        intersecting_by_x1 = {
            key: tuple(
                sorted(
                    values,
                    key=lambda value: (value.x1, value.index),
                )
            )
            for key, values in intersecting_char_buckets.items()
        }
        return cls(
            page_index=page.page_index,
            chars_by_y=ordered_chars_by_y,
            char_centers_by_y={
                key: tuple(
                    (value.x0 + value.x1) / 2 for value in values
                )
                for key, values in ordered_chars_by_y.items()
            },
            words_by_y=ordered_words_by_y,
            word_centers_by_y={
                key: tuple(
                    (value.x0 + value.x1) / 2 for value in values
                )
                for key, values in ordered_words_by_y.items()
            },
            intersecting_chars_by_y_x0=intersecting_by_x0,
            intersecting_char_x0s_by_y={
                key: tuple(value.x0 for value in values)
                for key, values in intersecting_by_x0.items()
            },
            intersecting_chars_by_y_x1=intersecting_by_x1,
            intersecting_char_x1s_by_y={
                key: tuple(value.x1 for value in values)
                for key, values in intersecting_by_x1.items()
            },
            long_intersecting_chars=tuple(long_intersecting_chars),
            contained_char_cache={},
            centered_char_cache={},
            centered_word_cache={},
            intersecting_char_cache={},
        )

    @staticmethod
    def _bucket_range(top: float, bottom: float) -> range:
        start = math.floor(top / 4)
        stop = math.floor(bottom / 4) + 1
        if stop < start:
            raise ValueError("form projection bbox has inverted geometry")
        if stop - start > MAX_COMPARISONS_PER_PAGE:
            raise ValueError("form projection spatial span limit exceeded")
        return range(start, stop)

    def chars_contained(
        self,
        bbox: tuple[float, float, float, float],
        *,
        tolerance: float,
    ) -> tuple[SourceChar, ...]:
        cache_key = (bbox, tolerance)
        if cache_key in self.contained_char_cache:
            return self.contained_char_cache[cache_key]
        x, y, width, height = bbox
        bucket_range = self._bucket_range(
            y - tolerance,
            y + height + tolerance,
        )
        _charge_projection_comparisons(
            self.page_index,
            2 * len(bucket_range),
        )
        candidate_records: list[SourceChar] = []
        for y_key in bucket_range:
            values = self.chars_by_y.get(y_key, ())
            centers = self.char_centers_by_y.get(y_key, ())
            lower = bisect_left(centers, x - tolerance)
            upper = bisect_right(centers, x + width + tolerance)
            _charge_projection_comparisons(
                self.page_index,
                upper - lower,
            )
            candidate_records.extend(values[lower:upper])
        candidates = tuple(candidate_records)
        result = tuple(
            char
            for char in candidates
            if char.x0 >= x - tolerance
            and char.x1 <= x + width + tolerance
            and char.top >= y - tolerance
            and char.bottom <= y + height + tolerance
        )
        self.contained_char_cache[cache_key] = result
        return result

    def chars_centered(
        self,
        bbox: tuple[float, float, float, float],
        *,
        above: float,
    ) -> tuple[SourceChar, ...]:
        cache_key = (bbox, above)
        if cache_key in self.centered_char_cache:
            return self.centered_char_cache[cache_key]
        x, y, width, height = bbox
        minimum_y = y - above - 0.2
        maximum_y = y + height + 0.3
        bucket_range = self._bucket_range(minimum_y, maximum_y)
        _charge_projection_comparisons(
            self.page_index,
            2 * len(bucket_range),
        )
        candidate_records = []
        for y_key in bucket_range:
            values = self.chars_by_y.get(y_key, ())
            centers = self.char_centers_by_y.get(y_key, ())
            lower = bisect_left(centers, x - 0.2)
            upper = bisect_right(centers, x + width + 0.2)
            _charge_projection_comparisons(
                self.page_index,
                upper - lower,
            )
            candidate_records.extend(values[lower:upper])
        candidates = tuple(candidate_records)
        result = tuple(
            char
            for char in candidates
            if x - 0.2 <= (char.x0 + char.x1) / 2 <= x + width + 0.2
            and minimum_y <= (char.top + char.bottom) / 2 <= maximum_y
        )
        self.centered_char_cache[cache_key] = result
        return result

    def words_centered(
        self,
        bbox: tuple[float, float, float, float],
        *,
        above: float,
    ) -> tuple[SourceWord, ...]:
        cache_key = (bbox, above)
        if cache_key in self.centered_word_cache:
            return self.centered_word_cache[cache_key]
        x, y, width, height = bbox
        minimum_y = y - above - 0.2
        maximum_y = y + height + 0.2
        bucket_range = self._bucket_range(minimum_y, maximum_y)
        _charge_projection_comparisons(
            self.page_index,
            2 * len(bucket_range),
        )
        candidate_words: list[SourceWord] = []
        for y_key in bucket_range:
            values = self.words_by_y.get(y_key, ())
            centers = self.word_centers_by_y.get(y_key, ())
            lower = bisect_left(centers, x - 0.2)
            upper = bisect_right(centers, x + width + 0.2)
            _charge_projection_comparisons(
                self.page_index,
                upper - lower,
            )
            candidate_words.extend(values[lower:upper])
        candidates = tuple(candidate_words)
        result = tuple(
            word
            for word in candidates
            if x - 0.2 <= (word.x0 + word.x1) / 2 <= x + width + 0.2
            and minimum_y <= (word.top + word.bottom) / 2 <= maximum_y
        )
        self.centered_word_cache[cache_key] = result
        return result

    def chars_intersecting(
        self,
        bbox: tuple[float, float, float, float],
    ) -> tuple[SourceChar, ...]:
        if bbox in self.intersecting_char_cache:
            return self.intersecting_char_cache[bbox]
        x, y, width, height = bbox
        right = x + width
        bottom = y + height
        y_bucket_range = self._bucket_range(y, bottom)
        _charge_projection_comparisons(
            self.page_index,
            4 * len(y_bucket_range),
        )
        candidates_by_index: dict[int, SourceChar] = {}
        for y_key in y_bucket_range:
            by_x0 = self.intersecting_chars_by_y_x0.get(y_key, ())
            x0s = self.intersecting_char_x0s_by_y.get(y_key, ())
            prefix_end = bisect_left(x0s, right)
            by_x1 = self.intersecting_chars_by_y_x1.get(y_key, ())
            x1s = self.intersecting_char_x1s_by_y.get(y_key, ())
            suffix_start = bisect_right(x1s, x)
            if prefix_end <= len(by_x1) - suffix_start:
                selected = by_x0
                selected_start = 0
                selected_end = prefix_end
            else:
                selected = by_x1
                selected_start = suffix_start
                selected_end = len(by_x1)
            _charge_projection_comparisons(
                self.page_index,
                selected_end - selected_start,
            )
            for selected_index in range(selected_start, selected_end):
                char = selected[selected_index]
                candidates_by_index[char.index] = char
        _charge_projection_comparisons(
            self.page_index,
            len(self.long_intersecting_chars),
        )
        for char in self.long_intersecting_chars:
            candidates_by_index[char.index] = char
        candidates = tuple(
            candidates_by_index[index]
            for index in sorted(candidates_by_index)
        )
        _charge_projection_comparisons(
            self.page_index,
            len(candidates),
        )
        result = tuple(
            char
            for char in candidates
            if char.x0 < right
            and char.x1 > x
            and char.top < bottom
            and char.bottom > y
        )
        self.intersecting_char_cache[bbox] = result
        return result


@dataclass(frozen=True, slots=True)
class _ProjectionVectorIndex:
    page_index: int
    rects_by_area: tuple[SourceVector, ...]
    rects_by_origin: Mapping[tuple[int, int], tuple[SourceVector, ...]]
    rects_by_top: tuple[SourceVector, ...]
    rect_tops: tuple[float, ...]
    vectors_by_top: tuple[SourceVector, ...]
    vector_tops: tuple[float, ...]
    vectors_by_bottom: tuple[SourceVector, ...]
    vector_bottoms: tuple[float, ...]
    vectors_by_identity: Mapping[tuple[str, int], SourceVector]
    matching_cache: dict[
        tuple[float, float, float, float],
        tuple[SourceVector, ...],
    ]
    container_cache: dict[
        tuple[float, float, float, float],
        SourceVector | None,
    ]
    adjacent_cache: dict[
        tuple[float, float, float],
        tuple[SourceVector, ...],
    ]
    interior_cache: dict[
        tuple[float, float, float, float],
        tuple[SourceVector, ...],
    ]

    @classmethod
    def build(cls, page: FormSourcePage) -> "_ProjectionVectorIndex":
        _charge_projection_comparisons(
            page.page_index,
            len(page.vectors),
        )
        rects = tuple(
            vector for vector in page.vectors if vector.kind == "rect"
        )
        by_origin: dict[tuple[int, int], list[SourceVector]] = {}
        budget = _PROJECTION_BUDGET.get()
        for index, vector in enumerate(rects):
            by_origin.setdefault(
                (
                    math.floor(vector.x0 / 16.0),
                    math.floor(vector.top / 16.0),
                ),
                [],
            ).append(vector)
            if budget is not None and index % 256 == 0:
                budget.check_deadline()
        by_top = tuple(
            sorted(rects, key=lambda vector: (vector.top, vector.index))
        )
        all_by_top = tuple(
            sorted(
                page.vectors,
                key=lambda vector: (
                    vector.top,
                    vector.index,
                    vector.kind,
                ),
            )
        )
        all_by_bottom = tuple(
            sorted(
                page.vectors,
                key=lambda vector: (
                    vector.bottom,
                    vector.index,
                    vector.kind,
                ),
            )
        )
        return cls(
            page_index=page.page_index,
            rects_by_area=tuple(
                sorted(
                    rects,
                    key=lambda vector: (
                        (vector.x1 - vector.x0)
                        * (vector.bottom - vector.top),
                        vector.index,
                    ),
                )
            ),
            rects_by_origin={
                key: tuple(values) for key, values in by_origin.items()
            },
            rects_by_top=by_top,
            rect_tops=tuple(vector.top for vector in by_top),
            vectors_by_top=all_by_top,
            vector_tops=tuple(vector.top for vector in all_by_top),
            vectors_by_bottom=all_by_bottom,
            vector_bottoms=tuple(
                vector.bottom for vector in all_by_bottom
            ),
            vectors_by_identity={
                (vector.kind, vector.index): vector
                for vector in page.vectors
            },
            matching_cache={},
            container_cache={},
            adjacent_cache={},
            interior_cache={},
        )

    def matching_bbox(
        self,
        bbox: tuple[float, float, float, float],
    ) -> tuple[SourceVector, ...]:
        if bbox in self.matching_cache:
            return self.matching_cache[bbox]
        x, y, width, height = bbox
        x_buckets = range(
            (_millipoints(x) - 150) // 16_000,
            (_millipoints(x) + 150) // 16_000 + 1,
        )
        y_buckets = range(
            (_millipoints(y) - 150) // 16_000,
            (_millipoints(y) + 150) // 16_000 + 1,
        )
        nearby = tuple(
            vector
            for x_bucket in x_buckets
            for y_bucket in y_buckets
            for vector in self.rects_by_origin.get(
                (x_bucket, y_bucket),
                (),
            )
        )
        _charge_projection_comparisons(
            self.page_index,
            len(x_buckets) * len(y_buckets) + len(nearby),
        )
        result = tuple(
            vector
            for vector in nearby
            if _within_points(vector.x0, x)
            and _within_points(vector.top, y)
            and _within_points(vector.x1, x + width)
            and _within_points(vector.bottom, y + height)
        )
        self.matching_cache[bbox] = result
        return result

    def smallest_container(
        self,
        bbox: tuple[float, float, float, float],
    ) -> SourceVector | None:
        if bbox in self.container_cache:
            return self.container_cache[bbox]
        x, y, width, height = bbox
        budget = _PROJECTION_BUDGET.get()
        for index, vector in enumerate(self.rects_by_area):
            _charge_projection_comparisons(self.page_index, 1)
            if (
                _at_most_with_tolerance(vector.x0, x)
                and _at_most_with_tolerance(vector.top, y)
                and _at_least_with_tolerance(vector.x1, x + width)
                and _at_least_with_tolerance(
                    vector.bottom,
                    y + height,
                )
            ):
                self.container_cache[bbox] = vector
                return vector
            if budget is not None and index % 256 == 0:
                budget.check_deadline()
        self.container_cache[bbox] = None
        return None

    def adjacent_at_top(
        self,
        coordinate: float,
        start: float,
        end: float,
    ) -> tuple[SourceVector, ...]:
        cache_key = (coordinate, start, end)
        if cache_key in self.adjacent_cache:
            return self.adjacent_cache[cache_key]
        lower = bisect_left(self.rect_tops, coordinate - 0.1505)
        upper = bisect_right(self.rect_tops, coordinate + 0.1505)
        candidates = self.rects_by_top[lower:upper]
        _charge_projection_comparisons(
            self.page_index,
            2 + len(candidates),
        )
        result = tuple(
            vector
            for vector in candidates
            if _within_points(vector.top, coordinate)
            and vector.x0 <= end - 0.5
            and vector.x1 >= start + 0.5
        )
        self.adjacent_cache[cache_key] = result
        return result

    def inside(
        self,
        bbox: tuple[float, float, float, float],
    ) -> tuple[SourceVector, ...]:
        if bbox in self.interior_cache:
            return self.interior_cache[bbox]
        x, y, width, height = bbox
        right = x + width
        bottom = y + height
        upper = bisect_right(self.vector_tops, bottom)
        lower = bisect_left(self.vector_bottoms, y)
        prefix_count = upper
        suffix_count = len(self.vectors_by_bottom) - lower
        candidates = (
            self.vectors_by_top[:upper]
            if prefix_count <= suffix_count
            else self.vectors_by_bottom[lower:]
        )
        _charge_projection_comparisons(
            self.page_index,
            2 + len(candidates),
        )
        result_values: list[SourceVector] = []
        for vector in candidates:
            horizontal_span = vector.x1 - vector.x0
            vertical_span = vector.bottom - vector.top
            horizontal_overlap = (
                min(vector.x1, right) - max(vector.x0, x)
            )
            vertical_overlap = (
                min(vector.bottom, bottom) - max(vector.top, y)
            )
            line_intersects = (
                horizontal_span > 0.01
                and vertical_span <= 0.01
                and horizontal_overlap > 0.01
                and y <= (vector.top + vector.bottom) / 2 <= bottom
            ) or (
                vertical_span > 0.01
                and horizontal_span <= 0.01
                and vertical_overlap > 0.01
                and x <= (vector.x0 + vector.x1) / 2 <= right
            )
            unfilled_rect_intersects = (
                vector.kind == "rect"
                and not vector.fill
                and (
                    (
                        x <= vector.x0 <= right
                        or x <= vector.x1 <= right
                    )
                    and vertical_overlap > 0.01
                    or (
                        y <= vector.top <= bottom
                        or y <= vector.bottom <= bottom
                    )
                    and horizontal_overlap > 0.01
                )
            )
            area_intersects = (
                (vector.kind != "rect" or vector.fill)
                and horizontal_span > 0.01
                and vertical_span > 0.01
                and horizontal_overlap > 0.01
                and vertical_overlap > 0.01
            )
            if (
                line_intersects
                or unfilled_rect_intersects
                or area_intersects
            ):
                result_values.append(vector)
        result = tuple(result_values)
        self.interior_cache[bbox] = result
        return result


_PROJECTION_SPATIAL_INDEXES: ContextVar[
    dict[int, _ProjectionSpatialIndex] | None
] = ContextVar("form_projection_spatial_indexes", default=None)
_SPATIAL_CHAR_RESULTS: ContextVar[dict[tuple[Any, ...], Any] | None] = (
    ContextVar("form_projection_spatial_char_results", default=None)
)
_PROJECTION_VECTOR_INDEXES: ContextVar[
    dict[int, _ProjectionVectorIndex] | None
] = ContextVar("form_projection_vector_indexes", default=None)


def _projection_spatial_index(
    page: FormSourcePage,
) -> _ProjectionSpatialIndex:
    cache = _PROJECTION_SPATIAL_INDEXES.get()
    page_key = id(page)
    if cache is not None and page_key in cache:
        return cache[page_key]
    index = _ProjectionSpatialIndex.build(page)
    if cache is not None:
        cache[page_key] = index
    return index


def _projection_vector_index(page: FormSourcePage) -> _ProjectionVectorIndex:
    cache = _PROJECTION_VECTOR_INDEXES.get()
    page_key = id(page)
    if cache is not None and page_key in cache:
        return cache[page_key]
    index = _ProjectionVectorIndex.build(page)
    if cache is not None:
        cache[page_key] = index
    return index


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
    )


def _bounded_public_string(value: str, *, allow_whitespace: bool = False) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value.encode("utf-8")) <= _ID_LIMIT
        and (allow_whitespace or bool(value.strip()))
    )


def _unique_strings(values: Sequence[str], *, max_bytes: int = _ID_LIMIT) -> bool:
    return len(values) == len(set(values)) and all(
        isinstance(value, str)
        and bool(value.strip())
        and len(value.encode("utf-8")) <= max_bytes
        for value in values
    )


def _bounded_text_value(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value.encode("utf-8")) <= MAX_TEXT_BYTES
    )


class FormBBox(_StrictModel):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["pt"] = "pt"


class CharacterRangeRef(_StrictModel):
    kind: Literal["character_range"]
    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> "CharacterRangeRef":
        if self.start >= self.end:
            raise ValueError("character range must be nonempty")
        return self


class IndexedSourceRef(_StrictModel):
    kind: Literal["line", "rect"]
    index: int = Field(ge=0)


class ObjectSourceRef(_StrictModel):
    kind: Literal["field", "widget", "annotation"]
    object_ref_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


SourceObjectRef = CharacterRangeRef | IndexedSourceRef | ObjectSourceRef


class ConfidenceDimension(_StrictModel):
    score: float | None = Field(default=None, ge=0, le=1)
    unavailable_reason: Literal[
        "not_calibrated",
        "not_applicable",
        "source_state_unavailable",
        "transcription_not_applicable",
    ] | None = None

    @model_validator(mode="after")
    def one_value(self) -> "ConfidenceDimension":
        if (self.score is None) == (self.unavailable_reason is None):
            raise ValueError("confidence dimension requires exactly one outcome")
        return self

    @model_serializer(mode="plain")
    def serialize_dimension(self) -> dict[str, float | str]:
        if self.score is not None:
            return {"score": self.score}
        assert self.unavailable_reason is not None
        return {"unavailable_reason": self.unavailable_reason}


class ConfidenceDimensions(_StrictModel):
    geometry: ConfidenceDimension
    role: ConfidenceDimension
    transcription: ConfidenceDimension
    state: ConfidenceDimension


class FormRelationship(_StrictModel):
    id: str
    type: Literal[
        "contains",
        "label_of",
        "value_of",
        "control_of",
        "key_of",
        "form_overlay_of",
    ]
    source_id: str
    target_id: str
    evidence_ids: list[str] = Field(max_length=64)
    canonical_inert: Literal[True]

    @model_validator(mode="after")
    def validate_relationship(self) -> "FormRelationship":
        if not all(
            _bounded_public_string(value)
            for value in (self.id, self.source_id, self.target_id)
        ) or not _unique_strings(self.evidence_ids):
            raise ValueError("form relationship identity is invalid")
        return self


class _PublicRecord(_StrictModel):
    id: str
    element_id: str
    page_index: int = Field(ge=1)
    bbox: FormBBox
    evidence_methods: list[
        Literal["native", "vector", "embedded", "recovered", "derived"]
    ] = Field(min_length=1, max_length=5)
    source_objects: list[SourceObjectRef] = Field(min_length=1, max_length=64)
    confidence_dimensions: ConfidenceDimensions
    concern_codes: list[str] = Field(max_length=MAX_FORM_CONCERNS_PER_GROUP)
    relationship_ids: list[str]

    @model_validator(mode="after")
    def validate_common_record(self) -> "_PublicRecord":
        if not all(
            _bounded_public_string(value) for value in (self.id, self.element_id)
        ):
            raise ValueError("form record identity is invalid")
        method_order = ["native", "vector", "embedded", "recovered", "derived"]
        if self.evidence_methods != [
            method for method in method_order if method in self.evidence_methods
        ]:
            raise ValueError("form evidence methods are not canonical")
        source_identities = [
            json.dumps(
                value.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
            for value in self.source_objects
        ]
        if len(source_identities) != len(set(source_identities)):
            raise ValueError("form source identities must be unique")
        if not _unique_strings(self.concern_codes) or not set(
            self.concern_codes
        ).issubset(_ALLOWED_CONCERNS):
            raise ValueError("form concern codes are invalid")
        if not _unique_strings(self.relationship_ids):
            raise ValueError("form relationship backlinks are invalid")
        return self


class PublicFormGroup(_PublicRecord):
    relationship_ids: list[str] = Field(min_length=1, max_length=2_816)
    group_key: str
    status: Literal["resolved", "unresolved"]
    interactivity: Literal["none", "static", "interactive", "mixed", "unknown"]
    canonical_mode: Literal["inert", "replace"]
    anchor_public_item_id: str
    anchor_element_id: str
    anchor_relationship_ids: list[str] = Field(max_length=1)
    contributor_public_item_ids: list[str] = Field(min_length=1, max_length=64)
    contributor_element_ids: list[str] = Field(min_length=1, max_length=64)
    field_ids: list[str] = Field(max_length=MAX_FORM_FIELDS_PER_GROUP)
    label_ids: list[str] = Field(max_length=MAX_FORM_LABELS_PER_GROUP)
    value_region_ids: list[str] = Field(
        max_length=MAX_FORM_VALUE_REGIONS_PER_GROUP
    )
    control_ids: list[str] = Field(max_length=MAX_FORM_CONTROLS_PER_GROUP)
    key_value_pair_ids: list[str] = Field(
        max_length=MAX_FORM_KEY_VALUE_PAIRS_PER_GROUP
    )

    @model_validator(mode="after")
    def validate_group(self) -> "PublicFormGroup":
        bounded = (
            self.group_key,
            self.anchor_public_item_id,
            self.anchor_element_id,
        )
        id_lists = (
            self.anchor_relationship_ids,
            self.contributor_public_item_ids,
            self.contributor_element_ids,
            self.field_ids,
            self.label_ids,
            self.value_region_ids,
            self.control_ids,
            self.key_value_pair_ids,
        )
        if not all(_bounded_public_string(value) for value in bounded) or not all(
            _unique_strings(values) for values in id_lists
        ):
            raise ValueError("form group identities are invalid")
        if len(self.contributor_public_item_ids) != len(
            self.contributor_element_ids
        ):
            raise ValueError("form contributors are not pairwise")
        public_anchor_indexes = [
            index
            for index, value in enumerate(self.contributor_public_item_ids)
            if value == self.anchor_public_item_id
        ]
        element_anchor_indexes = [
            index
            for index, value in enumerate(self.contributor_element_ids)
            if value == self.anchor_element_id
        ]
        if (
            len(public_anchor_indexes) != 1
            or public_anchor_indexes != element_anchor_indexes
            or self.element_id in self.contributor_element_ids
        ):
            raise ValueError("form group anchor custody is invalid")
        if not (self.field_ids or self.control_ids or self.key_value_pair_ids) or (
            self.key_value_pair_ids and (self.field_ids or self.control_ids)
        ):
            raise ValueError("form group role composition is invalid")
        return self


class PublicFormField(_PublicRecord):
    relationship_ids: list[str] = Field(min_length=4, max_length=323)
    group_id: str
    field_key: str
    label_ids: list[str] = Field(min_length=1, max_length=64)
    value_region_id: str
    control_ids: list[str] = Field(max_length=256)
    value: str | None
    value_state: Literal["empty", "present", "ambiguous", "not_applicable"]

    @model_validator(mode="after")
    def validate_field(self) -> "PublicFormField":
        if not all(
            _bounded_public_string(value)
            for value in (self.group_id, self.field_key, self.value_region_id)
        ) or not all(
            _unique_strings(values) for values in (self.label_ids, self.control_ids)
        ):
            raise ValueError("form field identities are invalid")
        if self.value_state == "present":
            if self.value is None or not _bounded_text_value(self.value):
                raise ValueError("present form field value is invalid")
        elif self.value is not None:
            raise ValueError("non-present form field value must be null")
        return self


class PublicFormLabel(_PublicRecord):
    relationship_ids: list[str] = Field(min_length=2, max_length=257)
    group_id: str
    label_role: Literal["field", "group", "control", "key"]
    text: str
    raw_text: str
    label_of_ids: list[str] = Field(max_length=256)
    key_of_ids: list[str] = Field(max_length=1)

    @model_validator(mode="after")
    def validate_label(self) -> "PublicFormLabel":
        if not _bounded_public_string(self.group_id) or not all(
            _bounded_text_value(value) for value in (self.text, self.raw_text)
        ) or not all(
            _unique_strings(values) for values in (self.label_of_ids, self.key_of_ids)
        ):
            raise ValueError("form label values are invalid")
        valid_cardinality = (
            self.label_role == "key"
            and not self.label_of_ids
            and len(self.key_of_ids) == 1
        ) or (
            self.label_role == "field"
            and bool(self.label_of_ids)
            and not self.key_of_ids
        ) or (
            self.label_role in {"group", "control"}
            and len(self.label_of_ids) == 1
            and not self.key_of_ids
        )
        if not valid_cardinality:
            raise ValueError("form label relationship cardinality is invalid")
        return self


class PublicFormValueRegion(_PublicRecord):
    relationship_ids: list[str] = Field(min_length=2, max_length=2)
    group_id: str
    owner_id: str
    excluded_label_ids: list[str] = Field(max_length=64)
    value: str | None
    value_state: Literal["empty", "present", "ambiguous", "not_applicable"]

    @model_validator(mode="after")
    def validate_value_region(self) -> "PublicFormValueRegion":
        if not all(
            _bounded_public_string(value) for value in (self.group_id, self.owner_id)
        ) or not _unique_strings(self.excluded_label_ids):
            raise ValueError("form value-region identities are invalid")
        if self.value_state == "present":
            if self.value is None or not _bounded_text_value(self.value):
                raise ValueError("present form value region is invalid")
        elif self.value is not None:
            raise ValueError("non-present form value region must be null")
        return self


class PublicFormControl(_PublicRecord):
    relationship_ids: list[str] = Field(min_length=2, max_length=3)
    group_id: str
    owner_field_id: str | None
    label_id: str | None
    control_type: Literal["checkbox", "radio"]
    state: Literal["checked", "unchecked", "ambiguous", "not_applicable"]
    origin: Literal["static_vector", "interactive_widget"]

    @model_validator(mode="after")
    def validate_control(self) -> "PublicFormControl":
        values = (self.group_id, self.owner_field_id, self.label_id)
        if not all(
            value is None or _bounded_public_string(value) for value in values
        ):
            raise ValueError("form control identities are invalid")
        return self


class PublicKeyValuePair(_PublicRecord):
    relationship_ids: list[str] = Field(min_length=5, max_length=5)
    group_id: str
    pair_key: str
    key_label_id: str
    value_region_id: str
    key: str
    value: str
    value_state: Literal["present"]
    key_source_item_id: str
    value_source_item_id: str

    @model_validator(mode="after")
    def validate_pair(self) -> "PublicKeyValuePair":
        identities = (
            self.group_id,
            self.pair_key,
            self.key_label_id,
            self.value_region_id,
            self.key_source_item_id,
            self.value_source_item_id,
        )
        if not all(_bounded_public_string(value) for value in identities) or not all(
            _bounded_text_value(value) for value in (self.key, self.value)
        ):
            raise ValueError("form key-value pair values are invalid")
        return self


@dataclass(frozen=True, slots=True)
class FormGroupRendering:
    group_element_id: str
    anchor_element_id: str
    canonical_mode: Literal["inert", "replace"]
    contributor_element_ids: tuple[str, ...]
    relationship_ids: tuple[str, ...]
    markdown: str
    text: str


@dataclass(frozen=True, slots=True)
class _RecordCandidate:
    token: str
    role: Literal[
        "group", "field", "label", "value_region", "control", "key_value_pair"
    ]
    key: str
    bbox: tuple[float, float, float, float]
    source_objects: tuple[_SourceIdentity, ...]
    data: Mapping[str, Any]
    concern_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _GroupCandidate:
    group_key: str
    page_index: int
    bbox: tuple[float, float, float, float]
    status: Literal["resolved", "unresolved"]
    interactivity: Literal["none", "static", "interactive", "mixed", "unknown"]
    canonical_mode: Literal["inert", "replace"]
    anchor_public_item_id: str
    anchor_element_id: str
    contributor_public_item_ids: tuple[str, ...]
    contributor_element_ids: tuple[str, ...]
    records: tuple[_RecordCandidate, ...]
    relationships: tuple[tuple[str, str, str], ...]
    source_objects: tuple[_SourceIdentity, ...]
    concern_codes: tuple[str, ...] = ()


@dataclass(slots=True)
class _ProjectionCandidateBudget:
    groups_by_page: Counter[int] = dataclass_field(default_factory=Counter)
    semantic_by_page: Counter[int] = dataclass_field(default_factory=Counter)
    relationships_by_page: Counter[int] = dataclass_field(
        default_factory=Counter
    )
    classes_by_page: Counter[tuple[int, str]] = dataclass_field(
        default_factory=Counter
    )
    group_count: int = 0
    semantic_count: int = 0
    relationship_count: int = 0
    class_counts: Counter[str] = dataclass_field(default_factory=Counter)

    def snapshot(self) -> tuple[Any, ...]:
        return (
            self.groups_by_page.copy(),
            self.semantic_by_page.copy(),
            self.relationships_by_page.copy(),
            self.classes_by_page.copy(),
            self.group_count,
            self.semantic_count,
            self.relationship_count,
            self.class_counts.copy(),
        )

    def restore(self, snapshot: tuple[Any, ...]) -> None:
        (
            self.groups_by_page,
            self.semantic_by_page,
            self.relationships_by_page,
            self.classes_by_page,
            self.group_count,
            self.semantic_count,
            self.relationship_count,
            self.class_counts,
        ) = snapshot

    def reserve(
        self,
        *,
        page_index: int,
        roles: Mapping[str, int],
        relationships: int,
    ) -> None:
        if any(
            roles.get(role, 0) > limit
            for role, limit in _FORM_GROUP_ROLE_LIMITS.items()
        ):
            raise _ProjectionPageLimitError(page_index)
        semantic_records = 1 + sum(roles.values())
        prospective_groups_page = self.groups_by_page[page_index] + 1
        prospective_semantic_page = (
            self.semantic_by_page[page_index] + semantic_records
        )
        prospective_relationships_page = (
            self.relationships_by_page[page_index] + relationships
        )
        prospective_classes_page = {
            role: self.classes_by_page[(page_index, role)]
            + roles.get(role, 0)
            for role in ("field", "control", "key_value_pair")
        }
        if (
            prospective_groups_page > MAX_FORM_GROUPS_PER_PAGE
            or prospective_semantic_page
            > MAX_FORM_SEMANTIC_RECORDS_PER_PAGE
            or prospective_relationships_page
            > MAX_FORM_RELATIONSHIPS_PER_PAGE
            or any(
                count > MAX_FORM_CLASS_RECORDS_PER_PAGE
                for count in prospective_classes_page.values()
            )
        ):
            raise _ProjectionPageLimitError(page_index)
        prospective_group_count = self.group_count + 1
        prospective_semantic_count = (
            self.semantic_count + semantic_records
        )
        prospective_relationship_count = (
            self.relationship_count + relationships
        )
        prospective_class_counts = {
            role: self.class_counts[role] + roles.get(role, 0)
            for role in ("field", "control", "key_value_pair")
        }
        if (
            prospective_group_count > MAX_FORM_GROUPS_PER_DOCUMENT
            or prospective_semantic_count
            > MAX_FORM_SEMANTIC_RECORDS_PER_DOCUMENT
            or prospective_relationship_count
            > MAX_FORM_RELATIONSHIPS_PER_DOCUMENT
            or any(
                count > MAX_FORM_CLASS_RECORDS_PER_DOCUMENT
                for count in prospective_class_counts.values()
            )
        ):
            raise _ProjectionDocumentLimitError(
                "form projection exceeded a document candidate limit"
            )
        self.groups_by_page[page_index] = prospective_groups_page
        self.semantic_by_page[page_index] = prospective_semantic_page
        self.relationships_by_page[
            page_index
        ] = prospective_relationships_page
        for role, count in prospective_classes_page.items():
            self.classes_by_page[(page_index, role)] = count
        self.group_count = prospective_group_count
        self.semantic_count = prospective_semantic_count
        self.relationship_count = prospective_relationship_count
        self.class_counts.update(
            {
                role: roles.get(role, 0)
                for role in ("field", "control", "key_value_pair")
            }
        )


_PROJECTION_CANDIDATE_BUDGET: ContextVar[
    _ProjectionCandidateBudget | None
] = ContextVar("form_projection_candidate_budget", default=None)


def _reserve_projection_candidate(
    *,
    page_index: int,
    roles: Mapping[str, int],
    relationships: int,
) -> None:
    budget = _PROJECTION_CANDIDATE_BUDGET.get()
    if budget is not None:
        budget.reserve(
            page_index=page_index,
            roles=roles,
            relationships=relationships,
        )


def form_processing_summary(
    metrics: Mapping[str, float] | None,
) -> dict[str, float]:
    """Return the bounded public timing summary for the enabled stage."""

    source = metrics or {}

    def timing(key: str) -> float:
        try:
            value = float(source.get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) and value >= 0 else 0.0

    extraction = timing("extraction_ms")
    projection = timing("projection_ms")
    total = max(extraction + projection, timing("total_ms"))
    return {
        "extraction_ms": round(extraction, 3),
        "projection_ms": round(projection, 3),
        "total_ms": round(total, 3),
    }


_PUBLIC_FORM_KEYS = frozenset(
    {
        "layout_forms_projected",
        "form_policy",
        "form_group",
        "form_fields",
        "form_labels",
        "form_value_regions",
        "form_controls",
        "form_key_value_pairs",
    }
)
_PUBLIC_FORM_RELATIONSHIP_TYPES = frozenset(
    {
        "contains",
        "label_of",
        "value_of",
        "control_of",
        "key_of",
        "form_overlay_of",
    }
)


def strip_form_semantics_public(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep US06-clean public predecessor.

    Existing relationship descriptors are preserved byte-for-byte in value
    and order; only descriptors carrying the exact US06 canonical-inert
    marker and one of the story's relationship types are removed.
    """

    cleaned = deepcopy(dict(document))
    pages = cleaned.get("pages")
    if not isinstance(pages, list):
        return cleaned
    for page in pages:
        if not isinstance(page, dict):
            continue
        items = page.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            form_relationship_ids: set[str] = set()
            group = item.get("form_group")
            valid_marker = (
                item.get("layout_forms_projected") is True
                and item.get("form_policy") == POLICY_ID
                and isinstance(group, Mapping)
            )
            if valid_marker:
                for key in ("relationship_ids", "anchor_relationship_ids"):
                    values = group.get(key)
                    if isinstance(values, list):
                        form_relationship_ids.update(
                            value
                            for value in values[:2_816]
                            if _bounded_public_string(value)
                        )
            for key in (
                "form_fields",
                "form_labels",
                "form_value_regions",
                "form_controls",
                "form_key_value_pairs",
            ):
                values = item.get(key) if valid_marker else None
                if not isinstance(values, list):
                    continue
                for record in values[:MAX_FORM_CONTROLS_PER_GROUP]:
                    if not isinstance(record, Mapping):
                        continue
                    relationship_ids = record.get("relationship_ids")
                    if isinstance(relationship_ids, list):
                        form_relationship_ids.update(
                            value
                            for value in relationship_ids[:323]
                            if _bounded_public_string(value)
                        )
            for key in _PUBLIC_FORM_KEYS:
                item.pop(key, None)
            relationships = item.get("relationships")
            if not isinstance(relationships, list):
                continue
            retained = [
                descriptor
                for descriptor in relationships
                if not (
                    isinstance(descriptor, Mapping)
                    and descriptor.get("id") in form_relationship_ids
                    and descriptor.get("type")
                    in _PUBLIC_FORM_RELATIONSHIP_TYPES
                    and descriptor.get("canonical_inert") is True
                    and set(descriptor)
                    == {
                        "id",
                        "type",
                        "source_id",
                        "target_id",
                        "evidence_ids",
                        "canonical_inert",
                    }
                )
            ]
            if retained:
                item["relationships"] = retained
            else:
                item.pop("relationships", None)
    return cleaned


def extract_form_evidence(
    pdf_bytes: bytes,
    *,
    max_pages: int = 100,
) -> FormEvidenceReport:
    """Extract a bounded immutable local source report from a PDF."""

    if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
        raise ValueError("form evidence requires nonempty PDF bytes")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer")
    started = time.perf_counter()
    budget = _ExtractionBudget(started)

    def remaining_seconds() -> float:
        budget.check_deadline()
        return DEADLINE_SECONDS - (time.perf_counter() - started)

    audit_acroform_raw(
        pdf_bytes,
        deadline_seconds=remaining_seconds(),
    )
    budget.check_deadline()
    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    try:
        import pdfplumber

        pdf = pdfplumber.open(BytesIO(pdf_bytes))
    except Exception as exc:
        raise ValueError("form source evidence is unavailable") from exc

    pages: list[FormSourcePage] = []
    total_chars = 0
    total_words = 0
    total_vectors = 0
    total_curve_points = 0
    document_concerns: list[str] = []
    report_budget = _RetainedReportBudget()
    try:
        budget.check_deadline()
        if len(pdf.pages) > max_pages:
            raise ValueError("form source exceeds the configured page limit")
        catalog = getattr(pdf.doc, "catalog", {})
        page_inputs: list[AcroFormPageInput] = []
        for page_index, page in enumerate(pdf.pages, start=1):
            if page_index % 16 == 1:
                budget.check_deadline()
            page_inputs.append(
                AcroFormPageInput(
                    page_index=page_index,
                    width=round(_finite(page.width), 3),
                    height=round(_finite(page.height), 3),
                    annotations=(
                        page.page_obj.attrs.get("Annots", ())
                        if isinstance(page.page_obj.attrs, Mapping)
                        else ()
                    ),
                    annotations_present=(
                        isinstance(page.page_obj.attrs, Mapping)
                        and "Annots" in page.page_obj.attrs
                    ),
                    rotation=int(getattr(page, "rotation", 0) or 0),
                    page_object_id=int(page.page_obj.pageid),
                    media_box=page.page_obj.attrs.get("MediaBox"),
                    crop_box=page.page_obj.attrs.get(
                        "CropBox",
                        page.page_obj.attrs.get("MediaBox"),
                    ),
                    user_unit=page.page_obj.attrs.get("UserUnit", 1),
                )
            )
        budget.check_deadline()
        inspection = inspect_acroform(
            catalog=catalog,
            pages=tuple(page_inputs),
            source_sha256=source_sha256,
            deadline_seconds=remaining_seconds(),
        )
        budget.check_deadline()
        inspection_pages = {
            page.page_index: page for page in inspection.pages
        }
        document_concerns.extend(inspection.concern_codes)
        for page_index, page in enumerate(pdf.pages, start=1):
            # Geometry/association comparisons are capped independently on
            # every page while retaining the one document-wide deadline.
            budget = _ExtractionBudget(started)
            budget.check_deadline()
            raw_chars = page.chars
            budget.check_deadline()
            try:
                raw_char_count = len(raw_chars)
            except TypeError as exc:
                raise ValueError(
                    "form source character records are not sized"
                ) from exc
            if total_chars + raw_char_count > MAX_SOURCE_CHARACTERS:
                raise ValueError("form source character limit exceeded")
            total_chars += raw_char_count

            extracted_words = page.extract_words(
                extra_attrs=["fontname", "size"],
                keep_blank_chars=False,
                use_text_flow=False,
            )
            budget.check_deadline()
            try:
                extracted_word_count = len(extracted_words)
            except TypeError as exc:
                raise ValueError(
                    "form source word records are not sized"
                ) from exc
            if extracted_word_count > MAX_WORDS_PER_PAGE:
                raise ValueError("form source word page limit exceeded")
            if total_words + extracted_word_count > MAX_WORDS_PER_DOCUMENT:
                raise ValueError("form source word document limit exceeded")
            total_words += extracted_word_count

            char_records: list[SourceChar] = []
            for index, raw in enumerate(raw_chars):
                if index % 1_024 == 0:
                    budget.check_deadline()
                char_record = SourceChar(
                    index=index,
                    text=_bounded_source_text(raw.get("text", "")),
                    x0=round(_finite(raw.get("x0")), 3),
                    top=round(_finite(raw.get("top")), 3),
                    x1=round(_finite(raw.get("x1")), 3),
                    bottom=round(_finite(raw.get("bottom")), 3),
                    font_name=_bounded_source_text(
                        raw.get("fontname", "unknown")
                    ),
                    size=round(_finite(raw.get("size")), 3),
                )
                report_budget.account_record(char_record)
                char_records.append(char_record)
            chars = tuple(char_records)
            char_index = _SourceCharIndex.build(chars, budget=budget)
            word_records: list[SourceWord] = []
            for index, raw in enumerate(extracted_words):
                if index % 256 == 0:
                    budget.check_deadline()
                word_record = _source_word(
                    index,
                    raw,
                    char_index,
                    budget=budget,
                )
                report_budget.account_record(word_record)
                word_records.append(word_record)
            words = tuple(word_records)

            raw_lines = page.lines
            budget.check_deadline()
            raw_rects = page.rects
            budget.check_deadline()
            raw_curves = page.curves
            budget.check_deadline()
            raw_edges = page.edges
            budget.check_deadline()
            line_count = len(raw_lines)
            rect_count = len(raw_rects)
            curve_count = len(raw_curves)
            edge_count = len(raw_edges)
            vector_count = (
                line_count + rect_count + curve_count + edge_count
            )
            if vector_count > MAX_VECTOR_OBJECTS_PER_PAGE:
                raise ValueError("form source vector page limit exceeded")
            total_vectors += vector_count
            if total_vectors > MAX_VECTOR_OBJECTS_PER_DOCUMENT:
                raise ValueError("form source vector document limit exceeded")

            page_curve_points = 0
            for curve_index, raw_curve in enumerate(raw_curves):
                if curve_index % 128 == 0:
                    budget.check_deadline()
                path = raw_curve.get("path", ())
                if not isinstance(path, (list, tuple)):
                    raise ValueError("form source curve path is invalid")
                point_count = len(path)
                if point_count > MAX_CURVE_POINTS_PER_OBJECT:
                    raise ValueError(
                        "form source curve object limit exceeded"
                    )
                page_curve_points += point_count
                if page_curve_points > MAX_CURVE_POINTS_PER_PAGE:
                    raise ValueError(
                        "form source curve page limit exceeded"
                    )
            total_curve_points += page_curve_points
            if total_curve_points > MAX_CURVE_POINTS_PER_DOCUMENT:
                raise ValueError(
                    "form source curve document limit exceeded"
                )

            vector_records: list[SourceVector] = []
            for kind, raw_vectors in (
                ("line", raw_lines),
                ("rect", raw_rects),
                ("curve", raw_curves),
            ):
                for index, raw in enumerate(raw_vectors):
                    if index % 256 == 0:
                        budget.check_deadline()
                    vector_record = _source_vector(kind, index, raw)
                    report_budget.account_record(vector_record)
                    vector_records.append(vector_record)
            vectors = tuple(vector_records)
            budget.check_deadline()
            page_inspection = inspection_pages.get(page_index)
            if page_inspection is None:
                raise ValueError("form page inspection is unavailable")
            interactive_controls = tuple(
                SourceInteractiveControl(
                    annotation_index=control.annotation_index,
                    bbox=control.bbox,
                    widget_ref_digest=control.object_ref_digest,
                    field_ref_digest=control.field_ref_digest,
                    field_name=control.field_name,
                    control_type=control.control_type,
                    state=control.state,
                    concern_codes=control.concern_codes,
                )
                for control in page_inspection.controls
            )
            for control in interactive_controls:
                report_budget.account_record(control)
            annotations = tuple(
                SourceAnnotation(
                    index=control.annotation_index,
                    subtype="Widget",
                    x0=control.bbox[0],
                    top=control.bbox[1],
                    x1=control.bbox[0] + control.bbox[2],
                    bottom=control.bbox[1] + control.bbox[3],
                    object_ref_digest=control.widget_ref_digest,
                )
                for control in interactive_controls
            )
            for annotation in annotations:
                report_budget.account_record(annotation)
            static = _page_has_static_form_evidence(
                words,
                vectors,
                budget=budget,
            )
            budget.check_deadline()
            page_concerns = list(page_inspection.concern_codes)
            if page_inspection.interactivity == "unknown":
                interactivity = "unknown"
            elif page_inspection.interactivity == "interactive" and static:
                interactivity = "mixed"
            elif page_inspection.interactivity == "interactive":
                interactivity = "interactive"
            elif static:
                interactivity = "static"
            else:
                interactivity = "none"
            page_report = FormSourcePage(
                page_index=page_index,
                width=round(_finite(page.width), 3),
                height=round(_finite(page.height), 3),
                chars=chars,
                words=words,
                vectors=vectors,
                annotations=annotations,
                interactivity=interactivity,
                interactive_controls=interactive_controls,
                concern_codes=tuple(page_concerns),
            )
            report_budget.account_page(page_report)
            pages.append(page_report)
            budget.check_deadline()
    finally:
        pdf.close()

    budget.check_deadline()
    states = {page.interactivity for page in pages}
    if "unknown" in states or inspection.interactivity == "unknown":
        interactivity = "unknown"
    elif "mixed" in states or ({"static", "interactive"} <= states):
        interactivity = "mixed"
    elif "interactive" in states:
        interactivity = "interactive"
    elif "static" in states:
        interactivity = "static"
    else:
        interactivity = "none"
    if interactivity == "unknown":
        document_concerns.append("form_interactivity_unknown")
    budget.check_deadline()
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    report = FormEvidenceReport(
        report_version=REPORT_VERSION,
        policy_id=POLICY_ID,
        source_sha256=source_sha256,
        pages=tuple(pages),
        interactivity=interactivity,
        concern_codes=tuple(dict.fromkeys(document_concerns)),
        extraction_ms=elapsed_ms,
    )
    report_size = (
        _compact_json_size(
            replace(report, pages=()),
            limit=MAX_REPORT_BYTES,
        )
        + report_budget.page_payload_bytes
        + max(0, report_budget.page_count - 1)
    )
    budget.check_deadline()
    if report_size > MAX_REPORT_BYTES:
        raise ValueError("form source report limit exceeded")
    budget.check_deadline()
    return report


def _bounded_source_text(value: object) -> str:
    text = str(value)
    try:
        payload = text.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("form source text is not encodable") from exc
    if len(payload) > MAX_TEXT_BYTES:
        raise ValueError("form source text limit exceeded")
    return text


def _finite(value: object) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("form source geometry must be finite")
    return number


def _millipoints(value: float) -> int:
    return int(round(value * 1_000))


def _within_points(
    first: float,
    second: float,
    *,
    tolerance: float = 0.15,
) -> bool:
    return abs(_millipoints(first) - _millipoints(second)) <= int(
        round(tolerance * 1_000)
    )


def _at_most_with_tolerance(
    value: float,
    boundary: float,
    *,
    tolerance: float = 0.15,
) -> bool:
    return _millipoints(value) <= (
        _millipoints(boundary) + int(round(tolerance * 1_000))
    )


def _at_least_with_tolerance(
    value: float,
    boundary: float,
    *,
    tolerance: float = 0.15,
) -> bool:
    return _millipoints(value) >= (
        _millipoints(boundary) - int(round(tolerance * 1_000))
    )


def _at_least_ninety_five_percent(
    value: float,
    reference: float,
) -> bool:
    return (
        max(0, _millipoints(value)) * 100
        >= max(0, _millipoints(reference)) * 95
    )


def _source_word(
    index: int,
    raw: Mapping[str, Any],
    char_index: _SourceCharIndex,
    *,
    budget: _ExtractionBudget,
) -> SourceWord:
    x0 = round(_finite(raw.get("x0")), 3)
    top = round(_finite(raw.get("top")), 3)
    x1 = round(_finite(raw.get("x1")), 3)
    bottom = round(_finite(raw.get("bottom")), 3)
    owned = char_index.contained_indexes(
        x0=x0,
        top=top,
        x1=x1,
        bottom=bottom,
        budget=budget,
    )
    if not owned:
        raise ValueError("form source word provenance is unavailable")
    char_start = min(owned)
    char_end = max(owned) + 1
    return SourceWord(
        index=index,
        text=_bounded_source_text(raw.get("text", "")),
        x0=x0,
        top=top,
        x1=x1,
        bottom=bottom,
        font_name=_bounded_source_text(raw.get("fontname", "unknown")),
        size=round(_finite(raw.get("size")), 3),
        char_start=char_start,
        char_end=char_end,
    )


def _source_vector(
    kind: Literal["line", "rect", "curve"],
    index: int,
    raw: Mapping[str, Any],
) -> SourceVector:
    x0 = round(
        _finite(raw.get("x0", min(raw.get("x0", 0), raw.get("x1", 0)))),
        3,
    )
    x1 = round(
        _finite(raw.get("x1", max(raw.get("x0", 0), raw.get("x1", 0)))),
        3,
    )
    top = round(_finite(raw.get("top", 0)), 3)
    bottom = round(_finite(raw.get("bottom", top)), 3)
    return SourceVector(
        kind=kind,
        index=index,
        x0=min(x0, x1),
        top=min(top, bottom),
        x1=max(x0, x1),
        bottom=max(top, bottom),
        fill=bool(raw.get("fill")),
    )


def _source_annotation(index: int, raw: Mapping[str, Any]) -> SourceAnnotation:
    data = raw.get("data")
    subtype = "unknown"
    if isinstance(data, Mapping) and data.get("Subtype") is not None:
        subtype = str(data.get("Subtype")).strip("/'")
    identity = f"annotation:{index}:{subtype}"
    return SourceAnnotation(
        index=index,
        subtype=_bounded_source_text(subtype),
        x0=round(_finite(raw.get("x0", 0)), 3),
        top=round(_finite(raw.get("top", 0)), 3),
        x1=round(_finite(raw.get("x1", 0)), 3),
        bottom=round(_finite(raw.get("bottom", 0)), 3),
        object_ref_digest=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
    )


def _catalog_acroform_state(
    catalog: Mapping[str, Any],
    resolver: Any,
) -> Literal["none", "present", "unknown"]:
    try:
        raw = catalog.get("AcroForm")
        if raw is None:
            return "none"
        resolved = resolver(raw)
        if not isinstance(resolved, Mapping):
            return "unknown"
        fields = resolver(resolved.get("Fields", []))
        if not isinstance(fields, (list, tuple)):
            return "unknown"
        return "present" if fields else "none"
    except Exception:
        return "unknown"


def _page_has_static_form_evidence(
    words: Sequence[SourceWord],
    vectors: Sequence[SourceVector],
    *,
    budget: _ExtractionBudget,
) -> bool:
    small_box_records: list[SourceVector] = []
    broad_value_regions: list[SourceVector] = []
    broad_regions = 0
    for vector in vectors:
        budget.account_comparison()
        width = vector.x1 - vector.x0
        height = vector.bottom - vector.top
        if (
            vector.kind == "rect"
            and 6 <= width <= 24
            and 6 <= height <= 24
            and 0.65 <= width / height <= 1.55
        ):
            small_box_records.append(vector)
        if vector.kind == "rect" and width >= 24 and 6 <= height <= 24:
            broad_value_regions.append(vector)
        if vector.kind == "rect" and width >= 120 and height >= 24:
            broad_regions += 1
    visible_words = tuple(word for word in words if word.text.strip())
    small_boxes = len(small_box_records)
    for box in small_box_records:
        for word in visible_words:
            budget.account_comparison()
            if (
                0.5 <= word.x0 - box.x1 <= 96
                and word.top <= box.bottom + 4
                and word.bottom >= box.top - 1.5
            ):
                return True
    for vector in broad_value_regions:
        for word in visible_words:
            budget.account_comparison()
            if (
                0.5 <= vector.x0 - word.x1 <= 96
                and word.top <= vector.bottom + 4
                and word.bottom >= vector.top - 1.5
            ):
                return True
    upper_labels = 0
    for word in words:
        budget.account_comparison()
        if (
            bool(word.text)
            and word.text.upper() == word.text
            and any(character.isalpha() for character in word.text)
        ):
            upper_labels += 1
    return (small_boxes >= 3 and upper_labels >= 3) or (
        broad_regions >= 3 and upper_labels >= 8
    )


def _bbox_tuple(
    element: ElementRecord,
    bboxes: Mapping[str, IRBoundingBox],
) -> tuple[float, float, float, float] | None:
    candidates = [
        bboxes[bbox_id]
        for bbox_id in element.bbox_ids
        if bbox_id in bboxes and bboxes[bbox_id].role == "element"
    ]
    if len(candidates) != 1:
        return None
    [bbox] = candidates
    if bbox.width <= 0 or bbox.height <= 0:
        return None
    return (bbox.x, bbox.y, bbox.width, bbox.height)


def _legacy_item(element: ElementRecord) -> Mapping[str, Any] | None:
    value = element.properties.get("legacy_item")
    return value if isinstance(value, Mapping) else None


def _element_text(element: ElementRecord) -> str | None:
    legacy = _legacy_item(element)
    if legacy is None:
        return None
    value = legacy.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        return None
    return value


def _chars_in_bbox(
    page: FormSourcePage,
    bbox: tuple[float, float, float, float],
    *,
    tolerance: float = 0.2,
) -> tuple[SourceChar, ...]:
    return _projection_spatial_index(page).chars_contained(
        bbox,
        tolerance=tolerance,
    )


def _chars_intersecting_bbox(
    page: FormSourcePage,
    bbox: tuple[float, float, float, float],
) -> tuple[SourceChar, ...]:
    return _projection_spatial_index(page).chars_intersecting(bbox)


def _source_range_for_bbox(
    page: FormSourcePage,
    bbox: tuple[float, float, float, float],
) -> tuple[tuple[str, int, int | None], ...]:
    chars = _chars_in_bbox(page, bbox)
    if not chars:
        return ()
    indexes = sorted(char.index for char in chars)
    ranges: list[tuple[str, int, int | None]] = []
    start = indexes[0]
    prior = start
    for index in indexes[1:]:
        if index == prior + 1:
            prior = index
            continue
        ranges.append(("character_range", start, prior + 1))
        if len(ranges) > 64:
            raise _ProjectionPageLimitError(page.page_index)
        start = prior = index
    ranges.append(("character_range", start, prior + 1))
    if len(ranges) > 64:
        raise _ProjectionPageLimitError(page.page_index)
    return tuple(ranges)


def _bounded_source_identities(
    values: Any,
    *,
    page_index: int,
) -> tuple[_SourceIdentity, ...]:
    retained: list[_SourceIdentity] = []
    seen: set[_SourceIdentity] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        retained.append(value)
        if len(retained) > 64:
            raise _ProjectionPageLimitError(page_index)
    return tuple(retained)


def _element_is_bold(
    page: FormSourcePage,
    element: ElementRecord,
    bbox: tuple[float, float, float, float],
) -> bool | None:
    text = _element_text(element)
    chars = _chars_in_bbox(page, bbox)
    if text is None or not chars:
        return None
    visible = "".join(char.text for char in sorted(chars, key=lambda c: c.x0))
    if re.sub(r"\s+", "", visible) != re.sub(r"\s+", "", text):
        return None
    states = {"bold" in char.font_name.casefold() for char in chars if char.text.strip()}
    return states.pop() if len(states) == 1 else None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:_ID_LIMIT] or "item"


def _key_value_group_key(keys: Sequence[str]) -> str:
    normalized = [re.sub(r"\s+", " ", key).strip() for key in keys]
    if normalized and all(re.fullmatch(r"GPIO\d+", key) for key in normalized):
        return "gpio-functions"
    if normalized and all(re.fullmatch(r"PIN\d+", key) for key in normalized):
        return "interface-pins"
    if any(key.startswith("Operating Temp ") for key in normalized) and all(
        key.startswith("Operating Temp ") or key in {"VBUS", "VSYS Min", "VSYS Max"}
        for key in normalized
    ):
        return "operating-conditions"
    prefix = re.match(r"[A-Za-z]+", normalized[0] if normalized else "values")
    return f"{_slug(prefix.group(0) if prefix else 'values')}-values"


def _canonical_predecessor_owned_primaries(ir: DocumentIR) -> frozenset[str]:
    cache = _PROJECTION_CANONICAL_OWNERS.get()
    cache_key = id(ir)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    try:
        from app.services.presentation import build_canonical_presentation

        presentation = build_canonical_presentation(ir)
    except Exception:
        return frozenset()
    blocks = [block for page in presentation.pages for block in page.blocks]
    eligible: set[str] = set()
    budget = _PROJECTION_BUDGET.get()
    claimed_ids = {
        contributor_id
        for block in blocks
        for contributor_id in block.contributing_element_ids
    }
    owner_counts: Counter[str] = Counter()
    for index, block in enumerate(blocks):
        owner_counts.update(
            {
                block.primary_element_id,
                *block.contributing_element_ids,
            }
        )
        if budget is not None and index % 256 == 0:
            budget.check_deadline()
    for index, block in enumerate(blocks):
        contributor_id = block.primary_element_id
        if (
            owner_counts[contributor_id] == 1
            and block.contributing_element_ids == [contributor_id]
            and block.omission_reason is None
            and block.suppressed_by_element_id is None
            and contributor_id in claimed_ids
        ):
            eligible.add(contributor_id)
        if budget is not None and index % 256 == 0:
            budget.check_deadline()
    result = frozenset(eligible)
    if cache is not None:
        cache[cache_key] = result
    return result


def _key_value_candidates(
    ir: DocumentIR,
    report: FormEvidenceReport,
    *,
    custody_rejections: list[tuple[int, str]] | None = None,
    canonical_owned_primaries: frozenset[str] | None = None,
) -> tuple[_GroupCandidate, ...]:
    pages_by_index = {page.page_index: page for page in report.pages}
    lookup = _projection_ir_lookup(ir)
    elements = lookup.elements
    bboxes = lookup.bboxes
    candidates: list[_GroupCandidate] = []
    owned_primaries = canonical_owned_primaries
    for page_record in sorted(ir.pages, key=lambda page: page.page_index):
        source_page = pages_by_index.get(page_record.page_index)
        if source_page is None:
            continue
        _charge_projection_comparisons(
            source_page.page_index,
            len(page_record.presentation_element_ids),
        )
        primary: list[ElementRecord] = []
        for element_id in page_record.presentation_element_ids:
            element = elements.get(element_id)
            if element is not None:
                primary.append(element)
        pairs: list[
            tuple[
                int,
                ElementRecord,
                ElementRecord,
                tuple[float, float, float, float],
                tuple[float, float, float, float],
            ]
        ] = []
        index = 0
        while index + 1 < len(primary):
            key_element = primary[index]
            value_element = primary[index + 1]
            key_legacy = _legacy_item(key_element)
            value_legacy = _legacy_item(value_element)
            key_bbox = _bbox_tuple(key_element, bboxes)
            value_bbox = _bbox_tuple(value_element, bboxes)
            if (
                key_legacy is None
                or value_legacy is None
                or key_legacy.get("type") != "text"
                or value_legacy.get("type") != "text"
                or key_legacy.get("source") not in {"native", "recovered"}
                or value_legacy.get("source") not in {"native", "recovered"}
                or key_bbox is None
                or value_bbox is None
            ):
                index += 1
                continue
            kx, ky, kw, kh = key_bbox
            vx, vy, vw, vh = value_bbox
            gap = vx - (kx + kw)
            geometry_ok = (
                abs(ky - vy) <= 1.25
                and abs(kh - vh) <= 2
                and 2 <= gap <= min(160, 0.35 * source_page.width)
            )
            if not geometry_ok or _element_is_bold(
                source_page, key_element, key_bbox
            ) is not True or _element_is_bold(
                source_page, value_element, value_bbox
            ) is not False:
                index += 1
                continue
            pairs.append(
                (index, key_element, value_element, key_bbox, value_bbox)
            )
            index += 2

        runs: list[list[Any]] = []
        _charge_projection_comparisons(
            source_page.page_index,
            len(pairs),
        )
        for pair in pairs:
            if not runs:
                runs.append([pair])
                continue
            prior = runs[-1][-1]
            cadence = pair[3][1] - prior[3][1]
            if (
                pair[0] == prior[0] + 2
                and 4 <= cadence <= 30
                and abs(pair[3][0] - prior[3][0]) <= 2
                and abs(pair[4][0] - prior[4][0]) <= 2
            ):
                runs[-1].append(pair)
            else:
                runs.append([pair])

        for run in runs:
            if len(run) < 3:
                continue
            if len(run) > MAX_FORM_KEY_VALUE_PAIRS_PER_GROUP:
                raise _ProjectionPageLimitError(source_page.page_index)
            cadences = [
                run[offset][3][1] - run[offset - 1][3][1]
                for offset in range(1, len(run))
            ]
            if max(cadences) - min(cadences) > 2:
                continue
            keys = [_element_text(pair[1]) for pair in run]
            values = [_element_text(pair[2]) for pair in run]
            if any(value is None for value in (*keys, *values)):
                continue
            exact_keys = [str(value) for value in keys]
            exact_values = [str(value) for value in values]
            group_key = _key_value_group_key(exact_keys)
            contributor_elements = tuple(
                element
                for pair in run
                for element in (pair[1], pair[2])
            )
            contributor_element_ids = tuple(
                element.id for element in contributor_elements
            )
            if len(contributor_element_ids) > 64:
                raise _ProjectionPageLimitError(
                    source_page.page_index
                )
            contributor_public_item_ids = tuple(
                str(_legacy_item(element)["id"])
                for element in contributor_elements
                if _legacy_item(element) is not None
            )
            if len(contributor_public_item_ids) != len(contributor_elements):
                continue
            if owned_primaries is None:
                owned_primaries = _canonical_predecessor_owned_primaries(ir)
            if not set(contributor_element_ids).issubset(owned_primaries):
                if custody_rejections is not None:
                    custody_rejections.append(
                        (
                            source_page.page_index,
                            contributor_element_ids[0],
                        )
                    )
                continue
            _reserve_projection_candidate(
                page_index=source_page.page_index,
                roles={
                    "key_value_pair": len(run),
                    "label": len(run),
                    "value_region": len(run),
                },
                relationships=5 * len(run),
            )
            left = min(pair[3][0] for pair in run)
            top = min(pair[3][1] for pair in run)
            right = max(pair[4][0] + pair[4][2] for pair in run)
            bottom = max(pair[4][1] + pair[4][3] for pair in run)
            records: list[_RecordCandidate] = []
            relationships: list[tuple[str, str, str]] = []
            for pair, key, value in zip(
                run, exact_keys, exact_values, strict=True
            ):
                _order, key_element, value_element, key_bbox, value_bbox = pair
                pair_key = f"{group_key}:{_slug(key)}"
                pair_token = f"pair:{pair_key}"
                label_token = f"label:{pair_key}"
                value_token = f"value-region:{pair_key}"
                pair_bbox = (
                    key_bbox[0],
                    min(key_bbox[1], value_bbox[1]),
                    value_bbox[0] + value_bbox[2] - key_bbox[0],
                    max(
                        key_bbox[1] + key_bbox[3],
                        value_bbox[1] + value_bbox[3],
                    )
                    - min(key_bbox[1], value_bbox[1]),
                )
                key_refs = _source_range_for_bbox(source_page, key_bbox)
                value_refs = _source_range_for_bbox(source_page, value_bbox)
                records.extend(
                    [
                        _RecordCandidate(
                            token=pair_token,
                            role="key_value_pair",
                            key=pair_key,
                            bbox=pair_bbox,
                            source_objects=tuple((*key_refs, *value_refs)),
                            data={
                                "key": key,
                                "value": value,
                                "key_source_item_id": str(
                                    _legacy_item(key_element)["id"]
                                ),
                                "value_source_item_id": str(
                                    _legacy_item(value_element)["id"]
                                ),
                                "key_source_element_id": key_element.id,
                                "value_source_element_id": value_element.id,
                            },
                        ),
                        _RecordCandidate(
                            token=label_token,
                            role="label",
                            key=pair_key,
                            bbox=key_bbox,
                            source_objects=key_refs,
                            data={
                                "label_role": "key",
                                "text": key,
                                "raw_text": key,
                            },
                        ),
                        _RecordCandidate(
                            token=value_token,
                            role="value_region",
                            key=pair_key,
                            bbox=value_bbox,
                            source_objects=value_refs,
                            data={"value": value, "value_state": "present"},
                        ),
                    ]
                )
                relationships.extend(
                    [
                        ("contains", f"group:{group_key}", pair_token),
                        ("contains", pair_token, label_token),
                        ("contains", pair_token, value_token),
                        ("key_of", label_token, pair_token),
                        ("value_of", value_token, pair_token),
                    ]
                )
            group_refs = _bounded_source_identities(
                (
                    ref
                    for record in records
                    if record.role == "key_value_pair"
                    for ref in record.source_objects
                ),
                page_index=source_page.page_index,
            )
            candidates.append(
                _GroupCandidate(
                    group_key=group_key,
                    page_index=page_record.page_index,
                    bbox=(left, top, right - left, bottom - top),
                    status="resolved",
                    interactivity="none",
                    canonical_mode="replace",
                    anchor_public_item_id=contributor_public_item_ids[0],
                    anchor_element_id=contributor_element_ids[0],
                    contributor_public_item_ids=contributor_public_item_ids,
                    contributor_element_ids=contributor_element_ids,
                    records=tuple(records),
                    relationships=tuple(relationships),
                    source_objects=group_refs,
                )
            )
    return tuple(candidates)


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256(
        json.dumps(
            parts,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).digest()[:10]
    compact_prefix = {
        "form-el": "e",
        "form-record": "r",
        "form-bbox": "b",
        "form-evidence": "v",
        "form-rel": "l",
    }.get(prefix, f"{prefix}-")
    token = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{compact_prefix}{token}"


def _rounded_bbox(
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    values = tuple(round(float(value), 3) for value in bbox)
    if not all(math.isfinite(value) for value in values) or (
        values[2] <= 0 or values[3] <= 0
    ):
        raise ValueError("form semantic bbox is invalid")
    return values


def _public_source_objects(
    refs: Sequence[_SourceIdentity],
) -> list[SourceObjectRef]:
    values: list[SourceObjectRef] = []
    seen: set[_SourceIdentity] = set()
    for kind, first, second in refs:
        identity = (kind, first, second)
        if identity in seen:
            continue
        seen.add(identity)
        if kind == "character_range" and second is not None:
            values.append(
                CharacterRangeRef(kind=kind, start=first, end=second)
            )
        elif kind in {"line", "rect"} and isinstance(first, int) and second is None:
            values.append(IndexedSourceRef(kind=kind, index=first))
        elif (
            kind in {"field", "widget", "annotation"}
            and isinstance(first, str)
            and second is None
        ):
            values.append(
                ObjectSourceRef(kind=kind, object_ref_digest=first)
            )
        else:
            raise ValueError("unsupported form source-object reference")
    if not 1 <= len(values) <= 64:
        raise ValueError("form semantic record requires 1-64 source identities")
    return values


def _confidence_dimensions(*, transcription: bool) -> ConfidenceDimensions:
    unavailable = ConfidenceDimension(unavailable_reason="not_calibrated")
    return ConfidenceDimensions(
        geometry=unavailable,
        role=unavailable,
        transcription=(
            ConfidenceDimension(score=1.0)
            if transcription
            else ConfidenceDimension(
                unavailable_reason="transcription_not_applicable"
            )
        ),
        state=unavailable,
    )


def _relationship_sort_key(
    relationship: tuple[str, str, str],
    token_order: Mapping[str, int],
) -> tuple[int, int, int, str, str]:
    type_order = {
        value.value: index for index, value in enumerate(RelationshipType)
    }
    relationship_type, source_token, target_token = relationship
    return (
        token_order.get(source_token, 10**9),
        type_order[relationship_type],
        token_order.get(target_token, 10**9),
        source_token,
        target_token,
    )


def _materialize_group(ir: DocumentIR, candidate: _GroupCandidate) -> None:
    elements_by_id = {element.id: element for element in ir.elements}
    page = next(
        (page for page in ir.pages if page.page_index == candidate.page_index),
        None,
    )
    if page is None:
        raise ValueError("form semantic group has no source page")
    anchor = elements_by_id.get(candidate.anchor_element_id)
    if anchor is None or anchor.page_id != page.id:
        raise ValueError("form semantic group has no exact public anchor")
    anchor_legacy = _legacy_item(anchor)
    if anchor_legacy is None or (
        anchor_legacy.get("id") != candidate.anchor_public_item_id
    ):
        raise ValueError("form semantic anchor public/internal IDs disagree")
    if len(candidate.concern_codes) > MAX_FORM_CONCERNS_PER_GROUP or any(
        code not in _ALLOWED_CONCERNS for code in candidate.concern_codes
    ):
        raise ValueError("form semantic candidate has unsupported concerns")
    if any(
        len(record.concern_codes) > MAX_FORM_CONCERNS_PER_GROUP
        or any(
            code not in _ALLOWED_CONCERNS
            for code in record.concern_codes
        )
        for record in candidate.records
    ):
        raise ValueError("form semantic record has unsupported concerns")

    token_order = {f"group:{candidate.group_key}": 0}
    token_order.update(
        {record.token: index for index, record in enumerate(candidate.records, 1)}
    )
    ordered_relationships = sorted(
        candidate.relationships,
        key=lambda value: _relationship_sort_key(value, token_order),
    )
    group_token = f"group:{candidate.group_key}"
    group_bbox = _rounded_bbox(candidate.bbox)
    group_element_id = _stable_id(
        "form-el",
        ir.source_sha256,
        candidate.page_index,
        "group",
        group_bbox,
        candidate.source_objects,
        candidate.group_key,
    )
    token_to_element = {group_token: group_element_id}
    token_to_record = {
        group_token: _stable_id(
            "form-record", ir.source_sha256, candidate.page_index, group_token
        )
    }
    for record in candidate.records:
        rounded = _rounded_bbox(record.bbox)
        token_to_element[record.token] = _stable_id(
            "form-el",
            ir.source_sha256,
            candidate.page_index,
            record.role,
            rounded,
            record.source_objects,
            group_element_id,
            record.key,
        )
        token_to_record[record.token] = _stable_id(
            "form-record",
            ir.source_sha256,
            candidate.page_index,
            record.token,
            group_element_id,
        )
    if set(token_to_element.values()) & set(elements_by_id):
        raise ValueError("form semantic replay repeats an element ID")

    relationship_records: list[RelationshipRecord] = []
    relationship_id_by_tuple: dict[tuple[str, str, str], str] = {}
    incident: dict[str, list[str]] = {
        token: [] for token in token_to_element
    }
    incoming: dict[tuple[str, str], list[str]] = {}
    outgoing: dict[tuple[str, str], list[str]] = {}
    evidence_ids_by_token: dict[str, list[str]] = {}

    record_by_token = {record.token: record for record in candidate.records}
    refs_by_token = {
        group_token: candidate.source_objects,
        **{
            record.token: record.source_objects
            for record in candidate.records
        },
    }
    coordinate_system_id = page.coordinate_system_id
    bbox_id_by_token: dict[str, str] = {}
    bbox_values_by_token = {
        group_token: group_bbox,
        **{
            record.token: _rounded_bbox(record.bbox)
            for record in candidate.records
        },
    }
    # An empty field and its value region intentionally share one canonical
    # bbox record without sharing semantic identity.
    for relationship_type, source_token, target_token in ordered_relationships:
        if relationship_type == "value_of":
            owner = record_by_token.get(target_token)
            if owner is not None and owner.role == "field":
                bbox_values_by_token[source_token] = bbox_values_by_token[target_token]
    for token in token_to_element:
        bbox_value = bbox_values_by_token[token]
        role = "field" if token.startswith(("field:", "value-region:")) else "element"
        share = token.startswith("value-region:") and any(
            rel_type == "value_of"
            and source == token
            and record_by_token.get(target) is not None
            and record_by_token[target].role == "field"
            for rel_type, source, target in ordered_relationships
        )
        if share:
            owner_token = next(
                target
                for rel_type, source, target in ordered_relationships
                if rel_type == "value_of" and source == token
            )
            bbox_id_by_token[token] = bbox_id_by_token[owner_token]
            continue
        bbox_id = _stable_id(
            "form-bbox",
            ir.source_sha256,
            candidate.page_index,
            token,
            bbox_value,
        )
        ir.bboxes.append(
            IRBoundingBox(
                id=bbox_id,
                coordinate_system_id=coordinate_system_id,
                x=bbox_value[0],
                y=bbox_value[1],
                width=bbox_value[2],
                height=bbox_value[3],
                role=role,
            )
        )
        bbox_id_by_token[token] = bbox_id

    for token, element_id in token_to_element.items():
        evidence_ids: list[str] = []
        for index, (kind, first, second) in enumerate(refs_by_token[token]):
            evidence_id = _stable_id(
                "form-evidence",
                ir.source_sha256,
                candidate.page_index,
                token,
                kind,
                first,
                second,
                index,
            )
            method = (
                EvidenceMethod.NATIVE
                if kind
                in {"character_range", "field", "widget", "annotation"}
                else EvidenceMethod.VECTOR
                if kind in {"line", "rect"}
                else EvidenceMethod.EMBEDDED
            )
            ir.evidence.append(
                EvidenceRecord(
                    id=evidence_id,
                    element_id=element_id,
                    method=method,
                    bbox_id=bbox_id_by_token[token],
                    confidence=ConfidenceRecord(
                        scope="evidence",
                        unavailable_reason="not_calibrated",
                    ),
                    metadata={"form_policy": POLICY_ID},
                )
            )
            evidence_ids.append(evidence_id)
        if not evidence_ids:
            raise ValueError("form semantic evidence cannot be empty")
        evidence_ids_by_token[token] = evidence_ids

    for relationship_type, source_token, target_token in ordered_relationships:
        source_id = token_to_element[source_token]
        target_id = (
            candidate.anchor_element_id
            if target_token.startswith("anchor-element:")
            else token_to_element[target_token]
        )
        relationship_id = _stable_id(
            "form-rel",
            ir.source_sha256,
            candidate.page_index,
            relationship_type,
            source_id,
            target_id,
        )
        relationship_records.append(
            RelationshipRecord(
                id=relationship_id,
                type=RelationshipType(relationship_type),
                source_id=source_id,
                target_id=target_id,
                evidence_ids=[],
                metadata={"canonical_inert": True},
            )
        )
        relationship_id_by_tuple[
            (relationship_type, source_token, target_token)
        ] = relationship_id
        incident[source_token].append(relationship_id)
        if target_token in incident:
            incident[target_token].append(relationship_id)
        incoming.setdefault((relationship_type, target_token), []).append(
            source_token
        )
        outgoing.setdefault((relationship_type, source_token), []).append(
            target_token
        )

    anchor_relationship_ids = [
        relationship_id_by_tuple[relationship]
        for relationship in ordered_relationships
        if relationship[0] == "form_overlay_of"
    ]
    group_descriptor = FormGroupSemanticDescriptor(
        policy_id=POLICY_ID,
        role="group",
        record_id=token_to_record[group_token],
        group_element_id=group_element_id,
        public_anchor_element_id=candidate.anchor_element_id,
        group_key=candidate.group_key,
        status=candidate.status,
        interactivity=candidate.interactivity,
        canonical_mode=candidate.canonical_mode,
        anchor_public_item_id=candidate.anchor_public_item_id,
        anchor_relationship_ids=anchor_relationship_ids,
        contributor_public_item_ids=list(candidate.contributor_public_item_ids),
        contributor_element_ids=list(candidate.contributor_element_ids),
    )
    semantic_elements: list[ElementRecord] = [
        ElementRecord(
            id=group_element_id,
            page_id=page.id,
            type="form",
            value=None,
            bbox_ids=[bbox_id_by_token[group_token]],
            evidence_ids=evidence_ids_by_token[group_token],
            form_semantics=group_descriptor,
            presentation_role="subordinate",
            properties={"form_policy": POLICY_ID},
        )
    ]

    for record in candidate.records:
        token = record.token
        element_id = token_to_element[token]
        common = {
            "policy_id": POLICY_ID,
            "record_id": token_to_record[token],
            "group_element_id": group_element_id,
            "public_anchor_element_id": candidate.anchor_element_id,
        }
        if record.role == "key_value_pair":
            [key_label_token] = incoming[("key_of", token)]
            [value_region_token] = incoming[("value_of", token)]
            descriptor = FormKeyValuePairSemanticDescriptor(
                **common,
                role="key_value_pair",
                pair_key=record.key,
                key_label_element_id=token_to_element[key_label_token],
                value_region_element_id=token_to_element[value_region_token],
                key=str(record.data["key"]),
                value=str(record.data["value"]),
                value_state="present",
                key_source_item_id=str(record.data["key_source_item_id"]),
                value_source_item_id=str(record.data["value_source_item_id"]),
                key_source_element_id=str(record.data["key_source_element_id"]),
                value_source_element_id=str(record.data["value_source_element_id"]),
            )
            element_type = "key_value"
            element_value: Any = record.data["value"]
        elif record.role == "label":
            descriptor = FormLabelSemanticDescriptor(
                **common,
                role="label",
                label_role=str(record.data["label_role"]),
                text=str(record.data["text"]),
                raw_text=str(record.data["raw_text"]),
                label_of_element_ids=[
                    token_to_element[value]
                    for value in outgoing.get(("label_of", token), [])
                ],
                key_of_element_ids=[
                    token_to_element[value]
                    for value in outgoing.get(("key_of", token), [])
                ],
            )
            element_type = "form_label"
            element_value = record.data["text"]
        elif record.role == "value_region":
            [owner_token] = outgoing[("value_of", token)]
            owner_record = record_by_token[owner_token]
            excluded = (
                incoming.get(("label_of", owner_token), [])
                if owner_record.role == "field"
                else []
            )
            descriptor = FormValueRegionSemanticDescriptor(
                **common,
                role="value_region",
                owner_element_id=token_to_element[owner_token],
                excluded_label_element_ids=[
                    token_to_element[value] for value in excluded
                ],
                value=record.data.get("value"),
                value_state=str(record.data["value_state"]),
            )
            element_type = "form_value_region"
            element_value = record.data.get("value")
        elif record.role == "field":
            [value_region_token] = incoming[("value_of", token)]
            descriptor = FormFieldSemanticDescriptor(
                **common,
                role="field",
                field_key=record.key,
                label_element_ids=[
                    token_to_element[value]
                    for value in incoming.get(("label_of", token), [])
                ],
                value_region_element_id=token_to_element[value_region_token],
                control_element_ids=[
                    token_to_element[value]
                    for value in incoming.get(("control_of", token), [])
                ],
                value=record.data.get("value"),
                value_state=str(record.data["value_state"]),
            )
            element_type = "form_field"
            element_value = record.data.get("value")
        elif record.role == "control":
            owners = outgoing.get(("control_of", token), [])
            [owner_token] = owners
            owner_record = record_by_token.get(owner_token)
            labels = incoming.get(("label_of", token), [])
            descriptor = FormControlSemanticDescriptor(
                **common,
                role="control",
                owner_field_element_id=(
                    token_to_element[owner_token]
                    if owner_record is not None and owner_record.role == "field"
                    else None
                ),
                label_element_id=(token_to_element[labels[0]] if labels else None),
                control_type=str(record.data["control_type"]),
                state=str(record.data["state"]),
                origin=str(record.data["origin"]),
            )
            element_type = "form_control"
            element_value = None
        else:
            raise ValueError("unexpected form semantic record role")
        semantic_elements.append(
            ElementRecord(
                id=element_id,
                page_id=page.id,
                type=element_type,
                value=element_value,
                bbox_ids=[bbox_id_by_token[token]],
                evidence_ids=evidence_ids_by_token[token],
                form_semantics=descriptor,
                presentation_role="subordinate",
                properties={"form_policy": POLICY_ID},
            )
        )

    ir.elements.extend(semantic_elements)
    page.element_ids.extend(element.id for element in semantic_elements)
    anchor_regions = [
        region
        for region in ir.regions
        if region.page_id == page.id
        and candidate.anchor_element_id in region.element_ids
    ]
    if len(anchor_regions) != 1:
        raise ValueError("form semantic anchor has no unique page region")
    anchor_regions[0].element_ids.extend(
        element.id for element in semantic_elements
    )
    ir.relationships.extend(relationship_records)

    common_public: dict[str, dict[str, Any]] = {}
    for token, element_id in token_to_element.items():
        role = "group" if token == group_token else record_by_token[token].role
        common_public[token] = {
            "id": token_to_record[token],
            "element_id": element_id,
            "page_index": candidate.page_index,
            "bbox": FormBBox(
                x=bbox_values_by_token[token][0],
                y=bbox_values_by_token[token][1],
                width=bbox_values_by_token[token][2],
                height=bbox_values_by_token[token][3],
            ),
            "evidence_methods": [
                method
                for method in ("native", "vector", "embedded")
                if method
                in {
                    "native"
                    if ref[0]
                    in {"character_range", "field", "widget", "annotation"}
                    else "vector"
                    for ref in refs_by_token[token]
                }
            ],
            "source_objects": _public_source_objects(refs_by_token[token]),
            "confidence_dimensions": _confidence_dimensions(
                transcription=role in {"label", "key_value_pair", "value_region"}
            ),
            "concern_codes": list(
                candidate.concern_codes
                if token == group_token
                else record_by_token[token].concern_codes
            ),
            "relationship_ids": incident[token],
        }

    role_tokens: dict[str, list[str]] = {
        role: []
        for role in ("field", "label", "value_region", "control", "key_value_pair")
    }
    for record in candidate.records:
        role_tokens[record.role].append(record.token)
    public_group = PublicFormGroup(
        **common_public[group_token],
        group_key=candidate.group_key,
        status=candidate.status,
        interactivity=candidate.interactivity,
        canonical_mode=candidate.canonical_mode,
        anchor_public_item_id=candidate.anchor_public_item_id,
        anchor_element_id=candidate.anchor_element_id,
        anchor_relationship_ids=anchor_relationship_ids,
        contributor_public_item_ids=list(candidate.contributor_public_item_ids),
        contributor_element_ids=list(candidate.contributor_element_ids),
        field_ids=[token_to_record[token] for token in role_tokens["field"]],
        label_ids=[token_to_record[token] for token in role_tokens["label"]],
        value_region_ids=[
            token_to_record[token] for token in role_tokens["value_region"]
        ],
        control_ids=[token_to_record[token] for token in role_tokens["control"]],
        key_value_pair_ids=[
            token_to_record[token] for token in role_tokens["key_value_pair"]
        ],
    )
    public_fields: list[PublicFormField] = []
    public_labels: list[PublicFormLabel] = []
    public_values: list[PublicFormValueRegion] = []
    public_controls: list[PublicFormControl] = []
    public_pairs: list[PublicKeyValuePair] = []
    for record in candidate.records:
        token = record.token
        if record.role == "key_value_pair":
            [label_token] = incoming[("key_of", token)]
            [value_token] = incoming[("value_of", token)]
            public_pairs.append(
                PublicKeyValuePair(
                    **common_public[token],
                    group_id=token_to_record[group_token],
                    pair_key=record.key,
                    key_label_id=token_to_record[label_token],
                    value_region_id=token_to_record[value_token],
                    key=str(record.data["key"]),
                    value=str(record.data["value"]),
                    value_state="present",
                    key_source_item_id=str(record.data["key_source_item_id"]),
                    value_source_item_id=str(record.data["value_source_item_id"]),
                )
            )
        elif record.role == "label":
            public_labels.append(
                PublicFormLabel(
                    **common_public[token],
                    group_id=token_to_record[group_token],
                    label_role=str(record.data["label_role"]),
                    text=str(record.data["text"]),
                    raw_text=str(record.data["raw_text"]),
                    label_of_ids=[
                        token_to_record[value]
                        for value in outgoing.get(("label_of", token), [])
                    ],
                    key_of_ids=[
                        token_to_record[value]
                        for value in outgoing.get(("key_of", token), [])
                    ],
                )
            )
        elif record.role == "value_region":
            [owner_token] = outgoing[("value_of", token)]
            owner_record = record_by_token[owner_token]
            public_values.append(
                PublicFormValueRegion(
                    **common_public[token],
                    group_id=token_to_record[group_token],
                    owner_id=token_to_record[owner_token],
                    excluded_label_ids=[
                        token_to_record[value]
                        for value in (
                            incoming.get(("label_of", owner_token), [])
                            if owner_record.role == "field"
                            else []
                        )
                    ],
                    value=record.data.get("value"),
                    value_state=str(record.data["value_state"]),
                )
            )
        elif record.role == "field":
            [value_token] = incoming[("value_of", token)]
            public_fields.append(
                PublicFormField(
                    **common_public[token],
                    group_id=token_to_record[group_token],
                    field_key=record.key,
                    label_ids=[
                        token_to_record[value]
                        for value in incoming.get(("label_of", token), [])
                    ],
                    value_region_id=token_to_record[value_token],
                    control_ids=[
                        token_to_record[value]
                        for value in incoming.get(("control_of", token), [])
                    ],
                    value=record.data.get("value"),
                    value_state=str(record.data["value_state"]),
                )
            )
        elif record.role == "control":
            [owner_token] = outgoing[("control_of", token)]
            owner_record = record_by_token.get(owner_token)
            labels = incoming.get(("label_of", token), [])
            public_controls.append(
                PublicFormControl(
                    **common_public[token],
                    group_id=token_to_record[group_token],
                    owner_field_id=(
                        token_to_record[owner_token]
                        if owner_record is not None and owner_record.role == "field"
                        else None
                    ),
                    label_id=(token_to_record[labels[0]] if labels else None),
                    control_type=str(record.data["control_type"]),
                    state=str(record.data["state"]),
                    origin=str(record.data["origin"]),
                )
            )

    # ``RelationshipRecord`` has already validated every closed enum and
    # endpoint field above.  Build its isomorphic public payload directly to
    # avoid validating and serializing the same bounded edge a second time.
    descriptor_payloads = [
        {
            "id": relationship.id,
            "type": relationship.type.value,
            "source_id": relationship.source_id,
            "target_id": relationship.target_id,
            "evidence_ids": list(relationship.evidence_ids),
            "canonical_inert": True,
        }
        for relationship in relationship_records
    ]
    legacy = dict(anchor_legacy)
    legacy["layout_forms_projected"] = True
    legacy["form_policy"] = POLICY_ID
    legacy["form_group"] = public_group.model_dump(mode="json")
    for key, values in (
        ("form_fields", public_fields),
        ("form_labels", public_labels),
        ("form_value_regions", public_values),
        ("form_controls", public_controls),
        ("form_key_value_pairs", public_pairs),
    ):
        if values:
            legacy[key] = [value.model_dump(mode="json") for value in values]
    prior_relationships = legacy.get("relationships")
    merged = (
        list(prior_relationships)
        if isinstance(prior_relationships, list)
        else []
    )
    merged.extend(descriptor_payloads)
    legacy["relationships"] = merged
    compact_sidecar = {
        key: legacy[key]
        for key in _PUBLIC_FORM_KEYS
        if key in legacy
    }
    compact_sidecar["relationships"] = descriptor_payloads
    if (
        _compact_public_sidecar_size(
            compact_sidecar,
            limit=MAX_PUBLIC_GROUP_BYTES,
        )
        > MAX_PUBLIC_GROUP_BYTES
    ):
        raise ValueError("form public group JSON limit exceeded")
    anchor.properties["legacy_item"] = legacy


@dataclass(frozen=True, slots=True)
class _PageMutationSnapshot:
    bbox_count: int
    evidence_count: int
    element_count: int
    relationship_count: int
    concern_count: int
    page_element_counts: Mapping[str, int]
    region_element_counts: Mapping[str, int]
    anchor_properties: Mapping[str, Mapping[str, Any]]


def _snapshot_page_mutations(
    ir: DocumentIR,
    candidates: Sequence[_GroupCandidate],
) -> _PageMutationSnapshot:
    anchor_ids = {
        candidate.anchor_element_id for candidate in candidates
    }
    return _PageMutationSnapshot(
        bbox_count=len(ir.bboxes),
        evidence_count=len(ir.evidence),
        element_count=len(ir.elements),
        relationship_count=len(ir.relationships),
        concern_count=len(ir.concerns),
        page_element_counts={
            page.id: len(page.element_ids) for page in ir.pages
        },
        region_element_counts={
            region.id: len(region.element_ids) for region in ir.regions
        },
        anchor_properties={
            element.id: deepcopy(element.properties)
            for element in ir.elements
            if element.id in anchor_ids
        },
    )


def _restore_page_mutations(
    ir: DocumentIR,
    snapshot: _PageMutationSnapshot,
) -> None:
    del ir.bboxes[snapshot.bbox_count :]
    del ir.evidence[snapshot.evidence_count :]
    del ir.elements[snapshot.element_count :]
    del ir.relationships[snapshot.relationship_count :]
    del ir.concerns[snapshot.concern_count :]
    for page in ir.pages:
        prior_count = snapshot.page_element_counts.get(page.id)
        if prior_count is not None:
            del page.element_ids[prior_count:]
    for region in ir.regions:
        prior_count = snapshot.region_element_counts.get(region.id)
        if prior_count is not None:
            del region.element_ids[prior_count:]
    for element in ir.elements:
        prior_properties = snapshot.anchor_properties.get(element.id)
        if prior_properties is not None:
            element.properties.clear()
            element.properties.update(deepcopy(prior_properties))


def _page_candidates_within_limits(
    candidates: Sequence[_GroupCandidate],
) -> bool:
    if len(candidates) > MAX_FORM_GROUPS_PER_PAGE:
        return False
    semantic_count = len(candidates)
    relationship_count = 0
    page_class_counts: Counter[str] = Counter()
    budget = _PROJECTION_BUDGET.get()
    for candidate_index, candidate in enumerate(candidates):
        if len(candidate.concern_codes) > MAX_FORM_CONCERNS_PER_GROUP or any(
            len(record.concern_codes) > MAX_FORM_CONCERNS_PER_GROUP
            for record in candidate.records
        ):
            return False
        group_counts = Counter(
            record.role for record in candidate.records
        )
        if any(
            group_counts[role] > limit
            for role, limit in _FORM_GROUP_ROLE_LIMITS.items()
        ):
            return False
        semantic_count += len(candidate.records)
        relationship_count += len(candidate.relationships)
        page_class_counts.update(
            {
                role: group_counts[role]
                for role in ("field", "control", "key_value_pair")
            }
        )
        if budget is not None and candidate_index % 64 == 0:
            budget.check_deadline()
    return (
        semantic_count <= MAX_FORM_SEMANTIC_RECORDS_PER_PAGE
        and relationship_count <= MAX_FORM_RELATIONSHIPS_PER_PAGE
        and all(
            page_class_counts[role] <= MAX_FORM_CLASS_RECORDS_PER_PAGE
            for role in ("field", "control", "key_value_pair")
        )
    )


def _document_candidates_within_limits(
    candidates: Sequence[_GroupCandidate],
) -> bool:
    if len(candidates) > MAX_FORM_GROUPS_PER_DOCUMENT:
        return False
    semantic_count = len(candidates)
    relationship_count = 0
    class_counts: Counter[str] = Counter()
    budget = _PROJECTION_BUDGET.get()
    for candidate_index, candidate in enumerate(candidates):
        semantic_count += len(candidate.records)
        relationship_count += len(candidate.relationships)
        class_counts.update(
            record.role
            for record in candidate.records
            if record.role in {"field", "control", "key_value_pair"}
        )
        if budget is not None and candidate_index % 64 == 0:
            budget.check_deadline()
    return (
        semantic_count <= MAX_FORM_SEMANTIC_RECORDS_PER_DOCUMENT
        and relationship_count <= MAX_FORM_RELATIONSHIPS_PER_DOCUMENT
        and all(
            class_counts[role] <= MAX_FORM_CLASS_RECORDS_PER_DOCUMENT
            for role in ("field", "control", "key_value_pair")
        )
    )


def _presentation_text_limit_rejections(
    ir: DocumentIR,
) -> tuple[set[int], bool]:
    """Preflight inspected presentation text before candidate construction."""

    lookup = _projection_ir_lookup(ir)
    rejected_pages: set[int] = set()
    document_bytes = 0
    for page in sorted(ir.pages, key=lambda value: value.page_index):
        page_bytes = 0
        budget = _PROJECTION_BUDGET.get()
        for index, element_id in enumerate(
            page.presentation_element_ids
        ):
            if budget is not None and index % 256 == 0:
                budget.check_deadline()
            element = lookup.elements.get(element_id)
            if element is None:
                continue
            legacy = _legacy_item(element)
            value = legacy.get("value") if legacy is not None else None
            if not isinstance(value, str):
                continue
            try:
                value_bytes = len(value.encode("utf-8"))
            except UnicodeError:
                rejected_pages.add(page.page_index)
                continue
            document_bytes += value_bytes
            page_bytes += value_bytes
            if value_bytes > MAX_TEXT_BYTES:
                rejected_pages.add(page.page_index)
            if document_bytes > MAX_PRESENTATION_TEXT_BYTES_PER_DOCUMENT:
                return rejected_pages, True
        if page_bytes > MAX_PRESENTATION_TEXT_BYTES_PER_PAGE:
            rejected_pages.add(page.page_index)
    return rejected_pages, False


def _projection_working_copy(
    predecessor: DocumentIR,
    candidates: Sequence[_GroupCandidate],
) -> DocumentIR:
    """Copy only graph containers and records mutated by US06 projection.

    The returned graph is fully revalidated into an independent ``DocumentIR``
    before it can escape ``project_form_semantics``.  Keeping immutable
    predecessor records shared during construction avoids deep-copying the
    complete accepted IR merely to append a bounded semantic overlay.
    """

    anchor_ids = {
        candidate.anchor_element_id for candidate in candidates
    }
    return predecessor.model_copy(
        update={
            "bboxes": list(predecessor.bboxes),
            "pages": [
                page.model_copy(
                    update={
                        "region_ids": list(page.region_ids),
                        "element_ids": list(page.element_ids),
                        "presentation_element_ids": list(
                            page.presentation_element_ids
                        ),
                    }
                )
                for page in predecessor.pages
            ],
            "regions": [
                region.model_copy(
                    update={"element_ids": list(region.element_ids)}
                )
                for region in predecessor.regions
            ],
            "elements": [
                element.model_copy(deep=True)
                if element.id in anchor_ids
                else element
                for element in predecessor.elements
            ],
            "evidence": list(predecessor.evidence),
            "relationships": list(predecessor.relationships),
            "concerns": list(predecessor.concerns),
        }
    )


def project_form_semantics(
    ir: DocumentIR,
    evidence: FormEvidenceReport | None,
    metrics: MutableMapping[str, float] | None = None,
) -> DocumentIR:
    """Project validated source evidence atomically onto the shared IR."""

    started = time.perf_counter()
    extraction_ms = 0.0
    if metrics is not None:
        try:
            seeded = float(metrics.get("extraction_ms", 0.0))
        except (TypeError, ValueError):
            seeded = 0.0
        if math.isfinite(seeded) and seeded >= 0:
            extraction_ms = seeded
    if extraction_ms == 0.0 and isinstance(evidence, FormEvidenceReport):
        extraction_ms = evidence.extraction_ms

    predecessor = ir
    projection_budget = _ProjectionBudget(
        started_at=started,
        comparisons_by_page={},
    )
    candidate_budget = _ProjectionCandidateBudget()
    budget_token = _PROJECTION_BUDGET.set(projection_budget)
    candidate_budget_token = _PROJECTION_CANDIDATE_BUDGET.set(
        candidate_budget
    )
    canonical_owner_token = _PROJECTION_CANONICAL_OWNERS.set({})
    ir_lookup_token = _PROJECTION_IR_LOOKUPS.set({})
    presentation_index_token = _PROJECTION_PRESENTATION_INDEXES.set({})
    text_fragment_token = _TEXT_FRAGMENT_CACHE.set({})
    static_control_box_token = _STATIC_CONTROL_BOX_CACHE.set({})
    candidate_shape_token = _PROJECTION_CANDIDATE_SHAPES.set({})
    spatial_token = _PROJECTION_SPATIAL_INDEXES.set({})
    spatial_char_token = _SPATIAL_CHAR_RESULTS.set({})
    vector_index_token = _PROJECTION_VECTOR_INDEXES.set({})
    rule_edge_token = _RULE_EDGE_INDEXES.set({})
    cell_source_token = _CELL_SOURCE_OBJECT_CACHE.set({})
    try:
        if evidence is None:
            return _with_form_concern(
                predecessor,
                "form_source_evidence_unavailable",
                "Form source evidence was unavailable; projection failed closed.",
            )
        if not isinstance(evidence, FormEvidenceReport) or (
            evidence.report_version != REPORT_VERSION
            or evidence.policy_id != POLICY_ID
            or evidence.source_sha256 != predecessor.source_sha256
        ):
            return _with_form_concern(
                predecessor,
                "form_source_evidence_unavailable",
                "Form source custody validation failed; projection failed closed.",
            )
        if evidence.interactivity == "unknown":
            return _with_form_concern(
                predecessor,
                "form_interactivity_unknown",
                "Form interactivity was unknown; projection failed closed.",
            )
        if any(element.form_semantics is not None for element in predecessor.elements):
            # Direct replay over an already-projected IR is a strict no-op.
            return predecessor.model_copy(deep=True)

        rejected_pages, document_text_limit = (
            _presentation_text_limit_rejections(predecessor)
        )
        if document_text_limit:
            return _with_form_concern(
                predecessor,
                "form_projection_failed_closed",
                "Form semantics projection exceeded a document limit.",
            )

        custody_rejections: list[tuple[int, str]] = []
        candidates: list[_GroupCandidate] = []
        for source_page in evidence.pages:
            projection_budget.check_deadline()
            if source_page.page_index in rejected_pages:
                continue
            page_evidence = replace(evidence, pages=(source_page,))
            page_candidates: list[_GroupCandidate] = []
            page_custody_rejections: list[tuple[int, str]] = []
            candidate_snapshot = candidate_budget.snapshot()
            try:
                page_candidates.extend(
                    _key_value_candidates(
                        predecessor,
                        page_evidence,
                        custody_rejections=page_custody_rejections,
                    )
                )
                page_candidates.extend(
                    _static_form_candidates(predecessor, page_evidence)
                )
                page_candidates.extend(
                    _interactive_form_candidates(predecessor, page_evidence)
                )
                if not _page_candidates_within_limits(page_candidates):
                    candidate_budget.restore(candidate_snapshot)
                    rejected_pages.add(source_page.page_index)
                    continue
            except _ProjectionPageLimitError:
                candidate_budget.restore(candidate_snapshot)
                rejected_pages.add(source_page.page_index)
                continue
            except (_ProjectionDocumentLimitError, TimeoutError):
                raise
            except Exception:
                candidate_budget.restore(candidate_snapshot)
                rejected_pages.add(source_page.page_index)
                continue
            candidates.extend(page_candidates)
            custody_rejections.extend(page_custody_rejections)
            projection_budget.check_deadline()
        candidates.sort(
            key=lambda candidate: (
                candidate.page_index,
                candidate.bbox[1],
                candidate.bbox[0],
                candidate.anchor_public_item_id,
            )
        )
        if not _document_candidates_within_limits(candidates):
            return _with_form_concern(
                predecessor,
                "form_projection_failed_closed",
                "Form semantics projection exceeded a document limit.",
            )
        candidates_by_page: dict[int, list[_GroupCandidate]] = {}
        for candidate in candidates:
            candidates_by_page.setdefault(candidate.page_index, []).append(candidate)
        working = _projection_working_copy(predecessor, candidates)
        detailed_concerns_by_page: Counter[int] = Counter()
        detailed_concern_count = 0
        concerns_truncated = False
        existing_concern_keys = {
            (
                concern.code,
                concern.source_ref,
                concern.target_ref,
            )
            for concern in working.concerns
        }

        def append_detailed_concern(
            *,
            page_index: int,
            code: str,
            message: str,
            source_ref: str | None = None,
            target_ref: str | None = None,
        ) -> None:
            nonlocal detailed_concern_count, concerns_truncated
            concern_key = (code, source_ref, target_ref)
            if concern_key in existing_concern_keys:
                return
            if (
                detailed_concerns_by_page[page_index] >= 256
                or detailed_concern_count >= 1_024
            ):
                concerns_truncated = True
                return
            working.concerns.append(
                IRConcern(
                    code=code,
                    message=message,
                    source_ref=source_ref,
                    target_ref=target_ref,
                )
            )
            existing_concern_keys.add(concern_key)
            detailed_concerns_by_page[page_index] += 1
            detailed_concern_count += 1

        projection_budget.check_deadline()
        for page_index, page_candidates in candidates_by_page.items():
            projection_budget.check_deadline()
            snapshot = _snapshot_page_mutations(
                working,
                page_candidates,
            )
            try:
                for candidate in page_candidates:
                    projection_budget.check_deadline()
                    _materialize_group(working, candidate)
                    projection_budget.check_deadline()
            except TimeoutError:
                raise
            except Exception:
                _restore_page_mutations(working, snapshot)
                append_detailed_concern(
                    page_index=page_index,
                    code="form_projection_failed_closed",
                    message=(
                        "Form semantic projection failed closed for a page."
                    ),
                    source_ref=f"page:{page_index}",
                )
                continue
            for candidate in page_candidates:
                group_element_id = _stable_id(
                    "form-el",
                    working.source_sha256,
                    candidate.page_index,
                    "group",
                    _rounded_bbox(candidate.bbox),
                    candidate.source_objects,
                    candidate.group_key,
                )
                for code in candidate.concern_codes:
                    append_detailed_concern(
                        page_index=page_index,
                        code=code,
                        message=(
                            "Form semantics retained a bounded source concern."
                        ),
                        source_ref=group_element_id,
                        target_ref=candidate.anchor_element_id,
                    )
        for page_index in sorted(rejected_pages):
            append_detailed_concern(
                page_index=page_index,
                code="form_projection_failed_closed",
                message="Form semantic projection failed closed for a page.",
                source_ref=f"page:{page_index}",
            )
        for page_index, anchor_element_id in tuple(
            dict.fromkeys(custody_rejections)
        ):
            append_detailed_concern(
                page_index=page_index,
                code="form_projection_failed_closed",
                message=(
                    "A form replacement failed canonical custody checks."
                ),
                source_ref=anchor_element_id,
            )
        if concerns_truncated and not any(
            key[0] == "form_concerns_truncated"
            for key in existing_concern_keys
        ):
            working.concerns.append(
                IRConcern(
                    code="form_concerns_truncated",
                    message="Additional form concerns were suppressed.",
                )
            )
        projection_budget.check_deadline()
        projected = DocumentIR.model_validate(
            working.model_dump(mode="json")
        )
        projection_budget.check_deadline()
        return projected
    except Exception:
        return _with_form_concern(
            predecessor,
            "form_projection_failed_closed",
            "Form semantics projection failed closed.",
        )
    finally:
        _RULE_EDGE_INDEXES.reset(rule_edge_token)
        _CELL_SOURCE_OBJECT_CACHE.reset(cell_source_token)
        _SPATIAL_CHAR_RESULTS.reset(spatial_char_token)
        _PROJECTION_SPATIAL_INDEXES.reset(spatial_token)
        _PROJECTION_VECTOR_INDEXES.reset(vector_index_token)
        _PROJECTION_CANDIDATE_SHAPES.reset(candidate_shape_token)
        _STATIC_CONTROL_BOX_CACHE.reset(static_control_box_token)
        _TEXT_FRAGMENT_CACHE.reset(text_fragment_token)
        _PROJECTION_PRESENTATION_INDEXES.reset(presentation_index_token)
        _PROJECTION_IR_LOOKUPS.reset(ir_lookup_token)
        _PROJECTION_CANONICAL_OWNERS.reset(canonical_owner_token)
        _PROJECTION_CANDIDATE_BUDGET.reset(candidate_budget_token)
        _PROJECTION_BUDGET.reset(budget_token)
        projection_ms = round((time.perf_counter() - started) * 1000.0, 3)
        if metrics is not None:
            metrics["extraction_ms"] = round(extraction_ms, 3)
            metrics["projection_ms"] = projection_ms
            metrics["total_ms"] = round(extraction_ms + projection_ms, 3)


def _with_form_concern(
    ir: DocumentIR,
    code: str,
    message: str,
    *,
    source_ref: str | None = None,
) -> DocumentIR:
    working = ir.model_copy(deep=True)
    if not any(
        concern.code == code and concern.source_ref == source_ref
        for concern in working.concerns
    ):
        working.concerns.append(
            IRConcern(code=code, message=message, source_ref=source_ref)
        )
    return DocumentIR.model_validate(working.model_dump(mode="json"))


def _static_form_candidates(
    ir: DocumentIR,
    evidence: FormEvidenceReport,
) -> tuple[_GroupCandidate, ...]:
    candidates: list[_GroupCandidate] = []
    for page in evidence.pages:
        if page.interactivity not in {"static", "mixed", "interactive"}:
            continue
        cells = _minimal_ruled_cells(page)
        if len(cells) > MAX_CANDIDATE_SHAPES_PER_PAGE:
            raise _ProjectionPageLimitError(page.page_index)
        shape_counts = _PROJECTION_CANDIDATE_SHAPES.get()
        if shape_counts is not None:
            shape_counts[page.page_index] = {
                _rounded_bbox(cell) for cell in cells
            }
        candidate = _static_page_form_candidate(ir, page, cells)
        if not candidate and page.interactivity == "static":
            candidate = _standalone_static_control_candidates(ir, page)
        candidates.extend(candidate)
    return tuple(candidates)


def _standalone_static_control_candidates(
    ir: DocumentIR,
    page: FormSourcePage,
) -> tuple[_GroupCandidate, ...]:
    provisional_key = "static-controls"
    controls, labels = _detect_static_controls(
        page,
        group_bbox=(0.0, 0.0, page.width, page.height),
        group_key=provisional_key,
    )
    if not controls:
        return ()
    if len(controls) > MAX_FORM_CONTROLS_PER_GROUP:
        raise _ProjectionPageLimitError(page.page_index)
    label_token_lists = [
        _slug(label.text).split("-") for label in labels if label.text.strip()
    ]
    common_tokens = (
        set(label_token_lists[0]).intersection(*map(set, label_token_lists[1:]))
        if label_token_lists
        else set()
    )
    group_key = (
        "-".join(
            token for token in label_token_lists[0] if token in common_tokens
        )
        if common_tokens
        else provisional_key
    )
    source_bboxes = [control.bbox for control in controls]
    source_bboxes.extend(label.bbox for label in labels)
    contributor_data = _interactive_group_contributors(
        ir,
        page_index=page.page_index,
        source_bboxes=source_bboxes,
    )
    if contributor_data is None:
        return ()
    (
        anchor_public_item_id,
        anchor_element_id,
        contributor_public_item_ids,
        contributor_element_ids,
    ) = contributor_data
    labels_by_key = {label.key: label for label in labels}
    label_count = sum(
        control.label_key in labels_by_key
        for control in controls
        if control.label_key is not None
    )
    _reserve_projection_candidate(
        page_index=page.page_index,
        roles={
            "control": len(controls),
            "label": label_count,
        },
        relationships=2 * (len(controls) + label_count),
    )
    records: list[_RecordCandidate] = []
    relationships: list[tuple[str, str, str]] = []
    sources: list[_SourceIdentity] = []
    for control in controls:
        control_token = f"control:{control.key}"
        label = labels_by_key.get(control.label_key or "")
        if label is not None:
            label_token = f"label:{control.key}"
            records.append(
                _RecordCandidate(
                    token=label_token,
                    role="label",
                    key=control.key,
                    bbox=label.bbox,
                    source_objects=label.source_objects,
                    data={
                        "label_role": "control",
                        "text": label.text,
                        "raw_text": label.raw_text,
                    },
                )
            )
            relationships.extend(
                (
                    ("contains", f"group:{group_key}", label_token),
                    ("label_of", label_token, control_token),
                )
            )
        records.append(
            _RecordCandidate(
                token=control_token,
                role="control",
                key=control.key,
                bbox=control.bbox,
                source_objects=control.source_objects,
                data={
                    "control_type": "checkbox",
                    "state": control.state,
                    "origin": "static_vector",
                },
                concern_codes=control.concern_codes,
            )
        )
        sources.extend(control.source_objects)
        relationships.extend(
            (
                ("contains", f"group:{group_key}", control_token),
                ("control_of", control_token, f"group:{group_key}"),
            )
        )
    return (
        _GroupCandidate(
            group_key=group_key,
            page_index=page.page_index,
            bbox=_union_bboxes(source_bboxes),
            status=(
                "unresolved"
                if any(control.state == "ambiguous" for control in controls)
                else "resolved"
            ),
            interactivity="static",
            canonical_mode="inert",
            anchor_public_item_id=anchor_public_item_id,
            anchor_element_id=anchor_element_id,
            contributor_public_item_ids=contributor_public_item_ids,
            contributor_element_ids=contributor_element_ids,
            records=tuple(records),
            relationships=tuple(relationships),
            source_objects=_bounded_source_identities(
                sources,
                page_index=page.page_index,
            ),
        ),
    )


def _interactive_control_label(
    page: FormSourcePage,
    control: SourceInteractiveControl,
    fragments: Sequence[_TextFragment],
) -> tuple[
    str,
    str,
    tuple[float, float, float, float],
    tuple[_SourceIdentity, ...],
] | None:
    x, y, width, height = control.bbox
    right = x + width
    bottom = y + height
    budget = _PROJECTION_BUDGET.get()
    comparisons = 0
    eligible: list[_TextFragment] = []
    for fragment in fragments:
        comparisons += 1
        if budget is not None:
            budget.account_comparisons(page.page_index, 1)
        elif comparisons > MAX_COMPARISONS_PER_PAGE:
            raise _ProjectionPageLimitError(page.page_index)
        if (
            0.5 <= fragment.bbox[0] - right <= 96
            and fragment.bbox[1] <= bottom + 4
            and fragment.bbox[1] + fragment.bbox[3] >= y - 1.5
        ):
            eligible.append(fragment)
    if budget is not None:
        budget.check_deadline()
    if not eligible:
        return None
    ranked = sorted(
        eligible,
        key=lambda fragment: (
            fragment.bbox[0] - right,
            abs(
                (fragment.bbox[1] + fragment.bbox[3] / 2)
                - (y + height / 2)
            ),
            fragment.bbox[0],
        ),
    )
    if len(ranked) > 1:
        first_gap = ranked[0].bbox[0] - right
        second_gap = ranked[1].bbox[0] - right
        if abs(first_gap - second_gap) <= 0.5:
            return None
    chosen = ranked[0]
    spatial = _spatial_chars(page, chosen.bbox)
    if spatial is None or not _bounded_text_value(spatial[0]):
        return None
    return spatial


def _interactive_group_contributors(
    ir: DocumentIR,
    *,
    page_index: int,
    source_bboxes: Sequence[tuple[float, float, float, float]],
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]] | None:
    index = _projection_presentation_index(ir, page_index)
    if not index.records:
        return None
    candidates_by_order: dict[int, _PresentationCandidate] = {}
    for source_bbox in source_bboxes:
        for candidate in index.intersecting(source_bbox):
            if (
                candidate.source_order not in candidates_by_order
                and len(candidates_by_order) >= 64
            ):
                raise _ProjectionPageLimitError(page_index)
            candidates_by_order[candidate.source_order] = candidate
    candidates = sorted(
        candidates_by_order.values(),
        key=lambda value: value.source_order,
    )
    if not candidates:
        spatial_union = _union_bboxes(source_bboxes)

        def distance(
            bbox: tuple[float, float, float, float],
        ) -> tuple[float, float]:
            horizontal = max(
                0.0,
                spatial_union[0] - (bbox[0] + bbox[2]),
                bbox[0] - (spatial_union[0] + spatial_union[2]),
            )
            vertical = max(
                0.0,
                spatial_union[1] - (bbox[1] + bbox[3]),
                bbox[1] - (spatial_union[1] + spatial_union[3]),
            )
            return horizontal + vertical, vertical

        _charge_projection_comparisons(
            page_index,
            len(index.records),
        )
        nearest = min(
            index.records,
            key=lambda value: (
                distance(value.bbox),
                value.source_order,
            ),
        )
        candidates.append(nearest)
    contributor_public_ids = tuple(
        str(value.legacy["id"]) for value in candidates
    )
    contributor_element_ids = tuple(
        value.element.id for value in candidates
    )
    return (
        contributor_public_ids[0],
        contributor_element_ids[0],
        contributor_public_ids,
        contributor_element_ids,
    )


def _interactive_form_candidates(
    ir: DocumentIR,
    evidence: FormEvidenceReport,
) -> tuple[_GroupCandidate, ...]:
    candidates: list[_GroupCandidate] = []
    for page in evidence.pages:
        if page.interactivity == "unknown" or not page.interactive_controls:
            continue
        if (
            len(page.interactive_controls) > MAX_FORM_CONTROLS_PER_GROUP
        ):
            raise _ProjectionPageLimitError(page.page_index)
        group_key = "interactive-controls"
        static_controls: tuple[_DetectedControl, ...] = ()
        static_labels: tuple[_DetectedLabel, ...] = ()
        if page.interactivity == "mixed":
            static_controls, static_labels = _detect_static_controls(
                page,
                group_bbox=(0.0, 0.0, page.width, page.height),
                group_key=group_key,
            )
        if (
            len(page.interactive_controls) + len(static_controls)
            > MAX_FORM_CONTROLS_PER_GROUP
        ):
            raise _ProjectionPageLimitError(page.page_index)
        fragments = _text_fragments(page)
        labels_by_annotation = {
            control.annotation_index: _interactive_control_label(
                page, control, fragments
            )
            for control in page.interactive_controls
        }
        source_bboxes = [control.bbox for control in page.interactive_controls]
        source_bboxes.extend(control.bbox for control in static_controls)
        source_bboxes.extend(
            label[2]
            for label in labels_by_annotation.values()
            if label is not None
        )
        source_bboxes.extend(label.bbox for label in static_labels)
        contributor_data = _interactive_group_contributors(
            ir,
            page_index=page.page_index,
            source_bboxes=source_bboxes,
        )
        if contributor_data is None:
            continue
        (
            anchor_public_item_id,
            anchor_element_id,
            contributor_public_item_ids,
            contributor_element_ids,
        ) = contributor_data
        static_labels_by_key = {
            label.key: label for label in static_labels
        }
        label_count = sum(
            label is not None for label in labels_by_annotation.values()
        ) + sum(
            control.label_key in static_labels_by_key
            for control in static_controls
            if control.label_key is not None
        )
        control_count = len(page.interactive_controls) + len(static_controls)
        _reserve_projection_candidate(
            page_index=page.page_index,
            roles={
                "control": control_count,
                "label": label_count,
            },
            relationships=2 * (control_count + label_count),
        )
        records: list[_RecordCandidate] = []
        relationships: list[tuple[str, str, str]] = []
        group_sources: list[_SourceIdentity] = []
        for control in page.interactive_controls:
            key = f"control-{control.annotation_index}-{control.widget_ref_digest[:12]}"
            control_token = f"control:{key}"
            control_sources: tuple[_SourceIdentity, ...] = (
                ("widget", control.widget_ref_digest, None),
                ("field", control.field_ref_digest, None),
            )
            group_sources.extend(control_sources)
            label = labels_by_annotation[control.annotation_index]
            label_token: str | None = None
            if label is not None:
                text, raw_text, label_bbox, label_sources = label
                label_token = f"label:{key}"
                records.append(
                    _RecordCandidate(
                        token=label_token,
                        role="label",
                        key=key,
                        bbox=_rounded_bbox(label_bbox),
                        source_objects=label_sources,
                        data={
                            "label_role": "control",
                            "text": text,
                            "raw_text": raw_text,
                        },
                    )
                )
                relationships.extend(
                    (
                        ("contains", f"group:{group_key}", label_token),
                        ("label_of", label_token, control_token),
                    )
                )
            records.append(
                _RecordCandidate(
                    token=control_token,
                    role="control",
                    key=key,
                    bbox=control.bbox,
                    source_objects=control_sources,
                    data={
                        "control_type": control.control_type,
                        "state": control.state,
                        "origin": "interactive_widget",
                    },
                    concern_codes=control.concern_codes,
                )
            )
            relationships.extend(
                (
                    ("contains", f"group:{group_key}", control_token),
                    ("control_of", control_token, f"group:{group_key}"),
                )
            )
        for control in static_controls:
            key = f"static-{control.key}"
            control_token = f"control:{key}"
            label = static_labels_by_key.get(control.label_key or "")
            if label is not None:
                label_token = f"label:{key}"
                records.append(
                    _RecordCandidate(
                        token=label_token,
                        role="label",
                        key=key,
                        bbox=label.bbox,
                        source_objects=label.source_objects,
                        data={
                            "label_role": "control",
                            "text": label.text,
                            "raw_text": label.raw_text,
                        },
                    )
                )
                relationships.extend(
                    (
                        ("contains", f"group:{group_key}", label_token),
                        ("label_of", label_token, control_token),
                    )
                )
            records.append(
                _RecordCandidate(
                    token=control_token,
                    role="control",
                    key=key,
                    bbox=control.bbox,
                    source_objects=control.source_objects,
                    data={
                        "control_type": "checkbox",
                        "state": control.state,
                        "origin": "static_vector",
                    },
                    concern_codes=control.concern_codes,
                )
            )
            group_sources.extend(control.source_objects)
            relationships.extend(
                (
                    ("contains", f"group:{group_key}", control_token),
                    ("control_of", control_token, f"group:{group_key}"),
                )
            )
        candidates.append(
            _GroupCandidate(
                group_key=group_key,
                page_index=page.page_index,
                bbox=_union_bboxes(source_bboxes),
                status=(
                    "unresolved"
                    if any(
                        control.state == "ambiguous"
                        for control in page.interactive_controls
                    )
                    or any(control.state == "ambiguous" for control in static_controls)
                    else "resolved"
                ),
                interactivity=page.interactivity,
                canonical_mode="inert",
                anchor_public_item_id=anchor_public_item_id,
                anchor_element_id=anchor_element_id,
                contributor_public_item_ids=contributor_public_item_ids,
                contributor_element_ids=contributor_element_ids,
                records=tuple(records),
                relationships=tuple(relationships),
                source_objects=_bounded_source_identities(
                    group_sources,
                    page_index=page.page_index,
                ),
            )
        )
    return tuple(candidates)


@dataclass(frozen=True, slots=True)
class _RuleEdge:
    orientation: Literal["h", "v"]
    coordinate: float
    start: float
    end: float
    source_kind: Literal["line", "rect"]
    source_index: int


def _build_rule_edges(page: FormSourcePage) -> tuple[_RuleEdge, ...]:
    edges: list[_RuleEdge] = []
    for vector in page.vectors:
        if vector.kind == "line":
            if (
                _millipoints(vector.bottom)
                - _millipoints(vector.top)
                <= 150
            ):
                edges.append(
                    _RuleEdge(
                        "h",
                        round((vector.top + vector.bottom) / 2, 3),
                        round(vector.x0, 3),
                        round(vector.x1, 3),
                        "line",
                        vector.index,
                    )
                )
            elif (
                _millipoints(vector.x1)
                - _millipoints(vector.x0)
                <= 150
            ):
                edges.append(
                    _RuleEdge(
                        "v",
                        round((vector.x0 + vector.x1) / 2, 3),
                        round(vector.top, 3),
                        round(vector.bottom, 3),
                        "line",
                        vector.index,
                    )
                )
        elif vector.kind == "rect":
            edges.extend(
                (
                    _RuleEdge(
                        "h",
                        round(vector.top, 3),
                        round(vector.x0, 3),
                        round(vector.x1, 3),
                        "rect",
                        vector.index,
                    ),
                    _RuleEdge(
                        "h",
                        round(vector.bottom, 3),
                        round(vector.x0, 3),
                        round(vector.x1, 3),
                        "rect",
                        vector.index,
                    ),
                    _RuleEdge(
                        "v",
                        round(vector.x0, 3),
                        round(vector.top, 3),
                        round(vector.bottom, 3),
                        "rect",
                        vector.index,
                    ),
                    _RuleEdge(
                        "v",
                        round(vector.x1, 3),
                        round(vector.top, 3),
                        round(vector.bottom, 3),
                        "rect",
                        vector.index,
                    ),
                )
            )
    return tuple(edges)


@dataclass(slots=True)
class _CoverageGroup:
    intervals: tuple[tuple[float, float], ...]
    intervals_milli: tuple[tuple[int, int], ...]
    starts: tuple[float, ...]
    ends: tuple[float, ...]
    starts_milli: tuple[int, ...]
    ends_milli: tuple[int, ...]
    chains_milli: tuple[tuple[int, int], ...]
    prefix_lengths: tuple[int, ...]
    large_gap_prefix: tuple[int, ...]

    def covers(self, start: float, end: float) -> bool:
        return self.covers_milli(
            _millipoints(start),
            _millipoints(end),
        )

    def covers_milli(self, start_milli: int, end_milli: int) -> bool:
        if len(self.intervals_milli) == 1:
            interval_start, interval_end = self.intervals_milli[0]
            if interval_end <= start_milli or interval_start >= end_milli:
                return False
            leading_gap = max(0, interval_start - start_milli)
            trailing_gap = max(0, end_milli - interval_end)
            if leading_gap > 150 or trailing_gap > 150:
                return False
            covered = max(
                0,
                min(end_milli, interval_end)
                - max(start_milli, interval_start),
            )
            return covered * 100 >= 95 * (end_milli - start_milli)
        first = bisect_right(self.ends_milli, start_milli)
        last = bisect_left(self.starts_milli, end_milli)
        if first >= last:
            return False
        leading_gap_milli = max(
            0,
            self.intervals_milli[first][0] - start_milli,
        )
        trailing_gap_milli = max(
            0,
            end_milli - self.intervals_milli[last - 1][1],
        )
        if (
            leading_gap_milli > 150
            or trailing_gap_milli > 150
            or self.large_gap_prefix[last - 1]
            - self.large_gap_prefix[first]
            > 0
        ):
            return False
        covered_milli = (
            self.prefix_lengths[last] - self.prefix_lengths[first]
        )
        covered_milli -= max(
            0,
            start_milli - self.intervals_milli[first][0],
        )
        covered_milli -= max(
            0,
            self.intervals_milli[last - 1][1] - end_milli,
        )
        span_milli = end_milli - start_milli
        return covered_milli * 100 >= 95 * span_milli


def _coverage_groups(
    groups: Mapping[float, tuple[_RuleEdge, ...]],
    *,
    page_index: int,
) -> Mapping[float, _CoverageGroup]:
    indexed: dict[float, _CoverageGroup] = {}
    budget = _PROJECTION_BUDGET.get()
    for coordinate, edges in groups.items():
        _charge_projection_comparisons(page_index, len(edges))
        merged: list[tuple[float, float]] = []
        for edge_index, edge in enumerate(edges):
            if not merged or edge.start > merged[-1][1]:
                merged.append((edge.start, edge.end))
            elif edge.end > merged[-1][1]:
                merged[-1] = (merged[-1][0], edge.end)
            if budget is not None and edge_index % 256 == 0:
                budget.check_deadline()
        prefix = [0]
        for interval_start, interval_end in merged:
            prefix.append(
                prefix[-1]
                + _millipoints(interval_end)
                - _millipoints(interval_start)
            )
        large_gap_prefix = [0]
        for interval_index in range(len(merged) - 1):
            gap_milli = int(
                round(
                    (
                        merged[interval_index + 1][0]
                        - merged[interval_index][1]
                    )
                    * 1_000
                )
            )
            large_gap_prefix.append(
                large_gap_prefix[-1] + (gap_milli > 150)
            )
        interval_millis = tuple(
            (_millipoints(start), _millipoints(end))
            for start, end in merged
        )
        chains_milli: list[tuple[int, int]] = []
        for interval_start, interval_end in interval_millis:
            if (
                not chains_milli
                or interval_start - chains_milli[-1][1] > 150
            ):
                chains_milli.append((interval_start, interval_end))
            else:
                chains_milli[-1] = (
                    chains_milli[-1][0],
                    interval_end,
                )
        indexed[coordinate] = _CoverageGroup(
            intervals=tuple(merged),
            intervals_milli=interval_millis,
            starts=tuple(interval[0] for interval in merged),
            ends=tuple(interval[1] for interval in merged),
            starts_milli=tuple(
                _millipoints(interval[0]) for interval in merged
            ),
            ends_milli=tuple(
                _millipoints(interval[1]) for interval in merged
            ),
            chains_milli=tuple(chains_milli),
            prefix_lengths=tuple(prefix),
            large_gap_prefix=tuple(large_gap_prefix),
        )
    return indexed


@dataclass(slots=True)
class _RuleEdgeIndex:
    page_index: int
    edges: tuple[_RuleEdge, ...]
    horizontal_by_y: Mapping[float, tuple[_RuleEdge, ...]]
    vertical_by_x: Mapping[float, tuple[_RuleEdge, ...]]
    line_horizontal_by_y: Mapping[float, tuple[_RuleEdge, ...]]
    line_vertical_by_x: Mapping[float, tuple[_RuleEdge, ...]]
    horizontal_coverage: Mapping[float, _CoverageGroup]
    vertical_coverage: Mapping[float, _CoverageGroup]
    line_horizontal_coverage: Mapping[float, _CoverageGroup]
    line_vertical_coverage: Mapping[float, _CoverageGroup]
    coverage_cache: dict[tuple[str, float, float, float], bool]
    nearby_cache: dict[
        tuple[str, float, float],
        tuple[_RuleEdge, ...],
    ]

    @classmethod
    def build(cls, page: FormSourcePage) -> "_RuleEdgeIndex":
        _charge_projection_comparisons(
            page.page_index,
            len(page.vectors),
        )
        edges = _build_rule_edges(page)
        budget = _PROJECTION_BUDGET.get()
        if budget is not None:
            budget.check_deadline()
        horizontal_groups = _snapped_edge_groups(
            tuple(edge for edge in edges if edge.orientation == "h"),
            page_index=page.page_index,
        )
        vertical_groups = _snapped_edge_groups(
            tuple(edge for edge in edges if edge.orientation == "v"),
            page_index=page.page_index,
        )
        snapped_edges = tuple(
            edge
            for groups in (horizontal_groups, vertical_groups)
            for group in groups.values()
            for edge in group
        )
        _charge_projection_comparisons(
            page.page_index,
            len(snapped_edges),
        )
        line_horizontal_groups = {
            coordinate: line_edges
            for coordinate, group in horizontal_groups.items()
            if (
                line_edges := tuple(
                    edge for edge in group if edge.source_kind == "line"
                )
            )
        }
        line_vertical_groups = {
            coordinate: line_edges
            for coordinate, group in vertical_groups.items()
            if (
                line_edges := tuple(
                    edge for edge in group if edge.source_kind == "line"
                )
            )
        }
        if budget is not None:
            budget.check_deadline()
        return cls(
            page_index=page.page_index,
            edges=snapped_edges,
            horizontal_by_y=horizontal_groups,
            vertical_by_x=vertical_groups,
            line_horizontal_by_y=line_horizontal_groups,
            line_vertical_by_x=line_vertical_groups,
            horizontal_coverage=_coverage_groups(
                horizontal_groups,
                page_index=page.page_index,
            ),
            vertical_coverage=_coverage_groups(
                vertical_groups,
                page_index=page.page_index,
            ),
            line_horizontal_coverage=_coverage_groups(
                line_horizontal_groups,
                page_index=page.page_index,
            ),
            line_vertical_coverage=_coverage_groups(
                line_vertical_groups,
                page_index=page.page_index,
            ),
            coverage_cache={},
            nearby_cache={},
        )

    def nearby(
        self,
        family: Literal[
            "horizontal",
            "vertical",
            "line_horizontal",
            "line_vertical",
        ],
        coordinate: float,
        *,
        tolerance: float = 0.15,
    ) -> tuple[_RuleEdge, ...]:
        key = (family, coordinate, tolerance)
        if key in self.nearby_cache:
            return self.nearby_cache[key]
        if family == "horizontal":
            groups = self.horizontal_by_y
        elif family == "vertical":
            groups = self.vertical_by_x
        elif family == "line_horizontal":
            groups = self.line_horizontal_by_y
        else:
            groups = self.line_vertical_by_x
        coordinates = tuple(groups)
        lower = bisect_left(
            coordinates,
            coordinate - tolerance - 0.0005,
        )
        upper = bisect_right(
            coordinates,
            coordinate + tolerance + 0.0005,
        )
        candidate_coordinates = tuple(
            value
            for value in coordinates[lower:upper]
            if _within_points(
                value,
                coordinate,
                tolerance=tolerance,
            )
        )
        result = tuple(
            edge
            for candidate_coordinate in candidate_coordinates
            for edge in groups[candidate_coordinate]
        )
        _charge_projection_comparisons(
            self.page_index,
            2 + (upper - lower) + len(result),
        )
        self.nearby_cache[key] = result
        return result

    def coverage(
        self,
        family: str,
        coordinate: float,
        start: float,
        end: float,
    ) -> bool:
        key = (family, coordinate, start, end)
        cached = self.coverage_cache.get(key)
        if cached is not None:
            return cached
        groups: Mapping[float, _CoverageGroup]
        if family == "horizontal":
            groups = self.horizontal_coverage
        elif family == "vertical":
            groups = self.vertical_coverage
        elif family == "line_horizontal":
            groups = self.line_horizontal_coverage
        elif family == "line_vertical":
            groups = self.line_vertical_coverage
        else:  # pragma: no cover - internal family is closed
            raise ValueError("unsupported rule-edge family")
        coverage = groups.get(coordinate)
        result = coverage.covers(start, end) if coverage is not None else False
        self.coverage_cache[key] = result
        return result


def _snapped_edge_groups(
    edges: Sequence[_RuleEdge],
    *,
    page_index: int,
) -> Mapping[float, tuple[_RuleEdge, ...]]:
    if not edges:
        return {}
    _charge_projection_comparisons(page_index, len(edges))
    ordered = sorted(
        edges,
        key=lambda edge: (
            edge.coordinate,
            edge.source_index,
            edge.source_kind,
            edge.start,
            edge.end,
        ),
    )
    groups: dict[float, list[_RuleEdge]] = {}
    anchor = ordered[0].coordinate
    anchor_milli = int(round(anchor * 1_000))
    budget = _PROJECTION_BUDGET.get()
    for index, edge in enumerate(ordered):
        coordinate_milli = int(round(edge.coordinate * 1_000))
        if coordinate_milli - anchor_milli > 150:
            anchor = edge.coordinate
            anchor_milli = coordinate_milli
        groups.setdefault(anchor, []).append(
            replace(edge, coordinate=anchor)
        )
        if budget is not None and index % 256 == 0:
            budget.check_deadline()
    snapped = {
        coordinate: tuple(
            sorted(
                group,
                key=lambda edge: (
                    edge.start,
                    edge.end,
                    edge.source_kind,
                    edge.source_index,
                ),
            )
        )
        for coordinate, group in groups.items()
    }
    if budget is not None:
        budget.check_deadline()
    return snapped


_RULE_EDGE_INDEXES: ContextVar[dict[int, _RuleEdgeIndex] | None] = ContextVar(
    "form_projection_rule_edge_indexes",
    default=None,
)
_CELL_SOURCE_OBJECT_CACHE: ContextVar[
    dict[
        tuple[int, tuple[float, float, float, float]],
        tuple[tuple[str, int, int | None], ...],
    ]
    | None
] = ContextVar("form_projection_cell_source_objects", default=None)


def _rule_edge_index(page: FormSourcePage) -> _RuleEdgeIndex:
    cache = _RULE_EDGE_INDEXES.get()
    page_key = id(page)
    if cache is not None and page_key in cache:
        return cache[page_key]
    index = _RuleEdgeIndex.build(page)
    if cache is not None:
        cache[page_key] = index
    return index


def _rule_edges(page: FormSourcePage) -> tuple[_RuleEdge, ...]:
    return _rule_edge_index(page).edges


def _edge_coverage(
    edges: Sequence[_RuleEdge],
    start: float,
    end: float,
    *,
    page_index: int | None = None,
) -> bool:
    start_milli = _millipoints(start)
    end_milli = _millipoints(end)
    cursor_milli = start_milli
    covered_milli = 0
    visited = 0
    for edge in edges:
        visited += 1
        if page_index is not None and visited % 256 == 0:
            _charge_projection_comparisons(page_index, 256)
        if edge.start > end:
            break
        if edge.end < start:
            continue
        left_milli = max(start_milli, _millipoints(edge.start))
        right_milli = min(end_milli, _millipoints(edge.end))
        if right_milli <= cursor_milli:
            continue
        left_milli = max(left_milli, cursor_milli)
        if max(0, left_milli - cursor_milli) > 150:
            if page_index is not None and visited % 256:
                _charge_projection_comparisons(
                    page_index,
                    visited % 256,
                )
            return False
        if right_milli > left_milli:
            covered_milli += right_milli - left_milli
            cursor_milli = right_milli
    if page_index is not None and visited % 256:
        _charge_projection_comparisons(page_index, visited % 256)
    return (
        max(0, end_milli - cursor_milli) <= 150
        and covered_milli * 100
        >= 95 * (end_milli - start_milli)
    )


def _minimal_ruled_cells(
    page: FormSourcePage,
) -> tuple[tuple[float, float, float, float], ...]:
    edge_index = _rule_edge_index(page)
    cells: list[tuple[float, float, float, float]] = []
    budget = _PROJECTION_BUDGET.get()
    comparisons = 0

    def account(count: int = 1) -> None:
        nonlocal comparisons
        comparisons += count
        if budget is not None:
            budget.account_comparisons(page.page_index, count)
        elif comparisons > MAX_COMPARISONS_PER_PAGE:
            raise ValueError("form projection comparison limit exceeded")

    account(
        len(edge_index.horizontal_by_y)
        + len(edge_index.vertical_by_x)
    )
    y_values = tuple(edge_index.horizontal_by_y)
    x_values = tuple(edge_index.vertical_by_x)
    account(len(x_values))
    vertical_coverages = tuple(
        edge_index.vertical_coverage[x] for x in x_values
    )
    y_millis = tuple(_millipoints(value) for value in y_values)
    account(len(vertical_coverages))
    chain_count = sum(
        len(coverage.chains_milli)
        for coverage in vertical_coverages
    )
    account(chain_count)
    vertical_chains = tuple(
        (x, coverage, chain_start, chain_end)
        for x, coverage in zip(
            x_values,
            vertical_coverages,
            strict=True,
        )
        for chain_start, chain_end in coverage.chains_milli
    )
    account(len(y_values) * chain_count)
    vertical_candidates_by_top = tuple(
        tuple(
            (x, coverage, chain_end)
            for x, coverage, chain_start, chain_end in vertical_chains
            if chain_start <= top_milli + 150
            and chain_end > top_milli
        )
        for top_milli in y_millis
    )

    for top_index, top in enumerate(y_values):
        top_milli = y_millis[top_index]
        account(2)
        bottom_start = bisect_left(
            y_values,
            top + 6,
            lo=top_index + 1,
        )
        bottom_end = bisect_right(
            y_values,
            top + 120,
            lo=bottom_start,
        )
        account(bottom_end - bottom_start)
        for bottom_index in range(bottom_start, bottom_end):
            bottom = y_values[bottom_index]
            bottom_milli = y_millis[bottom_index]
            height = bottom - top
            vertical_candidates = vertical_candidates_by_top[top_index]
            account(len(vertical_candidates))
            boundaries = [
                x
                for x, coverage, chain_end in vertical_candidates
                if chain_end >= bottom_milli - 150
                and coverage.covers_milli(top_milli, bottom_milli)
            ]
            account(max(0, len(boundaries) - 1))
            for left, right in zip(boundaries, boundaries[1:], strict=False):
                if right - left < 24:
                    continue
                account(2)
                if edge_index.coverage("horizontal", top, left, right) and (
                    edge_index.coverage("horizontal", bottom, left, right)
                ):
                    cells.append(_rounded_bbox((left, top, right - left, height)))
    unique_cells = set(cells)
    cell_millis = {
        cell: (
            _millipoints(cell[0]),
            _millipoints(cell[1]),
            _millipoints(cell[0] + cell[2]),
            _millipoints(cell[1] + cell[3]),
        )
        for cell in unique_cells
    }
    cell_bucket_size = 32.0
    cells_by_top_left: dict[
        tuple[int, int],
        list[
            tuple[
                tuple[float, float, float, float],
                tuple[int, int, int, int],
            ]
        ],
    ] = {}
    for candidate in unique_cells:
        bucket_key = (
            math.floor(candidate[0] / cell_bucket_size),
            math.floor(candidate[1] / cell_bucket_size),
        )
        cells_by_top_left.setdefault(bucket_key, []).append(
            (candidate, cell_millis[candidate])
        )
    for bucket_cells in cells_by_top_left.values():
        bucket_cells.sort(
            key=lambda value: (
                value[0][2] * value[0][3],
                value[0][3],
                value[0][2],
                value[0][1],
                value[0][0],
            )
        )
    minimal: list[tuple[float, float, float, float]] = []
    bucket_size_milli = int(cell_bucket_size * 1_000)
    for cell in unique_cells:
        contains_inner = False
        cell_left, cell_top, cell_right, cell_bottom = cell_millis[cell]
        left_bucket = (cell_left - 150) // bucket_size_milli
        right_bucket = (cell_right + 150) // bucket_size_milli
        top_bucket = (cell_top - 150) // bucket_size_milli
        bottom_bucket = (cell_bottom + 150) // bucket_size_milli
        for x_bucket in range(left_bucket, right_bucket + 1):
            for y_bucket in range(top_bucket, bottom_bucket + 1):
                account()
                for other, other_millis in cells_by_top_left.get(
                    (x_bucket, y_bucket),
                    (),
                ):
                    account()
                    (
                        other_left,
                        other_top,
                        other_right,
                        other_bottom,
                    ) = other_millis
                    if (
                        other != cell
                        and other_left >= cell_left - 150
                        and other_top >= cell_top - 150
                        and other_right <= cell_right + 150
                        and other_bottom <= cell_bottom + 150
                    ):
                        contains_inner = True
                        break
                if contains_inner:
                    break
            if contains_inner:
                break
        if not contains_inner:
            minimal.append(cell)
    if budget is not None:
        budget.check_deadline()
    return tuple(sorted(minimal, key=lambda value: (value[1], value[0])))


def _words_in_region(
    page: FormSourcePage,
    bbox: tuple[float, float, float, float],
    *,
    above: float = 0.0,
) -> tuple[SourceWord, ...]:
    return _projection_spatial_index(page).words_centered(
        bbox,
        above=above,
    )


def _spatial_text(
    words: Sequence[SourceWord],
) -> tuple[str, str, tuple[float, float, float, float], tuple[tuple[str, int, int | None], ...]] | None:
    if not words:
        return None
    ordered = sorted(words, key=lambda word: (word.top, word.x0, word.index))
    lines: list[list[SourceWord]] = []
    for word in ordered:
        if not lines or abs(word.top - lines[-1][0].top) > 1.25:
            lines.append([word])
        else:
            lines[-1].append(word)
    raw_text = " ".join(
        " ".join(word.text for word in sorted(line, key=lambda value: value.x0))
        for line in lines
    )
    raw_text = re.sub(r"\s+", " ", raw_text).strip()
    repairs = {
        "PRO- JECT": "PROJECT",
        "WC STATU- TORY LIMITS": "WC STATUTORY LIMITS",
        "OTH- ER": "OTHER",
    }
    text = repairs.get(raw_text, raw_text)
    left = min(word.x0 for word in words)
    top = min(word.top for word in words)
    right = max(word.x1 for word in words)
    bottom = max(word.bottom for word in words)
    refs = tuple(
        ("character_range", word.char_start, word.char_end)
        for word in sorted(words, key=lambda value: value.char_start)
    )
    return text, raw_text, (left, top, right - left, bottom - top), refs


def _spatial_chars(
    page: FormSourcePage,
    bbox: tuple[float, float, float, float],
    *,
    above: float = 0.0,
) -> tuple[str, str, tuple[float, float, float, float], tuple[tuple[str, int, int | None], ...]] | None:
    cache = _SPATIAL_CHAR_RESULTS.get()
    cache_key = (id(page), bbox, above)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    chars = list(
        _projection_spatial_index(page).chars_centered(
            bbox,
            above=above,
        )
    )
    if not chars:
        if cache is not None:
            cache[cache_key] = None
        return None
    ordered = sorted(chars, key=lambda char: (char.top, char.x0, char.index))
    lines: list[list[SourceChar]] = []
    for char in ordered:
        if not lines or abs(char.top - lines[-1][0].top) > 1.25:
            lines.append([char])
        else:
            lines[-1].append(char)
    line_texts = [
        "".join(char.text for char in sorted(line, key=lambda value: value.x0))
        for line in lines
    ]
    raw_text = re.sub(r"\s+", " ", " ".join(line_texts)).strip()
    repairs = {
        "PRO- JECT": "PROJECT",
        "WC STATU- TORY LIMITS": "WC STATUTORY LIMITS",
        "OTH- ER": "OTHER",
    }
    text = repairs.get(raw_text, raw_text)
    left = min(char.x0 for char in chars)
    top = min(char.top for char in chars)
    right = max(char.x1 for char in chars)
    bottom = max(char.bottom for char in chars)
    indexes = sorted(char.index for char in chars)
    refs: list[tuple[str, int, int | None]] = []
    start = prior = indexes[0]
    for index in indexes[1:]:
        if index == prior + 1:
            prior = index
            continue
        refs.append(("character_range", start, prior + 1))
        start = prior = index
    refs.append(("character_range", start, prior + 1))
    result = (
        text,
        raw_text,
        (left, top, right - left, bottom - top),
        tuple(refs),
    )
    if cache is not None:
        cache[cache_key] = result
    return result


@dataclass(frozen=True, slots=True)
class _ControlBox:
    bbox: tuple[float, float, float, float]
    source_objects: tuple[tuple[str, int, int | None], ...]


@dataclass(frozen=True, slots=True)
class _DetectedLabel:
    key: str
    role: Literal["field", "group", "control"]
    text: str
    raw_text: str
    bbox: tuple[float, float, float, float]
    source_objects: tuple[tuple[str, int, int | None], ...]
    target_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DetectedField:
    key: str
    group_key: str
    bbox: tuple[float, float, float, float]
    label_keys: tuple[str, ...]
    source_objects: tuple[tuple[str, int, int | None], ...]
    concern_codes: tuple[str, ...] = ()
    value: str | None = None
    value_state: Literal[
        "empty", "present", "ambiguous", "not_applicable"
    ] = "empty"


@dataclass(frozen=True, slots=True)
class _DetectedControl:
    key: str
    group_key: str
    bbox: tuple[float, float, float, float]
    label_key: str | None
    source_objects: tuple[tuple[str, int, int | None], ...]
    state: Literal["checked", "unchecked", "ambiguous"]
    concern_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _TextFragment:
    text: str
    bbox: tuple[float, float, float, float]


_TEXT_FRAGMENT_CACHE: ContextVar[
    dict[int, tuple[_TextFragment, ...]] | None
] = ContextVar("form_projection_text_fragments", default=None)
_STATIC_CONTROL_BOX_CACHE: ContextVar[
    dict[int, tuple[_ControlBox, ...]] | None
] = ContextVar("form_projection_static_control_boxes", default=None)
_PROJECTION_CANDIDATE_SHAPES: ContextVar[
    dict[int, set[tuple[float, float, float, float]]] | None
] = ContextVar("form_projection_candidate_shapes", default=None)


def _static_control_boxes(page: FormSourcePage) -> tuple[_ControlBox, ...]:
    cache = _STATIC_CONTROL_BOX_CACHE.get()
    cache_key = id(page)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    by_bbox: dict[
        tuple[float, float, float, float],
        set[tuple[str, int, int | None]],
    ] = {}
    budget = _PROJECTION_BUDGET.get()
    comparisons = 0

    def account(count: int = 1) -> None:
        nonlocal comparisons
        comparisons += count
        if budget is not None:
            budget.account_comparisons(page.page_index, count)
        elif comparisons > MAX_COMPARISONS_PER_PAGE:
            raise ValueError("form projection comparison limit exceeded")

    for vector in page.vectors:
        account()
        width = vector.x1 - vector.x0
        height = vector.bottom - vector.top
        if (
            vector.kind == "rect"
            and 6 <= width <= 24
            and 6 <= height <= 24
            and 0.65 <= width / height <= 1.55
        ):
            bbox = _rounded_bbox((vector.x0, vector.top, width, height))
            by_bbox.setdefault(bbox, set()).add(("rect", vector.index, None))
    edge_index = _rule_edge_index(page)
    horizontal_by_y = edge_index.line_horizontal_by_y
    vertical_by_x = edge_index.line_vertical_by_x
    x_values = tuple(vertical_by_x)
    y_values = tuple(horizontal_by_y)
    for left_index, left in enumerate(x_values):
        account(2)
        right_start = bisect_left(
            x_values,
            left + 6,
            lo=left_index + 1,
        )
        right_end = bisect_right(
            x_values,
            left + 24,
            lo=right_start,
        )
        for right_index in range(right_start, right_end):
            account()
            right = x_values[right_index]
            width = right - left
            for top_index, top in enumerate(y_values):
                account(2)
                bottom_start = bisect_left(
                    y_values,
                    top + 6,
                    lo=top_index + 1,
                )
                bottom_end = bisect_right(
                    y_values,
                    top + 24,
                    lo=bottom_start,
                )
                for bottom_index in range(bottom_start, bottom_end):
                    account()
                    bottom = y_values[bottom_index]
                    height = bottom - top
                    account()
                    if not 0.65 <= width / height <= 1.55:
                        continue
                    # Charge each of the four coverage predicates before
                    # evaluating them.  Boundary-bucket probes are deferred
                    # until the candidate has actually qualified.
                    account(4)
                    if not (
                        edge_index.coverage(
                            "line_vertical", left, top, bottom
                        )
                        and edge_index.coverage(
                            "line_vertical", right, top, bottom
                        )
                        and edge_index.coverage(
                            "line_horizontal", top, left, right
                        )
                        and edge_index.coverage(
                            "line_horizontal", bottom, left, right
                        )
                    ):
                        continue
                    account(4)
                    left_edges = vertical_by_x[left]
                    right_edges = vertical_by_x[right]
                    top_edges = horizontal_by_y[top]
                    bottom_edges = horizontal_by_y[bottom]
                    bbox = _rounded_bbox((left, top, width, height))
                    boundary_edges = (
                        *left_edges,
                        *right_edges,
                        *top_edges,
                        *bottom_edges,
                    )
                    account(len(boundary_edges))
                    sources = {
                        (edge.source_kind, edge.source_index, None)
                        for edge in boundary_edges
                        if min(
                            edge.end,
                            bottom if edge.orientation == "v" else right,
                        )
                        - max(
                            edge.start,
                            top if edge.orientation == "v" else left,
                        )
                        > 0.01
                    }
                    by_bbox.setdefault(bbox, set()).update(sources)
    exact_native_rects: dict[
        tuple[float, float, float, float],
        tuple[str, int, None],
    ] = {}
    for vector in page.vectors:
        account()
        if (
            vector.kind == "rect"
            and 6 <= vector.x1 - vector.x0 <= 24
            and 6 <= vector.bottom - vector.top <= 24
        ):
            exact_native_rects[
                _rounded_bbox(
                    (
                        vector.x0,
                        vector.top,
                        vector.x1 - vector.x0,
                        vector.bottom - vector.top,
                    )
                )
            ] = ("rect", vector.index, None)
    for bbox, source in exact_native_rects.items():
        if bbox in by_bbox:
            by_bbox[bbox] = {source}
    if budget is not None:
        budget.check_deadline()
    result = tuple(
        _ControlBox(bbox=bbox, source_objects=tuple(sorted(sources)))
        for bbox, sources in sorted(
            by_bbox.items(), key=lambda value: (value[0][1], value[0][0])
        )
    )
    shape_counts = _PROJECTION_CANDIDATE_SHAPES.get()
    if shape_counts is not None:
        page_shapes = shape_counts.setdefault(page.page_index, set())
        page_shapes.update(box.bbox for box in result)
        if len(page_shapes) > MAX_CANDIDATE_SHAPES_PER_PAGE:
            raise _ProjectionPageLimitError(page.page_index)
    elif len(result) > MAX_CANDIDATE_SHAPES_PER_PAGE:
        raise _ProjectionPageLimitError(page.page_index)
    if cache is not None:
        cache[cache_key] = result
    return result


def _text_fragments(page: FormSourcePage) -> tuple[_TextFragment, ...]:
    cache = _TEXT_FRAGMENT_CACHE.get()
    cache_key = id(page)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    if page.words:
        _charge_projection_comparisons(page.page_index, len(page.words))
        ordered_words = sorted(
            page.words,
            key=lambda word: (word.top, word.x0, word.index),
        )
        budget = _PROJECTION_BUDGET.get()
        _charge_projection_comparisons(page.page_index, len(page.chars))
        whitespace_chars: list[SourceChar] = []
        for char_index, char in enumerate(page.chars):
            if char.text.isspace():
                whitespace_chars.append(char)
            if budget is not None and char_index % 256 == 0:
                budget.check_deadline()
        _charge_projection_comparisons(
            page.page_index,
            len(whitespace_chars),
        )
        whitespace_chars.sort(
            key=lambda char: (char.top, char.x0, char.index)
        )
        whitespace_tops = tuple(char.top for char in whitespace_chars)

        def words_share_fragment(
            previous: SourceWord,
            current: SourceWord,
        ) -> bool:
            if current.x0 - previous.x1 <= 5:
                return True
            _charge_projection_comparisons(page.page_index, 2)
            lower = bisect_left(
                whitespace_tops,
                current.top - 1.25,
            )
            upper = bisect_right(
                whitespace_tops,
                current.top + 1.25,
            )
            _charge_projection_comparisons(
                page.page_index,
                upper - lower,
            )
            candidates = sorted(
                whitespace_chars[lower:upper],
                key=lambda char: (char.x0, char.index),
            )
            cursor = previous.x1
            for candidate_index, char in enumerate(candidates):
                if char.x1 < cursor:
                    continue
                if char.x0 - cursor > 5:
                    break
                cursor = max(cursor, char.x1)
                if cursor >= current.x0 - 5:
                    return True
                if budget is not None and candidate_index % 256 == 0:
                    budget.check_deadline()
            return current.x0 - cursor <= 5

        word_lines: list[list[SourceWord]] = []
        for index, word in enumerate(ordered_words):
            if (
                not word_lines
                or abs(word.top - word_lines[-1][0].top) > 1.25
            ):
                word_lines.append([word])
            else:
                word_lines[-1].append(word)
            if budget is not None and index % 256 == 0:
                budget.check_deadline()
        fragments: list[_TextFragment] = []
        _charge_projection_comparisons(
            page.page_index,
            len(page.words),
        )
        for line_index, line in enumerate(word_lines):
            parts: list[list[SourceWord]] = []
            for word_index, word in enumerate(
                sorted(line, key=lambda value: value.x0)
            ):
                if not parts or not words_share_fragment(
                    parts[-1][-1],
                    word,
                ):
                    parts.append([word])
                else:
                    parts[-1].append(word)
                if budget is not None and word_index % 256 == 0:
                    budget.check_deadline()
            for part in parts:
                text = " ".join(word.text for word in part).strip()
                if not text:
                    continue
                adjusted_right: float | None = None
                if text.endswith("$") and len(text) > 1:
                    text = text[:-1].rstrip()
                    if part[-1].text.strip() == "$":
                        # ``text`` drops exactly one terminal marker, so the
                        # geometry path must drop exactly one matching word.
                        # Popping every trailing ``$`` word makes a valid
                        # ``$ $`` fragment empty before its bbox is measured.
                        part.pop()
                    if part and part[-1].text.endswith("$"):
                        trailing_word = part[-1]
                        char_start = max(
                            0,
                            min(
                                len(page.chars),
                                trailing_word.char_start,
                            ),
                        )
                        char_end = max(
                            char_start,
                            min(
                                len(page.chars),
                                trailing_word.char_end,
                            ),
                        )
                        _charge_projection_comparisons(
                            page.page_index,
                            char_end - char_start,
                        )
                        retained_chars: list[SourceChar] = []
                        for char_offset, char_index in enumerate(
                            range(char_start, char_end)
                        ):
                            char = page.chars[char_index]
                            if char.text.strip() != "$":
                                retained_chars.append(char)
                            if (
                                budget is not None
                                and char_offset % 256 == 0
                            ):
                                budget.check_deadline()
                        if retained_chars:
                            adjusted_right = max(
                                char.x1 for char in retained_chars
                            )
                right_edges = [word.x1 for word in part]
                if adjusted_right is not None:
                    right_edges[-1] = adjusted_right
                fragments.append(
                    _TextFragment(
                        text=text,
                        bbox=_rounded_bbox(
                            (
                                min(word.x0 for word in part),
                                min(word.top for word in part),
                                max(right_edges)
                                - min(word.x0 for word in part),
                                max(word.bottom for word in part)
                                - min(word.top for word in part),
                            )
                        ),
                    )
                )
            if budget is not None and line_index % 128 == 0:
                budget.check_deadline()
        result = tuple(fragments)
        if cache is not None:
            cache[cache_key] = result
        if budget is not None:
            budget.check_deadline()
        return result

    _charge_projection_comparisons(page.page_index, len(page.chars))
    ordered = sorted(
        page.chars,
        key=lambda char: (char.top, char.x0, char.index),
    )
    budget = _PROJECTION_BUDGET.get()
    if budget is not None:
        budget.check_deadline()
    lines: list[list[SourceChar]] = []
    for index, char in enumerate(ordered):
        if not lines or abs(char.top - lines[-1][0].top) > 1.25:
            lines.append([char])
        else:
            lines[-1].append(char)
        if budget is not None and index % 256 == 0:
            budget.check_deadline()
    fragments: list[_TextFragment] = []
    _charge_projection_comparisons(page.page_index, len(page.chars))
    for line_index, line in enumerate(lines):
        parts: list[list[SourceChar]] = []
        for char_index, char in enumerate(
            sorted(line, key=lambda value: value.x0)
        ):
            if not parts or char.x0 - parts[-1][-1].x1 > 5:
                parts.append([char])
            else:
                parts[-1].append(char)
            if budget is not None and char_index % 256 == 0:
                budget.check_deadline()
        for part in parts:
            text = "".join(char.text for char in part).strip()
            if not text:
                continue
            if text.endswith("$") and len(text) > 1:
                text = text[:-1].rstrip()
                while part and part[-1].text.strip() == "$":
                    part.pop()
            fragments.append(
                _TextFragment(
                    text=text,
                    bbox=_rounded_bbox(
                        (
                            min(char.x0 for char in part),
                            min(char.top for char in part),
                            max(char.x1 for char in part)
                            - min(char.x0 for char in part),
                            max(char.bottom for char in part)
                            - min(char.top for char in part),
                        )
                    ),
                )
            )
        if budget is not None and line_index % 128 == 0:
            budget.check_deadline()
    result = tuple(fragments)
    if cache is not None:
        cache[cache_key] = result
    if budget is not None:
        budget.check_deadline()
    return result


def _control_label_for_box(
    page: FormSourcePage,
    box: _ControlBox,
    fragments: Sequence[_TextFragment],
) -> tuple[str, str, tuple[float, float, float, float], tuple[tuple[str, int, int | None], ...], bool] | None:
    x, y, width, height = box.bbox
    right = x + width
    bottom = y + height
    budget = _PROJECTION_BUDGET.get()
    comparisons = 0

    def account() -> None:
        nonlocal comparisons
        comparisons += 1
        if budget is not None:
            budget.account_comparisons(page.page_index, 1)
        elif comparisons > MAX_COMPARISONS_PER_PAGE:
            raise _ProjectionPageLimitError(page.page_index)

    def commit() -> None:
        if budget is not None:
            budget.check_deadline()

    # A visible response label immediately above/overlapping the outline is
    # retained as unresolved choice meaning, never as a selected state.
    overlapping: list[_TextFragment] = []
    for fragment in fragments:
        account()
        if (
            fragment.bbox[0] < right
            and fragment.bbox[0] + fragment.bbox[2] > x
            and 0 <= y - (fragment.bbox[1] + fragment.bbox[3]) <= 4
            and "/" in fragment.text
        ):
            overlapping.append(fragment)
    if overlapping:
        chosen = min(
            overlapping,
            key=lambda fragment: (
                y - (fragment.bbox[1] + fragment.bbox[3]),
                fragment.bbox[0],
            ),
        )
        spatial = _spatial_chars(page, chosen.bbox)
        if spatial is not None:
            commit()
            return (*spatial, True)

    eligible: list[_TextFragment] = []
    for fragment in fragments:
        account()
        if (
            0.5 <= fragment.bbox[0] - right <= 96
            and fragment.bbox[1] >= y - 1.5
            and fragment.bbox[1] + fragment.bbox[3] <= bottom + 1.5
        ):
            eligible.append(fragment)
    if not eligible:
        commit()
        return None
    x_starts = sorted({fragment.bbox[0] for fragment in eligible})
    nearest_x = min(x_starts, key=lambda value: (value - right, value))
    nearby_count = 0
    for value in x_starts:
        account()
        if abs(value - nearest_x) <= 0.5:
            nearby_count += 1
    if nearby_count > 1:
        commit()
        return None
    selected: list[_TextFragment] = []
    for fragment in eligible:
        account()
        if abs(fragment.bbox[0] - nearest_x) <= 3.5:
            selected.append(fragment)
    left = min(fragment.bbox[0] for fragment in selected)
    top = min(fragment.bbox[1] for fragment in selected)
    selected_right = max(
        fragment.bbox[0] + fragment.bbox[2] for fragment in selected
    )
    selected_bottom = max(
        fragment.bbox[1] + fragment.bbox[3] for fragment in selected
    )
    spatial = _spatial_chars(
        page,
        (left, top, selected_right - left, selected_bottom - top),
    )
    if spatial is None:
        commit()
        return None
    commit()
    return (*spatial, False)


def _control_key(text: str, section_suffix: str | None) -> str:
    normalized = text.upper()
    base = _slug(re.sub(r"\bLIAB\b", "LIABILITY", text))
    if normalized == "Y / N":
        return "yn-response"
    if normalized in {"CLAIMS-MADE", "OCCUR"} and section_suffix:
        return f"{base}-{section_suffix}"
    return base


def _control_section_suffix(
    box: _ControlBox,
    text: str,
    *,
    page_index: int,
    label_candidates: Mapping[
        tuple[float, float, float, float],
        tuple[
            str,
            str,
            tuple[float, float, float, float],
            tuple[tuple[str, int, int | None], ...],
            bool,
        ],
    ],
) -> str | None:
    if text.upper() not in {"CLAIMS-MADE", "OCCUR"}:
        return None
    contextual: list[tuple[float, float, str]] = []
    _charge_projection_comparisons(
        page_index,
        len(label_candidates),
    )
    for other_bbox, label in label_candidates.items():
        other_text = label[0]
        if other_text.upper() in {"CLAIMS-MADE", "OCCUR"}:
            continue
        tokens = re.findall(r"[A-Za-z]+", other_text)
        if len(tokens) < 2 or not _at_most_with_tolerance(
            other_bbox[0],
            box.bbox[0],
        ):
            continue
        vertical = abs(other_bbox[1] - box.bbox[1])
        if vertical > 18:
            continue
        contextual.append(
            (
                vertical,
                box.bbox[0] - other_bbox[0],
                other_text,
            )
        )
    if not contextual:
        return None
    owner_text = min(contextual)[2]
    owner_tokens = [_slug(token) for token in re.findall(r"[A-Za-z]+", owner_text)]
    if len(owner_tokens) >= 3:
        return owner_tokens[-2]
    return owner_tokens[0]


def _static_control_state(
    page: FormSourcePage,
    box: _ControlBox,
) -> tuple[
    Literal["checked", "unchecked", "ambiguous"],
    tuple[_SourceIdentity, ...],
]:
    x, y, width, height = box.bbox
    inset = (x + 1, y + 1, width - 2, height - 2)
    _ix, _iy, iw, ih = inset
    boundary_sources = {
        (kind, index)
        for kind, index, _unused in box.source_objects
        if kind in {"line", "rect"}
    }
    vector_index = _projection_vector_index(page)
    boundary_vectors = tuple(
        vector_index.vectors_by_identity[source]
        for source in boundary_sources
        if source in vector_index.vectors_by_identity
    )
    _charge_projection_comparisons(
        page.page_index,
        len(boundary_sources) + len(boundary_vectors),
    )
    if any(vector.fill for vector in boundary_vectors):
        return "ambiguous", ()
    interior_vectors = tuple(
        vector
        for vector in vector_index.inside(inset)
        if (vector.kind, vector.index) not in boundary_sources
    )
    _charge_projection_comparisons(
        page.page_index,
        len(interior_vectors),
    )
    if any(
        vector.fill
        and (vector.x1 - vector.x0) * (vector.bottom - vector.top)
        > 0.5 * iw * ih
        for vector in interior_vectors
    ):
        return "ambiguous", ()
    if any(
        vector.fill or vector.kind not in {"line", "curve"}
        for vector in interior_vectors
    ):
        return "ambiguous", ()
    _charge_projection_comparisons(
        page.page_index,
        len(interior_vectors),
    )
    segments = tuple(
        vector
        for vector in interior_vectors
        if vector.kind in {"line", "curve"} and not vector.fill
    )
    if not segments:
        return "unchecked", ()
    _charge_projection_comparisons(page.page_index, len(segments))
    combined_length = 0.0
    minimum_x = math.inf
    maximum_x = -math.inf
    minimum_y = math.inf
    maximum_y = -math.inf
    for vector in segments:
        combined_length += math.hypot(
            vector.x1 - vector.x0,
            vector.bottom - vector.top,
        )
        minimum_x = min(minimum_x, vector.x0)
        maximum_x = max(maximum_x, vector.x1)
        minimum_y = min(minimum_y, vector.top)
        maximum_y = max(maximum_y, vector.bottom)
    horizontal_span = maximum_x - minimum_x
    vertical_span = maximum_y - minimum_y
    if (
        2 <= len(segments) <= 4
        and combined_length >= 0.35 * math.hypot(iw, ih)
        and horizontal_span >= 0.35 * iw
        and vertical_span >= 0.35 * ih
    ):
        return (
            "checked",
            tuple((vector.kind, vector.index, None) for vector in segments),
        )
    return "ambiguous", ()


def _detect_static_controls(
    page: FormSourcePage,
    *,
    group_bbox: tuple[float, float, float, float],
    group_key: str,
) -> tuple[tuple[_DetectedControl, ...], tuple[_DetectedLabel, ...]]:
    fragments = _text_fragments(page)
    all_boxes = _static_control_boxes(page)
    _charge_projection_comparisons(page.page_index, len(all_boxes))
    boxes = [
        box
        for box in all_boxes
        if _intersects(box.bbox, group_bbox)
        and not _chars_intersecting_bbox(
            page,
            (
                box.bbox[0] + 1,
                box.bbox[1] + 1,
                max(0.1, box.bbox[2] - 2),
                max(0.1, box.bbox[3] - 2),
            ),
        )
    ]
    geometry_counts: dict[tuple[float, float], int] = {}
    _charge_projection_comparisons(page.page_index, len(boxes))
    for box in boxes:
        geometry = (round(box.bbox[2], 2), round(box.bbox[3], 2))
        geometry_counts[geometry] = geometry_counts.get(geometry, 0) + 1
    if geometry_counts:
        modal_geometry = max(
            geometry_counts,
            key=lambda value: (geometry_counts[value], -value[0], -value[1]),
        )
        _charge_projection_comparisons(page.page_index, len(boxes))
        boxes = [
            box
            for box in boxes
            if _within_points(box.bbox[2], modal_geometry[0])
            and _within_points(box.bbox[3], modal_geometry[1])
        ]
    label_candidates: dict[
        tuple[float, float, float, float],
        tuple[str, str, tuple[float, float, float, float], tuple[tuple[str, int, int | None], ...], bool],
    ] = {}
    for box in boxes:
        label = _control_label_for_box(page, box, fragments)
        if label is not None:
            label_candidates[box.bbox] = label

    # A label belongs to its closest compatible outline. This drops the
    # shared-edge phantom beside the reviewed claims-made control.
    label_owner: dict[
        tuple[str, tuple[float, float, float, float]],
        tuple[float, float, float, float],
    ] = {}
    _charge_projection_comparisons(
        page.page_index,
        len(label_candidates),
    )
    for bbox, label in label_candidates.items():
        identity = (label[1], label[2])
        prior = label_owner.get(identity)
        if prior is None:
            label_owner[identity] = bbox
            continue
        gap = label[2][0] - (bbox[0] + bbox[2])
        prior_gap = label[2][0] - (prior[0] + prior[2])
        if abs(gap) < abs(prior_gap):
            label_owner[identity] = bbox

    detected: list[_DetectedControl] = []
    labels: list[_DetectedLabel] = []
    labeled_sizes: list[tuple[float, float]] = []
    labeled_boxes: list[tuple[float, float, float, float]] = []
    _charge_projection_comparisons(page.page_index, len(boxes))
    for box in boxes:
        label = label_candidates.get(box.bbox)
        if label is None or label_owner.get((label[1], label[2])) != box.bbox:
            continue
        text, raw_text, label_bbox, refs, overlapping = label
        if not _bounded_text_value(text):
            continue
        key = _control_key(
            text,
            _control_section_suffix(
                box,
                text,
                page_index=page.page_index,
                label_candidates=label_candidates,
            ),
        )
        state, mark_sources = _static_control_state(page, box)
        if overlapping:
            state = "ambiguous"
        concerns = (
            ("form_control_state_ambiguous",) if state == "ambiguous" else ()
        )
        detected.append(
            _DetectedControl(
                key=key,
                group_key=group_key,
                bbox=box.bbox,
                label_key=key,
                source_objects=_bounded_source_identities(
                    (*box.source_objects, *mark_sources),
                    page_index=page.page_index,
                ),
                state=state,
                concern_codes=concerns,
            )
        )
        labels.append(
            _DetectedLabel(
                key=key,
                role="control",
                text=text,
                raw_text=raw_text,
                bbox=_rounded_bbox(label_bbox),
                source_objects=refs,
                target_keys=(key,),
            )
        )
        labeled_sizes.append((box.bbox[2], box.bbox[3]))
        labeled_boxes.append(box.bbox)

    section_indexes: dict[str, int] = {}
    labeled_box_set = set(labeled_boxes)
    for box in boxes:
        if box.bbox in labeled_box_set or box.bbox in label_candidates:
            continue
        width, height = box.bbox[2], box.bbox[3]
        _charge_projection_comparisons(
            page.page_index,
            len(labeled_sizes),
        )
        if sum(
            _within_points(other_width, width)
            and _within_points(other_height, height)
            for other_width, other_height in labeled_sizes
        ) < 3:
            continue
        _charge_projection_comparisons(
            page.page_index,
            len(labeled_boxes),
        )
        nearest_pitch = min(
            (
                min(abs(box.bbox[0] - other[0]), abs(box.bbox[1] - other[1]))
                for other in labeled_boxes
                if other != box.bbox
                and (
                    _within_points(box.bbox[0], other[0])
                    or _within_points(box.bbox[1], other[1])
                )
            ),
            default=math.inf,
        )
        if nearest_pitch > 24:
            continue
        # Name an unlabeled member from the vocabulary repeated by the nearby
        # labeled owner cluster.  This keeps the identity stable under page
        # translation and avoids treating a benchmark coordinate as policy.
        nearby_tokens: dict[str, int] = {}
        _charge_projection_comparisons(
            page.page_index,
            len(detected),
        )
        for labeled in detected:
            if labeled.label_key is None:
                continue
            if abs(labeled.bbox[1] - box.bbox[1]) > 2 * 24:
                continue
            for token in labeled.key.split("-"):
                normalized = token.removesuffix("s") if len(token) > 4 else token
                if len(normalized) < 3:
                    continue
                nearby_tokens[normalized] = nearby_tokens.get(normalized, 0) + 1
        repeated = [
            (count, token)
            for token, count in nearby_tokens.items()
            if count >= 2
        ]
        if not repeated:
            continue
        section = max(repeated, key=lambda value: (value[0], value[1]))[1]
        section_indexes[section] = section_indexes.get(section, 0) + 1
        detected.append(
            _DetectedControl(
                key=f"unlabeled-{section}-{section_indexes[section]}",
                group_key=group_key,
                bbox=box.bbox,
                label_key=None,
                source_objects=box.source_objects,
                state="ambiguous",
                concern_codes=("form_control_state_ambiguous",),
            )
        )
    detected.sort(key=lambda value: (value.bbox[1], value.bbox[0], value.key))
    labels.sort(key=lambda value: (value.bbox[1], value.bbox[0], value.key))
    return tuple(detected), tuple(labels)


def _cell_source_objects(
    page: FormSourcePage,
    bbox: tuple[float, float, float, float],
) -> tuple[tuple[str, int, int | None], ...]:
    cache = _CELL_SOURCE_OBJECT_CACHE.get()
    cache_key = (id(page), bbox)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    x, y, width, height = bbox
    right = x + width
    bottom = y + height
    vector_index = _projection_vector_index(page)
    native = vector_index.matching_bbox(bbox)
    if native:
        result = _bounded_source_identities(
            (
                ("rect", vector.index, None)
                for vector in native
            ),
            page_index=page.page_index,
        )
        if cache is not None:
            cache[cache_key] = result
        return result

    edge_index = _rule_edge_index(page)
    side_specs = (
        ("top", "h", y, x, right),
        ("bottom", "h", bottom, x, right),
        ("left", "v", x, y, bottom),
        ("right", "v", right, y, bottom),
    )
    selected_by_side: dict[str, tuple[_RuleEdge, ...]] = {}
    exact_span_sides = 0
    for name, orientation, coordinate, start, end in side_specs:
        nearby = edge_index.nearby(
            (
                "line_horizontal"
                if orientation == "h"
                else "line_vertical"
            ),
            coordinate,
        )
        _charge_projection_comparisons(
            page.page_index,
            len(nearby),
        )
        candidates = [
            edge
            for edge in nearby
            if min(edge.end, end) - max(edge.start, start) > 0.01
        ]
        if not candidates:
            selected_by_side[name] = ()
            continue
        side_length = end - start
        _charge_projection_comparisons(
            page.page_index,
            len(candidates),
        )
        covering = [
            edge
            for edge in candidates
            if _at_least_ninety_five_percent(
                min(edge.end, end) - max(edge.start, start),
                side_length,
            )
        ]
        pool = covering or candidates
        _charge_projection_comparisons(
            page.page_index,
            3 * len(pool),
        )
        best_overlap = max(
            min(edge.end, end) - max(edge.start, start) for edge in pool
        )
        best_span = min(
            edge.end - edge.start
            for edge in pool
            if _within_points(
                min(edge.end, end)
                - max(edge.start, start)
                - best_overlap,
                0.0,
            )
        )
        selected = tuple(
            edge
            for edge in pool
            if _within_points(
                min(edge.end, end)
                - max(edge.start, start)
                - best_overlap,
                0.0,
            )
            and _within_points(edge.end - edge.start, best_span)
        )
        selected_by_side[name] = selected
        if selected and _within_points(best_span, side_length):
            exact_span_sides += 1

    proposed = vector_index.smallest_container(bbox)
    container: SourceVector | None = None
    container_shared_sides = 0
    if proposed is not None:
        container_shared_sides = sum(
            (
                _within_points(proposed.top, y),
                _within_points(proposed.bottom, bottom),
                _within_points(proposed.x0, x),
                _within_points(proposed.x1, right),
            )
        )
        if container_shared_sides >= 2 and exact_span_sides < 2:
            container = proposed

    selected_lines: list[_RuleEdge] = []
    for name, _orientation, coordinate, _start, _end in side_specs:
        side_is_container_boundary = container is not None and (
            (name == "top" and _within_points(container.top, coordinate))
            or (
                name == "bottom"
                and _within_points(container.bottom, coordinate)
            )
            or (name == "left" and _within_points(container.x0, coordinate))
            or (name == "right" and _within_points(container.x1, coordinate))
        )
        _charge_projection_comparisons(
            page.page_index,
            len(selected_by_side[name]),
        )
        for edge in selected_by_side[name]:
            side_length = width if edge.orientation == "h" else height
            overlap = min(
                edge.end,
                right if edge.orientation == "h" else bottom,
            ) - max(edge.start, x if edge.orientation == "h" else y)
            if side_is_container_boundary and not (
                _at_least_ninety_five_percent(overlap, side_length)
            ):
                continue
            selected_lines.append(edge)

    # Repeated ruled rows retain boundary meaning in geometric side order.
    # Other source cells retain line-object order, matching the source draw
    # order while still discarding unrelated coincident container strokes.
    horizontal_coordinates = sorted(
        {
            edge.coordinate
            for edges in edge_index.line_horizontal_by_y.values()
            for edge in edges
            if _at_least_ninety_five_percent(
                min(edge.end, right) - max(edge.start, x),
                width,
            )
        }
    )
    _charge_projection_comparisons(
        page.page_index,
        sum(
            len(edges)
            for edges in edge_index.line_horizontal_by_y.values()
        ),
    )
    repeated_boundaries = 1
    for direction in (-1, 1):
        coordinate = y if direction < 0 else bottom
        while horizontal_coordinates:
            target = coordinate + direction * height
            lower = bisect_left(
                horizontal_coordinates,
                target - 0.1505,
            )
            _charge_projection_comparisons(page.page_index, 2)
            if (
                lower >= len(horizontal_coordinates)
                or not _within_points(
                    horizontal_coordinates[lower],
                    target,
                )
            ):
                break
            repeated_boundaries += 1
            coordinate += direction * height
    is_repeated_grid_row = height <= 24 and repeated_boundaries >= 3
    if is_repeated_grid_row:
        side_rank = {"top": 0, "bottom": 1, "left": 2, "right": 2}
        edge_side = {
            id(edge): name
            for name, edges in selected_by_side.items()
            for edge in edges
        }
        selected_lines.sort(
            key=lambda edge: (
                side_rank[edge_side[id(edge)]],
                -(edge.end - edge.start)
                if edge.orientation == "v"
                else 0.0,
                edge.source_index,
            )
        )
    else:
        selected_lines.sort(key=lambda edge: edge.source_index)

    sources: list[tuple[str, int, int | None]] = []
    if is_repeated_grid_row:
        container = None
    if container is not None and container_shared_sides < 3:
        sources.append(("rect", container.index, None))
    sources.extend(("line", edge.source_index, None) for edge in selected_lines)
    if container is not None and container_shared_sides >= 3:
        sources.append(("rect", container.index, None))
    result = _bounded_source_identities(
        sources,
        page_index=page.page_index,
    )
    if cache is not None:
        cache[cache_key] = result
    return result


def _form_key(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().rstrip(":")
    upper = normalized.upper()
    if upper.startswith("DATE ") or upper == "DATE":
        return "date"
    if upper.startswith("DESCRIPTION OF OPERATIONS"):
        return "description-of-operations"
    if upper.startswith("PHONE"):
        return "phone"
    if upper.startswith("FAX"):
        return "fax"
    if upper.startswith("E-MAIL ADDRESS"):
        return "email-address"
    match = re.fullmatch(r"INSURER\s+([A-Z])\s*", upper)
    if match:
        return f"insurer-{match.group(1).casefold()}-name"
    return _slug(re.sub(r"\([^)]*\)", "", normalized))


def _group_key_for_field(
    field_key: str,
    bbox: tuple[float, float, float, float],
    page: FormSourcePage,
) -> str:
    del bbox, page
    return field_key


def _dense_preserved_table_bbox(
    ir: DocumentIR,
    page_index: int,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    return _projection_presentation_index(
        ir,
        page_index,
    ).dense_table_bbox(page_width, page_height)


def _intersects(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    overlap_width = max(
        0.0,
        min(first[0] + first[2], second[0] + second[2])
        - max(first[0], second[0]),
    )
    overlap_height = max(
        0.0,
        min(first[1] + first[3], second[1] + second[3])
        - max(first[1], second[1]),
    )
    return overlap_width * overlap_height > 0.1 * first[2] * first[3]


def _detect_ruled_fields(
    ir: DocumentIR,
    page: FormSourcePage,
    cells: Sequence[tuple[float, float, float, float]],
) -> tuple[tuple[_DetectedField, ...], tuple[_DetectedLabel, ...]]:
    dense_table = _dense_preserved_table_bbox(
        ir, page.page_index, page.width, page.height
    )
    cell_set = set(cells)
    header_buckets: dict[
        tuple[int, int],
        list[tuple[float, float, float, float]],
    ] = {}
    header_bucket_size_milli = 150
    _charge_projection_comparisons(page.page_index, len(cells))
    for candidate in cells:
        header_buckets.setdefault(
            (
                _millipoints(candidate[0]) // header_bucket_size_milli,
                _millipoints(candidate[2]) // header_bucket_size_milli,
            ),
            [],
        ).append(candidate)
    header_cells: set[tuple[float, float, float, float]] = set()
    for cell in cells:
        x, y, width, height = cell
        x_buckets = range(
            (_millipoints(x) - 150) // header_bucket_size_milli,
            (_millipoints(x) + 150) // header_bucket_size_milli + 1,
        )
        width_buckets = range(
            (_millipoints(width) - 150) // header_bucket_size_milli,
            (_millipoints(width) + 150)
            // header_bucket_size_milli
            + 1,
        )
        nearby = tuple(
            other
            for x_bucket in x_buckets
            for width_bucket in width_buckets
            for other in header_buckets.get(
                (x_bucket, width_bucket),
                (),
            )
        )
        _charge_projection_comparisons(
            page.page_index,
            len(x_buckets) * len(width_buckets) + len(nearby),
        )
        repeated_below = sum(
            _within_points(other[0], x)
            and _within_points(other[2], width)
            and _at_least_with_tolerance(other[1], y + height)
            and _at_most_with_tolerance(other[1], y + height * 7)
            and _within_points(other[3], height)
            for other in nearby
        )
        if repeated_below >= 3:
            header_cells.add(cell)

    fields: list[_DetectedField] = []
    labels: dict[str, _DetectedLabel] = {}
    empty_by_row: dict[float, tuple[float, float, float, float]] = {}
    row_labels: dict[float, _DetectedLabel] = {}
    column_headers: dict[float, _DetectedLabel] = {}
    fragments = _text_fragments(page)
    vector_index = _projection_vector_index(page)
    _charge_projection_comparisons(page.page_index, len(cells))
    for cell in cells:
        if dense_table is not None and _intersects(cell, dense_table):
            continue
        x, y, width, height = cell
        # A left-hand ``Label: [value]`` field is only unambiguous when the
        # value box is a native rectangle.  Line-built table cells can have
        # unrelated colon-terminated text immediately to their left (the
        # ACORD insurer/certificate boundary is one real example).
        native_cell = bool(vector_index.matching_bbox(cell))
        if native_cell:
            _charge_projection_comparisons(
                page.page_index,
                len(fragments),
            )
        external_candidates = (
            [
                fragment
                for fragment in fragments
                if fragment.text.rstrip().endswith(":")
                and 0.5
                <= x - (fragment.bbox[0] + fragment.bbox[2])
                <= 96
                and fragment.bbox[1] <= y + height + 4
                and fragment.bbox[1] + fragment.bbox[3] >= y - 1.5
            ]
            if native_cell
            else []
        )
        if external_candidates:
            nearest_column = min(fragment.bbox[0] for fragment in external_candidates)
            external_candidates = [
                fragment
                for fragment in external_candidates
                if abs(fragment.bbox[0] - nearest_column) <= 3.5
            ]
            if len(external_candidates) > 64:
                raise _ProjectionPageLimitError(page.page_index)
            external_labels: list[_DetectedLabel] = []
            external_label_keys: set[str] = set()
            for label_index, fragment in enumerate(external_candidates):
                spatial_label = _spatial_chars(page, fragment.bbox)
                if spatial_label is None:
                    continue
                label_text, raw_text, label_bbox, refs = spatial_label
                label_key = _form_key(label_text)
                _charge_projection_comparisons(page.page_index, 1)
                if label_key in labels or label_key in external_label_keys:
                    label_key = f"{label_key}-{label_index + 1}"
                external_label_keys.add(label_key)
                external_labels.append(
                    _DetectedLabel(
                        key=label_key,
                        role="field",
                        text=label_text,
                        raw_text=raw_text,
                        bbox=_rounded_bbox(label_bbox),
                        source_objects=refs,
                        target_keys=(),
                    )
                )
            if external_labels:
                field_key = (
                    _form_key(external_labels[0].text)
                    if len(external_labels) == 1
                    else _slug(
                        "-".join(
                            _form_key(label.text) for label in external_labels
                        )
                    )
                )
                spatial_value = _spatial_chars(page, cell)
                if len(external_labels) > 1:
                    value = None
                    value_state: Literal["empty", "present", "ambiguous"] = (
                        "ambiguous"
                    )
                    concerns = ("form_value_state_ambiguous",)
                    value_sources: tuple[_SourceIdentity, ...] = ()
                elif spatial_value is None:
                    value = None
                    value_state = "empty"
                    concerns = ()
                    value_sources = ()
                else:
                    value = spatial_value[0]
                    value_state = "present"
                    concerns = ()
                    value_sources = spatial_value[3]
                label_keys = tuple(label.key for label in external_labels)
                for label in external_labels:
                    labels[label.key] = replace(
                        label,
                        target_keys=(field_key,),
                    )
                fields.append(
                    _DetectedField(
                        key=field_key,
                        group_key=field_key,
                        bbox=cell,
                        label_keys=label_keys,
                        source_objects=_bounded_source_identities(
                            (
                                *_cell_source_objects(page, cell),
                                *value_sources,
                            ),
                            page_index=page.page_index,
                        ),
                        concern_codes=concerns,
                        value=value,
                        value_state=value_state,
                    )
                )
                continue
        spatial = _spatial_chars(page, cell)
        if cell in header_cells:
            if spatial is not None and _looks_like_form_label(spatial[0]):
                text, raw_text, label_bbox, refs = spatial
                key = _form_key(text)
                if key.startswith("insurer-") and key.endswith("-name"):
                    pass
                else:
                    role: Literal["field", "group"] = (
                        "group" if "AFFORDING" in text.upper() else "field"
                    )
                    label_key = (
                        "insurers-affording-coverage"
                        if role == "group"
                        else key
                    )
                    labels[label_key] = _DetectedLabel(
                        key=label_key,
                        role=role,
                        text=text,
                        raw_text=raw_text,
                        bbox=_rounded_bbox(label_bbox),
                        source_objects=refs,
                        target_keys=(),
                    )
                    column_headers[cell[0]] = labels[label_key]
                    continue
            elif spatial is None:
                continue
        if spatial is None:
            empty_by_row[cell[1]] = cell
            continue
        text, raw_text, label_bbox, refs = spatial
        if not _looks_like_form_label(text) or (
            len(text) > 128
            and not text.upper().startswith("DESCRIPTION OF OPERATIONS")
        ):
            continue
        field_key = _form_key(text)
        if not field_key:
            continue
        group_key = _group_key_for_field(field_key, cell, page)
        label_key = field_key
        label = _DetectedLabel(
            key=label_key,
            role="field",
            text=text,
            raw_text=raw_text,
            bbox=_rounded_bbox(label_bbox),
            source_objects=refs,
            target_keys=(field_key,),
        )
        labels[label_key] = label
        fields.append(
            _DetectedField(
                key=field_key,
                group_key=group_key,
                bbox=cell,
                label_keys=(label_key,),
                source_objects=_cell_source_objects(page, cell),
            )
        )
        if field_key.startswith("insurer-") and field_key.endswith("-name"):
            row_labels[cell[1]] = label

    # Repeated empty cells immediately right of row-label cells inherit both
    # their exact row label and the exact column header above.
    naic_header = next(
        (
            label
            for label in column_headers.values()
            if "NAIC" in label.text.upper()
        ),
        None,
    )
    if naic_header is not None:
        naic_targets: list[str] = []
        fields_by_key = {field.key: field for field in fields}
        origin_bucket_size_milli = 150
        cells_by_origin: dict[
            tuple[int, int],
            list[tuple[float, float, float, float]],
        ] = {}
        _charge_projection_comparisons(page.page_index, len(cell_set))
        for candidate in cell_set:
            cells_by_origin.setdefault(
                (
                    _millipoints(candidate[0])
                    // origin_bucket_size_milli,
                    _millipoints(candidate[1])
                    // origin_bucket_size_milli,
                ),
                [],
            ).append(candidate)
        for y, row_label in sorted(row_labels.items()):
            _charge_projection_comparisons(
                page.page_index,
                len(row_label.target_keys),
            )
            row_field = next(
                (
                    fields_by_key[target_key]
                    for target_key in row_label.target_keys
                    if target_key in fields_by_key
                ),
                None,
            )
            if row_field is None:
                continue
            right = row_field.bbox[0] + row_field.bbox[2]
            x_buckets = range(
                (_millipoints(right) - 150)
                // origin_bucket_size_milli,
                (_millipoints(right) + 150)
                // origin_bucket_size_milli
                + 1,
            )
            y_buckets = range(
                (_millipoints(y) - 150)
                // origin_bucket_size_milli,
                (_millipoints(y) + 150)
                // origin_bucket_size_milli
                + 1,
            )
            nearby_cells = tuple(
                candidate
                for x_bucket in x_buckets
                for y_bucket in y_buckets
                for candidate in cells_by_origin.get(
                    (x_bucket, y_bucket),
                    (),
                )
            )
            _charge_projection_comparisons(
                page.page_index,
                len(x_buckets) * len(y_buckets) + len(nearby_cells),
            )
            empty = next(
                (
                    cell
                    for cell in nearby_cells
                    if _within_points(cell[0], right)
                    and _within_points(cell[1], y)
                    and _spatial_chars(page, cell) is None
                ),
                None,
            )
            if empty is None:
                continue
            key = row_field.key.removesuffix("-name") + "-naic"
            naic_targets.append(key)
            fields.append(
                _DetectedField(
                    key=key,
                    group_key=row_field.group_key,
                    bbox=empty,
                    label_keys=(row_label.key, naic_header.key),
                    source_objects=_cell_source_objects(page, empty),
                )
            )
            labels[row_label.key] = replace(
                row_label,
                target_keys=(*row_label.target_keys, key),
            )
        labels[naic_header.key] = replace(
            naic_header,
            target_keys=tuple(naic_targets),
        )

    # An empty native cell may carry its label in the immediately preceding
    # header band (the policy allows at most 12 pt).
    field_bboxes = {field.bbox for field in fields}
    _charge_projection_comparisons(page.page_index, len(cells))
    for cell in cells:
        if _spatial_chars(page, cell) is not None or cell in field_bboxes:
            continue
        above = _spatial_chars(
            page, (cell[0], cell[1], cell[2], min(12.0, cell[1])), above=12.0
        )
        if above is None or not _looks_like_form_label(above[0]):
            continue
        text, raw_text, label_bbox, refs = above
        if label_bbox[1] + label_bbox[3] > cell[1] + 0.5:
            continue
        field_key = _form_key(text)
        if field_key not in {"certificate-holder"}:
            continue
        label = _DetectedLabel(
            key=field_key,
            role="field",
            text=text,
            raw_text=raw_text,
            bbox=_rounded_bbox(label_bbox),
            source_objects=refs,
            target_keys=(field_key,),
        )
        labels[field_key] = label
        fields.append(
            _DetectedField(
                key=field_key,
                group_key=field_key,
                bbox=cell,
                label_keys=(field_key,),
                source_objects=_cell_source_objects(page, cell),
            )
        )
    return tuple(fields), tuple(labels.values())


def _detect_implicit_fields(
    ir: DocumentIR,
    page: FormSourcePage,
) -> tuple[tuple[_DetectedField, ...], tuple[_DetectedLabel, ...]]:
    lookup = _projection_ir_lookup(ir)
    page_record = lookup.pages_by_index.get(page.page_index)
    if page_record is None:
        return (), ()
    elements = lookup.elements
    bboxes = lookup.bboxes
    headings: list[
        tuple[ElementRecord, str, tuple[float, float, float, float]]
    ] = []
    _charge_projection_comparisons(
        page.page_index,
        len(page_record.presentation_element_ids),
    )
    for element_id in page_record.presentation_element_ids:
        element = elements.get(element_id)
        text = _element_text(element) if element is not None else None
        bbox = _bbox_tuple(element, bboxes) if element is not None else None
        if (
            element is not None
            and text is not None
            and bbox is not None
            and element.type.casefold() == "heading"
            and text.rstrip().endswith(":")
            and _looks_like_form_label(text)
        ):
            headings.append((element, text, bbox))
    if not headings:
        return (), ()
    edge_index = _rule_edge_index(page)
    horizontal_y = tuple(edge_index.horizontal_by_y)
    vector_index = _projection_vector_index(page)
    _charge_projection_comparisons(
        page.page_index,
        len(vector_index.rects_by_area),
    )
    page_right = max(
        (
            vector.x1
            for vector in vector_index.rects_by_area
            if _at_most_with_tolerance(vector.x1, page.width)
        ),
        default=page.width,
    )
    fields: list[_DetectedField] = []
    labels: list[_DetectedLabel] = []
    ordered_headings = sorted(headings, key=lambda value: value[2][0])
    heading_x_values = tuple(value[2][0] for value in ordered_headings)
    for _element, text, bbox in ordered_headings:
        source_label = _spatial_chars(
            page,
            (bbox[0] - 0.5, bbox[1] - 1.0, bbox[2] + 1.0, bbox[3] + 2.0),
        )
        if source_label is None:
            continue
        label_text, raw_text, label_bbox, refs = source_label
        if re.sub(r"\s+", " ", label_text).strip() != re.sub(
            r"\s+", " ", text
        ).strip():
            continue
        _charge_projection_comparisons(page.page_index, 6)
        top_index = bisect_right(
            horizontal_y,
            label_bbox[1] + 0.2,
        ) - 1
        if top_index < 0:
            continue
        top = horizontal_y[top_index]
        bottom_index = bisect_right(
            horizontal_y,
            top + 5.9,
            lo=top_index + 1,
        )
        if bottom_index >= len(horizontal_y):
            continue
        bottom = horizontal_y[bottom_index]
        if not 6 <= bottom - top <= 24:
            continue
        later_index = bisect_right(heading_x_values, bbox[0])
        right = (
            heading_x_values[later_index]
            if later_index < len(heading_x_values)
            else page_right
        )
        left = round(label_bbox[0] + label_bbox[2], 3)
        if right - left < 24:
            continue
        field_key = _form_key(label_text)
        field_bbox = _rounded_bbox((left, top, right - left, bottom - top))
        boundary_sources = _implicit_boundary_sources(page, field_bbox)
        if not boundary_sources:
            continue
        fields.append(
            _DetectedField(
                key=field_key,
                group_key=_group_key_for_field(field_key, field_bbox, page),
                bbox=field_bbox,
                label_keys=(field_key,),
                source_objects=boundary_sources,
                concern_codes=("form_value_boundary_implicit",),
            )
        )
        labels.append(
            _DetectedLabel(
                key=field_key,
                role="field",
                text=label_text,
                raw_text=raw_text,
                bbox=_rounded_bbox(label_bbox),
                source_objects=refs,
                target_keys=(field_key,),
            )
        )
    return tuple(fields), tuple(labels)


def _implicit_boundary_sources(
    page: FormSourcePage,
    bbox: tuple[float, float, float, float],
) -> tuple[tuple[str, int, int | None], ...]:
    x, y, width, height = bbox
    right = x + width
    bottom = y + height
    values: set[tuple[str, int, int | None]] = set()
    edge_index = _rule_edge_index(page)
    line_edges = tuple(
        dict.fromkeys(
            (
                *edge_index.nearby("line_horizontal", y),
                *edge_index.nearby("line_horizontal", bottom),
            )
        )
    )
    _charge_projection_comparisons(page.page_index, len(line_edges))
    for edge in line_edges:
        if (
            (
                _within_points(edge.coordinate, y)
                or _within_points(edge.coordinate, bottom)
            )
            and min(edge.end, right) - max(edge.start, x) > 0.5
        ):
            values.add(("line", edge.source_index, None))
    adjacent_rects = _projection_vector_index(page).adjacent_at_top(
        bottom,
        x,
        right,
    )
    if adjacent_rects:
        rectangle = min(
            adjacent_rects,
            key=lambda vector: (vector.x1 - vector.x0) * (vector.bottom - vector.top),
        )
        values.add(("rect", rectangle.index, None))
    return tuple(sorted(values))


def _looks_like_form_label(text: str) -> bool:
    if not text or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        return False
    prefix = text.split("(", 1)[0].strip()
    letters = [character for character in prefix if character.isalpha()]
    return (
        bool(letters)
        and sum(character.isupper() for character in letters) / len(letters) >= 0.85
        and len(text) <= 160
    )


_STATIC_PARTIES_BASE_FIELDS = (
    "producer",
    "insured",
    "contact-name",
    "phone",
    "fax",
    "email-address",
)
_STATIC_PARTIES_LABEL_TEXT = {
    "producer": "PRODUCER",
    "insured": "INSURED",
    "contact-name": "CONTACT NAME:",
    "phone": "PHONE (A/C, NO, EXT):",
    "fax": "FAX (A/C, NO):",
    "email-address": "E-MAIL ADDRESS:",
}
_STATIC_INSURER_GROUP_TEXT = "INSURER(S) AFFORDING COVERAGE"
_STATIC_INSURER_SHARED_TEXT = "NAIC #"
_STATIC_INSURER_FIELD_RE = re.compile(
    r"insurer-([a-z])-(name|naic)",
    re.ASCII,
)


def _normalized_form_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().upper()


def _static_insurer_rows(field_keys: set[str]) -> tuple[str, ...] | None:
    remaining = field_keys - set(_STATIC_PARTIES_BASE_FIELDS)
    parsed: dict[str, set[str]] = {}
    for field_key in remaining:
        match = _STATIC_INSURER_FIELD_RE.fullmatch(field_key)
        if match is None:
            return None
        parsed.setdefault(match.group(1), set()).add(match.group(2))
    if not 2 <= len(parsed) <= 26 or any(
        roles != {"name", "naic"} for roles in parsed.values()
    ):
        return None
    return tuple(sorted(parsed))


def _bbox_contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    tolerance: float = 0.5,
) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[0] + inner[2] <= outer[0] + outer[2] + tolerance
        and inner[1] + inner[3] <= outer[1] + outer[3] + tolerance
    )


def _complete_static_parties_and_insurers_candidate(
    *,
    group_key: str,
    group_bbox: tuple[float, float, float, float],
    fields: Sequence[_DetectedField],
    labels: Sequence[_DetectedLabel],
    controls: Sequence[_DetectedControl],
) -> bool:
    """Admit one source-complete static contact/insurer graph.

    This is intentionally narrower than ordinary form detection.  Canonical
    replacement suppresses every predecessor contributor, so it is allowed
    only when the detected graph can present every printed label once without
    asserting a value for a blank source field.
    """

    if group_key != "parties-and-insurers" or controls:
        return False
    fields_by_key = {field.key: field for field in fields}
    if len(fields_by_key) != len(fields) or not set(
        _STATIC_PARTIES_BASE_FIELDS
    ).issubset(fields_by_key):
        return False
    insurer_rows = _static_insurer_rows(set(fields_by_key))
    if insurer_rows is None or any(
        field.value is not None
        or field.value_state != "empty"
        or field.concern_codes
        or not field.source_objects
        or not any(
            source_kind in {"line", "rect"}
            for source_kind, _first, _second in field.source_objects
        )
        or not _bbox_contains(group_bbox, field.bbox)
        for field in fields
    ):
        return False

    labels_by_key = {label.key: label for label in labels}
    expected_label_keys = {
        *_STATIC_PARTIES_BASE_FIELDS,
        "insurers-affording-coverage",
        "naic",
        *(f"insurer-{row}-name" for row in insurer_rows),
    }
    if set(labels_by_key) != expected_label_keys or any(
        not label.source_objects
        or any(
            source_kind != "character_range"
            for source_kind, _first, _second in label.source_objects
        )
        or not _bbox_contains(group_bbox, label.bbox)
        for label in labels
    ):
        return False

    for field_key, expected_text in _STATIC_PARTIES_LABEL_TEXT.items():
        label = labels_by_key[field_key]
        if (
            label.role != "field"
            or label.target_keys != (field_key,)
            or fields_by_key[field_key].label_keys != (field_key,)
            or _normalized_form_label(label.text) != expected_text
        ):
            return False
    group_label = labels_by_key["insurers-affording-coverage"]
    shared_label = labels_by_key["naic"]
    expected_naic_keys = tuple(f"insurer-{row}-naic" for row in insurer_rows)
    if (
        group_label.role != "group"
        or group_label.target_keys != (group_key,)
        or _normalized_form_label(group_label.text)
        != _STATIC_INSURER_GROUP_TEXT
        or shared_label.role != "field"
        or set(shared_label.target_keys) != set(expected_naic_keys)
        or _normalized_form_label(shared_label.text)
        != _STATIC_INSURER_SHARED_TEXT
    ):
        return False

    producer = fields_by_key["producer"]
    insured = fields_by_key["insured"]
    contact = fields_by_key["contact-name"]
    phone = fields_by_key["phone"]
    fax = fields_by_key["fax"]
    email = fields_by_key["email-address"]
    if not (
        producer.bbox[0] < contact.bbox[0]
        and insured.bbox[0] < contact.bbox[0]
        and producer.bbox[1] < insured.bbox[1]
        and contact.bbox[1] <= phone.bbox[1] <= email.bbox[1]
        and abs(phone.bbox[1] - fax.bbox[1]) <= 1.0
        and phone.bbox[0] < fax.bbox[0]
    ):
        return False

    prior_top: float | None = None
    for row in insurer_rows:
        row_label_key = f"insurer-{row}-name"
        name_key = f"insurer-{row}-name"
        naic_key = f"insurer-{row}-naic"
        row_label = labels_by_key[row_label_key]
        name_field = fields_by_key[name_key]
        naic_field = fields_by_key[naic_key]
        if (
            row_label.role != "field"
            or set(row_label.target_keys) != {name_key, naic_key}
            or fields_by_key[name_key].label_keys != (row_label_key,)
            or set(fields_by_key[naic_key].label_keys)
            != {row_label_key, "naic"}
            or _normalized_form_label(row_label.text)
            != f"INSURER {row.upper()} :"
            or abs(name_field.bbox[1] - naic_field.bbox[1]) > 1.0
            or name_field.bbox[0] >= naic_field.bbox[0]
            or (prior_top is not None and name_field.bbox[1] <= prior_top)
        ):
            return False
        prior_top = name_field.bbox[1]
    first_name = fields_by_key[f"insurer-{insurer_rows[0]}-name"]
    if not (
        group_label.bbox[1] < first_name.bbox[1]
        and shared_label.bbox[1] < first_name.bbox[1]
    ):
        return False
    return True


def _static_page_form_candidate(
    ir: DocumentIR,
    page: FormSourcePage,
    cells: Sequence[tuple[float, float, float, float]],
) -> tuple[_GroupCandidate, ...]:
    ruled_fields, ruled_labels = _detect_ruled_fields(ir, page, cells)
    implicit_fields, implicit_labels = _detect_implicit_fields(ir, page)
    if (
        len(ruled_fields) + len(implicit_fields)
        > MAX_FORM_CLASS_RECORDS_PER_PAGE
    ):
        raise _ProjectionPageLimitError(page.page_index)
    fields = list(
        _assign_static_field_groups(
            ir,
            page,
            (*ruled_fields, *implicit_fields),
        )
    )
    labels: dict[str, _DetectedLabel] = {
        label.key: label for label in (*ruled_labels, *implicit_labels)
    }
    if not fields:
        return ()

    dense_table = _dense_preserved_table_bbox(
        ir, page.page_index, page.width, page.height
    )
    _charge_projection_comparisons(page.page_index, len(fields))
    coverage_fields = [field for field in fields if field.group_key == "coverages"]
    if coverage_fields and dense_table is not None:
        top = min(field.bbox[1] for field in coverage_fields)
        edge_index = _rule_edge_index(page)
        left_edges = edge_index.nearby(
            "vertical",
            dense_table[0],
            tolerance=2.0,
        )
        _charge_projection_comparisons(
            page.page_index,
            len(left_edges),
        )
        left = min(
            (
                edge.coordinate
                for edge in left_edges
            ),
            default=round(dense_table[0], 3),
        )
        right_edges = edge_index.nearby(
            "vertical",
            dense_table[0] + dense_table[2],
            tolerance=2.0,
        )
        _charge_projection_comparisons(
            page.page_index,
            len(right_edges),
        )
        right = max(
            (
                edge.coordinate
                for edge in right_edges
            ),
            default=round(dense_table[0] + dense_table[2], 3),
        )
        table_bottom = dense_table[1] + dense_table[3]
        bottom_edges = edge_index.nearby(
            "horizontal",
            table_bottom,
            tolerance=3.0,
        )
        _charge_projection_comparisons(
            page.page_index,
            len(bottom_edges),
        )
        bottom = min(
            (
                edge.coordinate
                for edge in bottom_edges
            ),
            key=lambda value: abs(value - table_bottom),
            default=round(table_bottom, 3),
        )
        coverage_bbox = _rounded_bbox((left, top, right - left, bottom - top))
        coverage_group_key = coverage_fields[0].group_key
        controls, control_labels = _detect_static_controls(
            page,
            group_bbox=coverage_bbox,
            group_key=coverage_group_key,
        )
        if len(controls) > MAX_FORM_CONTROLS_PER_GROUP:
            raise _ProjectionPageLimitError(page.page_index)
        labels.update({label.key: label for label in control_labels})
    else:
        coverage_bbox = None
        controls = ()

    # Existing source-grounded headings become group labels only when their
    # visible slug names an already detected spatial group and no field owns
    # the same label.
    lookup = _projection_ir_lookup(ir)
    page_record = lookup.pages_by_index[page.page_index]
    elements = lookup.elements
    bboxes = lookup.bboxes
    detected_group_keys = {field.group_key for field in fields} | {
        control.group_key for control in controls
    }
    field_label_keys = {key for field in fields for key in field.label_keys}
    _charge_projection_comparisons(
        page.page_index,
        len(page_record.presentation_element_ids),
    )
    for element_id in page_record.presentation_element_ids:
        element = elements[element_id]
        text = _element_text(element)
        bbox = _bbox_tuple(element, bboxes)
        if (
            text is None
            or bbox is None
            or element.type.casefold() != "heading"
            or not _looks_like_form_label(text)
        ):
            continue
        key = _slug(text.rstrip(":"))
        if key not in detected_group_keys or key in field_label_keys:
            continue
        source = _spatial_chars(
            page,
            (bbox[0] - 0.5, bbox[1] - 1.0, bbox[2] + 1.0, bbox[3] + 2.0),
        )
        if source is None:
            continue
        source_text, raw_text, source_bbox, refs = source
        labels[key] = _DetectedLabel(
            key=key,
            role="group",
            text=source_text,
            raw_text=raw_text,
            bbox=_rounded_bbox(source_bbox),
            source_objects=refs,
            target_keys=(key,),
        )
    if "insurers-affording-coverage" in labels:
        labels["insurers-affording-coverage"] = replace(
            labels["insurers-affording-coverage"],
            target_keys=("parties-and-insurers",),
        )

    candidates: list[_GroupCandidate] = []
    for group_key in sorted(detected_group_keys):
        _charge_projection_comparisons(
            page.page_index,
            len(fields) + len(controls),
        )
        group_fields = [field for field in fields if field.group_key == group_key]
        group_controls = [
            control for control in controls if control.group_key == group_key
        ]
        if (
            len(group_fields) > MAX_FORM_FIELDS_PER_GROUP
            or len(group_controls) > MAX_FORM_CONTROLS_PER_GROUP
        ):
            raise _ProjectionPageLimitError(page.page_index)
        if group_key == "coverages" and coverage_bbox is not None:
            group_bbox = coverage_bbox
        elif group_key == "cancellation" and group_fields:
            group_bbox = _smallest_native_container(
                page, group_fields[0].bbox
            ) or _union_bboxes([field.bbox for field in group_fields])
        else:
            group_bbox = _union_bboxes(
                [field.bbox for field in group_fields]
                + [control.bbox for control in group_controls]
            )
        contributor_data = _group_contributors(
            ir,
            page_index=page.page_index,
            group_key=group_key,
            group_bbox=group_bbox,
            dense_table_bbox=(dense_table if group_key == "coverages" else None),
        )
        if contributor_data is None:
            owner_keys = {
                *(field.key for field in group_fields),
                group_key,
            }
            _charge_projection_comparisons(
                page.page_index,
                len(labels),
            )
            relevant_label_bboxes = [
                label.bbox
                for label in labels.values()
                if owner_keys.intersection(label.target_keys)
            ]
            contributor_data = _interactive_group_contributors(
                ir,
                page_index=page.page_index,
                source_bboxes=[
                    *(field.bbox for field in group_fields),
                    *(control.bbox for control in group_controls),
                    *relevant_label_bboxes,
                ],
            )
        if contributor_data is None:
            continue
        (
            anchor_public_item_id,
            anchor_element_id,
            contributor_public_item_ids,
            contributor_element_ids,
        ) = contributor_data
        owner_keys = {
            *(field.key for field in group_fields),
            *(control.key for control in group_controls),
            group_key,
        }
        _charge_projection_comparisons(
            page.page_index,
            len(labels),
        )
        group_labels = [
            label
            for label in labels.values()
            if owner_keys.intersection(label.target_keys)
        ]
        if len(group_labels) > MAX_FORM_LABELS_PER_GROUP:
            raise _ProjectionPageLimitError(page.page_index)
        group_labels.sort(
            key=lambda label: (
                label.bbox[1],
                label.bbox[0],
                label.source_objects[0][1],
                label.key,
            )
        )
        group_fields.sort(key=lambda field: (field.bbox[1], field.bbox[0], field.key))
        group_controls.sort(
            key=lambda control: (control.bbox[1], control.bbox[0], control.key)
        )
        canonical_mode: Literal["inert", "replace"] = (
            "replace"
            if _complete_static_parties_and_insurers_candidate(
                group_key=group_key,
                group_bbox=group_bbox,
                fields=group_fields,
                labels=group_labels,
                controls=group_controls,
            )
            else "inert"
        )
        records: list[_RecordCandidate] = []
        relationships: list[tuple[str, str, str]] = []
        field_keys = {field.key for field in group_fields}
        control_keys = {control.key for control in group_controls}
        valid_label_relationships = 0
        for label in group_labels:
            _charge_projection_comparisons(
                page.page_index,
                len(label.target_keys),
            )
            valid_label_relationships += sum(
                (
                    target_key == group_key and label.role == "group"
                )
                or target_key in field_keys
                or target_key in control_keys
                for target_key in label.target_keys
            )
        _reserve_projection_candidate(
            page_index=page.page_index,
            roles={
                "field": len(group_fields),
                "value_region": len(group_fields),
                "label": len(group_labels),
                "control": len(group_controls),
            },
            relationships=(
                3 * len(group_fields)
                + 2 * len(group_controls)
                + len(group_labels)
                + valid_label_relationships
                + (group_key == "coverages" or canonical_mode == "replace")
            ),
        )
        for field in group_fields:
            field_token = f"field:{field.key}"
            value_token = f"value-region:{field.key}"
            records.append(
                _RecordCandidate(
                    token=field_token,
                    role="field",
                    key=field.key,
                    bbox=field.bbox,
                    source_objects=field.source_objects,
                    data={
                        "value": field.value,
                        "value_state": field.value_state,
                    },
                    concern_codes=field.concern_codes,
                )
            )
            records.append(
                _RecordCandidate(
                    token=value_token,
                    role="value_region",
                    key=field.key,
                    bbox=field.bbox,
                    source_objects=field.source_objects,
                    data={
                        "value": field.value,
                        "value_state": field.value_state,
                    },
                    concern_codes=field.concern_codes,
                )
            )
            relationships.extend(
                (
                    ("contains", f"group:{group_key}", field_token),
                    ("contains", field_token, value_token),
                    ("value_of", value_token, field_token),
                )
            )
        for label in group_labels:
            label_token = f"label:{label.key}"
            records.append(
                _RecordCandidate(
                    token=label_token,
                    role="label",
                    key=label.key,
                    bbox=label.bbox,
                    source_objects=label.source_objects,
                    data={
                        "label_role": label.role,
                        "text": label.text,
                        "raw_text": label.raw_text,
                    },
                )
            )
            relationships.append(
                ("contains", f"group:{group_key}", label_token)
            )
            for target_key in label.target_keys:
                _charge_projection_comparisons(page.page_index, 1)
                if target_key == group_key and label.role == "group":
                    target_token = f"group:{group_key}"
                elif target_key in field_keys:
                    target_token = f"field:{target_key}"
                elif target_key in control_keys:
                    target_token = f"control:{target_key}"
                else:
                    continue
                relationships.append(("label_of", label_token, target_token))
        for control in group_controls:
            control_token = f"control:{control.key}"
            records.append(
                _RecordCandidate(
                    token=control_token,
                    role="control",
                    key=control.key,
                    bbox=control.bbox,
                    source_objects=control.source_objects,
                    data={
                        "control_type": "checkbox",
                        "state": control.state,
                        "origin": "static_vector",
                    },
                    concern_codes=control.concern_codes,
                )
            )
            relationships.extend(
                (
                    ("contains", f"group:{group_key}", control_token),
                    ("control_of", control_token, f"group:{group_key}"),
                )
            )
        if group_key == "coverages" or canonical_mode == "replace":
            relationships.append(
                (
                    "form_overlay_of",
                    f"group:{group_key}",
                    f"anchor-element:{anchor_element_id}",
                )
            )
        group_sources = _cell_source_objects(page, group_bbox)
        if group_key == "coverages" and dense_table is not None:
            retained: list[tuple[str, int, int | None]] = []
            vector_index = _projection_vector_index(page)
            _charge_projection_comparisons(
                page.page_index,
                len(group_sources),
            )
            for source in group_sources:
                vector = vector_index.vectors_by_identity.get(
                    (source[0], source[1])
                )
                if (
                    vector is not None
                    and vector.kind == "rect"
                    and min(vector.bottom, group_bbox[1] + group_bbox[3])
                    - max(vector.top, group_bbox[1])
                    <= 0.5
                ):
                    continue
                retained.append(source)
            table_top = dense_table[1]
            nearby_table_edges = _rule_edge_index(page).nearby(
                "line_horizontal",
                table_top,
                tolerance=1.0,
            )
            _charge_projection_comparisons(
                page.page_index,
                len(nearby_table_edges),
            )
            table_edges = [
                edge
                for edge in nearby_table_edges
                if _edge_coverage(
                    [edge],
                    group_bbox[0],
                    group_bbox[0] + group_bbox[2],
                    page_index=page.page_index,
                )
            ]
            retained.extend(
                (edge.source_kind, edge.source_index, None)
                for edge in table_edges
            )
            _charge_projection_comparisons(
                page.page_index,
                len(vector_index.rects_by_area),
            )
            table_containers = [
                vector
                for vector in vector_index.rects_by_area
                if max(
                    0.0,
                    min(vector.x1, dense_table[0] + dense_table[2])
                    - max(vector.x0, dense_table[0]),
                )
                * max(
                    0.0,
                    min(vector.bottom, dense_table[1] + dense_table[3])
                    - max(vector.top, dense_table[1]),
                )
                >= 0.9 * dense_table[2] * dense_table[3]
            ]
            if table_containers:
                table_container = min(
                    table_containers,
                    key=lambda vector: (
                        (vector.x1 - vector.x0)
                        * (vector.bottom - vector.top),
                        vector.index,
                    ),
                )
                retained.append(("rect", table_container.index, None))
            group_sources = tuple(sorted(set(retained)))
        if not group_sources:
            group_sources = _bounded_source_identities(
                (
                    source
                    for record in records
                    for source in record.source_objects
                ),
                page_index=page.page_index,
            )
        group_concerns = (
            ["form_table_ownership_ambiguous"]
            if group_key == "coverages"
            else []
        )
        if any(field.value_state == "ambiguous" for field in group_fields):
            group_concerns.append("form_value_state_ambiguous")
        candidates.append(
            _GroupCandidate(
                group_key=group_key,
                page_index=page.page_index,
                bbox=group_bbox,
                status=("unresolved" if group_concerns else "resolved"),
                interactivity="static",
                canonical_mode=canonical_mode,
                anchor_public_item_id=anchor_public_item_id,
                anchor_element_id=anchor_element_id,
                contributor_public_item_ids=contributor_public_item_ids,
                contributor_element_ids=contributor_element_ids,
                records=tuple(records),
                relationships=tuple(relationships),
                source_objects=group_sources,
                concern_codes=tuple(group_concerns),
            )
        )
    return tuple(candidates)


def _assign_static_field_groups(
    ir: DocumentIR,
    page: FormSourcePage,
    fields: Sequence[_DetectedField],
) -> tuple[_DetectedField, ...]:
    if not fields:
        return ()
    budget = _PROJECTION_BUDGET.get()
    comparisons = 0

    def account(count: int = 1) -> None:
        nonlocal comparisons
        comparisons += count
        if budget is not None:
            budget.account_comparisons(page.page_index, count)
        elif comparisons > MAX_COMPARISONS_PER_PAGE:
            raise ValueError("form projection comparison limit exceeded")

    pair_count = len(fields) * (len(fields) - 1) // 2
    account(pair_count)
    account(len(page.vectors))
    native_rects = sorted(
        (
            vector for vector in page.vectors if vector.kind == "rect"
        ),
        key=lambda vector: (
            (vector.x1 - vector.x0) * (vector.bottom - vector.top),
            vector.index,
        ),
    )
    dense_table = _dense_preserved_table_bbox(
        ir, page.page_index, page.width, page.height
    )
    parent = list(range(len(fields)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        left = root(first)
        right = root(second)
        if left != right:
            parent[right] = left

    container_ids_by_field: list[frozenset[int]] = []
    for candidate_field in fields:
        container_ids: set[int] = set()
        for vector in native_rects:
            account()
            if (
                _at_most_with_tolerance(
                    vector.x0,
                    candidate_field.bbox[0],
                )
                and _at_most_with_tolerance(
                    vector.top,
                    candidate_field.bbox[1],
                )
                and _at_least_with_tolerance(
                    vector.x1,
                    candidate_field.bbox[0] + candidate_field.bbox[2],
                )
                and _at_least_with_tolerance(
                    vector.bottom,
                    candidate_field.bbox[1] + candidate_field.bbox[3],
                )
            ):
                container_ids.add(vector.index)
        container_ids_by_field.append(frozenset(container_ids))

    def shares_native_container(
        first_index: int,
        second_index: int,
    ) -> bool:
        first_ids = container_ids_by_field[first_index]
        second_ids = container_ids_by_field[second_index]
        account(min(len(first_ids), len(second_ids)))
        return not first_ids.isdisjoint(second_ids)

    for first_index, first in enumerate(fields):
        for second_index in range(first_index + 1, len(fields)):
            second = fields[second_index]
            aligned_stack = (
                any(source[0] == "rect" for source in first.source_objects)
                and any(
                    source[0] == "rect" for source in second.source_objects
                )
                and _within_points(first.bbox[0], second.bbox[0])
                and _within_points(first.bbox[2], second.bbox[2])
                and max(
                    0.0,
                    max(first.bbox[1], second.bbox[1])
                    - min(
                        first.bbox[1] + first.bbox[3],
                        second.bbox[1] + second.bbox[3],
                    ),
                )
                <= 1.5 * max(first.bbox[3], second.bbox[3])
            )
            if aligned_stack or shares_native_container(
                first_index,
                second_index,
            ):
                union(first_index, second_index)
    components: dict[int, list[int]] = {}
    for index in range(len(fields)):
        components.setdefault(root(index), []).append(index)

    lookup = _projection_ir_lookup(ir)
    page_record = lookup.pages_by_index[page.page_index]
    elements = lookup.elements
    bboxes = lookup.bboxes
    headings: list[tuple[str, tuple[float, float, float, float]]] = []
    account(len(page_record.presentation_element_ids))
    for element_id in page_record.presentation_element_ids:
        element = elements[element_id]
        text = _element_text(element)
        bbox = _bbox_tuple(element, bboxes)
        if (
            text is not None
            and bbox is not None
            and element.type.casefold() == "heading"
            and _looks_like_form_label(text)
        ):
            headings.append((text, bbox))

    assigned = list(fields)
    for indexes in components.values():
        component = [fields[index] for index in indexes]
        component_bbox = _union_bboxes([field.bbox for field in component])
        keys = {field.key for field in component}
        if (
            {"producer", "insured"} <= keys
            and any(key.startswith("insurer-") for key in keys)
        ):
            group_key = "parties-and-insurers"
        else:
            account(len(native_rects))
            containing_rects = [
                vector
                for vector in native_rects
                if _at_most_with_tolerance(
                    vector.x0,
                    component_bbox[0],
                )
                and _at_most_with_tolerance(
                    vector.top,
                    component_bbox[1],
                )
                and _at_least_with_tolerance(
                    vector.x1,
                    component_bbox[0] + component_bbox[2],
                )
                and _at_least_with_tolerance(
                    vector.bottom,
                    component_bbox[1] + component_bbox[3],
                )
            ]
            container = min(
                containing_rects,
                key=lambda vector: (
                    (vector.x1 - vector.x0) * (vector.bottom - vector.top),
                    vector.index,
                ),
                default=None,
            )
            account(len(headings) * 2)
            container_headings = [
                (text, bbox)
                for text, bbox in headings
                if container is not None
                and not (
                    dense_table is not None
                    and _intersects(
                        (
                            container.x0,
                            container.top,
                            container.x1 - container.x0,
                            container.bottom - container.top,
                        ),
                        dense_table,
                    )
                )
                and bbox[1] + bbox[3] <= component_bbox[1] + 0.5
                and bbox[0] >= container.x0 - 0.5
                and bbox[0] + bbox[2] <= container.x1 + 0.5
                and bbox[1] + bbox[3] >= container.top - 12
                and _slug(text.rstrip(":")) not in keys
            ]
            immediately_above = [
                (text, bbox)
                for text, bbox in headings
                if bbox[1] + bbox[3] <= component_bbox[1] + 0.5
                and 0 <= component_bbox[1] - (bbox[1] + bbox[3]) <= 12
                and bbox[0] >= component_bbox[0] - 0.5
                and bbox[0] + bbox[2]
                <= component_bbox[0] + component_bbox[2] + 0.5
            ]
            if container_headings:
                text, _bbox = min(
                    container_headings,
                    key=lambda value: component_bbox[1]
                    - (value[1][1] + value[1][3]),
                )
                group_key = _slug(text.rstrip(":"))
            elif immediately_above:
                text, _bbox = min(
                    immediately_above,
                    key=lambda value: component_bbox[1]
                    - (value[1][1] + value[1][3]),
                )
                group_key = _slug(text.rstrip(":"))
            elif len(component) == 1:
                group_key = component[0].key
            else:
                group_key = _slug("-and-".join(sorted(keys)[:3]))
        for index in indexes:
            assigned[index] = replace(fields[index], group_key=group_key)

    # Implicit aligned fields have no four-sided container. Bind co-linear
    # fields to the nearest source-visible, non-field heading on that band.
    field_keys = {field.key for field in assigned}
    for index, field in enumerate(assigned):
        if "form_value_boundary_implicit" not in field.concern_codes:
            continue
        account(len(headings))
        band_headings = [
            (text, bbox)
            for text, bbox in headings
            if abs(bbox[1] - field.bbox[1]) <= 12
            and bbox[0] < field.bbox[0]
            and _slug(text.rstrip(":")) not in field_keys
        ]
        if band_headings:
            text, _bbox = min(band_headings, key=lambda value: value[1][0])
            assigned[index] = replace(
                field,
                group_key=_slug(text.rstrip(":")),
            )
    if budget is not None:
        budget.check_deadline()
    return tuple(assigned)


def _union_bboxes(
    bboxes: Sequence[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    if not bboxes:
        raise ValueError("cannot union an empty form bbox set")
    left = min(bbox[0] for bbox in bboxes)
    top = min(bbox[1] for bbox in bboxes)
    right = max(bbox[0] + bbox[2] for bbox in bboxes)
    bottom = max(bbox[1] + bbox[3] for bbox in bboxes)
    return _rounded_bbox((left, top, right - left, bottom - top))


def _smallest_native_container(
    page: FormSourcePage,
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    container = _projection_vector_index(page).smallest_container(bbox)
    if container is None:
        return None
    return _rounded_bbox(
        (
            container.x0,
            container.top,
            container.x1 - container.x0,
            container.bottom - container.top,
        )
    )


def _group_contributors(
    ir: DocumentIR,
    *,
    page_index: int,
    group_key: str,
    group_bbox: tuple[float, float, float, float],
    dense_table_bbox: tuple[float, float, float, float] | None,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]] | None:
    index = _projection_presentation_index(ir, page_index)
    if not index.records:
        return None
    values: list[_PresentationCandidate] = []
    vertical_candidates = index.vertical_candidates(
        group_bbox[1] - 12,
        group_bbox[1] + group_bbox[3],
    )
    _charge_projection_comparisons(
        page_index,
        len(vertical_candidates),
    )
    for candidate in vertical_candidates:
        element = candidate.element
        bbox = candidate.bbox
        inside = _intersects(bbox, group_bbox)
        immediately_above = (
            bbox[1] + bbox[3] <= group_bbox[1] + 0.5
            and 0 <= group_bbox[1] - (bbox[1] + bbox[3]) <= 12
            and bbox[0] >= group_bbox[0] - 0.5
            and bbox[0] + bbox[2] <= group_bbox[0] + group_bbox[2] + 0.5
        )
        visible_text = _element_text(element) if immediately_above else None
        if inside or (
            immediately_above
            and visible_text is not None
            and len(visible_text) <= 128
            and _looks_like_form_label(visible_text)
        ):
            values.append(candidate)
    if group_key == "coverages":
        _charge_projection_comparisons(page_index, len(values))
        values = [
            value
            for value in values
            if value.element.type.casefold() in {"heading", "table"}
            and not (
                value.element.type.casefold() == "table"
                and dense_table_bbox is not None
                and not _intersects(value.bbox, dense_table_bbox)
            )
        ]
    elif group_key == "parties-and-insurers":
        values.sort(
            key=lambda value: (
                0
                if value.bbox[0] < group_bbox[0] + group_bbox[2] / 2
                else 1,
                0 if value.element.type.casefold() == "table" else 1,
                value.bbox[1],
                int(value.legacy.get("reading_order", 0)),
            )
        )
    else:
        values.sort(
            key=lambda value: int(
                value.legacy.get("reading_order", 0)
            )
        )
    if not values:
        return None
    if len(values) > 64:
        raise _ProjectionPageLimitError(page_index)
    _charge_projection_comparisons(page_index, len(values))
    tables = [
        value
        for value in values
        if value.element.type.casefold() == "table"
    ]
    anchor = tables[0] if tables else values[0]
    if group_key == "coverages":
        values.sort(
            key=lambda value: (
                1 if value.element.type.casefold() == "table" else 0,
                value.bbox[0],
            )
        )
    public_ids = tuple(str(value.legacy["id"]) for value in values)
    element_ids = tuple(value.element.id for value in values)
    return (
        str(anchor.legacy["id"]),
        anchor.element.id,
        public_ids,
        element_ids,
    )


def render_form_group_semantics(
    anchor: ElementRecord,
    *,
    elements_by_id: Mapping[str, ElementRecord] | None = None,
) -> FormGroupRendering | None:
    """Render a complete validated replace-mode sidecar without HTML."""

    legacy = _legacy_item(anchor)
    if legacy is None or legacy.get("layout_forms_projected") is not True or (
        legacy.get("form_policy") != POLICY_ID
    ):
        return None
    try:
        group = PublicFormGroup.model_validate(legacy.get("form_group"))
        if group.anchor_element_id != anchor.id or (
            group.anchor_public_item_id != legacy.get("id")
            or group.canonical_mode != "replace"
            or anchor.id not in group.contributor_element_ids
        ):
            return None
        anchor_index = group.contributor_element_ids.index(anchor.id)
        if group.contributor_public_item_ids[anchor_index] != legacy.get("id"):
            return None
        parsed_records: dict[str, list[_PublicRecord]] = {}
        for key, expected_ids, model in (
            ("form_fields", group.field_ids, PublicFormField),
            ("form_labels", group.label_ids, PublicFormLabel),
            ("form_value_regions", group.value_region_ids, PublicFormValueRegion),
            ("form_controls", group.control_ids, PublicFormControl),
            ("form_key_value_pairs", group.key_value_pair_ids, PublicKeyValuePair),
        ):
            raw_values = legacy.get(key)
            if not expected_ids:
                if key in legacy:
                    return None
                parsed_records[key] = []
                continue
            if not isinstance(raw_values, list) or len(raw_values) != len(
                expected_ids
            ):
                return None
            records = [model.model_validate(value) for value in raw_values]
            if [record.id for record in records] != expected_ids:
                return None
            parsed_records[key] = records
        fields = parsed_records["form_fields"]
        labels = parsed_records["form_labels"]
        values = parsed_records["form_value_regions"]
        controls = parsed_records["form_controls"]
        pairs = parsed_records["form_key_value_pairs"]
        all_records: list[_PublicRecord] = [
            group,
            *fields,
            *labels,
            *values,
            *controls,
            *pairs,
        ]
        if any(
            record.group_id != group.id or record.page_index != group.page_index
            for record in all_records[1:]
        ):
            return None
        record_ids = {record.id for record in all_records}
        element_ids = {record.element_id for record in all_records}
        if len(record_ids) != len(all_records) or len(element_ids) != len(all_records):
            return None
        labels_by_id = {label.id: label for label in labels}
        values_by_id = {value.id: value for value in values}
        controls_by_id = {control.id: control for control in controls}
        if group.value_region_ids != [
            *(field.value_region_id for field in fields),
            *(pair.value_region_id for pair in pairs),
        ]:
            return None
        for field in fields:
            value = values_by_id.get(field.value_region_id)
            if (
                value is None
                or value.owner_id != field.id
                or value.excluded_label_ids != field.label_ids
                or any(label_id not in labels_by_id for label_id in field.label_ids)
                or any(control_id not in controls_by_id for control_id in field.control_ids)
            ):
                return None
        for pair in pairs:
            value = values_by_id.get(pair.value_region_id)
            label = labels_by_id.get(pair.key_label_id)
            if (
                value is None
                or value.owner_id != pair.id
                or value.excluded_label_ids
                or value.value != pair.value
                or value.value_state != "present"
                or label is None
                or label.key_of_ids != [pair.id]
                or label.text != pair.key
            ):
                return None
        for control in controls:
            if (
                control.owner_field_id is not None
                and control.owner_field_id not in {field.id for field in fields}
            ) or (
                control.label_id is not None
                and control.label_id not in labels_by_id
            ):
                return None
        relationship_payload = legacy.get("relationships")
        if not isinstance(relationship_payload, list):
            return None
        referenced_relationship_ids = {
            relationship_id
            for record in all_records
            for relationship_id in record.relationship_ids
        } | set(group.anchor_relationship_ids)
        relationships: list[FormRelationship] = []
        for value in relationship_payload:
            if not isinstance(value, Mapping) or value.get("id") not in (
                referenced_relationship_ids
            ):
                continue
            if set(value) != {
                "id",
                "type",
                "source_id",
                "target_id",
                "evidence_ids",
                "canonical_inert",
            }:
                return None
            relationships.append(FormRelationship.model_validate(value))
        relationship_ids = [relationship.id for relationship in relationships]
        if (
            len(relationship_ids) != len(set(relationship_ids))
            or set(relationship_ids) != referenced_relationship_ids
            or not relationship_ids
        ):
            return None
        backlink_counts = Counter(
            relationship_id
            for record in all_records
            for relationship_id in record.relationship_ids
        )
        backlink_counts.update(group.anchor_relationship_ids)
        if backlink_counts != Counter({value: 2 for value in relationship_ids}):
            return None
        known_endpoints = element_ids | set(group.contributor_element_ids)
        if any(
            relationship.source_id not in known_endpoints
            or relationship.target_id not in known_endpoints
            for relationship in relationships
        ):
            return None
        for record in all_records:
            if record.relationship_ids != [
                relationship.id
                for relationship in relationships
                if record.element_id
                in {relationship.source_id, relationship.target_id}
            ]:
                return None
        if group.anchor_relationship_ids != [
            relationship.id
            for relationship in relationships
            if anchor.id in {relationship.source_id, relationship.target_id}
        ]:
            return None
        compact_sidecar = {
            key: legacy[key]
            for key in _PUBLIC_FORM_KEYS
            if key in legacy
        }
        compact_sidecar["relationships"] = [
            relationship.model_dump(mode="json") for relationship in relationships
        ]
        if (
            _compact_public_sidecar_size(
                compact_sidecar,
                limit=MAX_PUBLIC_GROUP_BYTES,
            )
            > MAX_PUBLIC_GROUP_BYTES
        ):
            return None
        if elements_by_id is not None:
            if any(
                element_id not in elements_by_id
                for element_id in known_endpoints
            ):
                return None
            group_element = elements_by_id.get(group.element_id)
            if (
                group_element is None
                or not isinstance(
                    group_element.form_semantics,
                    FormGroupSemanticDescriptor,
                )
                or group_element.form_semantics.record_id != group.id
            ):
                return None
            if any(
                elements_by_id[element_id].page_id != anchor.page_id
                for element_id in known_endpoints
            ):
                return None
            for public_id, element_id in zip(
                group.contributor_public_item_ids,
                group.contributor_element_ids,
                strict=True,
            ):
                contributor = elements_by_id[element_id]
                contributor_legacy = _legacy_item(contributor)
                if (
                    contributor.form_semantics is not None
                    or contributor_legacy is None
                    or contributor_legacy.get("id") != public_id
                ):
                    return None
            for record in all_records[1:]:
                semantic_element = elements_by_id.get(record.element_id)
                if (
                    semantic_element is None
                    or semantic_element.form_semantics is None
                    or semantic_element.form_semantics.record_id != record.id
                    or semantic_element.form_semantics.group_element_id
                    != group.element_id
                ):
                    return None
        markdown, text = _render_public_form_records(
            group=group,
            fields=fields,
            labels=labels,
            controls=controls,
            pairs=pairs,
        )
        if not markdown or not text:
            return None
        return FormGroupRendering(
            group_element_id=group.element_id,
            anchor_element_id=group.anchor_element_id,
            canonical_mode=group.canonical_mode,
            contributor_element_ids=tuple(group.contributor_element_ids),
            relationship_ids=tuple(relationship_ids),
            markdown=markdown,
            text=text,
        )
    except Exception:
        return None


def _safe_plain_text(value: str) -> str:
    return "".join(
        character
        if character >= " " and character not in {"\x7f", "\u2028", "\u2029"}
        else "�"
        for character in value
    )


def _safe_markdown_text(value: str) -> str:
    escaped = html.escape(_safe_plain_text(value), quote=False)
    escaped = (
        escaped.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("|", "\\|")
    )
    # An underscore surrounded by word characters is ordinary source text
    # (for example ``3V3_EN``); boundary underscores can activate emphasis.
    return re.sub(r"(?<!\w)_(?=\S)|(?<=\S)_(?!\w)", r"\\_", escaped)


def _public_form_bbox(record: _PublicRecord) -> tuple[float, float, float, float]:
    return (
        record.bbox.x,
        record.bbox.y,
        record.bbox.width,
        record.bbox.height,
    )


def _complete_public_static_parties_and_insurers(
    *,
    group: PublicFormGroup,
    fields: Sequence[PublicFormField],
    labels: Sequence[PublicFormLabel],
    controls: Sequence[PublicFormControl],
    pairs: Sequence[PublicKeyValuePair],
) -> tuple[str, ...] | None:
    """Revalidate the narrow replacement contract at render time."""

    if (
        group.group_key != "parties-and-insurers"
        or group.status != "resolved"
        or group.interactivity != "static"
        or group.canonical_mode != "replace"
        or group.concern_codes
        or controls
        or pairs
    ):
        return None
    fields_by_key = {field.field_key: field for field in fields}
    if len(fields_by_key) != len(fields) or not set(
        _STATIC_PARTIES_BASE_FIELDS
    ).issubset(fields_by_key):
        return None
    insurer_rows = _static_insurer_rows(set(fields_by_key))
    if insurer_rows is None or any(
        field.value is not None
        or field.value_state != "empty"
        or field.concern_codes
        or "vector" not in field.evidence_methods
        or not _bbox_contains(
            _public_form_bbox(group),
            _public_form_bbox(field),
        )
        for field in fields
    ):
        return None

    labels_by_id = {label.id: label for label in labels}
    if len(labels_by_id) != len(labels) or any(
        label.concern_codes
        or "native" not in label.evidence_methods
        or not _bbox_contains(
            _public_form_bbox(group),
            _public_form_bbox(label),
        )
        for label in labels
    ):
        return None

    used_label_ids: set[str] = set()
    for field_key, expected_text in _STATIC_PARTIES_LABEL_TEXT.items():
        field = fields_by_key[field_key]
        if len(field.label_ids) != 1:
            return None
        label = labels_by_id.get(field.label_ids[0])
        if (
            label is None
            or label.label_role != "field"
            or label.label_of_ids != [field.id]
            or _normalized_form_label(label.text) != expected_text
        ):
            return None
        used_label_ids.add(label.id)

    group_labels = [label for label in labels if label.label_role == "group"]
    shared_labels = [
        label
        for label in labels
        if _normalized_form_label(label.text) == _STATIC_INSURER_SHARED_TEXT
    ]
    if (
        len(group_labels) != 1
        or len(shared_labels) != 1
        or group_labels[0].label_of_ids != [group.id]
        or _normalized_form_label(group_labels[0].text)
        != _STATIC_INSURER_GROUP_TEXT
    ):
        return None
    group_label = group_labels[0]
    shared_label = shared_labels[0]
    used_label_ids.update((group_label.id, shared_label.id))

    producer = fields_by_key["producer"]
    insured = fields_by_key["insured"]
    contact = fields_by_key["contact-name"]
    phone = fields_by_key["phone"]
    fax = fields_by_key["fax"]
    email = fields_by_key["email-address"]
    if not (
        producer.bbox.x < contact.bbox.x
        and insured.bbox.x < contact.bbox.x
        and producer.bbox.y < insured.bbox.y
        and contact.bbox.y <= phone.bbox.y <= email.bbox.y
        and abs(phone.bbox.y - fax.bbox.y) <= 1.0
        and phone.bbox.x < fax.bbox.x
    ):
        return None

    expected_shared_targets: set[str] = set()
    prior_top: float | None = None
    for row in insurer_rows:
        name_field = fields_by_key[f"insurer-{row}-name"]
        naic_field = fields_by_key[f"insurer-{row}-naic"]
        common_label_ids = set(name_field.label_ids) & set(naic_field.label_ids)
        if len(common_label_ids) != 1 or shared_label.id not in naic_field.label_ids:
            return None
        row_label = labels_by_id.get(next(iter(common_label_ids)))
        if (
            row_label is None
            or row_label.label_role != "field"
            or set(row_label.label_of_ids) != {name_field.id, naic_field.id}
            or _normalized_form_label(row_label.text)
            != f"INSURER {row.upper()} :"
            or set(name_field.label_ids) != {row_label.id}
            or set(naic_field.label_ids) != {row_label.id, shared_label.id}
            or abs(name_field.bbox.y - naic_field.bbox.y) > 1.0
            or name_field.bbox.x >= naic_field.bbox.x
            or (prior_top is not None and name_field.bbox.y <= prior_top)
        ):
            return None
        prior_top = name_field.bbox.y
        expected_shared_targets.add(naic_field.id)
        used_label_ids.add(row_label.id)
    if (
        set(shared_label.label_of_ids) != expected_shared_targets
        or used_label_ids != set(labels_by_id)
        or group_label.bbox.y
        >= fields_by_key[f"insurer-{insurer_rows[0]}-name"].bbox.y
        or shared_label.bbox.y
        >= fields_by_key[f"insurer-{insurer_rows[0]}-name"].bbox.y
    ):
        return None
    return insurer_rows


def _render_static_parties_and_insurers(
    *,
    group: PublicFormGroup,
    fields: Sequence[PublicFormField],
    labels: Sequence[PublicFormLabel],
    controls: Sequence[PublicFormControl],
    pairs: Sequence[PublicKeyValuePair],
) -> tuple[str, str] | None:
    insurer_rows = _complete_public_static_parties_and_insurers(
        group=group,
        fields=fields,
        labels=labels,
        controls=controls,
        pairs=pairs,
    )
    if insurer_rows is None:
        return None
    fields_by_key = {field.field_key: field for field in fields}
    labels_by_id = {label.id: label for label in labels}
    base_labels = {
        field_key: labels_by_id[fields_by_key[field_key].label_ids[0]]
        for field_key in _STATIC_PARTIES_BASE_FIELDS
    }
    # One six-column grid follows the source's row-major visual order.  Each
    # label is followed by a blank value cell; the PDF prints ruled fields but
    # contains no entered values.  Keeping the whole region in one table also
    # prevents shared CONTACT/NAIC labels from being detached from their
    # source-visible fields.
    markdown_lines = [
        (
            f"| {_safe_markdown_text(base_labels['producer'].text)} |  | "
            f"{_safe_markdown_text(base_labels['contact-name'].text)} |  |  |  |"
        ),
        "| --- | --- | --- | --- | --- | --- |",
        (
            f"|  |  | {_safe_markdown_text(base_labels['phone'].text)} | "
            f" | {_safe_markdown_text(base_labels['fax'].text)} |  |"
        ),
        (
            f"|  |  | {_safe_markdown_text(base_labels['email-address'].text)} | "
            " |  |  |"
        ),
    ]
    text_lines = [
        (
            f"{_safe_plain_text(base_labels['producer'].text)}\t"
            f"{_safe_plain_text(base_labels['contact-name'].text)}"
        ),
        (
            f"{_safe_plain_text(base_labels['phone'].text)}\t"
            f"{_safe_plain_text(base_labels['fax'].text)}"
        ),
        _safe_plain_text(base_labels["email-address"].text),
    ]

    group_label = next(label for label in labels if label.label_role == "group")
    shared_label = next(
        label
        for label in labels
        if _normalized_form_label(label.text) == _STATIC_INSURER_SHARED_TEXT
    )
    markdown_lines.append(
        (
            f"|  |  | {_safe_markdown_text(group_label.text)} |  | "
            f"{_safe_markdown_text(shared_label.text)} |  |"
        )
    )
    text_lines.append(
        f"{_safe_plain_text(group_label.text)}\t"
        f"{_safe_plain_text(shared_label.text)}"
    )
    for row in insurer_rows:
        name_field = fields_by_key[f"insurer-{row}-name"]
        naic_field = fields_by_key[f"insurer-{row}-naic"]
        row_label_id = next(
            label_id
            for label_id in name_field.label_ids
            if label_id in naic_field.label_ids
        )
        row_label = labels_by_id[row_label_id]
        # The source's producer field occupies y=120–180 through insurer A;
        # INSURED begins at y=180 beside insurer B and continues through F.
        left_label = (
            _safe_markdown_text(base_labels["insured"].text)
            if row == insurer_rows[1]
            else ""
        )
        markdown_lines.append(
            f"| {left_label} |  | {_safe_markdown_text(row_label.text)} |  |  |  |"
        )
        text_prefix = (
            f"{_safe_plain_text(base_labels['insured'].text)}\t"
            if row == insurer_rows[1]
            else ""
        )
        text_lines.append(f"{text_prefix}{_safe_plain_text(row_label.text)}")
    return "\n".join(markdown_lines), "\n".join(text_lines)


def _render_public_form_records(
    *,
    group: PublicFormGroup,
    fields: Sequence[PublicFormField],
    labels: Sequence[PublicFormLabel],
    controls: Sequence[PublicFormControl],
    pairs: Sequence[PublicKeyValuePair],
) -> tuple[str, str]:
    if group.group_key == "parties-and-insurers":
        rendered = _render_static_parties_and_insurers(
            group=group,
            fields=fields,
            labels=labels,
            controls=controls,
            pairs=pairs,
        )
        return rendered if rendered is not None else ("", "")
    labels_by_id = {label.id: label for label in labels}
    markdown_lines: list[str] = []
    text_lines: list[str] = []
    headings = [label for label in labels if label.label_role == "group"]
    if headings:
        markdown_lines.append(f"### {_safe_markdown_text(headings[0].text)}")
        text_lines.append(_safe_plain_text(headings[0].text))
    for pair in pairs:
        markdown_lines.append(
            f"- **{_safe_markdown_text(pair.key)}:** "
            f"{_safe_markdown_text(pair.value)}"
        )
        text_lines.append(
            f"{_safe_plain_text(pair.key)}: {_safe_plain_text(pair.value)}"
        )
    field_state = {
        "empty": ("*(empty source-visible field)*", "[empty source-visible field]"),
        "ambiguous": (
            "*(value ambiguous; no value emitted)*",
            "[value ambiguous; no value emitted]",
        ),
        "not_applicable": (
            "*(not applicable in source)*",
            "[not applicable in source]",
        ),
    }
    for field in fields:
        markdown_names = [
            _safe_markdown_text(labels_by_id[label_id].text)
            for label_id in field.label_ids
            if label_id in labels_by_id
        ]
        plain_names = [
            _safe_plain_text(labels_by_id[label_id].text)
            for label_id in field.label_ids
            if label_id in labels_by_id
        ]
        if len(markdown_names) != len(field.label_ids):
            raise ValueError("form field label is unavailable")
        if field.value_state == "present":
            assert field.value is not None
            markdown_value = _safe_markdown_text(field.value)
            text_value = _safe_plain_text(field.value)
        else:
            markdown_value, text_value = field_state[field.value_state]
        markdown_lines.append(
            f"- **{' · '.join(markdown_names)}:** {markdown_value}"
        )
        text_lines.append(f"{' · '.join(plain_names)}: {text_value}")
    for control in controls:
        label = labels_by_id.get(control.label_id) if control.label_id else None
        source_descriptor = (
            label.text if label is not None else f"Unlabeled {control.control_type}"
        )
        markdown_descriptor = _safe_markdown_text(source_descriptor)
        plain_descriptor = _safe_plain_text(source_descriptor)
        if control.control_type == "checkbox":
            if control.state == "checked":
                markdown_lines.append(f"- [x] {markdown_descriptor}")
            elif control.state == "unchecked":
                markdown_lines.append(f"- [ ] {markdown_descriptor}")
            elif control.state == "ambiguous":
                markdown_lines.append(
                    f"- **{markdown_descriptor}:** state ambiguous"
                )
            else:
                markdown_lines.append(
                    f"- **{markdown_descriptor}:** not applicable"
                )
            plain_state = control.state.replace("_", " ")
        else:
            radio_state = {
                "checked": "selected radio option",
                "unchecked": "unselected radio option",
                "ambiguous": "state ambiguous",
                "not_applicable": "not applicable",
            }[control.state]
            markdown_lines.append(f"- **{markdown_descriptor}:** {radio_state}")
            plain_state = {
                "checked": "selected",
                "unchecked": "unselected",
                "ambiguous": "ambiguous",
                "not_applicable": "not applicable",
            }[control.state]
        text_lines.append(f"{plain_descriptor}: {plain_state}")
    return "\n".join(markdown_lines), "\n".join(text_lines)


__all__ = [
    "FormEvidenceReport",
    "FormGroupRendering",
    "extract_form_evidence",
    "form_processing_summary",
    "project_form_semantics",
    "render_form_group_semantics",
    "strip_form_semantics_public",
]
