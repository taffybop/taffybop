"""Source-grounded running regions and printed page identity.

P03-US08 is intentionally isolated in this module.  The pipeline imports it
only after the default-off feature guard has selected the enabled path.  A
projection is authorized by two deterministic reads of the exact PDF and by
an exact snapshot of the configured post-US07 public/IR/canonical state.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import pickle
import re
import time
import unicodedata
import weakref
import zlib
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Mapping, MutableMapping, Sequence
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from ctypes import c_uint
from dataclasses import dataclass, field as dataclass_field
from itertools import pairwise, repeat
from types import MappingProxyType
from typing import Any, Callable, Self

import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pydantic_core import PydanticSerializationError, to_json
from pdfplumber.utils.text import WordExtractor
from pdfminer import settings as pdfminer_settings
from pdfminer.casting import safe_int
from pdfminer.pdfdevice import PDFTextDevice
from pdfminer.pdfinterp import (
    LITERAL_FORM,
    LITERAL_FONT,
    LITERAL_IMAGE,
    PREDEFINED_COLORSPACE,
    PDFContentParser,
    PDFColorSpace,
    PDFInterpreterError,
    PDFPageInterpreter,
    PDFResourceManager,
)
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfdocument import (
    PDFBaseXRef,
    PDFException,
    PDFNoPageLabels,
    PDFNoValidXRef,
    PDFObjectNotFound,
    PDFXRef,
    PDFXRefStream,
    decipher_all,
)
from pdfminer.pdffont import (
    PDFCIDFont,
    PDFFontError,
    PDFTrueTypeFont,
    PDFType1Font,
    PDFType3Font,
    PDFUnicodeNotDefined,
)
from pdfminer.pdfparser import PDFParser, PDFSyntaxError
from pdfminer.pdfpage import LITERAL_PAGE, LITERAL_PAGES, PDFPage
from pdfminer.pdftypes import (
    PDFObjRef,
    PDFStream,
    dict_value,
    int_value,
    list_value,
    resolve1,
    stream_value,
)
from pdfminer.psparser import (
    END_HEX_STRING,
    END_KEYWORD,
    END_LITERAL,
    END_NUMBER,
    END_STRING,
    EOL,
    KEYWORD_ARRAY_BEGIN,
    KEYWORD_ARRAY_END,
    KEYWORD_DICT_BEGIN,
    KEYWORD_DICT_END,
    KEYWORD_PROC_BEGIN,
    KEYWORD_PROC_END,
    KWD,
    PSEOF,
    PSKeyword,
    PSLiteral,
    PSSyntaxError,
    PSTypeError,
    choplist,
    keyword_name,
    literal_name,
)
from pdfminer.utils import (
    MATRIX_IDENTITY,
    apply_matrix_rect,
    apply_png_predictor,
    mult_matrix,
)

from app.models import (
    ContentItem,
    PageIdentity,
    ProjectedRunningRegionConcern,
    RunningRegionDescriptor,
    RunningRegionsProcessingSummary,
)
from app.services.ir import (
    ConfidenceRecord,
    DocumentIR,
    ElementPresentationDirective,
    ElementRecord,
    EvidenceMethod,
    EvidenceRecord,
    IRBoundingBox,
)


POLICY_ID = "p03-running-regions-page-identity-v1"
REPORT_VERSION = "1.0"
COORDINATE_SYSTEM_ID = "pdf-top-left-pt-v1"
MAX_SOURCE_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGES = 100
MAX_CHARACTERS_PER_PAGE = 500_000
MAX_CHARACTERS_PER_DOCUMENT = 2_000_000
MAX_WORDS_PER_PAGE = 100_000
MAX_WORDS_PER_DOCUMENT = 500_000
MAX_LABEL_CANDIDATES_PER_PAGE = 64
MAX_BOUNDARY_CANDIDATES_PER_PAGE = 512
MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT = 10_000
MAX_RUNNING_REGIONS_PER_PAGE = 64
MAX_RUNNING_REGIONS_PER_DOCUMENT = 2_048
MAX_EXTRACTED_CONTRIBUTION_BYTES = 4 * 1024
MAX_EXTRACTED_CONTRIBUTIONS_PER_PAGE = 8
MAX_EXTRACTED_CONTRIBUTIONS_PER_DOCUMENT = 64
MAX_EXTRACTED_INTERVALS_PER_CONTRIBUTION = 8
MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_PAGE = 16 * 1024
MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_DOCUMENT = 256 * 1024
MAX_REPETITION_GROUPS_PER_DOCUMENT = 2_048
MAX_REPETITION_MEMBERS = 100
MAX_REFERENCES_PER_RECORD = 64
MAX_PUBLIC_PATH_SEGMENTS = 16
MAX_PAGE_IDENTITY_BYTES = 64 * 1024
MAX_RUNNING_DESCRIPTOR_BYTES = 256 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_CONCERNS_PER_PAGE = 64
MAX_CONCERNS_PER_DOCUMENT = 256
MAX_COMPARISONS_PER_PAGE = 4_096
MAX_COMPARISONS_PER_DOCUMENT = 65_536
MAX_LIVE_SOURCE_PROJECTION_AUTHORITIES = 8
SOURCE_EXTRACTION_DEADLINE_SECONDS = 2.0
PROJECTION_PAGE_DEADLINE_SECONDS = 0.250
PROJECTION_DOCUMENT_DEADLINE_SECONDS = 2.0
MAX_SAFE_LABEL_BYTES = 256
MAX_VISIBLE_TEXT_BYTES = 512
MAX_CANDIDATE_TEXT_BYTES = 16 * 1024
PRINTED_LABEL_RENDER_SCALE_PX_PER_PT = 4.0
PRINTED_LABEL_MIN_RGB_CHANNEL_DELTA = 16
MAX_PRINTED_LABEL_RENDER_DIMENSION_PX = 2_048
MAX_PRINTED_LABEL_RENDER_PIXELS = 262_144
MAX_PRINTED_LABEL_NON_STROKING_FILLS = 256
MAX_PRINTED_LABEL_PAGE_DIMENSION_PT = 20_000.0
MAX_PRINTED_LABEL_TEXT_OBJECTS = 256
MAX_PRINTED_LABEL_TEXT_OBJECT_SCAN = 10_000
PRINTED_LABEL_MAX_FORM_DEPTH = 8
PRINTED_LABEL_PAINTED_FILL_RENDER_MODES = (0, 2, 4, 6)
MAX_PRINTED_LABEL_CMYK_CUSTODY_CHANNEL_DELTA = 36

RESOURCE_LIMITS: Mapping[str, int | float] = MappingProxyType(
    {
        "pages_per_document": MAX_PAGES,
        "source_pdf_bytes": MAX_SOURCE_PDF_BYTES,
        "source_characters_per_page": MAX_CHARACTERS_PER_PAGE,
        "source_characters_per_document": MAX_CHARACTERS_PER_DOCUMENT,
        "source_words_per_page": MAX_WORDS_PER_PAGE,
        "source_words_per_document": MAX_WORDS_PER_DOCUMENT,
        "label_utf8_bytes": MAX_SAFE_LABEL_BYTES,
        "visible_text_utf8_bytes": MAX_VISIBLE_TEXT_BYTES,
        "candidate_text_utf8_bytes": MAX_CANDIDATE_TEXT_BYTES,
        "extracted_contribution_utf8_bytes": MAX_EXTRACTED_CONTRIBUTION_BYTES,
        "extracted_contributions_per_page": MAX_EXTRACTED_CONTRIBUTIONS_PER_PAGE,
        "extracted_contributions_per_document": MAX_EXTRACTED_CONTRIBUTIONS_PER_DOCUMENT,
        "extracted_intervals_per_contribution": MAX_EXTRACTED_INTERVALS_PER_CONTRIBUTION,
        "extracted_residual_plan_bytes_per_page": MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_PAGE,
        "extracted_residual_plan_bytes_per_document": MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_DOCUMENT,
        "label_candidates_per_page": MAX_LABEL_CANDIDATES_PER_PAGE,
        "boundary_candidates_per_page": MAX_BOUNDARY_CANDIDATES_PER_PAGE,
        "boundary_candidates_per_document": MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT,
        "running_regions_per_page": MAX_RUNNING_REGIONS_PER_PAGE,
        "running_regions_per_document": MAX_RUNNING_REGIONS_PER_DOCUMENT,
        "repetition_groups_per_document": MAX_REPETITION_GROUPS_PER_DOCUMENT,
        "repetition_members": MAX_REPETITION_MEMBERS,
        "evidence_ids_per_record": MAX_REFERENCES_PER_RECORD,
        "source_object_ids_per_record": MAX_REFERENCES_PER_RECORD,
        "public_path_segments": MAX_PUBLIC_PATH_SEGMENTS,
        "comparisons_per_page": MAX_COMPARISONS_PER_PAGE,
        "comparisons_per_document": MAX_COMPARISONS_PER_DOCUMENT,
        "page_identity_json_bytes": MAX_PAGE_IDENTITY_BYTES,
        "running_descriptor_json_bytes": MAX_RUNNING_DESCRIPTOR_BYTES,
        "report_json_bytes": MAX_REPORT_BYTES,
        "printed_label_render_dimension_pixels": MAX_PRINTED_LABEL_RENDER_DIMENSION_PX,
        "printed_label_render_pixels": MAX_PRINTED_LABEL_RENDER_PIXELS,
        "printed_label_non_stroking_fills": MAX_PRINTED_LABEL_NON_STROKING_FILLS,
        "printed_label_page_dimension_points": int(MAX_PRINTED_LABEL_PAGE_DIMENSION_PT),
        "printed_label_text_objects": MAX_PRINTED_LABEL_TEXT_OBJECTS,
        "printed_label_text_object_scan": MAX_PRINTED_LABEL_TEXT_OBJECT_SCAN,
        "printed_label_form_depth": PRINTED_LABEL_MAX_FORM_DEPTH,
        "live_source_projection_authorities": MAX_LIVE_SOURCE_PROJECTION_AUTHORITIES,
        "concerns_per_page": MAX_CONCERNS_PER_PAGE,
        "concerns_per_document": MAX_CONCERNS_PER_DOCUMENT,
        "source_extraction_seconds": SOURCE_EXTRACTION_DEADLINE_SECONDS,
        "projection_page_seconds": PROJECTION_PAGE_DEADLINE_SECONDS,
        "projection_document_seconds": PROJECTION_DOCUMENT_DEADLINE_SECONDS,
    }
)
MAXIMUM_PAGE_FIXTURE_ID = "synthetic:p03-us08:maximum-page-performance-v1"
_MAXIMUM_PAGE_FIELDS = frozenset(
    {
        "fixture_id",
        "policy_id",
        "physical_page_index",
        "source_character_count",
        "source_word_count",
        "label_candidate_count",
        "boundary_candidate_count",
        "accepted_running_region_count",
        "extracted_contribution_count",
        "extracted_intervals_per_contribution",
        "extracted_residual_plan_bytes",
        "indexed_comparison_count",
        "concern_count",
        "deadline_seconds",
    }
)

_LABEL_PAGE_OF_RE = re.compile(
    r"^Page\s+([1-9][0-9]{0,5})\s+of\s+([1-9][0-9]{0,5})$", re.I
)
_LABEL_PAGE_PIPE_RE = re.compile(r"^Page\s*\|\s*([1-9][0-9]{0,5})$", re.I)
_LABEL_FRACTION_RE = re.compile(r"^([1-9][0-9]{0,5})\s*/\s*([1-9][0-9]{0,5})$")
_LABEL_INTEGER_RE = re.compile(r"^[1-9][0-9]{0,5}$")
_NAVIGATION_TEXT_CUES = frozenset(
    {"TABLE OF CONTENTS", "CONTENTS", "PREVIOUS", "NEXT", "BACK", "HOME"}
)
_NAVIGATION_GLYPH_CUES = frozenset(
    {
        "<",
        ">",
        "<<",
        ">>",
        "←",
        "→",
        "⇐",
        "⇒",
        "‹",
        "›",
        "«",
        "»",
        "❮",
        "❯",
        "⟨",
        "⟩",
    }
)
_NAVIGATION_CUES = _NAVIGATION_TEXT_CUES | _NAVIGATION_GLYPH_CUES
_SAFE_LABEL_PUNCTUATION = frozenset(" ._-:/|()")
_PRIOR_SEMANTIC_KEYS = frozenset(
    {
        "form_group",
        "form_items",
        "outline_group",
        "outline_items",
        "layout_table_structure_projected",
        "table_structure",
    }
)
_DIRECT_SOURCE_EXCLUDED_OWNER_KINDS = frozenset(
    {
        "body",
        "table",
        "table_value",
        "table_cell",
        "chart",
        "diagram",
        "image",
        "visual",
        "caption",
        "form",
        "form_value",
        "form_field",
        "outline",
        "outline_item",
        "note",
        "note_value",
        "source_note",
        "footnote",
        "label",
        "label_value",
        "page_label",
    }
)
_SIDECAR_KEYS = (
    "layout_running_region_projected",
    "running_region_policy",
    "running_region",
)
_EXTRACTED_PLAN_FIELDS = frozenset(
    {
        "physical_page_index",
        "owner_public_item_id",
        "owner_sha256_before",
        "owner_sha256_after",
        "predecessor_canonical",
        "source_text",
        "presentation_text",
        "presentation_fragments",
        "delimiters",
        "predecessor_intervals",
        "residual_insertion_offsets",
        "source_span_groups",
        "whitespace_mappings",
        "residual_canonical",
        "source_text_sha256",
        "presentation_text_sha256",
        "predecessor_sha256",
        "presentation_fragment_sha256",
        "removed_interval_sha256",
        "delimiter_sha256",
        "ordered_plan_sha256",
        "residual_sha256",
    }
)
_SOURCE_REPORT_FIELDS = frozenset(
    {
        "report_version",
        "policy_id",
        "source_sha256",
        "status",
        "pages",
        "counts",
        "concern_codes",
        "extraction_ms",
    }
)
_SOURCE_PAGE_FIELDS = frozenset(
    {
        "page_index",
        "page_width",
        "page_height",
        "unit",
        "coordinate_system_id",
        "source_character_count",
        "source_word_count",
        "embedded_label",
        "label_candidates",
        "boundary_candidates",
        "concern_codes",
    }
)
_LABEL_CANDIDATE_FIELDS = frozenset(
    {
        "id",
        "visible_text",
        "normalized_label",
        "bbox",
        "source_object_ids",
        "source_method",
        "confidence",
        "concern_codes",
    }
)
_BOUNDARY_CANDIDATE_FIELDS = frozenset(
    {
        "id",
        "public_item_id",
        "public_path",
        "element_id",
        "predecessor_type",
        "bbox",
        "bbox_id",
        "evidence_ids",
        "source_object_ids",
        "raw_layout_role",
        "normalized_signature",
        "boundary_band",
        "source_method",
        "disposition",
        "confidence",
        "concern_codes",
    }
)
_SOURCE_COUNT_FIELDS = frozenset(
    {
        "page_count",
        "source_character_count",
        "source_word_count",
        "embedded_label_count",
        "label_candidate_count",
        "boundary_candidate_count",
        "concern_count",
    }
)
_CONCERN_CODES = frozenset(
    {
        "running_region_source_evidence_unavailable",
        "running_region_source_limit",
        "running_region_candidate_limit",
        "running_region_geometry_ambiguous",
        "running_region_repetition_ambiguous",
        "running_region_navigation_ambiguous",
        "running_region_ownership_conflict",
        "page_identity_embedded_label_invalid",
        "page_identity_detected_label_ambiguous",
        "page_identity_source_conflict",
        "page_identity_display_unsafe",
        "running_region_canonical_custody_invalid",
        "running_region_projection_failed_closed",
        "running_region_concerns_truncated",
    }
)
_SUMMARY_ZERO_KEYS = (
    "source_page_count",
    "identity_count",
    "detected_label_count",
    "embedded_label_count",
    "legacy_fallback_count",
    "candidate_count",
    "comparison_count",
    "running_region_count",
    "header_count",
    "footer_count",
    "top_navigation_count",
    "bottom_navigation_count",
    "concern_count",
)
_REPLAY_SUMMARY_IDENTITY_KEYS = (
    "policy_id",
    "status",
    "reason",
    *_SUMMARY_ZERO_KEYS,
)
_REPLAY_IDENTITY_KEYS = frozenset({"summary", "pages", "regions"})
_REPLAY_PAGE_KEYS = frozenset({"page_offset", "page_index", "page_identity"})
_REPLAY_REGION_KEYS = frozenset({"page_offset", "item_offset", "item_id", "descriptor"})


class RunningRegionError(ValueError):
    """A bounded, content-free US08 refusal."""


class _RunningRegionSourceBindingRefusal(RunningRegionError):
    """One proposed owner does not exactly bind its native source scalar."""


class RunningRegionResourceLimitError(RunningRegionError):
    """A bounded resource or deadline refusal inside the US08 stage."""

    def __init__(
        self,
        message: str,
        *,
        resource_name: str | None = None,
    ) -> None:
        self.resource_name = resource_name
        super().__init__(message)


class RunningRegionSourceOutcomeError(RunningRegionError):
    """A content-free source outcome that the pipeline may expose by code."""

    _CODES = frozenset(
        {
            "running_region_source_evidence_unavailable",
            "running_region_source_limit",
        }
    )

    def __init__(self, code: str, message: str | None = None) -> None:
        if code not in self._CODES:
            raise RunningRegionError("running-region source outcome differs")
        self.code = code
        super().__init__(message or "running-region source outcome unavailable")


def validate_running_region_resource_count(name: str, observed: int) -> int:
    """Validate one inclusive integral production resource boundary."""

    limit = RESOURCE_LIMITS.get(name)
    if (
        not isinstance(name, str)
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or isinstance(observed, bool)
        or not isinstance(observed, int)
        or observed < 0
    ):
        raise RunningRegionError("running-region resource boundary differs")
    if observed > limit:
        raise RunningRegionResourceLimitError(
            "running-region resource boundary exceeded",
            resource_name=name,
        )
    return observed


def validate_running_region_deadline(
    name: str,
    started_ns: int,
    *,
    monotonic_ns: Callable[[], int] = time.perf_counter_ns,
) -> float:
    """Read one injected finish tick and enforce an inclusive deadline."""

    limit = {
        "source_extraction": SOURCE_EXTRACTION_DEADLINE_SECONDS,
        "projection_page": PROJECTION_PAGE_DEADLINE_SECONDS,
        "projection_document": PROJECTION_DOCUMENT_DEADLINE_SECONDS,
    }.get(name)
    if (
        limit is None
        or isinstance(started_ns, bool)
        or not isinstance(started_ns, int)
        or started_ns < 0
        or not callable(monotonic_ns)
    ):
        raise RunningRegionError("running-region deadline input differs")
    finished_ns = monotonic_ns()
    if (
        isinstance(finished_ns, bool)
        or not isinstance(finished_ns, int)
        or finished_ns < started_ns
    ):
        raise RunningRegionError("running-region deadline input differs")
    if finished_ns - started_ns > int(round(limit * 1_000_000_000)):
        raise RunningRegionResourceLimitError(
            "running-region deadline exceeded",
            resource_name=f"{name}_seconds",
        )
    return (finished_ns - started_ns) / 1_000_000_000


@dataclass(slots=True)
class _ExtractionBudget:
    """Pre-charge source comparisons and poll the shared extraction clock."""

    started_ns: int
    comparisons: dict[int, int]
    total_comparisons: int = 0
    character_counts: dict[int, int] | None = None
    total_characters: int = 0
    word_counts: dict[int, int] | None = None
    total_words: int = 0
    decoded_content_bytes: int = 0
    retained_text_bytes: int = 0
    retained_text_by_page: dict[int, int] | None = None
    decoded_stream_ids: set[PDFStream] | None = None
    cmap_stream_ids: set[PDFStream] | None = None
    font_mapping_entries: int = 0
    operations_since_deadline: int = 0

    @classmethod
    def start(cls, started_ns: int | None = None) -> "_ExtractionBudget":
        tick = time.perf_counter_ns() if started_ns is None else started_ns
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
            raise RunningRegionError("running-region extraction budget differs")
        return cls(
            started_ns=tick,
            comparisons=defaultdict(int),
            character_counts=defaultdict(int),
            word_counts=defaultdict(int),
            retained_text_by_page=defaultdict(int),
            decoded_stream_ids=set(),
            cmap_stream_ids=set(),
        )

    def check_deadline(self, *, force: bool = False) -> None:
        self.operations_since_deadline += 1
        if force or self.operations_since_deadline >= 256:
            validate_running_region_deadline(
                "source_extraction",
                self.started_ns,
            )
            self.operations_since_deadline = 0

    def charge_comparisons(self, page_index: int, count: int = 1) -> None:
        if (
            isinstance(page_index, bool)
            or not isinstance(page_index, int)
            or not 1 <= page_index <= MAX_PAGES
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
        ):
            raise RunningRegionError("running-region comparison charge differs")
        page_total = self.comparisons[page_index] + count
        document_total = self.total_comparisons + count
        # Validate before the comparison/window is attempted so an adversarial
        # scan cannot perform unreported work beyond either sealed cap.
        validate_running_region_resource_count(
            "comparisons_per_page",
            page_total,
        )
        validate_running_region_resource_count(
            "comparisons_per_document",
            document_total,
        )
        self.comparisons[page_index] = page_total
        self.total_comparisons = document_total
        self.check_deadline()

    def charge_character(self, page_index: int) -> None:
        if self.character_counts is None:
            raise RunningRegionError("running-region character budget differs")
        page_total = self.character_counts[page_index] + 1
        document_total = self.total_characters + 1
        validate_running_region_resource_count(
            "source_characters_per_page",
            page_total,
        )
        validate_running_region_resource_count(
            "source_characters_per_document",
            document_total,
        )
        self.character_counts[page_index] = page_total
        self.total_characters = document_total
        self.check_deadline()

    def charge_word(self, page_index: int) -> None:
        if self.word_counts is None:
            raise RunningRegionError("running-region word budget differs")
        page_total = self.word_counts[page_index] + 1
        document_total = self.total_words + 1
        validate_running_region_resource_count(
            "source_words_per_page",
            page_total,
        )
        validate_running_region_resource_count(
            "source_words_per_document",
            document_total,
        )
        self.word_counts[page_index] = page_total
        self.total_words = document_total
        self.check_deadline()

    def decoded_remaining(self) -> int:
        return MAX_SOURCE_PDF_BYTES - self.decoded_content_bytes

    def retain_decoded_bytes(self, count: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise RunningRegionError("running-region decoded content differs")
        total = self.decoded_content_bytes + count
        if total > MAX_SOURCE_PDF_BYTES:
            raise RunningRegionResourceLimitError(
                "running-region decoded content stream exceeded its cap",
                resource_name="source_pdf_bytes",
            )
        self.decoded_content_bytes = total
        self.check_deadline(force=True)

    def decoded_stream_is_charged(self, stream: PDFStream) -> bool:
        if self.decoded_stream_ids is None:
            raise RunningRegionError("running-region decoded stream budget differs")
        return stream in self.decoded_stream_ids

    def mark_decoded_stream(self, stream: PDFStream) -> None:
        if self.decoded_stream_ids is None:
            raise RunningRegionError("running-region decoded stream budget differs")
        self.decoded_stream_ids.add(stream)

    def charge_font_mapping(self, stream: PDFStream, count: int) -> None:
        if (
            self.cmap_stream_ids is None
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise RunningRegionError("running-region font mapping budget differs")
        if stream in self.cmap_stream_ids:
            return
        validate_running_region_resource_count(
            "source_characters_per_page",
            count,
        )
        validate_running_region_resource_count(
            "source_characters_per_document",
            self.font_mapping_entries + count,
        )
        self.font_mapping_entries += count
        self.cmap_stream_ids.add(stream)
        self.check_deadline(force=True)

    def retain_text_bytes(self, page_index: int, count: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise RunningRegionError("running-region retained text differs")
        total = self.retained_text_bytes + count
        if total > MAX_SOURCE_PDF_BYTES:
            raise RunningRegionResourceLimitError(
                "running-region retained source text exceeded its cap",
                resource_name="source_characters_per_document",
            )
        self.retained_text_bytes = total
        if self.retained_text_by_page is None:
            raise RunningRegionError("running-region retained text budget differs")
        self.retained_text_by_page[page_index] += count
        self.check_deadline()

    def discard_page_source_counts(self, page_index: int) -> None:
        if self.character_counts is None or self.word_counts is None:
            raise RunningRegionError("running-region page source budget differs")
        # Page-local report payload can be discarded, but cumulative work is
        # never refunded: otherwise repeated overflowing pages could evade the
        # document character/word caps.
        self.character_counts.pop(page_index, 0)
        self.word_counts.pop(page_index, 0)
        if self.retained_text_by_page is not None:
            self.retained_text_bytes -= self.retained_text_by_page.pop(
                page_index,
                0,
            )


def account_maximum_page_workload(
    workload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate and detach the closed maximum-page accounting workload."""

    if not isinstance(workload, Mapping) or set(workload) != _MAXIMUM_PAGE_FIELDS:
        raise RunningRegionError("maximum-page running-region workload differs")
    detached = deepcopy(dict(workload))
    if (
        detached.get("fixture_id") != MAXIMUM_PAGE_FIXTURE_ID
        or detached.get("policy_id") != POLICY_ID
    ):
        raise RunningRegionError("maximum-page running-region identity differs")
    bindings = {
        "physical_page_index": "pages_per_document",
        "source_character_count": "source_characters_per_page",
        "source_word_count": "source_words_per_page",
        "label_candidate_count": "label_candidates_per_page",
        "boundary_candidate_count": "boundary_candidates_per_page",
        "accepted_running_region_count": "running_regions_per_page",
        "extracted_contribution_count": "extracted_contributions_per_page",
        "extracted_intervals_per_contribution": "extracted_intervals_per_contribution",
        "extracted_residual_plan_bytes": "extracted_residual_plan_bytes_per_page",
        "indexed_comparison_count": "comparisons_per_page",
        "concern_count": "concerns_per_page",
    }
    for field, resource_name in bindings.items():
        validate_running_region_resource_count(resource_name, detached.get(field))
    deadline = detached.get("deadline_seconds")
    if (
        isinstance(deadline, bool)
        or not isinstance(deadline, (int, float))
        or not math.isfinite(float(deadline))
        or float(deadline) < 0
        or float(deadline) > PROJECTION_PAGE_DEADLINE_SECONDS
    ):
        raise RunningRegionError("maximum-page running-region deadline differs")
    return MappingProxyType(detached)


def project_maximum_page_workload(
    workload: Mapping[str, Any],
    monotonic_ns: Callable[[], int],
) -> bool:
    """Exercise maximum-page accounting plus the real page deadline seam."""

    account_maximum_page_workload(workload)
    started_ns = monotonic_ns()
    validate_running_region_deadline(
        "projection_page", started_ns, monotonic_ns=monotonic_ns
    )
    return True


def _strict_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RunningRegionError("running-region value is not strict JSON") from exc


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_strict_json_bytes(value)).hexdigest()


def _compact_public_item_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    """Return the compact public item shape used by predecessor output."""

    compact = {key: deepcopy(value) for key, value in item.items() if value is not None}
    validated = ContentItem.model_validate(item)
    dumped = validated.model_dump(mode="json")
    typed_compact = {
        key: dumped[key]
        for key in validated.model_fields_set
        if key in dumped and dumped[key] is not None
    }
    if _strict_json_bytes(compact) != _strict_json_bytes(typed_compact):
        raise RunningRegionError("running-region compact public item differs")
    return compact


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha256_json(parts)[:20]}"


def _safe_text(value: Any, *, maximum_bytes: int) -> str:
    if not isinstance(value, str):
        raise RunningRegionError("running-region text differs")
    normalized = unicodedata.normalize("NFC", value)
    if normalized != value or not value:
        raise RunningRegionError("running-region text is unsafe")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise RunningRegionResourceLimitError("running-region text exceeds its cap")
    if any(
        ord(character) < 32
        or 0x7F <= ord(character) <= 0x9F
        or unicodedata.category(character) in {"Cf", "Cs"}
        or ord(character) & 0xFFFF in {0xFFFE, 0xFFFF}
        for character in value
    ):
        raise RunningRegionError("running-region text contains unsafe controls")
    return value


def _normalize_detected_label(value: str) -> str:
    normalized = " ".join(
        _safe_text(value, maximum_bytes=MAX_VISIBLE_TEXT_BYTES).split()
    )
    if match := _LABEL_PAGE_OF_RE.fullmatch(normalized):
        if int(match.group(1)) > int(match.group(2)):
            raise RunningRegionError("printed-label grammar differs")
        return f"{match.group(1)} of {match.group(2)}"
    if match := _LABEL_PAGE_PIPE_RE.fullmatch(normalized):
        return match.group(1)
    if match := _LABEL_FRACTION_RE.fullmatch(normalized):
        if int(match.group(1)) > int(match.group(2)):
            raise RunningRegionError("printed-label grammar differs")
        return f"{match.group(1)}/{match.group(2)}"
    if _LABEL_INTEGER_RE.fullmatch(normalized):
        return normalized
    raise RunningRegionError("printed-label grammar differs")


def _normalize_embedded_label(value: str) -> str:
    normalized = _safe_text(
        value,
        maximum_bytes=MAX_SAFE_LABEL_BYTES,
    ).strip()
    if not normalized or any(
        not (character.isalpha() or character.isdigit())
        and character not in _SAFE_LABEL_PUNCTUATION
        for character in normalized
    ):
        raise RunningRegionError("embedded page-label grammar differs")
    return normalized


def _normalized_signature(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFC", str(value or "")).casefold().split())


def _native_word_whitespace_matches(
    declared_normalized: str,
    native_words: Sequence[tuple[int, Mapping[str, Any]]],
    *,
    fused_word_boundaries: Mapping[int, frozenset[int]] | None = None,
) -> bool:
    """Admit source-word whitespace plus geometry-proven fused-word gaps."""

    declared_tokens = declared_normalized.split()
    native_tokens = [
        _normalized_signature(word.get("text")) for _index, word in native_words
    ]
    if (
        not declared_tokens
        or not native_tokens
        or "".join(declared_tokens) != "".join(native_tokens)
    ):
        return False

    def safe_group(
        word_index: int,
        normalized_native: str,
        tokens: Sequence[str],
    ) -> bool:
        if len(tokens) == 1:
            return tokens[0] == normalized_native
        if "".join(tokens) != normalized_native:
            return False
        boundaries: set[int] = set()
        cursor = 0
        for token in tokens[:-1]:
            cursor += len(token)
            boundaries.add(cursor)
        allowed = (
            fused_word_boundaries.get(word_index, frozenset())
            if fused_word_boundaries is not None
            else frozenset()
        )
        return bool(boundaries) and boundaries <= allowed

    # Partition the declared tokens over the fixed source-word sequence.  A
    # boundary between source words is always admissible; a boundary inside a
    # source word must pass the closed check above.
    positions: set[int] = {0}
    for native_offset, ((word_index, _word), native_token) in enumerate(
        zip(native_words, native_tokens, strict=True)
    ):
        next_positions: set[int] = set()
        for start in positions:
            combined = ""
            for end in range(start + 1, len(declared_tokens) + 1):
                combined += declared_tokens[end - 1]
                if not native_token.startswith(combined):
                    break
                if combined == native_token and safe_group(
                    word_index,
                    native_token,
                    declared_tokens[start:end],
                ):
                    next_positions.add(end)
        positions = next_positions
        if not positions:
            return False
        if native_offset + 1 == len(native_tokens):
            return len(declared_tokens) in positions
    return False


def _structured_native_scalar_matches(
    declared: Any,
    native_words: Sequence[tuple[int, Mapping[str, Any]]],
    *,
    fused_word_boundaries: Mapping[int, frozenset[int]] | None = None,
) -> bool:
    declared_normalized = _normalized_signature(declared)
    native = _candidate_signature(native_words)
    if declared_normalized == native:
        return True
    if all(word.get("upright") is True for _index, word in native_words):
        # The accepted predecessor has three closed native-layout transforms:
        # PDF word-boundary whitespace, en-dash -> ASCII hyphen, and PDF bullet
        # -> middle dot.  They are independent classes and may not be combined.
        if _native_word_whitespace_matches(
            declared_normalized,
            native_words,
            fused_word_boundaries=fused_word_boundaries,
        ):
            return True
        dash_normalized = native.replace("\u2013", "-")
        if dash_normalized != native and declared_normalized == dash_normalized:
            return True
        bullet_normalized = native.replace("\u2022", "\u00b7")
        return bullet_normalized != native and declared_normalized == bullet_normalized
    # PDFMiner exposes one reviewed 180-degree/vertical footer run in reverse
    # glyph order.  Reversal is admitted only when every supplying word carries
    # the exact non-upright top-to-bottom source geometry.
    return (
        bool(native_words)
        and all(
            word.get("upright") is False and word.get("direction") == "ttb"
            for _index, word in native_words
        )
        and declared_normalized == native[::-1]
    )


def _page_placeholder_signature(signature: str, visible_text: str) -> str | None:
    """Replace one grammar-bound printed folio in a normalized owner scalar."""

    visible = _normalized_signature(visible_text)
    patterns: list[re.Pattern[str]] = []
    if _LABEL_PAGE_OF_RE.fullmatch(visible_text):
        match = _LABEL_PAGE_OF_RE.fullmatch(visible_text)
        assert match is not None
        patterns.append(
            re.compile(
                rf"page\s+{re.escape(match.group(1))}\s+of\s+{re.escape(match.group(2))}"
            )
        )
    elif _LABEL_PAGE_PIPE_RE.fullmatch(visible_text):
        match = _LABEL_PAGE_PIPE_RE.fullmatch(visible_text)
        assert match is not None
        patterns.append(re.compile(rf"page\s*\|\s*{re.escape(match.group(1))}"))
    elif _LABEL_FRACTION_RE.fullmatch(visible):
        match = _LABEL_FRACTION_RE.fullmatch(visible)
        assert match is not None
        patterns.append(
            re.compile(
                rf"{re.escape(match.group(1))}\s*/\s*{re.escape(match.group(2))}"
            )
        )
    elif _LABEL_INTEGER_RE.fullmatch(visible):
        patterns.append(re.compile(rf"(?<![0-9]){re.escape(visible)}(?![0-9])"))
    if not patterns:
        return None
    matches = [match for pattern in patterns for match in pattern.finditer(signature)]
    if len(matches) != 1:
        return None
    match = matches[0]
    return f"{signature[: match.start()]}{{page}}{signature[match.end() :]}"


def _bbox(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        result = {
            "x": round(float(value["x"]), 3),
            "y": round(float(value["y"]), 3),
            "width": round(float(value.get("width", value.get("w"))), 3),
            "height": round(float(value.get("height", value.get("h"))), 3),
            "unit": str(value.get("unit") or "pt"),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise RunningRegionError("running-region bbox differs") from exc
    if (
        result["unit"] != "pt"
        or not all(math.isfinite(result[key]) for key in ("x", "y", "width", "height"))
        or result["width"] <= 0
        or result["height"] <= 0
    ):
        raise RunningRegionError("running-region bbox is invalid")
    return result


def _source_bbox(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "x": float(value["x0"]),
        "y": float(value["top"]),
        "width": float(value["x1"]) - float(value["x0"]),
        "height": float(value["bottom"]) - float(value["top"]),
        "unit": "pt",
    }


def _bbox_union(values: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not values:
        raise RunningRegionError("running-region bbox union is empty")
    left = min(float(value.get("x", value.get("x0"))) for value in values)
    top = min(float(value.get("y", value.get("top"))) for value in values)
    right = max(
        float(value.get("x", value.get("x0")))
        + float(
            value.get("width", float(value.get("x1", 0)) - float(value.get("x0", 0)))
        )
        for value in values
    )
    bottom = max(
        float(value.get("y", value.get("top")))
        + float(
            value.get(
                "height", float(value.get("bottom", 0)) - float(value.get("top", 0))
            )
        )
        for value in values
    )
    return _bbox(
        {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
            "unit": "pt",
        }
    )


def _center_inside(
    word: Mapping[str, Any], box: Mapping[str, Any], *, tolerance: float = 0.001
) -> bool:
    center_x = (float(word["x0"]) + float(word["x1"])) / 2
    center_y = (float(word["top"]) + float(word["bottom"])) / 2
    return (
        float(box["x"]) - tolerance
        <= center_x
        <= float(box["x"]) + float(box["width"]) + tolerance
        and float(box["y"]) - tolerance
        <= center_y
        <= float(box["y"]) + float(box["height"]) + tolerance
    )


def _has_prior_semantic_owner(item: Mapping[str, Any]) -> bool:
    return any(key in item for key in _PRIOR_SEMANTIC_KEYS)


def _ir_payload(ir: DocumentIR | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(ir, DocumentIR):
        return ir.model_dump(mode="json", exclude_none=True)
    if isinstance(ir, Mapping):
        return deepcopy(dict(ir))
    raise RunningRegionError("running-region IR differs")


def _configured_bundle(
    public_document: Mapping[str, Any],
    ir_document: DocumentIR | Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    ir_payload = (
        ir_document.model_dump(mode="json", exclude_none=True)
        if isinstance(ir_document, DocumentIR)
        else ir_document
    )
    if not isinstance(public_document, Mapping) or not isinstance(ir_payload, Mapping):
        raise RunningRegionError("running-region configured predecessor differs")
    return {
        "public": public_document,
        "ir": ir_payload,
    }


def _public_owner_path(
    document: Mapping[str, Any], page_offset: int, item_offset: int
) -> tuple[Any, ...]:
    pages = document.get("pages")
    if not isinstance(pages, list) or page_offset >= len(pages):
        raise RunningRegionError("running-region public page differs")
    items = pages[page_offset].get("items")
    if not isinstance(items, list) or item_offset >= len(items):
        raise RunningRegionError("running-region public item differs")
    return ("pages", page_offset, "items", item_offset)


def _resolve_path(document: Any, path: Sequence[Any]) -> Any:
    if isinstance(path, (str, bytes, bytearray)) or not isinstance(path, Sequence):
        raise RunningRegionError("running-region public path differs")
    validate_running_region_resource_count("public_path_segments", len(path))
    current = document
    for component in path:
        if isinstance(component, bool) or not isinstance(component, (str, int)):
            raise RunningRegionError("running-region public path differs")
        try:
            current = current[component]
        except (KeyError, IndexError, TypeError) as exc:
            raise RunningRegionError(
                "running-region public path is unresolved"
            ) from exc
    return current


def _bounded_references(
    values: Any,
    resource_name: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise RunningRegionError("running-region source references differ")
    validate_running_region_resource_count(resource_name, len(values))
    detached = list(values)
    if (not allow_empty and not detached) or any(
        not isinstance(value, str) or not value for value in detached
    ):
        raise RunningRegionError("running-region source references differ")
    if len(detached) != len(set(detached)):
        raise RunningRegionError("running-region source references differ")
    return detached


def _owner_indexes(
    public_document: Mapping[str, Any], ir_payload: Mapping[str, Any]
) -> tuple[
    dict[tuple[int, int], Mapping[str, Any]],
    dict[tuple[int, str], Mapping[str, Any]],
    dict[str, str],
]:
    elements = ir_payload.get("elements")
    pages = ir_payload.get("pages")
    public_pages = public_document.get("pages")
    canonical = public_document.get("canonical_presentation")
    if (
        not isinstance(elements, list)
        or not isinstance(pages, list)
        or not isinstance(public_pages, list)
        or not isinstance(canonical, Mapping)
    ):
        raise RunningRegionError("running-region predecessor custody is incomplete")
    elements_by_id = {
        value.get("id"): value
        for value in elements
        if isinstance(value, Mapping) and isinstance(value.get("id"), str)
    }
    if len(elements_by_id) != len(elements):
        raise RunningRegionError("running-region IR element identity differs")
    ir_pages_by_index = {
        value.get("page_index"): value
        for value in pages
        if isinstance(value, Mapping)
        and isinstance(value.get("page_index"), int)
        and not isinstance(value.get("page_index"), bool)
    }
    if len(ir_pages_by_index) != len(pages) or len(public_pages) != len(pages):
        raise RunningRegionError("running-region predecessor page custody differs")
    by_page_and_position: dict[tuple[int, int], Mapping[str, Any]] = {}
    by_public_id: dict[tuple[int, str], Mapping[str, Any]] = {}
    for page_offset, public_page in enumerate(public_pages):
        if not isinstance(public_page, Mapping):
            raise RunningRegionError("running-region public page differs")
        page_index = public_page.get("page_index")
        if (
            isinstance(page_index, bool)
            or not isinstance(page_index, int)
            or page_index != page_offset + 1
        ):
            raise RunningRegionError("running-region public page order differs")
        ir_page = ir_pages_by_index.get(page_index)
        items = public_page.get("items")
        presentation_ids = (
            ir_page.get("presentation_element_ids")
            if isinstance(ir_page, Mapping)
            else None
        )
        if (
            not isinstance(items, list)
            or not isinstance(presentation_ids, list)
            or len(items) != len(presentation_ids)
        ):
            raise RunningRegionError(
                "running-region presentation owner coverage differs"
            )
        for item_offset, (item, element_id) in enumerate(
            zip(items, presentation_ids, strict=True)
        ):
            element = elements_by_id.get(element_id)
            properties = (
                element.get("properties") if isinstance(element, Mapping) else None
            )
            legacy = (
                properties.get("legacy_item")
                if isinstance(properties, Mapping)
                else None
            )
            if (
                not isinstance(item, Mapping)
                or not isinstance(element, Mapping)
                or element.get("page_id") != ir_page.get("id")
                or element.get("presentation_role") != "primary"
                or not isinstance(legacy, Mapping)
                or dict(legacy) != dict(item)
            ):
                raise RunningRegionError(
                    "running-region presentation owner binding differs"
                )
            public_item_id = item.get("id")
            if not isinstance(public_item_id, str) or not public_item_id:
                raise RunningRegionError("running-region public owner ID differs")
            public_key = (page_index, public_item_id)
            if public_key in by_public_id:
                raise RunningRegionError("running-region public owner ID repeats")
            by_page_and_position[(page_index, item_offset)] = element
            by_public_id[public_key] = element
    canonical_by_element: dict[str, str] = {}
    for page in canonical.get("pages") or []:
        for block in page.get("blocks") or []:
            if not isinstance(block, Mapping) or not isinstance(
                block.get("primary_element_id"), str
            ):
                continue
            element_id = block["primary_element_id"]
            block_id = block.get("id")
            if (
                not isinstance(block_id, str)
                or not block_id
                or element_id in canonical_by_element
            ):
                raise RunningRegionError(
                    "running-region canonical owner identity differs"
                )
            canonical_by_element[element_id] = block_id
    return by_page_and_position, by_public_id, canonical_by_element


def _word_ids(source_sha256: str, page_index: int, indexes: Sequence[int]) -> list[str]:
    validate_running_region_resource_count(
        "source_object_ids_per_record",
        len(indexes),
    )
    return [
        f"pdfplumber:{source_sha256}:page:{page_index}:word:{index}"
        for index in indexes
    ]


def _character_ids(
    source_sha256: str, page_index: int, indexes: Sequence[int]
) -> list[str]:
    validate_running_region_resource_count(
        "source_object_ids_per_record",
        len(indexes),
    )
    return [
        f"pdfplumber:{source_sha256}:page:{page_index}:character:{index}"
        for index in indexes
    ]


def _confidence() -> dict[str, Any]:
    return {"scope": "deterministic_rule", "score": 1.0, "unavailable_reason": None}


def _semantic_report_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = deepcopy(dict(report))
    payload.pop("extraction_ms", None)
    return payload


class _ValidatedSourceProjectionAuthority:
    """Opaque identity-bound authority; it never retains source PDF bytes."""

    __slots__ = ("__weakref__", "_registry_token")

    def __new__(cls) -> Self:
        raise RunningRegionError("source projection authority must be factory-issued")

    def __setattr__(self, name: str, value: Any) -> None:
        del name, value
        raise RunningRegionError("source projection authority is immutable")

    def __copy__(self) -> Self:
        raise RunningRegionError("source projection authority cannot be copied")

    def __deepcopy__(self, memo: Any) -> Self:
        del memo
        raise RunningRegionError("source projection authority cannot be copied")

    def __reduce__(self) -> Any:
        raise RunningRegionError("source projection authority cannot be serialized")

    def __reduce_ex__(self, protocol: int) -> Any:
        del protocol
        raise RunningRegionError("source projection authority cannot be serialized")

    def __repr__(self) -> str:
        return "<validated running-region source authority>"


@dataclass(frozen=True, slots=True)
class _IssuedAuthorityRecord:
    reference: weakref.ReferenceType[_ValidatedSourceProjectionAuthority]
    registry_token: object
    source_sha256: str
    predecessor_sha256: str
    source_report_json: bytes = dataclass_field(repr=False)
    extracted_plans_json: bytes = dataclass_field(repr=False)
    comparison_ledger_json: bytes = dataclass_field(repr=False)
    method_proofs_json: bytes = dataclass_field(repr=False)
    owner_bindings_json: bytes = dataclass_field(repr=False)
    predecessor_template_pickle: bytes = dataclass_field(repr=False)
    predecessor_public_typed_json: bytes = dataclass_field(repr=False)
    predecessor_ir_typed_json: bytes = dataclass_field(repr=False)


_ISSUED_AUTHORITIES: dict[int, _IssuedAuthorityRecord] = {}


def _require_authority(value: Any) -> _IssuedAuthorityRecord:
    if not isinstance(value, _ValidatedSourceProjectionAuthority):
        raise RunningRegionError("source projection authority differs")
    issued = _ISSUED_AUTHORITIES.get(id(value))
    if (
        issued is None
        or issued.reference() is not value
        or getattr(value, "_registry_token", None) is not issued.registry_token
    ):
        raise RunningRegionError("source projection authority was not factory-issued")
    return issued


def _issue_authority(**values: Any) -> _ValidatedSourceProjectionAuthority:
    validate_running_region_resource_count(
        "live_source_projection_authorities", len(_ISSUED_AUTHORITIES) + 1
    )
    authority = object.__new__(_ValidatedSourceProjectionAuthority)
    registry_token = object()
    object.__setattr__(authority, "_registry_token", registry_token)
    identity = id(authority)

    def revoke(reference: weakref.ReferenceType[Any]) -> None:
        current = _ISSUED_AUTHORITIES.get(identity)
        if current is not None and current.reference is reference:
            _ISSUED_AUTHORITIES.pop(identity, None)

    reference = weakref.ref(authority, revoke)
    _ISSUED_AUTHORITIES[identity] = _IssuedAuthorityRecord(
        reference=reference,
        registry_token=registry_token,
        **values,
    )
    return authority


@dataclass(frozen=True, slots=True)
class _SourcePage:
    page_index: int
    width: float
    height: float
    chars: tuple[Mapping[str, Any], ...]
    words: tuple[Mapping[str, Any], ...]
    embedded_label: str | None
    concern_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PageWordIndex:
    by_center_y: tuple[tuple[float, int, Mapping[str, Any]], ...]
    center_ys: tuple[float, ...]

    @classmethod
    def build(cls, page: _SourcePage) -> "_PageWordIndex":
        records = tuple(
            sorted(
                (
                    (
                        (float(word["top"]) + float(word["bottom"])) / 2,
                        index,
                        word,
                    )
                    for index, word in enumerate(page.words)
                ),
                key=lambda value: (value[0], value[1]),
            )
        )
        return cls(records, tuple(value[0] for value in records))

    def query(
        self,
        page: _SourcePage,
        box: Mapping[str, Any],
        *,
        budget: _ExtractionBudget | None = None,
        tolerance: float = 0.001,
    ) -> list[tuple[int, Mapping[str, Any]]]:
        top = float(box["y"]) - tolerance
        bottom = float(box["y"]) + float(box["height"]) + tolerance
        start = bisect_left(self.center_ys, top)
        end = bisect_right(self.center_ys, bottom)
        selected: list[tuple[int, Mapping[str, Any]]] = []
        for _center_y, index, word in self.by_center_y[start:end]:
            if budget is not None:
                budget.charge_comparisons(page.page_index)
            if _center_inside(word, box, tolerance=tolerance):
                selected.append((index, word))
        selected.sort(key=lambda value: value[0])
        return selected


@dataclass(frozen=True, slots=True)
class _PageCharacterIndex:
    by_center_y: tuple[tuple[float, int, Mapping[str, Any]], ...]
    center_ys: tuple[float, ...]
    by_center_x: tuple[tuple[float, int, Mapping[str, Any]], ...]
    center_xs: tuple[float, ...]

    @classmethod
    def build(cls, page: _SourcePage) -> "_PageCharacterIndex":
        by_center_y = tuple(
            sorted(
                (
                    (
                        (float(character["top"]) + float(character["bottom"])) / 2.0,
                        index,
                        character,
                    )
                    for index, character in enumerate(page.chars)
                ),
                key=lambda value: (value[0], value[1]),
            )
        )
        by_center_x = tuple(
            sorted(
                (
                    (
                        (float(character["x0"]) + float(character["x1"])) / 2.0,
                        index,
                        character,
                    )
                    for index, character in enumerate(page.chars)
                ),
                key=lambda value: (value[0], value[1]),
            )
        )
        return cls(
            by_center_y=by_center_y,
            center_ys=tuple(value[0] for value in by_center_y),
            by_center_x=by_center_x,
            center_xs=tuple(value[0] for value in by_center_x),
        )

    def query(
        self,
        page: _SourcePage,
        box: Mapping[str, Any],
        *,
        budget: _ExtractionBudget | None,
        tolerance: float = 0.001,
    ) -> list[tuple[int, Mapping[str, Any]]]:
        top = float(box["y"]) - tolerance
        bottom = float(box["y"]) + float(box["height"]) + tolerance
        left = float(box["x"]) - tolerance
        right = float(box["x"]) + float(box["width"]) + tolerance
        y_start = bisect_left(self.center_ys, top)
        y_end = bisect_right(self.center_ys, bottom)
        x_start = bisect_left(self.center_xs, left)
        x_end = bisect_right(self.center_xs, right)
        records = (
            self.by_center_y[y_start:y_end]
            if y_end - y_start <= x_end - x_start
            else self.by_center_x[x_start:x_end]
        )
        selected: list[tuple[int, Mapping[str, Any]]] = []
        for _center, index, character in records:
            # Character materialization already charged the page/document
            # source-character caps.  This index and per-word cache bound each
            # geometry lookup without changing the sealed candidate-comparison
            # ledger; deadline polling still covers every inspected record.
            if budget is not None:
                budget.check_deadline()
            if _center_inside(character, box, tolerance=tolerance):
                selected.append((index, character))
        selected.sort(key=lambda value: value[0])
        return selected


class _BoundedWordExtractor(WordExtractor):
    def __init__(
        self,
        *,
        budget: _ExtractionBudget,
        page_index: int,
    ) -> None:
        super().__init__()
        self._running_budget = budget
        self._running_page_index = page_index

    def merge_chars(
        self,
        ordered_chars: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._running_budget.charge_word(self._running_page_index)
        word_bytes = sum(
            len(str(value.get("text") or "").encode("utf-8")) for value in ordered_chars
        )
        validate_running_region_resource_count(
            "candidate_text_utf8_bytes",
            word_bytes,
        )
        self._running_budget.retain_text_bytes(
            self._running_page_index,
            word_bytes,
        )
        return super().merge_chars(ordered_chars)


class _MinimalCharacterDevice(PDFTextDevice):
    """Emit only the character fields consumed by the closed US08 extractor.

    ``pdfplumber.Page.chars`` normally builds an LT layout tree and then walks
    it a second time to materialize dictionaries for every PDF object.  US08
    consumes neither that tree nor vector/image objects, so retaining them is
    avoidable work on dense reports.  The coordinate and glyph calculations
    below deliberately mirror ``pdfminer.layout.LTChar`` and
    ``pdfplumber.page.Page.process_object``.
    """

    def __init__(
        self,
        resource_manager: Any,
        *,
        unicode_norm: str | None,
        budget: _ExtractionBudget | None = None,
        page_index: int | None = None,
    ) -> None:
        super().__init__(resource_manager)
        self.unicode_norm = unicode_norm
        self.budget = budget
        self.page_index = page_index
        self.glyphs: list[
            tuple[
                str,
                float,
                float,
                float,
                float,
                bool,
                float,
                Any,
            ]
        ] = []

    def render_char(
        self,
        matrix: Any,
        font: Any,
        fontsize: float,
        scaling: float,
        rise: float,
        cid: int,
        ncs: Any,
        graphicstate: Any,
    ) -> float:
        del ncs
        if self.budget is not None:
            if self.page_index is None:
                raise RunningRegionError("running-region glyph page differs")
            self.budget.charge_character(self.page_index)
        else:
            validate_running_region_resource_count(
                "source_characters_per_page",
                len(self.glyphs) + 1,
            )
        try:
            text = font.to_unichr(cid)
            if not isinstance(text, str):
                raise RunningRegionError("running-region source glyph differs")
        except PDFUnicodeNotDefined:
            text = f"(cid:{cid})"
        if self.unicode_norm is not None:
            text = unicodedata.normalize(self.unicode_norm, text)
        text_bytes = len(text.encode("utf-8"))
        validate_running_region_resource_count(
            "candidate_text_utf8_bytes",
            text_bytes,
        )
        if self.budget is not None and self.page_index is not None:
            self.budget.retain_text_bytes(self.page_index, text_bytes)

        text_width = font.char_width(cid)
        advance = text_width * fontsize * scaling
        vertical = font.is_vertical()
        if vertical:
            text_displacement = font.char_disp(cid)
            if not isinstance(text_displacement, tuple):
                raise RunningRegionError(
                    "running-region vertical glyph displacement differs"
                )
            vx, vy = text_displacement
            vx = fontsize * 0.5 if vx is None else vx * fontsize * 0.001
            vy = (1000 - vy) * fontsize * 0.001
            glyph_box = (
                -vx,
                vy + rise + advance,
                -vx + fontsize,
                vy + rise,
            )
        else:
            descent = font.get_descent() * fontsize
            glyph_box = (
                0,
                descent + rise,
                advance,
                descent + rise + fontsize,
            )

        a, b, c, d, _e, _f = matrix
        upright = a * d * scaling > 0 and b * c <= 0
        x0, y0, x1, y1 = apply_matrix_rect(matrix, glyph_box)
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        size = x1 - x0 if vertical else y1 - y0
        non_stroking_color = graphicstate.ncolor
        if not isinstance(non_stroking_color, tuple):
            non_stroking_color = (non_stroking_color,)
        self.glyphs.append(
            (
                text,
                x0,
                y0,
                x1,
                y1,
                upright,
                size,
                non_stroking_color,
            )
        )
        return advance


def _bounded_pdf_stream_data(
    stream: PDFStream,
    budget: _ExtractionBudget,
) -> bytes:
    """Decode one parser-created stream under the shared extraction cap.

    This helper is used by structural xref/object streams, font resources,
    ToUnicode maps, page content, and Form XObjects.  It deliberately accepts
    only raw bytes or one ordinary Flate stream without encryption/predictors;
    every other eager PDFMiner decoder is outside the bounded v1 contract.
    """

    budget.check_deadline(force=True)
    if budget.decoded_stream_is_charged(stream):
        if not isinstance(stream.data, bytes) or stream.rawdata is not None:
            raise RunningRegionError("running-region decoded stream cache differs")
        return stream.data
    if stream.data is not None:
        if not isinstance(stream.data, bytes) or stream.rawdata is not None:
            raise RunningRegionError("running-region decoded stream state differs")
        data = stream.data
    else:
        raw = stream.rawdata
        if not isinstance(raw, bytes):
            raise RunningRegionError("running-region content stream differs")
        filters = stream.get_filters()
        if stream.decipher is not None:
            raise RunningRegionResourceLimitError(
                "running-region encrypted stream is not safely bounded",
                resource_name="source_pdf_bytes",
            )
        remaining = budget.decoded_remaining()
        if remaining < 0:
            raise RunningRegionResourceLimitError(
                "running-region decoded content stream exceeded its cap",
                resource_name="source_pdf_bytes",
            )
        if not filters:
            if len(raw) > remaining:
                raise RunningRegionResourceLimitError(
                    "running-region decoded content stream exceeded its cap",
                    resource_name="source_pdf_bytes",
                )
            data = raw
        else:
            params = filters[0][1] if len(filters) == 1 else None
            predictor = params.get("Predictor", 1) if isinstance(params, Mapping) else 1
            simple_flate = (
                len(filters) == 1
                and literal_name(filters[0][0]) in {"Fl", "FlateDecode"}
                and not isinstance(predictor, bool)
                and isinstance(predictor, int)
                and (
                    predictor == 1
                    or (
                        predictor in range(10, 16)
                        and literal_name(stream.get("Type")) in {"XRef", "ObjStm"}
                    )
                )
            )
            if not simple_flate:
                raise RunningRegionResourceLimitError(
                    "running-region content stream filter is not safely bounded",
                    resource_name="source_pdf_bytes",
                )
            try:
                decoder = zlib.decompressobj()
                data = decoder.decompress(raw, remaining + 1)
                if len(data) > remaining or decoder.unconsumed_tail:
                    raise RunningRegionResourceLimitError(
                        "running-region decoded content stream exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                data += decoder.flush(remaining - len(data) + 1)
                if len(data) > remaining or not decoder.eof or decoder.unused_data:
                    raise RunningRegionResourceLimitError(
                        "running-region decoded content stream exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                if predictor != 1:
                    if not isinstance(params, Mapping):
                        raise RunningRegionError(
                            "running-region structural predictor differs"
                        )
                    colors = params.get("Colors", 1)
                    columns = params.get("Columns", 1)
                    bits = params.get("BitsPerComponent", 8)
                    if (
                        any(
                            isinstance(value, bool) for value in (colors, columns, bits)
                        )
                        or not all(
                            isinstance(value, int) for value in (colors, columns, bits)
                        )
                        or not 1 <= colors <= 8
                        or not 1 <= columns <= MAX_CANDIDATE_TEXT_BYTES
                        or bits != 8
                    ):
                        raise RunningRegionResourceLimitError(
                            "running-region structural predictor is not safely bounded",
                            resource_name="source_pdf_bytes",
                        )
                    try:
                        data = apply_png_predictor(
                            predictor,
                            colors,
                            columns,
                            bits,
                            data,
                        )
                    except Exception as exc:
                        raise RunningRegionError(
                            "running-region structural predictor is unavailable"
                        ) from exc
            except zlib.error as exc:
                raise RunningRegionError(
                    "running-region content stream is unavailable"
                ) from exc
        stream.data = data
        stream.rawdata = None
    budget.retain_decoded_bytes(len(data))
    budget.mark_decoded_stream(stream)
    return data


class _BoundedPDFStream(PDFStream):
    """A PDFMiner stream whose every eager decode uses the extraction budget."""

    def __init__(
        self,
        attrs: dict[str, Any],
        rawdata: bytes,
        decipher: Any,
        *,
        budget: _ExtractionBudget,
    ) -> None:
        super().__init__(attrs, rawdata, decipher)
        self._running_budget = budget

    def decode(self) -> None:
        _bounded_pdf_stream_data(self, self._running_budget)

    def get_data(self) -> bytes:
        return _bounded_pdf_stream_data(self, self._running_budget)


class _BoundedPDFParser(PDFParser):
    """Create bounded streams before PDFDocument can decode xref/ObjStm data."""

    def __init__(self, fp: Any, *, budget: _ExtractionBudget) -> None:
        self._running_budget = budget
        super().__init__(fp)

    def nextline(self) -> tuple[int, bytes]:
        """Read one structural line without PDFMiner's value-bearing log."""

        line = bytearray()
        line_position = self.bufpos + self.charpos
        trailing_carriage_return = False
        while True:
            self._running_budget.check_deadline(force=True)
            self.fillbuf()
            if trailing_carriage_return:
                current = self.buf[self.charpos : self.charpos + 1]
                if current == b"\n":
                    line.extend(current)
                    self.charpos += 1
                break
            match = EOL.search(self.buf, self.charpos)
            if match is None:
                line.extend(self.buf[self.charpos :])
                self.charpos = len(self.buf)
                continue
            line.extend(self.buf[self.charpos : match.end(0)])
            self.charpos = match.end(0)
            if line[-1:] == b"\r":
                trailing_carriage_return = True
            else:
                break
        return line_position, bytes(line)

    def nexttoken(self) -> tuple[int, Any]:
        """Read one structural token without logging attacker-controlled data."""

        if self.eof:
            raise PSEOF("Unexpected EOF")
        while not self._tokens:
            self._running_budget.check_deadline(force=True)
            try:
                changed_stream = self.fillbuf()
                if changed_stream and self._curtoken:
                    self._parse1(b"\n", 0)
                else:
                    self.charpos = self._parse1(self.buf, self.charpos)
            except PSEOF:
                self.charpos = self._parse1(b"\n", 0)
                self.eof = True
                if not self._tokens:
                    raise
        return self._tokens.pop(0)

    def push(self, *objects: tuple[int, Any]) -> None:
        validate_running_region_resource_count(
            "source_characters_per_page",
            len(self.curstack) + len(objects),
        )
        self._running_budget.check_deadline()
        self.curstack.extend(objects)

    def add_results(self, *objects: tuple[int, Any]) -> None:
        validate_running_region_resource_count(
            "source_characters_per_page",
            len(self.results) + len(objects),
        )
        self.results.extend(objects)

    def start_type(self, position: int, value_type: str) -> None:
        if len(self.context) >= MAX_PUBLIC_PATH_SEGMENTS:
            raise RunningRegionResourceLimitError(
                "running-region structural nesting exceeded its cap",
                resource_name="public_path_segments",
            )
        self._running_budget.check_deadline()
        self.context.append((position, self.curtype, self.curstack))
        self.curtype, self.curstack = value_type, []

    def end_type(self, value_type: str) -> tuple[int, list[Any]]:
        if self.curtype != value_type:
            raise PSTypeError("running-region structural type differs")
        objects = [value for _position, value in self.curstack]
        position, self.curtype, self.curstack = self.context.pop()
        return position, objects

    def nextobject(self) -> tuple[int, Any]:
        """Assemble an object without PDFMiner's object/stack debug calls."""

        while not self.results:
            position, token = self.nexttoken()
            if isinstance(token, (int, float, bool, str, bytes, PSLiteral)):
                self.push((position, token))
            elif token == KEYWORD_ARRAY_BEGIN:
                self.start_type(position, "a")
            elif token == KEYWORD_ARRAY_END:
                try:
                    self.push(self.end_type("a"))
                except PSTypeError:
                    if pdfminer_settings.STRICT:
                        raise
            elif token == KEYWORD_DICT_BEGIN:
                self.start_type(position, "d")
            elif token == KEYWORD_DICT_END:
                try:
                    position, objects = self.end_type("d")
                    if len(objects) % 2:
                        raise PSSyntaxError(
                            "running-region structural dictionary differs"
                        )
                    value = {
                        literal_name(key): item
                        for key, item in choplist(2, objects)
                        if item is not None
                    }
                    self.push((position, value))
                except PSTypeError:
                    if pdfminer_settings.STRICT:
                        raise
            elif token == KEYWORD_PROC_BEGIN:
                self.start_type(position, "p")
            elif token == KEYWORD_PROC_END:
                try:
                    self.push(self.end_type("p"))
                except PSTypeError:
                    if pdfminer_settings.STRICT:
                        raise
            elif isinstance(token, PSKeyword):
                self.do_keyword(position, token)
            else:
                raise RunningRegionError("running-region structural token differs")
            if not self.context:
                self.flush()
        return self.results.pop(0)

    def do_keyword(self, position: int, token: PSKeyword) -> None:
        """Handle PDF keywords without constructing content-bearing logs."""

        if token in (self.KEYWORD_XREF, self.KEYWORD_STARTXREF):
            self.add_results(*self.pop(1))
        elif token is self.KEYWORD_ENDOBJ:
            self.add_results(*self.pop(4))
        elif token is self.KEYWORD_NULL:
            self.push((position, None))
        elif token is self.KEYWORD_R:
            if len(self.curstack) >= 2:
                (_, raw_object_id), _ = self.pop(2)
                object_id = safe_int(raw_object_id)
                if object_id is not None:
                    self.push((position, PDFObjRef(self.doc, object_id)))
        elif token is self.KEYWORD_STREAM:
            popped = self.pop(1)
            if len(popped) != 1:
                raise PDFSyntaxError("running-region stream dictionary differs")
            _dictionary_position, raw_dictionary = popped[0]
            dictionary = dict_value(raw_dictionary)
            object_length = 0
            if not self.fallback:
                try:
                    object_length = int_value(dictionary["Length"])
                except KeyError as exc:
                    if pdfminer_settings.STRICT:
                        raise PDFSyntaxError(
                            "running-region stream length differs"
                        ) from exc
            if object_length < 0:
                raise PDFSyntaxError("running-region stream length differs")
            validate_running_region_resource_count(
                "source_pdf_bytes",
                object_length,
            )
            self.seek(position)
            try:
                _line_position, line = self.nextline()
            except PSEOF as exc:
                if pdfminer_settings.STRICT:
                    raise PDFSyntaxError("Unexpected EOF") from exc
                return
            data_position = position + len(line)
            self.fp.seek(data_position)
            data = bytearray(self.fp.read(object_length))
            self.seek(data_position + object_length)
            while True:
                try:
                    _line_position, line = self.nextline()
                except PSEOF as exc:
                    if pdfminer_settings.STRICT:
                        raise PDFSyntaxError("Unexpected EOF") from exc
                    break
                if b"endstream" in line:
                    stream_end = line.index(b"endstream")
                    object_length += stream_end
                    if self.fallback:
                        data.extend(line[:stream_end])
                    break
                object_length += len(line)
                validate_running_region_resource_count(
                    "source_pdf_bytes",
                    object_length,
                )
                if self.fallback:
                    data.extend(line)
            self.seek(data_position + object_length)
            if self.doc is None:
                raise RunningRegionError("running-region document differs")
            stream = _BoundedPDFStream(
                dictionary,
                bytes(data),
                self.doc.decipher,
                budget=self._running_budget,
            )
            self.push((data_position, stream))
        else:
            self.push((position, token))

    def _check_token_append(self, count: int) -> None:
        if count < 0:
            raise RunningRegionError("running-region structural token differs")
        validate_running_region_resource_count(
            "candidate_text_utf8_bytes",
            len(self._curtoken) + count,
        )
        self._running_budget.check_deadline()

    def _bounded_match_append(
        self,
        pattern: Any,
        value: bytes,
        offset: int,
        *,
        extra: int = 0,
    ) -> None:
        match = pattern.search(value, offset)
        self._check_token_append(
            (match.start(0) if match is not None else len(value)) - offset + extra
        )

    def _parse_literal(self, value: bytes, offset: int) -> int:
        self._bounded_match_append(END_LITERAL, value, offset)
        return super()._parse_literal(value, offset)

    def _parse_literal_hex(self, value: bytes, offset: int) -> int:
        self._check_token_append(1)
        return super()._parse_literal_hex(value, offset)

    def _parse_string(self, value: bytes, offset: int) -> int:
        match = END_STRING.search(value, offset)
        end = match.start(0) if match is not None else len(value)
        marker = value[end : end + 1] if match is not None else b""
        extra = int(marker == b"(" or (marker == b")" and self.paren > 1))
        self._check_token_append(end - offset + extra)
        return super()._parse_string(value, offset)

    def _parse_string_1(self, value: bytes, offset: int) -> int:
        self._check_token_append(1)
        return super()._parse_string_1(value, offset)

    def _parse_hexstring(self, value: bytes, offset: int) -> int:
        self._bounded_match_append(END_HEX_STRING, value, offset)
        return super()._parse_hexstring(value, offset)

    def _parse_number(self, value: bytes, offset: int) -> int:
        match = END_NUMBER.search(value, offset)
        end = match.start(0) if match is not None else len(value)
        extra = int(match is not None and value[end : end + 1] == b".")
        self._check_token_append(end - offset + extra)
        return super()._parse_number(value, offset)

    def _parse_float(self, value: bytes, offset: int) -> int:
        self._bounded_match_append(END_NUMBER, value, offset)
        return super()._parse_float(value, offset)

    def _parse_keyword(self, value: bytes, offset: int) -> int:
        self._bounded_match_append(END_KEYWORD, value, offset)
        return super()._parse_keyword(value, offset)

    def _parse_comment(self, value: bytes, offset: int) -> int:
        self._running_budget.check_deadline(force=True)
        match = EOL.search(value, offset)
        if match is None:
            return len(value)
        self._curtoken = b""
        self._parse1 = self._parse_main
        return match.start(0)


_CMAP_WHITESPACE = b"\x00\t\n\x0c\r "
_CMAP_MAPPING_BLOCK = re.compile(
    rb"(?<![0-9])([0-9]{1,9})[\x00\t\n\x0c\r ]+"
    rb"begin(bf|cid)(char|range)\b(.*?)end\2\3\b",
    flags=re.DOTALL,
)


def _skip_cmap_space_and_comments(data: bytes, offset: int) -> int:
    while offset < len(data):
        if data[offset] in _CMAP_WHITESPACE:
            offset += 1
            continue
        if data[offset] != ord("%"):
            break
        newline = re.search(rb"[\r\n]", data[offset + 1 :])
        if newline is None:
            return len(data)
        offset += 1 + newline.end(0)
    return offset


def _parse_cmap_hex(data: bytes, offset: int) -> tuple[bytes, int]:
    offset = _skip_cmap_space_and_comments(data, offset)
    if (
        offset >= len(data)
        or data[offset : offset + 1] != b"<"
        or data[offset : offset + 2] == b"<<"
    ):
        raise RunningRegionError("running-region font mapping syntax differs")
    end = data.find(b">", offset + 1)
    if end < 0:
        raise RunningRegionError("running-region font mapping syntax differs")
    encoded = bytes(
        value for value in data[offset + 1 : end] if value not in _CMAP_WHITESPACE
    )
    if (
        not encoded
        or len(encoded) % 2
        or re.fullmatch(rb"[0-9A-Fa-f]+", encoded) is None
    ):
        raise RunningRegionError("running-region font mapping syntax differs")
    return bytes.fromhex(encoded.decode("ascii")), end + 1


def _parse_cmap_integer(data: bytes, offset: int) -> tuple[int, int]:
    offset = _skip_cmap_space_and_comments(data, offset)
    match = re.match(rb"[+-]?[0-9]+", data[offset:])
    if match is None:
        raise RunningRegionError("running-region font mapping syntax differs")
    end = offset + match.end(0)
    if end < len(data) and data[end] not in _CMAP_WHITESPACE:
        raise RunningRegionError("running-region font mapping syntax differs")
    return int(match.group(0)), end


def _bounded_cmap_mapping_count(data: bytes) -> int:
    """Count every mapping PDFMiner could materialize, without doing so."""

    if re.search(rb"\busecmap\b", data):
        raise RunningRegionResourceLimitError(
            "running-region inherited font mapping is not safely bounded",
            resource_name="source_characters_per_document",
        )
    blocks = tuple(_CMAP_MAPPING_BLOCK.finditer(data))
    declared_block_count = len(re.findall(rb"\bbegin(?:bf|cid)(?:char|range)\b", data))
    if len(blocks) != declared_block_count:
        raise RunningRegionError("running-region font mapping syntax differs")
    mapping_count = 0
    for block in blocks:
        declared = int(block.group(1))
        family = block.group(2)
        record_type = block.group(3)
        body = block.group(4)
        offset = 0
        records = 0
        while _skip_cmap_space_and_comments(body, offset) < len(body):
            offset = _skip_cmap_space_and_comments(body, offset)
            if record_type == b"char":
                if family == b"bf":
                    _source, offset = _parse_cmap_hex(body, offset)
                    _target, offset = _parse_cmap_hex(body, offset)
                else:
                    _cid, offset = _parse_cmap_integer(body, offset)
                    _target, offset = _parse_cmap_hex(body, offset)
                span = 1
            else:
                start, offset = _parse_cmap_hex(body, offset)
                end, offset = _parse_cmap_hex(body, offset)
                if len(start) != len(end):
                    raise RunningRegionError(
                        "running-region font mapping range differs"
                    )
                span = int.from_bytes(end, "big") - int.from_bytes(start, "big") + 1
                if span < 1:
                    raise RunningRegionError(
                        "running-region font mapping range differs"
                    )
                if family == b"cid":
                    _cid, offset = _parse_cmap_integer(body, offset)
                else:
                    offset = _skip_cmap_space_and_comments(body, offset)
                    if body[offset : offset + 1] == b"[":
                        offset += 1
                        target_count = 0
                        while True:
                            offset = _skip_cmap_space_and_comments(body, offset)
                            if body[offset : offset + 1] == b"]":
                                offset += 1
                                break
                            _target, offset = _parse_cmap_hex(body, offset)
                            target_count += 1
                            if target_count > MAX_CHARACTERS_PER_PAGE:
                                raise RunningRegionResourceLimitError(
                                    "running-region font mapping exceeded its cap",
                                    resource_name="source_characters_per_page",
                                )
                        if target_count != span:
                            raise RunningRegionError(
                                "running-region font mapping range differs"
                            )
                    else:
                        _target, offset = _parse_cmap_hex(body, offset)
            mapping_count += span
            if mapping_count > MAX_CHARACTERS_PER_PAGE:
                raise RunningRegionResourceLimitError(
                    "running-region font mapping exceeded its cap",
                    resource_name="source_characters_per_page",
                )
            records += 1
        if records != declared:
            raise RunningRegionError("running-region font mapping count differs")
    return mapping_count


class _BoundedPDFXRef(PDFXRef):
    """Classic xref reader without trailer/line value logging."""

    def load(self, parser: PDFParser) -> None:
        while True:
            try:
                position, line = parser.nextline()
                line = line.strip()
                if not line:
                    continue
            except PSEOF as exc:
                raise PDFNoValidXRef("Unexpected EOF - file corrupted?") from exc
            if line.startswith(b"trailer"):
                parser.seek(position)
                break
            fields = line.split(b" ")
            if len(fields) != 2:
                raise PDFNoValidXRef("running-region xref section differs")
            try:
                start, object_count = map(int, fields)
            except ValueError as exc:
                raise PDFNoValidXRef("running-region xref section differs") from exc
            for object_id in range(start, start + object_count):
                try:
                    _entry_position, line = parser.nextline()
                except PSEOF as exc:
                    raise PDFNoValidXRef("Unexpected EOF - file corrupted?") from exc
                fields = line.strip().split(b" ")
                if len(fields) != 3:
                    raise PDFNoValidXRef("running-region xref entry differs")
                position_bytes, generation_bytes, use_bytes = fields
                if use_bytes != b"n":
                    continue
                object_position = safe_int(position_bytes)
                generation = safe_int(generation_bytes)
                if object_position is not None and generation is not None:
                    self.offsets[object_id] = (
                        None,
                        object_position,
                        generation,
                    )
        self.load_trailer(parser)

    def load_trailer(self, parser: PDFParser) -> None:
        try:
            _position, keyword = parser.nexttoken()
            if keyword is not KWD(b"trailer"):
                raise PDFNoValidXRef("running-region xref trailer differs")
            _position, dictionary = parser.nextobject()
        except PSEOF:
            values = parser.pop(1)
            if not values:
                raise PDFNoValidXRef("Unexpected EOF - file corrupted") from None
            _position, dictionary = values[0]
        self.trailer.update(dict_value(dictionary))


class _BoundedPDFDocument(PDFDocument):
    """Resolve structural PDF objects without value-bearing debug calls."""

    def __init__(
        self,
        parser: _BoundedPDFParser,
        *,
        budget: _ExtractionBudget,
    ) -> None:
        self._running_budget = budget
        self._running_xref_starts: set[int] = set()
        # Fallback scanning uses PDFMiner parser classes that can log complete
        # structural values.  A malformed/missing xref therefore fails closed.
        super().__init__(parser, fallback=False)

    def getobj(self, objid: int) -> object:
        if not self.xrefs:
            raise PDFException("PDFDocument is not initialized")
        self._running_budget.check_deadline()
        if objid in self._cached_objs:
            value, _generation = self._cached_objs[objid]
            return value
        value: object
        generation: int
        for xref in self.xrefs:
            try:
                stream_id, index, generation = xref.get_pos(objid)
            except KeyError:
                continue
            try:
                if stream_id is not None:
                    stream = stream_value(self.getobj(stream_id))
                    value = self._getobj_objstm(stream, index, objid)
                else:
                    value = self._getobj_parse(index, objid)
                    if self.decipher:
                        value = decipher_all(
                            self.decipher,
                            objid,
                            generation,
                            value,
                        )
                if isinstance(value, PDFStream):
                    value.set_objid(objid, generation)
                break
            except (PSEOF, PDFSyntaxError):
                continue
        else:
            raise PDFObjectNotFound(objid)
        if self.caching:
            self._cached_objs[objid] = (value, generation)
        return value

    def find_xref(self, parser: PDFParser) -> int:
        previous = b""
        for line in parser.revreadlines():
            self._running_budget.check_deadline()
            line = line.strip()
            if line == b"startxref":
                if not previous.isdigit():
                    raise PDFNoValidXRef("running-region xref position differs")
                start = int(previous)
                if not 0 <= start < 2**31:
                    raise PDFNoValidXRef("running-region xref position differs")
                return start
            if line:
                previous = line
        raise PDFNoValidXRef("Unexpected EOF")

    def read_xref_from(
        self,
        parser: PDFParser,
        start: int,
        xrefs: list[PDFBaseXRef],
    ) -> None:
        if start in self._running_xref_starts:
            raise PDFNoValidXRef("running-region xref cycle differs")
        self._running_xref_starts.add(start)
        validate_running_region_resource_count(
            "boundary_candidates_per_page",
            len(self._running_xref_starts),
        )
        self._running_budget.check_deadline(force=True)
        parser.seek(start)
        parser.reset()
        try:
            position, token = parser.nexttoken()
        except PSEOF as exc:
            raise PDFNoValidXRef("Unexpected EOF") from exc
        if isinstance(token, int):
            parser.seek(position)
            parser.reset()
            xref: PDFBaseXRef = PDFXRefStream()
            xref.load(parser)
        else:
            if token is parser.KEYWORD_XREF:
                parser.nextline()
            xref = _BoundedPDFXRef()
            xref.load(parser)
        xrefs.append(xref)
        trailer = xref.get_trailer()
        if "XRefStm" in trailer:
            self.read_xref_from(
                parser,
                int_value(trailer["XRefStm"]),
                xrefs,
            )
        if "Prev" in trailer:
            self.read_xref_from(
                parser,
                int_value(trailer["Prev"]),
                xrefs,
            )


def _bounded_pdf_pages(
    document: _BoundedPDFDocument,
) -> Any:
    """Iterate the inherited page tree without logging page dictionaries."""

    try:
        page_labels = document.get_page_labels()
    except PDFNoPageLabels:
        page_labels = repeat(None)

    yielded_page = False
    if "Pages" in document.catalog:
        stack: list[tuple[Any, Mapping[str, Any]]] = [
            (document.catalog["Pages"], document.catalog)
        ]
        visited: set[int] = set()
        while stack:
            document._running_budget.check_deadline()
            raw_object, parent = stack.pop()
            if isinstance(raw_object, int):
                object_id = raw_object
                properties = dict_value(document.getobj(object_id)).copy()
            elif isinstance(raw_object, (PDFObjRef, PDFStream)):
                object_id = raw_object.objid
                properties = dict_value(raw_object).copy()
            else:
                raise RunningRegionError("running-region page tree differs")
            if object_id in visited:
                continue
            visited.add(object_id)
            validate_running_region_resource_count(
                "source_characters_per_page",
                len(visited),
            )
            for key, value in parent.items():
                if key in PDFPage.INHERITABLE_ATTRS and key not in properties:
                    properties[key] = value
            object_type = properties.get("Type")
            if object_type is None and not pdfminer_settings.STRICT:
                object_type = properties.get("type")
            if object_type is LITERAL_PAGES and "Kids" in properties:
                children = list(list_value(properties["Kids"]))
                validate_running_region_resource_count(
                    "source_characters_per_page",
                    len(visited) + len(children),
                )
                stack.extend((child, properties) for child in reversed(children))
            elif object_type is LITERAL_PAGE:
                yield PDFPage(
                    document,
                    object_id,
                    properties,
                    next(page_labels),
                )
                yielded_page = True
    if yielded_page:
        return
    for xref in document.xrefs:
        for object_id in xref.get_objids():
            document._running_budget.check_deadline()
            try:
                value = document.getobj(object_id)
                if isinstance(value, dict) and value.get("Type") is LITERAL_PAGE:
                    yield PDFPage(
                        document,
                        object_id,
                        value,
                        next(page_labels),
                    )
            except PDFObjectNotFound:
                continue


class _BoundedResourceManager(PDFResourceManager):
    def __init__(self, budget: _ExtractionBudget) -> None:
        self._running_budget = budget
        super().__init__()

    def get_font(self, objid: object, spec: Mapping[str, object]) -> Any:
        self._running_budget.check_deadline(force=True)
        # Type0 recursion re-enters this override.  Every concrete resource
        # stream must have been created by _BoundedPDFParser; refuse a foreign
        # eager-decode object before PDFMiner's font constructors can touch it.
        resources: list[Any] = []
        if "ToUnicode" in spec:
            to_unicode = resolve1(spec["ToUnicode"])
            resources.append(to_unicode)
            if isinstance(to_unicode, _BoundedPDFStream):
                cmap_data = to_unicode.get_data()
                validate_running_region_resource_count(
                    "candidate_text_utf8_bytes",
                    len(cmap_data),
                )
                self._running_budget.charge_font_mapping(
                    to_unicode,
                    _bounded_cmap_mapping_count(cmap_data),
                )
        descriptor = dict_value(spec.get("FontDescriptor", {}))
        for key in ("FontFile", "FontFile2", "FontFile3"):
            if key in descriptor:
                resources.append(resolve1(descriptor[key]))
        for resource in resources:
            if isinstance(resource, PDFStream) and not isinstance(
                resource, _BoundedPDFStream
            ):
                raise RunningRegionResourceLimitError(
                    "running-region font resource stream is not safely bounded",
                    resource_name="source_pdf_bytes",
                )
        if (
            objid not in self._cached_fonts
            and len(self._cached_fonts) >= MAX_BOUNDARY_CANDIDATES_PER_PAGE
        ):
            raise RunningRegionResourceLimitError(
                "running-region font cache exceeded its cap",
                resource_name="source_pdf_bytes",
            )
        if objid and objid in self._cached_fonts:
            return self._cached_fonts[objid]
        if pdfminer_settings.STRICT and spec["Type"] is not LITERAL_FONT:
            raise PDFFontError("Type is not /Font")
        if "Subtype" in spec:
            subtype = literal_name(spec["Subtype"])
        else:
            if pdfminer_settings.STRICT:
                raise PDFFontError("Font Subtype is not specified")
            subtype = "Type1"
        if subtype in {"Type1", "MMType1"}:
            font = PDFType1Font(self, spec)
        elif subtype == "TrueType":
            font = PDFTrueTypeFont(self, spec)
        elif subtype == "Type3":
            font = PDFType3Font(self, spec)
        elif subtype in {"CIDFontType0", "CIDFontType2"}:
            font = PDFCIDFont(self, spec)
        elif subtype == "Type0":
            descendant_fonts = list_value(spec["DescendantFonts"])
            if not descendant_fonts:
                raise PDFFontError("Font descendants differ")
            descendant_spec = dict_value(descendant_fonts[0]).copy()
            for key in ("Encoding", "ToUnicode"):
                if key in spec:
                    descendant_spec[key] = resolve1(spec[key])
            font = self.get_font(None, descendant_spec)
        else:
            if pdfminer_settings.STRICT:
                raise PDFFontError("Invalid Font spec")
            font = PDFType1Font(self, spec)
        if objid and self.caching:
            self._cached_fonts[objid] = font
        return font


class _BoundedPlumberPDF(pdfplumber.PDF):
    """The small pdfplumber construction seam needed for a scoped parser."""

    def __init__(self, stream: io.BytesIO, budget: _ExtractionBudget) -> None:
        self.stream = stream
        self.stream_is_external = False
        self.path = None
        self.pages_to_parse = None
        self.laparams = None
        self.password = None
        self.unicode_norm = None
        self.raise_unicode_errors = True
        parser = _BoundedPDFParser(stream, budget=budget)
        self.doc = _BoundedPDFDocument(parser, budget=budget)
        self.rsrcmgr = _BoundedResourceManager(budget)
        # US08 consumes neither document metadata nor pdfplumber's warning-
        # emitting best-effort metadata decoder.
        self.metadata: dict[str, Any] = {}

    @property
    def pages(self) -> list[Any]:
        if hasattr(self, "_pages"):
            return self._pages
        self._pages = []
        doctop = 0.0
        for page_offset, page_object in enumerate(_bounded_pdf_pages(self.doc)):
            validate_running_region_resource_count(
                "pages_per_document",
                page_offset + 1,
            )
            page = pdfplumber.page.Page(
                self,
                page_object,
                page_number=page_offset + 1,
                initial_doctop=doctop,
            )
            self._pages.append(page)
            doctop += float(page.height)
            self.rsrcmgr._running_budget.check_deadline(force=True)
        return self._pages


class _SourceContentParser(PDFContentParser):
    """PDFMiner content parser without disabled debug-call allocation."""

    def __init__(
        self,
        streams: Sequence[Any],
        *,
        budget: _ExtractionBudget | None = None,
    ) -> None:
        self.budget = budget
        self.decoded_bytes = 0
        super().__init__(streams)

    def fillfp(self) -> bool:
        if self.fp:
            return False
        if self.istream >= len(self.streams):
            raise PSEOF("Unexpected EOF, file truncated?")
        if self.budget is not None:
            self.budget.check_deadline(force=True)
        stream = stream_value(self.streams[self.istream])
        self.istream += 1
        if isinstance(stream, _BoundedPDFStream):
            data = stream.get_data()
            self.fp = io.BytesIO(data)
            return True
        raw = stream.rawdata
        filters = stream.get_filters()
        data: bytes
        # Bound the common compressed-content path before materializing its
        # decoded payload.  PDFMiner's ordinary get_data() uses unbounded
        # zlib.decompress(), which permits a tiny PDF stream to allocate far
        # beyond the source cap before the next deadline poll.
        simple_flate = (
            isinstance(raw, bytes)
            and stream.decipher is None
            and len(filters) == 1
            and literal_name(filters[0][0]) in {"Fl", "FlateDecode"}
            and (
                not filters[0][1]
                or (
                    isinstance(filters[0][1], Mapping)
                    and filters[0][1].get("Predictor", 1) == 1
                )
            )
        )
        if simple_flate:
            try:
                decoder = zlib.decompressobj()
                remaining_budget = (
                    self.budget.decoded_remaining()
                    if self.budget is not None
                    else MAX_SOURCE_PDF_BYTES - self.decoded_bytes
                )
                if remaining_budget < 0:
                    raise RunningRegionResourceLimitError(
                        "running-region decoded content stream exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                data = decoder.decompress(raw, remaining_budget + 1)
                if len(data) > remaining_budget or decoder.unconsumed_tail:
                    raise RunningRegionResourceLimitError(
                        "running-region decoded content stream exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                remaining = remaining_budget - len(data) + 1
                data += decoder.flush(remaining)
                if (
                    len(data) > remaining_budget
                    or not decoder.eof
                    or decoder.unused_data
                ):
                    raise RunningRegionResourceLimitError(
                        "running-region decoded content stream exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
            except zlib.error as exc:
                raise RunningRegionError(
                    "running-region content stream is unavailable"
                ) from exc
        elif filters or stream.decipher is not None:
            # Every accepted compressed stream must have a decoder with a hard
            # output bound.  Chained filters, predictors, LZW/ASCII wrappers,
            # and encrypted streams are therefore refused instead of falling
            # through PDFMiner's eager unbounded get_data().
            raise RunningRegionResourceLimitError(
                "running-region content stream filter is not safely bounded",
                resource_name="source_pdf_bytes",
            )
        elif isinstance(raw, bytes):
            data = raw
        else:
            raise RunningRegionError("running-region content stream differs")
        if not isinstance(data, bytes):
            raise RunningRegionError("running-region content stream differs")
        if self.budget is not None:
            self.budget.retain_decoded_bytes(len(data))
        else:
            self.decoded_bytes += len(data)
            if self.decoded_bytes > MAX_SOURCE_PDF_BYTES:
                raise RunningRegionResourceLimitError(
                    "running-region decoded content stream exceeded its cap",
                    resource_name="source_pdf_bytes",
                )
        self.fp = io.BytesIO(data)
        return True

    def seek(self, position: int) -> None:
        self.fillfp()
        self.fp.seek(position)
        self.bufpos = position
        self.buf = b""
        self.charpos = 0
        self._parse1 = self._parse_main
        self._curtoken = b""
        self._curtokenpos = 0
        self._tokens = []
        self.eof = False
        self.reset()

    def nexttoken(self) -> tuple[int, Any]:
        if self.eof:
            raise PSEOF("Unexpected EOF")
        while not self._tokens:
            if self.budget is not None:
                self.budget.check_deadline()
            try:
                changed_stream = self.fillbuf()
                if changed_stream and self._curtoken:
                    self._parse1(b"\n", 0)
                else:
                    self.charpos = self._parse1(self.buf, self.charpos)
            except PSEOF:
                self.charpos = self._parse1(b"\n", 0)
                self.eof = True
                if not self._tokens:
                    raise
        return self._tokens.pop(0)

    def _check_token_append(self, count: int) -> None:
        if count < 0:
            raise RunningRegionError("running-region content token differs")
        if len(self._curtoken) + count > MAX_CANDIDATE_TEXT_BYTES:
            raise RunningRegionResourceLimitError(
                "running-region content token exceeded its cap",
                resource_name="candidate_text_utf8_bytes",
            )

    def _parse_literal(self, value: bytes, offset: int) -> int:
        if len(self._curtoken) + len(value) - offset > MAX_CANDIDATE_TEXT_BYTES:
            match = END_LITERAL.search(value, offset)
            self._check_token_append(
                (match.start(0) if match is not None else len(value)) - offset
            )
        return super()._parse_literal(value, offset)

    def _parse_literal_hex(self, value: bytes, offset: int) -> int:
        self._check_token_append(1)
        return super()._parse_literal_hex(value, offset)

    def _parse_string(self, value: bytes, offset: int) -> int:
        if len(self._curtoken) + len(value) - offset > MAX_CANDIDATE_TEXT_BYTES:
            match = END_STRING.search(value, offset)
            end = match.start(0) if match is not None else len(value)
            marker = value[end : end + 1] if match is not None else b""
            extra = int(marker == b"(" or (marker == b")" and self.paren > 1))
            self._check_token_append(end - offset + extra)
        return super()._parse_string(value, offset)

    def _parse_string_1(self, value: bytes, offset: int) -> int:
        self._check_token_append(1)
        return super()._parse_string_1(value, offset)

    def _parse_hexstring(self, value: bytes, offset: int) -> int:
        if len(self._curtoken) + len(value) - offset > MAX_CANDIDATE_TEXT_BYTES:
            match = END_HEX_STRING.search(value, offset)
            self._check_token_append(
                (match.start(0) if match is not None else len(value)) - offset
            )
        return super()._parse_hexstring(value, offset)

    def _parse_number(self, value: bytes, offset: int) -> int:
        match = END_NUMBER.search(value, offset)
        end = match.start(0) if match is not None else len(value)
        extra = int(match is not None and value[end : end + 1] == b".")
        self._check_token_append(end - offset + extra)
        if match is None:
            self._curtoken += value[offset:]
            return len(value)
        self._curtoken += value[offset:end]
        if value[end : end + 1] == b".":
            self._curtoken += b"."
            self._parse1 = self._parse_float
            return end + 1
        try:
            self._add_token(int(self._curtoken))
        except ValueError:
            pass
        self._parse1 = self._parse_main
        return end

    def _parse_float(self, value: bytes, offset: int) -> int:
        match = END_NUMBER.search(value, offset)
        end = match.start(0) if match is not None else len(value)
        self._check_token_append(end - offset)
        if match is None:
            self._curtoken += value[offset:]
            return len(value)
        self._curtoken += value[offset:end]
        try:
            self._add_token(float(self._curtoken))
        except ValueError:
            pass
        self._parse1 = self._parse_main
        return end

    def _parse_keyword(self, value: bytes, offset: int) -> int:
        match = END_KEYWORD.search(value, offset)
        end = match.start(0) if match is not None else len(value)
        self._check_token_append(end - offset)
        if match is None:
            self._curtoken += value[offset:]
            return len(value)
        self._curtoken += value[offset:end]
        if self._curtoken == b"true":
            token: bool | PSKeyword = True
        elif self._curtoken == b"false":
            token = False
        else:
            token = KWD(self._curtoken)
        self._add_token(token)
        self._parse1 = self._parse_main
        return end

    def _parse_comment(self, value: bytes, offset: int) -> int:
        """Skip comments without retaining attacker-controlled bytes."""

        if self.budget is not None:
            self.budget.check_deadline(force=True)
        match = EOL.search(value, offset)
        if match is None:
            return len(value)
        self._curtoken = b""
        self._parse1 = self._parse_main
        return match.start(0)

    def push(self, *objects: tuple[int, Any]) -> None:
        if len(self.curstack) + len(objects) > MAX_CHARACTERS_PER_PAGE:
            raise RunningRegionResourceLimitError(
                "running-region resource boundary exceeded",
                resource_name="source_characters_per_page",
            )
        super().push(*objects)

    def add_results(self, *objects: tuple[int, Any]) -> None:
        self.results.extend(objects)

    def start_type(self, position: int, value_type: str) -> None:
        if len(self.context) >= MAX_PUBLIC_PATH_SEGMENTS:
            raise RunningRegionResourceLimitError(
                "running-region content nesting exceeded its cap",
                resource_name="public_path_segments",
            )
        if self.budget is not None:
            self.budget.check_deadline()
        self.context.append((position, self.curtype, self.curstack))
        self.curtype, self.curstack = value_type, []

    def get_inline_data(
        self,
        position: int,
        target: bytes = b"EI",
    ) -> tuple[int, bytes]:
        """Consume inline-image bytes linearly without retaining a duplicate."""

        self.seek(position)
        matched = 0
        while matched <= len(target):
            if self.budget is not None:
                self.budget.check_deadline(force=True)
            self.fillbuf()
            if matched:
                if self.charpos >= len(self.buf):
                    continue
                current = bytes((self.buf[self.charpos],))
                self.charpos += 1
                if (len(target) <= matched and current.isspace()) or (
                    matched < len(target) and current == bytes((target[matched],))
                ):
                    matched += 1
                else:
                    matched = 0
            else:
                try:
                    found = self.buf.index(target[0], self.charpos)
                except ValueError:
                    self.charpos = len(self.buf)
                else:
                    self.charpos = found + 1
                    matched = 1
        return position, b""

    def end_type(self, value_type: str) -> tuple[int, list[Any]]:
        if self.curtype != value_type:
            raise PSTypeError(f"Type mismatch: {self.curtype!r} != {value_type!r}")
        objects = [value for _position, value in self.curstack]
        position, self.curtype, self.curstack = self.context.pop()
        return position, objects

    def nextobject(self) -> tuple[int, Any]:
        while not self.results:
            position, token = self.nexttoken()
            if isinstance(token, (int, float, bool, str, bytes, PSLiteral)):
                self.push((position, token))
            elif token == KEYWORD_ARRAY_BEGIN:
                self.start_type(position, "a")
            elif token == KEYWORD_ARRAY_END:
                try:
                    self.push(self.end_type("a"))
                except PSTypeError:
                    if pdfminer_settings.STRICT:
                        raise
            elif token == KEYWORD_DICT_BEGIN:
                self.start_type(position, "d")
            elif token == KEYWORD_DICT_END:
                try:
                    position, objects = self.end_type("d")
                    if len(objects) % 2 != 0:
                        raise PSSyntaxError(
                            f"Invalid dictionary construct: {objects!r}"
                        )
                    value = {
                        literal_name(key): item
                        for key, item in choplist(2, objects)
                        if item is not None
                    }
                    self.push((position, value))
                except PSTypeError:
                    if pdfminer_settings.STRICT:
                        raise
            elif token == KEYWORD_PROC_BEGIN:
                self.start_type(position, "p")
            elif token == KEYWORD_PROC_END:
                try:
                    self.push(self.end_type("p"))
                except PSTypeError:
                    if pdfminer_settings.STRICT:
                        raise
            elif isinstance(token, PSKeyword):
                self.do_keyword(position, token)
            else:
                raise RunningRegionError("running-region content token differs")
            if not self.context:
                self.flush()
        return self.results.pop(0)


class _SourceTextInterpreter(PDFPageInterpreter):
    """Interpret text/state/XObjects without constructing unused PDF paths."""

    def __init__(
        self,
        resource_manager: Any,
        device: Any,
        *,
        budget: _ExtractionBudget | None = None,
        form_depth: int = 0,
    ) -> None:
        super().__init__(resource_manager, device)
        self.budget = (
            budget
            if budget is not None
            else getattr(
                device,
                "budget",
                None,
            )
        )
        self.form_depth = form_depth

    def dup(self) -> "_SourceTextInterpreter":
        next_depth = self.form_depth + 1
        validate_running_region_resource_count(
            "printed_label_form_depth",
            next_depth,
        )
        if self.budget is not None:
            self.budget.check_deadline(force=True)
        return self.__class__(
            self.rsrcmgr,
            self.device,
            budget=self.budget,
            form_depth=next_depth,
        )

    def init_resources(self, resources: dict[object, object]) -> None:
        """Resolve only bounded resource maps, without logging their values."""

        self.resources = resources
        self.fontmap = {}
        self.xobjmap = {}
        self.csmap = PREDEFINED_COLORSPACE.copy()
        if not resources:
            return
        resolved_resources = dict_value(resources)
        if len(resolved_resources) > MAX_REFERENCES_PER_RECORD:
            raise RunningRegionResourceLimitError(
                "running-region resource map exceeded its cap",
                resource_name="source_pdf_bytes",
            )

        def get_colorspace(spec: object) -> PDFColorSpace | None:
            if isinstance(spec, list):
                if not spec or len(spec) > MAX_REFERENCES_PER_RECORD:
                    raise RunningRegionResourceLimitError(
                        "running-region color resource exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                name = literal_name(spec[0])
            else:
                name = literal_name(spec)
            if name == "ICCBased" and isinstance(spec, list) and len(spec) >= 2:
                channels = stream_value(spec[1]).get("N")
                if (
                    isinstance(channels, bool)
                    or not isinstance(channels, int)
                    or not 1 <= channels <= 8
                ):
                    raise RunningRegionError("running-region color resource differs")
                return PDFColorSpace(name, channels)
            if name == "DeviceN" and isinstance(spec, list) and len(spec) >= 2:
                components = list_value(spec[1])
                if not 1 <= len(components) <= 8:
                    raise RunningRegionResourceLimitError(
                        "running-region color resource exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                return PDFColorSpace(name, len(components))
            return PREDEFINED_COLORSPACE.get(name)

        for resource_name, value in resolved_resources.items():
            if self.budget is not None:
                self.budget.check_deadline()
            if resource_name == "Font":
                fonts = dict_value(value)
                if len(fonts) > MAX_BOUNDARY_CANDIDATES_PER_PAGE:
                    raise RunningRegionResourceLimitError(
                        "running-region font resource map exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                for font_id, raw_spec in fonts.items():
                    objid = raw_spec.objid if isinstance(raw_spec, PDFObjRef) else None
                    self.fontmap[font_id] = self.rsrcmgr.get_font(
                        objid,
                        dict_value(raw_spec),
                    )
            elif resource_name == "ColorSpace":
                color_spaces = dict_value(value)
                if len(color_spaces) > MAX_REFERENCES_PER_RECORD:
                    raise RunningRegionResourceLimitError(
                        "running-region color resource map exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                for color_id, raw_spec in color_spaces.items():
                    color_space = get_colorspace(resolve1(raw_spec))
                    if color_space is not None:
                        self.csmap[color_id] = color_space
            elif resource_name == "ProcSet":
                procedures = list_value(value)
                if len(procedures) > MAX_REFERENCES_PER_RECORD:
                    raise RunningRegionResourceLimitError(
                        "running-region procedure resource exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                self.rsrcmgr.get_procset(procedures)
            elif resource_name == "XObject":
                xobjects = dict_value(value)
                if len(xobjects) > MAX_BOUNDARY_CANDIDATES_PER_PAGE:
                    raise RunningRegionResourceLimitError(
                        "running-region XObject resource map exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                self.xobjmap.update(xobjects)

    def process_page(self, page: PDFPage) -> None:
        if self.budget is not None:
            self.budget.check_deadline(force=True)
        x0, y0, x1, y1 = page.mediabox
        if page.rotate == 90:
            ctm = (0, -1, 1, 0, -y0, x1)
        elif page.rotate == 180:
            ctm = (-1, 0, 0, -1, x1, y1)
        elif page.rotate == 270:
            ctm = (0, 1, -1, 0, y1, -x0)
        else:
            ctm = (1, 0, 0, 1, -x0, -y0)
        self.device.begin_page(page, ctm)
        self.render_contents(page.resources, page.contents, ctm=ctm)
        self.device.end_page(page)

    def render_contents(
        self,
        resources: dict[object, object],
        streams: Sequence[object],
        ctm: Any = MATRIX_IDENTITY,
    ) -> None:
        if self.budget is not None:
            self.budget.check_deadline(force=True)
        self.init_resources(resources)
        self.init_state(ctm)
        self.execute(list_value(streams))

    def do_Do(self, xobjid_arg: Any) -> None:
        xobjid = literal_name(xobjid_arg)
        raw_xobject = self.xobjmap.get(xobjid)
        if raw_xobject is None:
            if pdfminer_settings.STRICT:
                raise PDFInterpreterError("Undefined running-region XObject")
            return
        xobject = stream_value(raw_xobject)
        subtype = xobject.get("Subtype")
        if subtype is LITERAL_IMAGE:
            # Images carry no text for this device and are never decoded.
            return
        if subtype is not LITERAL_FORM or "BBox" not in xobject:
            return
        bbox = list_value(xobject["BBox"])
        matrix = list_value(xobject.get("Matrix", MATRIX_IDENTITY))
        if (
            len(bbox) != 4
            or len(matrix) != 6
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in (*bbox, *matrix)
            )
        ):
            raise RunningRegionError("running-region Form geometry differs")
        xobject_resources = xobject.get("Resources")
        resources = (
            dict_value(xobject_resources)
            if xobject_resources
            else self.resources.copy()
        )
        interpreter = self.subinterp()
        self.device.begin_figure(xobjid, bbox, matrix)
        interpreter.render_contents(
            resources,
            [xobject],
            ctm=mult_matrix(matrix, self.ctm),
        )
        self.device.end_figure(xobjid)

    def execute(self, streams: Sequence[Any]) -> None:
        valid_streams: list[Any] = []
        self.stream_ids.clear()
        for value in streams:
            if self.budget is not None:
                self.budget.check_deadline(force=True)
            stream = stream_value(value)
            if stream.objid is None:
                continue
            if stream.objid in self.parent_stream_ids:
                continue
            else:
                if len(valid_streams) >= MAX_REFERENCES_PER_RECORD:
                    raise RunningRegionResourceLimitError(
                        "running-region content stream count exceeded its cap",
                        resource_name="source_pdf_bytes",
                    )
                valid_streams.append(stream)
                self.stream_ids.add(stream.objid)
        try:
            parser = _SourceContentParser(valid_streams, budget=self.budget)
        except PSEOF:
            return
        operator_cache: dict[str, tuple[Callable[..., Any], int] | None] = {}
        while True:
            try:
                _position, value = parser.nextobject()
            except PSEOF:
                break
            if isinstance(value, PSKeyword):
                name = keyword_name(value)
                cached = operator_cache.get(name)
                if name not in operator_cache:
                    method = "do_{}".format(
                        name.replace("*", "_a").replace('"', "_w").replace("'", "_q")
                    )
                    function = getattr(self, method, None)
                    cached = (
                        (function, function.__code__.co_argcount - 1)
                        if function is not None
                        else None
                    )
                    operator_cache[name] = cached
                if cached is not None:
                    function, argument_count = cached
                    if argument_count:
                        arguments = self.pop(argument_count)
                        if len(arguments) == argument_count:
                            self._validate_operator_arguments(name, arguments)
                            function(*arguments)
                    else:
                        function()
                elif pdfminer_settings.STRICT:
                    raise PDFInterpreterError(f"Unknown operator: {name!r}")
            else:
                self.push(value)

    @staticmethod
    def _validate_operator_arguments(name: str, arguments: Sequence[Any]) -> None:
        def number(value: Any) -> bool:
            return (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
            )

        all_numeric = {
            "cm",
            "w",
            "G",
            "g",
            "RG",
            "rg",
            "K",
            "k",
            "Tc",
            "Tw",
            "Tz",
            "TL",
            "Ts",
            "Tm",
        }
        valid = True
        if name in all_numeric:
            valid = all(number(value) for value in arguments)
        elif name == "Tr":
            valid = (
                len(arguments) == 1
                and number(arguments[0])
                and float(arguments[0]).is_integer()
            )
        elif name == "Tf":
            valid = (
                len(arguments) == 2
                and isinstance(arguments[0], PSLiteral)
                and number(arguments[1])
            )
        elif name in {"MP", "BMC", "Do"}:
            valid = len(arguments) == 1 and isinstance(arguments[0], PSLiteral)
        elif name in {"DP", "BDC"}:
            valid = len(arguments) == 2 and isinstance(arguments[0], PSLiteral)
        if not valid:
            raise RunningRegionError("running-region content operand differs")

    def push(self, *objects: Any) -> None:
        if len(self.argstack) + len(objects) > MAX_CHARACTERS_PER_PAGE:
            raise RunningRegionResourceLimitError(
                "running-region resource boundary exceeded",
                resource_name="source_characters_per_page",
            )
        super().push(*objects)

    def do_q(self) -> None:
        if len(self.gstack) >= MAX_REFERENCES_PER_RECORD:
            raise RunningRegionResourceLimitError(
                "running-region graphics-state depth exceeded its cap",
                resource_name="source_characters_per_page",
            )
        if self.budget is not None:
            self.budget.check_deadline()
        self.gstack.append(self.get_current_state())

    def _set_bounded_color(self, *, stroking: bool) -> None:
        color_space = self.graphicstate.scs if stroking else self.graphicstate.ncs
        if color_space.name == "Pattern":
            raise RunningRegionError("running-region pattern color is unsupported")
        count = color_space.ncomponents
        components = self.pop(count)
        if len(components) != count or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in components
        ):
            raise RunningRegionError("running-region content color differs")
        color: Any = (
            float(components[0])
            if len(components) == 1
            else tuple(float(value) for value in components)
        )
        if stroking:
            self.graphicstate.scolor = color
        else:
            self.graphicstate.ncolor = color

    def do_SCN(self) -> None:
        self._set_bounded_color(stroking=True)

    def do_scn(self) -> None:
        self._set_bounded_color(stroking=False)

    # Exact method arity is required: PDFMiner's operator dispatcher inspects
    # ``co_argcount`` before popping operands from the content stream.
    def do_m(self, x: Any, y: Any) -> None:
        del x, y

    def do_l(self, x: Any, y: Any) -> None:
        del x, y

    def do_c(
        self,
        x1: Any,
        y1: Any,
        x2: Any,
        y2: Any,
        x3: Any,
        y3: Any,
    ) -> None:
        del x1, y1, x2, y2, x3, y3

    def do_v(self, x2: Any, y2: Any, x3: Any, y3: Any) -> None:
        del x2, y2, x3, y3

    def do_y(self, x1: Any, y1: Any, x3: Any, y3: Any) -> None:
        del x1, y1, x3, y3

    def do_h(self) -> None:
        return None

    def do_re(self, x: Any, y: Any, width: Any, height: Any) -> None:
        del x, y, width, height

    def do_S(self) -> None:
        return None

    def do_s(self) -> None:
        return None

    def do_f(self) -> None:
        return None

    def do_F(self) -> None:
        return None

    def do_f_a(self) -> None:
        return None

    def do_B(self) -> None:
        return None

    def do_B_a(self) -> None:
        return None

    def do_b(self) -> None:
        return None

    def do_b_a(self) -> None:
        return None

    def do_n(self) -> None:
        return None

    def do_W(self) -> None:
        return None

    def do_W_a(self) -> None:
        return None


def _source_embedded_label(
    pdfium_document: Any,
    page_offset: int,
) -> tuple[str | None, tuple[str, ...]]:
    raw_label = pdfium_document.get_page_label(page_offset)
    if not raw_label:
        return None, ()
    try:
        return _normalize_embedded_label(str(raw_label)), ()
    except RunningRegionError:
        return None, ("page_identity_embedded_label_invalid",)


def _materialize_source_page(
    plumber_page: Any,
    pdfium_document: Any,
    page_offset: int,
    budget: _ExtractionBudget,
) -> _SourcePage:
    page_index = page_offset + 1
    device = _MinimalCharacterDevice(
        plumber_page.pdf.rsrcmgr,
        unicode_norm=plumber_page.pdf.unicode_norm,
        budget=budget,
        page_index=page_index,
    )
    _SourceTextInterpreter(
        plumber_page.pdf.rsrcmgr,
        device,
        budget=budget,
    ).process_page(plumber_page.page_obj)
    page_height = float(plumber_page.height)
    initial_doctop = float(plumber_page.initial_doctop)
    mb_x0, mb_top = plumber_page.mediabox[:2]
    char_records: list[dict[str, Any]] = []
    while device.glyphs:
        (
            text,
            x0,
            y0,
            x1,
            y1,
            upright,
            size,
            non_stroking_color,
        ) = device.glyphs.pop()
        budget.check_deadline()
        top = (page_height - y1) + mb_top
        char_records.append(
            {
                "text": text,
                "x0": x0 + mb_x0 if mb_x0 != 0 else x0,
                "x1": x1 + mb_x0 if mb_x0 != 0 else x1,
                "top": top,
                "bottom": (page_height - y0) + mb_top,
                "doctop": initial_doctop + top,
                "upright": upright,
                "size": size,
                "height": y1 - y0,
                "width": x1 - x0,
                "non_stroking_color": non_stroking_color,
            }
        )
    char_records.reverse()
    chars = tuple(char_records)
    word_records: list[dict[str, Any]] = []
    word_extractor = _BoundedWordExtractor(
        budget=budget,
        page_index=page_index,
    )
    for word, _word_chars in word_extractor.iter_extract_tuples(char_records):
        word_records.append(word)
    embedded_label, concern_codes = _source_embedded_label(
        pdfium_document,
        page_offset,
    )
    return _SourcePage(
        page_index=page_index,
        width=float(plumber_page.width),
        height=float(plumber_page.height),
        chars=chars,
        words=tuple(word_records),
        embedded_label=embedded_label,
        concern_codes=concern_codes,
    )


def _read_source_pages(
    source_pdf_bytes: bytes,
    *,
    pdfium_document: Any | None = None,
    budget: _ExtractionBudget | None = None,
) -> tuple[_SourcePage, ...]:
    if not isinstance(source_pdf_bytes, bytes) or not source_pdf_bytes:
        raise RunningRegionError("running-region source PDF differs")
    validate_running_region_resource_count("source_pdf_bytes", len(source_pdf_bytes))
    active_budget = budget or _ExtractionBudget.start()
    active_budget.check_deadline(force=True)
    owned_pdfium_document: Any | None = None
    plumber_document: Any | None = None
    try:
        if pdfium_document is None:
            owned_pdfium_document = pdfium.PdfDocument(source_pdf_bytes)
            pdfium_document = owned_pdfium_document
        plumber_document = _BoundedPlumberPDF(
            io.BytesIO(source_pdf_bytes),
            active_budget,
        )
    except RunningRegionError:
        if owned_pdfium_document is not None:
            owned_pdfium_document.close()
        raise
    except Exception as exc:
        if owned_pdfium_document is not None:
            owned_pdfium_document.close()
        raise RunningRegionError("running-region source PDF is unavailable") from exc
    try:
        pdfium_page_count = len(pdfium_document)
        if not 1 <= pdfium_page_count:
            raise RunningRegionError("running-region source page count differs")
        validate_running_region_resource_count("pages_per_document", pdfium_page_count)
        if pdfium_page_count != len(plumber_document.pages):
            raise RunningRegionError("running-region source page count differs")
        pages: list[_SourcePage] = []
        for page_offset, plumber_page in enumerate(plumber_document.pages):
            active_budget.check_deadline(force=True)
            try:
                page = _materialize_source_page(
                    plumber_page,
                    pdfium_document,
                    page_offset,
                    active_budget,
                )
            except RunningRegionResourceLimitError as exc:
                if exc.resource_name not in {
                    "source_characters_per_page",
                    "source_words_per_page",
                    "candidate_text_utf8_bytes",
                    "printed_label_form_depth",
                }:
                    raise
                active_budget.discard_page_source_counts(page_offset + 1)
                embedded_label, _embedded_concerns = _source_embedded_label(
                    pdfium_document,
                    page_offset,
                )
                page = _SourcePage(
                    page_index=page_offset + 1,
                    width=float(plumber_page.width),
                    height=float(plumber_page.height),
                    chars=(),
                    words=(),
                    embedded_label=embedded_label,
                    # A refused page carries one closed page-scoped outcome.
                    # Unmaterialized embedded-label diagnostics must not make
                    # the source-limit payload internally contradictory.
                    concern_codes=("running_region_source_limit",),
                )
            except Exception as exc:
                raise RunningRegionError(
                    "running-region source text layout is unavailable"
                ) from exc
            pages.append(page)
            active_budget.check_deadline(force=True)
        return tuple(pages)
    finally:
        plumber_document.close()
        if owned_pdfium_document is not None:
            owned_pdfium_document.close()


def _element_bbox(
    element: Mapping[str, Any],
    bboxes: Mapping[str, Mapping[str, Any]],
    public_item: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    bbox_ids = element.get("bbox_ids")
    if (
        not isinstance(bbox_ids, list)
        or not bbox_ids
        or len(bbox_ids) != len(set(bbox_ids))
        or not isinstance(public_item.get("bbox"), Mapping)
    ):
        raise RunningRegionError("running-region owner bbox differs")
    public_box = _bbox(public_item["bbox"])
    matches: list[tuple[str, dict[str, Any]]] = []
    for bbox_id in bbox_ids:
        if not isinstance(bbox_id, str) or not bbox_id:
            raise RunningRegionError("running-region owner bbox differs")
        record = bboxes.get(bbox_id)
        if record is None:
            raise RunningRegionError("running-region owner bbox is unresolved")
        normalized = _bbox(record)
        if normalized == public_box:
            matches.append((bbox_id, normalized))
    if len(matches) != 1:
        raise RunningRegionError("running-region owner bbox custody differs")
    return matches[0]


def _words_in_bbox(
    page: _SourcePage,
    box: Mapping[str, Any],
    *,
    budget: _ExtractionBudget | None = None,
    word_index: _PageWordIndex | None = None,
) -> list[tuple[int, Mapping[str, Any]]]:
    if word_index is not None:
        return word_index.query(page, box, budget=budget)
    selected: list[tuple[int, Mapping[str, Any]]] = []
    for index, word in enumerate(page.words):
        if budget is not None:
            budget.charge_comparisons(page.page_index)
        if _center_inside(word, box):
            selected.append((index, word))
    return selected


def _candidate_signature(
    values: Sequence[tuple[int, Mapping[str, Any]]],
) -> str:
    return _normalized_signature(
        " ".join(str(word.get("text") or "") for _index, word in values)
    )


def _native_word_geometry_boundaries(
    page: _SourcePage,
    native_words: Sequence[tuple[int, Mapping[str, Any]]],
    *,
    budget: _ExtractionBudget | None,
    character_index: _PageCharacterIndex,
    boundary_cache: MutableMapping[tuple[int, int], frozenset[int]],
) -> Mapping[int, frozenset[int]]:
    """Return compact-scalar offsets backed by a visible inter-glyph gap."""

    def calculate(word: Mapping[str, Any]) -> frozenset[int]:
        if word.get("upright") is not True or word.get("direction") != "ltr":
            return frozenset()
        native_scalar = _normalized_signature(word.get("text"))
        if not native_scalar:
            return frozenset()
        try:
            word_box = _source_bbox(word)
            characters = [
                character
                for _index, character in character_index.query(
                    page,
                    word_box,
                    budget=budget,
                )
            ]
        except (KeyError, TypeError, ValueError):
            return frozenset()
        normalized_characters: list[str] = []
        valid_geometry = True
        for character in characters:
            raw_text = character.get("text")
            if not isinstance(raw_text, str) or not raw_text:
                valid_geometry = False
                break
            normalized_text = unicodedata.normalize("NFC", raw_text).casefold()
            if not normalized_text or any(value.isspace() for value in normalized_text):
                valid_geometry = False
                break
            try:
                coordinates = tuple(
                    float(character[name]) for name in ("x0", "x1", "top", "bottom")
                )
            except (KeyError, TypeError, ValueError):
                valid_geometry = False
                break
            if (
                not all(math.isfinite(value) for value in coordinates)
                or coordinates[1] <= coordinates[0]
                or coordinates[3] <= coordinates[2]
                or character.get("upright") is not True
            ):
                valid_geometry = False
                break
            normalized_characters.append(normalized_text)
        if (
            not valid_geometry
            or len(characters) < 2
            or "".join(normalized_characters) != native_scalar
        ):
            return frozenset()
        allowed: set[int] = set()
        compact_offset = 0
        for offset, (current, following) in enumerate(pairwise(characters)):
            compact_offset += len(normalized_characters[offset])
            current_height = float(current["bottom"]) - float(current["top"])
            following_height = float(following["bottom"]) - float(following["top"])
            minimum_height = min(current_height, following_height)
            current_center = (float(current["top"]) + float(current["bottom"])) / 2.0
            following_center = (
                float(following["top"]) + float(following["bottom"])
            ) / 2.0
            horizontal_gap = float(following["x0"]) - float(current["x1"])
            if abs(following_center - current_center) <= max(
                0.25, minimum_height * 0.05
            ) and horizontal_gap >= max(0.25, minimum_height * 0.10):
                allowed.add(compact_offset)
        return frozenset(allowed)

    result: dict[int, frozenset[int]] = {}
    for word_index, word in native_words:
        cache_key = (page.page_index, word_index)
        if cache_key not in boundary_cache:
            boundary_cache[cache_key] = calculate(word)
        result[word_index] = boundary_cache[cache_key]
    return result


def _structured_owner_signature_binds(
    *,
    page: _SourcePage,
    owner: Mapping[str, Any],
    owner_box: Mapping[str, Any],
    selected_words: Sequence[tuple[int, Mapping[str, Any]]],
    declared_signature: str,
    budget: _ExtractionBudget | None,
    word_index: _PageWordIndex | None,
    character_index: _PageCharacterIndex,
    geometry_boundary_cache: MutableMapping[tuple[int, int], frozenset[int]],
    public_page: Mapping[str, Any] | None,
) -> str | None:
    children = owner.get("items")
    if not isinstance(children, list) or not children:
        return None
    outer_indexes = {index for index, _word in selected_words}
    claimed_indexes: set[int] = set()
    declared_children: list[str] = []
    unmatched_ocr_children = 0
    unmatched_children: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    outer_left = float(owner_box["x"])
    outer_top = float(owner_box["y"])
    outer_right = outer_left + float(owner_box["width"])
    outer_bottom = outer_top + float(owner_box["height"])
    for child in children:
        if not isinstance(child, Mapping) or not isinstance(child.get("bbox"), Mapping):
            return None
        try:
            child_box = _bbox(child["bbox"])
        except RunningRegionError:
            return None
        child_right = float(child_box["x"]) + float(child_box["width"])
        child_bottom = float(child_box["y"]) + float(child_box["height"])
        if (
            float(child_box["x"]) < outer_left - 0.001
            or float(child_box["y"]) < outer_top - 0.001
            or child_right > outer_right + 0.001
            or child_bottom > outer_bottom + 0.001
        ):
            return None
        child_words = _words_in_bbox(
            page,
            child_box,
            budget=budget,
            word_index=word_index,
        )
        child_indexes = {index for index, _word in child_words}
        child_signature = _normalized_signature(
            child.get("value") if child.get("value") is not None else child.get("md")
        )
        declared_children.append(child_signature)
        if not child_indexes:
            confidence = child.get("confidence")
            if (
                not child_signature
                or child.get("confidence_source") != "matched_page_ocr"
                or isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
                or not 0.0 <= float(confidence) <= 1.0
            ):
                return None
            unmatched_ocr_children += 1
            unmatched_children.append((child, child_box))
            continue
        scalar_matches = _structured_native_scalar_matches(
            child_signature,
            child_words,
        )
        if not scalar_matches:
            scalar_matches = _structured_native_scalar_matches(
                child_signature,
                child_words,
                fused_word_boundaries=_native_word_geometry_boundaries(
                    page,
                    child_words,
                    budget=budget,
                    character_index=character_index,
                    boundary_cache=geometry_boundary_cache,
                ),
            )
        if (
            claimed_indexes.intersection(child_indexes)
            or not child_indexes <= outer_indexes
            or child.get("source") != "native"
            or not child_signature
            or not scalar_matches
        ):
            return None
        claimed_indexes.update(child_indexes)
    if (
        claimed_indexes != outer_indexes
        or _normalized_signature(" ".join(declared_children)) != declared_signature
        or unmatched_ocr_children > 1
    ):
        return None
    if unmatched_children:
        page_items = (
            public_page.get("items") if isinstance(public_page, Mapping) else None
        )
        if not isinstance(page_items, list):
            return None
        for child, child_box in unmatched_children:
            child_signature = _normalized_signature(child.get("value"))
            child_confidence = float(child["confidence"])
            witnesses: list[Mapping[str, Any]] = []
            for sibling in page_items:
                if budget is not None:
                    budget.charge_comparisons(page.page_index)
                if sibling is owner or not isinstance(sibling, Mapping):
                    continue
                records = sibling.get("items")
                if not isinstance(records, list):
                    continue
                for record in records:
                    if budget is not None:
                        budget.charge_comparisons(page.page_index)
                    if (
                        not isinstance(record, Mapping)
                        or record.get("accepted") is not True
                        or record.get("source") != "ocr"
                        or _normalized_signature(
                            record.get("value", record.get("text"))
                        )
                        != child_signature
                        or record.get("confidence") != child_confidence
                        or not isinstance(record.get("bbox"), Mapping)
                    ):
                        continue
                    try:
                        witness_box = _bbox(record["bbox"])
                    except RunningRegionError:
                        continue
                    intersection = _intersection_area(child_box, witness_box)
                    if (
                        intersection
                        / min(
                            _area(child_box),
                            _area(witness_box),
                        )
                        >= 0.95
                    ):
                        witnesses.append(record)
            if len(witnesses) != 1:
                return None
    return "additive_ocr" if unmatched_ocr_children else "complete"


def _native_owner_evidence_binds(
    *,
    owner: Mapping[str, Any],
    element: Mapping[str, Any],
    bbox_id: str,
    evidence_records: Mapping[str, Mapping[str, Any]] | None,
) -> bool:
    if evidence_records is None:
        return False
    evidence_ids = element.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        return False
    owner_value = owner.get("value")
    if not isinstance(owner_value, str) or owner.get("md") not in {
        owner_value,
        owner_value.replace("\n", "\n\n"),
    }:
        return False
    matches = []
    for evidence_id in evidence_ids:
        record = evidence_records.get(str(evidence_id))
        if (
            isinstance(record, Mapping)
            and record.get("id") == evidence_id
            and record.get("element_id") == element.get("id")
            and record.get("method") == "native"
            and record.get("bbox_id") == bbox_id
            and record.get("value") == owner_value
        ):
            matches.append(record)
    return len(matches) == 1


def _direct_candidate_evidence_ids(
    *,
    element: Mapping[str, Any],
    bbox_id: str,
    evidence_records: Mapping[str, Mapping[str, Any]] | None,
) -> list[str]:
    """Select only direct-owner evidence bound to the candidate bbox."""

    evidence_ids = _bounded_references(
        element.get("evidence_ids") or (),
        "evidence_ids_per_record",
    )
    if evidence_records is None:
        raise RunningRegionError("running-region direct evidence is unavailable")
    matched = [
        evidence_id
        for evidence_id in evidence_ids
        if (
            isinstance(record := evidence_records.get(evidence_id), Mapping)
            and record.get("id") == evidence_id
            and record.get("element_id") == element.get("id")
            and record.get("bbox_id") == bbox_id
        )
    ]
    return _bounded_references(matched, "evidence_ids_per_record")


def _boundary_candidate(
    *,
    source_sha256: str,
    page: _SourcePage,
    public_item: Mapping[str, Any],
    public_path: Sequence[Any],
    element: Mapping[str, Any],
    bboxes: Mapping[str, Mapping[str, Any]],
    raw_layout_role: str | None,
    source_method: str,
    boundary_band: str,
    character_indexes: MutableMapping[int, _PageCharacterIndex],
    geometry_boundary_cache: MutableMapping[tuple[int, int], frozenset[int]],
    box_override: Mapping[str, Any] | None = None,
    bbox_id_override: str | None = None,
    evidence_ids_override: Sequence[str] | None = None,
    source_object_ids_override: Sequence[str] | None = None,
    signature_override: str | None = None,
    budget: _ExtractionBudget | None = None,
    word_index: _PageWordIndex | None = None,
    public_page: Mapping[str, Any] | None = None,
    evidence_records: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if isinstance(public_path, (str, bytes, bytearray)) or not isinstance(
        public_path, Sequence
    ):
        raise RunningRegionError("running-region public path differs")
    validate_running_region_resource_count(
        "public_path_segments",
        len(public_path),
    )
    if box_override is None:
        bbox_id, box = _element_bbox(element, bboxes, public_item)
    else:
        validated_box = _bbox(box_override)
        box = {
            "x": round(float(box_override["x"]), 5),
            "y": round(float(box_override["y"]), 5),
            "width": round(float(box_override["width"]), 5),
            "height": round(float(box_override["height"]), 5),
            "unit": validated_box["unit"],
        }
        if not bbox_id_override:
            raise RunningRegionError("running-region extracted bbox ID differs")
        bbox_id = bbox_id_override
    selected_words = _words_in_bbox(
        page,
        box,
        budget=budget,
        word_index=word_index,
    )
    source_object_ids = (
        _bounded_references(
            source_object_ids_override,
            "source_object_ids_per_record",
        )
        if source_object_ids_override is not None
        else _word_ids(
            source_sha256, page.page_index, [index for index, _word in selected_words]
        )
    )
    evidence_ids = (
        _bounded_references(
            evidence_ids_override,
            "evidence_ids_per_record",
        )
        if evidence_ids_override is not None
        else _direct_candidate_evidence_ids(
            element=element,
            bbox_id=bbox_id,
            evidence_records=evidence_records,
        )
    )
    source_object_ids = _bounded_references(
        source_object_ids,
        "source_object_ids_per_record",
    )
    selected_signature = _candidate_signature(selected_words)
    owner_signature = (
        signature_override
        if signature_override is not None
        else _normalized_signature(
            public_item.get("value")
            if public_item.get("value") is not None
            else public_item.get("md")
        )
    )
    structured_binding = None
    if bool(selected_signature) and owner_signature != selected_signature:
        character_index = character_indexes.get(page.page_index)
        if character_index is None:
            if budget is not None:
                budget.check_deadline(force=True)
            character_index = _PageCharacterIndex.build(page)
            character_indexes[page.page_index] = character_index
            if budget is not None:
                budget.check_deadline(force=True)
        structured_binding = _structured_owner_signature_binds(
            page=page,
            owner=public_item,
            owner_box=box,
            selected_words=selected_words,
            declared_signature=owner_signature,
            budget=budget,
            word_index=word_index,
            character_index=character_index,
            geometry_boundary_cache=geometry_boundary_cache,
            public_page=public_page,
        )
        if structured_binding is not None and not _native_owner_evidence_binds(
            owner=public_item,
            element=element,
            bbox_id=bbox_id,
            evidence_records=evidence_records,
        ):
            structured_binding = None
    if not selected_signature:
        raise _RunningRegionSourceBindingRefusal(
            "running-region native/source signature binding differs"
        )
    if owner_signature == selected_signature or structured_binding == "complete":
        declared_signature = owner_signature
    elif (
        source_method == "trusted_layout_role"
        and signature_override is None
        and structured_binding == "additive_ocr"
    ):
        # The one additive OCR scalar is independently witnessed by an accepted
        # same-page OCR record with identical value/confidence/geometry.  The
        # candidate's source-object list remains native-only, while the complete
        # configured owner signature is retained under predecessor hash custody.
        declared_signature = owner_signature
    else:
        raise _RunningRegionSourceBindingRefusal(
            "running-region native/source signature binding differs"
        )
    candidate: dict[str, Any] = {
        "id": "",
        "public_item_id": str(public_item.get("id") or ""),
        "public_path": list(public_path),
        "element_id": str(element.get("id") or ""),
        "predecessor_type": str(public_item.get("type") or ""),
        "bbox": box,
        "bbox_id": bbox_id,
        "evidence_ids": evidence_ids,
        "source_object_ids": source_object_ids,
        "raw_layout_role": raw_layout_role,
        "normalized_signature": declared_signature,
        "boundary_band": boundary_band,
        "source_method": source_method,
        "confidence": _confidence(),
        "concern_codes": [],
        "disposition": "accepted",
    }
    candidate["id"] = _stable_id(
        "boundary-candidate",
        POLICY_ID,
        source_sha256,
        page.page_index,
        candidate["public_item_id"],
        candidate["public_path"],
        candidate["element_id"],
        candidate["bbox_id"],
        candidate["evidence_ids"],
        candidate["source_object_ids"],
        candidate["boundary_band"],
        candidate["source_method"],
    )
    return candidate


def _nominal_band(box: Mapping[str, Any], page_height: float) -> str | None:
    top = float(box["y"])
    bottom = top + float(box["height"])
    if bottom <= page_height * 0.15 + 0.001:
        return "top"
    if top >= page_height * 0.85 - 0.001:
        return "bottom"
    return None


def _candidate_label_phrases(
    selected_words: Sequence[tuple[int, Mapping[str, Any]]],
    owner_value: Any,
) -> list[tuple[list[int], list[Mapping[str, Any]], str]]:
    if not isinstance(owner_value, str):
        return []

    def strip_unsafe_edge_tokens(values: Sequence[str]) -> list[str]:
        retained = list(values)

        def unsafe_icon(value: str) -> bool:
            return bool(value) and all(
                unicodedata.category(character) in {"Cc", "Cf", "Co", "Cs"}
                for character in value
            )

        while retained and unsafe_icon(retained[0]):
            retained.pop(0)
        while retained and unsafe_icon(retained[-1]):
            retained.pop()
        return retained

    owner_lines = {
        " ".join(strip_unsafe_edge_tokens(line.split()))
        for line in owner_value.splitlines()
        if strip_unsafe_edge_tokens(line.split())
    }

    def is_declared_owner_label(text: str) -> bool:
        try:
            normalized = _normalize_detected_label(text)
        except RunningRegionError:
            return False
        for owner_line in owner_lines:
            try:
                if _normalize_detected_label(owner_line) == normalized:
                    return True
            except RunningRegionError:
                continue
        # Some predecessors retain a one-line footer while the native source
        # makes its terminal folio a separate visual field.  Admit only the
        # unique terminal integer token; refuse calendar-year ambiguity.
        if _LABEL_INTEGER_RE.fullmatch(normalized):
            number = int(normalized)
            owner_scalar = " ".join(owner_value.split())
            matches = list(
                re.finditer(
                    rf"(?<![0-9]){re.escape(normalized)}(?![0-9])", owner_scalar
                )
            )
            if (
                len(matches) == 1
                and matches[0].end() == len(owner_scalar)
                and not 1900 <= number <= 2100
            ):
                return True
        return False

    phrases: list[tuple[list[int], list[Mapping[str, Any]], str]] = []
    for offset, (_index, _word) in enumerate(selected_words):
        for length in (4, 3, 1):
            values = selected_words[offset : offset + length]
            if len(values) != length:
                continue
            indexes = [value[0] for value in values]
            if indexes != list(range(indexes[0], indexes[0] + length)):
                continue
            text = " ".join(str(value[1].get("text") or "") for value in values)
            if is_declared_owner_label(text):
                phrases.append((indexes, [value[1] for value in values], text))
    return phrases


def _navigation_cue_from_text(value: str) -> str | None:
    normalized = unicodedata.normalize("NFC", value)
    upper = " ".join(normalized.upper().split())
    matches: set[str] = set()
    for cue in _NAVIGATION_TEXT_CUES:
        if re.search(rf"(?<!\w){re.escape(cue)}(?!\w)", upper):
            matches.add(cue)
    for cue in _NAVIGATION_GLYPH_CUES:
        if cue in normalized:
            matches.add(cue)
    return next(iter(matches)) if len(matches) == 1 else None


def _characters_for_phrase(
    page: _SourcePage,
    words: Sequence[Mapping[str, Any]],
    visible_text: str,
) -> tuple[list[int], list[Mapping[str, Any]], str]:
    word_box = _bbox_union([_source_bbox(word) for word in words])
    candidate_indexes = [
        index
        for index, character in enumerate(page.chars)
        if _center_inside(character, word_box, tolerance=1.0)
    ]
    scalar_records = [
        (index, str(page.chars[index].get("text") or "")) for index in candidate_indexes
    ]

    def selected_span(target: str, *, compact: bool) -> list[int] | None:
        projected = ""
        scalar_offsets: list[tuple[int, int, int]] = []
        for source_index, value in scalar_records:
            emitted = "".join(value.split()) if compact else value
            if not emitted:
                continue
            start = len(projected)
            projected += emitted
            scalar_offsets.append((start, len(projected), source_index))
        matches = [
            offset
            for offset in range(max(len(projected) - len(target) + 1, 0))
            if projected.startswith(target, offset)
        ]
        if len(matches) != 1:
            return None
        start = matches[0]
        end = start + len(target)
        selected = [
            source_index
            for scalar_start, scalar_end, source_index in scalar_offsets
            if scalar_end > start and scalar_start < end
        ]
        if not selected:
            return None
        # Retain the complete source interval, including source U+0020 scalars
        # between words; those characters are part of exact evidence custody.
        first = candidate_indexes.index(selected[0])
        last = candidate_indexes.index(selected[-1])
        return candidate_indexes[first : last + 1]

    retained = selected_span(visible_text, compact=False)
    if retained is None:
        retained = selected_span("".join(visible_text.split()), compact=True)
    if retained is None:
        raise RunningRegionError("printed-label character custody differs")
    characters = [page.chars[index] for index in retained]
    exact = "".join(str(character.get("text") or "") for character in characters)
    if " ".join(exact.split()) != " ".join(visible_text.split()):
        raise RunningRegionError("printed-label visible scalar differs")
    exact = visible_text
    return retained, characters, exact


def _pdf_color_component(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise RunningRegionError("printed-label PDF fill component differs")
    return float(value)


def normalize_pdf_non_stroking_fill(value: Any) -> tuple[int, int, int]:
    """Normalize a finite DeviceGray/RGB/CMYK fill to RGB bytes."""

    if isinstance(value, bool) or value is None:
        raise RunningRegionError("printed-label PDF fill differs")
    if isinstance(value, (int, float)):
        components = (_pdf_color_component(value),)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) not in {1, 3, 4}:
            raise RunningRegionError("printed-label PDF fill shape differs")
        components = tuple(_pdf_color_component(component) for component in value)
    else:
        raise RunningRegionError("printed-label PDF fill differs")
    if len(components) == 1:
        rgb = components * 3
    elif len(components) == 3:
        rgb = components
    else:
        cyan, magenta, yellow, black = components
        rgb = (
            (1 - cyan) * (1 - black),
            (1 - magenta) * (1 - black),
            (1 - yellow) * (1 - black),
        )
    return tuple(math.floor(value * 255 + 0.5) for value in rgb)  # type: ignore[return-value]


def _rgb_max_channel_delta(left: Sequence[int], right: Sequence[int]) -> int:
    if (
        len(left) != 3
        or len(right) != 3
        or any(
            isinstance(channel, bool)
            or not isinstance(channel, int)
            or not 0 <= channel <= 255
            for channel in (*left, *right)
        )
    ):
        raise RunningRegionError("printed-label RGB differs")
    return max(abs(left[index] - right[index]) for index in range(3))


def _displayed_pdf_object_bbox(
    bounds: Sequence[Any],
    *,
    page_width: float,
    page_height: float,
    page_rotation: int,
) -> dict[str, Any] | None:
    if len(bounds) != 4 or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in bounds
    ):
        raise RunningRegionError("printed-label PDF text-object geometry differs")
    left, bottom, right, top = (float(value) for value in bounds)
    if right <= left or top <= bottom:
        return None
    if page_rotation == 0:
        x, y = left, page_height - top
        width, height = right - left, top - bottom
    elif page_rotation == 90:
        x, y = bottom, left
        width, height = top - bottom, right - left
    elif page_rotation == 180:
        x, y = page_width - right, bottom
        width, height = right - left, top - bottom
    elif page_rotation == 270:
        x, y = page_width - top, page_height - right
        width, height = top - bottom, right - left
    else:
        raise RunningRegionError("printed-label visibility page rotation differs")
    if (
        not all(math.isfinite(value) for value in (x, y, width, height))
        or width <= 0
        or height <= 0
    ):
        raise RunningRegionError("printed-label PDF text-object geometry differs")
    return {"x": x, "y": y, "width": width, "height": height, "unit": "pt"}


def _bboxes_have_positive_intersection(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    left_right = float(left["x"]) + float(left["width"])
    left_bottom = float(left["y"]) + float(left["height"])
    right_right = float(right["x"]) + float(right["width"])
    right_bottom = float(right["y"]) + float(right["height"])
    return (
        min(left_right, right_right) - max(float(left["x"]), float(right["x"])) > 0
        and min(left_bottom, right_bottom) - max(float(left["y"]), float(right["y"]))
        > 0
    )


def _validate_printed_label_text_object_custody(
    page: Any,
    *,
    candidate_visible_text: str,
    candidate_bbox: Mapping[str, Any],
    page_width: float,
    page_height: float,
    page_rotation: int,
    normalized_fills: Sequence[tuple[int, int, int]],
    fill_arities: Sequence[int],
) -> tuple[tuple[int, int, int], ...]:
    target_compact = "".join(candidate_visible_text.split())
    intersecting: list[tuple[str, str, tuple[int, int, int], int, int]] = []
    scanned_count = 0
    textpage = page.get_textpage()
    try:
        for text_object in page.get_objects(
            filter=[pdfium_c.FPDF_PAGEOBJ_TEXT],
            max_depth=PRINTED_LABEL_MAX_FORM_DEPTH,
            textpage=textpage,
        ):
            scanned_count += 1
            validate_running_region_resource_count(
                "printed_label_text_object_scan", scanned_count
            )
            object_bbox = _displayed_pdf_object_bbox(
                text_object.get_bounds(),
                page_width=page_width,
                page_height=page_height,
                page_rotation=page_rotation,
            )
            if object_bbox is None or not _bboxes_have_positive_intersection(
                object_bbox, candidate_bbox
            ):
                continue
            validate_running_region_resource_count(
                "printed_label_text_objects", len(intersecting) + 1
            )
            try:
                object_text = text_object.extract()
                object_text_bytes = object_text.encode("utf-8")
            except Exception as exc:
                raise RunningRegionError(
                    "printed-label PDF text-object text is unavailable"
                ) from exc
            validate_running_region_resource_count(
                "candidate_text_utf8_bytes", len(object_text_bytes)
            )
            compact_text = "".join(object_text.split())
            render_mode = pdfium_c.FPDFTextObj_GetTextRenderMode(text_object.raw)
            red, green, blue, alpha = (c_uint() for _ in range(4))
            if not pdfium_c.FPDFPageObj_GetFillColor(
                text_object.raw, red, green, blue, alpha
            ):
                raise RunningRegionError(
                    "printed-label PDF text-object fill is unavailable"
                )
            intersecting.append(
                (
                    object_text,
                    compact_text,
                    (red.value, green.value, blue.value),
                    render_mode,
                    alpha.value,
                )
            )
    finally:
        textpage.close()

    matches: set[tuple[int, ...]] = set()
    for start in range(len(intersecting)):
        combined = ""
        for end in range(start, len(intersecting)):
            combined += intersecting[end][1]
            if combined == target_compact:
                matches.add(tuple(range(start, end + 1)))
            if len(combined) >= len(target_compact):
                break
        object_text = intersecting[start][0].rstrip()
        if object_text.endswith(candidate_visible_text):
            prefix = object_text[: -len(candidate_visible_text)]
            if not prefix or prefix[-1].isspace() or prefix[-1] in "|:/-":
                matches.add((start,))
    if len(matches) != 1:
        raise RunningRegionError("printed-label PDF candidate-text custody differs")

    selected = tuple(intersecting[index] for index in next(iter(matches)))
    if any(
        record[3] not in PRINTED_LABEL_PAINTED_FILL_RENDER_MODES or record[4] == 0
        for record in selected
    ):
        raise RunningRegionError(
            "printed-label PDF text object is unpainted/transparent"
        )
    selected_fill_rgbs = tuple(record[2] for record in selected)

    def corroborates(
        normalized_fill: tuple[int, int, int],
        fill_arity: int,
        selected_fill: tuple[int, int, int],
    ) -> bool:
        maximum_delta = (
            MAX_PRINTED_LABEL_CMYK_CUSTODY_CHANNEL_DELTA if fill_arity == 4 else 0
        )
        return _rgb_max_channel_delta(normalized_fill, selected_fill) <= maximum_delta

    if any(
        not any(
            corroborates(normalized_fill, fill_arity, selected_fill)
            for selected_fill in selected_fill_rgbs
        )
        for normalized_fill, fill_arity in zip(
            normalized_fills, fill_arities, strict=True
        )
    ) or any(
        not any(
            corroborates(normalized_fill, fill_arity, selected_fill)
            for normalized_fill, fill_arity in zip(
                normalized_fills, fill_arities, strict=True
            )
        )
        for selected_fill in selected_fill_rgbs
    ):
        raise RunningRegionError("printed-label PDF fill/object custody differs")
    return selected_fill_rgbs


def validate_rendered_label_visibility(
    source_pdf_bytes: bytes,
    *,
    physical_page_index: int,
    candidate_visible_text: str,
    candidate_bbox: Mapping[str, Any],
    non_stroking_fills: Sequence[Any],
    _document: Any | None = None,
) -> None:
    """Require exact candidate text to be visibly painted in its PDF crop."""

    if not isinstance(source_pdf_bytes, bytes) or not source_pdf_bytes:
        raise RunningRegionError("printed-label visibility PDF differs")
    validate_running_region_resource_count("source_pdf_bytes", len(source_pdf_bytes))
    if (
        isinstance(physical_page_index, bool)
        or not isinstance(physical_page_index, int)
        or not 1 <= physical_page_index <= MAX_PAGES
    ):
        raise RunningRegionError("printed-label visibility page differs")
    visible_text = _safe_text(
        candidate_visible_text, maximum_bytes=MAX_VISIBLE_TEXT_BYTES
    )
    if (
        visible_text != visible_text.strip()
        or "\n" in visible_text
        or "\r" in visible_text
    ):
        raise RunningRegionError("printed-label visible text differs")
    if not isinstance(candidate_bbox, Mapping) or set(candidate_bbox) != {
        "x",
        "y",
        "width",
        "height",
        "unit",
    }:
        raise RunningRegionError("printed-label visibility bbox differs")
    bbox = {
        "x": float(candidate_bbox["x"]),
        "y": float(candidate_bbox["y"]),
        "width": float(candidate_bbox["width"]),
        "height": float(candidate_bbox["height"]),
        "unit": candidate_bbox["unit"],
    }
    if (
        bbox["unit"] != "pt"
        or not all(
            math.isfinite(float(bbox[key])) for key in ("x", "y", "width", "height")
        )
        or float(bbox["width"]) <= 0
        or float(bbox["height"]) <= 0
    ):
        raise RunningRegionError("printed-label visibility bbox differs")
    if (
        not isinstance(non_stroking_fills, Sequence)
        or isinstance(non_stroking_fills, (str, bytes, bytearray))
        or not non_stroking_fills
    ):
        raise RunningRegionError("printed-label PDF fill count differs")
    validate_running_region_resource_count(
        "printed_label_non_stroking_fills", len(non_stroking_fills)
    )
    normalized_fills = tuple(
        normalize_pdf_non_stroking_fill(fill) for fill in non_stroking_fills
    )
    fill_arities = tuple(
        1
        if isinstance(fill, (int, float)) and not isinstance(fill, bool)
        else len(fill)
        for fill in non_stroking_fills
    )

    try:
        with (
            pdfium.PdfDocument(source_pdf_bytes)
            if _document is None
            else nullcontext(_document)
        ) as document:
            if not 1 <= len(document) or physical_page_index > len(document):
                raise RunningRegionError(
                    "printed-label visibility PDF page count differs"
                )
            validate_running_region_resource_count("pages_per_document", len(document))
            page = document[physical_page_index - 1]
            try:
                page_rotation = page.get_rotation()
                if page_rotation not in {0, 90, 180, 270}:
                    raise RunningRegionError(
                        "printed-label visibility page rotation differs"
                    )
                page_width, page_height = (float(value) for value in page.get_size())
                if not all(
                    math.isfinite(value) and value > 0
                    for value in (page_width, page_height)
                ):
                    raise RunningRegionError(
                        "printed-label visibility page geometry differs"
                    )
                for dimension in (page_width, page_height):
                    validate_running_region_resource_count(
                        "printed_label_page_dimension_points",
                        math.ceil(dimension),
                    )
                if (
                    float(bbox["x"]) < 0
                    or float(bbox["y"]) < 0
                    or float(bbox["x"]) + float(bbox["width"]) > page_width + 0.001
                    or float(bbox["y"]) + float(bbox["height"]) > page_height + 0.001
                ):
                    raise RunningRegionError(
                        "printed-label visibility bbox is outside the page"
                    )
                selected_fill_rgbs = _validate_printed_label_text_object_custody(
                    page,
                    candidate_visible_text=visible_text,
                    candidate_bbox=bbox,
                    page_width=page_width,
                    page_height=page_height,
                    page_rotation=page_rotation,
                    normalized_fills=normalized_fills,
                    fill_arities=fill_arities,
                )
                left_px = round(float(bbox["x"]) * PRINTED_LABEL_RENDER_SCALE_PX_PER_PT)
                top_px = round(float(bbox["y"]) * PRINTED_LABEL_RENDER_SCALE_PX_PER_PT)
                right_px = round(
                    (float(bbox["x"]) + float(bbox["width"]))
                    * PRINTED_LABEL_RENDER_SCALE_PX_PER_PT
                )
                bottom_px = round(
                    (float(bbox["y"]) + float(bbox["height"]))
                    * PRINTED_LABEL_RENDER_SCALE_PX_PER_PT
                )
                page_right_px = round(page_width * PRINTED_LABEL_RENDER_SCALE_PX_PER_PT)
                page_bottom_px = round(
                    page_height * PRINTED_LABEL_RENDER_SCALE_PX_PER_PT
                )
                width_px_bound = right_px - left_px
                height_px_bound = bottom_px - top_px
                if (
                    left_px < 0
                    or top_px < 0
                    or right_px > page_right_px
                    or bottom_px > page_bottom_px
                    or width_px_bound < 1
                    or height_px_bound < 1
                ):
                    raise RunningRegionError(
                        "printed-label visibility render bounds differ"
                    )
                validate_running_region_resource_count(
                    "printed_label_render_dimension_pixels", width_px_bound
                )
                validate_running_region_resource_count(
                    "printed_label_render_dimension_pixels", height_px_bound
                )
                validate_running_region_resource_count(
                    "printed_label_render_pixels",
                    width_px_bound * height_px_bound,
                )
                left = left_px / PRINTED_LABEL_RENDER_SCALE_PX_PER_PT
                top = top_px / PRINTED_LABEL_RENDER_SCALE_PX_PER_PT
                right = max(
                    0.0, page_width - right_px / PRINTED_LABEL_RENDER_SCALE_PX_PER_PT
                )
                bottom = max(
                    0.0, page_height - bottom_px / PRINTED_LABEL_RENDER_SCALE_PX_PER_PT
                )
                bitmap = page.render(
                    scale=PRINTED_LABEL_RENDER_SCALE_PX_PER_PT,
                    rotation=0,
                    crop=(left, bottom, right, top),
                    may_draw_forms=False,
                    fill_color=(255, 255, 255, 255),
                    rev_byteorder=True,
                    prefer_bgrx=False,
                    maybe_alpha=False,
                    draw_annots=False,
                )
                try:
                    rendered_image = bitmap.to_pil()
                    try:
                        width_px = bitmap.width
                        height_px = bitmap.height
                        pixel_count = width_px * height_px
                        if (
                            rendered_image.mode != "RGB"
                            or rendered_image.size != (width_px, height_px)
                            or rendered_image.size != (width_px_bound, height_px_bound)
                            or width_px < 1
                            or height_px < 1
                        ):
                            raise RunningRegionError(
                                "printed-label visibility bitmap differs"
                            )
                        validate_running_region_resource_count(
                            "printed_label_render_dimension_pixels", width_px
                        )
                        validate_running_region_resource_count(
                            "printed_label_render_dimension_pixels", height_px
                        )
                        validate_running_region_resource_count(
                            "printed_label_render_pixels", pixel_count
                        )
                        if len(rendered_image.tobytes()) != pixel_count * 3:
                            raise RunningRegionError(
                                "printed-label visibility RGB payload differs"
                            )
                        colors = rendered_image.getcolors(maxcolors=pixel_count)
                        if not colors:
                            raise RunningRegionError(
                                "printed-label visibility colors differ"
                            )
                    finally:
                        rendered_image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    except RunningRegionError:
        raise
    except Exception as exc:
        raise RunningRegionError("printed-label visibility rendering failed") from exc

    _modal_count, modal_rgb = min(colors, key=lambda record: (-record[0], record[1]))
    render_delta = max(
        _rgb_max_channel_delta(color, modal_rgb) for _count, color in colors
    )
    minimum_fill_delta = min(
        _rgb_max_channel_delta(fill, modal_rgb) for fill in selected_fill_rgbs
    )
    if (
        render_delta < PRINTED_LABEL_MIN_RGB_CHANNEL_DELTA
        or minimum_fill_delta < PRINTED_LABEL_MIN_RGB_CHANNEL_DELTA
    ):
        raise RunningRegionError(
            "printed-label render/fill contrast is below the closed threshold"
        )


def _label_candidate(
    *,
    source_pdf_bytes: bytes,
    source_sha256: str,
    page: _SourcePage,
    word_indexes: Sequence[int],
    words: Sequence[Mapping[str, Any]],
    visible_text: str,
    visibility_document: Any | None = None,
) -> dict[str, Any] | None:
    try:
        character_indexes, characters, exact_visible = _characters_for_phrase(
            page, words, visible_text
        )
        normalized = _normalize_detected_label(exact_visible)
        box = _bbox_union([_source_bbox(character) for character in characters])
        validate_rendered_label_visibility(
            source_pdf_bytes,
            physical_page_index=page.page_index,
            candidate_visible_text=exact_visible,
            candidate_bbox=box,
            non_stroking_fills=[
                character.get("non_stroking_color") for character in characters
            ],
            _document=visibility_document,
        )
        source_object_ids = [
            *_character_ids(source_sha256, page.page_index, character_indexes),
            *_word_ids(source_sha256, page.page_index, word_indexes),
        ]
        source_object_ids = _bounded_references(
            source_object_ids,
            "source_object_ids_per_record",
        )
        candidate_id = _stable_id(
            "label-candidate",
            POLICY_ID,
            source_sha256,
            page.page_index,
            source_object_ids,
            box,
        )
        return {
            "id": candidate_id,
            "visible_text": exact_visible,
            "normalized_label": normalized,
            "bbox": box,
            "source_object_ids": source_object_ids,
            "source_method": "native_printed_label",
            "confidence": _confidence(),
            "concern_codes": [],
        }
    except RunningRegionResourceLimitError:
        raise
    except RunningRegionError:
        return None


def _precise_source_bbox(values: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not values:
        raise RunningRegionError("extracted source bbox is empty")
    left = min(float(value["x0"]) for value in values)
    top = min(float(value["top"]) for value in values)
    right = max(float(value["x1"]) for value in values)
    bottom = max(float(value["bottom"]) for value in values)
    return {
        "x": round(left, 5),
        "y": round(top, 5),
        "width": round(right - left, 5),
        "height": round(bottom - top, 5),
        "unit": "pt",
    }


def _area(box: Mapping[str, Any]) -> float:
    return float(box["width"]) * float(box["height"])


def _intersection_area(first: Mapping[str, Any], second: Mapping[str, Any]) -> float:
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


def _source_span_indexes(
    page: _SourcePage,
    selected_words: Sequence[tuple[int, Mapping[str, Any]]],
) -> tuple[list[int], list[Mapping[str, Any]], str]:
    if not selected_words:
        raise RunningRegionError("extracted source span is empty")
    word_box = _precise_source_bbox([word for _index, word in selected_words])
    character_indexes = [
        index
        for index, character in enumerate(page.chars)
        if _center_inside(character, word_box, tolerance=0.5)
    ]
    while (
        character_indexes
        and str(page.chars[character_indexes[-1]].get("text") or "").isspace()
    ):
        character_indexes.pop()
    while (
        character_indexes
        and str(page.chars[character_indexes[0]].get("text") or "").isspace()
    ):
        character_indexes.pop(0)
    selected_set = set(character_indexes)
    for index in tuple(character_indexes):
        next_index = index + 1
        if next_index >= len(page.chars) or next_index in selected_set:
            continue
        current = page.chars[index]
        following = page.chars[next_index]
        if (
            str(following.get("text") or "").isspace()
            and abs(float(current["top"]) - float(following["top"])) <= 1.0
            and abs(float(current["bottom"]) - float(following["bottom"])) <= 1.0
            and any(selected_index > next_index for selected_index in selected_set)
        ):
            selected_set.add(next_index)
    character_indexes = sorted(selected_set)
    characters = [page.chars[index] for index in character_indexes]
    source_text = " ".join(
        str(word.get("text") or "") for _index, word in selected_words
    )
    if not characters or _normalized_signature(source_text) != _candidate_signature(
        selected_words
    ):
        raise RunningRegionError("extracted source scalar binding differs")
    return character_indexes, characters, source_text


def _canonical_owner_block(
    public_document: Mapping[str, Any], element_id: str
) -> Mapping[str, Any]:
    canonical = public_document.get("canonical_presentation")
    if not isinstance(canonical, Mapping):
        raise RunningRegionError("running-region canonical predecessor is absent")
    matches = [
        block
        for page in canonical.get("pages") or []
        for block in page.get("blocks") or []
        if isinstance(block, Mapping) and block.get("primary_element_id") == element_id
    ]
    if len(matches) != 1:
        raise RunningRegionError("running-region canonical owner differs")
    return matches[0]


def _utf8_offsets(value: str) -> list[int]:
    offsets = [0]
    for character in value:
        offsets.append(offsets[-1] + len(character.encode("utf-8")))
    return offsets


def _utf8_whitespace_ranges(value: str) -> tuple[tuple[int, int], ...]:
    offsets = _utf8_offsets(value)
    return tuple(
        (offsets[match.start()], offsets[match.end()])
        for match in re.finditer(r"\s+", value)
        if match.start() > 0 and match.end() < len(value)
    )


def _whitespace_boundary_indexes(value: str) -> tuple[int, ...]:
    return tuple(
        sum(not character.isspace() for character in value[: match.start()])
        for match in re.finditer(r"\s+", value)
        if match.start() > 0 and match.end() < len(value)
    )


def _plan_ranges(
    values: Any,
    maximum: int,
    *,
    allow_touching: bool,
) -> tuple[tuple[int, int], ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise RunningRegionError("extracted plan ranges differ")
    result: list[tuple[int, int]] = []
    for value in values:
        if (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes, bytearray))
            or len(value) != 2
        ):
            raise RunningRegionError("extracted plan range differs")
        start, end = value
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or not 0 <= start < end <= maximum
        ):
            raise RunningRegionError("extracted plan range differs")
        result.append((start, end))
    if result != sorted(result) or any(
        left[1] > right[0] if allow_touching else left[1] >= right[0]
        for left, right in pairwise(result)
    ):
        raise RunningRegionError("extracted plan ranges overlap/reorder")
    return tuple(result)


def _validate_extracted_plan(plan: Any) -> dict[str, Any]:
    """Execute the complete closed multi-interval plan and its exact inverse."""

    if not isinstance(plan, Mapping) or set(plan) != _EXTRACTED_PLAN_FIELDS:
        raise RunningRegionError("extracted contribution plan differs")
    detached = deepcopy(dict(plan))
    page_index = detached["physical_page_index"]
    if (
        isinstance(page_index, bool)
        or not isinstance(page_index, int)
        or not 1 <= page_index <= MAX_PAGES
        or not isinstance(detached["owner_public_item_id"], str)
        or not detached["owner_public_item_id"]
    ):
        raise RunningRegionError("extracted contribution plan owner differs")
    hash_fields = (
        "owner_sha256_before",
        "owner_sha256_after",
        "source_text_sha256",
        "presentation_text_sha256",
        "predecessor_sha256",
        "ordered_plan_sha256",
        "residual_sha256",
    )
    if (
        any(
            not isinstance(detached[field], str)
            or re.fullmatch(r"[0-9a-f]{64}", detached[field]) is None
            for field in hash_fields
        )
        or detached["owner_sha256_after"] != detached["owner_sha256_before"]
    ):
        raise RunningRegionError("extracted contribution plan hash differs")
    scalar_fields = (
        "predecessor_canonical",
        "source_text",
        "presentation_text",
        "residual_canonical",
    )
    if any(not isinstance(detached[field], str) for field in scalar_fields):
        raise RunningRegionError("extracted contribution plan scalar differs")
    try:
        predecessor = detached["predecessor_canonical"].encode("utf-8")
        source = detached["source_text"].encode("utf-8")
        presentation = detached["presentation_text"].encode("utf-8")
        residual = detached["residual_canonical"].encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RunningRegionError("extracted contribution Unicode differs") from exc
    validate_running_region_resource_count(
        "extracted_contribution_utf8_bytes",
        len(source),
    )
    validate_running_region_resource_count(
        "extracted_contribution_utf8_bytes",
        len(presentation),
    )
    if (
        not source
        or not presentation
        or not residual
        or detached["source_text"] != detached["source_text"].strip()
        or detached["presentation_text"] != detached["presentation_text"].strip()
        or unicodedata.normalize("NFC", detached["source_text"])
        != detached["source_text"]
        or unicodedata.normalize("NFC", detached["presentation_text"])
        != detached["presentation_text"]
    ):
        raise RunningRegionError("extracted contribution text differs")

    intervals_raw = detached["predecessor_intervals"]
    if isinstance(intervals_raw, (str, bytes, bytearray)) or not isinstance(
        intervals_raw, Sequence
    ):
        raise RunningRegionError("extracted contribution intervals differ")
    validate_running_region_resource_count(
        "extracted_intervals_per_contribution",
        len(intervals_raw),
    )
    if not intervals_raw:
        raise RunningRegionError("extracted contribution intervals differ")
    intervals = _plan_ranges(
        intervals_raw,
        len(predecessor),
        allow_touching=False,
    )
    parallel_fields = (
        "presentation_fragments",
        "delimiters",
        "residual_insertion_offsets",
        "source_span_groups",
        "presentation_fragment_sha256",
        "removed_interval_sha256",
        "delimiter_sha256",
    )
    if any(
        isinstance(detached[field], (str, bytes, bytearray))
        or not isinstance(detached[field], Sequence)
        or len(detached[field]) != len(intervals)
        for field in parallel_fields
    ):
        raise RunningRegionError("extracted interval parallel arrays differ")
    fragments = list(detached["presentation_fragments"])
    delimiters = list(detached["delimiters"])
    if (
        any(not isinstance(value, str) for value in fragments)
        or any(value != "\n" for value in delimiters)
        or detached["presentation_text"]
        != "".join(
            fragment + (delimiters[index] if index + 1 < len(fragments) else "")
            for index, fragment in enumerate(fragments)
        )
    ):
        raise RunningRegionError("extracted presentation fragments differ")
    groups_raw = detached["source_span_groups"]
    flattened: list[tuple[int, int]] = []
    normalized_groups: list[list[list[int]]] = []
    for group in groups_raw:
        if (
            isinstance(group, (str, bytes, bytearray))
            or not isinstance(group, Sequence)
            or not group
        ):
            raise RunningRegionError("extracted source span group differs")
        checked = _plan_ranges(group, len(source), allow_touching=True)
        flattened.extend(checked)
        normalized_groups.append([list(value) for value in checked])
    if flattened != sorted(flattened) or any(
        left[1] > right[0] for left, right in pairwise(flattened)
    ):
        raise RunningRegionError("extracted source spans reorder")

    removed: list[bytes] = []
    for index, ((start, end), fragment, delimiter, group) in enumerate(
        zip(intervals, fragments, delimiters, normalized_groups, strict=True)
    ):
        current = predecessor[start:end]
        expected = (fragment + delimiter).encode("utf-8")
        if current != expected or predecessor.count(current) != 1:
            raise RunningRegionError("extracted predecessor fragment is ambiguous")
        try:
            source_fragment = "".join(
                source[span_start:span_end].decode("utf-8")
                for span_start, span_end in group
            )
        except UnicodeDecodeError as exc:
            raise RunningRegionError("extracted source span alignment differs") from exc
        if "".join(source_fragment.split()) != "".join(fragment.split()):
            raise RunningRegionError("extracted source span mapping differs")
        if (
            hashlib.sha256(fragment.encode("utf-8")).hexdigest()
            != detached["presentation_fragment_sha256"][index]
            or hashlib.sha256(current).hexdigest()
            != detached["removed_interval_sha256"][index]
            or hashlib.sha256(delimiter.encode("utf-8")).hexdigest()
            != detached["delimiter_sha256"][index]
        ):
            raise RunningRegionError("extracted interval hash differs")
        removed.append(current)
    mapped_source = b"".join(source[start:end] for start, end in flattened)
    try:
        mapped_text = mapped_source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RunningRegionError("extracted source coverage differs") from exc
    if "".join(mapped_text.split()) != "".join(
        detached["source_text"].split()
    ) or "".join(detached["source_text"].split()) != "".join(
        detached["presentation_text"].split()
    ):
        raise RunningRegionError("extracted scalar mapping differs")

    source_whitespace_ranges = _utf8_whitespace_ranges(detached["source_text"])
    presentation_whitespace_ranges = _utf8_whitespace_ranges(
        detached["presentation_text"]
    )
    if len(source_whitespace_ranges) != len(presentation_whitespace_ranges):
        raise RunningRegionError("extracted whitespace mapping differs")
    expected_whitespace = [
        [*source_range, *presentation_range]
        for source_range, presentation_range in zip(
            source_whitespace_ranges,
            presentation_whitespace_ranges,
            strict=True,
        )
    ]
    if detached[
        "whitespace_mappings"
    ] != expected_whitespace or _whitespace_boundary_indexes(
        detached["source_text"]
    ) != _whitespace_boundary_indexes(detached["presentation_text"]):
        raise RunningRegionError("extracted whitespace mapping differs")

    residual_parts: list[bytes] = []
    insertion_offsets: list[int] = []
    cursor = 0
    residual_size = 0
    for start, end in intervals:
        retained = predecessor[cursor:start]
        residual_parts.append(retained)
        residual_size += len(retained)
        insertion_offsets.append(residual_size)
        cursor = end
    residual_parts.append(predecessor[cursor:])
    expected_residual = b"".join(residual_parts)
    if (
        detached["residual_insertion_offsets"] != insertion_offsets
        or residual != expected_residual
    ):
        raise RunningRegionError("extracted residual plan differs")
    reconstructed: list[bytes] = []
    residual_cursor = 0
    for offset, removed_bytes in zip(insertion_offsets, removed, strict=True):
        reconstructed.extend((residual[residual_cursor:offset], removed_bytes))
        residual_cursor = offset
    reconstructed.append(residual[residual_cursor:])
    if b"".join(reconstructed) != predecessor:
        raise RunningRegionError("extracted inverse reconstruction differs")
    if (
        detached["source_text_sha256"] != hashlib.sha256(source).hexdigest()
        or detached["presentation_text_sha256"]
        != hashlib.sha256(presentation).hexdigest()
        or detached["predecessor_sha256"] != hashlib.sha256(predecessor).hexdigest()
        or detached["residual_sha256"] != hashlib.sha256(residual).hexdigest()
    ):
        raise RunningRegionError("extracted scalar hash differs")
    ordered_payload = {
        "presentation_fragments": fragments,
        "delimiters": delimiters,
        "predecessor_intervals": [list(value) for value in intervals],
        "residual_insertion_offsets": insertion_offsets,
        "source_span_groups": normalized_groups,
        "whitespace_mappings": expected_whitespace,
    }
    if detached["ordered_plan_sha256"] != _sha256_json(ordered_payload):
        raise RunningRegionError("extracted ordered-plan hash differs")
    validate_running_region_resource_count(
        "extracted_residual_plan_bytes_per_page",
        len(_strict_json_bytes(detached)),
    )
    return detached


def _validate_extracted_plan_ledger(plans: Any) -> list[dict[str, Any]]:
    if isinstance(plans, (str, bytes, bytearray)) or not isinstance(plans, Sequence):
        raise RunningRegionError("extracted contribution ledger differs")
    validate_running_region_resource_count(
        "extracted_contributions_per_document",
        len(plans),
    )
    validated: list[dict[str, Any]] = []
    page_counts: dict[int, int] = defaultdict(int)
    page_bytes: dict[int, int] = defaultdict(int)
    document_bytes = 0
    seen_payloads: set[bytes] = set()
    owner_predecessors: dict[tuple[int, str], tuple[str, str, str]] = {}
    owner_intervals: dict[tuple[int, str, str], list[tuple[int, int]]] = defaultdict(
        list
    )
    for raw_plan in plans:
        plan = _validate_extracted_plan(raw_plan)
        serialized = _strict_json_bytes(plan)
        if serialized in seen_payloads:
            raise RunningRegionError("extracted contribution plan repeats")
        seen_payloads.add(serialized)
        page_index = plan["physical_page_index"]
        page_counts[page_index] += 1
        validate_running_region_resource_count(
            "extracted_contributions_per_page",
            page_counts[page_index],
        )
        page_bytes[page_index] += len(serialized)
        validate_running_region_resource_count(
            "extracted_residual_plan_bytes_per_page",
            page_bytes[page_index],
        )
        document_bytes += len(serialized)
        validate_running_region_resource_count(
            "extracted_residual_plan_bytes_per_document",
            document_bytes,
        )
        owner_key = (page_index, plan["owner_public_item_id"])
        predecessor_identity = (
            plan["predecessor_sha256"],
            plan["owner_sha256_before"],
            plan["predecessor_canonical"],
        )
        if (
            owner_key in owner_predecessors
            and owner_predecessors[owner_key] != predecessor_identity
        ):
            raise RunningRegionError("extracted owner predecessor plan differs")
        owner_predecessors[owner_key] = predecessor_identity
        interval_key = (
            page_index,
            plan["owner_public_item_id"],
            plan["predecessor_sha256"],
        )
        owner_intervals[interval_key].extend(
            tuple(value) for value in plan["predecessor_intervals"]
        )
        validated.append(plan)
    for intervals in owner_intervals.values():
        ordered = sorted(intervals)
        if len(ordered) != len(set(ordered)) or any(
            left[1] >= right[0] for left, right in pairwise(ordered)
        ):
            raise RunningRegionError("extracted owner intervals overlap")
    return validated


def _build_extracted_plan(
    *,
    physical_page_index: int,
    owner_public_item: Mapping[str, Any],
    predecessor_canonical: str,
    source_text: str,
    presentation_fragments: Sequence[str],
) -> dict[str, Any]:
    if (
        isinstance(presentation_fragments, (str, bytes, bytearray))
        or not isinstance(presentation_fragments, Sequence)
        or not presentation_fragments
    ):
        raise RunningRegionError("extracted presentation fragments are absent")
    validate_running_region_resource_count(
        "extracted_intervals_per_contribution",
        len(presentation_fragments),
    )
    if not all(isinstance(value, str) and value for value in presentation_fragments):
        raise RunningRegionError("extracted presentation fragments differ")
    predecessor_bytes = predecessor_canonical.encode("utf-8")
    source_bytes = source_text.encode("utf-8")
    validate_running_region_resource_count(
        "extracted_contribution_utf8_bytes",
        len(source_bytes),
    )
    validate_running_region_resource_count(
        "extracted_residual_plan_bytes_per_page",
        len(predecessor_bytes),
    )
    intervals: list[tuple[int, int]] = []
    cursor = 0
    for fragment in presentation_fragments:
        needle = (fragment + "\n").encode("utf-8")
        start = predecessor_bytes.find(needle, cursor)
        if start < 0 or predecessor_bytes.count(needle) != 1:
            raise RunningRegionError("extracted canonical fragment is ambiguous")
        intervals.append((start, start + len(needle)))
        cursor = start + len(needle)
    residual_parts: list[bytes] = []
    insertion_offsets: list[int] = []
    removed: list[bytes] = []
    cursor = 0
    residual_size = 0
    for start, end in intervals:
        retained = predecessor_bytes[cursor:start]
        residual_parts.append(retained)
        residual_size += len(retained)
        insertion_offsets.append(residual_size)
        removed.append(predecessor_bytes[start:end])
        cursor = end
    residual_parts.append(predecessor_bytes[cursor:])
    residual_bytes = b"".join(residual_parts)
    presentation_text = "\n".join(presentation_fragments)
    validate_running_region_resource_count(
        "extracted_contribution_utf8_bytes",
        len(presentation_text.encode("utf-8")),
    )
    source_span_groups: list[list[list[int]]] = []
    source_cursor = 0
    source_offsets = _utf8_offsets(source_text)
    for fragment in presentation_fragments:
        normalized_fragment = " ".join(fragment.split())
        start = source_text.find(normalized_fragment, source_cursor)
        if start < 0:
            raise RunningRegionError("extracted source fragment is ambiguous")
        end = start + len(normalized_fragment)
        source_span_groups.append([[source_offsets[start], source_offsets[end]]])
        source_cursor = end
    source_whitespace = list(_utf8_whitespace_ranges(source_text))
    presentation_whitespace = list(_utf8_whitespace_ranges(presentation_text))
    if len(source_whitespace) != len(presentation_whitespace):
        raise RunningRegionError("extracted whitespace mapping differs")
    whitespace_mappings = [
        [*source_range, *presentation_range]
        for source_range, presentation_range in zip(
            source_whitespace, presentation_whitespace, strict=True
        )
    ]
    delimiters = ["\n" for _fragment in presentation_fragments]
    ordered_payload = {
        "presentation_fragments": list(presentation_fragments),
        "delimiters": delimiters,
        "predecessor_intervals": [list(value) for value in intervals],
        "residual_insertion_offsets": insertion_offsets,
        "source_span_groups": source_span_groups,
        "whitespace_mappings": whitespace_mappings,
    }
    owner_sha256 = _sha256_json(_compact_public_item_payload(owner_public_item))
    plan = {
        "physical_page_index": physical_page_index,
        "owner_public_item_id": str(owner_public_item.get("id") or ""),
        "owner_sha256_before": owner_sha256,
        "owner_sha256_after": owner_sha256,
        "predecessor_canonical": predecessor_canonical,
        "source_text": source_text,
        "presentation_text": presentation_text,
        "presentation_fragments": list(presentation_fragments),
        "delimiters": delimiters,
        "predecessor_intervals": [list(value) for value in intervals],
        "residual_insertion_offsets": insertion_offsets,
        "source_span_groups": source_span_groups,
        "whitespace_mappings": whitespace_mappings,
        "residual_canonical": residual_bytes.decode("utf-8"),
        "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "presentation_text_sha256": hashlib.sha256(
            presentation_text.encode("utf-8")
        ).hexdigest(),
        "predecessor_sha256": hashlib.sha256(predecessor_bytes).hexdigest(),
        "presentation_fragment_sha256": [
            hashlib.sha256(value.encode("utf-8")).hexdigest()
            for value in presentation_fragments
        ],
        "removed_interval_sha256": [
            hashlib.sha256(value).hexdigest() for value in removed
        ],
        "delimiter_sha256": [
            hashlib.sha256(b"\n").hexdigest() for _value in presentation_fragments
        ],
        "ordered_plan_sha256": _sha256_json(ordered_payload),
        "residual_sha256": hashlib.sha256(residual_bytes).hexdigest(),
    }
    return _validate_extracted_plan(plan)


def _line_fragments(
    selected_words: Sequence[tuple[int, Mapping[str, Any]]],
) -> list[str]:
    lines: list[list[str]] = []
    line_tops: list[float] = []
    for _index, word in selected_words:
        top = float(word["top"])
        target = next(
            (
                offset
                for offset, value in enumerate(line_tops)
                if abs(value - top) <= 1.0
            ),
            None,
        )
        if target is None:
            line_tops.append(top)
            lines.append([])
            target = len(lines) - 1
        lines[target].append(str(word.get("text") or ""))
    return [
        " ".join(values) for _top, values in sorted(zip(line_tops, lines, strict=True))
    ]


def _effective_cluster(
    public_page: Mapping[str, Any],
    page_height: float,
    *,
    page_index: int | None = None,
    budget: _ExtractionBudget | None = None,
) -> list[tuple[int, Mapping[str, Any]]]:
    items = public_page.get("items")
    if not isinstance(items, list):
        return []
    eligible: list[tuple[int, Mapping[str, Any]]] = []
    for offset, item in enumerate(items):
        if budget is not None:
            if page_index is None:
                raise RunningRegionError("effective cluster page differs")
            budget.charge_comparisons(page_index)
        if (
            not isinstance(item, Mapping)
            or item.get("type") in {"header", "footer"}
            or _has_prior_semantic_owner(item)
        ):
            continue
        try:
            box = _bbox(item["bbox"])
        except (KeyError, RunningRegionError):
            continue
        if float(box["y"]) >= page_height * 0.70 - 0.001:
            eligible.append((offset, item))
    if len(eligible) < 3:
        return []
    cluster = eligible[-3:]
    if [offset for offset, _item in cluster] != list(
        range(cluster[0][0], cluster[0][0] + len(cluster))
    ):
        return []
    midpoints = [
        float(_bbox(item["bbox"])["y"]) + float(_bbox(item["bbox"])["height"]) / 2
        for _offset, item in cluster
    ]
    if max(midpoints) - min(midpoints) > page_height * 0.02:
        return []
    earlier_bottoms = [
        float(_bbox(item["bbox"])["y"]) + float(_bbox(item["bbox"])["height"])
        for offset, item in enumerate(items)
        if offset < cluster[0][0]
        and isinstance(item, Mapping)
        and isinstance(item.get("bbox"), Mapping)
    ]
    if earlier_bottoms and max(earlier_bottoms) >= min(midpoints):
        return []
    return cluster


def _extract_running_region_source_projection(
    source_pdf_bytes: bytes,
    configured_predecessor: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Fixed generalized extractor used by the factory-issued authority."""

    started_ns = time.perf_counter_ns()
    if not isinstance(source_pdf_bytes, bytes) or not source_pdf_bytes:
        raise RunningRegionError("running-region source PDF differs")
    validate_running_region_resource_count("source_pdf_bytes", len(source_pdf_bytes))
    try:
        with pdfium.PdfDocument(source_pdf_bytes) as visibility_document:
            return _extract_running_region_source_projection_with_visibility(
                source_pdf_bytes,
                configured_predecessor,
                visibility_document=visibility_document,
                started_ns=started_ns,
            )
    except RunningRegionError:
        raise
    except Exception as exc:
        raise RunningRegionError("running-region source PDF is unavailable") from exc


def _extract_running_region_source_projection_with_visibility(
    source_pdf_bytes: bytes,
    configured_predecessor: Mapping[str, Any],
    *,
    visibility_document: Any,
    started_ns: int,
) -> Mapping[str, Any]:
    """Extract with one verified PDFium document shared by label checks."""

    if set(configured_predecessor) != {"public", "ir"}:
        raise RunningRegionError("running-region configured predecessor differs")
    public_document = configured_predecessor["public"]
    ir_payload = configured_predecessor["ir"]
    if not isinstance(public_document, Mapping) or not isinstance(ir_payload, Mapping):
        raise RunningRegionError("running-region configured predecessor differs")
    source_sha256 = hashlib.sha256(source_pdf_bytes).hexdigest()
    if (public_document.get("document") or {}).get("sha256") != source_sha256:
        raise RunningRegionError("running-region source hash differs")
    budget = _ExtractionBudget.start(started_ns)
    source_pages = _read_source_pages(
        source_pdf_bytes,
        pdfium_document=visibility_document,
        budget=budget,
    )
    page_word_indexes = {
        page.page_index: _PageWordIndex.build(page) for page in source_pages
    }
    page_character_indexes: dict[int, _PageCharacterIndex] = {}
    geometry_boundary_cache: dict[tuple[int, int], frozenset[int]] = {}
    public_pages = public_document.get("pages")
    ir_pages = ir_payload.get("pages")
    if (
        not isinstance(public_pages, list)
        or not isinstance(ir_pages, list)
        or len(public_pages) != len(source_pages)
        or len(ir_pages) != len(source_pages)
    ):
        raise RunningRegionError("running-region predecessor page count differs")
    position_elements, _public_elements, _canonical_blocks = _owner_indexes(
        public_document, ir_payload
    )
    bboxes = {
        record["id"]: record
        for record in ir_payload.get("bboxes") or []
        if isinstance(record, Mapping) and isinstance(record.get("id"), str)
    }
    evidence_records = {
        record["id"]: record
        for record in ir_payload.get("evidence") or []
        if isinstance(record, Mapping) and isinstance(record.get("id"), str)
    }
    report_pages: list[dict[str, Any]] = []
    comparisons = budget.comparisons
    candidates_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    candidate_total = 0
    candidate_limited_pages: set[int] = set()
    claimed_positions: set[tuple[int, int]] = set()
    method_proofs: dict[str, Any] = {}
    extracted_plans: list[dict[str, Any]] = []

    def remove_candidate(page_index: int, candidate: Mapping[str, Any]) -> None:
        nonlocal candidate_total
        values = candidates_by_page.get(page_index)
        if values is None or candidate not in values:
            return
        values.remove(candidate)
        candidate_total -= 1
        candidate_id = candidate.get("id")
        if isinstance(candidate_id, str):
            method_proofs.pop(candidate_id, None)
        if candidate.get("source_method") == "extracted_source_contribution":
            owner_key = (page_index, candidate.get("public_item_id"))
            extracted_plans[:] = [
                plan
                for plan in extracted_plans
                if (
                    plan.get("physical_page_index"),
                    plan.get("owner_public_item_id"),
                )
                != owner_key
            ]

    def discard_candidate_page(page_index: int) -> None:
        nonlocal candidate_total
        candidate_limited_pages.add(page_index)
        removed = candidates_by_page.pop(page_index, [])
        candidate_total -= len(removed)
        for candidate in removed:
            candidate_id = candidate.get("id")
            if isinstance(candidate_id, str):
                method_proofs.pop(candidate_id, None)
        removed.clear()
        claimed_positions.difference_update(
            {value for value in claimed_positions if value[0] == page_index}
        )
        extracted_plans[:] = [
            plan
            for plan in extracted_plans
            if plan.get("physical_page_index") != page_index
        ]
        for report_page in report_pages:
            if report_page.get("page_index") == page_index:
                report_page["label_candidates"] = []
                report_page["boundary_candidates"] = []
                report_page["concern_codes"] = ["running_region_candidate_limit"]

    @contextmanager
    def candidate_page_scope(page_index: int) -> Any:
        try:
            yield
        except RunningRegionResourceLimitError as exc:
            if exc.resource_name not in {
                "comparisons_per_page",
                "boundary_candidates_per_page",
                "label_candidates_per_page",
            }:
                raise
            discard_candidate_page(page_index)

    def append_candidate(page_index: int, candidate: dict[str, Any]) -> None:
        nonlocal candidate_total
        validate_running_region_resource_count(
            "boundary_candidates_per_page",
            len(candidates_by_page[page_index]) + 1,
        )
        validate_running_region_resource_count(
            "boundary_candidates_per_document",
            candidate_total + 1,
        )
        candidates_by_page[page_index].append(candidate)
        candidate_total += 1

    # The accepted predecessor roles are the strongest source ownership rule.
    for page, public_page, ir_page in zip(
        source_pages, public_pages, ir_pages, strict=True
    ):
        if (
            public_page.get("page_index") != page.page_index
            or ir_page.get("page_index") != page.page_index
        ):
            raise RunningRegionError("running-region predecessor page identity differs")
        if (
            abs(float(public_page.get("page_width")) - page.width) > 0.001
            or abs(float(public_page.get("page_height")) - page.height) > 0.001
            or public_page.get("unit") != "pt"
        ):
            raise RunningRegionError("running-region predecessor geometry differs")
        items = public_page.get("items")
        if not isinstance(items, list):
            raise RunningRegionError("running-region predecessor items differ")
        if "running_region_source_limit" in page.concern_codes:
            continue
        with candidate_page_scope(page.page_index):
            for item_offset, item in enumerate(items):
                budget.charge_comparisons(page.page_index)
                if not isinstance(item, Mapping) or item.get("type") not in {
                    "header",
                    "footer",
                }:
                    continue
                element = position_elements.get((page.page_index, item_offset))
                if element is None:
                    raise RunningRegionError("running-region public/IR owner differs")
                _bbox_id, owner_box = _element_bbox(element, bboxes, item)
                band = _nominal_band(owner_box, page.height)
                if band is None:
                    continue
                try:
                    candidate = _boundary_candidate(
                        source_sha256=source_sha256,
                        page=page,
                        public_item=item,
                        public_path=_public_owner_path(
                            public_document, page.page_index - 1, item_offset
                        ),
                        element=element,
                        bboxes=bboxes,
                        raw_layout_role="page_header"
                        if item.get("type") == "header"
                        else "page_footer",
                        source_method="trusted_layout_role",
                        boundary_band=band,
                        character_indexes=page_character_indexes,
                        geometry_boundary_cache=geometry_boundary_cache,
                        budget=budget,
                        word_index=page_word_indexes[page.page_index],
                        public_page=public_pages[page.page_index - 1],
                        evidence_records=evidence_records,
                    )
                except _RunningRegionSourceBindingRefusal:
                    continue
                append_candidate(page.page_index, candidate)
                claimed_positions.add((page.page_index, item_offset))

    # A source-visible navigation cue or qualifying bottom-band printed label
    # is independently sufficient even when the predecessor typed its sole
    # owner as ordinary text.  The later label pass still performs rendering,
    # uniqueness, and exact source-span checks before a pending label proof is
    # bound; this pass only establishes the closed boundary owner.
    for page, public_page in zip(source_pages, public_pages, strict=True):
        if (
            "running_region_source_limit" in page.concern_codes
            or page.page_index in candidate_limited_pages
        ):
            continue
        with candidate_page_scope(page.page_index):
            for item_offset, item in enumerate(public_page.get("items") or []):
                budget.charge_comparisons(page.page_index)
                if (
                    (page.page_index, item_offset) in claimed_positions
                    or not isinstance(item, Mapping)
                    or _has_prior_semantic_owner(item)
                    or str(item.get("type") or "").casefold()
                    in _DIRECT_SOURCE_EXCLUDED_OWNER_KINDS
                ):
                    continue
                element = position_elements.get((page.page_index, item_offset))
                if element is None:
                    continue
                try:
                    _bbox_id, owner_box = _element_bbox(
                        element,
                        bboxes,
                        item,
                    )
                except RunningRegionError:
                    continue
                band = _nominal_band(owner_box, page.height)
                if band not in {"top", "bottom"}:
                    continue
                selected = _words_in_bbox(
                    page,
                    owner_box,
                    budget=budget,
                    word_index=page_word_indexes[page.page_index],
                )
                if not selected:
                    continue
                source_text = " ".join(
                    str(word.get("text") or "") for _index, word in selected
                )
                navigation_cue = _navigation_cue_from_text(source_text)
                label_phrases = (
                    _candidate_label_phrases(
                        selected,
                        item.get("value"),
                    )
                    if band == "bottom" and navigation_cue is None
                    else []
                )
                if navigation_cue is None and not label_phrases:
                    continue
                source_method = (
                    "boundary_navigation"
                    if navigation_cue is not None
                    else "printed_label_boundary"
                )
                try:
                    candidate = _boundary_candidate(
                        source_sha256=source_sha256,
                        page=page,
                        public_item=item,
                        public_path=_public_owner_path(
                            public_document,
                            page.page_index - 1,
                            item_offset,
                        ),
                        element=element,
                        bboxes=bboxes,
                        raw_layout_role=None,
                        source_method=source_method,
                        boundary_band=band,
                        character_indexes=page_character_indexes,
                        geometry_boundary_cache=geometry_boundary_cache,
                        budget=budget,
                        word_index=page_word_indexes[page.page_index],
                        public_page=public_page,
                        evidence_records=evidence_records,
                    )
                except _RunningRegionSourceBindingRefusal:
                    continue
                append_candidate(page.page_index, candidate)
                claimed_positions.add((page.page_index, item_offset))
                method_proofs[candidate["id"]] = (
                    {"navigation_cue": navigation_cue}
                    if navigation_cue is not None
                    else {"label_candidate_id": "__pending__"}
                )

    # Exact boundary repetition may correct an otherwise body-typed predecessor.
    repetition_pool: dict[
        tuple[str, str],
        list[
            tuple[
                _SourcePage,
                int,
                Mapping[str, Any],
                Mapping[str, Any],
                Mapping[str, Any],
            ]
        ],
    ] = defaultdict(list)
    for page, public_page in zip(source_pages, public_pages, strict=True):
        if (
            "running_region_source_limit" in page.concern_codes
            or page.page_index in candidate_limited_pages
        ):
            continue
        with candidate_page_scope(page.page_index):
            for item_offset, item in enumerate(public_page.get("items") or []):
                budget.charge_comparisons(page.page_index)
                if (
                    (page.page_index, item_offset) in claimed_positions
                    or not isinstance(item, Mapping)
                    or _has_prior_semantic_owner(item)
                ):
                    continue
                if (
                    str(item.get("type") or "").casefold()
                    in _DIRECT_SOURCE_EXCLUDED_OWNER_KINDS
                ):
                    continue
                # A generic body text line does not become furniture merely because
                # it repeats near a page edge (for example a recurring financial-
                # statement note).  Bare labels and navigation have their own
                # source-bound methods; the repetition correction is reserved for
                # an upstream structural owner such as a mis-typed heading/title.
                if (
                    str(item.get("type") or "").casefold() == "text"
                    and str(item.get("label") or "").casefold() == "text"
                ):
                    continue
                element = position_elements.get((page.page_index, item_offset))
                if element is None:
                    continue
                try:
                    _bbox_id, owner_box = _element_bbox(element, bboxes, item)
                except RunningRegionError:
                    continue
                band = _nominal_band(owner_box, page.height)
                if band not in {"top", "bottom"}:
                    continue
                selected = _words_in_bbox(
                    page,
                    owner_box,
                    budget=budget,
                    word_index=page_word_indexes[page.page_index],
                )
                signature = _normalized_signature(
                    item.get("value")
                    if item.get("value") is not None
                    else item.get("md")
                )
                if signature:
                    repetition_pool[(band, signature)].append(
                        (page, item_offset, item, element, owner_box)
                    )
    repetition_group_count = 0
    for (band, signature), records in sorted(repetition_pool.items()):
        records = [
            record
            for record in records
            if record[0].page_index not in candidate_limited_pages
        ]
        page_indexes = {record[0].page_index for record in records}
        if len(records) < 2 or len(page_indexes) != len(records):
            continue
        validate_running_region_resource_count(
            "repetition_members",
            len(records),
        )
        midpoints = [
            (float(owner_box["y"]) + float(owner_box["height"]) / 2) / page.height
            for page, _offset, _item, _element, owner_box in records
        ]
        intervals = [
            (
                float(owner_box["x"]),
                float(owner_box["x"]) + float(owner_box["width"]),
            )
            for _page, _offset, _item, _element, owner_box in records
        ]
        common_left = max(left for left, _right in intervals)
        common_right = min(right for _left, right in intervals)
        overlap = max(0.0, common_right - common_left)
        if max(midpoints) - min(midpoints) > 0.02 + 1e-9 or any(
            overlap / (right - left) < 0.50 for left, right in intervals
        ):
            continue
        repetition_group_count += 1
        validate_running_region_resource_count(
            "repetition_groups_per_document",
            repetition_group_count,
        )
        for page, item_offset, item, element, _owner_box in records:
            if page.page_index in candidate_limited_pages:
                continue
            with candidate_page_scope(page.page_index):
                candidate = _boundary_candidate(
                    source_sha256=source_sha256,
                    page=page,
                    public_item=item,
                    public_path=_public_owner_path(
                        public_document, page.page_index - 1, item_offset
                    ),
                    element=element,
                    bboxes=bboxes,
                    raw_layout_role=None,
                    source_method="cross_page_repetition",
                    boundary_band=band,
                    character_indexes=page_character_indexes,
                    geometry_boundary_cache=geometry_boundary_cache,
                    signature_override=signature,
                    budget=budget,
                    word_index=page_word_indexes[page.page_index],
                    public_page=public_pages[page.page_index - 1],
                    evidence_records=evidence_records,
                )
                append_candidate(page.page_index, candidate)
                claimed_positions.add((page.page_index, item_offset))

    # A single conservative trailing cluster may extend the effective bottom.
    for page, public_page in zip(source_pages, public_pages, strict=True):
        if (
            "running_region_source_limit" in page.concern_codes
            or page.page_index in candidate_limited_pages
        ):
            continue
        with candidate_page_scope(page.page_index):
            cluster = _effective_cluster(
                public_page,
                page.height,
                page_index=page.page_index,
                budget=budget,
            )
            if not cluster or any(
                (page.page_index, offset) in claimed_positions
                for offset, _item in cluster
            ):
                continue
            cluster_proof_items: list[dict[str, Any]] = []
            for item_offset, item in cluster:
                element = position_elements.get((page.page_index, item_offset))
                if element is None:
                    raise RunningRegionError("effective cluster IR owner differs")
                selected = _words_in_bbox(
                    page,
                    _bbox(item["bbox"]),
                    budget=budget,
                    word_index=page_word_indexes[page.page_index],
                )
                value = " ".join(
                    str(word.get("text") or "") for _index, word in selected
                )
                upper = " ".join(value.upper().split())
                try:
                    normalized_label = _normalize_detected_label(value)
                except RunningRegionError:
                    normalized_label = None
                navigation = upper if upper in _NAVIGATION_CUES else None
                method = (
                    "boundary_navigation"
                    if navigation
                    else "printed_label_boundary"
                    if normalized_label
                    else "effective_boundary_cluster"
                )
                candidate = _boundary_candidate(
                    source_sha256=source_sha256,
                    page=page,
                    public_item=item,
                    public_path=_public_owner_path(
                        public_document, page.page_index - 1, item_offset
                    ),
                    element=element,
                    bboxes=bboxes,
                    raw_layout_role=None,
                    source_method=method,
                    boundary_band="bottom",
                    character_indexes=page_character_indexes,
                    geometry_boundary_cache=geometry_boundary_cache,
                    budget=budget,
                    word_index=page_word_indexes[page.page_index],
                    public_page=public_page,
                    evidence_records=evidence_records,
                )
                append_candidate(page.page_index, candidate)
                claimed_positions.add((page.page_index, item_offset))
                proof_item = {
                    "id": item.get("id"),
                    "presentation_index": int(item.get("reading_order", item_offset)),
                    "bbox": _bbox(item["bbox"]),
                    "navigation_cue": navigation,
                    "normalized_label": normalized_label,
                    "claimed": False,
                }
                cluster_proof_items.append(proof_item)
            remaining = [
                _bbox(item["bbox"])
                for offset, item in enumerate(public_page.get("items") or [])
                if offset < cluster[0][0]
                and isinstance(item, Mapping)
                and isinstance(item.get("bbox"), Mapping)
                and item.get("type") not in {"header", "footer"}
            ]
            cluster_payload = {
                "items": cluster_proof_items,
                "remaining_body_bboxes": remaining,
                "candidate_cut_count": 1,
            }
            for candidate, proof_item in zip(
                candidates_by_page[page.page_index][-len(cluster) :],
                cluster_proof_items,
                strict=True,
            ):
                if candidate["source_method"] == "boundary_navigation":
                    method_proofs[candidate["id"]] = {
                        "navigation_cue": proof_item["navigation_cue"],
                        "effective_cluster": cluster_payload,
                    }
                elif candidate["source_method"] == "printed_label_boundary":
                    method_proofs[candidate["id"]] = {
                        "label_candidate_id": "__pending__",
                        "effective_cluster": cluster_payload,
                    }
                else:
                    method_proofs[candidate["id"]] = cluster_payload

    # Repeated native header text fused into one unique predecessor owner is
    # admitted through the sole extracted-contribution exception.
    direct_top_groups: dict[str, set[int]] = defaultdict(set)
    for page_index, values in candidates_by_page.items():
        for candidate in values:
            if candidate["boundary_band"] == "top" and candidate["source_method"] in {
                "trusted_layout_role",
                "cross_page_repetition",
            }:
                direct_top_groups[candidate["normalized_signature"]].add(page_index)
    for signature, member_pages in sorted(direct_top_groups.items()):
        if len(member_pages) < 2:
            continue
        token_count = len(signature.split())
        for page, public_page in zip(source_pages, public_pages, strict=True):
            if (
                page.page_index in member_pages
                or "running_region_source_limit" in page.concern_codes
                or page.page_index in candidate_limited_pages
            ):
                continue
            with candidate_page_scope(page.page_index):
                matches: list[list[tuple[int, Mapping[str, Any]]]] = []
                indexed_words = list(enumerate(page.words))
                for start in range(max(len(indexed_words) - token_count + 1, 0)):
                    budget.charge_comparisons(page.page_index)
                    window = indexed_words[start : start + token_count]
                    if _candidate_signature(window) != signature:
                        continue
                    contribution_box = _precise_source_bbox(
                        [word for _index, word in window]
                    )
                    if _nominal_band(contribution_box, page.height) != "top":
                        continue
                    matches.append(window)
                if len(matches) != 1:
                    continue
                selected_words = matches[0]
                character_indexes, characters, source_text = _source_span_indexes(
                    page, selected_words
                )
                contribution_box = _precise_source_bbox(characters)
                owners: list[tuple[int, Mapping[str, Any], Mapping[str, Any]]] = []
                for item_offset, item in enumerate(public_page.get("items") or []):
                    budget.charge_comparisons(page.page_index)
                    if not isinstance(item, Mapping):
                        continue
                    element = position_elements.get((page.page_index, item_offset))
                    if element is None:
                        continue
                    try:
                        _owner_bbox_id, owner_box = _element_bbox(element, bboxes, item)
                    except RunningRegionError:
                        continue
                    if (
                        _intersection_area(contribution_box, owner_box)
                        / _area(contribution_box)
                        >= 0.99
                    ):
                        owners.append((item_offset, item, element))
                if len(owners) != 1:
                    continue
                item_offset, owner_item, owner_element = owners[0]
                source_object_ids = [
                    *_character_ids(source_sha256, page.page_index, character_indexes),
                    *_word_ids(
                        source_sha256,
                        page.page_index,
                        [index for index, _word in selected_words],
                    ),
                ]
                source_object_ids = _bounded_references(
                    source_object_ids,
                    "source_object_ids_per_record",
                )
                bbox_id = _stable_id(
                    "running-bbox",
                    POLICY_ID,
                    source_sha256,
                    page.page_index,
                    owner_item.get("id"),
                    source_object_ids,
                    contribution_box,
                    "header",
                )
                element_id = _stable_id(
                    "running-element",
                    POLICY_ID,
                    source_sha256,
                    page.page_index,
                    owner_item.get("id"),
                    source_object_ids,
                    bbox_id,
                    "header",
                )
                evidence_id = _stable_id(
                    "running-region-evidence",
                    POLICY_ID,
                    source_sha256,
                    page.page_index,
                    owner_item.get("id"),
                    source_object_ids,
                    bbox_id,
                    "header",
                )
                synthetic_element = {
                    "id": element_id,
                    "bbox_ids": [bbox_id],
                    "evidence_ids": [evidence_id],
                }
                fragments = _line_fragments(selected_words)
                owner_block = _canonical_owner_block(
                    public_document, str(owner_element["id"])
                )
                predecessor_canonical = str(owner_block.get("text") or "")
                plan = _build_extracted_plan(
                    physical_page_index=page.page_index,
                    owner_public_item=owner_item,
                    predecessor_canonical=predecessor_canonical,
                    source_text=source_text,
                    presentation_fragments=fragments,
                )
                extracted_plans.append(plan)
                candidate = _boundary_candidate(
                    source_sha256=source_sha256,
                    page=page,
                    public_item=owner_item,
                    public_path=_public_owner_path(
                        public_document, page.page_index - 1, item_offset
                    ),
                    element=synthetic_element,
                    bboxes=bboxes,
                    raw_layout_role=None,
                    source_method="extracted_source_contribution",
                    boundary_band="top",
                    character_indexes=page_character_indexes,
                    geometry_boundary_cache=geometry_boundary_cache,
                    box_override=contribution_box,
                    bbox_id_override=bbox_id,
                    evidence_ids_override=[evidence_id],
                    source_object_ids_override=source_object_ids,
                    signature_override=signature,
                    budget=budget,
                    word_index=page_word_indexes[page.page_index],
                )
                append_candidate(page.page_index, candidate)
                method_proofs[candidate["id"]] = {
                    "native_source": True,
                    "evidence_mode": "exact_repetition",
                    "repetition_page_indexes": sorted(member_pages | {page.page_index}),
                    "complete_delimiter_line": True,
                    "scalar_match_count": 1,
                    "intervals_disjoint": True,
                    "owner_kind": owner_item.get("type"),
                }

    total_labels = 0
    total_boundaries = 0
    total_characters = 0
    total_words = 0
    for page, public_page in zip(source_pages, public_pages, strict=True):
        boundaries = candidates_by_page[page.page_index]
        labels: list[dict[str, Any]] = []
        for boundary in boundaries:
            if page.page_index in candidate_limited_pages:
                break
            with candidate_page_scope(page.page_index):
                budget.charge_comparisons(page.page_index)
                selected_words = [
                    (index, page.words[index])
                    for value in boundary["source_object_ids"]
                    if ":word:" in value
                    and (index := int(value.rsplit(":", 1)[1])) < len(page.words)
                ]
                owner = _resolve_path(public_document, boundary["public_path"])
                phrases = _candidate_label_phrases(
                    selected_words,
                    owner.get("value") if isinstance(owner, Mapping) else None,
                )
                if not phrases:
                    continue
                # Bottom-most then right-most is source-order independent and
                # distinguishes the printed folio from dates/note numbers.
                phrases.sort(
                    key=lambda value: (
                        max(float(word["top"]) for word in value[1]),
                        max(float(word["x1"]) for word in value[1]),
                        len(value[0]),
                    ),
                    reverse=True,
                )
                word_indexes, words, visible_text = phrases[0]
                budget.check_deadline(force=True)
                label = _label_candidate(
                    source_pdf_bytes=source_pdf_bytes,
                    source_sha256=source_sha256,
                    page=page,
                    word_indexes=word_indexes,
                    words=words,
                    visible_text=visible_text,
                    visibility_document=visibility_document,
                )
                budget.check_deadline(force=True)
                if label is not None and all(
                    label["id"] != existing["id"] for existing in labels
                ):
                    labels.append(label)
        if page.page_index not in candidate_limited_pages:
            labels.sort(key=lambda value: value["id"])
            with candidate_page_scope(page.page_index):
                validate_running_region_resource_count(
                    "label_candidates_per_page", len(labels)
                )
        if page.page_index in candidate_limited_pages:
            labels.clear()
        for candidate in boundaries:
            if page.page_index in candidate_limited_pages:
                break
            proof = method_proofs.get(candidate["id"])
            if (
                isinstance(proof, dict)
                and proof.get("label_candidate_id") == "__pending__"
            ):
                with candidate_page_scope(page.page_index):
                    matching = [
                        label
                        for label in labels
                        if not (budget.charge_comparisons(page.page_index) or False)
                        if set(
                            value
                            for value in label["source_object_ids"]
                            if ":word:" in value
                        )
                        <= set(candidate["source_object_ids"])
                    ]
                    if len(matching) == 1:
                        proof["label_candidate_id"] = matching[0]["id"]
        unresolved_standalone_labels = [
            candidate
            for candidate in tuple(boundaries)
            if candidate.get("source_method") == "printed_label_boundary"
            and isinstance(
                proof := method_proofs.get(candidate.get("id")),
                Mapping,
            )
            and proof.get("label_candidate_id") == "__pending__"
            and "effective_cluster" not in proof
        ]
        for candidate in unresolved_standalone_labels:
            remove_candidate(page.page_index, candidate)
        if page.page_index in candidate_limited_pages:
            labels.clear()
        concern_codes = (
            ["running_region_candidate_limit"]
            if page.page_index in candidate_limited_pages
            else list(page.concern_codes)
        )
        page_report = {
            "page_index": page.page_index,
            "page_width": page.width,
            "page_height": page.height,
            "unit": "pt",
            "coordinate_system_id": COORDINATE_SYSTEM_ID,
            "source_character_count": len(page.chars),
            "source_word_count": len(page.words),
            "embedded_label": page.embedded_label,
            "label_candidates": labels,
            "boundary_candidates": boundaries,
            "concern_codes": concern_codes,
        }
        report_pages.append(page_report)
        total_labels += len(labels)
        total_boundaries += len(boundaries)
        total_characters += len(page.chars)
        total_words += len(page.words)
    placeholder_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for page_report in report_pages:
        page_index = int(page_report["page_index"])
        if page_index in candidate_limited_pages:
            continue
        label_word_sets = [
            {value for value in label["source_object_ids"] if ":word:" in value}
            for label in page_report["label_candidates"]
        ]
        for boundary in page_report["boundary_candidates"]:
            if page_index in candidate_limited_pages:
                break
            with candidate_page_scope(page_index):
                budget.charge_comparisons(page_index)
                boundary_words = set(boundary["source_object_ids"])
                potentials = [
                    potential
                    for word_set, label in zip(
                        label_word_sets,
                        page_report["label_candidates"],
                        strict=True,
                    )
                    if not (budget.charge_comparisons(page_index) or False)
                    if word_set <= boundary_words
                    and (
                        potential := _page_placeholder_signature(
                            boundary["normalized_signature"], label["visible_text"]
                        )
                    )
                    is not None
                ]
                if len(potentials) == 1:
                    placeholder_groups[
                        (boundary["boundary_band"], potentials[0])
                    ].append(boundary)
    for (_band, potential), members in placeholder_groups.items():
        members = [
            member
            for member in members
            if int(member["public_path"][1]) + 1 not in candidate_limited_pages
        ]
        member_pages = {int(member["public_path"][1]) + 1 for member in members}
        if len(members) >= 2 and len(member_pages) == len(members):
            for member in members:
                member["normalized_signature"] = potential

    # A late page refusal can invalidate evidence that was assembled earlier
    # in the scan.  Close those dependencies before counts or authority data
    # are emitted; no surviving candidate may cite a refused page.
    failed_cluster_payloads = {
        _strict_json_bytes(proof["effective_cluster"])
        for proof in method_proofs.values()
        if isinstance(proof, Mapping)
        and proof.get("label_candidate_id") == "__pending__"
        and isinstance(proof.get("effective_cluster"), Mapping)
    }
    removals: list[tuple[int, Mapping[str, Any]]] = []
    for page_index, candidates in candidates_by_page.items():
        for candidate in candidates:
            proof = method_proofs.get(candidate.get("id"))
            cluster = None
            if isinstance(proof, Mapping):
                if isinstance(proof.get("effective_cluster"), Mapping):
                    cluster = proof["effective_cluster"]
                elif candidate.get("source_method") == "effective_boundary_cluster":
                    cluster = proof
            if (
                isinstance(cluster, Mapping)
                and _strict_json_bytes(cluster) in failed_cluster_payloads
            ):
                removals.append((page_index, candidate))
    for page_index, candidate in removals:
        remove_candidate(page_index, candidate)

    cross_groups: dict[tuple[str, str], list[tuple[int, Mapping[str, Any]]]] = (
        defaultdict(list)
    )
    for page_index, candidates in candidates_by_page.items():
        for candidate in candidates:
            if candidate.get("source_method") == "cross_page_repetition":
                cross_groups[
                    (
                        str(candidate.get("boundary_band")),
                        str(candidate.get("normalized_signature")),
                    )
                ].append((page_index, candidate))
    for members in cross_groups.values():
        if len({page_index for page_index, _candidate in members}) < 2:
            for page_index, candidate in members:
                remove_candidate(page_index, candidate)

    active_direct_pages: dict[str, set[int]] = defaultdict(set)
    for page_index, candidates in candidates_by_page.items():
        for candidate in candidates:
            if candidate.get("boundary_band") == "top" and candidate.get(
                "source_method"
            ) in {"trusted_layout_role", "cross_page_repetition"}:
                active_direct_pages[str(candidate.get("normalized_signature"))].add(
                    page_index
                )
    for page_index, candidates in tuple(candidates_by_page.items()):
        for candidate in tuple(candidates):
            if candidate.get("source_method") != "extracted_source_contribution":
                continue
            member_pages = active_direct_pages.get(
                str(candidate.get("normalized_signature")),
                set(),
            )
            proof = method_proofs.get(candidate.get("id"))
            if len(member_pages) < 2 or not isinstance(proof, dict):
                remove_candidate(page_index, candidate)
                continue
            proof["repetition_page_indexes"] = sorted(member_pages | {page_index})

    total_labels = sum(len(page["label_candidates"]) for page in report_pages)
    total_boundaries = sum(len(page["boundary_candidates"]) for page in report_pages)
    total_characters = sum(page["source_character_count"] for page in report_pages)
    total_words = sum(page["source_word_count"] for page in report_pages)
    if candidate_total != total_boundaries:
        raise RunningRegionError("running-region candidate accounting differs")
    validate_running_region_resource_count(
        "boundary_candidates_per_document", total_boundaries
    )
    elapsed_ms = round(
        validate_running_region_deadline("source_extraction", started_ns) * 1000.0,
        3,
    )
    report = {
        "report_version": REPORT_VERSION,
        "policy_id": POLICY_ID,
        "source_sha256": source_sha256,
        "status": "available",
        "pages": report_pages,
        "counts": {
            "page_count": len(report_pages),
            "source_character_count": total_characters,
            "source_word_count": total_words,
            "embedded_label_count": sum(
                page.embedded_label is not None for page in source_pages
            ),
            "label_candidate_count": total_labels,
            "boundary_candidate_count": total_boundaries,
            "concern_count": sum(
                len(page["concern_codes"])
                + sum(
                    len(candidate["concern_codes"])
                    for candidate in (
                        *page["label_candidates"],
                        *page["boundary_candidates"],
                    )
                )
                for page in report_pages
            ),
        },
        "concern_codes": [],
        "extraction_ms": elapsed_ms,
    }
    validate_running_region_resource_count(
        "report_json_bytes", len(_strict_json_bytes(report))
    )
    ledger = [
        {
            "page_index": page.page_index,
            "comparison_count": max(comparisons[page.page_index], 1),
        }
        for page in source_pages
    ]
    for value in ledger:
        validate_running_region_resource_count(
            "comparisons_per_page", value["comparison_count"]
        )
    validate_running_region_resource_count(
        "comparisons_per_document",
        sum(value["comparison_count"] for value in ledger),
    )
    extracted_plans = _validate_extracted_plan_ledger(extracted_plans)
    return {
        "source_report": report,
        "extracted_plans": extracted_plans,
        "comparison_ledger": ledger,
        "method_proofs": method_proofs,
    }


def extract_running_region_source_projection(
    source_pdf_bytes: bytes,
    predecessor_public: Mapping[str, Any],
    predecessor_ir: DocumentIR | Mapping[str, Any],
) -> Mapping[str, Any]:
    """Public diagnostic extractor; its result alone never authorizes projection."""

    return _extract_running_region_source_projection(
        source_pdf_bytes,
        _configured_bundle(predecessor_public, predecessor_ir),
    )


def _validate_authority_concern_codes(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or any(
            not isinstance(code, str) or code not in _CONCERN_CODES for code in value
        )
        or len(value) != len(set(value))
    ):
        raise RunningRegionError("source projection concern codes differ")
    return value


def _validate_authority_bbox(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "x",
        "y",
        "width",
        "height",
        "unit",
    }:
        raise RunningRegionError("source projection bbox differs")
    coordinates = [value.get(key) for key in ("x", "y", "width", "height")]
    if (
        value.get("unit") != "pt"
        or any(
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(float(number))
            for number in coordinates
        )
        or float(value["width"]) <= 0
        or float(value["height"]) <= 0
    ):
        raise RunningRegionError("source projection bbox differs")
    return value


def _validate_authority_source_references(
    values: Any,
    *,
    source_sha256: str,
    page_index: int,
    character_count: int,
    word_count: int,
) -> list[str]:
    references = _bounded_references(
        values,
        "source_object_ids_per_record",
    )
    prefix = f"pdfplumber:{source_sha256}:page:{page_index}:"
    for reference in references:
        if not reference.startswith(prefix):
            raise RunningRegionError("source projection source reference differs")
        suffix = reference[len(prefix) :]
        match = re.fullmatch(r"(character|word):(0|[1-9][0-9]*)", suffix)
        if match is None:
            raise RunningRegionError("source projection source reference differs")
        index = int(match.group(2))
        maximum = character_count if match.group(1) == "character" else word_count
        if index >= maximum:
            raise RunningRegionError("source projection source reference differs")
    return references


def _validate_authority_confidence(value: Any) -> None:
    if value != _confidence():
        raise RunningRegionError("source projection confidence differs")


def _validate_authority_effective_cluster(
    cluster: Any,
    *,
    page_index: int,
    public_document: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if (
        not isinstance(cluster, Mapping)
        or set(cluster)
        != {
            "items",
            "remaining_body_bboxes",
            "candidate_cut_count",
        }
        or cluster.get("candidate_cut_count") != 1
    ):
        raise RunningRegionError("source projection effective cluster differs")
    items = cluster.get("items")
    remaining = cluster.get("remaining_body_bboxes")
    if not isinstance(items, list) or len(items) < 3 or not isinstance(remaining, list):
        raise RunningRegionError("source projection effective cluster differs")
    public_pages = public_document.get("pages")
    if not isinstance(public_pages, list) or page_index > len(public_pages):
        raise RunningRegionError("source projection effective cluster differs")
    public_items = public_pages[page_index - 1].get("items")
    if not isinstance(public_items, list):
        raise RunningRegionError("source projection effective cluster differs")
    item_offsets = {
        str(item.get("id")): offset
        for offset, item in enumerate(public_items)
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    indexes: list[int] = []
    boxes: list[Mapping[str, Any]] = []
    navigation_count = 0
    label_count = 0
    cluster_ids: list[str] = []
    for proof_item in items:
        if not isinstance(proof_item, Mapping) or set(proof_item) != {
            "id",
            "presentation_index",
            "bbox",
            "navigation_cue",
            "normalized_label",
            "claimed",
        }:
            raise RunningRegionError("source projection effective cluster item differs")
        item_id = proof_item.get("id")
        presentation_index = proof_item.get("presentation_index")
        if (
            not isinstance(item_id, str)
            or item_id not in item_offsets
            or isinstance(presentation_index, bool)
            or not isinstance(presentation_index, int)
            or proof_item.get("claimed") is not False
        ):
            raise RunningRegionError("source projection effective cluster item differs")
        owner = public_items[item_offsets[item_id]]
        if _bbox(owner.get("bbox") or {}) != _bbox(proof_item.get("bbox") or {}):
            raise RunningRegionError("source projection effective cluster bbox differs")
        cue = proof_item.get("navigation_cue")
        label = proof_item.get("normalized_label")
        if cue is not None and cue not in _NAVIGATION_CUES:
            raise RunningRegionError("source projection navigation proof differs")
        if label is not None and (
            not isinstance(label, str) or _normalize_detected_label(label) != label
        ):
            raise RunningRegionError("source projection label proof differs")
        navigation_count += cue is not None
        label_count += label is not None
        indexes.append(presentation_index)
        boxes.append(_validate_authority_bbox(proof_item["bbox"]))
        cluster_ids.append(item_id)
    if (
        len(cluster_ids) != len(set(cluster_ids))
        or indexes != list(range(indexes[0], indexes[0] + len(indexes)))
        or navigation_count != 1
        or label_count != 1
    ):
        raise RunningRegionError("source projection effective cluster differs")
    ordered_boxes = sorted(boxes, key=lambda box: float(box["x"]))
    if any(
        float(left["x"]) + float(left["width"]) > float(right["x"]) + 0.001
        for left, right in pairwise(ordered_boxes)
    ):
        raise RunningRegionError("source projection effective cluster overlaps")
    for box in remaining:
        _validate_authority_bbox(box)
    if remaining and max(
        float(box["y"]) + float(box["height"]) for box in remaining
    ) >= min(float(box["y"]) for box in boxes):
        raise RunningRegionError("source projection effective cluster gap differs")
    candidate_ids = {
        str(candidate.get("public_item_id"))
        for candidate in candidates
        if candidate.get("source_method")
        in {
            "boundary_navigation",
            "printed_label_boundary",
            "effective_boundary_cluster",
        }
        and candidate.get("public_item_id") in set(cluster_ids)
    }
    if set(cluster_ids) != candidate_ids:
        raise RunningRegionError("source projection effective cluster closure differs")
    return cluster


def _validate_authority_payload(
    report: Any,
    plans: Any,
    ledger: Any,
    proofs: Any,
    *,
    source_sha256: str,
    public_document: Mapping[str, Any],
    ir_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Validate the complete closed authority graph before use or issuance."""

    if not isinstance(report, Mapping) or set(report) != _SOURCE_REPORT_FIELDS:
        raise RunningRegionError("source projection report shape differs")
    extraction_ms = report.get("extraction_ms")
    if (
        report.get("report_version") != REPORT_VERSION
        or report.get("policy_id") != POLICY_ID
        or report.get("source_sha256") != source_sha256
        or report.get("status") != "available"
        or not isinstance(report.get("pages"), list)
        or not isinstance(report.get("counts"), Mapping)
        or set(report["counts"]) != _SOURCE_COUNT_FIELDS
        or isinstance(extraction_ms, bool)
        or not isinstance(extraction_ms, (int, float))
        or not math.isfinite(float(extraction_ms))
        or not 0 <= float(extraction_ms) <= SOURCE_EXTRACTION_DEADLINE_SECONDS * 1000
        or abs(round(float(extraction_ms), 3) - float(extraction_ms)) > 1e-9
    ):
        raise RunningRegionError("source projection report differs")
    document_concerns = _validate_authority_concern_codes(report.get("concern_codes"))
    if document_concerns:
        raise RunningRegionError("source projection document concern differs")
    public_pages = public_document.get("pages")
    ir_pages = ir_payload.get("pages")
    if (
        not isinstance(public_pages, list)
        or not isinstance(ir_pages, list)
        or len(report["pages"]) != len(public_pages)
        or len(report["pages"]) != len(ir_pages)
        or not 1 <= len(report["pages"]) <= MAX_PAGES
    ):
        raise RunningRegionError("source projection page coverage differs")
    _positions, public_elements, _canonical_blocks = _owner_indexes(
        public_document,
        ir_payload,
    )
    bboxes = {
        record.get("id"): record
        for record in ir_payload.get("bboxes") or []
        if isinstance(record, Mapping) and isinstance(record.get("id"), str)
    }
    evidence = {
        record.get("id"): record
        for record in ir_payload.get("evidence") or []
        if isinstance(record, Mapping) and isinstance(record.get("id"), str)
    }
    label_by_id: dict[str, tuple[int, Mapping[str, Any]]] = {}
    boundary_by_id: dict[str, tuple[int, Mapping[str, Any]]] = {}
    extracted_candidates: dict[tuple[int, str], Mapping[str, Any]] = {}
    source_character_total = 0
    source_word_total = 0
    label_total = 0
    boundary_total = 0
    concern_total = 0

    for page_offset, (report_page, public_page, ir_page) in enumerate(
        zip(report["pages"], public_pages, ir_pages, strict=True)
    ):
        page_index = page_offset + 1
        if (
            not isinstance(report_page, Mapping)
            or set(report_page) != _SOURCE_PAGE_FIELDS
        ):
            raise RunningRegionError("source projection page shape differs")
        if (
            report_page.get("page_index") != page_index
            or not isinstance(public_page, Mapping)
            or public_page.get("page_index") != page_index
            or not isinstance(ir_page, Mapping)
            or ir_page.get("page_index") != page_index
            or report_page.get("unit") != "pt"
            or report_page.get("coordinate_system_id") != COORDINATE_SYSTEM_ID
        ):
            raise RunningRegionError("source projection page binding differs")
        width = report_page.get("page_width")
        height = report_page.get("page_height")
        if (
            any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
                for value in (width, height)
            )
            or abs(float(width) - float(public_page.get("page_width"))) > 0.001
            or abs(float(height) - float(public_page.get("page_height"))) > 0.001
        ):
            raise RunningRegionError("source projection page geometry differs")
        character_count = report_page.get("source_character_count")
        word_count = report_page.get("source_word_count")
        validate_running_region_resource_count(
            "source_characters_per_page", character_count
        )
        validate_running_region_resource_count("source_words_per_page", word_count)
        embedded_label = report_page.get("embedded_label")
        if embedded_label is not None and (
            not isinstance(embedded_label, str)
            or _normalize_embedded_label(embedded_label) != embedded_label
        ):
            raise RunningRegionError("source projection embedded label differs")
        labels = report_page.get("label_candidates")
        boundaries = report_page.get("boundary_candidates")
        if not isinstance(labels, list) or not isinstance(boundaries, list):
            raise RunningRegionError("source projection page candidates differ")
        validate_running_region_resource_count("label_candidates_per_page", len(labels))
        validate_running_region_resource_count(
            "boundary_candidates_per_page", len(boundaries)
        )
        page_concerns = _validate_authority_concern_codes(
            report_page.get("concern_codes")
        )
        if any(
            code in page_concerns
            for code in {
                "running_region_source_limit",
                "running_region_candidate_limit",
            }
        ) and (len(page_concerns) != 1 or labels or boundaries):
            raise RunningRegionError("source projection limited page differs")

        for label in labels:
            if not isinstance(label, Mapping) or set(label) != _LABEL_CANDIDATE_FIELDS:
                raise RunningRegionError("source projection label shape differs")
            label_id = label.get("id")
            visible = label.get("visible_text")
            normalized = label.get("normalized_label")
            if (
                not isinstance(label_id, str)
                or not label_id
                or label_id in label_by_id
                or not isinstance(visible, str)
                or not visible
                or not isinstance(normalized, str)
                or _normalize_detected_label(visible) != normalized
                or label.get("source_method") != "native_printed_label"
            ):
                raise RunningRegionError("source projection label differs")
            box = _validate_authority_bbox(label.get("bbox"))
            references = _validate_authority_source_references(
                label.get("source_object_ids"),
                source_sha256=source_sha256,
                page_index=page_index,
                character_count=character_count,
                word_count=word_count,
            )
            if (
                not any(":character:" in value for value in references)
                or not any(":word:" in value for value in references)
                or label_id
                != _stable_id(
                    "label-candidate",
                    POLICY_ID,
                    source_sha256,
                    page_index,
                    references,
                    box,
                )
            ):
                raise RunningRegionError("source projection label custody differs")
            _validate_authority_confidence(label.get("confidence"))
            _validate_authority_concern_codes(label.get("concern_codes"))
            label_by_id[label_id] = (page_index, label)

        for candidate in boundaries:
            if (
                not isinstance(candidate, Mapping)
                or set(candidate) != _BOUNDARY_CANDIDATE_FIELDS
            ):
                raise RunningRegionError("source projection candidate shape differs")
            candidate_id = candidate.get("id")
            method = candidate.get("source_method")
            band = candidate.get("boundary_band")
            if (
                not isinstance(candidate_id, str)
                or not candidate_id
                or candidate_id in boundary_by_id
                or method
                not in {
                    "trusted_layout_role",
                    "cross_page_repetition",
                    "boundary_navigation",
                    "printed_label_boundary",
                    "effective_boundary_cluster",
                    "extracted_source_contribution",
                }
                or band not in {"top", "bottom"}
                or candidate.get("disposition") != "accepted"
                or not isinstance(candidate.get("normalized_signature"), str)
                or not candidate.get("normalized_signature")
            ):
                raise RunningRegionError("source projection candidate differs")
            path = candidate.get("public_path")
            if (
                not isinstance(path, list)
                or path[:3] != ["pages", page_offset, "items"]
                or len(path) != 4
                or isinstance(path[3], bool)
                or not isinstance(path[3], int)
            ):
                raise RunningRegionError("source projection candidate path differs")
            owner = _resolve_path(public_document, path)
            public_item_id = candidate.get("public_item_id")
            if (
                not isinstance(owner, Mapping)
                or owner.get("id") != public_item_id
                or candidate.get("predecessor_type") != owner.get("type")
            ):
                raise RunningRegionError("source projection candidate owner differs")
            box = _validate_authority_bbox(candidate.get("bbox"))
            references = _validate_authority_source_references(
                candidate.get("source_object_ids"),
                source_sha256=source_sha256,
                page_index=page_index,
                character_count=character_count,
                word_count=word_count,
            )
            evidence_ids = _bounded_references(
                candidate.get("evidence_ids"),
                "evidence_ids_per_record",
            )
            raw_role = candidate.get("raw_layout_role")
            if method == "trusted_layout_role":
                expected_raw = "page_header" if band == "top" else "page_footer"
                if raw_role != expected_raw:
                    raise RunningRegionError("source projection trusted role differs")
            elif raw_role is not None:
                raise RunningRegionError("source projection raw role differs")
            owner_element = public_elements.get((page_index, str(public_item_id)))
            if owner_element is None:
                raise RunningRegionError("source projection candidate IR owner differs")
            if method == "extracted_source_contribution":
                if band != "top" or not any(
                    ":character:" in value for value in references
                ):
                    raise RunningRegionError(
                        "source projection extracted candidate differs"
                    )
                expected_bbox_id = _stable_id(
                    "running-bbox",
                    POLICY_ID,
                    source_sha256,
                    page_index,
                    public_item_id,
                    references,
                    box,
                    "header",
                )
                expected_element_id = _stable_id(
                    "running-element",
                    POLICY_ID,
                    source_sha256,
                    page_index,
                    public_item_id,
                    references,
                    expected_bbox_id,
                    "header",
                )
                expected_evidence_id = _stable_id(
                    "running-region-evidence",
                    POLICY_ID,
                    source_sha256,
                    page_index,
                    public_item_id,
                    references,
                    expected_bbox_id,
                    "header",
                )
                if (
                    candidate.get("bbox_id") != expected_bbox_id
                    or candidate.get("element_id") != expected_element_id
                    or evidence_ids != [expected_evidence_id]
                ):
                    raise RunningRegionError(
                        "source projection extracted custody differs"
                    )
                owner_key = (page_index, str(public_item_id))
                if owner_key in extracted_candidates:
                    raise RunningRegionError(
                        "source projection extracted owner repeats"
                    )
                extracted_candidates[owner_key] = candidate
            else:
                try:
                    expected_bbox_id, expected_box = _element_bbox(
                        owner_element,
                        bboxes,
                        owner,
                    )
                except RunningRegionError:
                    raise
                expected_evidence_ids = _direct_candidate_evidence_ids(
                    element=owner_element,
                    bbox_id=expected_bbox_id,
                    evidence_records=evidence,
                )
                if (
                    candidate.get("element_id") != owner_element.get("id")
                    or candidate.get("bbox_id") != expected_bbox_id
                    or box != expected_box
                    or evidence_ids != expected_evidence_ids
                    or any(value not in evidence for value in evidence_ids)
                ):
                    raise RunningRegionError("source projection direct custody differs")
            expected_candidate_id = _stable_id(
                "boundary-candidate",
                POLICY_ID,
                source_sha256,
                page_index,
                public_item_id,
                path,
                candidate.get("element_id"),
                candidate.get("bbox_id"),
                evidence_ids,
                references,
                band,
                method,
            )
            if candidate_id != expected_candidate_id:
                raise RunningRegionError("source projection candidate ID differs")
            _validate_authority_confidence(candidate.get("confidence"))
            _validate_authority_concern_codes(candidate.get("concern_codes"))
            boundary_by_id[candidate_id] = (page_index, candidate)

        source_character_total += character_count
        source_word_total += word_count
        label_total += len(labels)
        boundary_total += len(boundaries)
        concern_total += len(page_concerns) + sum(
            len(candidate["concern_codes"]) for candidate in (*labels, *boundaries)
        )

    validate_running_region_resource_count(
        "source_characters_per_document", source_character_total
    )
    validate_running_region_resource_count(
        "source_words_per_document", source_word_total
    )
    validate_running_region_resource_count(
        "boundary_candidates_per_document", boundary_total
    )
    expected_counts = {
        "page_count": len(report["pages"]),
        "source_character_count": source_character_total,
        "source_word_count": source_word_total,
        "embedded_label_count": sum(
            page.get("embedded_label") is not None for page in report["pages"]
        ),
        "label_candidate_count": label_total,
        "boundary_candidate_count": boundary_total,
        "concern_count": concern_total,
    }
    if dict(report["counts"]) != expected_counts:
        raise RunningRegionError("source projection report counts differ")

    if not isinstance(ledger, list) or len(ledger) != len(report["pages"]):
        raise RunningRegionError("source projection comparison ledger differs")
    comparison_total = 0
    for page_index, entry in enumerate(ledger, start=1):
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"page_index", "comparison_count"}
            or entry.get("page_index") != page_index
            or isinstance(entry.get("comparison_count"), bool)
            or not isinstance(entry.get("comparison_count"), int)
            or not 1 <= entry["comparison_count"] <= MAX_COMPARISONS_PER_PAGE
        ):
            raise RunningRegionError("source projection comparison ledger differs")
        comparison_total += entry["comparison_count"]
    validate_running_region_resource_count("comparisons_per_document", comparison_total)

    validated_plans = _validate_extracted_plan_ledger(plans)
    plan_by_owner = {
        (plan["physical_page_index"], plan["owner_public_item_id"]): plan
        for plan in validated_plans
    }
    if set(plan_by_owner) != set(extracted_candidates):
        raise RunningRegionError("source projection extracted plan closure differs")

    if not isinstance(proofs, Mapping) or any(
        not isinstance(key, str) for key in proofs
    ):
        raise RunningRegionError("source projection method proofs differ")
    proof_methods = {
        "boundary_navigation",
        "printed_label_boundary",
        "effective_boundary_cluster",
        "extracted_source_contribution",
    }
    expected_proof_ids = {
        candidate_id
        for candidate_id, (_page_index, candidate) in boundary_by_id.items()
        if candidate.get("source_method") in proof_methods
    }
    if set(proofs) != expected_proof_ids:
        raise RunningRegionError("source projection method proof closure differs")

    cluster_payloads: dict[tuple[int, bytes], Mapping[str, Any]] = {}
    direct_top_pages: dict[str, set[int]] = defaultdict(set)
    for page_index, candidate in boundary_by_id.values():
        if candidate.get("boundary_band") == "top" and candidate.get(
            "source_method"
        ) in {"trusted_layout_role", "cross_page_repetition"}:
            direct_top_pages[str(candidate.get("normalized_signature"))].add(page_index)
    for candidate_id, (page_index, candidate) in boundary_by_id.items():
        method = candidate.get("source_method")
        if method not in proof_methods:
            continue
        proof = proofs[candidate_id]
        if not isinstance(proof, Mapping):
            raise RunningRegionError("source projection method proof differs")
        if method == "extracted_source_contribution":
            if set(proof) != {
                "native_source",
                "evidence_mode",
                "repetition_page_indexes",
                "complete_delimiter_line",
                "scalar_match_count",
                "intervals_disjoint",
                "owner_kind",
            }:
                raise RunningRegionError(
                    "source projection extracted proof shape differs"
                )
            expected_pages = sorted(
                direct_top_pages.get(str(candidate.get("normalized_signature")), set())
                | {page_index}
            )
            owner = _resolve_path(public_document, candidate["public_path"])
            if (
                proof.get("native_source") is not True
                or proof.get("evidence_mode") != "exact_repetition"
                or proof.get("repetition_page_indexes") != expected_pages
                or len(expected_pages) < 3
                or proof.get("complete_delimiter_line") is not True
                or proof.get("scalar_match_count") != 1
                or proof.get("intervals_disjoint") is not True
                or proof.get("owner_kind") != owner.get("type")
            ):
                raise RunningRegionError("source projection extracted proof differs")
            continue
        if method == "effective_boundary_cluster":
            if set(proof) != {
                "items",
                "remaining_body_bboxes",
                "candidate_cut_count",
            }:
                raise RunningRegionError(
                    "source projection effective proof shape differs"
                )
            cluster = proof
        elif method == "boundary_navigation":
            if (
                set(proof)
                not in (
                    {"navigation_cue"},
                    {"navigation_cue", "effective_cluster"},
                )
                or proof.get("navigation_cue") not in _NAVIGATION_CUES
            ):
                raise RunningRegionError("source projection navigation proof differs")
            cluster = proof.get("effective_cluster")
            if cluster is None:
                continue
        else:
            if set(proof) not in (
                {"label_candidate_id"},
                {"label_candidate_id", "effective_cluster"},
            ):
                raise RunningRegionError("source projection label proof shape differs")
            label_record = label_by_id.get(str(proof.get("label_candidate_id")))
            if label_record is None or label_record[0] != page_index:
                raise RunningRegionError("source projection label proof differs")
            label_words = {
                value
                for value in label_record[1]["source_object_ids"]
                if ":word:" in value
            }
            if not label_words <= set(candidate["source_object_ids"]):
                raise RunningRegionError(
                    "source projection label proof custody differs"
                )
            cluster = proof.get("effective_cluster")
            if cluster is None:
                continue
        validated_cluster = _validate_authority_effective_cluster(
            cluster,
            page_index=page_index,
            public_document=public_document,
            candidates=[
                value
                for candidate_page, value in boundary_by_id.values()
                if candidate_page == page_index
            ],
        )
        cluster_payloads[(page_index, _strict_json_bytes(validated_cluster))] = (
            validated_cluster
        )

    for (page_index, payload_bytes), cluster in cluster_payloads.items():
        cluster_candidate_ids = {str(item["id"]) for item in cluster["items"]}
        for candidate_id, (candidate_page, candidate) in boundary_by_id.items():
            if (
                candidate_page != page_index
                or candidate.get("public_item_id") not in cluster_candidate_ids
            ):
                continue
            proof = proofs.get(candidate_id)
            if candidate.get("source_method") == "effective_boundary_cluster":
                candidate_cluster = proof
            else:
                candidate_cluster = proof.get("effective_cluster")
            if _strict_json_bytes(candidate_cluster) != payload_bytes:
                raise RunningRegionError("source projection cluster proof differs")
    return validated_plans


def _authority_owner_bindings(
    report: Mapping[str, Any],
    public_document: Mapping[str, Any],
    ir_payload: Mapping[str, Any],
) -> bytes:
    _positions, public_elements, canonical_blocks = _owner_indexes(
        public_document, ir_payload
    )
    bindings: list[dict[str, Any]] = []
    for report_page in report.get("pages") or []:
        page_index = report_page.get("page_index")
        for candidate in report_page.get("boundary_candidates") or []:
            if not isinstance(candidate, Mapping):
                raise RunningRegionError("source projection candidate differs")
            owner = _resolve_path(public_document, candidate.get("public_path") or ())
            public_item_id = candidate.get("public_item_id")
            if not isinstance(owner, Mapping) or owner.get("id") != public_item_id:
                raise RunningRegionError("source projection public owner differs")
            owner_element = public_elements.get((int(page_index), str(public_item_id)))
            if owner_element is None:
                raise RunningRegionError("source projection IR owner differs")
            if candidate.get("source_method") != "extracted_source_contribution" and (
                candidate.get("element_id") != owner_element.get("id")
                or candidate.get("bbox_id") not in (owner_element.get("bbox_ids") or ())
            ):
                raise RunningRegionError("source projection direct IR binding differs")
            canonical_block_id = canonical_blocks.get(str(owner_element.get("id")))
            if canonical_block_id is None:
                raise RunningRegionError("source projection canonical owner differs")
            bindings.append(
                {
                    "candidate_id": candidate.get("id"),
                    "page_index": page_index,
                    "public_item_id": public_item_id,
                    "public_path": list(candidate.get("public_path") or ()),
                    "ir_element_id": owner_element.get("id"),
                    "canonical_block_id": canonical_block_id,
                }
            )
    if len(bindings) > MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT or len(
        {value["candidate_id"] for value in bindings}
    ) != len(bindings):
        raise RunningRegionError("source projection owner bindings differ")
    return _strict_json_bytes({"bindings": bindings})


def prepare_source_projection_authority(
    configured_predecessor: Mapping[str, Any],
    source_pdf_bytes: bytes,
) -> _ValidatedSourceProjectionAuthority:
    """Run the fixed extractor twice and issue an opaque exact-state authority."""

    try:
        validate_running_region_resource_count(
            "live_source_projection_authorities", len(_ISSUED_AUTHORITIES) + 1
        )
    except RunningRegionResourceLimitError as exc:
        raise RunningRegionSourceOutcomeError("running_region_source_limit") from exc
    if not isinstance(configured_predecessor, Mapping) or set(
        configured_predecessor
    ) != {"public", "ir"}:
        raise RunningRegionError("source projection configured predecessor differs")
    if not isinstance(source_pdf_bytes, bytes) or not source_pdf_bytes:
        raise RunningRegionSourceOutcomeError(
            "running_region_source_evidence_unavailable"
        )
    try:
        validate_running_region_resource_count(
            "source_pdf_bytes", len(source_pdf_bytes)
        )
    except RunningRegionResourceLimitError as exc:
        raise RunningRegionSourceOutcomeError("running_region_source_limit") from exc
    public_document = configured_predecessor.get("public")
    ir_payload = configured_predecessor.get("ir")
    if not isinstance(public_document, Mapping) or not isinstance(ir_payload, Mapping):
        raise RunningRegionError("source projection configured predecessor differs")
    validated_ir = DocumentIR.model_validate(ir_payload)
    ir_payload = validated_ir.model_dump(mode="json", exclude_none=True)
    try:
        public_template = json.loads(_strict_json_bytes(public_document))
        predecessor_template_pickle = pickle.dumps(
            (public_template, validated_ir),
            protocol=pickle.HIGHEST_PROTOCOL,
        )
        predecessor_public_typed_json = to_json(public_document)
        predecessor_ir_typed_json = validated_ir.__pydantic_serializer__.to_json(
            validated_ir,
            exclude_none=True,
            serialize_as_any=True,
            warnings="error",
        )
    except (
        PydanticSerializationError,
        RecursionError,
        TypeError,
        ValueError,
        pickle.PickleError,
    ) as exc:
        raise RunningRegionError(
            "source projection configured predecessor differs"
        ) from exc
    try:
        validate_running_region_resource_count(
            "source_pdf_bytes",
            len(predecessor_template_pickle)
            + len(predecessor_public_typed_json)
            + len(predecessor_ir_typed_json),
        )
    except RunningRegionResourceLimitError as exc:
        raise RunningRegionSourceOutcomeError("running_region_source_limit") from exc
    snapshot = {"public": public_template, "ir": ir_payload}
    if not isinstance(public_document.get("canonical_presentation"), Mapping):
        raise RunningRegionError("source projection canonical predecessor is absent")
    source_sha256 = hashlib.sha256(source_pdf_bytes).hexdigest()
    if (public_document.get("document") or {}).get(
        "sha256"
    ) != source_sha256 or validated_ir.source_sha256 != source_sha256:
        raise RunningRegionError("source projection PDF/configured source hash differs")
    predecessor_sha256 = _sha256_json(snapshot)

    extracted: list[Mapping[str, Any]] = []
    for _run in range(2):
        try:
            result = _extract_running_region_source_projection(
                source_pdf_bytes, snapshot
            )
        except RunningRegionSourceOutcomeError:
            raise
        except RunningRegionResourceLimitError as exc:
            raise RunningRegionSourceOutcomeError(
                "running_region_source_limit"
            ) from exc
        except RunningRegionError as exc:
            raise RunningRegionSourceOutcomeError(
                "running_region_source_evidence_unavailable"
            ) from exc
        except Exception as exc:
            raise RunningRegionSourceOutcomeError(
                "running_region_source_evidence_unavailable"
            ) from exc
        if not isinstance(result, Mapping) or set(result) != {
            "source_report",
            "extracted_plans",
            "comparison_ledger",
            "method_proofs",
        }:
            raise RunningRegionSourceOutcomeError(
                "running_region_source_evidence_unavailable"
            )
        try:
            _validate_authority_payload(
                result["source_report"],
                result["extracted_plans"],
                result["comparison_ledger"],
                result["method_proofs"],
                source_sha256=source_sha256,
                public_document=public_document,
                ir_payload=ir_payload,
            )
        except RunningRegionResourceLimitError as exc:
            raise RunningRegionSourceOutcomeError(
                "running_region_source_limit"
            ) from exc
        except RunningRegionError as exc:
            raise RunningRegionSourceOutcomeError(
                "running_region_source_evidence_unavailable"
            ) from exc
        if _sha256_json(snapshot) != predecessor_sha256:
            raise RunningRegionError(
                "fixed running-region source extraction mutated its predecessor"
            )
        extracted.append(result)
    first, second = extracted
    first_report = first["source_report"]
    second_report = second["source_report"]
    if not isinstance(first_report, Mapping) or not isinstance(second_report, Mapping):
        raise RunningRegionSourceOutcomeError(
            "running_region_source_evidence_unavailable"
        )
    if (
        _strict_json_bytes(_semantic_report_payload(first_report))
        != _strict_json_bytes(_semantic_report_payload(second_report))
        or _strict_json_bytes(first["extracted_plans"])
        != _strict_json_bytes(second["extracted_plans"])
        or _strict_json_bytes(first["comparison_ledger"])
        != _strict_json_bytes(second["comparison_ledger"])
        or _strict_json_bytes(first["method_proofs"])
        != _strict_json_bytes(second["method_proofs"])
    ):
        raise RunningRegionSourceOutcomeError(
            "running_region_source_evidence_unavailable",
            "fixed running-region source extraction is nondeterministic",
        )
    if first_report.get("source_sha256") != source_sha256:
        raise RunningRegionSourceOutcomeError(
            "running_region_source_evidence_unavailable"
        )
    return _issue_authority(
        source_sha256=source_sha256,
        predecessor_sha256=predecessor_sha256,
        source_report_json=_strict_json_bytes(first_report),
        extracted_plans_json=_strict_json_bytes(first["extracted_plans"]),
        comparison_ledger_json=_strict_json_bytes(first["comparison_ledger"]),
        method_proofs_json=_strict_json_bytes(first["method_proofs"]),
        owner_bindings_json=_authority_owner_bindings(
            first_report, public_document, ir_payload
        ),
        predecessor_template_pickle=predecessor_template_pickle,
        predecessor_public_typed_json=predecessor_public_typed_json,
        predecessor_ir_typed_json=predecessor_ir_typed_json,
    )


def _authority_payload(
    authority: _ValidatedSourceProjectionAuthority,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    issued = _require_authority(authority)
    return _authority_payload_from_issued(issued)


def _authority_payload_from_issued(
    issued: _IssuedAuthorityRecord,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """Decode payload bytes after the caller has authenticated the authority."""

    try:
        report = json.loads(issued.source_report_json)
        plans = json.loads(issued.extracted_plans_json)
        ledger = json.loads(issued.comparison_ledger_json)
        proofs = json.loads(issued.method_proofs_json)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise RunningRegionError(
            "source projection authority payload is malformed"
        ) from exc
    if (
        not isinstance(report, dict)
        or not isinstance(plans, list)
        or not isinstance(ledger, list)
        or not isinstance(proofs, dict)
    ):
        raise RunningRegionError("source projection authority payload differs")
    return report, plans, ledger, proofs


def _validate_authority_predecessor(
    authority: _ValidatedSourceProjectionAuthority,
    public_document: Mapping[str, Any],
    ir_document: DocumentIR | Mapping[str, Any],
) -> DocumentIR:
    issued = _require_authority(authority)
    ir_payload = _ir_payload(ir_document)
    snapshot = {
        "public": dict(public_document),
        "ir": ir_payload,
    }
    if _sha256_json(snapshot) != issued.predecessor_sha256:
        raise RunningRegionError("source projection predecessor custody differs")
    validated_ir = (
        ir_document
        if isinstance(ir_document, DocumentIR)
        else DocumentIR.model_validate(ir_payload)
    )
    if (public_document.get("document") or {}).get(
        "sha256"
    ) != issued.source_sha256 or validated_ir.source_sha256 != issued.source_sha256:
        raise RunningRegionError("source projection source custody differs")
    return validated_ir


def _thaw_projection_template(
    issued: _IssuedAuthorityRecord,
) -> tuple[dict[str, Any], DocumentIR]:
    """Thaw one private, factory-built predecessor template."""

    try:
        template = pickle.loads(issued.predecessor_template_pickle)
    except (AttributeError, EOFError, TypeError, ValueError, pickle.PickleError) as exc:
        raise RunningRegionError(
            "source projection predecessor template is malformed"
        ) from exc
    if (
        not isinstance(template, tuple)
        or len(template) != 2
        or type(template[0]) is not dict
        or type(template[1]) is not DocumentIR
    ):
        raise RunningRegionError("source projection predecessor template differs")
    return template


def _projection_predecessor_clones_from_issued(
    issued: _IssuedAuthorityRecord,
    public_document: Mapping[str, Any],
    ir_document: DocumentIR | Mapping[str, Any],
) -> tuple[DocumentIR, dict[str, Any], DocumentIR]:
    """Authenticate inputs and thaw one detached factory-owned template."""

    if type(public_document) is dict and type(ir_document) is DocumentIR:
        try:
            public_typed_json = to_json(public_document)
            ir_typed_json = ir_document.__pydantic_serializer__.to_json(
                ir_document,
                exclude_none=True,
                serialize_as_any=True,
                warnings="error",
            )
        except (PydanticSerializationError, TypeError, ValueError) as exc:
            raise RunningRegionError(
                "source projection predecessor custody differs"
            ) from exc
        if ir_typed_json != issued.predecessor_ir_typed_json:
            raise RunningRegionError("source projection predecessor custody differs")
        if (
            public_typed_json != issued.predecessor_public_typed_json
            and _sha256_json(
                {
                    "public": dict(public_document),
                    "ir": ir_document.model_dump(mode="json", exclude_none=True),
                }
            )
            != issued.predecessor_sha256
        ):
            raise RunningRegionError("source projection predecessor custody differs")
        clean_ir = ir_document
    else:
        ir_payload = _ir_payload(ir_document)
        if (
            _sha256_json({"public": dict(public_document), "ir": ir_payload})
            != issued.predecessor_sha256
        ):
            raise RunningRegionError("source projection predecessor custody differs")
        clean_ir = (
            ir_document
            if isinstance(ir_document, DocumentIR)
            else DocumentIR.model_validate(ir_payload)
        )
    staged_public, staged_ir = _thaw_projection_template(issued)
    if (public_document.get("document") or {}).get(
        "sha256"
    ) != issued.source_sha256 or clean_ir.source_sha256 != issued.source_sha256:
        raise RunningRegionError("source projection source custody differs")
    return clean_ir, staged_public, staged_ir


def _projection_predecessor_clones(
    authority: _ValidatedSourceProjectionAuthority,
    public_document: Mapping[str, Any],
    ir_document: DocumentIR | Mapping[str, Any],
) -> tuple[DocumentIR, dict[str, Any], DocumentIR]:
    """Authenticate inputs and thaw detached factory-validated clone templates."""

    issued = _require_authority(authority)
    return _projection_predecessor_clones_from_issued(
        issued,
        public_document,
        ir_document,
    )


def _commit_projected_page(
    page_index: int,
    public_page: MutableMapping[str, Any],
    ir_page: Any,
) -> None:
    """The single page-transaction commit seam used by fault-injection tests."""

    del page_index, public_page, ir_page


def _bounded_label(value: Any) -> str | None:
    """Return a safe, trimmed, single-line legacy display label."""

    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        text = _safe_text(value, maximum_bytes=MAX_SAFE_LABEL_BYTES)
    except RunningRegionError:
        return None
    if "\n" in text or "\r" in text:
        return None
    allowed_punctuation = frozenset(" ._-:/|()")
    if any(
        not (character.isalpha() or character.isdigit())
        and character not in allowed_punctuation
        for character in text
    ):
        return None
    return text


def _fallback_page_identity(
    *,
    public_page: Mapping[str, Any],
    ir_page: Any,
    report_page: Mapping[str, Any],
    source_sha256: str,
    concern_codes: Sequence[str] = (),
) -> PageIdentity:
    page_index = int(report_page["page_index"])
    embedded: str | None = None
    raw_embedded = report_page.get("embedded_label")
    if isinstance(raw_embedded, str):
        try:
            candidate = _normalize_embedded_label(raw_embedded)
            embedded = candidate if candidate else None
        except RunningRegionError:
            embedded = None
    concerns = list(dict.fromkeys(str(value) for value in concern_codes))
    if embedded is not None:
        display_label = embedded
        display_source = "embedded_label"
        evidence_method = "embedded_pdf_label"
        evidence_reader = "pypdfium2"
        evidence_ids = [
            _stable_id(
                "embedded-page-label",
                POLICY_ID,
                source_sha256,
                page_index,
                embedded,
            )
        ]
        source_object_ids = [
            f"pypdfium2:{source_sha256}:page:{page_index}:embedded_label"
        ]
        confidence = {
            "scope": "source_metadata",
            "score": 1.0,
            "unavailable_reason": None,
        }
    else:
        legacy = _bounded_label(public_page.get("page_label"))
        if legacy is not None:
            display_label = legacy
            display_source = "legacy_display_fallback"
            evidence_method = "legacy_display_fallback"
            source_object_ids = [
                f"configured-predecessor:{source_sha256}:page:{page_index}:page_label"
            ]
            unavailable_reason = "page_identity_source_unavailable"
        else:
            display_label = str(page_index)
            display_source = "physical"
            evidence_method = "physical_page_index"
            source_object_ids = []
            unavailable_reason = "page_identity_display_fallback_physical"
            if public_page.get("page_label") not in (None, ""):
                concerns.append("page_identity_display_unsafe")
        evidence_reader = "configured_predecessor"
        evidence_ids = []
        confidence = {
            "scope": "unavailable",
            "score": None,
            "unavailable_reason": unavailable_reason,
        }
    identity = PageIdentity.model_validate(
        {
            "schema_version": "1.0",
            "policy_id": POLICY_ID,
            "page_id": ir_page.id,
            "physical_page_index": page_index,
            "embedded_label": embedded,
            "detected_printed_label": None,
            "visible_text": None,
            "display_label": display_label,
            "display_source": display_source,
            "evidence_bbox": None,
            "evidence_source": {
                "method": evidence_method,
                "reader": evidence_reader,
                "page_index": page_index,
                "public_item_id": None,
                "public_path": [],
                "element_id": None,
                "bbox_id": None,
                "evidence_ids": evidence_ids,
                "source_object_ids": source_object_ids,
            },
            "confidence": confidence,
            "concern_codes": sorted(set(concerns)),
        }
    )
    validate_running_region_resource_count(
        "page_identity_json_bytes",
        len(_strict_json_bytes(identity.model_dump(mode="json"))),
    )
    return identity


def _projected_page_identity(
    *,
    public_page: Mapping[str, Any],
    ir_page: Any,
    report_page: Mapping[str, Any],
    source_sha256: str,
) -> PageIdentity:
    labels = report_page.get("label_candidates") or []
    if len(labels) != 1:
        concerns = list(report_page.get("concern_codes") or [])
        if len(labels) > 1:
            concerns.append("page_identity_detected_label_ambiguous")
        return _fallback_page_identity(
            public_page=public_page,
            ir_page=ir_page,
            report_page=report_page,
            source_sha256=source_sha256,
            concern_codes=concerns,
        )
    label = labels[0]
    if not isinstance(label, Mapping):
        raise RunningRegionError("printed-label candidate differs")
    visible = _safe_text(
        label.get("visible_text"), maximum_bytes=MAX_VISIBLE_TEXT_BYTES
    )
    detected = _normalize_detected_label(visible)
    if detected != label.get("normalized_label"):
        raise RunningRegionError("printed-label normalization differs")
    embedded: str | None = None
    raw_embedded = report_page.get("embedded_label")
    if isinstance(raw_embedded, str):
        try:
            embedded = _normalize_embedded_label(raw_embedded)
        except RunningRegionError:
            embedded = None
    concerns = list(report_page.get("concern_codes") or [])
    concerns.extend(label.get("concern_codes") or [])
    if embedded is not None and embedded != detected:
        display_label = embedded
        display_source = "embedded_label"
        confidence = {
            "scope": "source_metadata",
            "score": 1.0,
            "unavailable_reason": None,
        }
        concerns.append("page_identity_source_conflict")
    else:
        display_label = detected
        display_source = "detected_printed_label"
        confidence = _confidence()
    identity = PageIdentity.model_validate(
        {
            "schema_version": "1.0",
            "policy_id": POLICY_ID,
            "page_id": ir_page.id,
            "physical_page_index": int(report_page["page_index"]),
            "embedded_label": embedded,
            "detected_printed_label": detected,
            "visible_text": visible,
            "display_label": display_label,
            "display_source": display_source,
            "evidence_bbox": _bbox(label.get("bbox") or {}),
            "evidence_source": {
                "method": "native_printed_label",
                "reader": "pdfplumber",
                "page_index": int(report_page["page_index"]),
                "public_item_id": None,
                "public_path": [],
                "element_id": None,
                "bbox_id": None,
                "evidence_ids": [str(label["id"])],
                "source_object_ids": list(label.get("source_object_ids") or []),
            },
            "confidence": confidence,
            "concern_codes": sorted(set(str(value) for value in concerns)),
        }
    )
    validate_running_region_resource_count(
        "page_identity_json_bytes",
        len(_strict_json_bytes(identity.model_dump(mode="json"))),
    )
    return identity


def _candidate_role(candidate: Mapping[str, Any]) -> str:
    method = candidate.get("source_method")
    band = candidate.get("boundary_band")
    raw_role = candidate.get("raw_layout_role")
    if band not in {"top", "bottom"}:
        raise RunningRegionError("running-region boundary band differs")
    if method == "trusted_layout_role":
        if raw_role == "page_header":
            return "header"
        if raw_role == "page_footer":
            return "footer"
        raise RunningRegionError("trusted running-region role differs")
    if method == "boundary_navigation":
        return "navigation_top" if band == "top" else "navigation_bottom"
    if method in {
        "cross_page_repetition",
        "printed_label_boundary",
        "effective_boundary_cluster",
        "extracted_source_contribution",
    }:
        return "header" if band == "top" else "footer"
    raise RunningRegionError("running-region source method differs")


def _prospective_extracted_descriptor_id(
    candidate: Mapping[str, Any],
    *,
    page_index: int,
    source_sha256: str,
) -> str:
    if candidate.get("source_method") != "extracted_source_contribution":
        raise RunningRegionError("extracted descriptor ordering differs")
    role = _candidate_role(candidate)
    return _stable_id(
        "running-region",
        POLICY_ID,
        source_sha256,
        page_index,
        str(candidate.get("public_item_id")),
        list(candidate.get("source_object_ids") or []),
        list(candidate.get("evidence_ids") or []),
        str(candidate.get("bbox_id")),
        role,
    )


def _repetition_memberships(
    report: Mapping[str, Any], source_sha256: str
) -> dict[str, tuple[str, tuple[int, ...]]]:
    grouped: dict[tuple[str, str], list[tuple[int, Mapping[str, Any], float]]] = (
        defaultdict(list)
    )
    for report_page in report.get("pages") or []:
        page_index = int(report_page["page_index"])
        page_height = float(report_page["page_height"])
        for candidate in report_page.get("boundary_candidates") or []:
            if not isinstance(candidate, Mapping):
                raise RunningRegionError("running-region source candidate differs")
            grouped[
                (
                    str(candidate.get("boundary_band")),
                    str(candidate.get("normalized_signature")),
                )
            ].append((page_index, candidate, page_height))
    result: dict[str, tuple[str, tuple[int, ...]]] = {}
    for (band, signature), records in grouped.items():
        pages = tuple(sorted({record[0] for record in records}))
        if len(pages) < 2 or len(pages) != len(records):
            continue
        midpoints: list[float] = []
        intervals: list[tuple[float, float]] = []
        for _page_index, candidate, page_height in records:
            box = _bbox(candidate.get("bbox") or {})
            midpoints.append((box["y"] + box["height"] / 2) / page_height)
            intervals.append((box["x"], box["x"] + box["width"]))
        if max(midpoints) - min(midpoints) > 0.02 + 1e-9:
            continue
        common_left = max(left for left, _right in intervals)
        common_right = min(right for _left, right in intervals)
        overlap = max(0.0, common_right - common_left)
        if any(overlap / (right - left) < 0.50 for left, right in intervals):
            continue
        group_id = _stable_id(
            "running-repeat", POLICY_ID, source_sha256, band, signature
        )
        for _page_index, candidate, _page_height in records:
            result[str(candidate["id"])] = (group_id, pages)
    return result


def _canonical_block_id(page_id: str, element_id: str) -> str:
    return _stable_id("pb", "1.0", "canonical-presentation-v1", page_id, element_id)


def _descriptor_for_candidate(
    *,
    candidate: Mapping[str, Any],
    owner: Mapping[str, Any],
    page_id: str,
    page_index: int,
    source_sha256: str,
    repetitions: Mapping[str, tuple[str, tuple[int, ...]]],
) -> RunningRegionDescriptor:
    method = str(candidate["source_method"])
    role = _candidate_role(candidate)
    evidence_ids = list(candidate.get("evidence_ids") or [])
    source_object_ids = list(candidate.get("source_object_ids") or [])
    bbox_id = str(candidate["bbox_id"])
    source_element_id = str(candidate["element_id"])
    source_public_item_id = str(candidate["public_item_id"])
    if not evidence_ids or not source_object_ids:
        raise RunningRegionError("running-region source provenance differs")
    if method == "extracted_source_contribution":
        stable_parts: tuple[Any, ...] = (
            POLICY_ID,
            source_sha256,
            page_index,
            source_public_item_id,
            source_object_ids,
            evidence_ids,
            bbox_id,
            role,
        )
    else:
        stable_parts = (
            POLICY_ID,
            source_sha256,
            page_index,
            source_element_id,
            bbox_id,
            role,
        )
    repetition = repetitions.get(str(candidate["id"]))
    if (
        method in {"cross_page_repetition", "extracted_source_contribution"}
        and repetition is None
    ):
        raise RunningRegionError("required running-region repetition differs")
    raw_bbox = candidate.get("bbox") or {}
    if method == "extracted_source_contribution":
        try:
            descriptor_bbox = {
                "x": float(raw_bbox["x"]),
                "y": float(raw_bbox["y"]),
                "width": float(raw_bbox["width"]),
                "height": float(raw_bbox["height"]),
                "unit": str(raw_bbox.get("unit") or "pt"),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RunningRegionError("extracted running-region bbox differs") from exc
        if (
            descriptor_bbox["unit"] != "pt"
            or descriptor_bbox["width"] <= 0
            or descriptor_bbox["height"] <= 0
            or not all(
                math.isfinite(descriptor_bbox[key])
                for key in ("x", "y", "width", "height")
            )
        ):
            raise RunningRegionError("extracted running-region bbox differs")
    else:
        descriptor_bbox = _bbox(raw_bbox)
    descriptor = {
        "id": _stable_id("running-region", *stable_parts),
        "page_id": page_id,
        "physical_page_index": page_index,
        "role": role,
        "canonical_scope": (
            "header" if role in {"header", "navigation_top"} else "footer"
        ),
        "source_public_item_id": source_public_item_id,
        "source_public_path": list(candidate.get("public_path") or []),
        "source_element_id": source_element_id,
        "predecessor_type": str(candidate["predecessor_type"]),
        "predecessor_item_sha256": _sha256_json(_compact_public_item_payload(owner)),
        "bbox_id": bbox_id,
        "bbox": descriptor_bbox,
        "evidence_ids": evidence_ids,
        "source_object_ids": source_object_ids,
        "source_method": method,
        "repetition_group_id": repetition[0] if repetition else None,
        "repetition_page_indexes": list(repetition[1]) if repetition else [],
        "confidence": _confidence(),
        "concern_codes": list(candidate.get("concern_codes") or []),
        "canonical_block_id": _canonical_block_id(page_id, source_element_id),
    }
    validated = RunningRegionDescriptor.model_validate(descriptor)
    validate_running_region_resource_count(
        "running_descriptor_json_bytes",
        len(_strict_json_bytes(validated.model_dump(mode="json"))),
    )
    return validated


def _element_by_id(
    ir_document: DocumentIR,
    element_id: str,
) -> tuple[int, ElementRecord]:
    matches = [
        (offset, value)
        for offset, value in enumerate(ir_document.elements)
        if value.id == element_id
    ]
    if len(matches) != 1:
        raise RunningRegionError("running-region IR element binding differs")
    return matches[0]


def _owner_element(
    ir_document: DocumentIR,
    *,
    page_id: str,
    owner: Mapping[str, Any],
    public_path: Sequence[Any],
) -> ElementRecord:
    current_position = (
        public_path[3]
        if len(public_path) == 4
        and public_path[0] == "pages"
        and public_path[2] == "items"
        and isinstance(public_path[3], int)
        and not isinstance(public_path[3], bool)
        else None
    )
    page_matches = [value for value in ir_document.pages if value.id == page_id]
    if (
        current_position is None
        or len(page_matches) != 1
        or public_path[1] != page_matches[0].page_index - 1
        or current_position < 0
        or current_position >= len(page_matches[0].presentation_element_ids)
    ):
        raise RunningRegionError("extracted running-region owner differs")
    element_id = page_matches[0].presentation_element_ids[current_position]
    matches = [
        value
        for value in ir_document.elements
        if value.id == element_id
        and value.page_id == page_id
        and value.presentation_role == "primary"
        and isinstance(value.properties.get("legacy_item"), Mapping)
        and dict(value.properties["legacy_item"]) == dict(owner)
    ]
    if len(matches) != 1:
        raise RunningRegionError("extracted running-region owner differs")
    return matches[0]


def _insert_before(values: list[str], value: str, anchor: str) -> None:
    try:
        offset = values.index(anchor)
    except ValueError as exc:
        raise RunningRegionError("running-region IR anchor differs") from exc
    values.insert(offset, value)


def _stage_direct_candidate(
    *,
    owner: MutableMapping[str, Any],
    descriptor: RunningRegionDescriptor,
    ir_document: DocumentIR,
) -> None:
    element_offset, element = _element_by_id(ir_document, descriptor.source_element_id)
    if element.page_id != descriptor.page_id:
        raise RunningRegionError("running-region direct page binding differs")
    element = element.model_copy()
    ir_document.elements[element_offset] = element
    public_type = (
        "header" if descriptor.role in {"header", "navigation_top"} else "footer"
    )
    owner["type"] = public_type
    owner["layout_running_region_projected"] = True
    owner["running_region_policy"] = POLICY_ID
    owner["running_region"] = descriptor.model_dump(mode="json")
    element.type = public_type
    element.running_region = descriptor


def _stage_extracted_candidate(
    *,
    public_page: MutableMapping[str, Any],
    owner: Mapping[str, Any],
    owner_element: ElementRecord,
    descriptor: RunningRegionDescriptor,
    plan: Mapping[str, Any],
    ir_document: DocumentIR,
    ir_page: Any,
) -> dict[str, Any]:
    source_text = plan.get("source_text")
    presentation_text = plan.get("presentation_text")
    residual = plan.get("residual_canonical")
    if not all(
        isinstance(value, str) and value
        for value in (source_text, presentation_text, residual)
    ):
        raise RunningRegionError("extracted running-region presentation differs")
    if (
        plan.get("owner_public_item_id") != descriptor.source_public_item_id
        or plan.get("physical_page_index") != descriptor.physical_page_index
        or plan.get("owner_sha256_before") != descriptor.predecessor_item_sha256
        or plan.get("owner_sha256_after") != descriptor.predecessor_item_sha256
        or plan.get("predecessor_canonical") != owner.get("value")
        or plan.get("predecessor_canonical") != owner.get("md")
    ):
        raise RunningRegionError("extracted running-region plan custody differs")

    synthetic_item_id = descriptor.id.replace(
        "running-region-", "running-region-item-", 1
    )
    public_items = public_page.get("items")
    if not isinstance(public_items, list):
        raise RunningRegionError("running-region public items differ")
    reading_orders = [
        item.get("reading_order") for item in public_items if isinstance(item, Mapping)
    ]
    if not reading_orders or any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in reading_orders
    ):
        raise RunningRegionError("running-region reading order differs")
    synthetic_reading_order = max(reading_orders) + 1
    synthetic_item: dict[str, Any] = {
        "id": synthetic_item_id,
        "type": (
            "header" if descriptor.role in {"header", "navigation_top"} else "footer"
        ),
        "reading_order": synthetic_reading_order,
        "value": source_text,
        "md": source_text,
        "bbox": descriptor.bbox.model_dump(mode="json"),
        "source": "native",
        "confidence": 1.0,
        "layout_running_region_projected": True,
        "running_region_policy": POLICY_ID,
        "running_region": descriptor.model_dump(mode="json"),
    }
    public_items.append(synthetic_item)

    coordinate_id = ir_page.coordinate_system_id
    synthetic_bbox = IRBoundingBox(
        id=descriptor.bbox_id,
        coordinate_system_id=coordinate_id,
        x=descriptor.bbox.x,
        y=descriptor.bbox.y,
        width=descriptor.bbox.width,
        height=descriptor.bbox.height,
        role="element",
    )
    evidence_id = descriptor.evidence_ids[0]
    synthetic_evidence = EvidenceRecord(
        id=evidence_id,
        element_id=descriptor.source_element_id,
        method=EvidenceMethod.NATIVE,
        bbox_id=descriptor.bbox_id,
        value=source_text,
        confidence=ConfidenceRecord(
            scope="evidence",
            score=None,
            unavailable_reason="not_calibrated",
        ),
        metadata={
            "policy_id": POLICY_ID,
            "source_object_ids": list(descriptor.source_object_ids),
        },
    )
    synthetic_element = ElementRecord(
        id=descriptor.source_element_id,
        page_id=descriptor.page_id,
        type=synthetic_item["type"],
        reading_order=synthetic_item["reading_order"],
        value=source_text,
        markdown=source_text,
        bbox_ids=[descriptor.bbox_id],
        evidence_ids=[evidence_id],
        running_region=descriptor,
        presentation_role="primary",
        presentation=ElementPresentationDirective(accepted=True),
        properties={
            "legacy_item": deepcopy(synthetic_item),
            "generated": False,
            "region_role": None,
            "content_type": None,
            "source_position": len(public_items) - 1,
        },
    )
    if any(value.id == synthetic_bbox.id for value in ir_document.bboxes):
        raise RunningRegionError("synthetic running-region bbox repeats")
    if any(value.id == synthetic_evidence.id for value in ir_document.evidence):
        raise RunningRegionError("synthetic running-region evidence repeats")
    if any(value.id == synthetic_element.id for value in ir_document.elements):
        raise RunningRegionError("synthetic running-region element repeats")
    ir_document.bboxes.append(synthetic_bbox)
    ir_document.evidence.append(synthetic_evidence)
    ir_document.elements.append(synthetic_element)
    ir_page.element_ids.append(synthetic_element.id)
    ir_page.presentation_element_ids.append(synthetic_element.id)
    regions = [
        value
        for value in ir_document.regions
        if value.page_id == ir_page.id and owner_element.id in value.element_ids
    ]
    if len(regions) != 1:
        raise RunningRegionError("extracted running-region region owner differs")
    regions[0].element_ids.append(synthetic_element.id)
    return {
        "page_index": descriptor.physical_page_index,
        "synthetic_element_id": synthetic_element.id,
        "owner_element_id": owner_element.id,
        "presentation_text": presentation_text,
        "residual_canonical": residual,
    }


def _restore_ir_page(
    projected: DocumentIR,
    predecessor: DocumentIR,
    *,
    page_index: int,
) -> Any:
    original_page = next(
        (value for value in predecessor.pages if value.page_index == page_index),
        None,
    )
    current_page = next(
        (value for value in projected.pages if value.page_index == page_index),
        None,
    )
    if (
        original_page is None
        or current_page is None
        or original_page.id != current_page.id
    ):
        raise RunningRegionError("running-region rollback page differs")
    page_id = original_page.id
    coordinate_ids = {
        value.id for value in projected.coordinate_systems if value.page_id == page_id
    }
    staged_element_ids = {
        value.id for value in projected.elements if value.page_id == page_id
    }
    staged_bbox_ids = {
        value.id
        for value in projected.bboxes
        if value.coordinate_system_id in coordinate_ids
    }

    original_elements = {
        value.id: value for value in predecessor.elements if value.page_id == page_id
    }
    projected.elements = [
        deepcopy(original_elements.get(value.id, value))
        for value in projected.elements
        if value.page_id != page_id or value.id in original_elements
    ]
    original_bboxes = {
        value.id: value
        for value in predecessor.bboxes
        if value.coordinate_system_id in coordinate_ids
    }
    projected.bboxes = [
        deepcopy(original_bboxes.get(value.id, value))
        for value in projected.bboxes
        if value.coordinate_system_id not in coordinate_ids
        or value.id in original_bboxes
    ]
    original_evidence = {
        value.id: value
        for value in predecessor.evidence
        if value.element_id in original_elements or value.bbox_id in original_bboxes
    }
    projected.evidence = [
        deepcopy(original_evidence.get(value.id, value))
        for value in projected.evidence
        if (
            value.element_id not in staged_element_ids
            and value.bbox_id not in staged_bbox_ids
        )
        or value.id in original_evidence
    ]
    original_regions = {
        value.id: value for value in predecessor.regions if value.page_id == page_id
    }
    projected.regions = [
        deepcopy(original_regions.get(value.id, value))
        for value in projected.regions
        if value.page_id != page_id or value.id in original_regions
    ]
    page_offset = projected.pages.index(current_page)
    projected.pages[page_offset] = deepcopy(original_page)
    return projected.pages[page_offset]


def _canonical_view(blocks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    included = [value for value in blocks if value.get("omission_reason") is None]

    def render(field: str) -> str:
        values = [
            str(value.get(field) or "").strip()
            for value in included
            if str(value.get(field) or "").strip()
        ]
        return "\n\n".join(values).rstrip() + "\n" if values else ""

    return {
        "block_ids": [str(value["id"]) for value in included],
        "markdown": render("markdown"),
        "text": render("text"),
    }


def _build_projected_canonical(
    ir_document: DocumentIR,
    adjustments: Sequence[Mapping[str, Any]],
    predecessor_canonical: Mapping[str, Any],
) -> dict[str, Any]:
    from app.services.presentation import CanonicalPresentation

    # The caller supplies the already-detached authority template.  A shallow
    # outer copy preserves the helper's return boundary while avoiding a second
    # multi-megabyte canonical clone on the projection hot path.
    payload = dict(predecessor_canonical)
    if not isinstance(payload.get("pages"), list):
        raise RunningRegionError("running-region canonical predecessor differs")
    identities_by_index = {
        value.page_index: (
            value.page_identity.model_dump(mode="json")
            if value.page_identity is not None
            else None
        )
        for value in ir_document.pages
    }
    for page in payload["pages"]:
        identity_payload = identities_by_index.get(int(page["page_index"]))
        if identity_payload is None:
            page.pop("page_identity", None)
        else:
            page["page_identity"] = identity_payload
    pages_by_index = {int(value["page_index"]): value for value in payload["pages"]}
    descriptors = [
        value.running_region
        for value in ir_document.elements
        if value.running_region is not None
    ]
    adjustment_by_element = {
        str(value["synthetic_element_id"]): value for value in adjustments
    }
    for descriptor in descriptors:
        assert descriptor is not None
        page = pages_by_index.get(descriptor.physical_page_index)
        if page is None or not isinstance(page.get("blocks"), list):
            raise RunningRegionError("running-region canonical page differs")
        if descriptor.source_method == "extracted_source_contribution":
            adjustment = adjustment_by_element.get(descriptor.source_element_id)
            if adjustment is None:
                raise RunningRegionError("extracted canonical adjustment differs")
            owner_offset = next(
                (
                    offset
                    for offset, value in enumerate(page["blocks"])
                    if value.get("primary_element_id") == adjustment["owner_element_id"]
                ),
                None,
            )
            if owner_offset is None:
                raise RunningRegionError("extracted canonical owner differs")
            owner = page["blocks"][owner_offset]
            owner["markdown"] = adjustment["residual_canonical"]
            owner["text"] = adjustment["residual_canonical"]
            synthetic = {
                "id": descriptor.canonical_block_id,
                "page_id": descriptor.page_id,
                "primary_element_id": descriptor.source_element_id,
                "primary_element_type": (
                    "header"
                    if descriptor.role in {"header", "navigation_top"}
                    else "footer"
                ),
                "scope": descriptor.canonical_scope,
                "markdown": adjustment["presentation_text"],
                "text": adjustment["presentation_text"],
                "contributing_element_ids": [descriptor.source_element_id],
                "relationship_ids": [],
                "excluded_contributions": [],
                "omission_reason": None,
            }
            page["blocks"].insert(owner_offset, synthetic)
            continue
        matches = [
            value
            for value in page["blocks"]
            if value.get("id") == descriptor.canonical_block_id
            and value.get("primary_element_id") == descriptor.source_element_id
        ]
        if len(matches) != 1:
            raise RunningRegionError("direct running-region canonical block differs")
        matches[0]["primary_element_type"] = (
            "header" if descriptor.role in {"header", "navigation_top"} else "footer"
        )
        matches[0]["scope"] = descriptor.canonical_scope
        if descriptor.predecessor_type.casefold() == "heading":
            canonical_markdown = matches[0].get("markdown")
            canonical_text = matches[0].get("text")
            if (
                isinstance(canonical_markdown, str)
                and isinstance(canonical_text, str)
            ):
                marker = re.fullmatch(
                    r"#{1,6} (.*)",
                    canonical_markdown,
                    flags=re.DOTALL,
                )
                if marker is not None and marker.group(1) == canonical_text:
                    matches[0]["markdown"] = canonical_text
        # The public US08 binding contract is closed and carries an explicit
        # null for included blocks; prior exclude-none serialization may have
        # omitted it before this additive stage.
        matches[0]["omission_reason"] = None

    for page in payload["pages"]:
        blocks = page["blocks"]
        page["full"] = _canonical_view(blocks)
        page["body"] = _canonical_view(
            [value for value in blocks if value["scope"] == "body"]
        )
        page["header"] = _canonical_view(
            [value for value in blocks if value["scope"] == "header"]
        )
        page["footer"] = _canonical_view(
            [value for value in blocks if value["scope"] == "footer"]
        )
    document_blocks = [block for page in payload["pages"] for block in page["blocks"]]
    payload["full"] = _canonical_view(document_blocks)
    payload["body"] = _canonical_view(
        [value for value in document_blocks if value["scope"] == "body"]
    )
    payload["header"] = _canonical_view(
        [value for value in document_blocks if value["scope"] == "header"]
    )
    payload["footer"] = _canonical_view(
        [value for value in document_blocks if value["scope"] == "footer"]
    )
    CanonicalPresentation.model_validate(payload)
    return payload


def _projected_public_semantic_bytes(
    public_document: Mapping[str, Any],
) -> bytes:
    """Serialize every projected surface except the three runtime timings."""

    detached = deepcopy(dict(public_document))
    processing = detached.get("processing")
    summary = (
        processing.get("running_regions")
        if isinstance(processing, MutableMapping)
        else None
    )
    if not isinstance(summary, MutableMapping):
        raise RunningRegionError("projected running-region summary differs")
    for field in ("extraction_ms", "projection_ms", "total_ms"):
        summary.pop(field, None)
    return _strict_json_bytes(detached)


def _already_projected(
    public_document: Any,
    ir_document: Any,
    source_authority: Any,
) -> tuple[Any, Any] | None:
    if not isinstance(public_document, Mapping):
        return None
    summary = (public_document.get("processing") or {}).get("running_regions")
    if not isinstance(summary, Mapping) or summary.get("status") != "projected":
        return None
    issued = _require_authority(source_authority)
    if (public_document.get("document") or {}).get("sha256") != issued.source_sha256:
        raise RunningRegionError("projected running-region source differs")
    validated_ir = DocumentIR.model_validate(
        ir_document.model_dump(mode="json")
        if isinstance(ir_document, DocumentIR)
        else _ir_payload(ir_document)
    )
    if validated_ir.source_sha256 != issued.source_sha256:
        raise RunningRegionError("projected running-region IR source differs")
    RunningRegionsProcessingSummary.model_validate(summary)
    pages = public_document.get("pages")
    canonical = public_document.get("canonical_presentation")
    canonical_pages = canonical.get("pages") if isinstance(canonical, Mapping) else None
    if (
        not isinstance(pages, list)
        or not isinstance(canonical_pages, list)
        or len(pages) != len(validated_ir.pages)
        or len(pages) != len(canonical_pages)
    ):
        raise RunningRegionError("projected running-region page coverage differs")
    canonical_by_index = {
        value.get("page_index"): value
        for value in canonical_pages
        if isinstance(value, Mapping)
    }
    ir_by_index = {value.page_index: value for value in validated_ir.pages}
    public_descriptors: dict[str, Mapping[str, Any]] = {}
    for page in pages:
        if not isinstance(page, Mapping) or not isinstance(
            page.get("page_identity"), Mapping
        ):
            raise RunningRegionError("projected page identity differs")
        identity = PageIdentity.model_validate(page["page_identity"])
        canonical_page = canonical_by_index.get(page.get("page_index"))
        ir_page = ir_by_index.get(page.get("page_index"))
        if (
            canonical_page is None
            or ir_page is None
            or canonical_page.get("page_identity") != identity.model_dump(mode="json")
            or ir_page.page_identity != identity
        ):
            raise RunningRegionError("projected page identity surfaces differ")
        for item in page.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            keys = set(item).intersection(_SIDECAR_KEYS)
            if keys and keys != set(_SIDECAR_KEYS):
                raise RunningRegionError("partial running-region sidecar")
            if keys:
                descriptor = RunningRegionDescriptor.model_validate(
                    item["running_region"]
                )
                if (
                    item["layout_running_region_projected"] is not True
                    or item["running_region_policy"] != POLICY_ID
                    or descriptor.id in public_descriptors
                ):
                    raise RunningRegionError("projected running-region sidecar differs")
                public_descriptors[descriptor.id] = descriptor.model_dump(mode="json")
    ir_descriptors = {
        value.running_region.id: value.running_region.model_dump(mode="json")
        for value in validated_ir.elements
        if value.running_region is not None
    }
    if public_descriptors != ir_descriptors:
        raise RunningRegionError("projected public/IR running regions differ")

    # Authenticate the repeat against the exact factory-bound predecessor,
    # then deterministically reconstruct the expected projection.  A projected
    # summary or derived canonical view is not self-authenticating: stripping
    # alone can legitimately discard both, so the complete reconstructed
    # public/IR surfaces must also match byte-for-byte (apart from timings).
    stripped_public, stripped_ir = strip_running_regions(
        public_document,
        validated_ir,
    )
    clean_ir = _validate_authority_predecessor(
        source_authority,
        stripped_public,
        stripped_ir,
    )
    expected_public, expected_ir = project_running_regions(
        stripped_public,
        clean_ir,
        source_authority,
    )
    if _projected_public_semantic_bytes(
        public_document
    ) != _projected_public_semantic_bytes(expected_public) or validated_ir.model_dump(
        mode="json"
    ) != expected_ir.model_dump(mode="json"):
        raise RunningRegionError("projected running-region authenticated state differs")
    return public_document, ir_document


def _add_projected_concern(
    concerns: dict[tuple[str, str], dict[str, Any]],
    *,
    code: str,
    source_ref: str,
    count: int,
    cap: int,
    exception_class: str | None = None,
) -> None:
    key = (source_ref, code)
    current = concerns.get(key)
    if current is None:
        concerns[key] = {
            "code": code,
            "source_ref": source_ref,
            "count": count,
            "cap": cap,
            "exception_class": exception_class,
        }
        return
    if current["cap"] != cap or current["exception_class"] != exception_class:
        raise RunningRegionError("running-region concern correlation differs")
    current["count"] += count


def _projected_concern_records(
    source_report: Mapping[str, Any],
    public_pages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Correlate every concern-bearing source and projected surface exactly."""

    concerns: dict[tuple[str, str], dict[str, Any]] = {}
    occurrences_by_source: dict[str, int] = defaultdict(int)

    def charge(values: Any, source_ref: str) -> None:
        if isinstance(values, (str, bytes, bytearray)) or not isinstance(
            values, Sequence
        ):
            raise RunningRegionError("running-region concern codes differ")
        cap = (
            MAX_CONCERNS_PER_DOCUMENT
            if source_ref == "document"
            else MAX_CONCERNS_PER_PAGE
        )
        for value in values:
            if not isinstance(value, str) or not value:
                raise RunningRegionError("running-region concern code differs")
            occurrences_by_source[source_ref] += 1
            _add_projected_concern(
                concerns,
                code=value,
                source_ref=source_ref,
                count=1,
                cap=cap,
            )

    charge(source_report.get("concern_codes"), "document")
    report_pages = source_report.get("pages")
    if not isinstance(report_pages, list) or len(report_pages) != len(public_pages):
        raise RunningRegionError("running-region concern page coverage differs")
    for report_page, public_page in zip(
        report_pages,
        public_pages,
        strict=True,
    ):
        if not isinstance(report_page, Mapping) or not isinstance(public_page, Mapping):
            raise RunningRegionError("running-region concern page differs")
        page_index = report_page.get("page_index")
        if (
            isinstance(page_index, bool)
            or not isinstance(page_index, int)
            or public_page.get("page_index") != page_index
        ):
            raise RunningRegionError("running-region concern page differs")
        source_ref = f"page:{page_index}"
        charge(report_page.get("concern_codes"), source_ref)
        for collection in ("label_candidates", "boundary_candidates"):
            candidates = report_page.get(collection)
            if not isinstance(candidates, list):
                raise RunningRegionError(
                    "running-region concern candidate coverage differs"
                )
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    raise RunningRegionError("running-region concern candidate differs")
                charge(candidate.get("concern_codes"), source_ref)
        identity = public_page.get("page_identity")
        if not isinstance(identity, Mapping):
            raise RunningRegionError("running-region concern identity differs")
        charge(identity.get("concern_codes"), source_ref)
        items = public_page.get("items")
        if not isinstance(items, list):
            raise RunningRegionError("running-region concern items differ")
        for item in items:
            descriptor = (
                item.get("running_region") if isinstance(item, Mapping) else None
            )
            if isinstance(descriptor, Mapping):
                charge(descriptor.get("concern_codes"), source_ref)

    validate_running_region_resource_count(
        "concerns_per_document",
        sum(occurrences_by_source.values()),
    )
    for source_ref, count in occurrences_by_source.items():
        if source_ref != "document":
            validate_running_region_resource_count("concerns_per_page", count)
    records = [concerns[key] for key in sorted(concerns)]
    return [
        ProjectedRunningRegionConcern.model_validate(record).model_dump(mode="json")
        for record in records
    ]


def project_running_regions(
    predecessor_public: Mapping[str, Any],
    predecessor_ir: DocumentIR | Mapping[str, Any],
    source_authority: _ValidatedSourceProjectionAuthority | None = None,
    *,
    enabled: bool = True,
    metrics: MutableMapping[str, Any] | None = None,
) -> tuple[dict[str, Any], DocumentIR]:
    """Project source-authorized page identity and running-region sidecars."""

    # This guard is intentionally the first executable branch.  It must not
    # inspect inputs, source authority, metrics, or page collections.
    if not enabled:
        return predecessor_public, predecessor_ir  # type: ignore[return-value]

    repeated = _already_projected(predecessor_public, predecessor_ir, source_authority)
    if repeated is not None:
        return repeated  # type: ignore[return-value]

    if not isinstance(predecessor_public, Mapping):
        raise RunningRegionError("running-region predecessor differs")
    issued = _require_authority(source_authority)
    _clean_ir, staged_public, staged_ir = _projection_predecessor_clones_from_issued(
        issued,
        predecessor_public,
        predecessor_ir,
    )
    report, plans, ledger, proofs = _authority_payload_from_issued(issued)
    # The source payload, owner bindings, and predecessor template were fully
    # validated before issuance.  They are private immutable registry bytes;
    # re-running the multi-megabyte validation here would add no custody signal.
    # The typed serialization check still authenticates every caller-supplied
    # predecessor field before projection.
    del proofs
    if (
        report.get("policy_id") != POLICY_ID
        or report.get("status") != "available"
        or report.get("source_sha256") != issued.source_sha256
        or not isinstance(report.get("pages"), list)
    ):
        raise RunningRegionError("running-region source report differs")
    comparison_count = 0
    ledger_indexes: list[int] = []
    for entry in ledger:
        if (
            not isinstance(entry, Mapping)
            or isinstance(entry.get("page_index"), bool)
            or not isinstance(entry.get("page_index"), int)
            or isinstance(entry.get("comparison_count"), bool)
            or not isinstance(entry.get("comparison_count"), int)
            or not 1 <= entry["comparison_count"] <= MAX_COMPARISONS_PER_PAGE
        ):
            raise RunningRegionError("running-region comparison ledger differs")
        ledger_indexes.append(entry["page_index"])
        comparison_count += entry["comparison_count"]
    if (
        ledger_indexes != sorted(set(ledger_indexes))
        or comparison_count > MAX_COMPARISONS_PER_DOCUMENT
    ):
        raise RunningRegionError("running-region comparison ledger differs")

    plan_by_owner: dict[tuple[int, str], Mapping[str, Any]] = {}
    for plan in plans:
        if not isinstance(plan, Mapping):
            raise RunningRegionError("extracted running-region plan differs")
        key = (int(plan["physical_page_index"]), str(plan["owner_public_item_id"]))
        if key in plan_by_owner:
            raise RunningRegionError("extracted running-region plan repeats")
        plan_by_owner[key] = plan

    public_pages = staged_public.get("pages")
    if not isinstance(public_pages, list):
        raise RunningRegionError("running-region public pages differ")
    report_pages = report["pages"]
    if len(public_pages) != len(staged_ir.pages) or len(report_pages) != len(
        public_pages
    ):
        raise RunningRegionError("running-region page coverage differs")
    report_by_index = {
        int(value["page_index"]): value
        for value in report_pages
        if isinstance(value, Mapping)
    }
    if len(report_by_index) != len(report_pages):
        raise RunningRegionError("running-region report page order differs")
    repetitions = _repetition_memberships(report, issued.source_sha256)
    projection_started_ns = time.perf_counter_ns()
    adjustments: list[dict[str, Any]] = []
    committed: list[RunningRegionDescriptor] = []
    identities: list[PageIdentity] = []

    for page_offset, public_page in enumerate(public_pages):
        if not isinstance(public_page, MutableMapping):
            raise RunningRegionError("running-region public page differs")
        page_index = public_page.get("page_index")
        if isinstance(page_index, bool) or not isinstance(page_index, int):
            raise RunningRegionError("running-region page index differs")
        report_page = report_by_index.get(page_index)
        ir_page = next(
            (value for value in staged_ir.pages if value.page_index == page_index),
            None,
        )
        if report_page is None or ir_page is None:
            raise RunningRegionError("running-region page binding differs")
        page_started_ns = time.perf_counter_ns()
        page_descriptors: list[RunningRegionDescriptor] = []
        page_adjustments: list[dict[str, Any]] = []
        try:
            identity = _projected_page_identity(
                public_page=public_page,
                ir_page=ir_page,
                report_page=report_page,
                source_sha256=issued.source_sha256,
            )
            public_page["page_identity"] = identity.model_dump(mode="json")
            ir_page.page_identity = identity
            raw_candidates = report_page.get("boundary_candidates") or []
            if not isinstance(raw_candidates, list) or any(
                not isinstance(candidate, Mapping) for candidate in raw_candidates
            ):
                raise RunningRegionError("running-region candidates differ")
            ordered_candidates = [
                candidate
                for _offset, candidate in sorted(
                    enumerate(raw_candidates),
                    key=lambda value: (
                        (
                            1,
                            _prospective_extracted_descriptor_id(
                                value[1],
                                page_index=page_index,
                                source_sha256=issued.source_sha256,
                            ),
                        )
                        if value[1].get("source_method")
                        == "extracted_source_contribution"
                        else (0, value[0])
                    ),
                )
            ]
            for candidate in ordered_candidates:
                if not isinstance(candidate, Mapping):
                    raise RunningRegionError("running-region candidate differs")
                owner = _resolve_path(staged_public, candidate.get("public_path") or [])
                if not isinstance(owner, MutableMapping) or owner.get(
                    "id"
                ) != candidate.get("public_item_id"):
                    raise RunningRegionError("running-region public owner differs")
                descriptor = _descriptor_for_candidate(
                    candidate=candidate,
                    owner=owner,
                    page_id=ir_page.id,
                    page_index=page_index,
                    source_sha256=issued.source_sha256,
                    repetitions=repetitions,
                )
                if descriptor.source_method == "extracted_source_contribution":
                    plan = plan_by_owner.get(
                        (page_index, descriptor.source_public_item_id)
                    )
                    if plan is None:
                        raise RunningRegionError(
                            "extracted running-region plan is absent"
                        )
                    owner_element = _owner_element(
                        staged_ir,
                        page_id=ir_page.id,
                        owner=owner,
                        public_path=descriptor.source_public_path,
                    )
                    page_adjustments.append(
                        _stage_extracted_candidate(
                            public_page=public_page,
                            owner=owner,
                            owner_element=owner_element,
                            descriptor=descriptor,
                            plan=plan,
                            ir_document=staged_ir,
                            ir_page=ir_page,
                        )
                    )
                else:
                    _stage_direct_candidate(
                        owner=owner,
                        descriptor=descriptor,
                        ir_document=staged_ir,
                    )
                page_descriptors.append(descriptor)
            validate_running_region_resource_count(
                "running_regions_per_page", len(page_descriptors)
            )
            validate_running_region_deadline("projection_page", page_started_ns)
            _commit_projected_page(page_index, public_page, ir_page)
        except Exception:
            rollback_public, rollback_ir = _thaw_projection_template(issued)
            rollback_pages = rollback_public.get("pages")
            if (
                not isinstance(rollback_pages, list)
                or page_offset >= len(rollback_pages)
                or not isinstance(rollback_pages[page_offset], MutableMapping)
            ):
                raise RunningRegionError("running-region rollback predecessor differs")
            restored_public_page = rollback_pages[page_offset]
            public_pages[page_offset] = restored_public_page
            restored_ir_page = _restore_ir_page(
                staged_ir, rollback_ir, page_index=page_index
            )
            identity = _fallback_page_identity(
                public_page=restored_public_page,
                ir_page=restored_ir_page,
                report_page=report_page,
                source_sha256=issued.source_sha256,
                concern_codes=("running_region_projection_failed_closed",),
            )
            restored_public_page["page_identity"] = identity.model_dump(mode="json")
            restored_ir_page.page_identity = identity
        else:
            committed.extend(page_descriptors)
            adjustments.extend(page_adjustments)
        identities.append(identity)

    staged_ir = staged_ir.validate_graph()
    staged_public["canonical_presentation"] = _build_projected_canonical(
        staged_ir,
        adjustments,
        staged_public.get("canonical_presentation") or {},
    )
    concern_records = _projected_concern_records(report, public_pages)
    counts = report.get("counts") or {}
    role_counts = {
        role: sum(value.role == role for value in committed)
        for role in ("header", "footer", "navigation_top", "navigation_bottom")
    }
    validate_running_region_resource_count(
        "running_regions_per_document", len(committed)
    )
    extraction_ms = round(float(report.get("extraction_ms") or 0.0), 3)
    projection_ms = round(
        validate_running_region_deadline("projection_document", projection_started_ns)
        * 1000,
        3,
    )
    summary = RunningRegionsProcessingSummary.model_validate(
        {
            "policy_id": POLICY_ID,
            "status": "projected",
            "reason": None,
            "source_page_count": len(report_pages),
            "identity_count": len(identities),
            "detected_label_count": sum(
                value.display_source == "detected_printed_label" for value in identities
            ),
            "embedded_label_count": sum(
                value.display_source == "embedded_label" for value in identities
            ),
            "legacy_fallback_count": sum(
                value.display_source in {"legacy_display_fallback", "physical"}
                for value in identities
            ),
            "candidate_count": int(counts.get("boundary_candidate_count") or 0),
            "comparison_count": comparison_count,
            "running_region_count": len(committed),
            "header_count": role_counts["header"],
            "footer_count": role_counts["footer"],
            "top_navigation_count": role_counts["navigation_top"],
            "bottom_navigation_count": role_counts["navigation_bottom"],
            "concern_count": len(concern_records),
            "extraction_ms": extraction_ms,
            "projection_ms": projection_ms,
            "total_ms": round(extraction_ms + projection_ms, 3),
        }
    ).model_dump(mode="json")
    processing = staged_public.setdefault("processing", {})
    if not isinstance(processing, MutableMapping):
        raise RunningRegionError("running-region processing surface differs")
    processing["running_regions"] = summary
    if concern_records:
        staged_public["running_region_concerns"] = concern_records
    else:
        staged_public.pop("running_region_concerns", None)
    if metrics is not None:
        metrics.update(summary)
    return staged_public, staged_ir


def _strip_public_canonical(
    public_document: MutableMapping[str, Any],
    records: Sequence[tuple[int, Mapping[str, Any], RunningRegionDescriptor]],
) -> None:
    from app.services.presentation import CanonicalPresentation

    canonical = public_document.get("canonical_presentation")
    if not isinstance(canonical, MutableMapping) or not isinstance(
        canonical.get("pages"), list
    ):
        raise RunningRegionError("running-region canonical projection differs")
    pages_by_index = {
        int(value["page_index"]): value
        for value in canonical["pages"]
        if isinstance(value, MutableMapping)
    }
    if len(pages_by_index) != len(canonical["pages"]):
        raise RunningRegionError("running-region canonical page order differs")
    for page in canonical["pages"]:
        page.pop("page_identity", None)
    for page_index, owner, descriptor in records:
        page = pages_by_index.get(page_index)
        if page is None or not isinstance(page.get("blocks"), list):
            raise RunningRegionError("running-region canonical page differs")
        blocks = page["blocks"]
        matches = [
            (offset, value)
            for offset, value in enumerate(blocks)
            if isinstance(value, MutableMapping)
            and value.get("id") == descriptor.canonical_block_id
        ]
        if len(matches) != 1:
            raise RunningRegionError("running-region canonical block differs")
        offset, block = matches[0]
        if descriptor.source_method == "extracted_source_contribution":
            if (
                block.get("primary_element_id") != descriptor.source_element_id
                or offset + 1 >= len(blocks)
                or not isinstance(blocks[offset + 1], MutableMapping)
            ):
                raise RunningRegionError("extracted canonical rollback differs")
            owner_block = blocks[offset + 1]
            predecessor_scalar = owner.get("value")
            if not isinstance(predecessor_scalar, str):
                predecessor_scalar = owner.get("md")
            if not isinstance(predecessor_scalar, str):
                raise RunningRegionError("extracted canonical predecessor differs")
            owner_block["markdown"] = predecessor_scalar
            owner_block["text"] = predecessor_scalar
            blocks.pop(offset)
            continue
        block["primary_element_type"] = descriptor.predecessor_type
        block["scope"] = (
            "header"
            if descriptor.predecessor_type.casefold() == "header"
            else "footer"
            if descriptor.predecessor_type.casefold() == "footer"
            else "body"
        )
        if (
            descriptor.predecessor_type.casefold() == "heading"
            and isinstance(owner.get("md"), str)
            and isinstance(owner.get("value"), str)
        ):
            marker = re.fullmatch(
                r"#{1,6} (.*)",
                owner["md"],
                flags=re.DOTALL,
            )
            if marker is not None and marker.group(1) == owner["value"]:
                block["markdown"] = owner["md"]
        block.pop("omission_reason", None)

    for page in canonical["pages"]:
        blocks = page["blocks"]
        page["full"] = _canonical_view(blocks)
        page["body"] = _canonical_view(
            [value for value in blocks if value["scope"] == "body"]
        )
        page["header"] = _canonical_view(
            [value for value in blocks if value["scope"] == "header"]
        )
        page["footer"] = _canonical_view(
            [value for value in blocks if value["scope"] == "footer"]
        )
    document_blocks = [value for page in canonical["pages"] for value in page["blocks"]]
    canonical["full"] = _canonical_view(document_blocks)
    canonical["body"] = _canonical_view(
        [value for value in document_blocks if value["scope"] == "body"]
    )
    canonical["header"] = _canonical_view(
        [value for value in document_blocks if value["scope"] == "header"]
    )
    canonical["footer"] = _canonical_view(
        [value for value in document_blocks if value["scope"] == "footer"]
    )
    try:
        CanonicalPresentation.model_validate(canonical)
    except Exception as exc:
        raise RunningRegionError("running-region canonical rollback differs") from exc


def _strip_ir_document(
    ir_document: DocumentIR | Mapping[str, Any],
    descriptors: Sequence[RunningRegionDescriptor],
) -> DocumentIR:
    projected = DocumentIR.model_validate(
        ir_document.model_dump(mode="json")
        if isinstance(ir_document, DocumentIR)
        else _ir_payload(ir_document)
    )
    cleaned = deepcopy(projected)
    extracted_element_ids = {
        value.source_element_id
        for value in descriptors
        if value.source_method == "extracted_source_contribution"
    }
    extracted_bbox_ids = {
        value.bbox_id
        for value in descriptors
        if value.source_method == "extracted_source_contribution"
    }
    extracted_evidence_ids = {
        evidence_id
        for value in descriptors
        if value.source_method == "extracted_source_contribution"
        for evidence_id in value.evidence_ids
    }
    descriptor_by_element = {value.source_element_id: value for value in descriptors}
    restored_elements: list[ElementRecord] = []
    for element in cleaned.elements:
        descriptor = descriptor_by_element.get(element.id)
        if descriptor is None:
            restored_elements.append(element)
            continue
        if descriptor.source_method == "extracted_source_contribution":
            continue
        legacy_item = element.properties.get("legacy_item")
        legacy_sidecar_keys = (
            set(legacy_item).intersection(_SIDECAR_KEYS)
            if isinstance(legacy_item, Mapping)
            else set()
        )
        if (
            not isinstance(legacy_item, Mapping)
            or legacy_sidecar_keys not in (set(), set(_SIDECAR_KEYS))
            or (
                not legacy_sidecar_keys
                and legacy_item.get("type") != descriptor.predecessor_type
            )
        ):
            raise RunningRegionError("running-region IR legacy owner differs")
        restored_legacy_item = deepcopy(dict(legacy_item))
        if legacy_sidecar_keys:
            for key in _SIDECAR_KEYS:
                restored_legacy_item.pop(key, None)
        restored_legacy_item["type"] = descriptor.predecessor_type
        element.properties = {
            **element.properties,
            "legacy_item": restored_legacy_item,
        }
        element.type = descriptor.predecessor_type
        element.running_region = None
        restored_elements.append(element)
    cleaned.elements = restored_elements
    cleaned.bboxes = [
        value for value in cleaned.bboxes if value.id not in extracted_bbox_ids
    ]
    cleaned.evidence = [
        value
        for value in cleaned.evidence
        if value.id not in extracted_evidence_ids
        and value.element_id not in extracted_element_ids
    ]
    for page in cleaned.pages:
        page.page_identity = None
        page.element_ids = [
            value for value in page.element_ids if value not in extracted_element_ids
        ]
        page.presentation_element_ids = [
            value
            for value in page.presentation_element_ids
            if value not in extracted_element_ids
        ]
    for region in cleaned.regions:
        region.element_ids = [
            value for value in region.element_ids if value not in extracted_element_ids
        ]
    return DocumentIR.model_validate(cleaned.model_dump(mode="json"))


def _validate_replay_identity_payload(
    value: Mapping[str, Any],
) -> dict[str, RunningRegionDescriptor]:
    """Validate a helper-issued replay identity before using it as a baseline."""

    if set(value) != _REPLAY_IDENTITY_KEYS:
        raise RunningRegionError("running-region replay identity differs")
    summary = value.get("summary")
    pages = value.get("pages")
    regions = value.get("regions")
    if (
        not isinstance(summary, Mapping)
        or set(summary) != set(_REPLAY_SUMMARY_IDENTITY_KEYS)
        or summary.get("policy_id") != POLICY_ID
        or summary.get("status") != "projected"
        or summary.get("reason") is not None
        or not isinstance(pages, list)
        or not isinstance(regions, list)
    ):
        raise RunningRegionError("running-region replay identity differs")
    for name in _SUMMARY_ZERO_KEYS:
        observed = summary.get(name)
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            raise RunningRegionError("running-region replay count differs")

    page_indexes: list[int] = []
    for expected_offset, page in enumerate(pages):
        if not isinstance(page, Mapping) or set(page) != _REPLAY_PAGE_KEYS:
            raise RunningRegionError("running-region replay page differs")
        page_offset = page.get("page_offset")
        page_index = page.get("page_index")
        if (
            page_offset != expected_offset
            or isinstance(page_index, bool)
            or not isinstance(page_index, int)
            or page_index != expected_offset + 1
        ):
            raise RunningRegionError("running-region replay page order differs")
        identity = PageIdentity.model_validate(page.get("page_identity"))
        if identity.physical_page_index != page_index:
            raise RunningRegionError("running-region replay page identity differs")
        page_indexes.append(page_index)

    descriptors: dict[str, RunningRegionDescriptor] = {}
    positions: list[tuple[int, int]] = []
    role_counts = {
        "header": 0,
        "footer": 0,
        "navigation_top": 0,
        "navigation_bottom": 0,
    }
    for region in regions:
        if not isinstance(region, Mapping) or set(region) != _REPLAY_REGION_KEYS:
            raise RunningRegionError("running-region replay descriptor differs")
        page_offset = region.get("page_offset")
        item_offset = region.get("item_offset")
        item_id = region.get("item_id")
        if (
            isinstance(page_offset, bool)
            or not isinstance(page_offset, int)
            or not 0 <= page_offset < len(pages)
            or isinstance(item_offset, bool)
            or not isinstance(item_offset, int)
            or item_offset < 0
            or not isinstance(item_id, str)
            or not item_id
        ):
            raise RunningRegionError("running-region replay position differs")
        position = (page_offset, item_offset)
        if positions and position <= positions[-1]:
            raise RunningRegionError("running-region replay order differs")
        positions.append(position)
        descriptor = RunningRegionDescriptor.model_validate(region.get("descriptor"))
        if (
            descriptor.id in descriptors
            or descriptor.physical_page_index != page_indexes[page_offset]
        ):
            raise RunningRegionError("running-region replay descriptor differs")
        descriptors[descriptor.id] = descriptor
        role_counts[descriptor.role] += 1

    if (
        summary["source_page_count"] != len(pages)
        or summary["identity_count"] != len(pages)
        or summary["running_region_count"] != len(regions)
        or summary["header_count"] != role_counts["header"]
        or summary["footer_count"] != role_counts["footer"]
        or summary["top_navigation_count"] != role_counts["navigation_top"]
        or summary["bottom_navigation_count"] != role_counts["navigation_bottom"]
    ):
        raise RunningRegionError("running-region replay coverage differs")
    return descriptors


def running_region_replay_identity(
    public_document: Mapping[str, Any],
    *,
    baseline_identity: Mapping[str, Any] | None = None,
    alignment_authorized_owner_ids: Sequence[str] = (),
    alignment_authorized_owner_ids_by_page: Mapping[
        int, Sequence[str]
    ]
    | None = None,
) -> dict[str, Any]:
    """Return the exact ordered US08 identity frozen across terminal replay.

    Terminal source alignment may change a descriptor predecessor hash only
    when its source public owner is explicitly named by a validated alignment
    selection.  Every page identity, descriptor field, position, and
    non-timing processing count remains part of the comparison.
    """

    if not isinstance(public_document, Mapping):
        raise RunningRegionError("running-region replay document differs")
    processing = public_document.get("processing")
    raw_summary = (
        processing.get("running_regions") if isinstance(processing, Mapping) else None
    )
    summary = RunningRegionsProcessingSummary.model_validate(raw_summary)
    if summary.status != "projected":
        raise RunningRegionError("running-region replay is not projected")

    if isinstance(alignment_authorized_owner_ids, (str, bytes, bytearray)):
        raise RunningRegionError("running-region replay authorization differs")
    authorized_owner_ids = tuple(alignment_authorized_owner_ids)
    if any(not isinstance(value, str) or not value for value in authorized_owner_ids):
        raise RunningRegionError("running-region replay authorization differs")
    if len(authorized_owner_ids) != len(set(authorized_owner_ids)):
        raise RunningRegionError("running-region replay authorization repeats")
    authorized_by_page: dict[int, tuple[str, ...]] = {}
    if alignment_authorized_owner_ids_by_page is not None:
        if (
            not isinstance(alignment_authorized_owner_ids_by_page, Mapping)
            or len(alignment_authorized_owner_ids_by_page) > MAX_PAGES
        ):
            raise RunningRegionError("running-region replay authorization differs")
        observed_authorized_ids: set[str] = set()
        for page_index, raw_ids in alignment_authorized_owner_ids_by_page.items():
            if (
                type(page_index) is not int
                or page_index < 1
                or not isinstance(raw_ids, Sequence)
                or isinstance(raw_ids, (str, bytes, bytearray))
            ):
                raise RunningRegionError(
                    "running-region replay authorization differs"
                )
            page_ids = tuple(raw_ids)
            if (
                any(type(value) is not str or not value for value in page_ids)
                or len(page_ids) != len(set(page_ids))
                or observed_authorized_ids.intersection(page_ids)
            ):
                raise RunningRegionError(
                    "running-region replay authorization differs"
                )
            observed_authorized_ids.update(page_ids)
            authorized_by_page[page_index] = page_ids
    if authorized_owner_ids and authorized_by_page:
        raise RunningRegionError("running-region replay authorization differs")
    if baseline_identity is None and (authorized_owner_ids or authorized_by_page):
        raise RunningRegionError("running-region replay baseline is absent")
    baseline_descriptors = (
        _validate_replay_identity_payload(baseline_identity)
        if baseline_identity is not None
        else {}
    )
    baseline_regions_by_id: dict[str, Mapping[str, Any]] = {}
    if baseline_identity is not None:
        for raw_region in baseline_identity["regions"]:
            descriptor = RunningRegionDescriptor.model_validate(
                raw_region["descriptor"]
            )
            baseline_regions_by_id[descriptor.id] = raw_region
    position_normalized = False

    pages = public_document.get("pages")
    if not isinstance(pages, list):
        raise RunningRegionError("running-region replay pages differ")
    page_records: list[dict[str, Any]] = []
    region_records: list[dict[str, Any]] = []
    display_counts = {
        "detected_printed_label": 0,
        "embedded_label": 0,
        "legacy_fallback": 0,
    }
    for page_offset, page in enumerate(pages):
        if not isinstance(page, Mapping):
            raise RunningRegionError("running-region replay page differs")
        page_index = page.get("page_index")
        if (
            isinstance(page_index, bool)
            or not isinstance(page_index, int)
            or page_index != page_offset + 1
        ):
            raise RunningRegionError("running-region replay page order differs")
        identity = PageIdentity.model_validate(page.get("page_identity"))
        if identity.physical_page_index != page_index:
            raise RunningRegionError("running-region replay page identity differs")
        if identity.display_source == "detected_printed_label":
            display_counts["detected_printed_label"] += 1
        elif identity.display_source == "embedded_label":
            display_counts["embedded_label"] += 1
        else:
            display_counts["legacy_fallback"] += 1
        page_records.append(
            {
                "page_offset": page_offset,
                "page_index": page_index,
                "page_identity": identity.model_dump(mode="json"),
            }
        )
        items = page.get("items")
        if not isinstance(items, list):
            raise RunningRegionError("running-region replay items differ")
        for item_offset, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            sidecar_keys = set(item).intersection(_SIDECAR_KEYS)
            if sidecar_keys and sidecar_keys != set(_SIDECAR_KEYS):
                raise RunningRegionError("partial running-region sidecar")
            if not sidecar_keys:
                continue
            if (
                item.get("layout_running_region_projected") is not True
                or item.get("running_region_policy") != POLICY_ID
                or not isinstance(item.get("id"), str)
                or not item["id"]
            ):
                raise RunningRegionError("running-region replay sidecar differs")
            descriptor = RunningRegionDescriptor.model_validate(
                item.get("running_region")
            )
            descriptor_payload = descriptor.model_dump(mode="json")
            page_authorized_owner_ids = authorized_by_page.get(
                page_index,
                authorized_owner_ids,
            )
            baseline_descriptor = baseline_descriptors.get(descriptor.id)
            baseline_region = baseline_regions_by_id.get(descriptor.id)
            current_item_offset = item_offset
            position_shift_authorized = False
            if baseline_descriptor is not None and baseline_region is not None:
                baseline_item_offset = baseline_region["item_offset"]
                if current_item_offset < baseline_item_offset:
                    page_items = pages[page_offset].get("items")
                    baseline_path = baseline_descriptor.source_public_path
                    surviving_ids = {
                        str(raw_item.get("id") or "")
                        for raw_item in page_items
                        if isinstance(raw_item, Mapping)
                    } if isinstance(page_items, list) else set()
                    removed_owner_ids = {
                        value
                        for value in page_authorized_owner_ids
                        if value not in surviving_ids
                    }
                    if (
                        not isinstance(page_items, list)
                        or not isinstance(baseline_path, list)
                        or len(baseline_path) < 4
                        or baseline_path[:3]
                        != ["pages", page_offset, "items"]
                        or baseline_path[3] != baseline_item_offset
                        or len(removed_owner_ids)
                        != baseline_item_offset - current_item_offset
                    ):
                        raise RunningRegionError(
                            "running-region replay authorization differs"
                        )
                    position_shift_authorized = True
            if (
                baseline_descriptor is not None
                and baseline_region is not None
                and baseline_descriptor.source_public_item_id
                == descriptor.source_public_item_id
                and (
                    descriptor.source_public_item_id in page_authorized_owner_ids
                    or position_shift_authorized
                )
            ):
                descriptor_payload["predecessor_item_sha256"] = (
                    baseline_descriptor.predecessor_item_sha256
                )
                # A validated terminal source selection may remove a rejected
                # body owner before an otherwise unchanged running-region
                # item.  Replay necessarily updates the owner's public path
                # and list offset to that compacted public sequence.  Compare
                # those two positional scalars using the baseline identity,
                # but only when every intervening removed item is explicitly
                # named by the alignment transaction.  Descriptor identity,
                # page identity, item identity, region order, and coverage
                # remain exact below.
                if position_shift_authorized:
                    descriptor_payload["source_public_path"] = list(
                        baseline_descriptor.source_public_path
                    )
                    current_item_offset = baseline_region["item_offset"]
                    position_normalized = True
            region_records.append(
                {
                    "page_offset": page_offset,
                    "item_offset": current_item_offset,
                    "item_id": item["id"],
                    "descriptor": descriptor_payload,
                }
            )

    if baseline_identity is not None and position_normalized:
        # Candidate comparison counts depend on the number of surviving public
        # owners and may shrink after a source-proven rejection.  Normalize
        # only this derived count to its already-validated baseline; every
        # semantic count remains independently checked by coverage validation.
        result_comparison_count = baseline_identity["summary"][
            "comparison_count"
        ]
    else:
        result_comparison_count = summary.comparison_count

    summary_payload = summary.model_dump(mode="json")
    summary_payload["comparison_count"] = result_comparison_count
    result = {
        "summary": {key: summary_payload[key] for key in _REPLAY_SUMMARY_IDENTITY_KEYS},
        "pages": page_records,
        "regions": region_records,
    }
    if (
        result["summary"]["detected_label_count"]
        != display_counts["detected_printed_label"]
        or result["summary"]["embedded_label_count"] != display_counts["embedded_label"]
        or result["summary"]["legacy_fallback_count"]
        != display_counts["legacy_fallback"]
    ):
        raise RunningRegionError("running-region replay display counts differ")
    _validate_replay_identity_payload(result)
    return result


def strip_running_regions(
    public_document: Mapping[str, Any],
    ir_document: DocumentIR | Mapping[str, Any] | None = None,
) -> Any:
    """Remove US08 projection exactly; optionally strip the paired typed IR."""

    if not isinstance(public_document, Mapping):
        raise RunningRegionError("running-region public document differs")
    has_projection = bool(
        isinstance(
            (public_document.get("processing") or {}).get("running_regions"), Mapping
        )
        or public_document.get("running_region_concerns")
        or any(
            isinstance(page, Mapping)
            and (
                "page_identity" in page
                or any(
                    isinstance(item, Mapping)
                    and bool(set(item).intersection(_SIDECAR_KEYS))
                    for item in page.get("items") or []
                )
            )
            for page in public_document.get("pages") or []
        )
    )
    if not has_projection:
        if ir_document is None:
            return public_document
        return public_document, ir_document

    cleaned = deepcopy(dict(public_document))
    records: list[tuple[int, Mapping[str, Any], RunningRegionDescriptor]] = []
    descriptors: list[RunningRegionDescriptor] = []
    pages = cleaned.get("pages")
    if not isinstance(pages, list):
        raise RunningRegionError("running-region public pages differ")
    for page in pages:
        if not isinstance(page, MutableMapping) or not isinstance(
            page.get("items"), list
        ):
            raise RunningRegionError("running-region public page differs")
        page_index = int(page["page_index"])
        page.pop("page_identity", None)
        restored_items: list[Any] = []
        for item in page["items"]:
            if not isinstance(item, MutableMapping):
                restored_items.append(item)
                continue
            keys = set(item).intersection(_SIDECAR_KEYS)
            if not keys:
                restored_items.append(item)
                continue
            if keys != set(_SIDECAR_KEYS):
                raise RunningRegionError("partial running-region sidecar")
            descriptor = RunningRegionDescriptor.model_validate(item["running_region"])
            if (
                item["layout_running_region_projected"] is not True
                or item["running_region_policy"] != POLICY_ID
            ):
                raise RunningRegionError("running-region sidecar differs")
            descriptors.append(descriptor)
            owner = _resolve_path(cleaned, descriptor.source_public_path)
            if not isinstance(owner, Mapping):
                raise RunningRegionError("running-region rollback owner differs")
            records.append((page_index, owner, descriptor))
            if descriptor.source_method == "extracted_source_contribution":
                continue
            restored = deepcopy(dict(item))
            for key in _SIDECAR_KEYS:
                restored.pop(key, None)
            restored["type"] = descriptor.predecessor_type
            restored_items.append(restored)
        page["items"] = restored_items

    if isinstance(cleaned.get("canonical_presentation"), Mapping):
        _strip_public_canonical(cleaned, records)
    processing = cleaned.get("processing")
    if isinstance(processing, MutableMapping):
        processing.pop("running_regions", None)
    cleaned.pop("running_region_concerns", None)
    if ir_document is None:
        return cleaned
    return cleaned, _strip_ir_document(ir_document, descriptors)


def replay_running_regions_identity_locked(
    stripped_public: Mapping[str, Any],
    rebuilt_ir: DocumentIR | Mapping[str, Any],
    source_pdf_bytes: bytes,
    *,
    baseline_projected_public: Mapping[str, Any],
    baseline_projected_ir: DocumentIR | Mapping[str, Any],
    baseline_identity: Mapping[str, Any],
    alignment_authorized_owner_ids_by_page: Mapping[int, Sequence[str]],
    alignment_selections: Sequence[Mapping[str, Any]],
    prior_summary: Mapping[str, Any] | None = None,
    metrics: MutableMapping[str, Any] | None = None,
) -> tuple[dict[str, Any], DocumentIR]:
    """Replay an exact prior direct-owner projection without redetection.

    Terminal source alignment can expose text which was deliberately ignored
    by the earlier running-region detector.  Re-running that detector would
    therefore change page identity or mint new regions.  This path instead
    authenticates the complete prior projection, proves that the terminal
    item sequence differs only by page-scoped authorized deletions, and
    relocates the same direct owners.  Extracted-source contributions are not
    reconstructible from the public replay identity and fail closed here.
    """

    started_ns = time.perf_counter_ns()
    if (
        not isinstance(source_pdf_bytes, bytes)
        or not source_pdf_bytes
        or len(source_pdf_bytes) > MAX_SOURCE_PDF_BYTES
        or not isinstance(baseline_projected_public, Mapping)
        or not isinstance(alignment_authorized_owner_ids_by_page, Mapping)
        or not isinstance(alignment_selections, Sequence)
        or isinstance(alignment_selections, (str, bytes, bytearray))
    ):
        raise RunningRegionError("identity-locked running-region input differs")

    baseline_descriptors = _validate_replay_identity_payload(baseline_identity)
    observed_baseline_identity = running_region_replay_identity(
        baseline_projected_public
    )
    if _strict_json_bytes(observed_baseline_identity) != _strict_json_bytes(
        baseline_identity
    ):
        raise RunningRegionError("identity-locked running-region baseline differs")

    baseline_ir = DocumentIR.model_validate(
        baseline_projected_ir.model_dump(mode="json")
        if isinstance(baseline_projected_ir, DocumentIR)
        else _ir_payload(baseline_projected_ir)
    )
    baseline_source_sha256 = (baseline_projected_public.get("document") or {}).get(
        "sha256"
    )
    if (
        not isinstance(baseline_source_sha256, str)
        or len(baseline_source_sha256) != 64
        or any(value not in "0123456789abcdef" for value in baseline_source_sha256)
        or baseline_ir.source_sha256 != baseline_source_sha256
        or hashlib.sha256(source_pdf_bytes).hexdigest() != baseline_source_sha256
    ):
        raise RunningRegionError("identity-locked running-region source differs")

    baseline_clean_public, baseline_clean_ir = strip_running_regions(
        baseline_projected_public,
        baseline_ir,
    )
    current_processing = stripped_public.get("processing")
    current_pages = stripped_public.get("pages")
    if (
        isinstance(current_processing, Mapping)
        and "running_regions" in current_processing
        or not isinstance(current_pages, list)
        or "running_region_concerns" in stripped_public
        or any(
            not isinstance(page, Mapping)
            or "page_identity" in page
            or any(
                isinstance(item, Mapping)
                and bool(set(item).intersection(_SIDECAR_KEYS))
                for item in page.get("items") or []
            )
            for page in current_pages
        )
    ):
        raise RunningRegionError(
            "identity-locked running-region terminal predecessor is projected"
        )
    clean_ir = DocumentIR.model_validate(
        rebuilt_ir.model_dump(mode="json")
        if isinstance(rebuilt_ir, DocumentIR)
        else _ir_payload(rebuilt_ir)
    )
    if any(value.page_identity is not None for value in clean_ir.pages) or any(
        value.running_region is not None for value in clean_ir.elements
    ):
        raise RunningRegionError(
            "identity-locked running-region terminal IR is projected"
        )
    clean_public = stripped_public
    baseline_clean_ir = DocumentIR.model_validate(
        baseline_clean_ir.model_dump(mode="json")
        if isinstance(baseline_clean_ir, DocumentIR)
        else _ir_payload(baseline_clean_ir)
    )
    clean_ir = DocumentIR.model_validate(
        clean_ir.model_dump(mode="json")
        if isinstance(clean_ir, DocumentIR)
        else _ir_payload(clean_ir)
    )
    staged_public = deepcopy(dict(clean_public))
    staged_ir = DocumentIR.model_validate(clean_ir.model_dump(mode="json"))
    current_source_sha256 = (staged_public.get("document") or {}).get("sha256")
    if (
        current_source_sha256 != baseline_source_sha256
        or staged_ir.source_sha256 != baseline_source_sha256
        or baseline_clean_ir.source_sha256 != baseline_source_sha256
    ):
        raise RunningRegionError("identity-locked running-region source differs")

    raw_baseline_pages = baseline_clean_public.get("pages")
    raw_current_pages = staged_public.get("pages")
    if (
        not isinstance(raw_baseline_pages, list)
        or not isinstance(raw_current_pages, list)
        or len(raw_baseline_pages) != len(raw_current_pages)
        or len(raw_baseline_pages) > MAX_PAGES
        or len(raw_baseline_pages) != len(baseline_identity["pages"])
    ):
        raise RunningRegionError("identity-locked running-region pages differ")

    authorized_by_page: dict[int, tuple[str, ...]] = {}
    authorized_document_ids: set[str] = set()
    if len(alignment_authorized_owner_ids_by_page) > MAX_PAGES:
        raise RunningRegionError("identity-locked running-region authorization differs")
    for raw_page_index, raw_owner_ids in alignment_authorized_owner_ids_by_page.items():
        if (
            type(raw_page_index) is not int
            or raw_page_index < 1
            or raw_page_index > MAX_PAGES
            or not isinstance(raw_owner_ids, Sequence)
            or isinstance(raw_owner_ids, (str, bytes, bytearray))
        ):
            raise RunningRegionError(
                "identity-locked running-region authorization differs"
            )
        owner_ids = tuple(raw_owner_ids)
        if (
            len(owner_ids) != len(set(owner_ids))
            or any(type(value) is not str or not value for value in owner_ids)
            or authorized_document_ids.intersection(owner_ids)
        ):
            raise RunningRegionError(
                "identity-locked running-region authorization differs"
            )
        authorized_document_ids.update(owner_ids)
        authorized_by_page[raw_page_index] = owner_ids

    total_item_count = 0
    baseline_item_page: dict[str, int] = {}
    current_document_ids: set[str] = set()
    current_items_by_page: dict[int, dict[str, MutableMapping[str, Any]]] = {}
    baseline_items_by_page: dict[int, dict[str, Mapping[str, Any]]] = {}

    def public_survivor_matches(
        baseline_item: Mapping[str, Any],
        current_item: Mapping[str, Any],
        *,
        baseline_position: int,
        current_position: int,
    ) -> bool:
        baseline_reading_order = baseline_item.get("reading_order")
        current_reading_order = current_item.get("reading_order")
        if (
            type(baseline_reading_order) is not int
            or baseline_reading_order != baseline_position
            or type(current_reading_order) is not int
            or current_reading_order != current_position
        ):
            return False
        normalized_current = deepcopy(dict(current_item))
        normalized_current["reading_order"] = baseline_reading_order
        return _strict_json_bytes(baseline_item) == _strict_json_bytes(
            normalized_current
        )

    for page_offset, (baseline_page, current_page) in enumerate(
        zip(raw_baseline_pages, raw_current_pages, strict=True)
    ):
        if (
            not isinstance(baseline_page, Mapping)
            or not isinstance(current_page, MutableMapping)
            or baseline_page.get("page_index") != page_offset + 1
            or current_page.get("page_index") != page_offset + 1
        ):
            raise RunningRegionError("identity-locked running-region page order differs")
        page_index = page_offset + 1
        baseline_items = baseline_page.get("items")
        current_items = current_page.get("items")
        if not isinstance(baseline_items, list) or not isinstance(current_items, list):
            raise RunningRegionError("identity-locked running-region items differ")
        total_item_count += len(baseline_items) + len(current_items)
        if total_item_count > 2 * MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT:
            raise RunningRegionResourceLimitError(
                "identity-locked running-region item boundary exceeded",
                resource_name="boundary_candidates_per_document",
            )

        baseline_ids: list[str] = []
        baseline_by_id: dict[str, Mapping[str, Any]] = {}
        for baseline_position, item in enumerate(baseline_items):
            item_id = item.get("id") if isinstance(item, Mapping) else None
            if (
                type(item_id) is not str
                or not item_id
                or item_id in baseline_item_page
                or type(item.get("reading_order")) is not int
                or item.get("reading_order") != baseline_position
            ):
                raise RunningRegionError(
                    "identity-locked running-region predecessor item differs"
                )
            baseline_ids.append(item_id)
            baseline_by_id[item_id] = item
            baseline_item_page[item_id] = page_index

        current_ids: list[str] = []
        current_by_id: dict[str, MutableMapping[str, Any]] = {}
        for current_position, item in enumerate(current_items):
            item_id = item.get("id") if isinstance(item, MutableMapping) else None
            if (
                type(item_id) is not str
                or not item_id
                or item_id in current_by_id
                or item_id in current_document_ids
                or type(item.get("reading_order")) is not int
                or item.get("reading_order") != current_position
            ):
                raise RunningRegionError(
                    "identity-locked running-region terminal item differs"
                )
            current_ids.append(item_id)
            current_by_id[item_id] = item
            current_document_ids.add(item_id)

        page_authorized_ids = set(authorized_by_page.get(page_index, ()))
        if any(baseline_item_page.get(value) != page_index for value in page_authorized_ids):
            raise RunningRegionError(
                "identity-locked running-region authorization page differs"
            )
        if set(baseline_ids).difference(current_ids) != page_authorized_ids:
            raise RunningRegionError(
                "identity-locked running-region authorization differs"
            )
        expected_current_ids = [
            value for value in baseline_ids if value not in page_authorized_ids
        ]
        if current_ids != expected_current_ids:
            raise RunningRegionError(
                "identity-locked running-region terminal sequence differs"
            )
        baseline_positions = {
            item_id: item_position
            for item_position, item_id in enumerate(baseline_ids)
        }
        if any(
            not public_survivor_matches(
                baseline_by_id[item_id],
                current_by_id[item_id],
                baseline_position=baseline_positions[item_id],
                current_position=current_position,
            )
            for current_position, item_id in enumerate(current_ids)
        ):
            raise RunningRegionError(
                "identity-locked running-region survivor custody differs"
            )
        baseline_items_by_page[page_index] = baseline_by_id
        current_items_by_page[page_index] = current_by_id
        validate_running_region_deadline("projection_document", started_ns)
    if (
        set(authorized_by_page).difference(range(1, len(raw_baseline_pages) + 1))
        or set(authorized_document_ids).difference(baseline_item_page)
    ):
        raise RunningRegionError("identity-locked running-region authorization differs")

    selection_ids_by_page: dict[int, list[str]] = defaultdict(list)
    if len(alignment_selections) > MAX_RUNNING_REGIONS_PER_DOCUMENT:
        raise RunningRegionResourceLimitError(
            "identity-locked running-region selection boundary exceeded",
            resource_name="running_regions_per_document",
        )
    for selection in alignment_selections:
        if not isinstance(selection, Mapping):
            raise RunningRegionError(
                "identity-locked running-region selection differs"
            )
        owner_id = selection.get("owner_id")
        page_index = selection.get("page_index")
        terminal_reason = selection.get("terminal_reason")
        rejected = selection.get("rejected_ocr_alternative")
        owner_snapshot = (
            rejected.get("owner_snapshot")
            if isinstance(rejected, Mapping)
            else None
        )
        if (
            type(owner_id) is not str
            or not owner_id
            or type(page_index) is not int
            or page_index < 1
            or terminal_reason
            != "selected_vector_source_owned_table_duplicate"
            or not isinstance(owner_snapshot, Mapping)
            or owner_snapshot.get("id") != owner_id
            or baseline_items_by_page.get(page_index, {}).get(owner_id) is None
            or _strict_json_bytes(
                baseline_items_by_page[page_index][owner_id]
            )
            != _strict_json_bytes(owner_snapshot)
        ):
            raise RunningRegionError(
                "identity-locked running-region selection differs"
            )
        selection_ids_by_page[page_index].append(owner_id)
    if {
        page_index: tuple(owner_ids)
        for page_index, owner_ids in selection_ids_by_page.items()
    } != authorized_by_page:
        raise RunningRegionError(
            "identity-locked running-region selection authorization differs"
        )

    # Re-run the independently bounded selected-vector IR transition here so
    # this destructive replay helper cannot be called with an ID-only deletion
    # manifest.  The validator closes every removed owner, surviving public/IR
    # record, deterministic reading-chain bridge, and page/region membership.
    from app.services.pipeline import _validate_selected_vector_ir_transition

    _validate_selected_vector_ir_transition(
        baseline_clean_ir,
        clean_ir,
        alignment_selections,
        staged_public,
    )

    baseline_projected_ir_by_element = {
        value.id: value for value in baseline_ir.elements
    }
    baseline_clean_ir_by_element = {
        value.id: value for value in baseline_clean_ir.elements
    }
    current_ir_by_element = {value.id: value for value in staged_ir.elements}
    baseline_bbox_by_id = {value.id: value for value in baseline_clean_ir.bboxes}
    current_bbox_by_id = {value.id: value for value in staged_ir.bboxes}
    baseline_evidence_by_id = {
        value.id: value for value in baseline_clean_ir.evidence
    }
    current_evidence_by_id = {value.id: value for value in staged_ir.evidence}
    baseline_ir_page_by_index = {
        value.page_index: value for value in baseline_clean_ir.pages
    }
    current_ir_page_by_index = {value.page_index: value for value in staged_ir.pages}

    baseline_clean_canonical = baseline_clean_public.get("canonical_presentation")
    current_canonical = staged_public.get("canonical_presentation")
    baseline_projected_canonical = baseline_projected_public.get(
        "canonical_presentation"
    )
    if not all(
        isinstance(value, Mapping)
        and isinstance(value.get("pages"), list)
        for value in (
            baseline_clean_canonical,
            current_canonical,
            baseline_projected_canonical,
        )
    ):
        raise RunningRegionError("identity-locked running-region canonical differs")

    from app.services.presentation import build_canonical_presentation

    rebuilt_baseline_canonical = build_canonical_presentation(
        baseline_clean_ir
    ).model_dump(mode="json", exclude_none=True)
    rebuilt_current_canonical = build_canonical_presentation(clean_ir).model_dump(
        mode="json", exclude_none=True
    )
    if (
        _strict_json_bytes(rebuilt_baseline_canonical)
        != _strict_json_bytes(baseline_clean_canonical)
        or _strict_json_bytes(rebuilt_current_canonical)
        != _strict_json_bytes(current_canonical)
    ):
        raise RunningRegionError(
            "identity-locked running-region canonical custody differs"
        )

    canonical_indexes: dict[int, dict[tuple[int, str], Mapping[str, Any]]] = {}

    def canonical_index(
        canonical: Mapping[str, Any],
    ) -> dict[tuple[int, str], Mapping[str, Any]]:
        cached = canonical_indexes.get(id(canonical))
        if cached is not None:
            return cached
        pages = canonical.get("pages")
        if not isinstance(pages, list) or len(pages) > MAX_PAGES:
            raise RunningRegionError(
                "identity-locked running-region canonical pages differ"
            )
        result: dict[tuple[int, str], Mapping[str, Any]] = {}
        block_count = 0
        for page in pages:
            page_index = page.get("page_index") if isinstance(page, Mapping) else None
            blocks = page.get("blocks") if isinstance(page, Mapping) else None
            if type(page_index) is not int or not isinstance(blocks, list):
                raise RunningRegionError(
                    "identity-locked running-region canonical page differs"
                )
            for block in blocks:
                block_id = block.get("id") if isinstance(block, Mapping) else None
                key = (page_index, block_id)
                if type(block_id) is not str or not block_id or key in result:
                    raise RunningRegionError(
                        "identity-locked running-region canonical block differs"
                    )
                result[key] = block
                block_count += 1
                if block_count > MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT:
                    raise RunningRegionResourceLimitError(
                        "identity-locked running-region canonical boundary exceeded",
                        resource_name="boundary_candidates_per_document",
                    )
            validate_running_region_deadline("projection_document", started_ns)
        canonical_indexes[id(canonical)] = result
        return result

    def canonical_block(
        canonical: Mapping[str, Any],
        *,
        page_index: int,
        block_id: str,
    ) -> Mapping[str, Any]:
        match = canonical_index(canonical).get((page_index, block_id))
        if match is None:
            raise RunningRegionError(
                "identity-locked running-region canonical block differs"
            )
        return match

    projected_descriptor_payloads: list[dict[str, Any]] = []
    if len(baseline_identity["regions"]) > MAX_RUNNING_REGIONS_PER_DOCUMENT:
        raise RunningRegionResourceLimitError(
            "identity-locked running-region descriptor boundary exceeded",
            resource_name="running_regions_per_document",
        )
    for raw_region in baseline_identity["regions"]:
        descriptor = RunningRegionDescriptor.model_validate(raw_region["descriptor"])
        if (
            descriptor.source_method == "extracted_source_contribution"
            or baseline_descriptors.get(descriptor.id) != descriptor
        ):
            raise RunningRegionError(
                "identity-locked running-region descriptor is not direct"
            )
        page_index = descriptor.physical_page_index
        baseline_owner = baseline_items_by_page.get(page_index, {}).get(
            descriptor.source_public_item_id
        )
        current_owner = current_items_by_page.get(page_index, {}).get(
            descriptor.source_public_item_id
        )
        if (
            baseline_owner is None
            or current_owner is None
            or _sha256_json(_compact_public_item_payload(baseline_owner))
            != descriptor.predecessor_item_sha256
            or current_owner.get("type") != descriptor.predecessor_type
            or set(current_owner).intersection(_SIDECAR_KEYS)
        ):
            raise RunningRegionError(
                "identity-locked running-region owner custody differs"
            )

        baseline_page_items = raw_baseline_pages[page_index - 1]["items"]
        current_page_items = raw_current_pages[page_index - 1]["items"]
        baseline_owner_offset = next(
            (
                offset
                for offset, value in enumerate(baseline_page_items)
                if isinstance(value, Mapping)
                and value.get("id") == descriptor.source_public_item_id
            ),
            None,
        )
        current_owner_offset = next(
            (
                offset
                for offset, value in enumerate(current_page_items)
                if isinstance(value, Mapping)
                and value.get("id") == descriptor.source_public_item_id
            ),
            None,
        )
        if (
            baseline_owner_offset is None
            or current_owner_offset is None
            or descriptor.source_public_path
            != ["pages", page_index - 1, "items", baseline_owner_offset]
            or not public_survivor_matches(
                baseline_owner,
                current_owner,
                baseline_position=baseline_owner_offset,
                current_position=current_owner_offset,
            )
        ):
            raise RunningRegionError(
                "identity-locked running-region owner position differs"
            )

        baseline_projected_element = baseline_projected_ir_by_element.get(
            descriptor.source_element_id
        )
        baseline_element = baseline_clean_ir_by_element.get(
            descriptor.source_element_id
        )
        current_element = current_ir_by_element.get(descriptor.source_element_id)
        baseline_page = baseline_ir_page_by_index.get(page_index)
        current_page = current_ir_page_by_index.get(page_index)
        if (
            baseline_projected_element is None
            or baseline_projected_element.running_region != descriptor
            or baseline_element is None
            or current_element is None
            or baseline_page is None
            or current_page is None
            or baseline_page.id != descriptor.page_id
            or current_page.id != descriptor.page_id
            or baseline_page.presentation_element_ids[baseline_owner_offset]
            != descriptor.source_element_id
            or current_page.presentation_element_ids[current_owner_offset]
            != descriptor.source_element_id
        ):
            raise RunningRegionError(
                "identity-locked running-region element binding differs"
            )

        baseline_element_payload = baseline_element.model_dump(mode="json")
        current_element_payload = current_element.model_dump(mode="json")
        baseline_properties = baseline_element_payload.get("properties")
        current_properties = current_element_payload.get("properties")
        baseline_legacy = (
            baseline_properties.get("legacy_item")
            if isinstance(baseline_properties, MutableMapping)
            else None
        )
        current_legacy = (
            current_properties.get("legacy_item")
            if isinstance(current_properties, MutableMapping)
            else None
        )
        if (
            not isinstance(baseline_properties, MutableMapping)
            or not isinstance(current_properties, MutableMapping)
            or not isinstance(baseline_legacy, MutableMapping)
            or not isinstance(current_legacy, MutableMapping)
            or type(baseline_element_payload.get("reading_order")) is not int
            or baseline_element_payload.get("reading_order")
            != baseline_owner_offset
            or type(current_element_payload.get("reading_order")) is not int
            or current_element_payload.get("reading_order")
            != current_owner_offset
            or type(baseline_properties.get("source_position")) is not int
            or baseline_properties.get("source_position") != baseline_owner_offset
            or type(current_properties.get("source_position")) is not int
            or current_properties.get("source_position") != current_owner_offset
            or type(baseline_legacy.get("reading_order")) is not int
            or baseline_legacy.get("reading_order") != baseline_owner_offset
            or type(current_legacy.get("reading_order")) is not int
            or current_legacy.get("reading_order") != current_owner_offset
            or dict(baseline_legacy) != dict(baseline_owner)
            or dict(current_legacy) != dict(current_owner)
        ):
            raise RunningRegionError(
                "identity-locked running-region source position differs"
            )
        current_element_payload["reading_order"] = baseline_owner_offset
        current_properties["source_position"] = baseline_owner_offset
        current_legacy["reading_order"] = baseline_owner_offset
        if _strict_json_bytes(baseline_element_payload) != _strict_json_bytes(
            current_element_payload
        ):
            raise RunningRegionError(
                "identity-locked running-region element custody differs"
            )

        baseline_bbox = baseline_bbox_by_id.get(descriptor.bbox_id)
        current_bbox = current_bbox_by_id.get(descriptor.bbox_id)
        if (
            baseline_bbox is None
            or current_bbox is None
            or descriptor.bbox_id not in current_element.bbox_ids
            or _strict_json_bytes(baseline_bbox.model_dump(mode="json"))
            != _strict_json_bytes(current_bbox.model_dump(mode="json"))
            or descriptor.bbox.model_dump(mode="json")
            != {
                "x": current_bbox.x,
                "y": current_bbox.y,
                "width": current_bbox.width,
                "height": current_bbox.height,
                "unit": "pt",
            }
        ):
            raise RunningRegionError(
                "identity-locked running-region bbox custody differs"
            )
        descriptor_evidence_ids = list(descriptor.evidence_ids)
        baseline_element_evidence_ids = list(baseline_element.evidence_ids)
        current_element_evidence_ids = list(current_element.evidence_ids)
        if (
            not descriptor_evidence_ids
            or len(descriptor_evidence_ids) != len(set(descriptor_evidence_ids))
            or len(baseline_element_evidence_ids)
            != len(set(baseline_element_evidence_ids))
            or baseline_element_evidence_ids != current_element_evidence_ids
            or current_element_evidence_ids[: len(descriptor_evidence_ids)]
            != descriptor_evidence_ids
        ):
            raise RunningRegionError(
                "identity-locked running-region evidence binding differs"
            )
        for evidence_id in descriptor_evidence_ids:
            baseline_evidence = baseline_evidence_by_id.get(evidence_id)
            current_evidence = current_evidence_by_id.get(evidence_id)
            if (
                baseline_evidence is None
                or current_evidence is None
                or current_evidence.element_id != descriptor.source_element_id
                or current_evidence.bbox_id != descriptor.bbox_id
                or _strict_json_bytes(baseline_evidence.model_dump(mode="json"))
                != _strict_json_bytes(current_evidence.model_dump(mode="json"))
            ):
                raise RunningRegionError(
                    "identity-locked running-region evidence custody differs"
                )
        for evidence_id in current_element_evidence_ids[
            len(descriptor_evidence_ids) :
        ]:
            baseline_evidence = baseline_evidence_by_id.get(evidence_id)
            current_evidence = current_evidence_by_id.get(evidence_id)
            if (
                baseline_evidence is None
                or current_evidence is None
                or current_evidence.element_id != descriptor.source_element_id
                or _strict_json_bytes(baseline_evidence.model_dump(mode="json"))
                != _strict_json_bytes(current_evidence.model_dump(mode="json"))
            ):
                raise RunningRegionError(
                    "identity-locked running-region extra evidence custody differs"
                )

        baseline_regions = [
            value
            for value in baseline_clean_ir.regions
            if descriptor.source_element_id in value.element_ids
        ]
        current_regions = [
            value
            for value in staged_ir.regions
            if descriptor.source_element_id in value.element_ids
        ]
        if (
            len(baseline_regions) != 1
            or len(current_regions) != 1
            or baseline_regions[0].id != current_regions[0].id
            or baseline_regions[0].page_id != current_regions[0].page_id
            or baseline_regions[0].role != current_regions[0].role
            or baseline_regions[0].bbox_id != current_regions[0].bbox_id
        ):
            raise RunningRegionError(
                "identity-locked running-region region custody differs"
            )

        baseline_clean_block = canonical_block(
            baseline_clean_canonical,
            page_index=page_index,
            block_id=descriptor.canonical_block_id,
        )
        current_clean_block = canonical_block(
            current_canonical,
            page_index=page_index,
            block_id=descriptor.canonical_block_id,
        )
        if (
            baseline_clean_block.get("primary_element_id")
            != descriptor.source_element_id
            or _strict_json_bytes(baseline_clean_block)
            != _strict_json_bytes(current_clean_block)
        ):
            raise RunningRegionError(
                "identity-locked running-region canonical custody differs"
            )

        descriptor_payload = descriptor.model_dump(mode="json")
        descriptor_payload["source_public_path"] = [
            "pages",
            page_index - 1,
            "items",
            current_owner_offset,
        ]
        descriptor_payload["predecessor_item_sha256"] = _sha256_json(
            _compact_public_item_payload(current_owner)
        )
        relocated = RunningRegionDescriptor.model_validate(descriptor_payload)
        _stage_direct_candidate(
            owner=current_owner,
            descriptor=relocated,
            ir_document=staged_ir,
        )
        projected_descriptor_payloads.append(relocated.model_dump(mode="json"))
        validate_running_region_deadline("projection_document", started_ns)

    baseline_pages_by_index = {
        int(value["page_index"]): value
        for value in baseline_identity["pages"]
        if isinstance(value, Mapping)
    }
    for page in staged_public["pages"]:
        page_index = page.get("page_index") if isinstance(page, MutableMapping) else None
        ir_page = current_ir_page_by_index.get(page_index)
        baseline_page = baseline_pages_by_index.get(page_index)
        if (
            not isinstance(page, MutableMapping)
            or ir_page is None
            or baseline_page is None
        ):
            raise RunningRegionError(
                "identity-locked running-region page identity differs"
            )
        identity = PageIdentity.model_validate(baseline_page["page_identity"])
        if identity.page_id != ir_page.id:
            raise RunningRegionError(
                "identity-locked running-region page identity differs"
            )
        page["page_identity"] = identity.model_dump(mode="json")
        ir_page.page_identity = identity

    staged_ir = staged_ir.validate_graph()
    staged_public["canonical_presentation"] = _build_projected_canonical(
        staged_ir,
        (),
        current_canonical,
    )
    for descriptor_payload in projected_descriptor_payloads:
        descriptor = RunningRegionDescriptor.model_validate(descriptor_payload)
        projected_block = canonical_block(
            staged_public["canonical_presentation"],
            page_index=descriptor.physical_page_index,
            block_id=descriptor.canonical_block_id,
        )
        baseline_projected_block = canonical_block(
            baseline_projected_canonical,
            page_index=descriptor.physical_page_index,
            block_id=descriptor.canonical_block_id,
        )
        if _strict_json_bytes(projected_block) != _strict_json_bytes(
            baseline_projected_block
        ):
            raise RunningRegionError(
                "identity-locked running-region projected canonical differs"
            )

    baseline_summary_raw = (baseline_projected_public.get("processing") or {}).get(
        "running_regions"
    )
    baseline_summary = RunningRegionsProcessingSummary.model_validate(
        baseline_summary_raw
    )
    if baseline_summary.status != "projected":
        raise RunningRegionError("identity-locked running-region summary differs")
    if prior_summary is not None and _strict_json_bytes(prior_summary) != (
        _strict_json_bytes(baseline_summary.model_dump(mode="json"))
    ):
        raise RunningRegionError("identity-locked running-region summary differs")
    projection_ms = round(
        baseline_summary.projection_ms
        + validate_running_region_deadline("projection_document", started_ns) * 1000,
        3,
    )
    summary_payload = baseline_summary.model_dump(mode="json")
    summary_payload["projection_ms"] = projection_ms
    summary_payload["total_ms"] = round(
        baseline_summary.extraction_ms + projection_ms,
        3,
    )
    summary_payload = RunningRegionsProcessingSummary.model_validate(
        summary_payload
    ).model_dump(mode="json")
    processing = staged_public.setdefault("processing", {})
    if not isinstance(processing, MutableMapping):
        raise RunningRegionError("identity-locked running-region processing differs")
    processing["running_regions"] = summary_payload
    baseline_concerns = baseline_projected_public.get("running_region_concerns")
    if baseline_summary.concern_count:
        if (
            not isinstance(baseline_concerns, list)
            or len(baseline_concerns) != baseline_summary.concern_count
        ):
            raise RunningRegionError("identity-locked running-region concerns differ")
        validated_concerns = [
            ProjectedRunningRegionConcern.model_validate(value).model_dump(mode="json")
            for value in baseline_concerns
        ]
        if _strict_json_bytes(validated_concerns) != _strict_json_bytes(
            baseline_concerns
        ):
            raise RunningRegionError("identity-locked running-region concerns differ")
        staged_public["running_region_concerns"] = deepcopy(validated_concerns)
    elif baseline_concerns not in (None, []):
        raise RunningRegionError("identity-locked running-region concerns differ")
    else:
        staged_public.pop("running_region_concerns", None)

    replay_identity = running_region_replay_identity(
        staged_public,
        baseline_identity=baseline_identity,
        alignment_authorized_owner_ids_by_page=authorized_by_page,
    )
    if _strict_json_bytes(replay_identity) != _strict_json_bytes(baseline_identity):
        raise RunningRegionError("identity-locked running-region replay differs")
    if metrics is not None:
        metrics.update(summary_payload)
    return staged_public, staged_ir


def _failed_closed_replay(
    predecessor_public: Mapping[str, Any],
    predecessor_ir: DocumentIR,
    *,
    metrics: MutableMapping[str, Any] | None,
) -> tuple[dict[str, Any], DocumentIR]:
    failed = deepcopy(dict(predecessor_public))
    summary = RunningRegionsProcessingSummary.model_validate(
        {
            "policy_id": POLICY_ID,
            "status": "failed_closed",
            "reason": "running_region_projection_failed_closed",
            **{key: 0 for key in _SUMMARY_ZERO_KEYS},
            "concern_count": 1,
            "extraction_ms": 0.0,
            "projection_ms": 0.0,
            "total_ms": 0.0,
        }
    ).model_dump(mode="json")
    processing = failed.setdefault("processing", {})
    if not isinstance(processing, MutableMapping):
        processing = {}
        failed["processing"] = processing
    processing["running_regions"] = summary
    failed["running_region_concerns"] = [
        {"code": "running_region_projection_failed_closed"}
    ]
    if metrics is not None:
        metrics.update(summary)
    return failed, predecessor_ir


def replay_running_regions(
    stripped_public: Mapping[str, Any],
    rebuilt_ir: DocumentIR | Mapping[str, Any],
    source_pdf_bytes: bytes,
    *,
    prior_summary: Mapping[str, Any] | None = None,
    metrics: MutableMapping[str, Any] | None = None,
) -> tuple[dict[str, Any], DocumentIR]:
    """Terminally replay US08 after an earlier phase rebuilt public/IR state."""

    clean_public, clean_ir = strip_running_regions(stripped_public, rebuilt_ir)
    clean_ir = DocumentIR.model_validate(
        clean_ir.model_dump(mode="json")
        if isinstance(clean_ir, DocumentIR)
        else _ir_payload(clean_ir)
    )
    try:
        authority = prepare_source_projection_authority(
            {
                "public": clean_public,
                "ir": clean_ir.model_dump(mode="json", exclude_none=True),
            },
            source_pdf_bytes,
        )
        projected, projected_ir = project_running_regions(
            clean_public,
            clean_ir,
            authority,
        )
        if prior_summary is not None:
            prior = RunningRegionsProcessingSummary.model_validate(prior_summary)
            current = projected["processing"]["running_regions"]
            extraction_ms = prior.extraction_ms
            projection_ms = round(
                prior.projection_ms + float(current["projection_ms"]), 3
            )
            current["extraction_ms"] = extraction_ms
            current["projection_ms"] = projection_ms
            current["total_ms"] = round(extraction_ms + projection_ms, 3)
        if metrics is not None:
            metrics.update(projected["processing"]["running_regions"])
        return projected, projected_ir
    except Exception:
        return _failed_closed_replay(
            clean_public,
            clean_ir,
            metrics=metrics,
        )
