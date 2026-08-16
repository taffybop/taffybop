"""Executable readiness contract for P03-US08 running regions/page identity.

The module is test-only and implementation-neutral.  It freezes the closed
source, public, canonical, summary, rollback, and terminal-replay contracts
before the production projector exists.  Production code must not import it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import weakref
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from ctypes import c_uint
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from itertools import pairwise
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, Self

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from app.services.source_text_alignment import (
    extract_source_text_evidence as _extract_phase02_source_text_evidence,
)

POLICY_ID = "p03-running-regions-page-identity-v1"
REPORT_VERSION = "1.0"
SCHEMA_VERSION = "1.0"
COORDINATE_SYSTEM_ID = "pdf-top-left-pt-v1"

# Inclusive production limits frozen by the readiness policy.
MAX_PAGES_PER_DOCUMENT = 100
MAX_SOURCE_PDF_BYTES = 25 * 1024 * 1024
MAX_SOURCE_CHARACTERS_PER_PAGE = 500_000
MAX_SOURCE_CHARACTERS_PER_DOCUMENT = 2_000_000
MAX_SOURCE_WORDS_PER_PAGE = 100_000
MAX_SOURCE_WORDS_PER_DOCUMENT = 500_000
MAX_LABEL_UTF8_BYTES = 256
MAX_VISIBLE_TEXT_UTF8_BYTES = 512
MAX_CANDIDATE_TEXT_UTF8_BYTES = 16 * 1024
MAX_EXTRACTED_CONTRIBUTION_UTF8_BYTES = 4 * 1024
MAX_EXTRACTED_CONTRIBUTIONS_PER_PAGE = 8
MAX_EXTRACTED_CONTRIBUTIONS_PER_DOCUMENT = 64
MAX_EXTRACTED_INTERVALS_PER_CONTRIBUTION = 8
MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_PAGE = 16 * 1024
MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_DOCUMENT = 256 * 1024
MAX_LABEL_CANDIDATES_PER_PAGE = 64
MAX_BOUNDARY_CANDIDATES_PER_PAGE = 512
MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT = 10_000
MAX_RUNNING_REGIONS_PER_PAGE = 64
MAX_RUNNING_REGIONS_PER_DOCUMENT = 2_048
MAX_REPETITION_GROUPS_PER_DOCUMENT = 2_048
MAX_REPETITION_MEMBERS = 100
MAX_REFERENCES_PER_RECORD = 64
MAX_PUBLIC_PATH_SEGMENTS = 16
MAX_COMPARISONS_PER_PAGE = 4_096
MAX_COMPARISONS_PER_DOCUMENT = 65_536
MAX_PAGE_IDENTITY_BYTES = 64 * 1024
MAX_RUNNING_DESCRIPTOR_BYTES = 256 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_CONCERNS_PER_PAGE = 64
MAX_CONCERNS_PER_DOCUMENT = 256
SOURCE_EXTRACTION_DEADLINE_SECONDS = 2.0
PROJECTION_PAGE_DEADLINE_SECONDS = 0.250
PROJECTION_DOCUMENT_DEADLINE_SECONDS = 2.0
NATIVE_LABEL_MIN_CANDIDATE_AREA_COVERAGE = 0.80
NATIVE_LABEL_MAX_VERTICAL_CENTER_DELTA_RATIO = 0.002
EXTRACTED_NATIVE_MIN_CANDIDATE_AREA_COVERAGE = 0.99
EXTRACTED_NATIVE_MIN_CHILD_AREA_COVERAGE = 0.90
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
MAX_LIVE_SOURCE_PROJECTION_AUTHORITIES = 8

RESOURCE_LIMITS: Mapping[str, int | float] = MappingProxyType(
    {
        "pages_per_document": MAX_PAGES_PER_DOCUMENT,
        "source_pdf_bytes": MAX_SOURCE_PDF_BYTES,
        "source_characters_per_page": MAX_SOURCE_CHARACTERS_PER_PAGE,
        "source_characters_per_document": MAX_SOURCE_CHARACTERS_PER_DOCUMENT,
        "source_words_per_page": MAX_SOURCE_WORDS_PER_PAGE,
        "source_words_per_document": MAX_SOURCE_WORDS_PER_DOCUMENT,
        "label_utf8_bytes": MAX_LABEL_UTF8_BYTES,
        "visible_text_utf8_bytes": MAX_VISIBLE_TEXT_UTF8_BYTES,
        "candidate_text_utf8_bytes": MAX_CANDIDATE_TEXT_UTF8_BYTES,
        "extracted_contribution_utf8_bytes": MAX_EXTRACTED_CONTRIBUTION_UTF8_BYTES,
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
        "printed_label_render_dimension_pixels": (
            MAX_PRINTED_LABEL_RENDER_DIMENSION_PX
        ),
        "printed_label_render_pixels": MAX_PRINTED_LABEL_RENDER_PIXELS,
        "printed_label_non_stroking_fills": (MAX_PRINTED_LABEL_NON_STROKING_FILLS),
        "printed_label_page_dimension_points": (
            int(MAX_PRINTED_LABEL_PAGE_DIMENSION_PT)
        ),
        "printed_label_text_objects": MAX_PRINTED_LABEL_TEXT_OBJECTS,
        "printed_label_text_object_scan": MAX_PRINTED_LABEL_TEXT_OBJECT_SCAN,
        "printed_label_form_depth": PRINTED_LABEL_MAX_FORM_DEPTH,
        "live_source_projection_authorities": (MAX_LIVE_SOURCE_PROJECTION_AUTHORITIES),
        "concerns_per_page": MAX_CONCERNS_PER_PAGE,
        "concerns_per_document": MAX_CONCERNS_PER_DOCUMENT,
        "source_extraction_seconds": SOURCE_EXTRACTION_DEADLINE_SECONDS,
        "projection_page_seconds": PROJECTION_PAGE_DEADLINE_SECONDS,
        "projection_document_seconds": PROJECTION_DOCUMENT_DEADLINE_SECONDS,
    }
)

PERFORMANCE_TARGETS = ("uber-earnings", "ny-timetable")
PAIRED_STATE_ORDER = (
    ("off", "on"),
    ("on", "off"),
    ("off", "on"),
    ("on", "off"),
    ("off", "on"),
)
PAIRED_CASES = (
    ("uber-earnings", 0, "off"),
    ("uber-earnings", 0, "on"),
    ("uber-earnings", 1, "on"),
    ("uber-earnings", 1, "off"),
    ("uber-earnings", 2, "off"),
    ("uber-earnings", 2, "on"),
    ("uber-earnings", 3, "on"),
    ("uber-earnings", 3, "off"),
    ("uber-earnings", 4, "off"),
    ("uber-earnings", 4, "on"),
    ("ny-timetable", 0, "off"),
    ("ny-timetable", 0, "on"),
    ("ny-timetable", 1, "on"),
    ("ny-timetable", 1, "off"),
    ("ny-timetable", 2, "off"),
    ("ny-timetable", 2, "on"),
    ("ny-timetable", 3, "on"),
    ("ny-timetable", 3, "off"),
    ("ny-timetable", 4, "off"),
    ("ny-timetable", 4, "on"),
)
PAIRED_WORKER_COUNT = 20
PAIRED_FIXED_CEILINGS_SECONDS: Mapping[str, float] = MappingProxyType(
    {"uber-earnings": 1.4575, "ny-timetable": 2.3380}
)
PEAK_MEMORY_DELTA_CEILING_BYTES = 67_108_864
ISOLATED_SOURCE_EXTRACTION_P95_SECONDS = 0.250
ISOLATED_PROJECTION_P95_SECONDS = 0.050
ISOLATED_LATENCY_WARMUPS = 2
ISOLATED_LATENCY_SAMPLES = 20
ISOLATED_ALLOCATION_WARMUPS = 1
ISOLATED_ALLOCATION_SAMPLES = 5
WHOLE_OUTPUT_TIMING_PATHS = (
    "processing.duration_ms",
    "processing.form_semantics.extraction_ms",
    "processing.form_semantics.projection_ms",
    "processing.form_semantics.total_ms",
    "processing.outline_structure.extraction_ms",
    "processing.outline_structure.projection_ms",
    "processing.outline_structure.total_ms",
    "processing.running_regions.extraction_ms",
    "processing.running_regions.projection_ms",
    "processing.running_regions.total_ms",
)
FINAL_METRICS_ARTIFACT_PATH = (
    "tracker/phase-03-layout/evidence/P03-US08-running-region-metrics.json"
)
FAILED_METRICS_ARTIFACT_PATTERN = re.compile(
    r"^tracker/phase-03-layout/evidence/"
    r"P03-US08-running-region-metrics-attempt-([0-9]{2})-failed\.json$"
)
METRICS_ARTIFACT_FIELDS = (
    "schema_version",
    "record_kind",
    "story",
    "status",
    "generated_at",
    "retained_path",
    "semantic_sha256",
    "measurement",
    "policy",
    "settings_delta",
    "m0_reference",
    "input_custody",
    "predecessor_custody",
    "oracle_custody",
    "contract_custody",
    "synthetic_fixture_custody",
    "code_sha256",
    "dependency_custody",
    "source_extraction",
    "running_region_projection",
    "resource_boundaries",
    "deadline_boundaries",
    "paired_parser",
    "quality",
    "control_matrix",
    "comparison_ledgers",
    "output_sizes",
    "rollback",
    "prior_failed_candidates",
    "failures",
    "aggregate",
    "hosted_requests",
    "hosted_tokens",
    "hosted_cost_usd",
)
METRICS_FAILURE_FIELDS = ("type", "stage", "target_id", "pair_index", "state")
CODE_CUSTODY_RECORD_FIELDS = ("path", "size_bytes", "sha256")
CODE_CUSTODY_FIELDS = ("manifest_sha256", "pre", "post", "pre_post_match")
DEPENDENCY_CUSTODY_FIELDS = (
    "manifests",
    "python_packages",
    "local_tools",
    "runtime",
    "offline_environment",
)
DEPENDENCY_MANIFEST_PATHS = (
    "pyproject.toml",
    "uv.lock",
    "frontend/package.json",
    "frontend/package-lock.json",
)
DEPENDENCY_PACKAGE_FIELDS = ("distribution", "version")
DEPENDENCY_REQUIRED_PYTHON_PACKAGES = (
    "docling",
    "docling-core",
    "pdfminer.six",
    "pdfplumber",
    "pydantic",
    "pypdfium2",
)
DEPENDENCY_LOCAL_TOOL_FIELDS = ("name", "version")
DEPENDENCY_REQUIRED_LOCAL_TOOLS = ("tesseract",)
DEPENDENCY_RUNTIME_FIELDS = ("python_version", "platform")
OFFLINE_ENVIRONMENT_FIELDS = (
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "TOKENIZERS_PARALLELISM",
)
OFFLINE_ENVIRONMENT: Mapping[str, str] = MappingProxyType(
    {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
)
OUTPUT_SIZES_FIELDS = (
    "paired_samples",
    "source_reports",
    "isolated_projection_outputs",
    "maximum_page_identity_json_bytes",
    "maximum_running_descriptor_json_bytes",
    "maximum_source_report_json_bytes",
    "all_within_limits",
)
OUTPUT_SAMPLE_FIELDS = ("target_id", "pair_index", "state", "variants")
OUTPUT_VARIANTS = (
    "raw_json",
    "semantic_json",
    "running_region_semantic_json",
    "serialized_markdown",
    "canonical_body_text",
    "canonical_body_markdown",
    "canonical_full_text",
    "canonical_full_markdown",
)
OUTPUT_IDENTITY_FIELDS = ("size_bytes", "sha256")
MAXIMUM_PAGE_FIXTURE_ID = "synthetic:p03-us08:maximum-page-performance-v1"
MAXIMUM_PAGE_WORKLOAD_FIELDS = (
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
)
MAXIMUM_PAGE_WORKLOAD: Mapping[str, Any] = MappingProxyType(
    {
        "fixture_id": MAXIMUM_PAGE_FIXTURE_ID,
        "policy_id": POLICY_ID,
        "physical_page_index": 1,
        "source_character_count": MAX_SOURCE_CHARACTERS_PER_PAGE,
        "source_word_count": MAX_SOURCE_WORDS_PER_PAGE,
        "label_candidate_count": MAX_LABEL_CANDIDATES_PER_PAGE,
        "boundary_candidate_count": MAX_BOUNDARY_CANDIDATES_PER_PAGE,
        "accepted_running_region_count": MAX_RUNNING_REGIONS_PER_PAGE,
        "extracted_contribution_count": MAX_EXTRACTED_CONTRIBUTIONS_PER_PAGE,
        "extracted_intervals_per_contribution": MAX_EXTRACTED_INTERVALS_PER_CONTRIBUTION,
        "extracted_residual_plan_bytes": MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_PAGE,
        "indexed_comparison_count": MAX_COMPARISONS_PER_PAGE,
        "concern_count": MAX_CONCERNS_PER_PAGE,
        "deadline_seconds": PROJECTION_PAGE_DEADLINE_SECONDS,
    }
)

DISPLAY_SOURCES = (
    "detected_printed_label",
    "embedded_label",
    "legacy_display_fallback",
    "physical",
)
RUNNING_REGION_ROLES = (
    "header",
    "footer",
    "navigation_top",
    "navigation_bottom",
)
SOURCE_METHODS = (
    "trusted_layout_role",
    "cross_page_repetition",
    "boundary_navigation",
    "printed_label_boundary",
    "effective_boundary_cluster",
    "extracted_source_contribution",
)
NAVIGATION_TEXT_CUES = frozenset(
    {"TABLE OF CONTENTS", "CONTENTS", "PREVIOUS", "NEXT", "BACK", "HOME"}
)
NAVIGATION_GLYPH_CUES = frozenset(
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
REPORT_STATUSES = ("available", "unavailable", "refused")
PROCESSING_STATUSES = (
    "projected",
    "unavailable",
    "not_applicable",
    "failed_closed",
)

ROLE_TYPE_SCOPE: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "header": ("header", "header"),
        "footer": ("footer", "footer"),
        "navigation_top": ("header", "header"),
        "navigation_bottom": ("footer", "footer"),
    }
)

CONCERN_CODES = (
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
)
PAGE_IDENTITY_CONCERN_CODES = (
    "running_region_source_evidence_unavailable",
    "running_region_source_limit",
    "running_region_candidate_limit",
    "running_region_geometry_ambiguous",
    "running_region_ownership_conflict",
    "page_identity_embedded_label_invalid",
    "page_identity_detected_label_ambiguous",
    "page_identity_source_conflict",
    "page_identity_display_unsafe",
    "running_region_projection_failed_closed",
    "running_region_concerns_truncated",
)

BBOX_FIELDS = ("x", "y", "width", "height", "unit")
EFFECTIVE_CLUSTER_ITEM_FIELDS = (
    "id",
    "presentation_index",
    "bbox",
    "navigation_cue",
    "normalized_label",
    "claimed",
)
CONFIDENCE_FIELDS = ("scope", "score", "unavailable_reason")
EVIDENCE_SOURCE_FIELDS = (
    "method",
    "reader",
    "page_index",
    "public_item_id",
    "public_path",
    "element_id",
    "bbox_id",
    "evidence_ids",
    "source_object_ids",
)
PAGE_IDENTITY_FIELDS = (
    "schema_version",
    "policy_id",
    "page_id",
    "physical_page_index",
    "embedded_label",
    "detected_printed_label",
    "visible_text",
    "display_label",
    "display_source",
    "evidence_bbox",
    "evidence_source",
    "confidence",
    "concern_codes",
)
RUNNING_REGION_FIELDS = (
    "id",
    "page_id",
    "physical_page_index",
    "role",
    "canonical_scope",
    "source_public_item_id",
    "source_public_path",
    "source_element_id",
    "predecessor_type",
    "predecessor_item_sha256",
    "bbox_id",
    "bbox",
    "evidence_ids",
    "source_object_ids",
    "source_method",
    "repetition_group_id",
    "repetition_page_indexes",
    "confidence",
    "concern_codes",
    "canonical_block_id",
)
RUNNING_REGION_SIDECAR_FIELDS = (
    "layout_running_region_projected",
    "running_region_policy",
    "running_region",
)
SOURCE_REPORT_FIELDS = (
    "report_version",
    "policy_id",
    "source_sha256",
    "status",
    "pages",
    "counts",
    "concern_codes",
    "extraction_ms",
)
SOURCE_PAGE_FIELDS = (
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
)
LABEL_CANDIDATE_FIELDS = (
    "id",
    "visible_text",
    "normalized_label",
    "bbox",
    "source_object_ids",
    "source_method",
    "confidence",
    "concern_codes",
)
BOUNDARY_CANDIDATE_FIELDS = (
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
)
EXTRACTED_EVIDENCE_FIELDS = (
    "id",
    "element_id",
    "method",
    "bbox_id",
    "value",
    "confidence",
    "metadata",
)
EXTRACTED_EVIDENCE_METADATA_FIELDS = (
    "policy_id",
    "source_object_ids",
)
EXTRACTED_EVIDENCE_CONFIDENCE: Mapping[str, Any] = MappingProxyType(
    {
        "scope": "evidence",
        "score": None,
        "unavailable_reason": "not_calibrated",
    }
)
SOURCE_COUNT_FIELDS = (
    "page_count",
    "source_character_count",
    "source_word_count",
    "embedded_label_count",
    "label_candidate_count",
    "boundary_candidate_count",
    "concern_count",
)
PROCESSING_SUMMARY_FIELDS = (
    "policy_id",
    "status",
    "reason",
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
    "extraction_ms",
    "projection_ms",
    "total_ms",
)
FORM_PROCESSING_SUMMARY_FIELDS = (
    "extraction_ms",
    "projection_ms",
    "total_ms",
)
OUTLINE_PROCESSING_SUMMARY_FIELDS = (
    "policy_id",
    "status",
    "reason",
    "group_count",
    "node_count",
    "relationship_count",
    "concern_count",
    "extraction_ms",
    "projection_ms",
    "total_ms",
)
OUTLINE_POLICY_ID = "p03-outline-structure-v1"
SOURCE_ALIGNMENT_POLICY_ID = "p02-source-text-alignment-v1"
SOURCE_ALIGNMENT_SUMMARY_FIELDS = (
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
)
SOURCE_ALIGNMENT_SELECTION_FIELDS = (
    "id",
    "page_index",
    "owner_id",
    "owner_type",
    "owner_bbox",
    "original_text",
    "selected_text",
    "selected_source",
    "source_line_ids",
    "source_character_ids",
    "type1_mapping_ids",
    "source_roles",
    "method",
    "checks",
    "terminal_reason",
    "rejected_ocr_alternative",
)
SOURCE_ALIGNMENT_TRACE_FIELDS = (
    "schema_version",
    "policy_id",
    "source_sha256",
    "selection_id",
    "original_text",
    "selected_text",
    "selected_source",
    "source_line_ids",
    "source_character_ids",
    "type1_mapping_ids",
    "source_roles",
    "method",
    "checks",
    "terminal_reason",
    "rejected_ocr_alternative",
)
SOURCE_ALIGNMENT_EVIDENCE_FIELDS = (
    "schema_version",
    "policy_id",
    "source_sha256",
    "usable",
    "refusal_code",
    "page_count",
    "character_count",
    "line_count",
    "type1_glyph_count",
    "pages",
    "type1_glyphs",
    "diagnostics",
    "elapsed_ms",
)
SOURCE_ALIGNMENT_EVIDENCE_PAGE_FIELDS = (
    "page_index",
    "page_width",
    "page_height",
    "unit",
    "characters",
    "lines",
)
SOURCE_ALIGNMENT_EVIDENCE_CHARACTER_FIELDS = (
    "id",
    "page_index",
    "character_index",
    "raw_code_point",
    "raw_text",
    "text",
    "bbox",
    "fill_rgba",
    "font_ref",
    "font_size",
    "baseline",
    "pdfium_is_hyphen",
    "space_supported",
    "excluded_reason",
    "type1_evidence_ids",
    "corroborating_line_ids",
    "role",
)
SOURCE_ALIGNMENT_EVIDENCE_LINE_FIELDS = (
    "id",
    "page_index",
    "text",
    "raw_text",
    "bbox",
    "source_character_ids",
    "source_character_indexes",
    "type1_evidence_ids",
    "has_unsafe_character",
    "terminal_semantic_hyphen",
)
SOURCE_ALIGNMENT_EVIDENCE_TYPE1_FIELDS = (
    "id",
    "page_index",
    "bbox",
    "font_ref",
    "font_object_id",
    "cid",
    "glyph_name",
    "original_text",
    "recovered_text",
    "role",
    "method",
)
SOURCE_ALIGNMENT_EVIDENCE_BBOX_FIELDS = (
    "x",
    "y",
    "width",
    "height",
    "unit",
)
SOURCE_ALIGNMENT_SOURCE_ROLE_FIELDS = (
    "role",
    "text",
    "page_index",
    "bbox",
    "source_character_indexes",
    "type1_evidence_ids",
)
SOURCE_ALIGNMENT_REJECTED_OCR_FIELDS = (
    "text",
    "source",
    "bbox",
    "confidence",
    "reason",
)
SOURCE_ALIGNMENT_TABLE_OWNED_REASON = (
    "table_owned_complete_source_line_duplicate"
)
SOURCE_ALIGNMENT_TABLE_OWNED_POLICY_ID = (
    "p02-table-owned-supplemental-reconciliation-v1"
)
SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_SCHEMA_VERSION = "1.0"
SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_POLICY_ID = (
    "p02-supplemental-ocr-contributor-v1"
)
SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_FIELDS = (
    "schema_version",
    "policy_id",
    "id",
    "source_document_identity",
    "page_index",
    "region_object_index",
    "region_origin",
    "region_role",
    "line_index",
    "ocr_pass",
    "coordinate_unit",
    "bbox",
    "raw_text",
    "confidence",
)
SOURCE_ALIGNMENT_TABLE_OWNED_REJECTED_OCR_FIELDS = (
    *SOURCE_ALIGNMENT_REJECTED_OCR_FIELDS,
    "ocr_contributor",
    "canonical_owner",
)
SOURCE_ALIGNMENT_TABLE_OWNED_CANONICAL_OWNER_FIELDS = (
    "policy_id",
    "suppression_reason",
    "page_index",
    "coordinate_unit",
    "table_item_id",
    "table_id",
    "candidate_id",
    "table_order",
    "row_index",
    "cell_ids",
    "source_object_ids",
    "evidence_ids",
    "table_bbox",
    "row_bbox",
    "source_line_bbox",
    "content_coverage",
    "source_character_geometry_coverage",
)
SOURCE_ALIGNMENT_TABLE_TRACE_FIELDS = (
    "schema_version",
    "policy_id",
    "source_sha256",
    "selection_ids",
)
_SOURCE_ALIGNMENT_BASE_CHECKS = frozenset(
    {
        "finite_geometry",
        "single_page",
        "printable_unicode",
        "bounded_candidate",
        "source_hash_bound",
    }
)
_SOURCE_ALIGNMENT_METHOD_CHECKS = MappingProxyType(
    {
        "type1_encoding_differences": frozenset(
            {"closed_glyph_allowlist", "font_cid_geometry_match"}
        ),
        "pdfium_semantic_hyphen": frozenset(
            {"pdfium_is_hyphen", "same_document_corroboration"}
        ),
        "pdfium_spacing_diaeresis": frozenset(
            {"same_font_run", "mark_overlap", "nfc_composition"}
        ),
        "pdfium_nonlexical_overlay": frozenset(
            {"fill_color_grounded", "tight_nontext_enclosure"}
        ),
        "pdfium_source_space": frozenset({"encoded_u0020", "space_geometry"}),
        "pdfium_native_text": frozenset({"unique_owner_alignment"}),
        "source_safe_native_token": frozenset(
            {
                "native_token_overlap",
                "unique_complete_line",
                "ocr_evidence_retained",
            }
        ),
    }
)
_SOURCE_ALIGNMENT_TABLE_OWNED_CHECKS = frozenset(
    {
        "canonical_table_authority",
        "same_page_coordinate_unit",
        "source_character_geometry_coverage",
        "complete_table_cell_content_coverage",
        "unique_table_row_owner",
        "table_cell_source_lineage",
    }
)
_SOURCE_ALIGNMENT_EMISSION_EXCLUSIONS = frozenset(
    {
        "unsafe_unicode",
        "invalid_hyphen_sentinel_bbox",
        "uncorroborated_hyphen_sentinel",
        "ambiguous_type1_geometry",
        "conflicting_type1_geometry",
        "transparent_text",
        "white_icon_overlay",
    }
)
_SOURCE_ALIGNMENT_FATAL_SELECTION_EXCLUSIONS = frozenset(
    {
        "unsafe_unicode",
        "invalid_hyphen_sentinel_bbox",
        "uncorroborated_hyphen_sentinel",
        "ambiguous_type1_geometry",
        "conflicting_type1_geometry",
    }
)
_SOURCE_ALIGNMENT_NATIVE_BOUNDARY_PUNCTUATION = frozenset(
    {",", ".", ";", ":", "!", "?"}
)
PROJECTED_CONCERN_FIELDS = (
    "code",
    "source_ref",
    "count",
    "cap",
    "exception_class",
)
COMPARISON_LEDGER_FIELDS = ("page_index", "comparison_count")

PUBLIC_PAGE_IDENTITY_KEY = "page_identity"
PUBLIC_RUNNING_REGION_KEYS = frozenset(RUNNING_REGION_SIDECAR_FIELDS)
_HEX = frozenset("0123456789abcdef")
_ALLOWED_ASCII_PUNCTUATION = frozenset(" ._-:/|()")
_DETECTED_INTEGER = r"[1-9][0-9]{0,5}"
_INTEGER_RE = re.compile(rf"^({_DETECTED_INTEGER})$")
_FRACTION_RE = re.compile(rf"^({_DETECTED_INTEGER})\s*/\s*({_DETECTED_INTEGER})$")
_PAGE_OF_RE = re.compile(
    rf"^page\s+({_DETECTED_INTEGER})\s+of\s+({_DETECTED_INTEGER})$", re.IGNORECASE
)
_PIPE_RE = re.compile(rf"^page\s*\|\s*({_DETECTED_INTEGER})$", re.IGNORECASE)
_NORMALIZED_FRACTION_RE = re.compile(rf"^({_DETECTED_INTEGER})/({_DETECTED_INTEGER})$")
_NORMALIZED_PAGE_OF_RE = re.compile(
    rf"^({_DETECTED_INTEGER}) of ({_DETECTED_INTEGER})$"
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
_EXTRACTED_SOURCE_EXCLUDED_OWNER_KINDS = frozenset(
    {
        "table",
        "table_value",
        "table_cell",
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
_PRIOR_SEMANTIC_MARKER_KEYS = frozenset(
    {
        "layout_forms_projected",
        "form_semantics",
        "form_group",
        "form_fields",
        "form_labels",
        "form_value_regions",
        "layout_outline_structure_projected",
        "outline_structure",
        "outline_node",
        "layout_source_notes_projected",
        "source_notes",
        "source_note",
        "footnotes",
        "layout_visual_relationships_projected",
        "visual_relationships",
        "chart_data",
        "layout_table_structure_projected",
        "table_structure",
    }
)


class ReadinessContractError(ValueError):
    """Raised when a readiness witness violates the frozen US08 policy."""


def _exact_keys(value: Mapping[str, Any], expected: Sequence[str], path: str) -> None:
    if set(value) != set(expected):
        raise ReadinessContractError(f"{path} closed keys differ")


def strict_json_bytes(value: Any) -> bytes:
    """Apply the normative compact UTF-8 JSON byte rule."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReadinessContractError("value is not strict JSON") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(strict_json_bytes(value)).hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    """Return the normative stable-ID framing without label/display inputs."""

    return f"{prefix}-{sha256_json(parts)[:20]}"


def extracted_evidence_record_id(
    *,
    source_sha256: str,
    physical_page_index: int,
    source_public_item_id: str,
    source_object_ids: Sequence[str],
    bbox_id: str,
    role: str,
) -> str:
    """Return the acyclic deterministic ID for additive extracted evidence."""

    if not _is_hash(source_sha256):
        raise ReadinessContractError("extracted evidence source hash differs")
    physical = _index(
        physical_page_index,
        "extracted_evidence.physical_page_index",
        maximum=MAX_PAGES_PER_DOCUMENT,
    )
    owner_id = _string(
        source_public_item_id,
        "extracted_evidence.source_public_item_id",
        maximum_bytes=512,
    )
    objects = _references(
        source_object_ids,
        "extracted_evidence.source_object_ids",
        allow_empty=False,
    )
    bounded_bbox_id = _string(bbox_id, "extracted_evidence.bbox_id", maximum_bytes=512)
    if role not in RUNNING_REGION_ROLES:
        raise ReadinessContractError("extracted evidence role differs")
    return stable_id(
        "running-region-evidence",
        POLICY_ID,
        source_sha256,
        physical,
        owner_id,
        objects,
        bounded_bbox_id,
        role,
    )


def label_candidate_id(
    *,
    source_sha256: str,
    physical_page_index: int,
    source_object_ids: Sequence[str],
    bbox: Mapping[str, Any],
) -> str:
    """Return the source-scoped deterministic printed-label candidate ID."""

    if not _is_hash(source_sha256):
        raise ReadinessContractError("label candidate source hash differs")
    physical = _index(
        physical_page_index,
        "label_candidate.physical_page_index",
        maximum=MAX_PAGES_PER_DOCUMENT,
    )
    objects = _references(
        source_object_ids, "label_candidate.source_object_ids", allow_empty=False
    )
    canonical_bbox = _canonical_bbox(bbox, path="label_candidate.bbox")
    return stable_id(
        "label-candidate",
        POLICY_ID,
        source_sha256,
        physical,
        objects,
        canonical_bbox,
    )


def boundary_candidate_id(
    candidate: Mapping[str, Any],
    *,
    source_sha256: str,
    physical_page_index: int,
) -> str:
    """Return the exact source-scoped boundary-candidate ID."""

    if not isinstance(candidate, Mapping) or not _is_hash(source_sha256):
        raise ReadinessContractError("boundary candidate ID inputs differ")
    physical = _index(
        physical_page_index,
        "boundary_candidate.physical_page_index",
        maximum=MAX_PAGES_PER_DOCUMENT,
    )
    return stable_id(
        "boundary-candidate",
        POLICY_ID,
        source_sha256,
        physical,
        candidate.get("public_item_id"),
        candidate.get("public_path"),
        candidate.get("element_id"),
        candidate.get("bbox_id"),
        candidate.get("evidence_ids"),
        candidate.get("source_object_ids"),
        candidate.get("boundary_band"),
        candidate.get("source_method"),
    )


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _string(
    value: Any,
    path: str,
    *,
    maximum_bytes: int = MAX_CANDIDATE_TEXT_UTF8_BYTES,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ReadinessContractError(f"{path} is not a valid string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ReadinessContractError(f"{path} contains an unpaired surrogate") from exc
    if size > maximum_bytes:
        raise ReadinessContractError(f"{path} exceeds its UTF-8 cap")
    return value


def _index(value: Any, path: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ReadinessContractError(f"{path} is not a positive integer")
    if maximum is not None and value > maximum:
        raise ReadinessContractError(f"{path} exceeds its cap")
    return value


def _count(value: Any, path: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReadinessContractError(f"{path} is not a non-negative integer")
    if maximum is not None and value > maximum:
        raise ReadinessContractError(f"{path} exceeds its cap")
    return value


def _duration(value: Any, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or float(value) != round(float(value), 3)
    ):
        raise ReadinessContractError(f"{path} is not a rounded finite duration")
    return float(value)


def _source_alignment_duration(value: Any, path: str) -> float:
    """Validate the Phase-02 extractor's six-decimal millisecond timing."""

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or float(value) != round(float(value), 6)
    ):
        raise ReadinessContractError(
            f"{path} is not a Phase-02 rounded finite duration"
        )
    return float(value)


def validate_resource_payload(counter: str, payload: Any) -> int:
    """Run the authoritative inclusive cap for one isolated resource payload."""

    unit_by_counter = {
        "source_pdf_bytes": "bytes",
        "source_characters_per_page": "characters",
        "source_characters_per_document": "characters",
        "label_utf8_bytes": "utf8_bytes",
        "visible_text_utf8_bytes": "utf8_bytes",
        "candidate_text_utf8_bytes": "utf8_bytes",
        "extracted_contribution_utf8_bytes": "utf8_bytes",
        "extracted_residual_plan_bytes_per_page": "json_bytes",
        "extracted_residual_plan_bytes_per_document": "json_bytes",
        "page_identity_json_bytes": "json_bytes",
        "running_descriptor_json_bytes": "json_bytes",
        "report_json_bytes": "json_bytes",
    }
    if counter not in RESOURCE_LIMITS or not isinstance(RESOURCE_LIMITS[counter], int):
        raise ReadinessContractError("resource counter is not authoritative/integral")
    if counter in {
        "extracted_residual_plan_bytes_per_page",
        "extracted_residual_plan_bytes_per_document",
    }:
        if not isinstance(payload, (list, tuple)) or not payload:
            raise ReadinessContractError("resource plan payload is not ordered")
        plans = tuple(payload)
        validate_extracted_plan_ledger(plans)
        if (
            counter == "extracted_residual_plan_bytes_per_page"
            and len({plan.physical_page_index for plan in plans}) != 1
        ):
            raise ReadinessContractError("resource page plan scope differs")
        observed = sum(len(extracted_plan_json_bytes(plan)) for plan in plans)
        if observed > int(RESOURCE_LIMITS[counter]):
            raise ReadinessContractError("resource payload exceeds its inclusive cap")
        return observed
    unit = unit_by_counter.get(counter, "items")
    if unit == "bytes":
        if not isinstance(payload, bytes):
            raise ReadinessContractError("resource payload is not bytes")
        observed = len(payload)
    elif unit == "characters":
        if not isinstance(payload, str):
            raise ReadinessContractError("resource payload is not text")
        observed = len(payload)
    elif unit == "utf8_bytes":
        if not isinstance(payload, str):
            raise ReadinessContractError("resource payload is not text")
        try:
            observed = len(payload.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ReadinessContractError("resource payload is not UTF-8") from exc
    elif unit == "json_bytes":
        if not isinstance(payload, bytes):
            raise ReadinessContractError("resource payload is not serialized JSON")
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReadinessContractError("resource payload is not strict JSON") from exc
        if not isinstance(decoded, Mapping):
            raise ReadinessContractError("resource JSON payload is not an object")
        validator = {
            "page_identity_json_bytes": validate_page_identity,
            "running_descriptor_json_bytes": validate_running_region,
            "report_json_bytes": validate_source_report,
        }.get(counter)
        if validator is None:
            raise ReadinessContractError("resource JSON counter differs")
        validator(decoded)
        observed = len(payload)
    else:
        if not isinstance(payload, (list, tuple)):
            raise ReadinessContractError(
                "resource payload is not an ordered collection"
            )
        observed = len(payload)
    if observed > int(RESOURCE_LIMITS[counter]):
        raise ReadinessContractError("resource payload exceeds its inclusive cap")
    return observed


def validate_deadline_window(name: str, start: Any, finish: Any) -> float:
    """Validate one injected monotonic interval against its authoritative deadline."""

    limit = {
        "source_extraction_deadline": SOURCE_EXTRACTION_DEADLINE_SECONDS,
        "projection_page_deadline": PROJECTION_PAGE_DEADLINE_SECONDS,
        "projection_document_deadline": PROJECTION_DOCUMENT_DEADLINE_SECONDS,
    }.get(name)
    if (
        limit is None
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in (start, finish)
        )
        or float(finish) < float(start)
    ):
        raise ReadinessContractError("deadline window differs")
    elapsed = float(finish) - float(start)
    if elapsed > limit + 1e-12:
        raise ReadinessContractError("deadline window exceeds its cap")
    return elapsed


def inclusive_nearest_rank(values: Sequence[float], percentile: float = 0.95) -> float:
    """Return the policy's finite, nonnegative, non-interpolated percentile."""

    if (
        not isinstance(values, (list, tuple))
        or not values
        or isinstance(percentile, bool)
        or not isinstance(percentile, (int, float))
        or not math.isfinite(percentile)
        or not 0 < float(percentile) <= 1
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in values
        )
    ):
        raise ReadinessContractError("nearest-rank inputs differ")
    ordered = sorted(float(value) for value in values)
    rank = math.ceil(float(percentile) * len(ordered))
    return ordered[rank - 1]


def paired_worker_plan() -> tuple[dict[str, Any], ...]:
    """Return the exact target/pair/state order for 20 fresh workers."""

    records = [
        {
            "worker_index": worker_index,
            "target_id": target_id,
            "pair_index": pair_index,
            "state": state,
        }
        for worker_index, (target_id, pair_index, state) in enumerate(PAIRED_CASES)
    ]
    if len(records) != PAIRED_WORKER_COUNT:
        raise ReadinessContractError("paired worker plan cardinality differs")
    return tuple(records)


def normalize_ru_maxrss(raw_value: Any, platform: str) -> int:
    """Normalize RUSAGE_SELF ru_maxrss to bytes on the two approved platforms."""

    raw = _count(raw_value, "ru_maxrss.raw")
    if platform == "darwin":
        return raw
    if platform == "linux":
        return raw * 1024
    raise ReadinessContractError("ru_maxrss platform differs")


def summarize_paired_performance(
    target_id: str,
    *,
    off_seconds: Sequence[float],
    on_seconds: Sequence[float],
    off_rss_bytes: Sequence[int],
    on_rss_bytes: Sequence[int],
) -> dict[str, Any]:
    """Apply clipped overhead, dual latency ceilings, and paired RSS delta."""

    if target_id not in PERFORMANCE_TARGETS or any(
        len(values) != len(PAIRED_STATE_ORDER)
        for values in (off_seconds, on_seconds, off_rss_bytes, on_rss_bytes)
    ):
        raise ReadinessContractError("paired target/sample cardinality differs")
    inclusive_nearest_rank(off_seconds)
    inclusive_nearest_rank(on_seconds)
    off_values = tuple(float(value) for value in off_seconds)
    on_values = tuple(float(value) for value in on_seconds)
    normalized_off_rss = tuple(
        _count(value, "paired.off_rss_bytes") for value in off_rss_bytes
    )
    normalized_on_rss = tuple(
        _count(value, "paired.on_rss_bytes") for value in on_rss_bytes
    )
    signed = tuple(on - off for off, on in zip(off_values, on_values))
    clipped = tuple(max(value, 0.0) for value in signed)
    overhead_p95 = inclusive_nearest_rank(clipped)
    off_p95 = inclusive_nearest_rank(off_values)
    relative_ceiling = 0.05 * off_p95
    fixed_ceiling = PAIRED_FIXED_CEILINGS_SECONDS[target_id]
    effective_ceiling = min(relative_ceiling, fixed_ceiling)
    rss_deltas = tuple(
        max(on - off, 0) for off, on in zip(normalized_off_rss, normalized_on_rss)
    )
    peak_rss_delta = max(rss_deltas)
    passed = (
        overhead_p95 <= relative_ceiling
        and overhead_p95 <= fixed_ceiling
        and peak_rss_delta <= PEAK_MEMORY_DELTA_CEILING_BYTES
    )
    return {
        "target_id": target_id,
        "signed_seconds": signed,
        "clipped_seconds": clipped,
        "overhead_p95_seconds": overhead_p95,
        "off_p95_seconds": off_p95,
        "relative_ceiling_seconds": relative_ceiling,
        "fixed_ceiling_seconds": fixed_ceiling,
        "effective_ceiling_seconds": effective_ceiling,
        "rss_delta_bytes": rss_deltas,
        "peak_rss_delta_bytes": peak_rss_delta,
        "passed": passed,
    }


def execute_paired_performance_harness(
    worker: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Execute the exact no-retry worker plan and fail on any invalid sample."""

    samples: dict[str, dict[str, list[Any]]] = {
        target_id: {
            "off_seconds": [],
            "on_seconds": [],
            "off_rss_bytes": [],
            "on_rss_bytes": [],
        }
        for target_id in PERFORMANCE_TARGETS
    }
    result_fields = (
        "wall_seconds",
        "raw_ru_maxrss",
        "platform",
        "exit_code",
        "source_match",
        "code_match",
        "custody_match",
    )
    for work in paired_worker_plan():
        try:
            result = worker(deepcopy(work))
        except Exception as exc:
            raise ReadinessContractError("paired worker raised") from exc
        if not isinstance(result, Mapping):
            raise ReadinessContractError("paired worker result differs")
        _exact_keys(result, result_fields, "paired_worker.result")
        wall_seconds = result["wall_seconds"]
        exit_code = result["exit_code"]
        if (
            isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, (int, float))
            or not math.isfinite(wall_seconds)
            or wall_seconds < 0
            or isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or exit_code != 0
            or any(
                result[key] is not True
                for key in ("source_match", "code_match", "custody_match")
            )
        ):
            raise ReadinessContractError("paired worker failed its custody/sample gate")
        rss_bytes = normalize_ru_maxrss(result["raw_ru_maxrss"], result["platform"])
        state = work["state"]
        target_samples = samples[work["target_id"]]
        target_samples[f"{state}_seconds"].append(float(wall_seconds))
        target_samples[f"{state}_rss_bytes"].append(rss_bytes)
    return {
        target_id: summarize_paired_performance(target_id, **target_samples)
        for target_id, target_samples in samples.items()
    }


def isolated_measurement_protocol(stage: str, target_id: str) -> dict[str, Any]:
    """Return the exact isolated latency/allocation invocation protocol."""

    if stage not in {"source_extraction", "running_region_projection"}:
        raise ReadinessContractError("isolated stage differs")
    if target_id not in PERFORMANCE_TARGETS:
        raise ReadinessContractError("isolated target differs")
    return {
        "stage": stage,
        "target_id": target_id,
        "latency_warmups": ISOLATED_LATENCY_WARMUPS,
        "latency_samples": ISOLATED_LATENCY_SAMPLES,
        "latency_clock": "time.perf_counter_ns",
        "input_prepared_outside_timing": True,
        "tracemalloc_during_latency": False,
        "gc_outside_timing": True,
        "output_release_outside_timing": True,
        "allocation_warmups": ISOLATED_ALLOCATION_WARMUPS,
        "allocation_samples": ISOLATED_ALLOCATION_SAMPLES,
        "allocation_start_each_sample": True,
        "allocation_reset_peak_each_sample": True,
        "allocation_stop_each_sample": True,
        "allocation_timing_claim": False,
        "comparison_instrumentation": "third_untimed_projection_call",
        "replacement_samples": 0,
        "failure_scope": "complete_measurement_candidate",
        "latency_p95_ceiling_seconds": (
            ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
            if stage == "source_extraction"
            else ISOLATED_PROJECTION_P95_SECONDS
        ),
        "allocation_ceiling_bytes": PEAK_MEMORY_DELTA_CEILING_BYTES,
        "report_size_ceiling_bytes": (
            MAX_REPORT_BYTES if stage == "source_extraction" else None
        ),
    }


def validate_isolated_measurement_protocol(protocol: Mapping[str, Any]) -> None:
    """Refuse any sample-count, timing, tracing, reset, release, or retry drift."""

    if not isinstance(protocol, Mapping):
        raise ReadinessContractError("isolated protocol is not an object")
    stage = protocol.get("stage")
    target_id = protocol.get("target_id")
    expected = isolated_measurement_protocol(stage, target_id)
    if dict(protocol) != expected:
        raise ReadinessContractError("isolated measurement protocol differs")


def summarize_isolated_measurement(
    stage: str,
    target_id: str,
    *,
    latency_seconds: Sequence[float],
    allocation_bytes: Sequence[int],
    warmup_successes: Sequence[bool],
    measured_output_successes: Sequence[bool],
    report_sizes: Sequence[int] = (),
    predecessor_unchanged: bool = True,
    idempotent: bool = True,
) -> dict[str, Any]:
    """Apply isolated gates with complete-candidate failure and no replacements."""

    protocol = isolated_measurement_protocol(stage, target_id)
    if (
        len(latency_seconds) != protocol["latency_samples"]
        or len(allocation_bytes) != protocol["allocation_samples"]
        or len(warmup_successes)
        != protocol["latency_warmups"] + protocol["allocation_warmups"]
        or len(measured_output_successes)
        != protocol["latency_samples"] + protocol["allocation_samples"]
        or any(value is not True for value in warmup_successes)
        or any(value is not True for value in measured_output_successes)
    ):
        raise ReadinessContractError("isolated sample/failure scope differs")
    p95_seconds = inclusive_nearest_rank(latency_seconds)
    allocations = tuple(
        _count(value, "isolated.allocation_bytes") for value in allocation_bytes
    )
    peak_allocation = max(allocations)
    if stage == "source_extraction":
        if len(report_sizes) != len(latency_seconds) or any(
            _count(size, "isolated.report_size", maximum=MAX_REPORT_BYTES)
            > MAX_REPORT_BYTES
            for size in report_sizes
        ):
            raise ReadinessContractError("isolated source report size differs")
    elif report_sizes:
        raise ReadinessContractError("projection retained source report sizes")
    if stage == "running_region_projection" and (
        predecessor_unchanged is not True or idempotent is not True
    ):
        raise ReadinessContractError("isolated projection custody differs")
    passed = (
        p95_seconds <= protocol["latency_p95_ceiling_seconds"]
        and peak_allocation <= protocol["allocation_ceiling_bytes"]
    )
    return {
        "stage": stage,
        "target_id": target_id,
        "latency_p95_seconds": p95_seconds,
        "peak_allocation_bytes": peak_allocation,
        "passed": passed,
    }


def _remove_exact_paths(
    value: Mapping[str, Any], paths: Sequence[str]
) -> dict[str, Any]:
    result = deepcopy(dict(value))
    for path in paths:
        parts = path.split(".")
        cursor: Any = result
        for part in parts[:-1]:
            if not isinstance(cursor, dict) or part not in cursor:
                raise ReadinessContractError("semantic timing path is absent")
            cursor = cursor[part]
        if not isinstance(cursor, dict) or parts[-1] not in cursor:
            raise ReadinessContractError("semantic timing path is absent")
        cursor.pop(parts[-1])
    return result


def whole_output_semantic_payload(document: Mapping[str, Any]) -> dict[str, Any]:
    """Remove exactly the ten approved whole-output timing paths."""

    return _remove_exact_paths(document, WHOLE_OUTPUT_TIMING_PATHS)


def source_report_semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only the private source report's root extraction timing."""

    return _remove_exact_paths(report, ("extraction_ms",))


def metrics_artifact_semantic_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only generated_at and the self-referential semantic digest."""

    return _remove_exact_paths(artifact, ("generated_at", "semantic_sha256"))


def _validate_file_identity(key: str, value: Any, path: str) -> None:
    if not isinstance(value, Mapping):
        raise ReadinessContractError(f"{path} is not an object")
    _exact_keys(value, CODE_CUSTODY_RECORD_FIELDS, path)
    relative = value["path"]
    normalized = PurePosixPath(relative) if isinstance(relative, str) else None
    if (
        not isinstance(relative, str)
        or not relative
        or relative != key
        or normalized is None
        or normalized.is_absolute()
        or ".." in normalized.parts
        or str(normalized) != relative
        or isinstance(value["size_bytes"], bool)
        or not isinstance(value["size_bytes"], int)
        or value["size_bytes"] < 0
        or not _is_hash(value["sha256"])
    ):
        raise ReadinessContractError(f"{path} identity differs")


def _validate_code_custody(value: Any) -> bool:
    if not isinstance(value, Mapping):
        raise ReadinessContractError("metrics code custody differs")
    _exact_keys(value, CODE_CUSTODY_FIELDS, "metrics_artifact.code_sha256")

    def validate_manifest(manifest: Any, name: str) -> Mapping[str, Any]:
        if not isinstance(manifest, Mapping) or not manifest:
            raise ReadinessContractError(f"metrics code {name} manifest differs")
        for path, record in manifest.items():
            if not isinstance(path, str):
                raise ReadinessContractError("metrics code custody member differs")
            _validate_file_identity(
                path,
                record,
                f"metrics_artifact.code_sha256.{name}.{path}",
            )
        return manifest

    pre = validate_manifest(value["pre"], "pre")
    post = validate_manifest(value["post"], "post")
    if set(pre) != set(post):
        raise ReadinessContractError("metrics code manifest coverage differs")
    expected_match = pre == post
    if value["pre_post_match"] is not expected_match:
        raise ReadinessContractError("metrics code pre/post flag differs")
    expected_manifest_sha256 = hashlib.sha256(strict_json_bytes(post)).hexdigest()
    if value["manifest_sha256"] != expected_manifest_sha256:
        raise ReadinessContractError("metrics code manifest digest differs")
    return expected_match


def _validate_dependency_custody(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ReadinessContractError("metrics dependency custody differs")
    _exact_keys(value, DEPENDENCY_CUSTODY_FIELDS, "metrics_artifact.dependency")
    manifests = value["manifests"]
    if not isinstance(manifests, Mapping) or set(manifests) != set(
        DEPENDENCY_MANIFEST_PATHS
    ):
        raise ReadinessContractError("metrics dependency manifests differ")
    for path, record in manifests.items():
        _validate_file_identity(path, record, f"metrics dependency manifest {path}")

    packages = value["python_packages"]
    if not isinstance(packages, Mapping) or set(packages) != set(
        DEPENDENCY_REQUIRED_PYTHON_PACKAGES
    ):
        raise ReadinessContractError("metrics dependency packages differ")
    for distribution, record in packages.items():
        if not isinstance(record, Mapping):
            raise ReadinessContractError("metrics dependency package differs")
        _exact_keys(record, DEPENDENCY_PACKAGE_FIELDS, "metrics dependency package")
        if (
            record["distribution"] != distribution
            or not isinstance(record["version"], str)
            or not record["version"]
        ):
            raise ReadinessContractError("metrics dependency package identity differs")

    tools = value["local_tools"]
    if not isinstance(tools, Mapping) or set(tools) != set(
        DEPENDENCY_REQUIRED_LOCAL_TOOLS
    ):
        raise ReadinessContractError("metrics dependency tools differ")
    for name, record in tools.items():
        if not isinstance(record, Mapping):
            raise ReadinessContractError("metrics dependency tool differs")
        _exact_keys(record, DEPENDENCY_LOCAL_TOOL_FIELDS, "metrics dependency tool")
        if (
            record["name"] != name
            or not isinstance(record["version"], str)
            or not record["version"]
        ):
            raise ReadinessContractError("metrics dependency tool identity differs")

    runtime = value["runtime"]
    if not isinstance(runtime, Mapping):
        raise ReadinessContractError("metrics dependency runtime differs")
    _exact_keys(runtime, DEPENDENCY_RUNTIME_FIELDS, "metrics dependency runtime")
    if any(
        not isinstance(runtime[field], str) or not runtime[field] for field in runtime
    ):
        raise ReadinessContractError("metrics dependency runtime identity differs")
    offline = value["offline_environment"]
    if not isinstance(offline, Mapping) or dict(offline) != dict(OFFLINE_ENVIRONMENT):
        raise ReadinessContractError("metrics offline environment differs")


def _validate_output_identity(value: Any, path: str) -> None:
    if not isinstance(value, Mapping):
        raise ReadinessContractError(f"{path} is not an object")
    _exact_keys(value, OUTPUT_IDENTITY_FIELDS, path)
    if (
        isinstance(value["size_bytes"], bool)
        or not isinstance(value["size_bytes"], int)
        or value["size_bytes"] < 0
        or not _is_hash(value["sha256"])
    ):
        raise ReadinessContractError(f"{path} identity differs")


def _validate_output_sizes(value: Any, *, complete: bool) -> None:
    if not isinstance(value, Mapping):
        raise ReadinessContractError("metrics output sizes differ")
    _exact_keys(value, OUTPUT_SIZES_FIELDS, "metrics_artifact.output_sizes")
    collections = (
        ("paired_samples", value["paired_samples"]),
        ("source_reports", value["source_reports"]),
        ("isolated_projection_outputs", value["isolated_projection_outputs"]),
    )
    for field, records in collections:
        if not isinstance(records, Mapping) or not set(records) <= set(
            PERFORMANCE_TARGETS
        ):
            raise ReadinessContractError(f"metrics output {field} targets differ")
        if complete and set(records) != set(PERFORMANCE_TARGETS):
            raise ReadinessContractError(f"metrics output {field} is incomplete")

    paired = value["paired_samples"]
    for target_id, samples in paired.items():
        if not isinstance(samples, list):
            raise ReadinessContractError("metrics paired output is not ordered")
        expected_order = tuple(
            (pair_index, state)
            for plan_target, pair_index, state in PAIRED_CASES
            if plan_target == target_id
        )
        observed_order: list[tuple[int, str]] = []
        for sample in samples:
            if not isinstance(sample, Mapping):
                raise ReadinessContractError("metrics paired output sample differs")
            _exact_keys(sample, OUTPUT_SAMPLE_FIELDS, "metrics paired output sample")
            pair_index = sample["pair_index"]
            state = sample["state"]
            if (
                sample["target_id"] != target_id
                or isinstance(pair_index, bool)
                or not isinstance(pair_index, int)
                or not 0 <= pair_index < len(PAIRED_STATE_ORDER)
                or state not in {"off", "on"}
            ):
                raise ReadinessContractError("metrics paired output identity differs")
            observed_order.append((pair_index, state))
            variants = sample["variants"]
            if not isinstance(variants, Mapping) or set(variants) != set(
                OUTPUT_VARIANTS
            ):
                raise ReadinessContractError("metrics output variants differ")
            for variant, identity in variants.items():
                _validate_output_identity(identity, f"metrics output {variant}")
        if tuple(observed_order) != expected_order[: len(observed_order)] or (
            complete and tuple(observed_order) != expected_order
        ):
            raise ReadinessContractError("metrics paired output order differs")

    for field in ("source_reports", "isolated_projection_outputs"):
        for target_id, identity in value[field].items():
            _validate_output_identity(identity, f"metrics output {field}.{target_id}")
    ceilings = {
        "maximum_page_identity_json_bytes": MAX_PAGE_IDENTITY_BYTES,
        "maximum_running_descriptor_json_bytes": MAX_RUNNING_DESCRIPTOR_BYTES,
        "maximum_source_report_json_bytes": MAX_REPORT_BYTES,
    }
    within = True
    for field, ceiling in ceilings.items():
        observed = value[field]
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            raise ReadinessContractError(f"metrics output {field} differs")
        within = within and observed <= ceiling
    if value["all_within_limits"] is not within:
        raise ReadinessContractError("metrics output size aggregate differs")
    if complete and not within:
        raise ReadinessContractError("final metrics output size cap exceeded")


def _validate_maximum_page_workload(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ReadinessContractError("maximum page workload differs")
    _exact_keys(value, MAXIMUM_PAGE_WORKLOAD_FIELDS, "maximum page workload")
    if dict(value) != dict(MAXIMUM_PAGE_WORKLOAD):
        raise ReadinessContractError("maximum page workload identity differs")


def validate_metrics_artifact_custody(
    artifact: Mapping[str, Any],
    *,
    existing_paths: Sequence[str] = (),
) -> None:
    """Validate closed final/failed artifact identity and exclusive-create custody."""

    if not isinstance(artifact, Mapping):
        raise ReadinessContractError("metrics artifact is not an object")
    if (
        not isinstance(existing_paths, (list, tuple))
        or any(not isinstance(path, str) or not path for path in existing_paths)
        or len(existing_paths) != len(set(existing_paths))
    ):
        raise ReadinessContractError("existing metrics artifact custody differs")
    _exact_keys(artifact, METRICS_ARTIFACT_FIELDS, "metrics_artifact")
    if (
        artifact["schema_version"] != "1.0"
        or artifact["record_kind"] != "p03_us08_running_region_metrics"
        or artifact["story"] != "P03-US08"
        or not isinstance(artifact["generated_at"], str)
        or not artifact["generated_at"]
    ):
        raise ReadinessContractError("metrics artifact identity differs")
    try:
        generated_at = datetime.fromisoformat(artifact["generated_at"])
    except ValueError as exc:
        raise ReadinessContractError("metrics artifact timestamp differs") from exc
    if generated_at.tzinfo is None:
        raise ReadinessContractError("metrics artifact timestamp lacks timezone")
    mapping_fields = (
        "measurement",
        "policy",
        "settings_delta",
        "m0_reference",
        "input_custody",
        "predecessor_custody",
        "oracle_custody",
        "contract_custody",
        "synthetic_fixture_custody",
        "code_sha256",
        "dependency_custody",
        "source_extraction",
        "running_region_projection",
        "resource_boundaries",
        "deadline_boundaries",
        "paired_parser",
        "quality",
        "control_matrix",
        "comparison_ledgers",
        "output_sizes",
        "rollback",
        "aggregate",
    )
    if any(not isinstance(artifact[field], Mapping) for field in mapping_fields) or any(
        not isinstance(artifact[field], list)
        for field in ("prior_failed_candidates", "failures")
    ):
        raise ReadinessContractError("metrics artifact value shape differs")
    code_custody_match = _validate_code_custody(artifact["code_sha256"])
    _validate_dependency_custody(artifact["dependency_custody"])
    measurement = artifact["measurement"]
    _validate_maximum_page_workload(measurement.get("maximum_page_workload"))
    retained_path = artifact["retained_path"]
    if not isinstance(retained_path, str) or retained_path in existing_paths:
        raise ReadinessContractError("metrics artifact would overwrite custody")
    failures = artifact["failures"]
    if not isinstance(failures, list) or any(
        not isinstance(failure, Mapping) for failure in failures
    ):
        raise ReadinessContractError("metrics failure ledger differs")
    for failure in failures:
        _exact_keys(failure, METRICS_FAILURE_FIELDS, "metrics_artifact.failure")
        _string(failure["type"], "metrics_artifact.failure.type")
        _string(failure["stage"], "metrics_artifact.failure.stage")
        if failure["target_id"] not in (*PERFORMANCE_TARGETS, None):
            raise ReadinessContractError("metrics failure target differs")
        if failure["pair_index"] is not None and (
            isinstance(failure["pair_index"], bool)
            or not isinstance(failure["pair_index"], int)
            or not 0 <= failure["pair_index"] < len(PAIRED_STATE_ORDER)
        ):
            raise ReadinessContractError("metrics failure pair differs")
        if failure["state"] not in {"off", "on", None}:
            raise ReadinessContractError("metrics failure state differs")
    status = artifact["status"]
    _validate_output_sizes(
        artifact["output_sizes"],
        complete=status == "final_measurement_candidate",
    )
    if status == "final_measurement_candidate":
        if (
            retained_path != FINAL_METRICS_ARTIFACT_PATH
            or failures
            or not code_custody_match
        ):
            raise ReadinessContractError("final metrics artifact custody differs")
        aggregate = artifact["aggregate"]
        if (
            not isinstance(aggregate, Mapping)
            or not aggregate
            or any(value is not True for value in aggregate.values())
        ):
            raise ReadinessContractError("final metrics aggregate gate differs")
    elif status == "failed_measurement_candidate":
        match = FAILED_METRICS_ARTIFACT_PATTERN.fullmatch(retained_path)
        if match is None or not failures:
            raise ReadinessContractError("failed metrics artifact custody differs")
        existing_attempts = [
            int(existing.group(1))
            for path in existing_paths
            if (existing := FAILED_METRICS_ARTIFACT_PATTERN.fullmatch(path)) is not None
        ]
        expected_attempt = max(existing_attempts, default=0) + 1
        if int(match.group(1)) != expected_attempt:
            raise ReadinessContractError("failed metrics attempt sequence differs")
    else:
        raise ReadinessContractError("metrics artifact status differs")
    hosted_requests = artifact["hosted_requests"]
    hosted_tokens = artifact["hosted_tokens"]
    hosted_cost = artifact["hosted_cost_usd"]
    if (
        isinstance(hosted_requests, bool)
        or not isinstance(hosted_requests, int)
        or hosted_requests != 0
        or isinstance(hosted_tokens, bool)
        or not isinstance(hosted_tokens, int)
        or hosted_tokens != 0
        or isinstance(hosted_cost, bool)
        or not isinstance(hosted_cost, (int, float))
        or not math.isfinite(hosted_cost)
        or float(hosted_cost) != 0.0
    ):
        raise ReadinessContractError("metrics artifact hosted usage differs")
    expected_semantic_sha256 = hashlib.sha256(
        strict_json_bytes(metrics_artifact_semantic_payload(artifact))
    ).hexdigest()
    if artifact["semantic_sha256"] != expected_semantic_sha256:
        raise ReadinessContractError("metrics artifact semantic digest differs")


def _known_concerns(
    value: Any,
    path: str,
    *,
    maximum: int,
    allowed: Sequence[str] = CONCERN_CODES,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ReadinessContractError(f"{path} is not ordered")
    result = tuple(value)
    if (
        len(result) > maximum
        or tuple(sorted(set(result))) != result
        or any(item not in allowed for item in result)
    ):
        raise ReadinessContractError(f"{path} differs")
    return result


def _references(value: Any, path: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ReadinessContractError(f"{path} is not ordered")
    refs = tuple(value)
    if (
        (not allow_empty and not refs)
        or len(refs) > MAX_REFERENCES_PER_RECORD
        or len(refs) != len(set(refs))
        or any(not isinstance(item, str) or not item for item in refs)
    ):
        raise ReadinessContractError(f"{path} differs")
    return refs


def validate_public_path(value: Any, *, path: str = "public_path") -> tuple[Any, ...]:
    """Validate an ordered public path rooted at ``pages``."""

    if not isinstance(value, (list, tuple)):
        raise ReadinessContractError(f"{path} is not ordered")
    segments = tuple(value)
    if (
        not segments
        or segments[0] != "pages"
        or len(segments) > MAX_PUBLIC_PATH_SEGMENTS
    ):
        raise ReadinessContractError(f"{path} root/length differs")
    for segment in segments:
        if isinstance(segment, bool) or not isinstance(segment, (str, int)):
            raise ReadinessContractError(f"{path} segment type differs")
        if isinstance(segment, int) and segment < 0:
            raise ReadinessContractError(f"{path} has a negative index")
        if isinstance(segment, str) and not segment:
            raise ReadinessContractError(f"{path} has an empty key")
    return segments


def resolve_public_path(document: Any, path: Sequence[Any]) -> Any:
    """Resolve a previously validated public path without coercion."""

    current = document
    for segment in validate_public_path(path):
        if isinstance(segment, str):
            if not isinstance(current, Mapping) or segment not in current:
                raise ReadinessContractError("public path does not resolve")
            current = current[segment]
        else:
            if not isinstance(current, (list, tuple)) or segment >= len(current):
                raise ReadinessContractError("public path index does not resolve")
            current = current[segment]
    return current


def _exact_public_item_path(
    value: Sequence[Any], *, physical_page_index: int
) -> tuple[Any, ...]:
    """Return the sole attached page-item path admitted for printed evidence."""

    path = validate_public_path(value, path="page_identity.evidence_source.public_path")
    if (
        len(path) != 4
        or path[0] != "pages"
        or path[1] != physical_page_index - 1
        or path[2] != "items"
        or isinstance(path[3], bool)
        or not isinstance(path[3], int)
    ):
        raise ReadinessContractError("detected page-label public item path differs")
    return path


def _exact_public_visible_text(owner: Mapping[str, Any], visible_text: Any) -> None:
    """Bind a detected label to the complete selected public source value."""

    owner_text = owner.get("value")
    if owner_text is None:
        owner_text = owner.get("md")
    if not isinstance(owner_text, str) or owner_text != visible_text:
        raise ReadinessContractError("detected page-label visible source differs")


def _unicode_noncharacter(character: str) -> bool:
    point = ord(character)
    return 0xFDD0 <= point <= 0xFDEF or (point & 0xFFFF) in {0xFFFE, 0xFFFF}


def _safe_semantic_string(
    value: Any,
    path: str,
    *,
    maximum_bytes: int,
    normalization: Literal["NFC", "none"],
) -> str:
    text = _string(value, path, maximum_bytes=maximum_bytes)
    if text != text.strip() or "\n" in text or "\r" in text:
        raise ReadinessContractError(f"{path} is not a trimmed single line")
    if normalization == "NFC" and unicodedata.normalize("NFC", text) != text:
        raise ReadinessContractError(f"{path} is not NFC")
    for character in text:
        category = unicodedata.category(character)
        if category[0] in {"L", "N"} or character in _ALLOWED_ASCII_PUNCTUATION:
            continue
        raise ReadinessContractError(f"{path} contains a forbidden character")
    if any(_unicode_noncharacter(character) for character in text):
        raise ReadinessContractError(f"{path} contains a Unicode noncharacter")
    return text


def normalize_embedded_label(value: str) -> str:
    """Return embedded-label NFC/edge-whitespace normalization or refuse it."""

    raw = _string(
        value,
        "embedded_label",
        maximum_bytes=MAX_LABEL_UTF8_BYTES,
        allow_empty=True,
    )
    # Edge whitespace is the only normalization exception.  Validate the raw
    # scalar first so C0/C1 controls, line separators, bidi controls, surrogate
    # code points, and noncharacters cannot be hidden by ``str.strip()``.
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        or _unicode_noncharacter(character)
        for character in raw
    ):
        raise ReadinessContractError("embedded_label contains a forbidden character")
    normalized = unicodedata.normalize("NFC", value).strip()
    return _safe_semantic_string(
        normalized,
        "embedded_label",
        maximum_bytes=MAX_LABEL_UTF8_BYTES,
        normalization="NFC",
    )


def normalize_detected_label(value: str) -> str:
    """Apply the closed v1 printed-label grammar."""

    visible = _safe_semantic_string(
        value,
        "visible_text",
        maximum_bytes=MAX_VISIBLE_TEXT_UTF8_BYTES,
        normalization="NFC",
    )
    match = _INTEGER_RE.fullmatch(visible)
    if match:
        return match.group(1)
    match = _FRACTION_RE.fullmatch(visible)
    if match:
        current, total = (int(match.group(1)), int(match.group(2)))
        if current <= total:
            return f"{current}/{total}"
        raise ReadinessContractError("visible fraction exceeds total")
    match = _PAGE_OF_RE.fullmatch(visible)
    if match:
        current, total = (int(match.group(1)), int(match.group(2)))
        if current <= total:
            return f"{current} of {total}"
        raise ReadinessContractError("visible Page-of-total exceeds total")
    match = _PIPE_RE.fullmatch(visible)
    if match:
        return match.group(1)
    raise ReadinessContractError("visible text is outside the closed label grammar")


def validate_bbox(
    value: Mapping[str, Any],
    *,
    page_width: float | None = None,
    page_height: float | None = None,
    path: str = "bbox",
) -> None:
    """Validate finite positive top-left point-space geometry."""

    if not isinstance(value, Mapping):
        raise ReadinessContractError(f"{path} is not an object")
    _exact_keys(value, BBOX_FIELDS, path)
    if value["unit"] != "pt":
        raise ReadinessContractError(f"{path} unit differs")
    raw = tuple(value[key] for key in ("x", "y", "width", "height"))
    if any(
        isinstance(number, bool)
        or not isinstance(number, (int, float))
        or not math.isfinite(number)
        for number in raw
    ):
        raise ReadinessContractError(f"{path} is non-finite")
    x, y, width, height = (float(number) for number in raw)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ReadinessContractError(f"{path} has invalid area")
    if page_width is not None and x + width > page_width + 0.001:
        raise ReadinessContractError(f"{path} exceeds page width")
    if page_height is not None and y + height > page_height + 0.001:
        raise ReadinessContractError(f"{path} exceeds page height")


def _canonical_bbox(value: Any, *, path: str) -> dict[str, Any]:
    """Read canonical geometry from a predecessor bbox without rewriting aliases."""

    if not isinstance(value, Mapping) or not set(BBOX_FIELDS) <= set(value):
        raise ReadinessContractError(f"{path} canonical fields are incomplete")
    canonical = {key: value[key] for key in BBOX_FIELDS}
    validate_bbox(canonical, path=path)
    return canonical


def _candidate_uses_effective_bottom(
    candidate: Mapping[str, Any],
    *,
    page_width: float,
    page_height: float,
    path: str,
) -> bool:
    """Bind a declared band to nominal geometry or the bounded bottom extension."""

    validate_bbox(
        candidate["bbox"],
        page_width=page_width,
        page_height=page_height,
        path=f"{path}.bbox",
    )
    bbox = candidate["bbox"]
    y = float(bbox["y"])
    bottom = y + float(bbox["height"])
    declared = candidate.get("boundary_band")
    if bottom <= page_height * 0.15 + 0.001:
        actual = "top"
        effective = False
    elif y >= page_height * 0.85 - 0.001:
        actual = "bottom"
        effective = False
    elif y >= page_height * 0.70 - 0.001:
        actual = "bottom"
        effective = True
    else:
        raise ReadinessContractError(f"{path} is outside a boundary band")
    if declared != actual:
        raise ReadinessContractError(f"{path} declared band/geometry differs")
    return effective


def _bbox_contains(outer: Mapping[str, Any], inner: Mapping[str, Any]) -> bool:
    outer_box = _canonical_bbox(outer, path="source_admission.outer_bbox")
    inner_box = _canonical_bbox(inner, path="source_admission.inner_bbox")
    return (
        float(inner_box["x"]) >= float(outer_box["x"]) - 0.001
        and float(inner_box["y"]) >= float(outer_box["y"]) - 0.001
        and float(inner_box["x"]) + float(inner_box["width"])
        <= float(outer_box["x"]) + float(outer_box["width"]) + 0.001
        and float(inner_box["y"]) + float(inner_box["height"])
        <= float(outer_box["y"]) + float(outer_box["height"]) + 0.001
    )


_PDFPLUMBER_SOURCE_ID_RE = re.compile(
    r"^pdfplumber:(?P<sha256>[0-9a-f]{64}):page:(?P<page>[1-9][0-9]*):"
    r"(?P<kind>character|word):(?P<index>0|[1-9][0-9]*)$"
)
_GENERIC_SOURCE_ID_RE = re.compile(
    r"^(?P<prefix>.*?)(?P<kind>character|word)[_:-]"
    r"(?P<index>0|[1-9][0-9]*)$"
)


def _parse_source_reference(
    source_id: str,
    *,
    source_sha256: str,
    page_index: int,
    path: str,
) -> tuple[Literal["pdfplumber", "generic"], str, Literal["character", "word"], int]:
    match = _PDFPLUMBER_SOURCE_ID_RE.fullmatch(source_id)
    if match is not None:
        if (
            match.group("sha256") != source_sha256
            or int(match.group("page")) != page_index
        ):
            raise ReadinessContractError(f"{path} source/page custody differs")
        return (
            "pdfplumber",
            f"pdfplumber:{source_sha256}:page:{page_index}:",
            match.group("kind"),  # type: ignore[return-value]
            int(match.group("index")),
        )
    match = _GENERIC_SOURCE_ID_RE.fullmatch(source_id)
    if match is None:
        raise ReadinessContractError(f"{path} source reference differs")
    return (
        "generic",
        match.group("prefix"),
        match.group("kind"),  # type: ignore[return-value]
        int(match.group("index")),
    )


def _ordered_source_reference_runs(
    value: Any,
    *,
    source_sha256: str,
    page_index: int,
    path: str,
    source_character_count: int | None = None,
    source_word_count: int | None = None,
) -> dict[str, tuple[str, ...]]:
    source_ids = _references(value, path, allow_empty=False)
    parsed = [
        _parse_source_reference(
            source_id,
            source_sha256=source_sha256,
            page_index=page_index,
            path=path,
        )
        for source_id in source_ids
    ]
    families = {family for family, _, _, _ in parsed}
    if len(families) != 1:
        raise ReadinessContractError(f"{path} source families differ")
    family = next(iter(families))
    if len({prefix for _, prefix, _, _ in parsed}) != 1:
        raise ReadinessContractError(f"{path} source scopes differ")
    kinds = [kind for _, _, kind, _ in parsed]
    if "character" in kinds and kinds != sorted(
        kinds, key={"character": 0, "word": 1}.__getitem__
    ):
        raise ReadinessContractError(f"{path} source kind order differs")
    result: dict[str, tuple[str, ...]] = {}
    for kind, maximum in (
        ("character", source_character_count),
        ("word", source_word_count),
    ):
        members = [
            (source_id, prefix, index)
            for source_id, (_, prefix, parsed_kind, index) in zip(
                source_ids, parsed, strict=True
            )
            if parsed_kind == kind
        ]
        if not members:
            result[kind] = ()
            continue
        prefixes = {prefix for _, prefix, _ in members}
        indexes = [index for _, _, index in members]
        if len(prefixes) != 1 or indexes != list(
            range(indexes[0], indexes[0] + len(indexes))
        ):
            raise ReadinessContractError(f"{path} {kind} run differs")
        if (
            family == "pdfplumber"
            and maximum is not None
            and (maximum < 0 or indexes[-1] >= maximum)
        ):
            raise ReadinessContractError(f"{path} {kind} run exceeds source count")
        result[kind] = tuple(source_id for source_id, _, _ in members)
    return result


def _source_reference_kind(source_id: Any) -> str | None:
    if not isinstance(source_id, str):
        return None
    match = _PDFPLUMBER_SOURCE_ID_RE.fullmatch(source_id)
    if match is None:
        match = _GENERIC_SOURCE_ID_RE.fullmatch(source_id)
    return match.group("kind") if match is not None else None


def _source_word_ids(value: Any) -> set[str]:
    """Return only syntactically complete word references from a reference list."""

    if not isinstance(value, (list, tuple)):
        return set()
    return {
        source_id
        for source_id in value
        if isinstance(source_id, str) and _source_reference_kind(source_id) == "word"
    }


def _candidate_area_coverage(
    candidate_bbox: Mapping[str, Any], owner_bbox: Mapping[str, Any]
) -> float:
    """Return intersection area divided by the candidate area."""

    candidate = _canonical_bbox(candidate_bbox, path="source_admission.candidate_bbox")
    owner = _canonical_bbox(owner_bbox, path="source_admission.owner_bbox")
    if candidate["unit"] != owner["unit"]:
        raise ReadinessContractError("source owner coordinate frame differs")
    candidate_left = float(candidate["x"])
    candidate_top = float(candidate["y"])
    candidate_right = candidate_left + float(candidate["width"])
    candidate_bottom = candidate_top + float(candidate["height"])
    owner_left = float(owner["x"])
    owner_top = float(owner["y"])
    owner_right = owner_left + float(owner["width"])
    owner_bottom = owner_top + float(owner["height"])
    intersection_width = max(
        0.0, min(candidate_right, owner_right) - max(candidate_left, owner_left)
    )
    intersection_height = max(
        0.0, min(candidate_bottom, owner_bottom) - max(candidate_top, owner_top)
    )
    return (intersection_width * intersection_height) / (
        float(candidate["width"]) * float(candidate["height"])
    )


def _vertical_center_delta(
    first_bbox: Mapping[str, Any], second_bbox: Mapping[str, Any]
) -> float:
    first = _canonical_bbox(first_bbox, path="source_admission.first_bbox")
    second = _canonical_bbox(second_bbox, path="source_admission.second_bbox")
    if first["unit"] != second["unit"]:
        raise ReadinessContractError("source owner coordinate frame differs")
    first_center = float(first["y"]) + float(first["height"]) / 2.0
    second_center = float(second["y"]) + float(second["height"]) / 2.0
    return abs(first_center - second_center)


def _native_label_owner_geometry_matches(
    label_bbox: Mapping[str, Any],
    owner_bbox: Mapping[str, Any],
    *,
    page_height: float,
) -> bool:
    """Apply the closed native-label containment-or-coverage rule."""

    return _bbox_contains(owner_bbox, label_bbox) or (
        _candidate_area_coverage(label_bbox, owner_bbox)
        >= NATIVE_LABEL_MIN_CANDIDATE_AREA_COVERAGE
        and _vertical_center_delta(label_bbox, owner_bbox)
        <= page_height * NATIVE_LABEL_MAX_VERTICAL_CENTER_DELTA_RATIO
    )


def _pdf_color_component(value: Any, *, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ReadinessContractError(f"{path} is not a finite PDF color component")
    return float(value)


def _rgb_byte(value: float) -> int:
    """Quantize a normalized channel with deterministic round-half-up."""

    return math.floor(value * 255.0 + 0.5)


def normalize_pdf_non_stroking_fill(value: Any) -> tuple[int, int, int]:
    """Normalize one finite DeviceGray/RGB/CMYK fill to an RGB byte triple."""

    if isinstance(value, bool) or value is None:
        raise ReadinessContractError("printed-label PDF fill differs")
    if isinstance(value, (int, float)):
        components = (_pdf_color_component(value, path="printed_label.fill.gray"),)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) not in {1, 3, 4}:
            raise ReadinessContractError("printed-label PDF fill shape differs")
        components = tuple(
            _pdf_color_component(component, path=f"printed_label.fill[{offset}]")
            for offset, component in enumerate(value)
        )
    else:
        raise ReadinessContractError("printed-label PDF fill differs")

    if len(components) == 1:
        normalized = (components[0],) * 3
    elif len(components) == 3:
        normalized = components
    else:
        cyan, magenta, yellow, black = components
        # Freeze the simple DeviceCMYK conversion used by this policy.  ICC,
        # calibrated, pattern, and separation spaces are outside v1.
        normalized = (
            (1.0 - cyan) * (1.0 - black),
            (1.0 - magenta) * (1.0 - black),
            (1.0 - yellow) * (1.0 - black),
        )
    return tuple(_rgb_byte(component) for component in normalized)  # type: ignore[return-value]


def _rgb_max_channel_delta(left: Sequence[int], right: Sequence[int]) -> int:
    if len(left) != 3 or len(right) != 3:
        raise ReadinessContractError("printed-label RGB shape differs")
    if any(
        isinstance(channel, bool)
        or not isinstance(channel, int)
        or not 0 <= channel <= 255
        for channel in (*left, *right)
    ):
        raise ReadinessContractError("printed-label RGB channel differs")
    return max(abs(left[index] - right[index]) for index in range(3))


def _displayed_pdf_object_bbox(
    bounds: Sequence[Any],
    *,
    page_width: float,
    page_height: float,
    page_rotation: int,
) -> dict[str, float | str] | None:
    if len(bounds) != 4 or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in bounds
    ):
        raise ReadinessContractError("printed-label PDF text-object geometry differs")
    left, bottom, right, top = (float(value) for value in bounds)
    if right <= left or top <= bottom:
        # Degenerate page text objects cannot positively intersect a finite
        # candidate.  Ignore them, but still require a separate intersecting
        # painted object below; this prevents unrelated source debris from
        # rejecting an otherwise authoritative label.
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
        raise ReadinessContractError("printed-label visibility page rotation differs")
    output: dict[str, float | str] = {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": "pt",
    }
    validate_bbox(output, path="printed_label.text_object_bbox")
    return output


def _bboxes_have_positive_intersection(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    left_box = _canonical_bbox(left, path="printed_label.intersection.left")
    right_box = _canonical_bbox(right, path="printed_label.intersection.right")
    intersection_width = min(
        float(left_box["x"]) + float(left_box["width"]),
        float(right_box["x"]) + float(right_box["width"]),
    ) - max(float(left_box["x"]), float(right_box["x"]))
    intersection_height = min(
        float(left_box["y"]) + float(left_box["height"]),
        float(right_box["y"]) + float(right_box["height"]),
    ) - max(float(left_box["y"]), float(right_box["y"]))
    return intersection_width > 0 and intersection_height > 0


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
    target_compact = candidate_visible_text.replace(" ", "")
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
            if scanned_count > MAX_PRINTED_LABEL_TEXT_OBJECT_SCAN:
                raise ReadinessContractError(
                    "printed-label PDF text-object scan exceeds its cap"
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
            if len(intersecting) >= MAX_PRINTED_LABEL_TEXT_OBJECTS:
                raise ReadinessContractError(
                    "printed-label PDF text-object count exceeds its cap"
                )
            try:
                object_text = text_object.extract()
                object_text_bytes = object_text.encode("utf-8")
            except Exception as exc:
                raise ReadinessContractError(
                    "printed-label PDF text-object text is unavailable"
                ) from exc
            if len(object_text_bytes) > MAX_CANDIDATE_TEXT_UTF8_BYTES:
                raise ReadinessContractError(
                    "printed-label PDF text-object text exceeds its cap"
                )
            compact_text = "".join(object_text.split())
            render_mode = pdfium_c.FPDFTextObj_GetTextRenderMode(text_object.raw)
            red, green, blue, alpha = (c_uint() for _ in range(4))
            if not pdfium_c.FPDFPageObj_GetFillColor(
                text_object.raw, red, green, blue, alpha
            ):
                raise ReadinessContractError(
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
        raise ReadinessContractError("printed-label PDF candidate-text custody differs")

    selected = tuple(intersecting[index] for index in next(iter(matches)))
    if any(
        record[3] not in PRINTED_LABEL_PAINTED_FILL_RENDER_MODES or record[4] == 0
        for record in selected
    ):
        raise ReadinessContractError(
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
        raise ReadinessContractError("printed-label PDF fill/object custody differs")
    return selected_fill_rgbs


def validate_rendered_label_visibility(
    source_pdf_bytes: bytes,
    *,
    physical_page_index: int,
    candidate_visible_text: str,
    candidate_bbox: Mapping[str, Any],
    non_stroking_fills: Sequence[Any],
) -> None:
    """Require a printed label to be visibly distinct in its exact PDF crop.

    The candidate bbox uses top-left points.  The crop is rasterized once at
    exactly four pixels per point against opaque white, without forms or
    annotations.  Each scaled bbox edge is rounded to its nearest integer pixel
    with ties to even before rendering.  Both the crop's maximum modal-RGB
    delta and every selected PDFium text-object fill's modal-RGB delta must be
    at least 16 byte levels (16/255).  Candidate-local objects are selected by
    exact bounded visible text plus positive bbox intersection.  They must use
    a fill-painting render mode (0/2/4/6) and nonzero fill alpha.  DeviceGray
    and DeviceRGB source fills corroborate PDFium exactly; DeviceCMYK permits
    at most the frozen 36-channel Adobe-conversion difference in either
    custody direction.  PDFium's selected-object RGB remains authoritative
    for the contrast decision.
    This is an ephemeral admission gate: success returns ``None`` and no
    rendered pixels or visibility proof may be serialized or retained.
    """

    if (
        not isinstance(source_pdf_bytes, bytes)
        or not source_pdf_bytes
        or len(source_pdf_bytes) > MAX_SOURCE_PDF_BYTES
    ):
        raise ReadinessContractError("printed-label visibility PDF differs")
    page_index = _index(
        physical_page_index,
        "printed_label.physical_page_index",
        maximum=MAX_PAGES_PER_DOCUMENT,
    )
    visible_text = _safe_semantic_string(
        candidate_visible_text,
        "printed_label.candidate_visible_text",
        maximum_bytes=MAX_VISIBLE_TEXT_UTF8_BYTES,
        normalization="NFC",
    )
    if not isinstance(candidate_bbox, Mapping) or set(candidate_bbox) != set(
        BBOX_FIELDS
    ):
        raise ReadinessContractError("printed-label visibility bbox differs")
    bbox = _canonical_bbox(candidate_bbox, path="printed_label.visibility_bbox")
    if (
        not isinstance(non_stroking_fills, Sequence)
        or isinstance(non_stroking_fills, (str, bytes, bytearray))
        or not non_stroking_fills
        or len(non_stroking_fills) > MAX_PRINTED_LABEL_NON_STROKING_FILLS
    ):
        raise ReadinessContractError("printed-label PDF fill count differs")
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
        with pdfium.PdfDocument(source_pdf_bytes) as document:
            if not 1 <= len(document) <= MAX_PAGES_PER_DOCUMENT:
                raise ReadinessContractError(
                    "printed-label visibility PDF page count differs"
                )
            if page_index > len(document):
                raise ReadinessContractError(
                    "printed-label visibility page is unavailable"
                )
            page = document[page_index - 1]
            try:
                page_rotation = page.get_rotation()
                if page_rotation not in {0, 90, 180, 270}:
                    raise ReadinessContractError(
                        "printed-label visibility page rotation differs"
                    )
                page_width, page_height = (float(value) for value in page.get_size())
                if not all(
                    math.isfinite(value)
                    and 0 < value <= MAX_PRINTED_LABEL_PAGE_DIMENSION_PT
                    for value in (page_width, page_height)
                ):
                    raise ReadinessContractError(
                        "printed-label visibility page geometry differs"
                    )
                validate_bbox(
                    bbox,
                    page_width=page_width,
                    page_height=page_height,
                    path="printed_label.visibility_bbox",
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
                    or width_px_bound > MAX_PRINTED_LABEL_RENDER_DIMENSION_PX
                    or height_px_bound > MAX_PRINTED_LABEL_RENDER_DIMENSION_PX
                    or width_px_bound * height_px_bound
                    > MAX_PRINTED_LABEL_RENDER_PIXELS
                ):
                    raise ReadinessContractError(
                        "printed-label visibility render bounds differ"
                    )
                left = left_px / PRINTED_LABEL_RENDER_SCALE_PX_PER_PT
                top = top_px / PRINTED_LABEL_RENDER_SCALE_PX_PER_PT
                right = max(
                    0.0,
                    page_width - right_px / PRINTED_LABEL_RENDER_SCALE_PX_PER_PT,
                )
                bottom = max(
                    0.0,
                    page_height - bottom_px / PRINTED_LABEL_RENDER_SCALE_PX_PER_PT,
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
                    image = bitmap.to_pil()
                    try:
                        width_px = bitmap.width
                        height_px = bitmap.height
                        pixel_count = width_px * height_px
                        if (
                            image.mode != "RGB"
                            or image.size != (width_px, height_px)
                            or image.size != (width_px_bound, height_px_bound)
                            or width_px < 1
                            or height_px < 1
                            or width_px > MAX_PRINTED_LABEL_RENDER_DIMENSION_PX
                            or height_px > MAX_PRINTED_LABEL_RENDER_DIMENSION_PX
                            or pixel_count > MAX_PRINTED_LABEL_RENDER_PIXELS
                        ):
                            raise ReadinessContractError(
                                "printed-label visibility bitmap differs"
                            )
                        rgb_bytes = image.tobytes()
                        if len(rgb_bytes) != pixel_count * 3:
                            raise ReadinessContractError(
                                "printed-label visibility RGB payload differs"
                            )
                        colors = image.getcolors(maxcolors=pixel_count)
                        if not colors:
                            raise ReadinessContractError(
                                "printed-label visibility colors differ"
                            )
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    except ReadinessContractError:
        raise
    except Exception as exc:
        raise ReadinessContractError(
            "printed-label visibility rendering failed"
        ) from exc

    _modal_count, modal_rgb = min(colors, key=lambda record: (-record[0], record[1]))
    render_delta = max(
        _rgb_max_channel_delta(color, modal_rgb) for _count_value, color in colors
    )
    fill_deltas = tuple(
        _rgb_max_channel_delta(fill, modal_rgb) for fill in selected_fill_rgbs
    )
    minimum_fill_delta = min(fill_deltas)
    if (
        render_delta < PRINTED_LABEL_MIN_RGB_CHANNEL_DELTA
        or minimum_fill_delta < PRINTED_LABEL_MIN_RGB_CHANNEL_DELTA
    ):
        raise ReadinessContractError(
            "printed-label render/fill contrast is below the closed threshold"
        )


def _bbox_union(values: Sequence[Mapping[str, Any]], *, path: str) -> dict[str, Any]:
    if not values:
        raise ReadinessContractError(f"{path} is empty")
    boxes = [_canonical_bbox(value, path=f"{path}.bbox") for value in values]
    units = {box["unit"] for box in boxes}
    if len(units) != 1:
        raise ReadinessContractError(f"{path} coordinate frames differ")
    left = min(float(box["x"]) for box in boxes)
    top = min(float(box["y"]) for box in boxes)
    right = max(float(box["x"]) + float(box["width"]) for box in boxes)
    bottom = max(float(box["y"]) + float(box["height"]) for box in boxes)
    return {
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
        "unit": next(iter(units)),
    }


def _ir_bbox_in_page_frame(
    ir_document: Mapping[str, Any],
    bbox_id: str,
    *,
    page_id: str,
    path: str,
) -> dict[str, Any]:
    bbox_matches = [
        bbox
        for bbox in ir_document.get("bboxes", [])
        if isinstance(bbox, Mapping) and bbox.get("id") == bbox_id
    ]
    if len(bbox_matches) != 1:
        raise ReadinessContractError(f"{path} IR bbox is not unique")
    bbox = bbox_matches[0]
    coordinate_matches = [
        coordinate
        for coordinate in ir_document.get("coordinate_systems", [])
        if isinstance(coordinate, Mapping)
        and coordinate.get("id") == bbox.get("coordinate_system_id")
    ]
    if (
        len(coordinate_matches) != 1
        or coordinate_matches[0].get("page_id") != page_id
        or coordinate_matches[0].get("origin") != "top_left"
        or coordinate_matches[0].get("unit") != "pt"
    ):
        raise ReadinessContractError(f"{path} IR coordinate frame differs")
    return _canonical_bbox(
        {
            "x": bbox.get("x"),
            "y": bbox.get("y"),
            "width": bbox.get("width"),
            "height": bbox.get("height"),
            "unit": coordinate_matches[0]["unit"],
        },
        path=f"{path}.bbox",
    )


def _normalized_label_value(value: Any, path: str) -> str:
    label = _safe_semantic_string(
        value,
        path,
        maximum_bytes=MAX_LABEL_UTF8_BYTES,
        normalization="NFC",
    )
    if _INTEGER_RE.fullmatch(label):
        return label
    match = _NORMALIZED_FRACTION_RE.fullmatch(label)
    if match is None:
        match = _NORMALIZED_PAGE_OF_RE.fullmatch(label)
    if match is not None and int(match.group(1)) <= int(match.group(2)):
        return label
    raise ReadinessContractError(f"{path} is outside normalized label grammar")


def _normalized_navigation_cue(value: Any, path: str) -> str:
    cue = _string(value, path, maximum_bytes=64)
    if cue in NAVIGATION_GLYPH_CUES:
        return cue
    cue = _safe_semantic_string(
        cue,
        path,
        maximum_bytes=64,
        normalization="NFC",
    )
    canonical = cue.upper()
    if canonical not in NAVIGATION_TEXT_CUES:
        raise ReadinessContractError(f"{path} is outside the closed navigation cues")
    return canonical


def _has_prior_semantic_owner(owner: Mapping[str, Any]) -> bool:
    return bool(set(owner) & _PRIOR_SEMANTIC_MARKER_KEYS)


def _normalized_repetition_text(value: Any, path: str) -> str:
    text = _string(value, path, maximum_bytes=MAX_CANDIDATE_TEXT_UTF8_BYTES)
    normalized = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    if not normalized:
        raise ReadinessContractError(f"{path} is empty after normalization")
    return normalized


def _validate_repetition_signature_binding(
    candidate: Mapping[str, Any],
    owner: Mapping[str, Any],
    *,
    label_candidates: Sequence[Mapping[str, Any]],
    required: bool = False,
    source_text_override: str | None = None,
) -> None:
    if not required and candidate["source_method"] != "cross_page_repetition":
        return
    source_text = _string(
        owner.get("value") if source_text_override is None else source_text_override,
        "source_candidate.owner.value",
        maximum_bytes=MAX_CANDIDATE_TEXT_UTF8_BYTES,
    )
    declared = _string(
        candidate["normalized_signature"],
        "source_candidate.normalized_signature",
        maximum_bytes=MAX_CANDIDATE_TEXT_UTF8_BYTES,
    )
    if "{page}" not in declared:
        expected = _normalized_repetition_text(
            source_text, "source_candidate.owner.value"
        )
    else:
        if declared.count("{page}") != 1:
            raise ReadinessContractError("repetition page placeholder count differs")
        source_ids = set(candidate["source_object_ids"])
        eligible_labels = [
            label
            for label in label_candidates
            if isinstance(label, Mapping)
            and label.get("confidence")
            == {
                "scope": "deterministic_rule",
                "score": 1.0,
                "unavailable_reason": None,
            }
            and not label.get("concern_codes")
            and bool(source_ids & set(label.get("source_object_ids", ())))
        ]
        if len(eligible_labels) != 1:
            raise ReadinessContractError(
                "repetition page-label substitution is ambiguous"
            )
        visible = eligible_labels[0]["visible_text"]
        if source_text.count(visible) != 1:
            raise ReadinessContractError("repetition page-label source span differs")
        expected = _normalized_repetition_text(
            source_text.replace(visible, "{page}", 1),
            "source_candidate.placeholder_value",
        )
    if declared != expected:
        raise ReadinessContractError("repetition normalized signature differs")


def _validate_navigation_source_text(
    candidate: Mapping[str, Any],
    proof: Mapping[str, Any] | None,
    owner: Mapping[str, Any],
) -> None:
    if candidate["source_method"] != "boundary_navigation":
        return
    if not isinstance(proof, Mapping):
        raise ReadinessContractError("navigation source proof is absent")
    cue = _normalized_navigation_cue(
        proof.get("navigation_cue"), "source_candidate.navigation_cue"
    )
    owner_text = _string(
        owner.get("value"),
        "source_candidate.navigation_owner.value",
        maximum_bytes=MAX_CANDIDATE_TEXT_UTF8_BYTES,
    )
    if cue in NAVIGATION_GLYPH_CUES:
        present = cue in owner_text
    else:
        present = (
            re.search(
                rf"(?<!\w){re.escape(cue)}(?!\w)",
                unicodedata.normalize("NFC", owner_text).upper(),
            )
            is not None
        )
    if not present:
        raise ReadinessContractError("navigation cue is absent from source owner text")


def _validate_raw_layout_role_binding(
    candidate: Mapping[str, Any],
    owner: Mapping[str, Any],
    *,
    predecessor_ir: Mapping[str, Any] | None,
) -> None:
    raw_role = candidate["raw_layout_role"]
    if (
        raw_role is None
        or candidate["source_method"] == "extracted_source_contribution"
    ):
        return

    def has_role(value: Mapping[str, Any]) -> bool:
        return _mapping_has_raw_layout_role(value, raw_role)

    if not has_role(owner):
        raise ReadinessContractError("candidate public raw layout role is unproven")
    if predecessor_ir is not None:
        elements = predecessor_ir.get("elements")
        if not isinstance(elements, (list, tuple)):
            raise ReadinessContractError("predecessor IR elements are absent")
        matches = [
            element
            for element in elements
            if isinstance(element, Mapping)
            and element.get("id") == candidate["element_id"]
        ]
        if len(matches) != 1 or not has_role(matches[0]):
            raise ReadinessContractError("candidate IR raw layout role is unproven")


def _mapping_has_raw_layout_role(value: Mapping[str, Any], raw_role: str) -> bool:
    mapped_type = "header" if raw_role == "page_header" else "footer"
    if (
        value.get("type") == mapped_type
        or value.get("label") == raw_role
        or value.get("raw_layout_role") == raw_role
    ):
        return True
    properties = value.get("properties")
    legacy_item = (
        properties.get("legacy_item") if isinstance(properties, Mapping) else None
    )
    return isinstance(legacy_item, Mapping) and (
        legacy_item.get("type") == mapped_type
        or legacy_item.get("label") == raw_role
        or legacy_item.get("raw_layout_role") == raw_role
    )


def _validate_extracted_method_evidence_binding(
    candidate: Mapping[str, Any],
    proof: Mapping[str, Any] | None,
    descriptor: Mapping[str, Any],
    predecessor_owner: Mapping[str, Any],
    *,
    predecessor_ir: Mapping[str, Any] | None,
    source_sha256: str,
    extracted_plan: ExtractedContributionPlan | None,
    page_height: float,
    source_character_count: int,
    source_word_count: int,
) -> None:
    """Bind extracted eligibility and the nested-native exception to source/IR."""

    if candidate["source_method"] != "extracted_source_contribution":
        return
    if not isinstance(proof, Mapping) or not isinstance(
        extracted_plan, ExtractedContributionPlan
    ):
        raise ReadinessContractError("extracted source evidence proof is absent")
    extracted_plan.execute()
    if (
        extracted_plan.physical_page_index != descriptor["physical_page_index"]
        or extracted_plan.owner_public_item_id != candidate["public_item_id"]
        or extracted_plan.owner_sha256_before
        != sha256_json(_compact_public_item(predecessor_owner))
        or extracted_plan.predecessor_canonical != predecessor_owner.get("value")
        or extracted_plan.predecessor_canonical != predecessor_owner.get("md")
    ):
        raise ReadinessContractError("extracted plan predecessor custody differs")
    if not isinstance(predecessor_ir, Mapping):
        raise ReadinessContractError("extracted predecessor IR is absent")
    path = validate_public_path(
        candidate["public_path"], path="extracted_evidence.public_path"
    )
    if (
        len(path) != 4
        or path[2] != "items"
        or isinstance(path[3], bool)
        or not isinstance(path[3], int)
    ):
        raise ReadinessContractError("extracted trusted public path differs")
    exact_owner_elements = []
    for value in predecessor_ir.get("elements", []):
        if (
            not isinstance(value, Mapping)
            or value.get("presentation_role") != "primary"
        ):
            continue
        properties = value.get("properties")
        legacy_item = (
            properties.get("legacy_item") if isinstance(properties, Mapping) else None
        )
        if (
            isinstance(properties, Mapping)
            and properties.get("source_position") == path[3]
            and isinstance(legacy_item, Mapping)
            and dict(legacy_item) == dict(predecessor_owner)
        ):
            exact_owner_elements.append(value)
    if len(exact_owner_elements) != 1:
        raise ReadinessContractError("extracted exact predecessor IR owner is unproven")
    owner_element = exact_owner_elements[0]
    owner_page_id = owner_element.get("page_id")
    ir_page_matches = [
        page
        for page in predecessor_ir.get("pages", [])
        if isinstance(page, Mapping)
        and page.get("id") == owner_page_id
        and page.get("page_index") == descriptor["physical_page_index"]
    ]
    if len(ir_page_matches) != 1 or owner_element.get("id") not in ir_page_matches[
        0
    ].get("presentation_element_ids", []):
        raise ReadinessContractError("extracted predecessor IR page differs")

    source_runs = _ordered_source_reference_runs(
        candidate["source_object_ids"],
        source_sha256=source_sha256,
        page_index=descriptor["physical_page_index"],
        path="extracted_evidence.source_object_ids",
        source_character_count=source_character_count,
        source_word_count=source_word_count,
    )
    if (
        not extracted_plan.source_text.isascii()
        or len(source_runs["character"]) != len(extracted_plan.source_text)
        or len(source_runs["word"])
        != len(re.findall(r"\S+", extracted_plan.source_text))
    ):
        raise ReadinessContractError("extracted native source span differs")

    owner_bbox = predecessor_owner.get("bbox")
    if (
        _candidate_area_coverage(candidate["bbox"], owner_bbox)
        < EXTRACTED_NATIVE_MIN_CANDIDATE_AREA_COVERAGE
    ):
        raise ReadinessContractError("extracted coarse owner coverage differs")

    evidence_records = predecessor_ir.get("evidence")
    if not isinstance(evidence_records, (list, tuple)):
        raise ReadinessContractError("extracted predecessor evidence is absent")
    native_source_evidence = []
    for record in evidence_records:
        if not isinstance(record, Mapping):
            continue
        metadata = record.get("metadata")
        if (
            record.get("method") == "native"
            and record.get("value") == extracted_plan.source_text
            and record.get("element_id") == owner_element.get("id")
            and isinstance(metadata, Mapping)
            and tuple(metadata.get("source_object_ids", ()))
            == tuple(candidate["source_object_ids"])
        ):
            native_source_evidence.append(record)
    if len(native_source_evidence) != 1 or native_source_evidence[0].get(
        "id"
    ) not in owner_element.get("evidence_ids", []):
        raise ReadinessContractError("extracted native source evidence differs")
    native_bbox_id = native_source_evidence[0].get("bbox_id")
    if not isinstance(native_bbox_id, str) or _ir_bbox_in_page_frame(
        predecessor_ir,
        native_bbox_id,
        page_id=owner_page_id,
        path="extracted_evidence.native",
    ) != _canonical_bbox(candidate["bbox"], path="extracted_evidence.candidate_bbox"):
        raise ReadinessContractError("extracted native evidence bbox differs")

    contained_items = predecessor_owner.get("contained_items")
    relationships = predecessor_owner.get("relationships")
    if not isinstance(contained_items, (list, tuple)) or not isinstance(
        relationships, (list, tuple)
    ):
        raise ReadinessContractError("extracted nested-native graph is absent")
    selected_children: list[Mapping[str, Any]] = []
    selected_positions: list[int] = []
    for fragment in extracted_plan.presentation_fragments:
        matches = [
            (position, child)
            for position, child in enumerate(contained_items)
            if isinstance(child, Mapping)
            and child.get("value") == fragment
            and child.get("md") == fragment
            and child.get("source") == "native"
            and child.get("presentation_role") == "subordinate"
            and child.get("contained_by") == predecessor_owner.get("id")
            and child.get("relationship_type") == "contains"
            and child.get("relationship_basis") == "graph_and_geometry"
        ]
        if len(matches) != 1:
            raise ReadinessContractError("extracted nested-native child is not unique")
        position, child = matches[0]
        child_id = child.get("id")
        relationship_id = child.get("relationship_id")
        graph_matches = [
            relationship
            for relationship in relationships
            if isinstance(relationship, Mapping)
            and relationship.get("id") == relationship_id
            and relationship.get("source_id") == predecessor_owner.get("id")
            and relationship.get("target_id") == child_id
            and relationship.get("type") == "contains"
        ]
        if not isinstance(child_id, str) or not child_id or len(graph_matches) != 1:
            raise ReadinessContractError("extracted nested-native graph link differs")
        selected_positions.append(position)
        selected_children.append(child)
    if selected_positions != sorted(selected_positions) or len(
        {child["id"] for child in selected_children}
    ) != len(selected_children):
        raise ReadinessContractError("extracted nested-native child order differs")

    child_union = _bbox_union(
        [child["bbox"] for child in selected_children],
        path="extracted_evidence.child_union",
    )
    if (
        _candidate_area_coverage(candidate["bbox"], child_union)
        < EXTRACTED_NATIVE_MIN_CHILD_AREA_COVERAGE
        or _vertical_center_delta(candidate["bbox"], child_union)
        > page_height * NATIVE_LABEL_MAX_VERTICAL_CENTER_DELTA_RATIO
    ):
        raise ReadinessContractError("extracted nested-native child geometry differs")

    elements = predecessor_ir.get("elements")
    if not isinstance(elements, (list, tuple)):
        raise ReadinessContractError("extracted predecessor IR elements are absent")
    for fragment, child in zip(
        extracted_plan.presentation_fragments, selected_children, strict=True
    ):
        child_elements = [
            element
            for element in elements
            if isinstance(element, Mapping) and element.get("id") == child["id"]
        ]
        if len(child_elements) != 1:
            raise ReadinessContractError("extracted nested IR child is not unique")
        child_element = child_elements[0]
        properties = child_element.get("properties")
        legacy_item = (
            properties.get("legacy_item") if isinstance(properties, Mapping) else None
        )
        if (
            child_element.get("page_id") != owner_page_id
            or child_element.get("presentation_role") != "subordinate"
            or child_element.get("source") != "native"
            or child_element.get("value") != fragment
            or child_element.get("markdown") != fragment
            or not isinstance(properties, Mapping)
            or properties.get("parent_element_id") != owner_element.get("id")
            or not isinstance(legacy_item, Mapping)
            or dict(legacy_item) != dict(child)
            or child_element.get("id") not in ir_page_matches[0].get("element_ids", [])
            or child_element.get("id")
            in ir_page_matches[0].get("presentation_element_ids", [])
        ):
            raise ReadinessContractError("extracted nested IR child custody differs")
        matching_bbox_ids = [
            bbox_id
            for bbox_id in child_element.get("bbox_ids", [])
            if isinstance(bbox_id, str)
            and _ir_bbox_in_page_frame(
                predecessor_ir,
                bbox_id,
                page_id=owner_page_id,
                path="extracted_evidence.child",
            )
            == _canonical_bbox(
                child["bbox"], path="extracted_evidence.public_child_bbox"
            )
        ]
        child_evidence = [
            record
            for record in evidence_records
            if isinstance(record, Mapping)
            and record.get("id") in child_element.get("evidence_ids", [])
            and record.get("element_id") == child_element.get("id")
            and record.get("bbox_id") in matching_bbox_ids
            and record.get("method") == "native"
            and record.get("value") == fragment
        ]
        if len(matching_bbox_ids) != 1 or len(child_evidence) != 1:
            raise ReadinessContractError("extracted nested IR evidence differs")

    evidence_mode = proof.get("evidence_mode")
    declared_pages = tuple(proof.get("repetition_page_indexes", ()))
    if evidence_mode == "exact_repetition":
        if (
            descriptor["repetition_group_id"] is None
            or declared_pages != tuple(descriptor["repetition_page_indexes"])
            or declared_pages != tuple(sorted(set(declared_pages)))
            or len(declared_pages) < 2
        ):
            raise ReadinessContractError(
                "extracted repetition evidence membership differs"
            )
        expected_group_id = stable_id(
            "running-repeat",
            POLICY_ID,
            source_sha256,
            candidate["boundary_band"],
            candidate["normalized_signature"],
        )
        if descriptor["repetition_group_id"] != expected_group_id:
            raise ReadinessContractError("extracted repetition evidence group differs")
        return
    if evidence_mode != "trusted_layout_role":
        raise ReadinessContractError("extracted evidence mode differs")
    raw_role = candidate["raw_layout_role"]
    if (
        raw_role not in {"page_header", "page_footer"}
        or not _mapping_has_raw_layout_role(predecessor_owner, raw_role)
        or not _mapping_has_raw_layout_role(owner_element, raw_role)
    ):
        raise ReadinessContractError("extracted trusted layout role is unproven")


def _validate_effective_extension_binding(
    candidate: Mapping[str, Any],
    proof: Mapping[str, Any] | None,
    *,
    label_candidates: Sequence[Mapping[str, Any]],
    page_width: float,
    page_height: float,
) -> None:
    """Require any outer-30% admission to prove its exact effective member."""

    if not isinstance(proof, Mapping):
        raise ReadinessContractError("effective boundary extension proof is absent")
    method = candidate["source_method"]
    member_kind: Literal["any", "furniture", "navigation", "label"] = "any"
    cue: str | None = None
    normalized_label: str | None = None
    if method == "effective_boundary_cluster":
        cluster_proof = proof
        member_kind = "furniture"
    elif method == "boundary_navigation":
        cluster_proof = proof.get("effective_cluster")
        cue = _normalized_navigation_cue(
            proof.get("navigation_cue"), "method_proof.navigation.navigation_cue"
        )
        member_kind = "navigation"
    elif method == "printed_label_boundary":
        cluster_proof = proof.get("effective_cluster")
        matches = [
            label
            for label in label_candidates
            if label.get("id") == proof.get("label_candidate_id")
        ]
        if len(matches) != 1:
            raise ReadinessContractError("effective printed-label candidate is absent")
        label = matches[0]
        if not _native_label_owner_geometry_matches(
            label["bbox"],
            candidate["bbox"],
            page_height=page_height,
        ) or not set(candidate["source_object_ids"]) & set(label["source_object_ids"]):
            raise ReadinessContractError("effective printed-label binding differs")
        normalized_label = label["normalized_label"]
        member_kind = "label"
    elif method == "extracted_source_contribution":
        cluster_proof = proof.get("effective_cluster")
    else:
        cluster_proof = proof
    if not isinstance(cluster_proof, Mapping):
        raise ReadinessContractError("effective cluster proof is absent")
    _validate_effective_candidate_membership(
        candidate,
        cluster_proof,
        page_width=page_width,
        page_height=page_height,
        member_kind=member_kind,
        navigation_cue=cue,
        normalized_label=normalized_label,
    )


def validate_effective_bottom_cluster(
    items: Sequence[Mapping[str, Any]],
    *,
    remaining_body_bboxes: Sequence[Mapping[str, Any]],
    page_width: float,
    page_height: float,
    candidate_cut_count: int,
) -> float:
    """Validate the narrow three-item-or-more effective-bottom extension."""

    if (
        not isinstance(items, (list, tuple))
        or not isinstance(remaining_body_bboxes, (list, tuple))
        or isinstance(page_width, bool)
        or not isinstance(page_width, (int, float))
        or not math.isfinite(page_width)
        or page_width <= 0
        or isinstance(page_height, bool)
        or not isinstance(page_height, (int, float))
        or not math.isfinite(page_height)
        or page_height <= 0
        or isinstance(candidate_cut_count, bool)
        or not isinstance(candidate_cut_count, int)
        or len(items) < 3
        or candidate_cut_count != 1
    ):
        raise ReadinessContractError("effective-bottom cluster size/cut differs")
    identifiers: list[str] = []
    indexes: list[int] = []
    rectangles: list[tuple[float, float, float, float]] = []
    navigation_indexes: list[int] = []
    label_indexes: list[int] = []
    for offset, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ReadinessContractError("effective-bottom item is not an object")
        _exact_keys(item, EFFECTIVE_CLUSTER_ITEM_FIELDS, "effective_bottom.item")
        identifiers.append(_string(item["id"], "effective_bottom.item.id"))
        indexes.append(
            _count(item["presentation_index"], "effective_bottom.item.order")
        )
        validate_bbox(
            item["bbox"],
            page_width=page_width,
            page_height=page_height,
            path="effective_bottom.item.bbox",
        )
        bbox = item["bbox"]
        rectangle = tuple(float(bbox[key]) for key in ("x", "y", "width", "height"))
        rectangles.append(rectangle)  # type: ignore[arg-type]
        if rectangle[1] < page_height * 0.70:
            raise ReadinessContractError("effective-bottom item exceeds outer 30%")
        if item["claimed"] is not False:
            raise ReadinessContractError("effective-bottom item has a prior owner")
        if item["navigation_cue"] is not None:
            _normalized_navigation_cue(
                item["navigation_cue"], "effective_bottom.item.navigation_cue"
            )
            navigation_indexes.append(offset)
        if item["normalized_label"] is not None:
            _normalized_label_value(
                item["normalized_label"],
                "effective_bottom.item.normalized_label",
            )
            label_indexes.append(offset)
    if len(identifiers) != len(set(identifiers)):
        raise ReadinessContractError("effective-bottom ownership is duplicated")
    if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        raise ReadinessContractError("effective-bottom order is noncontiguous")
    midpoints = [y + height / 2 for _, y, _, height in rectangles]
    if max(midpoints) - min(midpoints) > page_height * 0.02 + 0.001:
        raise ReadinessContractError("effective-bottom baseline differs")
    ordered_x = sorted((x, x + width) for x, _, width, _ in rectangles)
    if any(
        right > next_left + 0.001 for (_, right), (next_left, _) in pairwise(ordered_x)
    ):
        raise ReadinessContractError("effective-bottom horizontal intervals overlap")
    if (
        not navigation_indexes
        or len(label_indexes) != 1
        or label_indexes[0] in navigation_indexes
    ):
        raise ReadinessContractError("effective-bottom cue/label evidence differs")
    cluster_top = min(y for _, y, _, _ in rectangles)
    for bbox in remaining_body_bboxes:
        validate_bbox(
            bbox,
            page_width=page_width,
            page_height=page_height,
            path="effective_bottom.remaining_body_bbox",
        )
        if float(bbox["y"]) + float(bbox["height"]) >= cluster_top:
            raise ReadinessContractError("effective-bottom cluster overlaps body")
    return cluster_top


def validate_confidence(value: Mapping[str, Any], *, path: str = "confidence") -> None:
    """Validate the exact deterministic/source-metadata/fallback confidence."""

    if not isinstance(value, Mapping):
        raise ReadinessContractError(f"{path} is not an object")
    _exact_keys(value, CONFIDENCE_FIELDS, path)
    scope, score, reason = (
        value["scope"],
        value["score"],
        value["unavailable_reason"],
    )
    if score is None:
        if scope != "unavailable" or reason not in {
            "page_identity_source_unavailable",
            "page_identity_display_fallback_physical",
        }:
            raise ReadinessContractError(f"{path} unavailable state differs")
        return
    if (
        scope not in {"deterministic_rule", "source_metadata"}
        or isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 0 <= float(score) <= 1
        or reason is not None
    ):
        raise ReadinessContractError(f"{path} score differs")


def validate_evidence_source(
    value: Mapping[str, Any],
    *,
    display_source: str,
    physical_page_index: int,
    has_detected_evidence: bool,
) -> None:
    """Validate the selected/conflict evidence binding and its nullability."""

    if not isinstance(value, Mapping):
        raise ReadinessContractError("evidence_source is not an object")
    _exact_keys(value, EVIDENCE_SOURCE_FIELDS, "page_identity.evidence_source")
    method = value["method"]
    reader = value["reader"]
    if value["page_index"] != physical_page_index:
        raise ReadinessContractError("evidence source page differs")
    public_path = value["public_path"]
    evidence_ids = _references(
        value["evidence_ids"],
        "page_identity.evidence_source.evidence_ids",
        allow_empty=True,
    )
    source_ids = _references(
        value["source_object_ids"],
        "page_identity.evidence_source.source_object_ids",
        allow_empty=(display_source == "physical" and not has_detected_evidence),
    )
    nullable_ids = ("public_item_id", "element_id", "bbox_id")
    if has_detected_evidence:
        if method != "native_printed_label" or reader != "pdfplumber":
            raise ReadinessContractError("detected evidence method/reader differs")
        if not evidence_ids or not source_ids:
            raise ReadinessContractError("detected source provenance is incomplete")
        attached = all(
            isinstance(value[key], str) and bool(value[key]) for key in nullable_ids
        )
        detached = all(value[key] is None for key in nullable_ids)
        if attached:
            validate_public_path(
                public_path, path="page_identity.evidence_source.public_path"
            )
        elif detached:
            if not isinstance(public_path, (list, tuple)) or public_path:
                raise ReadinessContractError(
                    "detached detected evidence path is not empty"
                )
        else:
            raise ReadinessContractError("detected evidence IDs are partially bound")
        return
    if not isinstance(public_path, (list, tuple)) or public_path:
        raise ReadinessContractError("fallback evidence path is not empty")
    if any(value[key] is not None for key in nullable_ids):
        raise ReadinessContractError("fallback evidence IDs are not null")
    if display_source == "embedded_label":
        if method != "embedded_pdf_label" or reader != "pypdfium2" or not evidence_ids:
            raise ReadinessContractError("embedded evidence binding differs")
    elif display_source == "legacy_display_fallback":
        if (
            method != "legacy_display_fallback"
            or reader != "configured_predecessor"
            or evidence_ids
            or len(source_ids) != 1
        ):
            raise ReadinessContractError("legacy evidence binding differs")
    elif display_source == "physical":
        if (
            method != "physical_page_index"
            or reader != "configured_predecessor"
            or evidence_ids
            or source_ids
        ):
            raise ReadinessContractError("physical evidence binding differs")
    else:
        raise ReadinessContractError("detected display lacks detected evidence")


def validate_page_identity(
    identity: Mapping[str, Any],
    *,
    public_page: Mapping[str, Any] | None = None,
    canonical_page: Mapping[str, Any] | None = None,
) -> None:
    """Validate exact page identity, precedence, conflict, and page custody."""

    if not isinstance(identity, Mapping):
        raise ReadinessContractError("page_identity is not an object")
    _exact_keys(identity, PAGE_IDENTITY_FIELDS, "page_identity")
    if (
        identity["schema_version"] != SCHEMA_VERSION
        or identity["policy_id"] != POLICY_ID
    ):
        raise ReadinessContractError("page identity version/policy differs")
    page_id = _string(identity["page_id"], "page_identity.page_id", maximum_bytes=512)
    physical = _index(
        identity["physical_page_index"],
        "page_identity.physical_page_index",
        maximum=MAX_PAGES_PER_DOCUMENT,
    )
    embedded = identity["embedded_label"]
    if embedded is not None and normalize_embedded_label(embedded) != embedded:
        raise ReadinessContractError("embedded label is not normalized")
    detected = identity["detected_printed_label"]
    visible = identity["visible_text"]
    if (detected is None) != (visible is None):
        raise ReadinessContractError("detected/visible label nullability differs")
    if detected is not None:
        normalized = normalize_detected_label(visible)
        if detected != normalized:
            raise ReadinessContractError("detected label normalization differs")
        _safe_semantic_string(
            detected,
            "page_identity.detected_printed_label",
            maximum_bytes=MAX_LABEL_UTF8_BYTES,
            normalization="NFC",
        )
    display = _safe_semantic_string(
        identity["display_label"],
        "page_identity.display_label",
        maximum_bytes=MAX_LABEL_UTF8_BYTES,
        normalization="NFC",
    )
    source = identity["display_source"]
    if source not in DISPLAY_SOURCES:
        raise ReadinessContractError("display source differs")
    concerns = _known_concerns(
        identity["concern_codes"],
        "page_identity.concern_codes",
        maximum=MAX_CONCERNS_PER_PAGE,
        allowed=PAGE_IDENTITY_CONCERN_CODES,
    )
    conflict = embedded is not None and detected is not None and embedded != detected
    if conflict:
        if (
            source != "embedded_label"
            or display != embedded
            or "page_identity_source_conflict" not in concerns
        ):
            raise ReadinessContractError("page identity conflict selection differs")
    elif detected is not None:
        if source != "detected_printed_label" or display != detected:
            raise ReadinessContractError("detected label did not take precedence")
        if "page_identity_detected_label_ambiguous" in concerns:
            raise ReadinessContractError("ambiguous detected label was promoted")
    elif embedded is not None:
        if source != "embedded_label" or display != embedded:
            raise ReadinessContractError("embedded label selection differs")
    else:
        if source not in {"legacy_display_fallback", "physical"}:
            raise ReadinessContractError("display fallback source differs")
        if source == "physical" and display != str(physical):
            raise ReadinessContractError("physical display fallback differs")
        if public_page is not None:
            legacy = public_page.get("page_label")
            safe_legacy: str | None = None
            if isinstance(legacy, str) and legacy:
                try:
                    safe_legacy = _safe_semantic_string(
                        legacy,
                        "public_page.page_label",
                        maximum_bytes=MAX_LABEL_UTF8_BYTES,
                        normalization="NFC",
                    )
                except ReadinessContractError:
                    safe_legacy = None
            if safe_legacy is not None:
                if source != "legacy_display_fallback" or display != safe_legacy:
                    raise ReadinessContractError("safe legacy fallback differs")
            else:
                if source != "physical" or display != str(physical):
                    raise ReadinessContractError("physical fallback precedence differs")
                if (
                    legacy is not None
                    and legacy != ""
                    and ("page_identity_display_unsafe" not in concerns)
                ):
                    raise ReadinessContractError("unsafe legacy fallback lacks concern")

    has_detected_evidence = detected is not None
    evidence_bbox = identity["evidence_bbox"]
    if has_detected_evidence:
        if evidence_bbox is None:
            raise ReadinessContractError("detected label has no evidence bbox")
        validate_bbox(evidence_bbox, path="page_identity.evidence_bbox")
    elif evidence_bbox is not None:
        raise ReadinessContractError("fallback label has a visible evidence bbox")
    validate_evidence_source(
        identity["evidence_source"],
        display_source=source,
        physical_page_index=physical,
        has_detected_evidence=has_detected_evidence,
    )
    validate_confidence(identity["confidence"], path="page_identity.confidence")
    expected_scope = (
        "source_metadata"
        if source == "embedded_label"
        else "deterministic_rule"
        if source == "detected_printed_label"
        else "unavailable"
    )
    if identity["confidence"]["scope"] != expected_scope:
        raise ReadinessContractError("page identity confidence source differs")
    if expected_scope != "unavailable" and identity["confidence"]["score"] != 1.0:
        raise ReadinessContractError("accepted page identity confidence is not exact")
    if expected_scope == "unavailable":
        expected_reason = (
            "page_identity_display_fallback_physical"
            if source == "physical"
            else "page_identity_source_unavailable"
        )
        if identity["confidence"]["unavailable_reason"] != expected_reason:
            raise ReadinessContractError("page identity fallback confidence differs")

    if public_page is not None and (
        not isinstance(public_page, Mapping)
        or public_page.get("page_index") != physical
    ):
        raise ReadinessContractError("public page physical binding differs")
    if canonical_page is not None:
        if (
            not isinstance(canonical_page, Mapping)
            or canonical_page.get("page_id") != page_id
            or canonical_page.get("page_index") != physical
        ):
            raise ReadinessContractError("canonical page identity binding differs")
        if canonical_page.get("page_identity") != identity:
            raise ReadinessContractError("public/canonical page identity differs")
    if len(strict_json_bytes(identity)) > MAX_PAGE_IDENTITY_BYTES:
        raise ReadinessContractError("page identity JSON exceeds its cap")


def _compact_public_item(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in item.items() if value is not None}


def _predecessor_item(item: Mapping[str, Any], predecessor_type: str) -> dict[str, Any]:
    candidate = _compact_public_item(item)
    for key in RUNNING_REGION_SIDECAR_FIELDS:
        candidate.pop(key, None)
    candidate["type"] = predecessor_type
    return candidate


def predecessor_item_sha256(item: Mapping[str, Any], predecessor_type: str) -> str:
    """Hash an owner after removing US08 fields/restoring predecessor type."""

    return sha256_json(_predecessor_item(item, predecessor_type))


def validate_running_region(
    region: Mapping[str, Any],
    *,
    owning_item: Mapping[str, Any] | None = None,
    public_document: Mapping[str, Any] | None = None,
    source_sha256: str | None = None,
) -> None:
    """Validate one closed running-region descriptor and optional owner/path."""

    if not isinstance(region, Mapping):
        raise ReadinessContractError("running_region is not an object")
    _exact_keys(region, RUNNING_REGION_FIELDS, "running_region")
    for key in (
        "id",
        "page_id",
        "source_public_item_id",
        "source_element_id",
        "predecessor_type",
        "predecessor_item_sha256",
        "bbox_id",
        "canonical_block_id",
    ):
        _string(region[key], f"running_region.{key}", maximum_bytes=512)
    if not _is_hash(region["predecessor_item_sha256"]):
        raise ReadinessContractError("predecessor item hash differs")
    physical = _index(
        region["physical_page_index"],
        "running_region.physical_page_index",
        maximum=MAX_PAGES_PER_DOCUMENT,
    )
    role = region["role"]
    if role not in RUNNING_REGION_ROLES:
        raise ReadinessContractError("running region role differs")
    mapped_type, scope = ROLE_TYPE_SCOPE[role]
    if region["canonical_scope"] != scope:
        raise ReadinessContractError("running region canonical scope differs")
    path = validate_public_path(
        region["source_public_path"], path="running_region.source_public_path"
    )
    validate_bbox(region["bbox"], path="running_region.bbox")
    evidence_ids = _references(
        region["evidence_ids"], "running_region.evidence_ids", allow_empty=False
    )
    source_object_ids = _references(
        region["source_object_ids"],
        "running_region.source_object_ids",
        allow_empty=False,
    )
    if not evidence_ids or not source_object_ids:
        raise ReadinessContractError("running region source references are empty")
    method = region["source_method"]
    if method not in SOURCE_METHODS:
        raise ReadinessContractError("running region source method differs")
    if method == "extracted_source_contribution" and len(evidence_ids) != 1:
        raise ReadinessContractError(
            "extracted contribution requires one synthetic evidence record"
        )
    if method == "trusted_layout_role" and role not in {"header", "footer"}:
        raise ReadinessContractError("trusted layout role mapping differs")
    if method == "boundary_navigation" and role not in {
        "navigation_top",
        "navigation_bottom",
    }:
        raise ReadinessContractError("navigation method role differs")
    if method == "printed_label_boundary" and role not in {"header", "footer"}:
        raise ReadinessContractError("printed-label boundary role differs")
    if method == "effective_boundary_cluster" and role != "footer":
        raise ReadinessContractError("effective-boundary cluster role differs")
    repetition_group = region["repetition_group_id"]
    repetition_pages = region["repetition_page_indexes"]
    if not isinstance(repetition_pages, (list, tuple)):
        raise ReadinessContractError("repetition pages are not ordered")
    pages = tuple(repetition_pages)
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in pages
        )
        or tuple(sorted(set(pages))) != pages
    ):
        raise ReadinessContractError("repetition pages differ")
    if len(pages) > MAX_REPETITION_MEMBERS:
        raise ReadinessContractError("repetition page count exceeds its cap")
    if repetition_group is None:
        if pages or method == "cross_page_repetition":
            raise ReadinessContractError("repetition identity is incomplete")
    else:
        _string(
            repetition_group, "running_region.repetition_group_id", maximum_bytes=512
        )
        if len(pages) < 2 or physical not in pages:
            raise ReadinessContractError("repetition membership differs")
    validate_confidence(region["confidence"], path="running_region.confidence")
    if (
        region["confidence"]["scope"] != "deterministic_rule"
        or region["confidence"]["score"] != 1.0
    ):
        raise ReadinessContractError("accepted running-region confidence differs")
    _known_concerns(
        region["concern_codes"],
        "running_region.concern_codes",
        maximum=MAX_CONCERNS_PER_PAGE,
    )

    if owning_item is not None:
        if not isinstance(owning_item, Mapping):
            raise ReadinessContractError("running-region owner is not an object")
        if (
            owning_item.get("type") != mapped_type
            or _canonical_bbox(
                owning_item.get("bbox"), path="running_region.owner_bbox"
            )
            != region["bbox"]
        ):
            raise ReadinessContractError("marked running item type/bbox differs")
        if method != "extracted_source_contribution":
            if owning_item.get("id") != region["source_public_item_id"]:
                raise ReadinessContractError("direct running item ID differs")
            if (
                predecessor_item_sha256(owning_item, region["predecessor_type"])
                != region["predecessor_item_sha256"]
            ):
                raise ReadinessContractError("direct predecessor item hash differs")
    if public_document is not None:
        resolved = resolve_public_path(public_document, path)
        if (
            not isinstance(resolved, Mapping)
            or resolved.get("id") != region["source_public_item_id"]
        ):
            raise ReadinessContractError("running-region public path differs")
        if method == "extracted_source_contribution":
            if owning_item is not None and resolved == owning_item:
                raise ReadinessContractError("extracted item aliases its fused owner")
            if resolved.get("type") != region["predecessor_type"]:
                raise ReadinessContractError("extracted owner predecessor type differs")
            if (
                sha256_json(_compact_public_item(resolved))
                != region["predecessor_item_sha256"]
            ):
                raise ReadinessContractError("extracted fused owner hash differs")
        elif (
            owning_item is not None
            and resolved is not owning_item
            and resolved != owning_item
        ):
            raise ReadinessContractError("direct running-region path owner differs")
    if source_sha256 is not None:
        if not _is_hash(source_sha256):
            raise ReadinessContractError("source document hash differs")
        id_parts: tuple[object, ...]
        if method == "extracted_source_contribution":
            id_parts = (
                POLICY_ID,
                source_sha256,
                physical,
                region["source_public_item_id"],
                tuple(source_object_ids),
                tuple(evidence_ids),
                region["bbox_id"],
                role,
            )
        else:
            id_parts = (
                POLICY_ID,
                source_sha256,
                physical,
                region["source_element_id"],
                region["bbox_id"],
                role,
            )
        expected_id = stable_id("running-region", *id_parts)
        if region["id"] != expected_id:
            raise ReadinessContractError("running-region stable ID differs")
        if method == "extracted_source_contribution" and owning_item is not None:
            expected_item_id = stable_id("running-region-item", *id_parts)
            if owning_item.get("id") != expected_item_id:
                raise ReadinessContractError("extracted synthetic item ID differs")
    if len(strict_json_bytes(region)) > MAX_RUNNING_DESCRIPTOR_BYTES:
        raise ReadinessContractError("running descriptor JSON exceeds its cap")


def validate_running_region_sidecar(
    sidecar: Mapping[str, Any],
    *,
    owning_item: Mapping[str, Any] | None = None,
    public_document: Mapping[str, Any] | None = None,
    source_sha256: str | None = None,
) -> None:
    """Validate the singular marker and the two other exact item fields."""

    if not isinstance(sidecar, Mapping):
        raise ReadinessContractError("running-region sidecar is not an object")
    _exact_keys(sidecar, RUNNING_REGION_SIDECAR_FIELDS, "running_region_sidecar")
    if sidecar["layout_running_region_projected"] is not True:
        raise ReadinessContractError("running-region marker differs")
    if sidecar["running_region_policy"] != POLICY_ID:
        raise ReadinessContractError("running-region policy differs")
    validate_running_region(
        sidecar["running_region"],
        owning_item=owning_item,
        public_document=public_document,
        source_sha256=source_sha256,
    )


def validate_extracted_evidence_record(
    record: Mapping[str, Any],
    *,
    descriptor: Mapping[str, Any],
    source_text: str,
    source_sha256: str | None = None,
) -> None:
    """Validate the sole additive native EvidenceRecord for an extraction."""

    validate_running_region(descriptor)
    if descriptor["source_method"] != "extracted_source_contribution":
        raise ReadinessContractError("evidence descriptor is not extracted")
    if not isinstance(record, Mapping):
        raise ReadinessContractError("extracted evidence is not an object")
    _exact_keys(record, EXTRACTED_EVIDENCE_FIELDS, "extracted_evidence")
    bounded_source_text = _string(
        source_text,
        "extracted_evidence.source_text",
        maximum_bytes=MAX_EXTRACTED_CONTRIBUTION_UTF8_BYTES,
    )
    evidence_id = descriptor["evidence_ids"][0]
    if (
        record["id"] != evidence_id
        or record["element_id"] != descriptor["source_element_id"]
        or record["bbox_id"] != descriptor["bbox_id"]
        or record["method"] != "native"
        or record["value"] != bounded_source_text
    ):
        raise ReadinessContractError("extracted evidence scalar binding differs")
    confidence = record["confidence"]
    if not isinstance(confidence, Mapping) or dict(confidence) != dict(
        EXTRACTED_EVIDENCE_CONFIDENCE
    ):
        raise ReadinessContractError("extracted evidence confidence differs")
    metadata = record["metadata"]
    if not isinstance(metadata, Mapping):
        raise ReadinessContractError("extracted evidence metadata is not an object")
    _exact_keys(
        metadata,
        EXTRACTED_EVIDENCE_METADATA_FIELDS,
        "extracted_evidence.metadata",
    )
    if (
        metadata["policy_id"] != POLICY_ID
        or not isinstance(metadata["source_object_ids"], list)
        or metadata["source_object_ids"] != list(descriptor["source_object_ids"])
    ):
        raise ReadinessContractError("extracted evidence metadata binding differs")
    if source_sha256 is not None:
        expected_id = extracted_evidence_record_id(
            source_sha256=source_sha256,
            physical_page_index=descriptor["physical_page_index"],
            source_public_item_id=descriptor["source_public_item_id"],
            source_object_ids=descriptor["source_object_ids"],
            bbox_id=descriptor["bbox_id"],
            role=descriptor["role"],
        )
        if record["id"] != expected_id:
            raise ReadinessContractError("extracted evidence stable ID differs")


def _label_has_exact_public_binding(
    public_document: Mapping[str, Any] | None,
    *,
    page_index: int,
    candidate_id: str,
) -> bool:
    """Classify the selected label as attached exact-public or detached native."""

    if public_document is None:
        return False
    pages = public_document.get("pages")
    if not isinstance(pages, (list, tuple)):
        raise ReadinessContractError("label public page custody is absent")
    page_matches = [
        page
        for page in pages
        if isinstance(page, Mapping) and page.get("page_index") == page_index
    ]
    if len(page_matches) != 1:
        raise ReadinessContractError("label public page custody is not unique")
    identity = page_matches[0].get("page_identity")
    if identity is None:
        # A clean configured predecessor intentionally predates US08 identity
        # projection.  Its native label remains detached at extraction time;
        # the final binder re-runs this check against the projected page.
        return False
    evidence_source = (
        identity.get("evidence_source") if isinstance(identity, Mapping) else None
    )
    if not isinstance(evidence_source, Mapping):
        raise ReadinessContractError("label public identity custody is absent")
    evidence_ids = evidence_source.get("evidence_ids")
    if not isinstance(evidence_ids, (list, tuple)) or candidate_id not in evidence_ids:
        return False
    if tuple(evidence_ids) != (candidate_id,):
        raise ReadinessContractError("selected label public evidence is not unique")
    nullable_ids = ("public_item_id", "element_id", "bbox_id")
    attached = all(
        isinstance(evidence_source.get(key), str) and bool(evidence_source[key])
        for key in nullable_ids
    )
    detached = all(evidence_source.get(key) is None for key in nullable_ids)
    public_path = evidence_source.get("public_path")
    if attached:
        if not validate_public_path(
            public_path, path="label.exact_public_binding.public_path"
        ):
            raise ReadinessContractError("exact-public label path is empty")
        return True
    if detached:
        if not isinstance(public_path, (list, tuple)) or public_path:
            raise ReadinessContractError("native-source-only label path is not empty")
        return False
    raise ReadinessContractError("label public IDs are partially bound")


def _validate_label_candidate(
    candidate: Mapping[str, Any],
    *,
    source_sha256: str,
    page_index: int,
    page_width: float,
    page_height: float,
    boundary_candidates: Sequence[Mapping[str, Any]],
    method_proofs: Mapping[str, Mapping[str, Any]],
    exact_public_binding: bool = False,
    source_character_count: int | None = None,
    source_word_count: int | None = None,
) -> None:
    if not isinstance(candidate, Mapping):
        raise ReadinessContractError("label candidate is not an object")
    _exact_keys(candidate, LABEL_CANDIDATE_FIELDS, "report.label_candidate")
    _string(candidate["id"], "report.label_candidate.id", maximum_bytes=512)
    visible = _safe_semantic_string(
        candidate["visible_text"],
        "report.label_candidate.visible_text",
        maximum_bytes=MAX_VISIBLE_TEXT_UTF8_BYTES,
        normalization="NFC",
    )
    if candidate["normalized_label"] != normalize_detected_label(visible):
        raise ReadinessContractError("label candidate normalization differs")
    validate_bbox(
        candidate["bbox"],
        page_width=page_width,
        page_height=page_height,
        path="report.label_candidate.bbox",
    )
    label_y = float(candidate["bbox"]["y"])
    label_bottom = label_y + float(candidate["bbox"]["height"])
    in_top = label_bottom <= page_height * 0.15 + 0.001
    in_nominal_bottom = label_y >= page_height * 0.85 - 0.001
    in_effective_bottom = label_y >= page_height * 0.70 - 0.001
    if not (in_top or in_nominal_bottom or in_effective_bottom):
        raise ReadinessContractError("label candidate is outside a qualifying boundary")
    source_runs = _ordered_source_reference_runs(
        candidate["source_object_ids"],
        source_sha256=source_sha256,
        page_index=page_index,
        path="report.label_candidate.source_object_ids",
        source_character_count=source_character_count,
        source_word_count=source_word_count,
    )
    visible_tokens = re.findall(r"\S+", visible)
    if len(source_runs["word"]) != len(visible_tokens):
        raise ReadinessContractError("label candidate source word span differs")
    if source_runs["character"] and (
        not visible.isascii() or len(source_runs["character"]) != len(visible)
    ):
        raise ReadinessContractError("label candidate source character span differs")
    if candidate["id"] != label_candidate_id(
        source_sha256=source_sha256,
        physical_page_index=page_index,
        source_object_ids=candidate["source_object_ids"],
        bbox=candidate["bbox"],
    ):
        raise ReadinessContractError("label candidate stable ID differs")
    if candidate["source_method"] != "native_printed_label":
        raise ReadinessContractError("label candidate source method differs")
    validate_confidence(
        candidate["confidence"], path="report.label_candidate.confidence"
    )
    _known_concerns(
        candidate["concern_codes"],
        "report.label_candidate.concern_codes",
        maximum=MAX_CONCERNS_PER_PAGE,
    )
    candidate_word_ids = set(source_runs["word"])
    if not candidate_word_ids:
        raise ReadinessContractError("label candidate source word custody is absent")

    def supports_label(boundary: Mapping[str, Any]) -> bool:
        if boundary.get("disposition") != "accepted":
            return False
        owner_word_ids = _source_word_ids(boundary.get("source_object_ids"))
        if not candidate_word_ids <= owner_word_ids:
            return False
        owner_bbox = boundary.get("bbox")
        if exact_public_binding:
            return _bbox_contains(owner_bbox, candidate["bbox"])
        return _native_label_owner_geometry_matches(
            candidate["bbox"], owner_bbox, page_height=page_height
        )

    supporting_boundaries = [
        boundary
        for boundary in boundary_candidates
        if isinstance(boundary, Mapping) and supports_label(boundary)
    ]
    if len(supporting_boundaries) != 1:
        raise ReadinessContractError("label candidate boundary owner is not unique")
    support = supporting_boundaries[0]
    if (
        in_top
        and _INTEGER_RE.fullmatch(visible)
        and not (
            support.get("raw_layout_role") == "page_header"
            and support.get("predecessor_type") in {"header", "text"}
        )
    ):
        raise ReadinessContractError("bare top label lacks trusted-header ownership")
    if not in_top and not in_nominal_bottom:
        if support.get("source_method") != "printed_label_boundary":
            raise ReadinessContractError("effective label owner method differs")
        _validate_effective_extension_binding(
            support,
            method_proofs.get(support["id"]),
            label_candidates=(candidate,),
            page_width=page_width,
            page_height=page_height,
        )


def _validate_boundary_candidate(
    candidate: Mapping[str, Any],
    *,
    page_index: int,
    page_width: float,
    page_height: float,
    source_sha256: str,
    public_document: Mapping[str, Any] | None,
    label_candidates: Sequence[Mapping[str, Any]],
    method_proofs: Mapping[str, Mapping[str, Any]],
) -> None:
    if not isinstance(candidate, Mapping):
        raise ReadinessContractError("boundary candidate is not an object")
    _exact_keys(candidate, BOUNDARY_CANDIDATE_FIELDS, "report.boundary_candidate")
    for key in (
        "id",
        "public_item_id",
        "element_id",
        "predecessor_type",
        "bbox_id",
        "normalized_signature",
    ):
        _string(candidate[key], f"report.boundary_candidate.{key}")
    public_path = validate_public_path(
        candidate["public_path"], path="report.boundary_candidate.public_path"
    )
    if len(public_path) < 2 or public_path[1] != page_index - 1:
        raise ReadinessContractError("boundary candidate public page path differs")
    uses_effective_bottom = _candidate_uses_effective_bottom(
        candidate,
        page_width=page_width,
        page_height=page_height,
        path="report.boundary_candidate",
    )
    _references(
        candidate["evidence_ids"],
        "report.boundary_candidate.evidence_ids",
        allow_empty=False,
    )
    _references(
        candidate["source_object_ids"],
        "report.boundary_candidate.source_object_ids",
        allow_empty=False,
    )
    if candidate["raw_layout_role"] not in {None, "page_header", "page_footer"}:
        raise ReadinessContractError("boundary candidate layout role differs")
    if candidate["boundary_band"] not in {"top", "bottom"}:
        raise ReadinessContractError("boundary candidate band differs")
    if candidate["source_method"] not in SOURCE_METHODS:
        raise ReadinessContractError("boundary candidate method differs")
    expected_candidate_role(candidate)
    if uses_effective_bottom:
        _validate_effective_extension_binding(
            candidate,
            method_proofs.get(candidate["id"]),
            label_candidates=label_candidates,
            page_width=page_width,
            page_height=page_height,
        )
    if candidate["id"] != boundary_candidate_id(
        candidate,
        source_sha256=source_sha256,
        physical_page_index=page_index,
    ):
        raise ReadinessContractError("boundary candidate stable ID differs")
    if public_document is not None:
        owner = resolve_public_path(public_document, public_path)
        if (
            not isinstance(owner, Mapping)
            or owner.get("id") != candidate["public_item_id"]
        ):
            raise ReadinessContractError("boundary candidate public owner differs")
        validate_source_owner_admission(
            owner_kind=candidate["predecessor_type"],
            raw_layout_role=candidate["raw_layout_role"],
            source_method=candidate["source_method"],
            prior_semantic_owner=_has_prior_semantic_owner(owner),
        )
        _validate_repetition_signature_binding(
            candidate,
            owner,
            label_candidates=label_candidates,
        )
        sidecar_keys = set(owner) & PUBLIC_RUNNING_REGION_KEYS
        if sidecar_keys and sidecar_keys != PUBLIC_RUNNING_REGION_KEYS:
            raise ReadinessContractError("boundary candidate owner sidecar is partial")
        if candidate["source_method"] == "extracted_source_contribution":
            if sidecar_keys or owner.get("type") != candidate["predecessor_type"]:
                raise ReadinessContractError("extracted candidate owner type differs")
        elif sidecar_keys == PUBLIC_RUNNING_REGION_KEYS:
            descriptor = owner["running_region"]
            validate_running_region_sidecar(
                {key: owner[key] for key in RUNNING_REGION_SIDECAR_FIELDS},
                owning_item=owner,
                public_document=public_document,
                source_sha256=source_sha256,
            )
            scalar_bindings = (
                ("source_public_item_id", "public_item_id"),
                ("source_element_id", "element_id"),
                ("predecessor_type", "predecessor_type"),
                ("bbox_id", "bbox_id"),
                ("source_method", "source_method"),
            )
            if (
                any(
                    descriptor[descriptor_key] != candidate[candidate_key]
                    for descriptor_key, candidate_key in scalar_bindings
                )
                or tuple(descriptor["source_public_path"])
                != tuple(candidate["public_path"])
                or tuple(descriptor["evidence_ids"]) != tuple(candidate["evidence_ids"])
                or tuple(descriptor["source_object_ids"])
                != tuple(candidate["source_object_ids"])
                or _canonical_bbox(
                    descriptor["bbox"],
                    path="report.boundary_candidate.descriptor_bbox",
                )
                != _canonical_bbox(
                    candidate["bbox"],
                    path="report.boundary_candidate.candidate_bbox",
                )
            ):
                raise ReadinessContractError(
                    "projected direct candidate descriptor differs"
                )
        elif owner.get("type") != candidate["predecessor_type"] or _canonical_bbox(
            owner.get("bbox"), path="report.boundary_candidate.owner_bbox"
        ) != _canonical_bbox(
            candidate["bbox"], path="report.boundary_candidate.candidate_bbox"
        ):
            raise ReadinessContractError("direct candidate owner binding differs")
    validate_confidence(
        candidate["confidence"], path="report.boundary_candidate.confidence"
    )
    concerns = _known_concerns(
        candidate["concern_codes"],
        "report.boundary_candidate.concern_codes",
        maximum=MAX_CONCERNS_PER_PAGE,
    )
    accepted = (
        candidate["confidence"]
        == {
            "scope": "deterministic_rule",
            "score": 1.0,
            "unavailable_reason": None,
        }
        and not concerns
    )
    expected_disposition = "accepted" if accepted else "rejected"
    if candidate["disposition"] != expected_disposition:
        raise ReadinessContractError("boundary candidate disposition differs")


def validate_source_report(
    report: Mapping[str, Any],
    *,
    public_document: Mapping[str, Any] | None = None,
    method_proofs: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Validate the closed source report and exact aggregate ledgers."""

    if not isinstance(report, Mapping):
        raise ReadinessContractError("source report is not an object")
    _exact_keys(report, SOURCE_REPORT_FIELDS, "report")
    if report["report_version"] != REPORT_VERSION or report["policy_id"] != POLICY_ID:
        raise ReadinessContractError("source report identity differs")
    if not _is_hash(report["source_sha256"]):
        raise ReadinessContractError("source report hash differs")
    if report["status"] not in REPORT_STATUSES:
        raise ReadinessContractError("source report status differs")
    pages = report["pages"]
    if not isinstance(pages, (list, tuple)) or len(pages) > MAX_PAGES_PER_DOCUMENT:
        raise ReadinessContractError("source report pages differ")
    expected_indexes = list(range(1, len(pages) + 1))
    actual_indexes: list[int] = []
    totals = {
        "page_count": len(pages),
        "source_character_count": 0,
        "source_word_count": 0,
        "embedded_label_count": 0,
        "label_candidate_count": 0,
        "boundary_candidate_count": 0,
        "concern_count": 0,
    }
    proofs = {} if method_proofs is None else method_proofs
    if not isinstance(proofs, Mapping) or any(
        not isinstance(candidate_id, str) or not isinstance(proof, Mapping)
        for candidate_id, proof in proofs.items()
    ):
        raise ReadinessContractError("source report method proof ledger differs")
    all_candidate_ids: set[str] = set()
    for page in pages:
        if not isinstance(page, Mapping):
            raise ReadinessContractError("source report page is not an object")
        _exact_keys(page, SOURCE_PAGE_FIELDS, "report.page")
        page_index = _index(
            page["page_index"], "report.page.page_index", maximum=MAX_PAGES_PER_DOCUMENT
        )
        actual_indexes.append(page_index)
        if page["unit"] != "pt" or page["coordinate_system_id"] != COORDINATE_SYSTEM_ID:
            raise ReadinessContractError("source report page coordinates differ")
        dimensions = (page["page_width"], page["page_height"])
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in dimensions
        ):
            raise ReadinessContractError("source report page dimensions differ")
        width, height = (float(value) for value in dimensions)
        characters = _count(
            page["source_character_count"],
            "report.page.source_character_count",
            maximum=MAX_SOURCE_CHARACTERS_PER_PAGE,
        )
        words = _count(
            page["source_word_count"],
            "report.page.source_word_count",
            maximum=MAX_SOURCE_WORDS_PER_PAGE,
        )
        embedded = page["embedded_label"]
        if embedded is not None and normalize_embedded_label(embedded) != embedded:
            raise ReadinessContractError("source report embedded label differs")
        labels = page["label_candidates"]
        boundaries = page["boundary_candidates"]
        if (
            not isinstance(labels, (list, tuple))
            or len(labels) > MAX_LABEL_CANDIDATES_PER_PAGE
        ):
            raise ReadinessContractError("source report label candidates differ")
        if (
            not isinstance(boundaries, (list, tuple))
            or len(boundaries) > MAX_BOUNDARY_CANDIDATES_PER_PAGE
        ):
            raise ReadinessContractError("source report boundary candidates differ")
        page_ids: list[str] = []
        for candidate in labels:
            exact_public_binding = _label_has_exact_public_binding(
                public_document,
                page_index=page_index,
                candidate_id=candidate.get("id")
                if isinstance(candidate, Mapping)
                else "",
            )
            _validate_label_candidate(
                candidate,
                source_sha256=report["source_sha256"],
                page_index=page_index,
                page_width=width,
                page_height=height,
                boundary_candidates=boundaries,
                method_proofs=proofs,
                exact_public_binding=exact_public_binding,
                source_character_count=characters,
                source_word_count=words,
            )
            page_ids.append(candidate["id"])
            totals["concern_count"] += len(candidate["concern_codes"])
        for candidate in boundaries:
            _validate_boundary_candidate(
                candidate,
                page_index=page_index,
                page_width=width,
                page_height=height,
                source_sha256=report["source_sha256"],
                public_document=public_document,
                label_candidates=labels,
                method_proofs=proofs,
            )
            page_ids.append(candidate["id"])
            totals["concern_count"] += len(candidate["concern_codes"])
        if len(page_ids) != len(set(page_ids)) or all_candidate_ids.intersection(
            page_ids
        ):
            raise ReadinessContractError("source report candidate ID ownership differs")
        all_candidate_ids.update(page_ids)
        concerns = _known_concerns(
            page["concern_codes"],
            "report.page.concern_codes",
            maximum=MAX_CONCERNS_PER_PAGE,
        )
        if "running_region_source_limit" in concerns and (
            tuple(concerns) != ("running_region_source_limit",)
            or labels
            or boundaries
            or characters
            or words
        ):
            raise ReadinessContractError("refused source page payload differs")
        totals["source_character_count"] += characters
        totals["source_word_count"] += words
        totals["embedded_label_count"] += int(embedded is not None)
        totals["label_candidate_count"] += len(labels)
        totals["boundary_candidate_count"] += len(boundaries)
        totals["concern_count"] += len(concerns)
    if actual_indexes != expected_indexes:
        raise ReadinessContractError("source report page order differs")
    document_concerns = _known_concerns(
        report["concern_codes"],
        "report.concern_codes",
        maximum=MAX_CONCERNS_PER_DOCUMENT,
    )
    totals["concern_count"] += len(document_concerns)
    refusal_code = {
        "unavailable": "running_region_source_evidence_unavailable",
        "refused": "running_region_source_limit",
    }.get(report["status"])
    if refusal_code is not None:
        if pages or tuple(document_concerns) != (refusal_code,):
            raise ReadinessContractError("source report refusal payload differs")
    elif any(
        code
        in {
            "running_region_source_evidence_unavailable",
            "running_region_source_limit",
        }
        for code in document_concerns
    ):
        raise ReadinessContractError("available source report has document refusal")
    counts = report["counts"]
    if not isinstance(counts, Mapping):
        raise ReadinessContractError("source report counts are not an object")
    _exact_keys(counts, SOURCE_COUNT_FIELDS, "report.counts")
    for key, expected in totals.items():
        if _count(counts[key], f"report.counts.{key}") != expected:
            raise ReadinessContractError("source report aggregate counts differ")
    if (
        totals["source_character_count"] > MAX_SOURCE_CHARACTERS_PER_DOCUMENT
        or totals["source_word_count"] > MAX_SOURCE_WORDS_PER_DOCUMENT
        or totals["boundary_candidate_count"] > MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT
        or totals["concern_count"] > MAX_CONCERNS_PER_DOCUMENT
    ):
        raise ReadinessContractError("source report document cap exceeded")
    extraction_ms = _duration(report["extraction_ms"], "report.extraction_ms")
    if extraction_ms > SOURCE_EXTRACTION_DEADLINE_SECONDS * 1_000:
        raise ReadinessContractError("source extraction deadline exceeded")
    if len(strict_json_bytes(report)) > MAX_REPORT_BYTES:
        raise ReadinessContractError("source report byte cap exceeded")


def validate_processing_summary(summary: Mapping[str, Any]) -> None:
    """Validate the closed enabled-stage processing summary and count algebra."""

    if not isinstance(summary, Mapping):
        raise ReadinessContractError("processing summary is not an object")
    _exact_keys(summary, PROCESSING_SUMMARY_FIELDS, "processing.running_regions")
    if (
        summary["policy_id"] != POLICY_ID
        or summary["status"] not in PROCESSING_STATUSES
    ):
        raise ReadinessContractError("processing summary identity/status differs")
    status, reason = summary["status"], summary["reason"]
    expected_reasons = {
        "projected": {None},
        "unavailable": {
            "running_region_source_evidence_unavailable",
            "running_region_source_limit",
        },
        "not_applicable": {"running_region_input_not_applicable"},
        "failed_closed": {"running_region_projection_failed_closed"},
    }[status]
    if reason not in expected_reasons:
        raise ReadinessContractError("processing summary reason differs")
    count_keys = PROCESSING_SUMMARY_FIELDS[3:16]
    counts = {key: _count(summary[key], f"processing.{key}") for key in count_keys}
    if status == "projected":
        if counts["source_page_count"] != counts["identity_count"]:
            raise ReadinessContractError("processing identity coverage differs")
        if (
            counts["detected_label_count"]
            + counts["embedded_label_count"]
            + counts["legacy_fallback_count"]
            != counts["identity_count"]
        ):
            raise ReadinessContractError("processing display-source counts differ")
        if (
            counts["header_count"]
            + counts["footer_count"]
            + counts["top_navigation_count"]
            + counts["bottom_navigation_count"]
            != counts["running_region_count"]
        ):
            raise ReadinessContractError("processing role counts differ")
    elif any(counts[key] for key in count_keys if key != "concern_count"):
        raise ReadinessContractError("non-projecting summary has feature counts")
    elif counts["concern_count"] > 1:
        raise ReadinessContractError("non-projecting summary has excess concerns")
    if (
        counts["source_page_count"] > MAX_PAGES_PER_DOCUMENT
        or counts["candidate_count"] > MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT
        or counts["comparison_count"] > MAX_COMPARISONS_PER_DOCUMENT
        or counts["running_region_count"] > MAX_RUNNING_REGIONS_PER_DOCUMENT
        or counts["concern_count"] > MAX_CONCERNS_PER_DOCUMENT
    ):
        raise ReadinessContractError("processing count cap exceeded")
    extraction = _duration(summary["extraction_ms"], "processing.extraction_ms")
    projection = _duration(summary["projection_ms"], "processing.projection_ms")
    total = _duration(summary["total_ms"], "processing.total_ms")
    if total != round(extraction + projection, 3):
        raise ReadinessContractError("processing total timing differs")
    if extraction > SOURCE_EXTRACTION_DEADLINE_SECONDS * 1_000:
        raise ReadinessContractError("processing extraction deadline exceeded")
    if projection > PROJECTION_DOCUMENT_DEADLINE_SECONDS * 1_000:
        raise ReadinessContractError("processing projection deadline exceeded")


def validate_projected_concerns(
    concerns: Any,
    *,
    page_count: int,
    expected_count: int,
) -> tuple[Mapping[str, Any], ...]:
    """Validate the content-free projected concern ledger and its cardinality."""

    if not isinstance(concerns, list) or len(concerns) != expected_count:
        raise ReadinessContractError("projected concern cardinality differs")
    maximum_cap = max(
        value
        for value in RESOURCE_LIMITS.values()
        if isinstance(value, int) and not isinstance(value, bool)
    )
    normalized: list[Mapping[str, Any]] = []
    identities: list[tuple[str, str]] = []
    for concern in concerns:
        if not isinstance(concern, Mapping):
            raise ReadinessContractError("projected concern is not an object")
        _exact_keys(concern, PROJECTED_CONCERN_FIELDS, "running_region_concern")
        code = concern["code"]
        source_ref = concern["source_ref"]
        if code not in CONCERN_CODES or not isinstance(source_ref, str):
            raise ReadinessContractError("projected concern identity differs")
        if source_ref != "document":
            match = re.fullmatch(r"page:([1-9][0-9]*)", source_ref)
            if match is None or int(match.group(1)) > page_count:
                raise ReadinessContractError(
                    "projected concern source reference differs"
                )
        count = _count(
            concern["count"],
            "running_region_concern.count",
            maximum=maximum_cap,
        )
        cap = _count(
            concern["cap"],
            "running_region_concern.cap",
            maximum=maximum_cap,
        )
        if count < 1 or cap < 1 or count > cap:
            raise ReadinessContractError("projected concern count/cap differs")
        exception_class = concern["exception_class"]
        if exception_class is not None and (
            not isinstance(exception_class, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,127}", exception_class) is None
        ):
            raise ReadinessContractError("projected concern exception class differs")
        identities.append((source_ref, code))
        normalized.append(concern)
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise ReadinessContractError("projected concern order/identity differs")
    return tuple(normalized)


def validate_comparison_ledger(
    ledger: Sequence[Mapping[str, Any]],
    *,
    source_page_count: int,
    expected_comparison_count: int,
) -> None:
    """Validate exact per-page comparison charging without an all-pairs escape."""

    _count(
        source_page_count,
        "comparison_ledger.source_page_count",
        maximum=MAX_PAGES_PER_DOCUMENT,
    )
    expected = _count(
        expected_comparison_count,
        "comparison_ledger.expected_comparison_count",
        maximum=MAX_COMPARISONS_PER_DOCUMENT,
    )
    if not isinstance(ledger, (list, tuple)):
        raise ReadinessContractError("comparison ledger is not ordered")
    indexes: list[int] = []
    total = 0
    for entry in ledger:
        if not isinstance(entry, Mapping):
            raise ReadinessContractError("comparison ledger entry is not an object")
        _exact_keys(entry, COMPARISON_LEDGER_FIELDS, "comparison_ledger.entry")
        page_index = _index(
            entry["page_index"],
            "comparison_ledger.entry.page_index",
            maximum=source_page_count,
        )
        comparison_count = _count(
            entry["comparison_count"],
            "comparison_ledger.entry.comparison_count",
            maximum=MAX_COMPARISONS_PER_PAGE,
        )
        if comparison_count < 1:
            raise ReadinessContractError("comparison ledger retained a zero entry")
        indexes.append(page_index)
        total += comparison_count
    if indexes != sorted(indexes) or len(indexes) != len(set(indexes)):
        raise ReadinessContractError("comparison ledger page order differs")
    if total != expected or total > MAX_COMPARISONS_PER_DOCUMENT:
        raise ReadinessContractError("comparison ledger total differs")


def combine_terminal_processing_summaries(
    initial: Mapping[str, Any], terminal: Mapping[str, Any]
) -> dict[str, Any]:
    """Charge extraction once and both bounded projection passes."""

    validate_processing_summary(initial)
    validate_processing_summary(terminal)
    combined = deepcopy(dict(terminal))
    combined["extraction_ms"] = round(float(initial["extraction_ms"]), 3)
    combined["projection_ms"] = round(
        float(initial["projection_ms"]) + float(terminal["projection_ms"]), 3
    )
    combined["total_ms"] = round(
        combined["extraction_ms"] + combined["projection_ms"], 3
    )
    validate_processing_summary(combined)
    return combined


def validate_form_processing_summary(summary: Mapping[str, Any]) -> None:
    if not isinstance(summary, Mapping):
        raise ReadinessContractError("form processing summary is not an object")
    _exact_keys(summary, FORM_PROCESSING_SUMMARY_FIELDS, "processing.form_semantics")
    extraction = _duration(
        summary["extraction_ms"], "processing.form_semantics.extraction_ms"
    )
    projection = _duration(
        summary["projection_ms"], "processing.form_semantics.projection_ms"
    )
    total = _duration(summary["total_ms"], "processing.form_semantics.total_ms")
    if total != round(extraction + projection, 3):
        raise ReadinessContractError("form processing total differs")


def combine_terminal_form_processing_summaries(
    initial: Mapping[str, Any], terminal: Mapping[str, Any]
) -> dict[str, Any]:
    validate_form_processing_summary(initial)
    validate_form_processing_summary(terminal)
    combined = {
        "extraction_ms": round(float(initial["extraction_ms"]), 3),
        "projection_ms": round(
            float(initial["projection_ms"]) + float(terminal["projection_ms"]),
            3,
        ),
    }
    combined["total_ms"] = round(
        combined["extraction_ms"] + combined["projection_ms"], 3
    )
    validate_form_processing_summary(combined)
    return combined


def validate_outline_processing_summary(summary: Mapping[str, Any]) -> None:
    if not isinstance(summary, Mapping):
        raise ReadinessContractError("outline processing summary is not an object")
    _exact_keys(
        summary,
        OUTLINE_PROCESSING_SUMMARY_FIELDS,
        "processing.outline_structure",
    )
    if summary["policy_id"] != OUTLINE_POLICY_ID or summary["status"] not in {
        "projected",
        "no_candidates",
        "unavailable",
        "failed_closed",
    }:
        raise ReadinessContractError("outline processing identity differs")
    for field in (
        "group_count",
        "node_count",
        "relationship_count",
        "concern_count",
    ):
        _count(summary[field], f"processing.outline_structure.{field}")
    extraction = _duration(
        summary["extraction_ms"], "processing.outline_structure.extraction_ms"
    )
    projection = _duration(
        summary["projection_ms"], "processing.outline_structure.projection_ms"
    )
    total = _duration(summary["total_ms"], "processing.outline_structure.total_ms")
    if total != round(extraction + projection, 3):
        raise ReadinessContractError("outline processing total differs")
    if summary["status"] == "projected":
        if (
            summary["reason"] is not None
            or summary["group_count"] < 1
            or summary["node_count"] < summary["group_count"] * 2
            or summary["relationship_count"] < summary["node_count"]
        ):
            raise ReadinessContractError("outline projected summary differs")
    elif summary["status"] == "no_candidates":
        if (
            summary["reason"] is not None
            or summary["group_count"]
            or summary["node_count"]
            or summary["relationship_count"]
        ):
            raise ReadinessContractError("outline no-candidate summary differs")
    elif not isinstance(summary["reason"], str) or not summary["reason"]:
        raise ReadinessContractError("outline failure reason differs")


def combine_terminal_outline_processing_summaries(
    initial: Mapping[str, Any], terminal: Mapping[str, Any]
) -> dict[str, Any]:
    validate_outline_processing_summary(initial)
    validate_outline_processing_summary(terminal)
    non_timing = set(OUTLINE_PROCESSING_SUMMARY_FIELDS) - {
        "extraction_ms",
        "projection_ms",
        "total_ms",
    }
    if any(terminal[field] != initial[field] for field in non_timing):
        raise ReadinessContractError("terminal outline graph summary differs")
    combined = deepcopy(dict(terminal))
    combined["extraction_ms"] = round(float(initial["extraction_ms"]), 3)
    combined["projection_ms"] = round(
        float(initial["projection_ms"]) + float(terminal["projection_ms"]),
        3,
    )
    combined["total_ms"] = round(
        combined["extraction_ms"] + combined["projection_ms"], 3
    )
    validate_outline_processing_summary(combined)
    return combined


def _canonical_page_views_from_blocks(
    canonical_page: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Derive exact page views from ordered, non-omitted canonical blocks."""

    blocks = canonical_page.get("blocks")
    if not isinstance(blocks, list) or any(
        not isinstance(block, Mapping) for block in blocks
    ):
        raise ReadinessContractError("canonical page blocks differ")
    ordered_block_ids = [block.get("id") for block in blocks]
    included_blocks = [
        block for block in blocks if block.get("omission_reason") is None
    ]
    ordered_included_ids = [block["id"] for block in included_blocks]
    if any(
        not isinstance(value, str) or not value for value in ordered_block_ids
    ) or len(ordered_block_ids) != len(set(ordered_block_ids)):
        raise ReadinessContractError("canonical block IDs/order differs")
    expected_views: dict[str, list[str]] = {
        scope: [] for scope in ("body", "header", "footer")
    }
    for block in included_blocks:
        block_scope = block.get("scope")
        if block_scope not in expected_views:
            raise ReadinessContractError("canonical block scope differs")
        expected_views[block_scope].append(block["id"])
    blocks_by_id = {block["id"]: block for block in included_blocks}

    def render_view(ids: Sequence[str], field: str) -> str:
        if any(
            not isinstance(blocks_by_id[member_id].get(field), str) for member_id in ids
        ):
            raise ReadinessContractError("canonical block scalar differs")
        values = [
            blocks_by_id[member_id][field].strip()
            for member_id in ids
            if blocks_by_id[member_id][field].strip()
        ]
        return "\n\n".join(values).rstrip() + "\n" if values else ""

    return {
        view_name: {
            "block_ids": ids,
            "markdown": render_view(ids, "markdown"),
            "text": render_view(ids, "text"),
        }
        for view_name, ids in {
            "full": ordered_included_ids,
            **expected_views,
        }.items()
    }


def _validate_canonical_page_views(canonical_page: Mapping[str, Any]) -> None:
    expected = _canonical_page_views_from_blocks(canonical_page)
    for view_name, expected_view in expected.items():
        view = canonical_page.get(view_name)
        if (
            not isinstance(view, Mapping)
            or set(view) != {"block_ids", "markdown", "text"}
            or dict(view) != expected_view
        ):
            raise ReadinessContractError(f"canonical {view_name} view differs")


def validate_canonical_binding(
    region: Mapping[str, Any],
    canonical_block: Mapping[str, Any],
    canonical_page: Mapping[str, Any],
) -> None:
    """Prove one accepted region is excluded from body and included once in full."""

    validate_running_region(region)
    required_block = {
        "id",
        "page_id",
        "primary_element_id",
        "scope",
        "contributing_element_ids",
        "omission_reason",
    }
    if not isinstance(canonical_block, Mapping) or not required_block <= set(
        canonical_block
    ):
        raise ReadinessContractError("canonical block is incomplete")
    if (
        canonical_block["id"] != region["canonical_block_id"]
        or canonical_block["page_id"] != region["page_id"]
        or canonical_block["primary_element_id"] != region["source_element_id"]
        or canonical_block["scope"] != region["canonical_scope"]
        or canonical_block["omission_reason"] is not None
    ):
        raise ReadinessContractError("canonical block custody differs")
    contributors = canonical_block["contributing_element_ids"]
    if (
        not isinstance(contributors, list)
        or not contributors
        or contributors[0] != region["source_element_id"]
    ):
        raise ReadinessContractError("canonical primary contribution differs")
    if (
        canonical_page.get("page_id") != region["page_id"]
        or canonical_page.get("page_index") != region["physical_page_index"]
    ):
        raise ReadinessContractError("canonical page custody differs")
    _validate_canonical_page_views(canonical_page)
    block_id = region["canonical_block_id"]
    body_ids = canonical_page["body"]["block_ids"]
    full_ids = canonical_page["full"]["block_ids"]
    header_ids = canonical_page["header"]["block_ids"]
    footer_ids = canonical_page["footer"]["block_ids"]
    scope_ids = canonical_page[region["canonical_scope"]]["block_ids"]
    opposite_ids = footer_ids if region["canonical_scope"] == "header" else header_ids
    if (
        block_id in body_ids
        or block_id in opposite_ids
        or full_ids.count(block_id) != 1
        or scope_ids.count(block_id) != 1
    ):
        raise ReadinessContractError("canonical body/full/scope membership differs")


def _canonical_document_views_from_pages(
    canonical_pages: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Derive production document views from ordered canonical page views."""

    views: dict[str, dict[str, Any]] = {}
    for view_name in ("full", "body", "header", "footer"):
        block_ids: list[str] = []
        markdown_pages: list[str] = []
        text_pages: list[str] = []
        for page in canonical_pages:
            view = page.get(view_name)
            if (
                not isinstance(view, Mapping)
                or set(view) != {"block_ids", "markdown", "text"}
                or not isinstance(view.get("block_ids"), list)
                or any(
                    not isinstance(block_id, str) or not block_id
                    for block_id in view.get("block_ids", [])
                )
                or not isinstance(view.get("markdown"), str)
                or not isinstance(view.get("text"), str)
            ):
                raise ReadinessContractError(f"canonical page {view_name} view differs")
            block_ids.extend(view["block_ids"])
            markdown = view["markdown"].strip()
            text = view["text"].strip()
            if markdown:
                markdown_pages.append(markdown)
            if text:
                text_pages.append(text)

        def render(values: Sequence[str]) -> str:
            return "\n\n".join(values).rstrip() + "\n" if values else ""

        views[view_name] = {
            "block_ids": block_ids,
            "markdown": render(markdown_pages),
            "text": render(text_pages),
        }
    return views


def _validate_canonical_document_views(
    canonical: Mapping[str, Any], canonical_pages: Sequence[Mapping[str, Any]]
) -> None:
    """Validate optional top-level views against production page aggregation."""

    view_names = ("full", "body", "header", "footer")
    present = {name for name in view_names if name in canonical}
    if not present:
        return
    if present != set(view_names):
        raise ReadinessContractError("canonical document view coverage differs")
    expected = _canonical_document_views_from_pages(canonical_pages)
    for name in view_names:
        if canonical[name] != expected[name]:
            raise ReadinessContractError(f"canonical document {name} view differs")


def _utf8_whitespace_ranges(value: str) -> tuple[tuple[int, int], ...]:
    offsets = [0]
    for character in value:
        offsets.append(offsets[-1] + len(character.encode("utf-8")))
    return tuple(
        (offsets[match.start()], offsets[match.end()])
        for match in re.finditer(r"\s+", value)
        if match.start() > 0 and match.end() < len(value)
    )


def _whitespace_boundary_indexes(value: str) -> tuple[int, ...]:
    """Return each internal whitespace run's boundary in non-space codepoints."""

    return tuple(
        sum(not character.isspace() for character in value[: match.start()])
        for match in re.finditer(r"\s+", value)
        if match.start() > 0 and match.end() < len(value)
    )


@dataclass(frozen=True, slots=True)
class ExtractedContributionPlan:
    """Bounded multi-interval plan for the sole synthetic-content exception."""

    physical_page_index: int
    owner_public_item_id: str
    owner_sha256_before: str
    owner_sha256_after: str
    predecessor_canonical: str
    source_text: str
    presentation_text: str
    presentation_fragments: tuple[str, ...]
    delimiters: tuple[str, ...]
    predecessor_intervals: tuple[tuple[int, int], ...]
    residual_insertion_offsets: tuple[int, ...]
    source_span_groups: tuple[tuple[tuple[int, int], ...], ...]
    whitespace_mappings: tuple[tuple[int, int, int, int], ...]
    residual_canonical: str
    source_text_sha256: str
    presentation_text_sha256: str
    predecessor_sha256: str
    presentation_fragment_sha256: tuple[str, ...]
    removed_interval_sha256: tuple[str, ...]
    delimiter_sha256: tuple[str, ...]
    ordered_plan_sha256: str
    residual_sha256: str

    def execute(self) -> str:
        _index(
            self.physical_page_index,
            "extracted_plan.physical_page_index",
            maximum=MAX_PAGES_PER_DOCUMENT,
        )
        _string(self.owner_public_item_id, "extracted_plan.owner_public_item_id")
        if (
            not _is_hash(self.owner_sha256_before)
            or self.owner_sha256_after != self.owner_sha256_before
        ):
            raise ReadinessContractError("extracted owner hash differs")
        strings = (
            self.predecessor_canonical,
            self.source_text,
            self.presentation_text,
            self.residual_canonical,
        )
        try:
            predecessor, source_text, presentation_text, residual = (
                value.encode("utf-8") for value in strings
            )
        except UnicodeEncodeError as exc:
            raise ReadinessContractError(
                "extracted plan contains invalid Unicode"
            ) from exc
        if (
            not source_text
            or not presentation_text
            or self.source_text != self.source_text.strip()
            or len(source_text) > MAX_EXTRACTED_CONTRIBUTION_UTF8_BYTES
            or len(presentation_text) > MAX_EXTRACTED_CONTRIBUTION_UTF8_BYTES
            or unicodedata.normalize("NFC", self.source_text) != self.source_text
            or unicodedata.normalize("NFC", self.presentation_text)
            != self.presentation_text
        ):
            raise ReadinessContractError("extracted contribution text differs")
        interval_count = len(self.predecessor_intervals)
        parallel_lengths = (
            len(self.presentation_fragments),
            len(self.delimiters),
            len(self.residual_insertion_offsets),
            len(self.source_span_groups),
            len(self.presentation_fragment_sha256),
            len(self.removed_interval_sha256),
            len(self.delimiter_sha256),
        )
        if not 1 <= interval_count <= MAX_EXTRACTED_INTERVALS_PER_CONTRIBUTION or any(
            length != interval_count for length in parallel_lengths
        ):
            raise ReadinessContractError("extracted interval parallel arrays differ")

        def valid_ranges(
            ranges: Sequence[tuple[int, int]], maximum: int, path: str
        ) -> tuple[tuple[int, int], ...]:
            checked: list[tuple[int, int]] = []
            for value in ranges:
                if (
                    not isinstance(value, (list, tuple))
                    or len(value) != 2
                    or any(
                        isinstance(part, bool) or not isinstance(part, int)
                        for part in value
                    )
                ):
                    raise ReadinessContractError(f"{path} range type differs")
                start, end = value
                if not 0 <= start < end <= maximum:
                    raise ReadinessContractError(f"{path} range is out of bounds")
                checked.append((start, end))
            if checked != sorted(checked) or any(
                left[1] > right[0] for left, right in pairwise(checked)
            ):
                raise ReadinessContractError(f"{path} ranges overlap/reorder")
            return tuple(checked)

        intervals = valid_ranges(
            self.predecessor_intervals, len(predecessor), "extracted predecessor"
        )
        if any(left[1] >= right[0] for left, right in pairwise(intervals)):
            raise ReadinessContractError(
                "extracted predecessor intervals overlap/touch"
            )
        flattened_source_spans = tuple(
            span for group in self.source_span_groups for span in group
        )
        if any(not group for group in self.source_span_groups):
            raise ReadinessContractError("extracted source span group is empty")
        source_spans = valid_ranges(
            flattened_source_spans, len(source_text), "extracted source"
        )
        if source_spans != flattened_source_spans:
            raise ReadinessContractError(
                "extracted source spans are not in native order"
            )
        for delimiter in self.delimiters:
            if delimiter != "\n":
                raise ReadinessContractError("extracted delimiter differs")
        expected_presentation = "".join(
            fragment + (self.delimiters[index] if index + 1 < interval_count else "")
            for index, fragment in enumerate(self.presentation_fragments)
        )
        if (
            self.presentation_text != expected_presentation
            or self.presentation_text != self.presentation_text.strip()
        ):
            raise ReadinessContractError("extracted presentation fragment join differs")
        removed: list[bytes] = []
        for index, ((start, end), fragment, delimiter, group) in enumerate(
            zip(
                intervals,
                self.presentation_fragments,
                self.delimiters,
                self.source_span_groups,
            )
        ):
            fragment_bytes = fragment.encode("utf-8")
            delimiter_bytes = delimiter.encode("utf-8")
            current = predecessor[start:end]
            if (
                current != fragment_bytes + delimiter_bytes
                or predecessor.count(current) != 1
            ):
                raise ReadinessContractError(
                    "extracted predecessor fragment is ambiguous"
                )
            try:
                source_fragment = "".join(
                    source_text[a:b].decode("utf-8") for a, b in group
                )
            except UnicodeDecodeError as exc:
                raise ReadinessContractError(
                    "extracted source span is not UTF-8 aligned"
                ) from exc
            source_non_whitespace = "".join(
                character for character in source_fragment if not character.isspace()
            )
            fragment_non_whitespace = "".join(
                character for character in fragment if not character.isspace()
            )
            if source_non_whitespace != fragment_non_whitespace:
                raise ReadinessContractError("extracted source-span mapping differs")
            if (
                hashlib.sha256(fragment_bytes).hexdigest()
                != self.presentation_fragment_sha256[index]
            ):
                raise ReadinessContractError("extracted fragment hash differs")
            if (
                hashlib.sha256(current).hexdigest()
                != self.removed_interval_sha256[index]
            ):
                raise ReadinessContractError("extracted removed-interval hash differs")
            if (
                hashlib.sha256(delimiter_bytes).hexdigest()
                != self.delimiter_sha256[index]
            ):
                raise ReadinessContractError("extracted delimiter hash differs")
            removed.append(current)
        mapped_source = b"".join(source_text[start:end] for start, end in source_spans)
        try:
            mapped_source_text = mapped_source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReadinessContractError(
                "extracted source coverage is not UTF-8 aligned"
            ) from exc
        if "".join(
            character for character in mapped_source_text if not character.isspace()
        ) != "".join(
            character for character in self.source_text if not character.isspace()
        ):
            raise ReadinessContractError(
                "extracted source spans do not cover native text"
            )
        if "".join(
            character for character in self.source_text if not character.isspace()
        ) != "".join(
            character for character in self.presentation_text if not character.isspace()
        ):
            raise ReadinessContractError("extracted non-whitespace sequence differs")
        source_whitespace = _utf8_whitespace_ranges(self.source_text)
        presentation_whitespace = _utf8_whitespace_ranges(self.presentation_text)
        expected_whitespace = tuple(
            (*source_range, *presentation_range)
            for source_range, presentation_range in zip(
                source_whitespace,
                presentation_whitespace,
            )
        )
        if (
            len(source_whitespace) != len(presentation_whitespace)
            or _whitespace_boundary_indexes(self.source_text)
            != _whitespace_boundary_indexes(self.presentation_text)
            or self.whitespace_mappings != expected_whitespace
        ):
            raise ReadinessContractError("extracted whitespace mapping differs")
        residual_parts: list[bytes] = []
        insertion_offsets: list[int] = []
        predecessor_cursor = 0
        residual_size = 0
        for start, end in intervals:
            retained = predecessor[predecessor_cursor:start]
            residual_parts.append(retained)
            residual_size += len(retained)
            insertion_offsets.append(residual_size)
            predecessor_cursor = end
        residual_parts.append(predecessor[predecessor_cursor:])
        expected_residual = b"".join(residual_parts)
        if tuple(insertion_offsets) != self.residual_insertion_offsets:
            raise ReadinessContractError("extracted residual insertion offsets differ")
        if residual != expected_residual or not residual:
            raise ReadinessContractError("extracted residual differs")
        reconstructed_parts: list[bytes] = []
        residual_cursor = 0
        for offset, removed_bytes in zip(insertion_offsets, removed):
            reconstructed_parts.extend(
                (residual[residual_cursor:offset], removed_bytes)
            )
            residual_cursor = offset
        reconstructed_parts.append(residual[residual_cursor:])
        if b"".join(reconstructed_parts) != predecessor:
            raise ReadinessContractError("extracted inverse reconstruction differs")
        expected_hashes = (
            hashlib.sha256(source_text).hexdigest(),
            hashlib.sha256(presentation_text).hexdigest(),
            hashlib.sha256(predecessor).hexdigest(),
            hashlib.sha256(residual).hexdigest(),
        )
        actual_hashes = (
            self.source_text_sha256,
            self.presentation_text_sha256,
            self.predecessor_sha256,
            self.residual_sha256,
        )
        if expected_hashes != actual_hashes:
            raise ReadinessContractError("extracted scalar hash differs")
        ordered_payload = {
            "presentation_fragments": self.presentation_fragments,
            "delimiters": self.delimiters,
            "predecessor_intervals": intervals,
            "residual_insertion_offsets": tuple(insertion_offsets),
            "source_span_groups": self.source_span_groups,
            "whitespace_mappings": self.whitespace_mappings,
        }
        if sha256_json(ordered_payload) != self.ordered_plan_sha256:
            raise ReadinessContractError("extracted ordered-plan hash differs")
        if (
            len(extracted_plan_json_bytes(self))
            > MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_PAGE
        ):
            raise ReadinessContractError("extracted residual plan exceeds its page cap")
        return self.residual_canonical


def extracted_plan_json_bytes(plan: ExtractedContributionPlan) -> bytes:
    """Serialize every private plan field with the normative JSON byte rule."""

    return strict_json_bytes(
        {
            name: getattr(plan, name)
            for name in ExtractedContributionPlan.__dataclass_fields__
        }
    )


def validate_extracted_plan_ledger(
    plans: Sequence[ExtractedContributionPlan],
) -> None:
    """Validate page/document contribution counts and residual-plan byte ledgers."""

    if len(plans) > MAX_EXTRACTED_CONTRIBUTIONS_PER_DOCUMENT:
        raise ReadinessContractError("document extracted-contribution count exceeded")
    page_counts: dict[int, int] = {}
    page_bytes: dict[int, int] = {}
    document_bytes = 0
    seen_plan_payloads: set[bytes] = set()
    owner_predecessors: dict[tuple[int, str], tuple[str, str, str]] = {}
    owner_intervals: dict[tuple[int, str, str], list[tuple[int, int]]] = {}
    for plan in plans:
        if not isinstance(plan, ExtractedContributionPlan):
            raise ReadinessContractError("extracted plan ledger member differs")
        plan.execute()
        serialized = extracted_plan_json_bytes(plan)
        if serialized in seen_plan_payloads:
            raise ReadinessContractError("duplicate extracted contribution plan")
        seen_plan_payloads.add(serialized)
        page = plan.physical_page_index
        owner_key = (page, plan.owner_public_item_id)
        predecessor_identity = (
            plan.predecessor_sha256,
            plan.owner_sha256_before,
            plan.predecessor_canonical,
        )
        if owner_key in owner_predecessors and (
            owner_predecessors[owner_key] != predecessor_identity
        ):
            raise ReadinessContractError("extracted owner predecessor plan differs")
        owner_predecessors[owner_key] = predecessor_identity
        interval_key = (page, plan.owner_public_item_id, plan.predecessor_sha256)
        owner_intervals.setdefault(interval_key, []).extend(plan.predecessor_intervals)
        page_counts[page] = page_counts.get(page, 0) + 1
        size = len(serialized)
        page_bytes[page] = page_bytes.get(page, 0) + size
        document_bytes += size
    if any(
        value > MAX_EXTRACTED_CONTRIBUTIONS_PER_PAGE for value in page_counts.values()
    ):
        raise ReadinessContractError("page extracted-contribution count exceeded")
    if any(
        value > MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_PAGE
        for value in page_bytes.values()
    ):
        raise ReadinessContractError("page extracted residual-plan bytes exceeded")
    if document_bytes > MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_DOCUMENT:
        raise ReadinessContractError("document extracted residual-plan bytes exceeded")
    for intervals in owner_intervals.values():
        ordered = sorted(intervals)
        if len(ordered) != len(set(ordered)) or any(
            left[1] >= right[0] for left, right in pairwise(ordered)
        ):
            raise ReadinessContractError(
                "extracted contribution plans overlap/touch one owner"
            )


def build_extracted_contribution_plan(
    *,
    physical_page_index: int,
    owner_public_item_id: str,
    owner_sha256: str,
    predecessor_canonical: str,
    source_text: str,
    presentation_fragments: Sequence[str],
    delimiters: Sequence[str],
    predecessor_intervals: Sequence[tuple[int, int]],
    source_span_groups: Sequence[Sequence[tuple[int, int]]],
) -> ExtractedContributionPlan:
    """Build a fully hashed detached plan from exact ranges, then validate it."""

    predecessor = predecessor_canonical.encode("utf-8")
    intervals = tuple(tuple(value) for value in predecessor_intervals)
    fragments = tuple(presentation_fragments)
    delimiter_tuple = tuple(delimiters)
    groups = tuple(tuple(tuple(span) for span in group) for group in source_span_groups)
    presentation_text = "".join(
        fragment + (delimiter_tuple[index] if index + 1 < len(fragments) else "")
        for index, fragment in enumerate(fragments)
    )
    residual_parts: list[bytes] = []
    insertion_offsets: list[int] = []
    cursor = 0
    residual_size = 0
    removed: list[bytes] = []
    for start, end in intervals:
        retained = predecessor[cursor:start]
        residual_parts.append(retained)
        residual_size += len(retained)
        insertion_offsets.append(residual_size)
        removed.append(predecessor[start:end])
        cursor = end
    residual_parts.append(predecessor[cursor:])
    residual = b"".join(residual_parts)
    source_ranges = _utf8_whitespace_ranges(source_text)
    presentation_ranges = _utf8_whitespace_ranges(presentation_text)
    whitespace_mappings = tuple(
        (*source_range, *presentation_range)
        for source_range, presentation_range in zip(source_ranges, presentation_ranges)
    )
    ordered_payload = {
        "presentation_fragments": fragments,
        "delimiters": delimiter_tuple,
        "predecessor_intervals": intervals,
        "residual_insertion_offsets": tuple(insertion_offsets),
        "source_span_groups": groups,
        "whitespace_mappings": whitespace_mappings,
    }
    plan = ExtractedContributionPlan(
        physical_page_index=physical_page_index,
        owner_public_item_id=owner_public_item_id,
        owner_sha256_before=owner_sha256,
        owner_sha256_after=owner_sha256,
        predecessor_canonical=predecessor_canonical,
        source_text=source_text,
        presentation_text=presentation_text,
        presentation_fragments=fragments,
        delimiters=delimiter_tuple,
        predecessor_intervals=intervals,
        residual_insertion_offsets=tuple(insertion_offsets),
        source_span_groups=groups,
        whitespace_mappings=whitespace_mappings,
        residual_canonical=residual.decode("utf-8"),
        source_text_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        presentation_text_sha256=hashlib.sha256(
            presentation_text.encode("utf-8")
        ).hexdigest(),
        predecessor_sha256=hashlib.sha256(predecessor).hexdigest(),
        presentation_fragment_sha256=tuple(
            hashlib.sha256(value.encode("utf-8")).hexdigest() for value in fragments
        ),
        removed_interval_sha256=tuple(
            hashlib.sha256(value).hexdigest() for value in removed
        ),
        delimiter_sha256=tuple(
            hashlib.sha256(value.encode("utf-8")).hexdigest()
            for value in delimiter_tuple
        ),
        ordered_plan_sha256=sha256_json(ordered_payload),
        residual_sha256=hashlib.sha256(residual).hexdigest(),
    )
    plan.execute()
    return plan


def validate_extracted_contribution(
    region: Mapping[str, Any],
    *,
    synthetic_item: Mapping[str, Any],
    fused_owner: Mapping[str, Any],
    synthetic_block: Mapping[str, Any],
    residual_owner_block: Mapping[str, Any],
    canonical_page: Mapping[str, Any],
    predecessor_owner_block: Mapping[str, Any],
    predecessor_canonical_page: Mapping[str, Any],
    plan: ExtractedContributionPlan,
) -> None:
    """Validate synthetic item, unchanged owner, residual, and canonical custody."""

    if region.get("source_method") != "extracted_source_contribution":
        raise ReadinessContractError("descriptor is not an extracted contribution")
    validate_running_region(region, owning_item=synthetic_item)
    if (
        plan.physical_page_index != region["physical_page_index"]
        or fused_owner.get("id") != region["source_public_item_id"]
        or fused_owner.get("type") != region["predecessor_type"]
        or sha256_json(_compact_public_item(fused_owner))
        != region["predecessor_item_sha256"]
        or plan.owner_public_item_id != region["source_public_item_id"]
        or plan.owner_sha256_before != region["predecessor_item_sha256"]
    ):
        raise ReadinessContractError("extracted fused-owner custody differs")
    residual = plan.execute()
    if plan.owner_sha256_after != sha256_json(_compact_public_item(fused_owner)):
        raise ReadinessContractError("extracted public owner changed")
    if not isinstance(predecessor_owner_block, Mapping) or not isinstance(
        predecessor_canonical_page, Mapping
    ):
        raise ReadinessContractError("canonical predecessor owner differs")
    owner_source_value = fused_owner.get("value")
    owner_source_markdown = fused_owner.get("md")
    if (
        owner_source_value != plan.predecessor_canonical
        or owner_source_markdown != plan.predecessor_canonical
    ):
        raise ReadinessContractError("extracted predecessor scalar custody differs")
    if (
        canonical_page.get("page_id") != region["page_id"]
        or canonical_page.get("page_index") != region["physical_page_index"]
        or predecessor_canonical_page.get("page_id") != region["page_id"]
        or predecessor_canonical_page.get("page_index") != region["physical_page_index"]
    ):
        raise ReadinessContractError("extracted canonical owner page differs")
    owner_block_id = predecessor_owner_block.get("id")
    if (
        not isinstance(owner_block_id, str)
        or not owner_block_id
        or residual_owner_block.get("id") != owner_block_id
        or predecessor_owner_block.get("page_id") != region["page_id"]
        or residual_owner_block.get("page_id") != region["page_id"]
        or predecessor_owner_block.get("primary_element_id")
        != residual_owner_block.get("primary_element_id")
        or predecessor_owner_block.get("primary_element_id")
        == region["source_element_id"]
    ):
        raise ReadinessContractError("extracted canonical owner identity differs")
    predecessor_matches = [
        block
        for block in predecessor_canonical_page.get("blocks", [])
        if isinstance(block, Mapping) and block.get("id") == owner_block_id
    ]
    residual_matches = [
        block
        for block in canonical_page.get("blocks", [])
        if isinstance(block, Mapping) and block.get("id") == owner_block_id
    ]
    if (
        len(predecessor_matches) != 1
        or predecessor_matches[0] != predecessor_owner_block
        or len(residual_matches) != 1
        or residual_matches[0] != residual_owner_block
        or set(predecessor_owner_block) != set(residual_owner_block)
    ):
        raise ReadinessContractError("extracted canonical owner block differs")
    for key in predecessor_owner_block:
        if key not in {"markdown", "text"} and (
            predecessor_owner_block[key] != residual_owner_block[key]
        ):
            raise ReadinessContractError("extracted residual owner metadata changed")
    if (
        predecessor_owner_block.get("text") != plan.predecessor_canonical
        or predecessor_owner_block.get("markdown") != plan.predecessor_canonical
        or residual_owner_block.get("text") != residual
        or residual_owner_block.get("markdown") != residual
    ):
        raise ReadinessContractError("canonical predecessor/residual scalar differs")

    def view_ids(page: Mapping[str, Any], name: str) -> list[str]:
        view = page.get(name)
        if not isinstance(view, Mapping) or not isinstance(view.get("block_ids"), list):
            raise ReadinessContractError("extracted canonical owner view differs")
        return list(view["block_ids"])

    for page in (predecessor_canonical_page, canonical_page):
        if (
            view_ids(page, "body").count(owner_block_id) != 1
            or view_ids(page, "full").count(owner_block_id) != 1
            or owner_block_id in view_ids(page, "header")
            or owner_block_id in view_ids(page, "footer")
        ):
            raise ReadinessContractError("extracted residual owner membership differs")
    validate_canonical_binding(region, synthetic_block, canonical_page)
    if (
        synthetic_item.get("value") != plan.source_text
        or synthetic_item.get("md") != plan.source_text
    ):
        raise ReadinessContractError("synthetic public source contribution differs")
    if (
        synthetic_block.get("text") != plan.presentation_text
        or synthetic_block.get("markdown") != plan.presentation_text
    ):
        raise ReadinessContractError("synthetic canonical contribution differs")


def validate_extracted_candidate_eligibility(
    *,
    contribution_text: str,
    native_source: bool,
    evidence_mode: Literal["trusted_layout_role", "exact_repetition"],
    repetition_page_indexes: Sequence[int],
    complete_delimiter_line: bool,
    scalar_match_count: int,
    intervals_disjoint: bool,
    owner_kind: str,
    owner_sha256_before: str,
    owner_sha256_after: str,
) -> None:
    """Execute the bounded extracted-contribution admission predicates."""

    text = _string(
        contribution_text,
        "extracted_candidate.contribution_text",
        maximum_bytes=MAX_EXTRACTED_CONTRIBUTION_UTF8_BYTES,
    )
    if not text or text != text.strip() or native_source is not True:
        raise ReadinessContractError("extracted contribution is not native/nonempty")
    if evidence_mode not in {"trusted_layout_role", "exact_repetition"}:
        raise ReadinessContractError("extracted evidence mode differs")
    pages = tuple(repetition_page_indexes)
    valid_pages = (
        len(pages) <= MAX_REPETITION_MEMBERS
        and tuple(sorted(set(pages))) == pages
        and all(
            not isinstance(value, bool) and isinstance(value, int) and value >= 1
            for value in pages
        )
    )
    if (
        not valid_pages
        or (evidence_mode == "exact_repetition" and len(pages) < 2)
        or (evidence_mode == "trusted_layout_role" and pages)
    ):
        raise ReadinessContractError("extracted evidence-mode membership differs")
    if (
        complete_delimiter_line is not True
        or isinstance(scalar_match_count, bool)
        or not isinstance(scalar_match_count, int)
        or scalar_match_count != 1
    ):
        raise ReadinessContractError("extracted contribution line mapping is ambiguous")
    if intervals_disjoint is not True:
        raise ReadinessContractError("extracted contribution intervals overlap")
    if owner_kind.casefold() in {
        "table",
        "table_value",
        "table_cell",
        "cell",
        "cell_value",
        "form",
        "form_value",
        "outline",
        "outline_item",
        "outline_value",
        "label",
        "label_value",
        "page_label",
        "note",
        "note_value",
        "source_note",
        "source_note_value",
        "footnote",
    }:
        raise ReadinessContractError("extracted contribution owner is ineligible")
    if not _is_hash(owner_sha256_before) or owner_sha256_after != owner_sha256_before:
        raise ReadinessContractError("extracted contribution owner changed")


def _validate_non_projecting_document(
    document: Mapping[str, Any],
    *,
    processing: Mapping[str, Any],
    summary: Mapping[str, Any],
    public_pages: Sequence[Any],
    canonical_pages: Sequence[Any],
) -> None:
    """Refuse every recognizable US08 remnant outside a committed projection."""

    def contains_sidecar(value: Any) -> bool:
        if isinstance(value, Mapping):
            keys = set(value)
            if PUBLIC_PAGE_IDENTITY_KEY in keys or keys & PUBLIC_RUNNING_REGION_KEYS:
                return True
            return any(contains_sidecar(member) for member in value.values())
        if isinstance(value, (list, tuple)):
            return any(contains_sidecar(member) for member in value)
        return False

    if any(contains_sidecar(page) for page in (*public_pages, *canonical_pages)):
        raise ReadinessContractError("non-projecting output has a US08 sidecar")

    def looks_us08_named(key: Any) -> bool:
        return isinstance(key, str) and key.startswith(
            ("running_region", "layout_running_region", "page_identity")
        )

    if any(key != "running_regions" and looks_us08_named(key) for key in processing):
        raise ReadinessContractError("non-projecting output has extra US08 processing")
    if any(
        key != "running_region_concerns" and looks_us08_named(key) for key in document
    ):
        raise ReadinessContractError("non-projecting output has an extra US08 field")

    status = summary["status"]
    allowed_concerns = {
        "unavailable": {summary["reason"]},
        "not_applicable": set(),
        "failed_closed": {
            "running_region_canonical_custody_invalid",
            "running_region_projection_failed_closed",
        },
    }[status]
    if "running_region_concerns" not in document:
        concern_count = 0
    else:
        raw_concerns = document["running_region_concerns"]
        if not isinstance(raw_concerns, list) or len(raw_concerns) != 1:
            raise ReadinessContractError(
                "non-projecting output concern cardinality differs"
            )
        concern = raw_concerns[0]
        if not isinstance(concern, Mapping):
            raise ReadinessContractError("non-projecting concern is not an object")
        _exact_keys(concern, ("code",), "running_region_concern")
        if concern["code"] not in allowed_concerns:
            raise ReadinessContractError("non-projecting concern code differs")
        concern_count = 1
    if summary["concern_count"] != concern_count:
        raise ReadinessContractError("non-projecting concern count differs")


def validate_projected_document(document: Mapping[str, Any]) -> None:
    """Validate projected page/canonical coverage, item sidecars, and counts."""

    processing = document.get("processing")
    if not isinstance(processing, Mapping) or not isinstance(
        processing.get("running_regions"), Mapping
    ):
        raise ReadinessContractError("processing.running_regions is absent")
    summary = processing["running_regions"]
    validate_processing_summary(summary)
    public_pages = document.get("pages")
    canonical = document.get("canonical_presentation")
    canonical_pages = canonical.get("pages") if isinstance(canonical, Mapping) else None
    if not isinstance(public_pages, list) or not isinstance(canonical_pages, list):
        raise ReadinessContractError("public/canonical pages are unavailable")
    if summary["status"] != "projected":
        _validate_non_projecting_document(
            document,
            processing=processing,
            summary=summary,
            public_pages=public_pages,
            canonical_pages=canonical_pages,
        )
        return
    raw_projected_concerns = document.get("running_region_concerns", [])
    validate_projected_concerns(
        raw_projected_concerns,
        page_count=len(public_pages),
        expected_count=summary["concern_count"],
    )
    if len(public_pages) != summary["identity_count"] or len(canonical_pages) != len(
        public_pages
    ):
        raise ReadinessContractError("projected page coverage differs")
    if any(not isinstance(page, Mapping) for page in canonical_pages):
        raise ReadinessContractError("canonical page is not an object")
    public_page_bindings = [
        (page.get("page_index"), page.get("page_identity", {}).get("page_id"))
        if isinstance(page, Mapping) and isinstance(page.get("page_identity"), Mapping)
        else (None, None)
        for page in public_pages
    ]
    canonical_page_bindings = [
        (page.get("page_index"), page.get("page_id")) for page in canonical_pages
    ]
    if (
        canonical_page_bindings != public_page_bindings
        or len({page_id for _, page_id in canonical_page_bindings})
        != len(canonical_page_bindings)
        or len({page_index for page_index, _ in canonical_page_bindings})
        != len(canonical_page_bindings)
    ):
        raise ReadinessContractError("canonical physical page order/identity differs")
    canonical_block_ids: list[str] = []
    for canonical_page in canonical_pages:
        _validate_canonical_page_views(canonical_page)
        canonical_block_ids.extend(block["id"] for block in canonical_page["blocks"])
    if len(canonical_block_ids) != len(set(canonical_block_ids)):
        raise ReadinessContractError("canonical document block IDs differ")
    _validate_canonical_document_views(canonical, canonical_pages)
    canonical_by_index = {page["page_index"]: page for page in canonical_pages}
    region_count = 0
    role_counts = {role: 0 for role in RUNNING_REGION_ROLES}
    display_counts = {source: 0 for source in DISPLAY_SOURCES}
    seen_region_ids: set[str] = set()
    seen_elements: set[str] = set()
    repetition_groups: set[str] = set()
    extracted_document_count = 0
    source_document = document.get("document")
    source_sha256 = (
        source_document.get("sha256") if isinstance(source_document, Mapping) else None
    )
    if source_sha256 is not None and not _is_hash(source_sha256):
        raise ReadinessContractError("document source hash differs")
    for expected_index, page in enumerate(public_pages, start=1):
        if not isinstance(page, Mapping) or page.get("page_index") != expected_index:
            raise ReadinessContractError("public physical page order differs")
        canonical_page = canonical_by_index.get(expected_index)
        if not isinstance(canonical_page, Mapping):
            raise ReadinessContractError("matching canonical page is absent")
        identity = page.get("page_identity")
        if not isinstance(identity, Mapping):
            raise ReadinessContractError("projected page identity is absent")
        validate_page_identity(
            identity, public_page=page, canonical_page=canonical_page
        )
        if identity["detected_printed_label"] is not None:
            evidence_source = identity["evidence_source"]
            if evidence_source["public_path"]:
                _exact_public_item_path(
                    evidence_source["public_path"],
                    physical_page_index=expected_index,
                )
                owner = resolve_public_path(document, evidence_source["public_path"])
                if (
                    not isinstance(owner, Mapping)
                    or owner.get("id") != evidence_source["public_item_id"]
                    or _canonical_bbox(
                        owner.get("bbox"), path="page_identity.public_owner_bbox"
                    )
                    != _canonical_bbox(
                        identity["evidence_bbox"],
                        path="page_identity.evidence_bbox",
                    )
                ):
                    raise ReadinessContractError(
                        "detected page-label public binding differs"
                    )
                _exact_public_visible_text(owner, identity["visible_text"])
        display_counts[identity["display_source"]] += 1
        items = page.get("items", [])
        if not isinstance(items, list):
            raise ReadinessContractError("public page items are not ordered")
        page_region_count = 0
        page_extracted_count = 0
        extracted_suffix_started = False
        for item in items:
            if not isinstance(item, Mapping):
                if extracted_suffix_started:
                    raise ReadinessContractError(
                        "extracted synthetic suffix is not contiguous"
                    )
                continue
            keys = set(item) & PUBLIC_RUNNING_REGION_KEYS
            if not keys:
                if extracted_suffix_started:
                    raise ReadinessContractError(
                        "extracted synthetic suffix is not contiguous"
                    )
                continue
            if keys != PUBLIC_RUNNING_REGION_KEYS:
                raise ReadinessContractError("partial running-region sidecar")
            sidecar = {key: item[key] for key in RUNNING_REGION_SIDECAR_FIELDS}
            validate_running_region_sidecar(
                sidecar,
                owning_item=item,
                public_document=document,
                source_sha256=source_sha256,
            )
            region = sidecar["running_region"]
            is_extracted = region["source_method"] == "extracted_source_contribution"
            if is_extracted:
                extracted_suffix_started = True
                page_extracted_count += 1
                extracted_document_count += 1
            elif extracted_suffix_started:
                raise ReadinessContractError(
                    "direct item follows extracted synthetic suffix"
                )
            if (
                region["id"] in seen_region_ids
                or region["source_element_id"] in seen_elements
            ):
                raise ReadinessContractError("duplicate running-region ownership")
            seen_region_ids.add(region["id"])
            seen_elements.add(region["source_element_id"])
            blocks = canonical_page.get("blocks")
            matches = (
                [
                    block
                    for block in blocks
                    if isinstance(block, Mapping)
                    and block.get("id") == region["canonical_block_id"]
                ]
                if isinstance(blocks, list)
                else []
            )
            if len(matches) != 1:
                raise ReadinessContractError("running-region canonical block differs")
            validate_canonical_binding(region, matches[0], canonical_page)
            region_count += 1
            page_region_count += 1
            role_counts[region["role"]] += 1
            if region["repetition_group_id"] is not None:
                repetition_groups.add(region["repetition_group_id"])
        if page_region_count > MAX_RUNNING_REGIONS_PER_PAGE:
            raise ReadinessContractError("page running-region cap exceeded")
        if page_extracted_count > MAX_EXTRACTED_CONTRIBUTIONS_PER_PAGE:
            raise ReadinessContractError("page extracted-contribution cap exceeded")
    if region_count != summary["running_region_count"]:
        raise ReadinessContractError("running-region processing count differs")
    if extracted_document_count > MAX_EXTRACTED_CONTRIBUTIONS_PER_DOCUMENT:
        raise ReadinessContractError("document extracted-contribution cap exceeded")
    if len(repetition_groups) > MAX_REPETITION_GROUPS_PER_DOCUMENT:
        raise ReadinessContractError("document repetition-group cap exceeded")
    if (
        display_counts["detected_printed_label"] != summary["detected_label_count"]
        or display_counts["embedded_label"] != summary["embedded_label_count"]
        or display_counts["legacy_display_fallback"] + display_counts["physical"]
        != summary["legacy_fallback_count"]
        or role_counts["header"] != summary["header_count"]
        or role_counts["footer"] != summary["footer_count"]
        or role_counts["navigation_top"] != summary["top_navigation_count"]
        or role_counts["navigation_bottom"] != summary["bottom_navigation_count"]
    ):
        raise ReadinessContractError("projected processing source/role counts differ")


def validate_ir_bindings(
    ir_document: Mapping[str, Any],
    *,
    public_document: Mapping[str, Any],
) -> None:
    """Validate exact serialized PageRecord/ElementRecord US08 bindings.

    The validator intentionally consumes dictionaries rather than production
    model classes so readiness remains implementation-neutral while still
    proving page, element, bbox, evidence, public, and canonical custody.
    """

    validate_projected_document(public_document)
    if not isinstance(ir_document, Mapping):
        raise ReadinessContractError("serialized IR is not an object")
    collections: dict[str, list[Mapping[str, Any]]] = {}
    for name in ("pages", "elements", "bboxes", "evidence", "coordinate_systems"):
        raw = ir_document.get(name)
        if not isinstance(raw, list) or any(
            not isinstance(item, Mapping) for item in raw
        ):
            raise ReadinessContractError(f"IR {name} collection differs")
        values = list(raw)
        identifiers = [item.get("id") for item in values]
        if any(
            not isinstance(identifier, str) or not identifier
            for identifier in identifiers
        ) or len(identifiers) != len(set(identifiers)):
            raise ReadinessContractError(f"IR {name} IDs differ")
        collections[name] = values
    pages_by_index = {page.get("page_index"): page for page in collections["pages"]}
    elements_by_id = {element["id"]: element for element in collections["elements"]}
    bboxes_by_id = {bbox["id"]: bbox for bbox in collections["bboxes"]}
    evidence_by_id = {record["id"]: record for record in collections["evidence"]}
    coordinates_by_id = {
        coordinate["id"]: coordinate for coordinate in collections["coordinate_systems"]
    }
    public_source = public_document.get("document")
    source_sha256 = (
        public_source.get("sha256") if isinstance(public_source, Mapping) else None
    )
    if source_sha256 is not None and not _is_hash(source_sha256):
        raise ReadinessContractError("public/IR source hash differs")
    public_pages = public_document["pages"]
    canonical_pages = public_document["canonical_presentation"]["pages"]
    canonical_by_index = {page["page_index"]: page for page in canonical_pages}
    expected_page_bindings = [
        (page["page_index"], page["page_identity"]["page_id"]) for page in public_pages
    ]
    actual_page_bindings = [
        (page.get("page_index"), page["id"]) for page in collections["pages"]
    ]
    if (
        len(collections["pages"]) != len(public_pages)
        or len(pages_by_index) != len(public_pages)
        or actual_page_bindings != expected_page_bindings
    ):
        raise ReadinessContractError("IR physical page coverage differs")
    element_owner_page: dict[str, str] = {}
    for page in collections["pages"]:
        for element_id in page.get("element_ids", []):
            if element_id not in elements_by_id or element_id in element_owner_page:
                raise ReadinessContractError("IR element page ownership differs")
            element_owner_page[element_id] = page["id"]
    public_regions: dict[str, Mapping[str, Any]] = {}
    public_region_items: dict[str, Mapping[str, Any]] = {}
    for public_page in public_pages:
        page_index = public_page["page_index"]
        ir_page = pages_by_index[page_index]
        identity = public_page["page_identity"]
        if (
            ir_page.get("id") != identity["page_id"]
            or ir_page.get("page_identity") != identity
        ):
            raise ReadinessContractError("IR/public page identity differs")
        if canonical_by_index[page_index].get("page_identity") != identity:
            raise ReadinessContractError("IR/canonical page identity differs")
        if identity["detected_printed_label"] is not None:
            evidence_source = identity["evidence_source"]
            expected_label_id = label_candidate_id(
                source_sha256=source_sha256,
                physical_page_index=page_index,
                source_object_ids=evidence_source["source_object_ids"],
                bbox=identity["evidence_bbox"],
            )
            if tuple(evidence_source["evidence_ids"]) != (expected_label_id,):
                raise ReadinessContractError(
                    "IR page-label source candidate ID differs"
                )
            if evidence_source["public_path"]:
                public_path = _exact_public_item_path(
                    evidence_source["public_path"],
                    physical_page_index=page_index,
                )
                owner = resolve_public_path(public_document, public_path)
                element = elements_by_id.get(evidence_source["element_id"])
                bbox = bboxes_by_id.get(evidence_source["bbox_id"])
                coordinate = (
                    coordinates_by_id.get(bbox.get("coordinate_system_id"))
                    if isinstance(bbox, Mapping)
                    else None
                )
                expected_bbox = (
                    {
                        "x": bbox.get("x"),
                        "y": bbox.get("y"),
                        "width": bbox.get("width"),
                        "height": bbox.get("height"),
                        "unit": coordinate.get("unit"),
                    }
                    if isinstance(bbox, Mapping) and isinstance(coordinate, Mapping)
                    else None
                )
                if (
                    not isinstance(owner, Mapping)
                    or owner.get("id") != evidence_source["public_item_id"]
                    or not isinstance(element, Mapping)
                    or element_owner_page.get(element["id"]) != identity["page_id"]
                    or element.get("page_id") != identity["page_id"]
                    or element.get("presentation_role") != "primary"
                    or evidence_source["bbox_id"] not in element.get("bbox_ids", [])
                    or expected_bbox != identity["evidence_bbox"]
                    or not isinstance(coordinate, Mapping)
                    or coordinate.get("page_id") != identity["page_id"]
                    or coordinate.get("origin") != "top_left"
                ):
                    raise ReadinessContractError(
                        "IR exact-public page-label owner binding differs"
                    )
                descriptor = owner.get("running_region")
                if isinstance(descriptor, Mapping) and (
                    descriptor.get("source_element_id") != element["id"]
                    or descriptor.get("bbox_id") != bbox["id"]
                ):
                    raise ReadinessContractError(
                        "IR page-label running owner binding differs"
                    )
                if not isinstance(descriptor, Mapping):
                    source_position = public_path[3]
                    exact_primary_matches = []
                    for primary_element_id in ir_page.get(
                        "presentation_element_ids", []
                    ):
                        primary = elements_by_id.get(primary_element_id)
                        properties = (
                            primary.get("properties")
                            if isinstance(primary, Mapping)
                            else None
                        )
                        legacy_item = (
                            properties.get("legacy_item")
                            if isinstance(properties, Mapping)
                            else None
                        )
                        if (
                            isinstance(primary, Mapping)
                            and primary.get("presentation_role") == "primary"
                            and isinstance(properties, Mapping)
                            and properties.get("source_position") == source_position
                            and isinstance(legacy_item, Mapping)
                            and dict(legacy_item) == dict(owner)
                        ):
                            exact_primary_matches.append(primary)
                    if (
                        len(exact_primary_matches) != 1
                        or exact_primary_matches[0]["id"] != element["id"]
                    ):
                        raise ReadinessContractError(
                            "IR page-label public primary binding differs"
                        )
        for item in public_page.get("items", []):
            if not isinstance(item, Mapping) or not (
                set(item) & PUBLIC_RUNNING_REGION_KEYS
            ):
                continue
            if set(item) & PUBLIC_RUNNING_REGION_KEYS != PUBLIC_RUNNING_REGION_KEYS:
                raise ReadinessContractError("partial public running-region binding")
            descriptor = item["running_region"]
            if descriptor["id"] in public_regions:
                raise ReadinessContractError("public running-region ID is duplicated")
            public_regions[descriptor["id"]] = descriptor
            public_region_items[descriptor["id"]] = item

    ir_regions: dict[str, Mapping[str, Any]] = {}
    for element in collections["elements"]:
        descriptor = element.get("running_region")
        if descriptor is None:
            continue
        validate_running_region(descriptor)
        if element.get("presentation_role") != "primary":
            raise ReadinessContractError("running region is not an IR primary")
        if (
            element.get("id") != descriptor["source_element_id"]
            or element.get("page_id") != descriptor["page_id"]
            or element_owner_page.get(element["id"]) != descriptor["page_id"]
            or element.get("type") != ROLE_TYPE_SCOPE[descriptor["role"]][0]
        ):
            raise ReadinessContractError("IR running-region element binding differs")
        if descriptor["id"] in ir_regions:
            raise ReadinessContractError("IR running-region ownership is duplicated")
        ir_regions[descriptor["id"]] = descriptor
        if (
            descriptor["id"] not in public_regions
            or public_regions[descriptor["id"]] != descriptor
        ):
            raise ReadinessContractError("public/IR running-region descriptor differs")
        bbox = bboxes_by_id.get(descriptor["bbox_id"])
        if bbox is None or descriptor["bbox_id"] not in element.get("bbox_ids", []):
            raise ReadinessContractError("IR running-region bbox reference differs")
        coordinate = coordinates_by_id.get(bbox.get("coordinate_system_id"))
        expected_bbox = {
            "x": bbox.get("x"),
            "y": bbox.get("y"),
            "width": bbox.get("width"),
            "height": bbox.get("height"),
            "unit": coordinate.get("unit") if isinstance(coordinate, Mapping) else None,
        }
        if (
            not isinstance(coordinate, Mapping)
            or coordinate.get("page_id") != descriptor["page_id"]
            or coordinate.get("origin") != "top_left"
            or expected_bbox != descriptor["bbox"]
        ):
            raise ReadinessContractError("IR running-region bbox geometry differs")
        element_evidence_ids = element.get("evidence_ids", [])
        if not set(descriptor["evidence_ids"]).issubset(set(element_evidence_ids)):
            raise ReadinessContractError("IR running-region evidence backlinks differ")
        extracted = descriptor["source_method"] == "extracted_source_contribution"
        if extracted and element_evidence_ids != list(descriptor["evidence_ids"]):
            raise ReadinessContractError(
                "extracted IR element evidence ownership differs"
            )
        for evidence_id in descriptor["evidence_ids"]:
            record = evidence_by_id.get(evidence_id)
            if (
                record is None
                or record.get("bbox_id") != descriptor["bbox_id"]
                or record.get("element_id") != element["id"]
            ):
                raise ReadinessContractError(
                    "IR running-region evidence binding differs"
                )
            if extracted:
                public_item = public_region_items[descriptor["id"]]
                source_text = public_item.get("value")
                if source_text is None:
                    source_text = public_item.get("md")
                if (
                    not isinstance(source_text, str)
                    or element.get("value") != source_text
                ):
                    raise ReadinessContractError(
                        "extracted public/IR source text differs"
                    )
                validate_extracted_evidence_record(
                    record,
                    descriptor=descriptor,
                    source_text=source_text,
                    source_sha256=source_sha256,
                )
    if ir_regions != public_regions:
        raise ReadinessContractError("public/IR running-region coverage differs")


def validate_repetition_group_bindings(
    bindings: Sequence[tuple[Mapping[str, Any], Mapping[str, Any], float]],
    *,
    source_sha256: str,
) -> None:
    """Validate exact repetition membership, source signature, and stable IDs."""

    if not _is_hash(source_sha256):
        raise ReadinessContractError("repetition source hash differs")
    groups: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any], float]]] = {}
    for binding in bindings:
        if (
            not isinstance(binding, (list, tuple))
            or len(binding) != 3
            or not isinstance(binding[0], Mapping)
            or not isinstance(binding[1], Mapping)
            or isinstance(binding[2], bool)
            or not isinstance(binding[2], (int, float))
            or not math.isfinite(binding[2])
            or binding[2] <= 0
        ):
            raise ReadinessContractError("repetition source binding differs")
        descriptor, candidate, page_height = binding
        validate_running_region(descriptor)
        if (
            candidate.get("public_item_id") != descriptor["source_public_item_id"]
            or tuple(candidate.get("public_path", ()))
            != tuple(descriptor["source_public_path"])
            or candidate.get("element_id") != descriptor["source_element_id"]
            or candidate.get("predecessor_type") != descriptor["predecessor_type"]
            or candidate.get("bbox_id") != descriptor["bbox_id"]
            or tuple(candidate.get("evidence_ids", ()))
            != tuple(descriptor["evidence_ids"])
            or tuple(candidate.get("source_object_ids", ()))
            != tuple(descriptor["source_object_ids"])
            or candidate.get("source_method") != descriptor["source_method"]
            or _canonical_bbox(
                candidate.get("bbox"), path="repetition.source_candidate_bbox"
            )
            != _canonical_bbox(descriptor["bbox"], path="repetition.descriptor_bbox")
        ):
            raise ReadinessContractError("repetition descriptor/source binding differs")
        group_id = descriptor["repetition_group_id"]
        if group_id is not None:
            groups.setdefault(group_id, []).append(
                (descriptor, candidate, float(page_height))
            )
    for group_id, members in groups.items():
        actual_pages = tuple(
            sorted({descriptor["physical_page_index"] for descriptor, _, _ in members})
        )
        if len(actual_pages) < 2 or len(actual_pages) != len(members):
            raise ReadinessContractError("repetition group has insufficient members")
        if any(
            tuple(descriptor["repetition_page_indexes"]) != actual_pages
            for descriptor, _, _ in members
        ):
            raise ReadinessContractError("repetition declared member pages differ")
        signatures = {
            _string(
                candidate.get("normalized_signature"),
                "repetition.normalized_signature",
            )
            for _, candidate, _ in members
        }
        bands = {candidate.get("boundary_band") for _, candidate, _ in members}
        if len(signatures) != 1 or len(bands) != 1 or not bands <= {"top", "bottom"}:
            raise ReadinessContractError("repetition source signature/band differs")
        signature = next(iter(signatures))
        boundary_band = next(iter(bands))
        expected_group_id = stable_id(
            "running-repeat",
            POLICY_ID,
            source_sha256,
            boundary_band,
            signature,
        )
        if group_id != expected_group_id:
            raise ReadinessContractError("repetition stable group ID differs")
        normalized_midpoints: list[float] = []
        horizontal_intervals: list[tuple[float, float]] = []
        for _, candidate, page_height in members:
            bbox = _canonical_bbox(candidate.get("bbox"), path="repetition.bbox")
            normalized_midpoints.append(
                (float(bbox["y"]) + float(bbox["height"]) / 2) / page_height
            )
            horizontal_intervals.append(
                (float(bbox["x"]), float(bbox["x"]) + float(bbox["width"]))
            )
        if max(normalized_midpoints) - min(normalized_midpoints) > 0.02 + 1e-9:
            raise ReadinessContractError("repetition vertical midpoint drift differs")
        common_left = max(left for left, _ in horizontal_intervals)
        common_right = min(right for _, right in horizontal_intervals)
        common_overlap = max(0.0, common_right - common_left)
        if any(
            common_overlap / (right - left) < 0.50
            for left, right in horizontal_intervals
        ):
            raise ReadinessContractError("repetition horizontal overlap differs")


def expected_candidate_role(candidate: Mapping[str, Any]) -> str:
    """Return the sole role admitted by a method/role/band proof tuple."""

    method = candidate.get("source_method")
    band = candidate.get("boundary_band")
    raw_role = candidate.get("raw_layout_role")
    if band not in {"top", "bottom"}:
        raise ReadinessContractError("candidate role band differs")
    if raw_role is not None and (
        raw_role not in {"page_header", "page_footer"}
        or (raw_role == "page_header") != (band == "top")
    ):
        raise ReadinessContractError("candidate raw role/band differs")
    if method == "trusted_layout_role":
        if raw_role is None:
            raise ReadinessContractError("trusted candidate has no layout role")
        return "header" if raw_role == "page_header" else "footer"
    if method == "boundary_navigation":
        return "navigation_top" if band == "top" else "navigation_bottom"
    if method == "printed_label_boundary":
        return "header" if band == "top" else "footer"
    if method == "effective_boundary_cluster":
        if band != "bottom":
            raise ReadinessContractError("bottom-boundary candidate band differs")
        return "footer"
    if method in {"cross_page_repetition", "extracted_source_contribution"}:
        return "header" if band == "top" else "footer"
    raise ReadinessContractError("candidate source method differs")


_EFFECTIVE_CLUSTER_PROOF_FIELDS = (
    "items",
    "remaining_body_bboxes",
    "candidate_cut_count",
)


def _validate_effective_candidate_membership(
    candidate: Mapping[str, Any],
    proof: Mapping[str, Any],
    *,
    page_width: float,
    page_height: float,
    member_kind: Literal["any", "furniture", "navigation", "label"],
    navigation_cue: str | None = None,
    normalized_label: str | None = None,
) -> None:
    _exact_keys(
        proof, _EFFECTIVE_CLUSTER_PROOF_FIELDS, "method_proof.effective_cluster"
    )
    validate_effective_bottom_cluster(
        proof["items"],
        remaining_body_bboxes=proof["remaining_body_bboxes"],
        page_width=page_width,
        page_height=page_height,
        candidate_cut_count=proof["candidate_cut_count"],
    )
    selected_items = [
        item for item in proof["items"] if item["id"] == candidate["public_item_id"]
    ]
    if len(selected_items) != 1 or _canonical_bbox(
        selected_items[0]["bbox"], path="method_proof.effective_cluster.item_bbox"
    ) != _canonical_bbox(
        candidate["bbox"], path="method_proof.effective_cluster.candidate_bbox"
    ):
        raise ReadinessContractError("effective-cluster method proof differs")
    selected = selected_items[0]
    if member_kind == "furniture" and (
        selected["navigation_cue"] is not None
        or selected["normalized_label"] is not None
    ):
        raise ReadinessContractError("effective furniture member proof differs")
    if member_kind == "navigation" and (
        selected["navigation_cue"] is None
        or _normalized_navigation_cue(
            selected["navigation_cue"], "method_proof.effective.navigation_cue"
        )
        != navigation_cue
        or selected["normalized_label"] is not None
    ):
        raise ReadinessContractError("effective navigation member proof differs")
    if member_kind == "label" and (
        selected["navigation_cue"] is not None
        or selected["normalized_label"] != normalized_label
    ):
        raise ReadinessContractError("effective label member proof differs")


def validate_boundary_method_proof(
    candidate: Mapping[str, Any],
    proof: Mapping[str, Any] | None,
    *,
    page_width: float,
    page_height: float,
    label_candidate_ids: Sequence[str],
    label_candidates: Sequence[Mapping[str, Any]] = (),
    extracted_plan: ExtractedContributionPlan | None = None,
    expected_repetition_page_indexes: Sequence[int] | None = None,
) -> None:
    """Compose each detached method proof with its accepted source candidate."""

    method = candidate["source_method"]
    effective = _candidate_uses_effective_bottom(
        candidate,
        page_width=page_width,
        page_height=page_height,
        path="method_proof.candidate",
    )
    if method in {"trusted_layout_role", "cross_page_repetition"}:
        if not effective and proof is not None:
            raise ReadinessContractError("intrinsic method received a detached proof")
        if effective:
            if not isinstance(proof, Mapping):
                raise ReadinessContractError("effective intrinsic proof is absent")
            _validate_effective_candidate_membership(
                candidate,
                proof,
                page_width=page_width,
                page_height=page_height,
                member_kind="any",
            )
        expected_candidate_role(candidate)
        return
    if not isinstance(proof, Mapping):
        raise ReadinessContractError("accepted candidate method proof is absent")
    if method == "boundary_navigation":
        fields = (
            ("navigation_cue", "effective_cluster")
            if effective
            else ("navigation_cue",)
        )
        _exact_keys(proof, fields, "method_proof.navigation")
        cue = _normalized_navigation_cue(
            proof["navigation_cue"],
            "method_proof.navigation.navigation_cue",
        )
        if effective:
            effective_proof = proof["effective_cluster"]
            if not isinstance(effective_proof, Mapping):
                raise ReadinessContractError("effective navigation proof is absent")
            _validate_effective_candidate_membership(
                candidate,
                effective_proof,
                page_width=page_width,
                page_height=page_height,
                member_kind="navigation",
                navigation_cue=cue,
            )
        expected_candidate_role(candidate)
        return
    if method == "printed_label_boundary":
        fields = (
            ("label_candidate_id", "effective_cluster")
            if effective
            else ("label_candidate_id",)
        )
        _exact_keys(
            proof,
            fields,
            "method_proof.printed_label",
        )
        if proof["label_candidate_id"] not in set(label_candidate_ids):
            raise ReadinessContractError("printed-label method proof differs")
        matched_labels = [
            label
            for label in label_candidates
            if label.get("id") == proof["label_candidate_id"]
        ]
        if len(matched_labels) != 1:
            raise ReadinessContractError("printed-label retained candidate is absent")
        label = matched_labels[0]
        if not _native_label_owner_geometry_matches(
            label["bbox"],
            candidate["bbox"],
            page_height=page_height,
        ) or not set(label["source_object_ids"]) & set(candidate["source_object_ids"]):
            raise ReadinessContractError("printed-label source span binding differs")
        if (
            candidate["boundary_band"] == "top"
            and _INTEGER_RE.fullmatch(label["visible_text"])
            and candidate["raw_layout_role"] != "page_header"
        ):
            raise ReadinessContractError("bare top label lacks trusted-header proof")
        if effective:
            effective_proof = proof["effective_cluster"]
            if not isinstance(effective_proof, Mapping):
                raise ReadinessContractError("effective printed-label proof is absent")
            _validate_effective_candidate_membership(
                candidate,
                effective_proof,
                page_width=page_width,
                page_height=page_height,
                member_kind="label",
                normalized_label=label["normalized_label"],
            )
        expected_candidate_role(candidate)
        return
    if method == "effective_boundary_cluster":
        _validate_effective_candidate_membership(
            candidate,
            proof,
            page_width=page_width,
            page_height=page_height,
            member_kind="furniture",
        )
        expected_candidate_role(candidate)
        return
    if method == "extracted_source_contribution":
        fields = (
            "native_source",
            "evidence_mode",
            "repetition_page_indexes",
            "complete_delimiter_line",
            "scalar_match_count",
            "intervals_disjoint",
            "owner_kind",
        )
        if effective:
            fields = (*fields, "effective_cluster")
        _exact_keys(proof, fields, "method_proof.extracted")
        if extracted_plan is None:
            raise ReadinessContractError("extracted method plan proof is absent")
        if (
            not isinstance(proof["owner_kind"], str)
            or proof["owner_kind"].casefold()
            != candidate["predecessor_type"].casefold()
        ):
            raise ReadinessContractError("extracted proof owner kind differs")
        validate_extracted_candidate_eligibility(
            contribution_text=extracted_plan.source_text,
            native_source=proof["native_source"],
            evidence_mode=proof["evidence_mode"],
            repetition_page_indexes=proof["repetition_page_indexes"],
            complete_delimiter_line=proof["complete_delimiter_line"],
            scalar_match_count=proof["scalar_match_count"],
            intervals_disjoint=proof["intervals_disjoint"],
            owner_kind=proof["owner_kind"],
            owner_sha256_before=extracted_plan.owner_sha256_before,
            owner_sha256_after=extracted_plan.owner_sha256_after,
        )
        if proof["evidence_mode"] == "exact_repetition":
            if not isinstance(expected_repetition_page_indexes, Sequence) or isinstance(
                expected_repetition_page_indexes,
                (str, bytes, bytearray),
            ):
                raise ReadinessContractError(
                    "extracted repetition expected membership is absent"
                )
            expected_pages = tuple(expected_repetition_page_indexes)
            candidate_path = validate_public_path(
                candidate["public_path"],
                path="method_proof.extracted.public_path",
            )
            if (
                len(expected_pages) < 2
                or len(expected_pages) > MAX_REPETITION_MEMBERS
                or expected_pages != tuple(sorted(set(expected_pages)))
                or any(
                    isinstance(page, bool)
                    or not isinstance(page, int)
                    or not 1 <= page <= MAX_PAGES_PER_DOCUMENT
                    for page in expected_pages
                )
                or tuple(proof["repetition_page_indexes"]) != expected_pages
                or len(candidate_path) < 2
                or candidate_path[1] + 1 not in expected_pages
            ):
                raise ReadinessContractError(
                    "extracted repetition expected membership differs"
                )
        elif expected_repetition_page_indexes not in (None, (), []):
            raise ReadinessContractError(
                "trusted extracted proof received repetition membership"
            )
        if proof["evidence_mode"] == "trusted_layout_role" and candidate[
            "raw_layout_role"
        ] not in {"page_header", "page_footer"}:
            raise ReadinessContractError("extracted trusted-role proof differs")
        if effective:
            effective_proof = proof["effective_cluster"]
            if not isinstance(effective_proof, Mapping):
                raise ReadinessContractError("effective extracted proof is absent")
            _validate_effective_candidate_membership(
                candidate,
                effective_proof,
                page_width=page_width,
                page_height=page_height,
                member_kind="any",
            )
        expected_candidate_role(candidate)
        return
    raise ReadinessContractError("unsupported boundary method proof")


def validate_source_owner_admission(
    *,
    owner_kind: str,
    raw_layout_role: str | None,
    source_method: str,
    prior_semantic_owner: bool,
) -> None:
    """Refuse label-like evidence from semantic containers or prior owners."""

    kind = _string(owner_kind, "source_owner.owner_kind").casefold()
    if source_method not in SOURCE_METHODS:
        raise ReadinessContractError("source candidate method differs")
    excluded_kinds = (
        _EXTRACTED_SOURCE_EXCLUDED_OWNER_KINDS
        if source_method == "extracted_source_contribution"
        else _DIRECT_SOURCE_EXCLUDED_OWNER_KINDS
    )
    if kind in excluded_kinds:
        raise ReadinessContractError("source candidate owner kind is ineligible")
    if (
        source_method != "extracted_source_contribution"
        and prior_semantic_owner is not False
    ):
        raise ReadinessContractError("source candidate already has a semantic owner")
    if source_method == "extracted_source_contribution" and not isinstance(
        prior_semantic_owner, bool
    ):
        raise ReadinessContractError("source candidate owner state differs")
    if source_method == "trusted_layout_role" and raw_layout_role not in {
        "page_header",
        "page_footer",
    }:
        raise ReadinessContractError("trusted source candidate lacks a trusted role")


def _effective_cluster_payload(
    candidate: Mapping[str, Any], proof: Mapping[str, Any] | None
) -> Mapping[str, Any] | None:
    if not isinstance(proof, Mapping):
        return None
    method = candidate["source_method"]
    if method in {
        "boundary_navigation",
        "printed_label_boundary",
        "extracted_source_contribution",
    }:
        value = proof.get("effective_cluster")
        return value if isinstance(value, Mapping) else None
    return proof


def _validate_effective_cluster_projection_parity(
    cluster_proof: Mapping[str, Any],
    *,
    report_page: Mapping[str, Any],
    public_page: Mapping[str, Any],
    predecessor_page: Mapping[str, Any],
    canonical_page: Mapping[str, Any],
    ir_page: Mapping[str, Any],
    predecessor_ir_page: Mapping[str, Any],
    ir_elements: Mapping[str, Mapping[str, Any]],
    predecessor_ir_elements: Mapping[str, Mapping[str, Any]],
    ir_bboxes: Mapping[str, Mapping[str, Any]],
    accepted_descriptors: Mapping[str, Mapping[str, Any]],
    proofs: Mapping[str, Mapping[str, Any]],
) -> None:
    """Resolve the complete effective cluster against every committed surface."""

    items = cluster_proof["items"]
    cluster_ids = [item["id"] for item in items]
    candidates_by_item: dict[str, Mapping[str, Any]] = {}
    for item in items:
        matches = [
            candidate
            for candidate in report_page["boundary_candidates"]
            if candidate["disposition"] == "accepted"
            and candidate["public_item_id"] == item["id"]
        ]
        if len(matches) != 1 or matches[0]["id"] not in accepted_descriptors:
            raise ReadinessContractError(
                "effective cluster member is not an accepted projected candidate"
            )
        candidate = matches[0]
        candidates_by_item[item["id"]] = candidate
        if (
            _effective_cluster_payload(candidate, proofs.get(candidate["id"]))
            != cluster_proof
        ):
            raise ReadinessContractError("effective cluster member proof differs")
        if item["navigation_cue"] is not None:
            if candidate["source_method"] != "boundary_navigation":
                raise ReadinessContractError("effective cue member method differs")
        elif item["normalized_label"] is not None:
            if candidate["source_method"] != "printed_label_boundary":
                raise ReadinessContractError("effective label member method differs")
        elif candidate["source_method"] != "effective_boundary_cluster":
            raise ReadinessContractError("effective furniture member method differs")

    public_items = public_page.get("items")
    predecessor_items = predecessor_page.get("items")
    if not isinstance(public_items, list) or not isinstance(predecessor_items, list):
        raise ReadinessContractError("effective cluster public items are absent")
    public_by_id = {
        item.get("id"): item for item in public_items if isinstance(item, Mapping)
    }
    predecessor_by_id = {
        item.get("id"): item for item in predecessor_items if isinstance(item, Mapping)
    }
    cluster_element_ids: list[str] = []
    cluster_block_ids: list[str] = []
    for proof_item in items:
        item_id = proof_item["id"]
        candidate = candidates_by_item[item_id]
        descriptor = accepted_descriptors[candidate["id"]]
        current = public_by_id.get(item_id)
        predecessor = predecessor_by_id.get(item_id)
        current_element = ir_elements.get(descriptor["source_element_id"])
        predecessor_element = predecessor_ir_elements.get(
            descriptor["source_element_id"]
        )
        bbox = ir_bboxes.get(descriptor["bbox_id"])
        if (
            not isinstance(current, Mapping)
            or not isinstance(predecessor, Mapping)
            or _has_prior_semantic_owner(predecessor)
            or predecessor.get("reading_order") != proof_item["presentation_index"]
            or _canonical_bbox(
                predecessor.get("bbox"), path="effective.predecessor_bbox"
            )
            != _canonical_bbox(proof_item["bbox"], path="effective.proof_bbox")
            or not isinstance(current_element, Mapping)
            or not isinstance(predecessor_element, Mapping)
            or current_element.get("page_id") != descriptor["page_id"]
            or predecessor_element.get("page_id") != descriptor["page_id"]
            or descriptor["bbox_id"] not in current_element.get("bbox_ids", [])
            or descriptor["bbox_id"] not in predecessor_element.get("bbox_ids", [])
            or not isinstance(bbox, Mapping)
            or {key: bbox.get(key) for key in ("x", "y", "width", "height")}
            != {key: proof_item["bbox"][key] for key in ("x", "y", "width", "height")}
        ):
            raise ReadinessContractError("effective cluster member custody differs")
        cluster_element_ids.append(descriptor["source_element_id"])
        cluster_block_ids.append(descriptor["canonical_block_id"])

    proof_body = [
        _canonical_bbox(bbox, path="effective.remaining_body_bbox")
        for bbox in cluster_proof["remaining_body_bboxes"]
    ]
    expected_body_items = [
        item
        for item in predecessor_items
        if isinstance(item, Mapping)
        and item.get("id") not in set(cluster_ids)
        and isinstance(item.get("reading_order"), int)
        and item["reading_order"] < items[0]["presentation_index"]
        and item.get("type") not in {"header", "footer"}
        and isinstance(item.get("bbox"), Mapping)
    ]
    expected_body = [
        _canonical_bbox(item["bbox"], path="effective.predecessor_body_bbox")
        for item in sorted(
            expected_body_items, key=lambda value: value["reading_order"]
        )
    ]
    trailing_ids = [
        item.get("id")
        for item in predecessor_items
        if isinstance(item, Mapping)
        and isinstance(item.get("reading_order"), int)
        and item["reading_order"] >= items[0]["presentation_index"]
    ]
    if proof_body != expected_body or trailing_ids != cluster_ids:
        raise ReadinessContractError("effective cluster body/trailing order differs")

    def require_contiguous(sequence: Any, expected: Sequence[str], path: str) -> None:
        if not isinstance(sequence, (list, tuple)):
            raise ReadinessContractError(f"{path} is not ordered")
        positions = [sequence.index(value) for value in expected if value in sequence]
        if len(positions) != len(expected) or positions != list(
            range(positions[0], positions[0] + len(expected))
        ):
            raise ReadinessContractError(f"{path} cluster order differs")

    require_contiguous(
        ir_page.get("presentation_element_ids"),
        cluster_element_ids,
        "effective IR presentation",
    )
    require_contiguous(
        predecessor_ir_page.get("presentation_element_ids"),
        cluster_element_ids,
        "effective predecessor IR presentation",
    )
    full = canonical_page.get("full")
    if not isinstance(full, Mapping):
        raise ReadinessContractError("effective canonical full view is absent")
    require_contiguous(
        full.get("block_ids"), cluster_block_ids, "effective canonical presentation"
    )


_SOURCE_PROJECTION_EXTRACTION_FIELDS = (
    "source_report",
    "extracted_plans",
    "comparison_ledger",
    "method_proofs",
)
_SOURCE_PROJECTION_OWNER_BINDING_FIELDS = (
    "candidate_id",
    "page_index",
    "public_item_id",
    "public_path",
    "ir_element_id",
    "canonical_block_id",
)


def _extract_running_region_source_projection(
    source_pdf_bytes: bytes,
    configured_predecessor: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Production hook replaced only when the post-US07 extractor lands."""

    del source_pdf_bytes, configured_predecessor
    raise ReadinessContractError("fixed running-region source extractor is unavailable")


def _extracted_plan_from_json_payload(
    payload: Mapping[str, Any],
) -> ExtractedContributionPlan:
    if not isinstance(payload, Mapping):
        raise ReadinessContractError("source projection extracted-plan payload differs")
    _exact_keys(
        payload,
        tuple(ExtractedContributionPlan.__dataclass_fields__),
        "source_projection_authority.extracted_plan",
    )
    values = dict(payload)
    for field_name in (
        "presentation_fragments",
        "delimiters",
        "residual_insertion_offsets",
        "presentation_fragment_sha256",
        "removed_interval_sha256",
        "delimiter_sha256",
    ):
        value = values[field_name]
        if not isinstance(value, (list, tuple)):
            raise ReadinessContractError(
                "source projection extracted-plan sequence differs"
            )
        values[field_name] = tuple(value)
    for field_name in ("predecessor_intervals", "whitespace_mappings"):
        value = values[field_name]
        if not isinstance(value, (list, tuple)) or any(
            not isinstance(record, (list, tuple)) for record in value
        ):
            raise ReadinessContractError(
                "source projection extracted-plan ranges differ"
            )
        values[field_name] = tuple(tuple(record) for record in value)
    span_groups = values["source_span_groups"]
    if not isinstance(span_groups, (list, tuple)) or any(
        not isinstance(group, (list, tuple))
        or any(not isinstance(span, (list, tuple)) for span in group)
        for group in span_groups
    ):
        raise ReadinessContractError(
            "source projection extracted-plan source spans differ"
        )
    values["source_span_groups"] = tuple(
        tuple(tuple(span) for span in group) for group in span_groups
    )
    try:
        plan = ExtractedContributionPlan(**values)
    except TypeError as exc:
        raise ReadinessContractError(
            "source projection extracted-plan construction differs"
        ) from exc
    plan.execute()
    return plan


def _source_projection_extraction_payload(
    value: Any,
    *,
    predecessor_public: Mapping[str, Any],
) -> tuple[bytes, bytes, bytes, bytes]:
    if not isinstance(value, Mapping):
        raise ReadinessContractError(
            "fixed running-region source extraction is not an object"
        )
    _exact_keys(
        value,
        _SOURCE_PROJECTION_EXTRACTION_FIELDS,
        "source_projection_authority.extraction",
    )
    source_report = value["source_report"]
    plans_payload = value["extracted_plans"]
    comparison_ledger = value["comparison_ledger"]
    method_proofs = value["method_proofs"]
    if not isinstance(source_report, Mapping):
        raise ReadinessContractError("source projection authority report differs")
    if not isinstance(plans_payload, (list, tuple)):
        raise ReadinessContractError("source projection authority plans differ")
    if not isinstance(comparison_ledger, (list, tuple)):
        raise ReadinessContractError(
            "source projection authority comparison ledger differs"
        )
    if not isinstance(method_proofs, Mapping):
        raise ReadinessContractError("source projection authority method proofs differ")
    validate_source_report(
        source_report,
        public_document=predecessor_public,
        method_proofs=method_proofs,
    )
    predecessor_pages = predecessor_public["pages"]
    if len(source_report["pages"]) != len(predecessor_pages) or any(
        report_page["page_index"] != predecessor_page["page_index"]
        or float(report_page["page_width"]) != float(predecessor_page["page_width"])
        or float(report_page["page_height"]) != float(predecessor_page["page_height"])
        or report_page["unit"] != predecessor_page["unit"]
        for report_page, predecessor_page in zip(
            source_report["pages"], predecessor_pages, strict=True
        )
    ):
        raise ReadinessContractError(
            "source projection authority predecessor geometry differs"
        )
    plans = tuple(_extracted_plan_from_json_payload(plan) for plan in plans_payload)
    validate_extracted_plan_ledger(plans)
    comparison_total = sum(
        entry.get("comparison_count", 0)
        if isinstance(entry, Mapping)
        and isinstance(entry.get("comparison_count"), int)
        and not isinstance(entry.get("comparison_count"), bool)
        else 0
        for entry in comparison_ledger
    )
    validate_comparison_ledger(
        comparison_ledger,
        source_page_count=len(source_report["pages"]),
        expected_comparison_count=comparison_total,
    )
    return (
        strict_json_bytes(source_report),
        strict_json_bytes(plans_payload),
        strict_json_bytes(comparison_ledger),
        strict_json_bytes(method_proofs),
    )


def _source_projection_owner_bindings(
    source_report: Mapping[str, Any],
    predecessor_public: Mapping[str, Any],
    predecessor_ir: Mapping[str, Any],
) -> bytes:
    """Freeze only explicit source-candidate public/IR/canonical owners."""

    ir_elements = predecessor_ir["elements"]
    canonical_pages = predecessor_public["canonical_presentation"]["pages"]
    ir_page_id_by_index = {
        page["page_index"]: page["id"] for page in predecessor_ir["pages"]
    }
    canonical_page_by_index = {page["page_index"]: page for page in canonical_pages}
    bindings: list[dict[str, Any]] = []
    for report_page in source_report["pages"]:
        page_index = report_page["page_index"]
        for candidate in report_page["boundary_candidates"]:
            owner = resolve_public_path(predecessor_public, candidate["public_path"])
            if (
                not isinstance(owner, Mapping)
                or owner.get("id") != candidate["public_item_id"]
            ):
                raise ReadinessContractError(
                    "source projection candidate public owner differs"
                )
            element_matches = [
                element
                for element in ir_elements
                if element.get("page_id") == ir_page_id_by_index.get(page_index)
                and candidate["public_item_id"]
                in _explicit_ir_public_owner_ids(element)
                and (
                    candidate["source_method"] == "extracted_source_contribution"
                    or (
                        candidate["source_method"] != "extracted_source_contribution"
                        and element.get("id") == candidate["element_id"]
                        and candidate["bbox_id"] in element.get("bbox_ids", ())
                    )
                )
            ]
            if len(element_matches) != 1:
                raise ReadinessContractError(
                    "source projection candidate IR owner differs"
                )
            block_matches = [
                block
                for block in canonical_page_by_index[page_index]["blocks"]
                if block.get("primary_element_id") == element_matches[0]["id"]
            ]
            if len(block_matches) != 1:
                raise ReadinessContractError(
                    "source projection candidate canonical owner differs"
                )
            bindings.append(
                {
                    "candidate_id": candidate["id"],
                    "page_index": page_index,
                    "public_item_id": candidate["public_item_id"],
                    "public_path": list(candidate["public_path"]),
                    "ir_element_id": element_matches[0]["id"],
                    "canonical_block_id": block_matches[0]["id"],
                }
            )
    if len(bindings) > MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT:
        raise ReadinessContractError(
            "source projection candidate-owner bindings exceed their cap"
        )
    identities = [binding["candidate_id"] for binding in bindings]
    if len(identities) != len(set(identities)):
        raise ReadinessContractError(
            "source projection candidate-owner identity differs"
        )
    return strict_json_bytes({"bindings": bindings})


class _ValidatedSourceProjectionAuthority:
    """Opaque, identity-authorized result of fixed US08 source extraction."""

    __slots__ = (
        "__weakref__",
        "comparison_ledger_json",
        "extracted_plans_json",
        "method_proofs_json",
        "owner_bindings_json",
        "predecessor_sha256",
        "source_report_json",
        "source_sha256",
    )

    def __new__(cls) -> Self:
        raise ReadinessContractError(
            "source projection authority must be factory-issued"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        del name, value
        raise ReadinessContractError("source projection authority is immutable")

    def __copy__(self) -> Self:
        raise ReadinessContractError("source projection authority cannot be copied")

    def __deepcopy__(self, memo: Any) -> Self:
        del memo
        raise ReadinessContractError("source projection authority cannot be copied")

    def __reduce__(self) -> Any:
        raise ReadinessContractError("source projection authority cannot be serialized")

    def __reduce_ex__(self, protocol: int) -> Any:
        del protocol
        raise ReadinessContractError("source projection authority cannot be serialized")


_ISSUED_SOURCE_PROJECTION_AUTHORITIES: dict[
    int,
    tuple[
        weakref.ReferenceType[_ValidatedSourceProjectionAuthority],
        bytes,
    ],
] = {}


def _source_projection_authority_fingerprint(
    authority: _ValidatedSourceProjectionAuthority,
) -> bytes:
    return hashlib.sha256(
        b"\x1e".join(
            (
                authority.source_sha256.encode(),
                authority.predecessor_sha256.encode(),
                authority.source_report_json,
                authority.extracted_plans_json,
                authority.comparison_ledger_json,
                authority.method_proofs_json,
                authority.owner_bindings_json,
            )
        )
    ).digest()


def _require_issued_source_projection_authority(
    authority: Any,
) -> _ValidatedSourceProjectionAuthority:
    if not isinstance(authority, _ValidatedSourceProjectionAuthority):
        raise ReadinessContractError("source projection authority differs")
    try:
        issued = _ISSUED_SOURCE_PROJECTION_AUTHORITIES.get(id(authority))
        if (
            issued is None
            or issued[0]() is not authority
            or issued[1] != _source_projection_authority_fingerprint(authority)
        ):
            raise ReadinessContractError(
                "source projection authority was not factory-issued"
            )
    except AttributeError as exc:
        raise ReadinessContractError(
            "source projection authority is uninitialized"
        ) from exc
    return authority


def _issue_source_projection_authority(
    *,
    source_sha256: str,
    predecessor_sha256: str,
    source_report_json: bytes,
    extracted_plans_json: bytes,
    comparison_ledger_json: bytes,
    method_proofs_json: bytes,
    owner_bindings_json: bytes,
) -> _ValidatedSourceProjectionAuthority:
    if len(_ISSUED_SOURCE_PROJECTION_AUTHORITIES) >= (
        MAX_LIVE_SOURCE_PROJECTION_AUTHORITIES
    ):
        raise ReadinessContractError("source projection authority registry is full")
    authority = object.__new__(_ValidatedSourceProjectionAuthority)
    for name, value in (
        ("source_sha256", source_sha256),
        ("predecessor_sha256", predecessor_sha256),
        ("source_report_json", source_report_json),
        ("extracted_plans_json", extracted_plans_json),
        ("comparison_ledger_json", comparison_ledger_json),
        ("method_proofs_json", method_proofs_json),
        ("owner_bindings_json", owner_bindings_json),
    ):
        object.__setattr__(authority, name, value)
    authority_id = id(authority)

    def revoke(reference: weakref.ReferenceType[Any]) -> None:
        current = _ISSUED_SOURCE_PROJECTION_AUTHORITIES.get(authority_id)
        if current is not None and current[0] is reference:
            _ISSUED_SOURCE_PROJECTION_AUTHORITIES.pop(authority_id, None)

    reference = weakref.ref(authority, revoke)
    _ISSUED_SOURCE_PROJECTION_AUTHORITIES[authority_id] = (
        reference,
        _source_projection_authority_fingerprint(authority),
    )
    return authority


def prepare_source_projection_authority(
    configured_predecessor: Mapping[str, Any],
    source_pdf_bytes: bytes,
) -> _ValidatedSourceProjectionAuthority:
    """Run the fixed US08 extractor twice and freeze its source authority."""

    if not isinstance(configured_predecessor, Mapping):
        raise ReadinessContractError("source projection configured predecessor differs")
    if (
        not isinstance(source_pdf_bytes, bytes)
        or not source_pdf_bytes
        or len(source_pdf_bytes) > MAX_SOURCE_PDF_BYTES
    ):
        raise ReadinessContractError(
            "source projection authority requires exact bounded PDF bytes"
        )
    if len(_ISSUED_SOURCE_PROJECTION_AUTHORITIES) >= (
        MAX_LIVE_SOURCE_PROJECTION_AUTHORITIES
    ):
        raise ReadinessContractError("source projection authority registry is full")
    predecessor = deepcopy(dict(configured_predecessor))
    predecessor_public, predecessor_ir = _validate_predecessor_state_bundle(predecessor)
    source_sha256 = hashlib.sha256(source_pdf_bytes).hexdigest()
    if source_sha256 != predecessor_public["document"]["sha256"]:
        raise ReadinessContractError(
            "source projection PDF/configured source hash differs"
        )
    extracted: list[tuple[bytes, bytes, bytes, bytes]] = []
    for _run in range(2):
        try:
            value = _extract_running_region_source_projection(
                source_pdf_bytes,
                deepcopy(predecessor),
            )
        except ReadinessContractError:
            raise
        except Exception as exc:
            raise ReadinessContractError(
                "fixed running-region source extraction failed"
            ) from exc
        extracted.append(
            _source_projection_extraction_payload(
                value,
                predecessor_public=predecessor_public,
            )
        )
    first_report = json.loads(extracted[0][0])
    second_report = json.loads(extracted[1][0])
    if (
        strict_json_bytes(source_report_semantic_payload(first_report))
        != strict_json_bytes(source_report_semantic_payload(second_report))
        or extracted[0][1:] != extracted[1][1:]
    ):
        raise ReadinessContractError(
            "fixed running-region source extraction is nondeterministic"
        )
    if first_report["source_sha256"] != source_sha256:
        raise ReadinessContractError("source projection report/PDF source hash differs")
    return _issue_source_projection_authority(
        source_sha256=source_sha256,
        predecessor_sha256=sha256_json(predecessor),
        source_report_json=extracted[0][0],
        extracted_plans_json=extracted[0][1],
        comparison_ledger_json=extracted[0][2],
        method_proofs_json=extracted[0][3],
        owner_bindings_json=_source_projection_owner_bindings(
            first_report, predecessor_public, predecessor_ir
        ),
    )


def _source_projection_authority_report(
    authority: _ValidatedSourceProjectionAuthority,
) -> Mapping[str, Any]:
    try:
        report = json.loads(authority.source_report_json)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ReadinessContractError(
            "source projection authority report is malformed"
        ) from exc
    if not isinstance(report, Mapping):
        raise ReadinessContractError("source projection authority report differs")
    return report


def validate_source_projection_bindings(
    source_authority: _ValidatedSourceProjectionAuthority,
    public_document: Mapping[str, Any],
    *,
    predecessor_document: Mapping[str, Any],
    ir_document: Mapping[str, Any] | None = None,
    predecessor_ir: Mapping[str, Any] | None = None,
    extracted_plans: Sequence[ExtractedContributionPlan] = (),
    comparison_ledger: Sequence[Mapping[str, Any]] = (),
    method_proofs: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Bind every selected source candidate to its committed public/IR result."""

    authority = _require_issued_source_projection_authority(source_authority)
    source_report = _source_projection_authority_report(authority)
    proofs = {} if method_proofs is None else method_proofs
    if not isinstance(proofs, Mapping) or any(
        not isinstance(candidate_id, str) or not isinstance(proof, Mapping)
        for candidate_id, proof in proofs.items()
    ):
        raise ReadinessContractError("boundary method proof ledger differs")
    validate_extracted_plan_ledger(extracted_plans)
    if not isinstance(predecessor_document, Mapping) or not isinstance(
        predecessor_ir, Mapping
    ):
        raise ReadinessContractError(
            "configured predecessor public/IR authority is required"
        )
    predecessor_bundle = {
        "public": deepcopy(dict(predecessor_document)),
        "ir": deepcopy(dict(predecessor_ir)),
    }
    predecessor_public, predecessor_ir_authority = _validate_predecessor_state_bundle(
        predecessor_bundle
    )
    if authority.predecessor_sha256 != sha256_json(
        predecessor_bundle
    ) or authority.owner_bindings_json != _source_projection_owner_bindings(
        source_report, predecessor_public, predecessor_ir_authority
    ):
        raise ReadinessContractError(
            "source projection configured predecessor authority differs"
        )
    actual_plans_json = strict_json_bytes(
        [json.loads(extracted_plan_json_bytes(plan)) for plan in extracted_plans]
    )
    actual_comparison_ledger_json = strict_json_bytes(comparison_ledger)
    actual_method_proofs_json = strict_json_bytes(proofs)
    if (
        actual_plans_json != authority.extracted_plans_json
        or actual_comparison_ledger_json != authority.comparison_ledger_json
        or actual_method_proofs_json != authority.method_proofs_json
    ):
        raise ReadinessContractError(
            "source projection authority private ledger differs"
        )
    validate_source_report(
        source_report,
        public_document=public_document,
        method_proofs=proofs,
    )
    validate_projected_document(public_document)
    if not isinstance(predecessor_document, Mapping):
        raise ReadinessContractError("configured predecessor document is required")
    if source_report["status"] != "available":
        raise ReadinessContractError("projected source report is not available")
    source_document = public_document.get("document")
    source_sha256 = (
        source_document.get("sha256") if isinstance(source_document, Mapping) else None
    )
    if source_sha256 != source_report["source_sha256"]:
        raise ReadinessContractError("source report/public source hash differs")
    public_pages = public_document["pages"]
    report_pages = source_report["pages"]
    summary = public_document["processing"]["running_regions"]
    if (
        len(public_pages) != len(report_pages)
        or source_report["counts"]["page_count"] != len(public_pages)
        or summary["source_page_count"] != len(public_pages)
        or summary["candidate_count"]
        != source_report["counts"]["boundary_candidate_count"]
        or float(summary["extraction_ms"]) != float(source_report["extraction_ms"])
    ):
        raise ReadinessContractError("source projection page/candidate counts differ")
    validate_comparison_ledger(
        comparison_ledger,
        source_page_count=len(public_pages),
        expected_comparison_count=summary["comparison_count"],
    )
    if ir_document is not None:
        if not isinstance(predecessor_ir, Mapping):
            raise ReadinessContractError("configured predecessor IR is required")
        if ir_document.get("source_sha256") != source_sha256:
            raise ReadinessContractError("source report/IR source hash differs")
        validate_ir_bindings(ir_document, public_document=public_document)
    elif predecessor_ir is not None:
        raise ReadinessContractError("predecessor IR has no projected IR")

    extracted_descriptors = [
        item["running_region"]
        for page in public_pages
        for item in page.get("items", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("running_region"), Mapping)
        and item["running_region"].get("source_method")
        == "extracted_source_contribution"
    ]
    if len(extracted_descriptors) != len(extracted_plans):
        raise ReadinessContractError("extracted method plan coverage differs")
    validate_extracted_plan_ledger(extracted_plans)
    extracted_plan_by_descriptor = {
        descriptor["id"]: plan
        for descriptor, plan in zip(extracted_descriptors, extracted_plans)
    }

    used_boundary_candidates: set[str] = set()
    repetition_bindings: list[tuple[Mapping[str, Any], Mapping[str, Any], float]] = []
    descriptor_by_candidate_id: dict[str, Mapping[str, Any]] = {}
    eligible_boundary_candidates: set[str] = set()
    used_method_proofs: set[str] = set()
    for public_page, report_page in zip(public_pages, report_pages):
        if (
            public_page.get("page_index") != report_page["page_index"]
            or public_page.get("page_width") != report_page["page_width"]
            or public_page.get("page_height") != report_page["page_height"]
            or public_page.get("unit") != report_page["unit"]
        ):
            raise ReadinessContractError("source projection page geometry differs")
        identity = public_page["page_identity"]
        if identity["embedded_label"] != report_page["embedded_label"]:
            raise ReadinessContractError("source projection embedded label differs")
        if identity["display_source"] == "legacy_display_fallback":
            expected_source_object_id = (
                f"configured-predecessor:{source_sha256}:"
                f"page:{report_page['page_index']}:page_label"
            )
            if tuple(identity["evidence_source"]["source_object_ids"]) != (
                expected_source_object_id,
            ):
                raise ReadinessContractError(
                    "legacy fallback source object binding differs"
                )
        label_candidates = report_page["label_candidates"]
        eligible_label_candidates = [
            candidate
            for candidate in label_candidates
            if candidate["confidence"]
            == {
                "scope": "deterministic_rule",
                "score": 1.0,
                "unavailable_reason": None,
            }
            and not candidate["concern_codes"]
        ]
        detected = identity["detected_printed_label"]
        if len(eligible_label_candidates) == 1 and detected is None:
            raise ReadinessContractError(
                "unique source label candidate was silently downgraded"
            )
        if len(eligible_label_candidates) == 0 and detected is not None:
            raise ReadinessContractError("detected identity has no source candidate")
        if len(eligible_label_candidates) > 1 and (
            detected is not None
            or "page_identity_detected_label_ambiguous" not in identity["concern_codes"]
        ):
            raise ReadinessContractError(
                "ambiguous source labels did not select fallback"
            )
        if detected is not None:
            candidate_ids = identity["evidence_source"]["evidence_ids"]
            candidates = [
                candidate
                for candidate in eligible_label_candidates
                if candidate["id"] in candidate_ids
            ]
            if len(candidate_ids) != 1 or len(candidates) != 1:
                raise ReadinessContractError(
                    "detected identity source candidate is not unique"
                )
            candidate = candidates[0]
            if (
                candidate["id"] != candidate_ids[0]
                or candidate["visible_text"] != identity["visible_text"]
                or candidate["normalized_label"] != identity["detected_printed_label"]
                or _canonical_bbox(
                    candidate["bbox"], path="source_projection.label_candidate_bbox"
                )
                != _canonical_bbox(
                    identity["evidence_bbox"],
                    path="source_projection.identity_evidence_bbox",
                )
                or tuple(candidate["source_object_ids"])
                != tuple(identity["evidence_source"]["source_object_ids"])
                or candidate["source_method"] != identity["evidence_source"]["method"]
            ):
                raise ReadinessContractError(
                    "detected identity source candidate binding differs"
                )

        boundary_candidates = report_page["boundary_candidates"]
        eligible_boundary_candidates.update(
            candidate["id"]
            for candidate in boundary_candidates
            if candidate["disposition"] == "accepted"
        )
        for item in public_page.get("items", []):
            if not isinstance(item, Mapping) or not (
                set(item) & PUBLIC_RUNNING_REGION_KEYS
            ):
                continue
            descriptor = item["running_region"]
            matches = [
                candidate
                for candidate in boundary_candidates
                if candidate["public_item_id"] == descriptor["source_public_item_id"]
                and tuple(candidate["public_path"])
                == tuple(descriptor["source_public_path"])
                and candidate["element_id"] == descriptor["source_element_id"]
                and candidate["predecessor_type"] == descriptor["predecessor_type"]
                and _canonical_bbox(
                    candidate["bbox"], path="source_projection.candidate_bbox"
                )
                == _canonical_bbox(
                    descriptor["bbox"], path="source_projection.descriptor_bbox"
                )
                and candidate["bbox_id"] == descriptor["bbox_id"]
                and tuple(candidate["evidence_ids"])
                == tuple(descriptor["evidence_ids"])
                and tuple(candidate["source_object_ids"])
                == tuple(descriptor["source_object_ids"])
                and candidate["source_method"] == descriptor["source_method"]
            ]
            if len(matches) != 1 or matches[0]["id"] in used_boundary_candidates:
                raise ReadinessContractError(
                    "running descriptor source candidate is not unique"
                )
            if matches[0]["disposition"] != "accepted" or descriptor[
                "role"
            ] != expected_candidate_role(matches[0]):
                raise ReadinessContractError(
                    "running descriptor candidate admission/role differs"
                )
            proof = proofs.get(matches[0]["id"])
            predecessor_owner = resolve_public_path(
                predecessor_document, matches[0]["public_path"]
            )
            if (
                not isinstance(predecessor_owner, Mapping)
                or predecessor_owner.get("id") != matches[0]["public_item_id"]
                or predecessor_owner.get("type") != matches[0]["predecessor_type"]
            ):
                raise ReadinessContractError(
                    "source candidate predecessor owner binding differs"
                )
            validate_source_owner_admission(
                owner_kind=matches[0]["predecessor_type"],
                raw_layout_role=matches[0]["raw_layout_role"],
                source_method=matches[0]["source_method"],
                prior_semantic_owner=_has_prior_semantic_owner(predecessor_owner),
            )
            _validate_raw_layout_role_binding(
                matches[0],
                predecessor_owner,
                predecessor_ir=predecessor_ir,
            )
            _validate_navigation_source_text(matches[0], proof, predecessor_owner)
            extracted_plan = extracted_plan_by_descriptor.get(descriptor["id"])
            _validate_repetition_signature_binding(
                matches[0],
                predecessor_owner,
                label_candidates=label_candidates,
                required=True,
                source_text_override=(
                    extracted_plan.source_text if extracted_plan is not None else None
                ),
            )
            validate_boundary_method_proof(
                matches[0],
                proof,
                page_width=float(report_page["page_width"]),
                page_height=float(report_page["page_height"]),
                label_candidate_ids=[candidate["id"] for candidate in label_candidates],
                label_candidates=label_candidates,
                extracted_plan=extracted_plan,
                expected_repetition_page_indexes=descriptor["repetition_page_indexes"],
            )
            _validate_extracted_method_evidence_binding(
                matches[0],
                proof,
                descriptor,
                predecessor_owner,
                predecessor_ir=predecessor_ir,
                source_sha256=source_sha256,
                extracted_plan=extracted_plan,
                page_height=float(report_page["page_height"]),
                source_character_count=report_page["source_character_count"],
                source_word_count=report_page["source_word_count"],
            )
            if proof is not None:
                used_method_proofs.add(matches[0]["id"])
            used_boundary_candidates.add(matches[0]["id"])
            descriptor_by_candidate_id[matches[0]["id"]] = descriptor
            repetition_bindings.append(
                (descriptor, matches[0], float(report_page["page_height"]))
            )

    effective_candidates = [
        (report_page, candidate)
        for report_page in report_pages
        for candidate in report_page["boundary_candidates"]
        if candidate["disposition"] == "accepted"
        and _candidate_uses_effective_bottom(
            candidate,
            page_width=float(report_page["page_width"]),
            page_height=float(report_page["page_height"]),
            path="source_projection.effective_candidate",
        )
    ]
    if effective_candidates:
        if not isinstance(ir_document, Mapping) or not isinstance(
            predecessor_ir, Mapping
        ):
            raise ReadinessContractError("effective cluster IR custody is absent")
        predecessor_pages = predecessor_document.get("pages")
        ir_pages = ir_document.get("pages")
        predecessor_ir_pages = predecessor_ir.get("pages")
        if not all(
            isinstance(value, (list, tuple))
            for value in (predecessor_pages, ir_pages, predecessor_ir_pages)
        ):
            raise ReadinessContractError("effective cluster page custody is absent")
        predecessor_page_by_index = {
            page.get("page_index"): page
            for page in predecessor_pages
            if isinstance(page, Mapping)
        }
        ir_page_by_index = {
            page.get("page_index"): page
            for page in ir_pages
            if isinstance(page, Mapping)
        }
        predecessor_ir_page_by_index = {
            page.get("page_index"): page
            for page in predecessor_ir_pages
            if isinstance(page, Mapping)
        }
        ir_elements = {
            element.get("id"): element
            for element in ir_document.get("elements", [])
            if isinstance(element, Mapping)
        }
        predecessor_ir_elements = {
            element.get("id"): element
            for element in predecessor_ir.get("elements", [])
            if isinstance(element, Mapping)
        }
        ir_bboxes = {
            bbox.get("id"): bbox
            for bbox in ir_document.get("bboxes", [])
            if isinstance(bbox, Mapping)
        }
        canonical_page_by_index = {
            page.get("page_index"): page
            for page in public_document["canonical_presentation"]["pages"]
            if isinstance(page, Mapping)
        }
        public_page_by_index = {
            page.get("page_index"): page
            for page in public_pages
            if isinstance(page, Mapping)
        }
        validated_clusters: set[str] = set()
        for report_page, candidate in effective_candidates:
            cluster_proof = _effective_cluster_payload(
                candidate, proofs.get(candidate["id"])
            )
            if not isinstance(cluster_proof, Mapping):
                raise ReadinessContractError("effective cluster payload is absent")
            cluster_identity = sha256_json(cluster_proof)
            if cluster_identity in validated_clusters:
                continue
            page_index = report_page["page_index"]
            surfaces = (
                public_page_by_index.get(page_index),
                predecessor_page_by_index.get(page_index),
                canonical_page_by_index.get(page_index),
                ir_page_by_index.get(page_index),
                predecessor_ir_page_by_index.get(page_index),
            )
            if any(not isinstance(value, Mapping) for value in surfaces):
                raise ReadinessContractError("effective cluster page surface is absent")
            _validate_effective_cluster_projection_parity(
                cluster_proof,
                report_page=report_page,
                public_page=surfaces[0],
                predecessor_page=surfaces[1],
                canonical_page=surfaces[2],
                ir_page=surfaces[3],
                predecessor_ir_page=surfaces[4],
                ir_elements=ir_elements,
                predecessor_ir_elements=predecessor_ir_elements,
                ir_bboxes=ir_bboxes,
                accepted_descriptors=descriptor_by_candidate_id,
                proofs=proofs,
            )
            validated_clusters.add(cluster_identity)

    repeated_source_groups: dict[
        tuple[str, str], list[tuple[int, float, Mapping[str, Any]]]
    ] = {}
    for report_page in report_pages:
        for candidate in report_page["boundary_candidates"]:
            if candidate["disposition"] != "accepted":
                continue
            repeated_source_groups.setdefault(
                (candidate["boundary_band"], candidate["normalized_signature"]),
                [],
            ).append(
                (
                    report_page["page_index"],
                    float(report_page["page_height"]),
                    candidate,
                )
            )
    for members in repeated_source_groups.values():
        page_indexes = [page_index for page_index, _, _ in members]
        if len(members) < 2 or len(page_indexes) != len(set(page_indexes)):
            continue
        midpoints = [
            (float(candidate["bbox"]["y"]) + float(candidate["bbox"]["height"]) / 2)
            / page_height
            for _, page_height, candidate in members
        ]
        intervals = [
            (
                float(candidate["bbox"]["x"]),
                float(candidate["bbox"]["x"]) + float(candidate["bbox"]["width"]),
            )
            for _, _, candidate in members
        ]
        geometry_matches = max(midpoints) - min(midpoints) <= 0.02 + 1e-9
        common_overlap = max(
            0.0,
            min(right for _, right in intervals) - max(left for left, _ in intervals),
        )
        geometry_matches = geometry_matches and all(
            common_overlap / (right - left) >= 0.50 for left, right in intervals
        )
        if not geometry_matches:
            continue
        projected_members = [
            descriptor_by_candidate_id.get(candidate["id"])
            for _, _, candidate in members
        ]
        if any(descriptor is None for descriptor in projected_members) or any(
            descriptor["repetition_group_id"] is None
            for descriptor in projected_members
            if descriptor is not None
        ):
            raise ReadinessContractError(
                "eligible repeated source group was not projected"
            )
    validate_repetition_group_bindings(
        repetition_bindings,
        source_sha256=source_sha256,
    )
    if used_boundary_candidates != eligible_boundary_candidates:
        raise ReadinessContractError(
            "accepted boundary candidate/descriptor bijection differs"
        )
    if used_method_proofs != set(proofs):
        raise ReadinessContractError("unused boundary method proof differs")

    expected_concerns: dict[tuple[str, str], int] = {}

    def charge_concerns(codes: Sequence[str], source_ref: str) -> None:
        for code in codes:
            key = (source_ref, code)
            expected_concerns[key] = expected_concerns.get(key, 0) + 1

    charge_concerns(source_report["concern_codes"], "document")
    for report_page, public_page in zip(report_pages, public_pages):
        source_ref = f"page:{report_page['page_index']}"
        charge_concerns(report_page["concern_codes"], source_ref)
        for candidate in (
            *report_page["label_candidates"],
            *report_page["boundary_candidates"],
        ):
            charge_concerns(candidate["concern_codes"], source_ref)
        charge_concerns(public_page["page_identity"]["concern_codes"], source_ref)
        for item in public_page.get("items", []):
            if isinstance(item, Mapping) and isinstance(
                item.get("running_region"), Mapping
            ):
                charge_concerns(item["running_region"]["concern_codes"], source_ref)
    projected_concerns = public_document.get("running_region_concerns", [])
    actual_concerns = {
        (record["source_ref"], record["code"]): record for record in projected_concerns
    }
    if set(actual_concerns) != set(expected_concerns):
        raise ReadinessContractError("source/projected concern identity differs")
    for identity_key, occurrence_count in expected_concerns.items():
        record = actual_concerns[identity_key]
        expected_cap = (
            MAX_CONCERNS_PER_DOCUMENT
            if record["source_ref"] == "document"
            else MAX_CONCERNS_PER_PAGE
        )
        if (
            record["count"] != occurrence_count
            or record["cap"] != expected_cap
            or record["exception_class"] is not None
        ):
            raise ReadinessContractError("source/projected concern payload differs")

    strip_complete_running_region_sidecars(
        public_document,
        predecessor_document=predecessor_document,
        plans=extracted_plans,
        ir_document=ir_document,
        predecessor_ir=predecessor_ir,
    )


def validate_extracted_evidence_strip(
    projected_ir: Mapping[str, Any],
    stripped_ir: Mapping[str, Any],
    descriptors: Sequence[Mapping[str, Any]],
    *,
    projected_public: Mapping[str, Any],
    stripped_public: Mapping[str, Any],
    predecessor_public: Mapping[str, Any],
    predecessor_ir: Mapping[str, Any],
    plans: Sequence[ExtractedContributionPlan],
) -> None:
    """Prove a plan-aware exact inverse for every extracted contribution."""

    if any(
        not isinstance(value, Mapping)
        for value in (
            projected_ir,
            stripped_ir,
            projected_public,
            stripped_public,
            predecessor_public,
            predecessor_ir,
        )
    ):
        raise ReadinessContractError("extracted strip document differs")
    descriptor_ids: list[str] = []
    for descriptor in descriptors:
        validate_running_region(descriptor)
        if descriptor["source_method"] != "extracted_source_contribution":
            raise ReadinessContractError("evidence strip descriptor is not extracted")
        descriptor_ids.append(descriptor["id"])
    if len(descriptor_ids) != len(set(descriptor_ids)):
        raise ReadinessContractError("evidence strip descriptor is not unique")
    projected_descriptor_ids = [
        item["running_region"]["id"]
        for page in projected_public.get("pages", [])
        if isinstance(page, Mapping)
        for item in page.get("items", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("running_region"), Mapping)
        and item["running_region"].get("source_method")
        == "extracted_source_contribution"
    ]
    if descriptor_ids != projected_descriptor_ids:
        raise ReadinessContractError(
            "extracted strip descriptor coverage/order differs"
        )
    if strict_json_bytes(stripped_public) != strict_json_bytes(
        predecessor_public
    ) or strict_json_bytes(stripped_ir) != strict_json_bytes(predecessor_ir):
        raise ReadinessContractError("supplied stripped predecessor differs")
    derived = strip_complete_running_region_sidecars(
        projected_public,
        predecessor_document=predecessor_public,
        plans=plans,
        ir_document=projected_ir,
        predecessor_ir=predecessor_ir,
    )
    if strict_json_bytes(derived) != strict_json_bytes(stripped_public):
        raise ReadinessContractError("extracted derived public predecessor differs")


def _rebuild_canonical_views(page: dict[str, Any]) -> None:
    """Rebuild the four canonical views from ordered, non-omitted blocks."""

    for name, view in _canonical_page_views_from_blocks(page).items():
        page[name] = view


def _rebuild_canonical_document_views(canonical: dict[str, Any]) -> None:
    """Rebuild optional document views after reverse-projecting every page."""

    pages = canonical.get("pages")
    if not isinstance(pages, list) or any(
        not isinstance(page, Mapping) for page in pages
    ):
        raise ReadinessContractError("canonical inverse page coverage differs")
    view_names = ("full", "body", "header", "footer")
    present = {name for name in view_names if name in canonical}
    if not present:
        return
    if present != set(view_names):
        raise ReadinessContractError("canonical inverse document view coverage differs")
    for name, view in _canonical_document_views_from_pages(pages).items():
        canonical[name] = view


def _combined_extracted_residual(
    predecessor: str,
    plans: Sequence[ExtractedContributionPlan],
) -> str:
    predecessor_bytes = predecessor.encode("utf-8")
    intervals = sorted(
        interval for plan in plans for interval in plan.predecessor_intervals
    )
    if len(intervals) != len(set(intervals)) or any(
        left[1] >= right[0] for left, right in pairwise(intervals)
    ):
        raise ReadinessContractError("combined extracted intervals overlap/touch")
    parts: list[bytes] = []
    cursor = 0
    for start, end in intervals:
        parts.append(predecessor_bytes[cursor:start])
        cursor = end
    parts.append(predecessor_bytes[cursor:])
    try:
        residual = b"".join(parts).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReadinessContractError(
            "combined extracted residual is not UTF-8 aligned"
        ) from exc
    if not residual:
        raise ReadinessContractError("combined extracted residual is empty")
    return residual


def strip_complete_running_region_sidecars(
    document: Mapping[str, Any],
    *,
    predecessor_document: Mapping[str, Any],
    plans: Sequence[ExtractedContributionPlan] = (),
    ir_document: Mapping[str, Any] | None = None,
    predecessor_ir: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive and prove the exact configured predecessor across every projection."""

    if not isinstance(predecessor_document, Mapping):
        raise ReadinessContractError("configured predecessor document is required")
    validate_projected_document(document)
    if document["processing"]["running_regions"]["status"] != "projected":
        raise ReadinessContractError("only a projected US08 result can be stripped")
    if (ir_document is None) != (predecessor_ir is None):
        raise ReadinessContractError("projected/predecessor IR pair is incomplete")
    if ir_document is not None:
        if not isinstance(ir_document, Mapping) or not isinstance(
            predecessor_ir, Mapping
        ):
            raise ReadinessContractError("configured predecessor IR is required")
        validate_ir_bindings(ir_document, public_document=document)

    validate_extracted_plan_ledger(plans)
    descriptor_records: list[tuple[int, Mapping[str, Any], Mapping[str, Any]]] = []
    extracted_records: list[tuple[int, Mapping[str, Any], Mapping[str, Any]]] = []
    for page in document["pages"]:
        for item in page.get("items", []):
            if not isinstance(item, Mapping) or not isinstance(
                item.get("running_region"), Mapping
            ):
                continue
            descriptor = item["running_region"]
            record = (page["page_index"], item, descriptor)
            descriptor_records.append(record)
            if descriptor["source_method"] == "extracted_source_contribution":
                extracted_records.append(record)
    if len(extracted_records) != len(plans):
        raise ReadinessContractError("extracted plan/descriptor cardinality differs")
    plan_by_descriptor: dict[str, ExtractedContributionPlan] = {}
    for record, plan in zip(extracted_records, plans):
        page_index, item, descriptor = record
        if (
            plan.physical_page_index != page_index
            or plan.owner_public_item_id != descriptor["source_public_item_id"]
            or plan.owner_sha256_before != descriptor["predecessor_item_sha256"]
            or item.get("value") != plan.source_text
            or item.get("md") != plan.source_text
        ):
            raise ReadinessContractError(
                "extracted plan/descriptor order binding differs"
            )
        plan_by_descriptor[descriptor["id"]] = plan

    cleaned = deepcopy(dict(document))
    for page in cleaned["pages"]:
        page.pop("page_identity")
        retained_items: list[Any] = []
        for item in page.get("items", []):
            if not isinstance(item, dict):
                retained_items.append(item)
                continue
            keys = set(item) & PUBLIC_RUNNING_REGION_KEYS
            if not keys:
                retained_items.append(item)
                continue
            if keys != PUBLIC_RUNNING_REGION_KEYS:
                raise ReadinessContractError("partial running-region sidecar")
            descriptor = item["running_region"]
            if descriptor["source_method"] == "extracted_source_contribution":
                continue
            predecessor_type = descriptor["predecessor_type"]
            expected_hash = descriptor["predecessor_item_sha256"]
            for key in RUNNING_REGION_SIDECAR_FIELDS:
                item.pop(key)
            item["type"] = predecessor_type
            if sha256_json(_compact_public_item(item)) != expected_hash:
                raise ReadinessContractError("running-region strip hash differs")
            retained_items.append(item)
        page["items"] = retained_items

    projected_canonical = cleaned.get("canonical_presentation")
    predecessor_canonical = predecessor_document.get("canonical_presentation")
    projected_canonical_pages = (
        projected_canonical.get("pages")
        if isinstance(projected_canonical, Mapping)
        else None
    )
    predecessor_canonical_pages = (
        predecessor_canonical.get("pages")
        if isinstance(predecessor_canonical, Mapping)
        else None
    )
    if (
        not isinstance(projected_canonical_pages, list)
        or not isinstance(predecessor_canonical_pages, list)
        or len(projected_canonical_pages) != len(predecessor_canonical_pages)
    ):
        raise ReadinessContractError("canonical predecessor page coverage differs")
    predecessor_canonical_by_index = {
        page.get("page_index"): page
        for page in predecessor_canonical_pages
        if isinstance(page, Mapping)
    }
    if len(predecessor_canonical_by_index) != len(predecessor_canonical_pages):
        raise ReadinessContractError("canonical predecessor page identity differs")

    records_by_page: dict[int, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
    for page_index, item, descriptor in descriptor_records:
        records_by_page.setdefault(page_index, []).append((item, descriptor))

    for projected_page in projected_canonical_pages:
        if not isinstance(projected_page, dict):
            raise ReadinessContractError("projected canonical page differs")
        page_index = projected_page.get("page_index")
        predecessor_page = predecessor_canonical_by_index.get(page_index)
        if not isinstance(predecessor_page, Mapping) or predecessor_page.get(
            "page_id"
        ) != projected_page.get("page_id"):
            raise ReadinessContractError("canonical predecessor page binding differs")
        projected_page.pop("page_identity")
        projected_blocks = projected_page.get("blocks")
        predecessor_blocks = predecessor_page.get("blocks")
        if (
            not isinstance(projected_blocks, list)
            or not isinstance(predecessor_blocks, list)
            or any(
                not isinstance(block, Mapping)
                for block in (*projected_blocks, *predecessor_blocks)
            )
        ):
            raise ReadinessContractError("canonical predecessor blocks differ")
        predecessor_by_id = {block.get("id"): block for block in predecessor_blocks}
        if len(predecessor_by_id) != len(predecessor_blocks):
            raise ReadinessContractError("canonical predecessor block IDs differ")
        projected_by_id = {block.get("id"): block for block in projected_blocks}
        if len(projected_by_id) != len(projected_blocks):
            raise ReadinessContractError("projected canonical block IDs differ")

        extracted_groups: dict[
            str,
            list[
                tuple[Mapping[str, Any], Mapping[str, Any], ExtractedContributionPlan]
            ],
        ] = {}
        synthetic_block_ids: set[str] = set()
        for item, descriptor in records_by_page.get(page_index, []):
            synthetic_block_id = descriptor["canonical_block_id"]
            current_block = projected_by_id.get(synthetic_block_id)
            if not isinstance(current_block, Mapping):
                raise ReadinessContractError(
                    "projected canonical owner block is absent"
                )
            if descriptor["source_method"] != "extracted_source_contribution":
                predecessor_block = predecessor_by_id.get(synthetic_block_id)
                if not isinstance(predecessor_block, Mapping):
                    raise ReadinessContractError("direct predecessor block is absent")
                reconstructed = deepcopy(dict(current_block))
                if (
                    predecessor_block.get("scope") != "body"
                    or predecessor_block.get("primary_element_type")
                    != descriptor["predecessor_type"]
                ):
                    raise ReadinessContractError(
                        "direct predecessor block custody differs"
                    )
                reconstructed["scope"] = predecessor_block["scope"]
                reconstructed["primary_element_type"] = predecessor_block[
                    "primary_element_type"
                ]
                if reconstructed != predecessor_block:
                    raise ReadinessContractError("direct canonical predecessor changed")
                for offset, block in enumerate(projected_blocks):
                    if block.get("id") == synthetic_block_id:
                        projected_blocks[offset] = reconstructed
                        projected_by_id[synthetic_block_id] = reconstructed
                        break
                continue

            plan = plan_by_descriptor[descriptor["id"]]
            if (
                item.get("value") != plan.source_text
                or item.get("md") != plan.source_text
                or current_block.get("markdown") != plan.presentation_text
                or current_block.get("text") != plan.presentation_text
            ):
                raise ReadinessContractError("extracted synthetic presentation differs")
            extracted_groups.setdefault(descriptor["source_public_item_id"], []).append(
                (item, descriptor, plan)
            )
            synthetic_block_ids.add(synthetic_block_id)

        for owner_public_item_id, owner_records in extracted_groups.items():
            owner_plans = [record[2] for record in owner_records]
            predecessor_values = {plan.predecessor_canonical for plan in owner_plans}
            if len(predecessor_values) != 1:
                raise ReadinessContractError("extracted predecessor scalar differs")
            predecessor_value = next(iter(predecessor_values))
            owner_path = owner_records[0][1]["source_public_path"]
            projected_owner = resolve_public_path(document, owner_path)
            predecessor_owner = resolve_public_path(predecessor_document, owner_path)
            if (
                not isinstance(projected_owner, Mapping)
                or projected_owner != predecessor_owner
                or projected_owner.get("id") != owner_public_item_id
                or projected_owner.get("value") != predecessor_value
                or projected_owner.get("md") != predecessor_value
                or any(
                    plan.owner_sha256_after
                    != sha256_json(_compact_public_item(projected_owner))
                    for plan in owner_plans
                )
            ):
                raise ReadinessContractError(
                    "extracted fused owner predecessor differs"
                )
            predecessor_owner_blocks = [
                block
                for block in predecessor_blocks
                if block.get("text") == predecessor_value
                and block.get("markdown") == predecessor_value
                and block.get("scope") == "body"
                and block.get("omission_reason") is None
                and block.get("id") not in synthetic_block_ids
            ]
            if len(predecessor_owner_blocks) != 1:
                raise ReadinessContractError("extracted predecessor owner is ambiguous")
            predecessor_owner_block = predecessor_owner_blocks[0]
            owner_block_id = predecessor_owner_block["id"]
            residual_owner_block = projected_by_id.get(owner_block_id)
            expected_residual = _combined_extracted_residual(
                predecessor_value, owner_plans
            )
            if (
                not isinstance(residual_owner_block, Mapping)
                or set(residual_owner_block) != set(predecessor_owner_block)
                or residual_owner_block.get("text") != expected_residual
                or residual_owner_block.get("markdown") != expected_residual
            ):
                raise ReadinessContractError("extracted residual owner differs")
            reconstructed_owner = deepcopy(dict(residual_owner_block))
            reconstructed_owner["text"] = predecessor_value
            reconstructed_owner["markdown"] = predecessor_value
            if reconstructed_owner != predecessor_owner_block:
                raise ReadinessContractError("extracted owner metadata changed")
            for offset, block in enumerate(projected_blocks):
                if block.get("id") == owner_block_id:
                    projected_blocks[offset] = reconstructed_owner
                    projected_by_id[owner_block_id] = reconstructed_owner
                    break

        projected_page["blocks"] = [
            block
            for block in projected_blocks
            if block.get("id") not in synthetic_block_ids
        ]
        _rebuild_canonical_views(projected_page)

    if not isinstance(projected_canonical, dict):
        raise ReadinessContractError("projected canonical presentation differs")
    _rebuild_canonical_document_views(projected_canonical)

    processing = cleaned.get("processing")
    if not isinstance(processing, dict):
        raise ReadinessContractError("projected processing differs")
    processing.pop("running_regions")
    if not processing:
        cleaned.pop("processing")
    cleaned.pop("running_region_concerns", None)
    if strict_json_bytes(cleaned) != strict_json_bytes(predecessor_document):
        raise ReadinessContractError("derived public predecessor differs")

    if ir_document is not None:
        assert isinstance(predecessor_ir, Mapping)
        cleaned_ir = deepcopy(dict(ir_document))
        extracted_element_ids = {
            descriptor["source_element_id"] for _, _, descriptor in extracted_records
        }
        extracted_bbox_ids = {
            descriptor["bbox_id"] for _, _, descriptor in extracted_records
        }
        extracted_evidence_ids = {
            evidence_id
            for _, _, descriptor in extracted_records
            for evidence_id in descriptor["evidence_ids"]
        }
        for page in cleaned_ir.get("pages", []):
            if not isinstance(page, dict):
                raise ReadinessContractError("projected IR page differs")
            page.pop("page_identity")
            for field in ("element_ids", "presentation_element_ids"):
                if not isinstance(page.get(field), list):
                    raise ReadinessContractError("projected IR page backlinks differ")
                page[field] = [
                    element_id
                    for element_id in page[field]
                    if element_id not in extracted_element_ids
                ]
        retained_elements: list[Any] = []
        for element in cleaned_ir.get("elements", []):
            if not isinstance(element, dict):
                raise ReadinessContractError("projected IR element differs")
            descriptor = element.get("running_region")
            if isinstance(descriptor, Mapping):
                if descriptor["source_method"] == "extracted_source_contribution":
                    continue
                element.pop("running_region")
                element["type"] = descriptor["predecessor_type"]
            retained_elements.append(element)
        cleaned_ir["elements"] = retained_elements
        for collection, removed_ids in (
            ("bboxes", extracted_bbox_ids),
            ("evidence", extracted_evidence_ids),
        ):
            records = cleaned_ir.get(collection)
            if not isinstance(records, list):
                raise ReadinessContractError(
                    f"projected IR {collection} collection differs"
                )
            cleaned_ir[collection] = [
                record
                for record in records
                if isinstance(record, Mapping) and record.get("id") not in removed_ids
            ]
        if strict_json_bytes(cleaned_ir) != strict_json_bytes(predecessor_ir):
            raise ReadinessContractError("derived IR predecessor differs")
    return cleaned


def terminal_reentry_order(
    *, forms_enabled: bool, outlines_enabled: bool
) -> tuple[str, ...]:
    """Return reverse-strip, one-align, forward-replay ordering for US08."""

    events = ["snapshot", "validate_running_regions", "strip_running_regions"]
    if outlines_enabled:
        events.append("strip_outline")
    if forms_enabled:
        events.append("strip_forms")
    events.extend(("drop_canonical", "round_trip_once"))
    events.append("replay_forms" if forms_enabled else "skip_forms")
    events.append("replay_outline" if outlines_enabled else "skip_outline")
    events.extend(
        (
            "replay_running_regions",
            "validate_replay_identity",
            "validate_final_ir",
            "canonical_dry_run",
            "commit",
        )
    )
    return tuple(events)


@dataclass(frozen=True, slots=True)
class ProjectionTransactionResult:
    payload: dict[str, Any]
    committed: bool
    events: tuple[str, ...]


def _state_bundle_members(
    bundle: Mapping[str, Any], *, path: str
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Return the public/IR pair from the sole accepted witness state shape."""

    if not isinstance(bundle, Mapping):
        raise ReadinessContractError(f"{path} is not an object")
    _exact_keys(bundle, ("public", "ir"), path)
    public_document = bundle["public"]
    ir_document = bundle["ir"]
    if not isinstance(public_document, Mapping) or not isinstance(ir_document, Mapping):
        raise ReadinessContractError(f"{path} public/IR member differs")
    return public_document, ir_document


def _indexed_records(
    records: Any, *, collection: str, path: str
) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    if not isinstance(records, list) or any(
        not isinstance(record, Mapping) for record in records
    ):
        raise ReadinessContractError(f"{path} {collection} collection differs")
    identifiers = [record.get("id") for record in records]
    if any(
        not isinstance(identifier, str) or not identifier for identifier in identifiers
    ) or len(identifiers) != len(set(identifiers)):
        raise ReadinessContractError(f"{path} {collection} IDs differ")
    values = list(records)
    return values, {record["id"]: record for record in values}


def _validate_predecessor_state_bundle(
    bundle: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Validate a clean configured predecessor across public/canonical/IR surfaces."""

    public_document, ir_document = _state_bundle_members(
        bundle, path="predecessor_state"
    )
    public_pages = public_document.get("pages")
    canonical = public_document.get("canonical_presentation")
    canonical_pages = canonical.get("pages") if isinstance(canonical, Mapping) else None
    if (
        not isinstance(public_pages, list)
        or not public_pages
        or any(not isinstance(page, Mapping) for page in public_pages)
        or not isinstance(canonical, Mapping)
        or not isinstance(canonical_pages, list)
        or any(not isinstance(page, Mapping) for page in canonical_pages)
        or len(canonical_pages) != len(public_pages)
    ):
        raise ReadinessContractError(
            "predecessor public/canonical page coverage differs"
        )
    expected_indexes = list(range(1, len(public_pages) + 1))
    if [page.get("page_index") for page in public_pages] != expected_indexes or [
        page.get("page_index") for page in canonical_pages
    ] != expected_indexes:
        raise ReadinessContractError("predecessor physical page order differs")
    canonical_page_ids = [page.get("page_id") for page in canonical_pages]
    if any(
        not isinstance(page_id, str) or not page_id for page_id in canonical_page_ids
    ) or len(canonical_page_ids) != len(set(canonical_page_ids)):
        raise ReadinessContractError("predecessor canonical page IDs differ")
    canonical_block_ids: list[str] = []
    for page in canonical_pages:
        if "page_identity" in page:
            raise ReadinessContractError(
                "predecessor canonical page retains page identity"
            )
        _validate_canonical_page_views(page)
        canonical_block_ids.extend(block["id"] for block in page["blocks"])
    if len(canonical_block_ids) != len(set(canonical_block_ids)):
        raise ReadinessContractError("predecessor canonical block IDs differ")
    _validate_canonical_document_views(canonical, canonical_pages)

    for page in public_pages:
        if "page_identity" in page:
            raise ReadinessContractError(
                "predecessor public page retains page identity"
            )
        items = page.get("items")
        if not isinstance(items, list):
            raise ReadinessContractError("predecessor public items are not ordered")
        for item in items:
            if isinstance(item, Mapping) and set(item) & PUBLIC_RUNNING_REGION_KEYS:
                raise ReadinessContractError(
                    "predecessor public item retains running-region custody"
                )
    processing = public_document.get("processing")
    if isinstance(processing, Mapping) and "running_regions" in processing:
        raise ReadinessContractError("predecessor retains running-region processing")
    if "running_region_concerns" in public_document:
        raise ReadinessContractError("predecessor retains running-region concerns")

    ir_pages, ir_pages_by_id = _indexed_records(
        ir_document.get("pages"), collection="pages", path="predecessor IR"
    )
    elements, elements_by_id = _indexed_records(
        ir_document.get("elements"), collection="elements", path="predecessor IR"
    )
    bboxes, bboxes_by_id = _indexed_records(
        ir_document.get("bboxes"), collection="bboxes", path="predecessor IR"
    )
    evidence, evidence_by_id = _indexed_records(
        ir_document.get("evidence"), collection="evidence", path="predecessor IR"
    )
    coordinates, coordinates_by_id = _indexed_records(
        ir_document.get("coordinate_systems"),
        collection="coordinate_systems",
        path="predecessor IR",
    )
    if [page.get("page_index") for page in ir_pages] != expected_indexes or [
        page["id"] for page in ir_pages
    ] != canonical_page_ids:
        raise ReadinessContractError("predecessor public/canonical/IR pages differ")
    public_source = public_document.get("document")
    public_source_sha256 = (
        public_source.get("sha256") if isinstance(public_source, Mapping) else None
    )
    if (
        not _is_hash(public_source_sha256)
        or ir_document.get("source_sha256") != public_source_sha256
    ):
        raise ReadinessContractError("predecessor public/IR source hash differs")

    element_owner: dict[str, str] = {}
    for page in ir_pages:
        if "page_identity" in page:
            raise ReadinessContractError("predecessor IR page retains page identity")
        element_ids = page.get("element_ids")
        presentation_ids = page.get("presentation_element_ids")
        if (
            not isinstance(element_ids, list)
            or not isinstance(presentation_ids, list)
            or any(
                not isinstance(identifier, str) or identifier not in elements_by_id
                for identifier in (*element_ids, *presentation_ids)
            )
            or len(element_ids) != len(set(element_ids))
            or len(presentation_ids) != len(set(presentation_ids))
            or not set(presentation_ids) <= set(element_ids)
        ):
            raise ReadinessContractError("predecessor IR page backlinks differ")
        for element_id in element_ids:
            if element_id in element_owner:
                raise ReadinessContractError(
                    "predecessor IR element page ownership differs"
                )
            element_owner[element_id] = page["id"]
    if set(element_owner) != set(elements_by_id):
        raise ReadinessContractError("predecessor IR element coverage differs")

    for coordinate in coordinates:
        if (
            coordinate.get("page_id") not in ir_pages_by_id
            or coordinate.get("origin") != "top_left"
            or coordinate.get("unit") not in {"pt", "px"}
        ):
            raise ReadinessContractError(
                "predecessor IR coordinate-system custody differs"
            )
    for bbox in bboxes:
        coordinate = coordinates_by_id.get(bbox.get("coordinate_system_id"))
        if not isinstance(coordinate, Mapping):
            raise ReadinessContractError("predecessor IR bbox custody differs")
    for element in elements:
        element_id = element["id"]
        page_id = element.get("page_id")
        if page_id != element_owner[element_id] or "running_region" in element:
            raise ReadinessContractError("predecessor IR element custody differs")
        bbox_ids = element.get("bbox_ids")
        evidence_ids = element.get("evidence_ids")
        if (
            not isinstance(bbox_ids, list)
            or not isinstance(evidence_ids, list)
            or any(identifier not in bboxes_by_id for identifier in bbox_ids)
            or any(identifier not in evidence_by_id for identifier in evidence_ids)
        ):
            raise ReadinessContractError("predecessor IR element references differ")
        if any(
            coordinates_by_id[bboxes_by_id[bbox_id]["coordinate_system_id"]].get(
                "page_id"
            )
            != page_id
            for bbox_id in bbox_ids
        ):
            raise ReadinessContractError("predecessor IR element bbox page differs")
    for record in evidence:
        if (
            record.get("element_id") not in elements_by_id
            or record.get("bbox_id") not in bboxes_by_id
        ):
            raise ReadinessContractError("predecessor IR evidence custody differs")
    return public_document, ir_document


def _validate_projected_state_bundle(
    bundle: Mapping[str, Any],
    *,
    predecessor: Mapping[str, Any],
    plans: Sequence[ExtractedContributionPlan] = (),
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Validate a projected fixed point and its exact public/IR inverse."""

    predecessor_public, predecessor_ir = _validate_predecessor_state_bundle(predecessor)
    public_document, ir_document = _state_bundle_members(bundle, path="projected_state")
    validate_ir_bindings(ir_document, public_document=public_document)
    stripped_public = strip_complete_running_region_sidecars(
        public_document,
        predecessor_document=predecessor_public,
        plans=plans,
        ir_document=ir_document,
        predecessor_ir=predecessor_ir,
    )
    if strict_json_bytes(stripped_public) != strict_json_bytes(predecessor_public):
        raise ReadinessContractError("projected state public inverse differs")
    return public_document, ir_document


def _validate_staged_state_envelope(
    bundle: Mapping[str, Any], *, predecessor: Mapping[str, Any]
) -> None:
    """Require a complete public/canonical/IR envelope before failure injection."""

    staged_public, staged_ir = _state_bundle_members(bundle, path="staged_projection")
    predecessor_public, predecessor_ir = _state_bundle_members(
        predecessor, path="predecessor_state"
    )
    staged_canonical = staged_public.get("canonical_presentation")
    predecessor_canonical = predecessor_public.get("canonical_presentation")
    collections = (
        staged_public.get("pages"),
        staged_canonical.get("pages")
        if isinstance(staged_canonical, Mapping)
        else None,
        staged_ir.get("pages"),
    )
    expected_counts = (
        len(predecessor_public["pages"]),
        len(predecessor_canonical["pages"]),
        len(predecessor_ir["pages"]),
    )
    if any(
        not isinstance(records, list)
        or len(records) != expected
        or any(not isinstance(record, Mapping) for record in records)
        for records, expected in zip(collections, expected_counts)
    ):
        raise ReadinessContractError("staged projection page envelope differs")
    predecessor_sha256 = predecessor_public["document"]["sha256"]
    staged_source = staged_public.get("document")
    if (
        not isinstance(staged_source, Mapping)
        or staged_source.get("sha256") != predecessor_sha256
        or staged_ir.get("source_sha256") != predecessor_sha256
    ):
        raise ReadinessContractError("staged projection source envelope differs")


def _ir_page_closure(ir_document: Mapping[str, Any], *, page_id: str) -> dict[str, Any]:
    """Return every ordered IR record whose custody belongs to one page."""

    pages = ir_document["pages"]
    page_matches = [page for page in pages if page.get("id") == page_id]
    if len(page_matches) != 1:
        raise ReadinessContractError("IR page closure identity differs")
    page_elements = [
        element
        for element in ir_document["elements"]
        if element.get("page_id") == page_id
    ]
    element_ids = {element["id"] for element in page_elements}
    coordinate_ids = {
        coordinate["id"]
        for coordinate in ir_document["coordinate_systems"]
        if coordinate.get("page_id") == page_id
    }
    page_bboxes = [
        bbox
        for bbox in ir_document["bboxes"]
        if bbox.get("coordinate_system_id") in coordinate_ids
    ]
    bbox_ids = {bbox["id"] for bbox in page_bboxes}
    page_evidence = [
        record
        for record in ir_document["evidence"]
        if record.get("element_id") in element_ids or record.get("bbox_id") in bbox_ids
    ]
    return {
        "page": page_matches[0],
        "elements": page_elements,
        "bboxes": page_bboxes,
        "evidence": page_evidence,
        "coordinate_systems": [
            coordinate
            for coordinate in ir_document["coordinate_systems"]
            if coordinate["id"] in coordinate_ids
        ],
    }


def _without_page_identity(page: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(dict(page))
    cleaned.pop("page_identity", None)
    return cleaned


def _validate_page_local_fallback(
    fallback: Mapping[str, Any],
    *,
    projected: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    physical_page_index: int,
    plans: Sequence[ExtractedContributionPlan],
) -> None:
    # The detached candidate was validated against the complete plan ledger,
    # but a failed page must discard every synthetic extracted contribution
    # owned by that page.  Only unaffected-page plans remain applicable to the
    # committed fallback fixed point.
    fallback_plans = tuple(
        plan for plan in plans if plan.physical_page_index != physical_page_index
    )
    fallback_public, fallback_ir = _validate_projected_state_bundle(
        fallback, predecessor=predecessor, plans=fallback_plans
    )
    projected_public, projected_ir = _state_bundle_members(
        projected, path="projected_state"
    )
    predecessor_public, predecessor_ir = _state_bundle_members(
        predecessor, path="predecessor_state"
    )
    fallback_pages = fallback_public["pages"]
    projected_pages = projected_public["pages"]
    predecessor_pages = predecessor_public["pages"]
    matching_offsets = [
        offset
        for offset, page in enumerate(fallback_pages)
        if page.get("page_index") == physical_page_index
    ]
    if len(matching_offsets) != 1:
        raise ReadinessContractError("transaction page is unavailable")
    page_offset = matching_offsets[0]
    fallback_identity = fallback_pages[page_offset]["page_identity"]
    if fallback_identity["display_source"] == "detected_printed_label":
        raise ReadinessContractError("page rollback cannot promote detected identity")
    if any(
        isinstance(item, Mapping) and set(item) & PUBLIC_RUNNING_REGION_KEYS
        for item in fallback_pages[page_offset].get("items", [])
    ):
        raise ReadinessContractError("page rollback retains running-region projection")
    if (
        _without_page_identity(fallback_pages[page_offset])
        != predecessor_pages[page_offset]
    ):
        raise ReadinessContractError("page rollback public predecessor differs")

    fallback_canonical_pages = fallback_public["canonical_presentation"]["pages"]
    projected_canonical_pages = projected_public["canonical_presentation"]["pages"]
    predecessor_canonical_pages = predecessor_public["canonical_presentation"]["pages"]
    if (
        _without_page_identity(fallback_canonical_pages[page_offset])
        != predecessor_canonical_pages[page_offset]
    ):
        raise ReadinessContractError("page rollback canonical predecessor differs")
    fallback_ir_pages = fallback_ir["pages"]
    projected_ir_pages = projected_ir["pages"]
    predecessor_ir_pages = predecessor_ir["pages"]
    if (
        _without_page_identity(fallback_ir_pages[page_offset])
        != predecessor_ir_pages[page_offset]
    ):
        raise ReadinessContractError("page rollback IR predecessor differs")

    for offset in range(len(fallback_pages)):
        page_id = fallback_ir_pages[offset]["id"]
        if offset == page_offset:
            expected_ir = predecessor_ir
        else:
            if (
                fallback_pages[offset] != projected_pages[offset]
                or fallback_canonical_pages[offset] != projected_canonical_pages[offset]
                or fallback_ir_pages[offset] != projected_ir_pages[offset]
            ):
                raise ReadinessContractError(
                    "page rollback changed a non-failing page surface"
                )
            expected_ir = projected_ir
        fallback_closure = _ir_page_closure(fallback_ir, page_id=page_id)
        if offset == page_offset:
            fallback_closure = deepcopy(fallback_closure)
            fallback_closure["page"].pop("page_identity", None)
        if strict_json_bytes(fallback_closure) != strict_json_bytes(
            _ir_page_closure(expected_ir, page_id=page_id)
        ):
            raise ReadinessContractError("page rollback IR page closure differs")


@dataclass(frozen=True, slots=True)
class _ValidatedPredecessorStateBundle:
    payload: dict[str, Any]


def prepare_flag_off_witness(
    predecessor: Mapping[str, Any],
) -> _ValidatedPredecessorStateBundle:
    """Validate and snapshot full state before entering the flag-off guard."""

    snapshot = deepcopy(dict(predecessor))
    try:
        _validate_predecessor_state_bundle(snapshot)
    except Exception as exc:
        if isinstance(exc, ReadinessContractError):
            raise
        raise ReadinessContractError("flag-off predecessor validation failed") from exc
    return _ValidatedPredecessorStateBundle(snapshot)


def execute_flag_off_witness(
    predecessor: _ValidatedPredecessorStateBundle,
    *,
    feature_hooks: Sequence[Callable[[], Any]] = (),
) -> ProjectionTransactionResult:
    """Return prevalidated state without touching pages or any US08 hook."""

    if not isinstance(predecessor, _ValidatedPredecessorStateBundle):
        raise ReadinessContractError(
            "flag-off requires a prevalidated full-state snapshot"
        )
    # ``feature_hooks`` deliberately remains opaque and uniterated.  Synthetic
    # spies prove extraction, projection, validation, and page traversal are not
    # invoked after the constant-time guard has selected this branch.
    _ = feature_hooks

    return ProjectionTransactionResult(
        predecessor.payload, True, ("flag_off", "return_predecessor")
    )


def execute_transaction_witness(
    predecessor: Mapping[str, Any],
    *,
    projected_state: Mapping[str, Any],
    outcome: Literal[
        "success", "page_failure", "document_failure", "canonical_failure"
    ],
    physical_page_index: int = 1,
    fallback_state: Mapping[str, Any] | None = None,
    plans: Sequence[ExtractedContributionPlan] = (),
) -> ProjectionTransactionResult:
    """Execute full-state commit, page fallback, or atomic document rollback."""

    before = deepcopy(dict(predecessor))
    predecessor_public, predecessor_ir = _validate_predecessor_state_bundle(before)
    if (
        isinstance(physical_page_index, bool)
        or not isinstance(physical_page_index, int)
        or physical_page_index < 1
    ):
        raise ReadinessContractError("transaction page is unavailable")
    events = ("snapshot_document", "snapshot_page", "stage_detached_projection")
    try:
        _validate_staged_state_envelope(projected_state, predecessor=before)
        projected_public, _projected_ir = _validate_projected_state_bundle(
            projected_state, predecessor=before, plans=plans
        )
        if (
            sum(
                page.get("page_index") == physical_page_index
                for page in projected_public["pages"]
            )
            != 1
        ):
            raise ReadinessContractError("transaction page is unavailable")
    except Exception as exc:
        if outcome not in {"document_failure", "canonical_failure"}:
            if isinstance(exc, ReadinessContractError):
                raise
            raise ReadinessContractError(
                "staged transaction validation failed"
            ) from exc
    if outcome == "page_failure":
        if fallback_state is None:
            raise ReadinessContractError("page rollback requires a fallback state")
        _validate_page_local_fallback(
            fallback_state,
            projected=projected_state,
            predecessor=before,
            physical_page_index=physical_page_index,
            plans=plans,
        )
        return ProjectionTransactionResult(
            deepcopy(dict(fallback_state)),
            True,
            (*events, "discard_page_projection", "commit_fallback_state"),
        )
    if outcome in {"document_failure", "canonical_failure"}:
        restored_public = deepcopy(dict(predecessor_public))
        processing = restored_public.setdefault("processing", {})
        if not isinstance(processing, dict):
            raise ReadinessContractError("predecessor processing is not mutable")
        processing["running_regions"] = {
            "policy_id": POLICY_ID,
            "status": "failed_closed",
            "reason": "running_region_projection_failed_closed",
            **{key: 0 for key in PROCESSING_SUMMARY_FIELDS[3:16]},
            "concern_count": 1,
            "extraction_ms": 0.0,
            "projection_ms": 0.0,
            "total_ms": 0.0,
        }
        restored_public["running_region_concerns"] = [
            {
                "code": (
                    "running_region_canonical_custody_invalid"
                    if outcome == "canonical_failure"
                    else "running_region_projection_failed_closed"
                )
            }
        ]
        validate_projected_document(restored_public)
        restored = {
            "public": restored_public,
            "ir": deepcopy(dict(predecessor_ir)),
        }
        return ProjectionTransactionResult(
            restored,
            False,
            (
                *events,
                "canonical_dry_run"
                if outcome == "canonical_failure"
                else "validate_document",
                "restore_document",
                "emit_content_free_concern",
            ),
        )
    if outcome != "success":
        raise ReadinessContractError("transaction outcome differs")
    return ProjectionTransactionResult(
        deepcopy(dict(projected_state)),
        True,
        (*events, "validate_document", "canonical_dry_run", "commit"),
    )


@dataclass(frozen=True, slots=True)
class IdempotenceWitness:
    predecessor: Mapping[str, Any]
    projector: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    plans: Sequence[ExtractedContributionPlan] = ()

    def execute(self) -> tuple[dict[str, Any], dict[str, Any]]:
        predecessor_snapshot = deepcopy(dict(self.predecessor))
        _validate_predecessor_state_bundle(predecessor_snapshot)
        first = deepcopy(dict(self.projector(deepcopy(predecessor_snapshot))))
        _validate_projected_state_bundle(
            first, predecessor=predecessor_snapshot, plans=self.plans
        )
        second = deepcopy(dict(self.projector(deepcopy(first))))
        _validate_projected_state_bundle(
            second, predecessor=predecessor_snapshot, plans=self.plans
        )
        if strict_json_bytes(first) != strict_json_bytes(second):
            raise ReadinessContractError(
                "full public/IR/canonical projection is not idempotent"
            )
        return first, second


def source_alignment_selection_id(
    *,
    source_sha256: str,
    page_index: int,
    owner_id: str,
    original_text: str,
    selected_text: str,
) -> str:
    payload = "\x1f".join((str(page_index), owner_id, original_text, selected_text))
    digest = hashlib.sha256(f"{source_sha256}\x1e{payload}".encode()).hexdigest()[:24]
    return f"alignment-{digest}"


def source_alignment_evidence_id(
    prefix: str, *, source_sha256: str, parts: Sequence[object]
) -> str:
    """Reproduce the Phase-02 source-evidence stable-ID framing."""

    if not isinstance(prefix, str) or not prefix or not _is_hash(source_sha256):
        raise ReadinessContractError("source alignment evidence ID input differs")
    payload = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(f"{source_sha256}\x1e{payload}".encode()).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _source_alignment_bbox(value: Any, *, path: str) -> dict[str, float | str]:
    if not isinstance(value, Mapping):
        raise ReadinessContractError(f"{path} is not an object")
    _exact_keys(value, SOURCE_ALIGNMENT_EVIDENCE_BBOX_FIELDS, path)
    result = _canonical_bbox(value, path=path)
    if result["unit"] != "pt":
        raise ReadinessContractError(f"{path} unit differs")
    return result


def _source_alignment_bbox_union(
    characters: Sequence[Mapping[str, Any]], *, path: str
) -> dict[str, float | str]:
    boxes = [
        _source_alignment_bbox(character["bbox"], path=f"{path}.bbox")
        for character in characters
        if character.get("bbox") is not None
    ]
    if not boxes:
        raise ReadinessContractError(f"{path} geometry is absent")
    left = min(float(box["x"]) for box in boxes)
    top = min(float(box["y"]) for box in boxes)
    right = max(float(box["x"]) + float(box["width"]) for box in boxes)
    bottom = max(float(box["y"]) + float(box["height"]) for box in boxes)
    return {
        "x": round(left, 6),
        "y": round(top, 6),
        "width": round(right - left, 6),
        "height": round(bottom - top, 6),
        "unit": "pt",
    }


def _source_alignment_line_text(
    characters: Sequence[Mapping[str, Any]], *, raw: bool
) -> str:
    excluded = {
        "unsafe_unicode",
        "transparent_text",
        "white_icon_overlay",
        "uncorroborated_hyphen_sentinel",
    }
    field = "raw_text" if raw else "text"
    return "".join(
        str(character[field])
        for character in characters
        if character.get("excluded_reason") not in excluded
    ).strip(" ")


def _source_alignment_roles(
    characters: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    groups: list[list[Mapping[str, Any]]] = []
    active: list[Mapping[str, Any]] = []
    active_role: str | None = None
    for character in characters:
        role = character.get("role")
        if role is None:
            if active:
                groups.append(active)
                active = []
                active_role = None
            continue
        if active and (
            role != active_role
            or character["character_index"] > active[-1]["character_index"] + 1
        ):
            groups.append(active)
            active = []
        active.append(character)
        active_role = str(role)
    if active:
        groups.append(active)
    output: list[dict[str, Any]] = []
    for group in groups:
        output.append(
            {
                "role": group[0]["role"],
                "text": "".join(
                    str(character["text"]) for character in group if character["text"]
                ),
                "page_index": group[0]["page_index"],
                "bbox": _source_alignment_bbox_union(
                    group, path="terminal_alignment.source_role"
                ),
                "source_character_indexes": [
                    character["character_index"] for character in group
                ],
                "type1_evidence_ids": list(
                    dict.fromkeys(
                        evidence_id
                        for character in group
                        for evidence_id in character["type1_evidence_ids"]
                    )
                ),
            }
        )
    return output


_SOURCE_ALIGNMENT_CHARACTER_EXCLUSIONS = frozenset(
    {
        "ambiguous_type1_geometry",
        "conflicting_type1_geometry",
        "invalid_hyphen_sentinel_bbox",
        "spacing_diaeresis_composed",
        "transparent_text",
        "uncorroborated_hyphen_sentinel",
        "unsafe_unicode",
        "white_icon_overlay",
    }
)
_SOURCE_ALIGNMENT_TYPE1_RECOVERY = MappingProxyType(
    {
        **dict(
            zip(
                (
                    "zero.numr",
                    "one.numr",
                    "two.numr",
                    "three.numr",
                    "four.numr",
                    "five.numr",
                    "six.numr",
                    "seven.numr",
                    "eight.numr",
                    "nine.numr",
                ),
                "0123456789",
                strict=True,
            )
        ),
        "f_i": "fi",
        "f_l": "fl",
    }
)


def _validate_source_alignment_character_text(
    character: Mapping[str, Any],
    *,
    following: Mapping[str, Any] | None,
    type1_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    """Bind Phase-02 character strings to their extractor derivation."""

    raw_code_point = character["raw_code_point"]
    raw_text = character["raw_text"]
    text = character["text"]
    excluded_reason = character["excluded_reason"]
    type1_ids = character["type1_evidence_ids"]
    if raw_text != chr(raw_code_point) or raw_text in {"\r", "\n"}:
        raise ReadinessContractError(
            "source alignment character raw code-point binding differs"
        )
    if excluded_reason not in {None, *_SOURCE_ALIGNMENT_CHARACTER_EXCLUSIONS}:
        raise ReadinessContractError("source alignment character exclusion differs")
    if character["space_supported"] is True and (
        raw_code_point != 0x20
        or character["bbox"] is None
        or excluded_reason is not None
    ):
        raise ReadinessContractError(
            "source alignment supported-space derivation differs"
        )
    if raw_code_point != 0x20 and character["space_supported"] is True:
        raise ReadinessContractError(
            "source alignment supported-space code point differs"
        )

    if type1_ids:
        if len(type1_ids) != 1:
            raise ReadinessContractError(
                "source alignment character Type1 derivation differs"
            )
        glyph = type1_by_id[type1_ids[0]]
        if (
            text != glyph["recovered_text"]
            or character["role"] != glyph["role"]
            or excluded_reason is not None
            or character["pdfium_is_hyphen"] is True
        ):
            raise ReadinessContractError(
                "source alignment character Type1 text differs"
            )
        return

    if character["pdfium_is_hyphen"] is True:
        if character["bbox"] is None:
            valid = (
                text == ""
                and excluded_reason == "invalid_hyphen_sentinel_bbox"
                and not character["corroborating_line_ids"]
            )
        elif excluded_reason == "uncorroborated_hyphen_sentinel":
            valid = text == "" and not character["corroborating_line_ids"]
        else:
            valid = (
                excluded_reason is None
                and text == "-"
                and bool(character["corroborating_line_ids"])
            )
        if not valid:
            raise ReadinessContractError(
                "source alignment semantic-hyphen derivation differs"
            )
        return
    if excluded_reason in {
        "invalid_hyphen_sentinel_bbox",
        "uncorroborated_hyphen_sentinel",
    }:
        raise ReadinessContractError("source alignment non-hyphen exclusion differs")

    if excluded_reason == "spacing_diaeresis_composed":
        if raw_code_point != 0x00A8 or text != "":
            raise ReadinessContractError(
                "source alignment spacing-diaeresis mark differs"
            )
        return
    if text == raw_text:
        return

    # Phase-02's sole non-Type1 rewrite of a base character is NFC
    # composition with the immediately following spacing diaeresis.
    if (
        following is None
        or following["raw_code_point"] != 0x00A8
        or following["excluded_reason"] != "spacing_diaeresis_composed"
        or following["text"] != ""
        or raw_text not in "AEIOUYaeiouy"
        or character["bbox"] is None
        or following["bbox"] is None
        or character["font_ref"] is None
        or character["font_ref"] != following["font_ref"]
        or character["font_size"] is None
        or following["font_size"] is None
        or character["baseline"] is None
        or following["baseline"] is None
    ):
        raise ReadinessContractError(
            "source alignment character canonical text differs"
        )
    base_bbox = _source_alignment_bbox(
        character["bbox"], path="source_alignment.evidence.composed_base_bbox"
    )
    mark_bbox = _source_alignment_bbox(
        following["bbox"], path="source_alignment.evidence.composed_mark_bbox"
    )
    local_font_size = max(float(character["font_size"]), float(following["font_size"]))
    horizontal_overlap = max(
        min(
            float(base_bbox["x"]) + float(base_bbox["width"]),
            float(mark_bbox["x"]) + float(mark_bbox["width"]),
        )
        - max(float(base_bbox["x"]), float(mark_bbox["x"])),
        0.0,
    )
    mark_center_x = float(mark_bbox["x"]) + float(mark_bbox["width"]) / 2
    composed = unicodedata.normalize("NFC", raw_text + "\u0308")
    if (
        abs(float(character["baseline"]) - float(following["baseline"]))
        > 0.10 * local_font_size
        or horizontal_overlap < 0.80 * float(mark_bbox["width"])
        or not (
            float(base_bbox["x"])
            <= mark_center_x
            <= float(base_bbox["x"]) + float(base_bbox["width"])
        )
        or len(composed) != 1
        or unicodedata.category(composed) == "Cn"
        or text != composed
    ):
        raise ReadinessContractError("source alignment spacing-diaeresis base differs")


def _validate_source_alignment_evidence(
    evidence: Mapping[str, Any], *, expected_source_sha256: str
) -> dict[str, Any]:
    """Validate the exact Phase-02 source-evidence envelope and ownership."""

    if not isinstance(evidence, Mapping):
        raise ReadinessContractError("source alignment evidence is not an object")
    _exact_keys(evidence, SOURCE_ALIGNMENT_EVIDENCE_FIELDS, "source_alignment.evidence")
    if (
        evidence["schema_version"] != "1.0"
        or evidence["policy_id"] != SOURCE_ALIGNMENT_POLICY_ID
        or evidence["source_sha256"] != expected_source_sha256
        or evidence["usable"] is not True
        or evidence["refusal_code"] is not None
    ):
        raise ReadinessContractError("source alignment evidence identity differs")
    page_count = _index(
        evidence["page_count"],
        "source_alignment.evidence.page_count",
        maximum=MAX_PAGES_PER_DOCUMENT,
    )
    character_count = _count(
        evidence["character_count"],
        "source_alignment.evidence.character_count",
        maximum=MAX_SOURCE_CHARACTERS_PER_DOCUMENT,
    )
    line_count = _count(evidence["line_count"], "source_alignment.evidence.line_count")
    type1_count = _count(
        evidence["type1_glyph_count"],
        "source_alignment.evidence.type1_glyph_count",
    )
    _source_alignment_duration(
        evidence["elapsed_ms"], "source_alignment.evidence.elapsed_ms"
    )
    pages = evidence["pages"]
    type1_glyphs = evidence["type1_glyphs"]
    diagnostics = evidence["diagnostics"]
    if (
        not isinstance(pages, list)
        or len(pages) != page_count
        or not isinstance(type1_glyphs, list)
        or len(type1_glyphs) != type1_count
        or not isinstance(diagnostics, list)
        or any(not isinstance(value, Mapping) for value in diagnostics)
        or len(strict_json_bytes(evidence)) > MAX_REPORT_BYTES
    ):
        raise ReadinessContractError("source alignment evidence envelope differs")

    type1_by_id: dict[str, Mapping[str, Any]] = {}
    for occurrence_index, glyph in enumerate(type1_glyphs, start=1):
        if not isinstance(glyph, Mapping):
            raise ReadinessContractError("source alignment type1 evidence differs")
        _exact_keys(
            glyph,
            SOURCE_ALIGNMENT_EVIDENCE_TYPE1_FIELDS,
            "source_alignment.evidence.type1",
        )
        identifier = _string(glyph["id"], "source_alignment.evidence.type1.id")
        page_index = _index(
            glyph["page_index"],
            "source_alignment.evidence.type1.page_index",
            maximum=page_count,
        )
        bbox = _source_alignment_bbox(
            glyph["bbox"], path="source_alignment.evidence.type1.bbox"
        )
        font_ref = _string(
            glyph["font_ref"], "source_alignment.evidence.type1.font_ref"
        )
        font_object_id = glyph["font_object_id"]
        if font_object_id is not None:
            _count(
                font_object_id,
                "source_alignment.evidence.type1.font_object_id",
            )
        cid = _count(glyph["cid"], "source_alignment.evidence.type1.cid")
        glyph_name = _string(
            glyph["glyph_name"], "source_alignment.evidence.type1.glyph_name"
        )
        original_text = glyph["original_text"]
        recovered_text = glyph["recovered_text"]
        if (
            not isinstance(original_text, str)
            or not isinstance(recovered_text, str)
            or not 1 <= len(original_text) <= 2
            or glyph["role"] not in {"superscript", "ligature"}
            or glyph["method"] != "type1_encoding_differences"
            or _SOURCE_ALIGNMENT_TYPE1_RECOVERY.get(glyph_name) != recovered_text
            or (glyph["role"] == "superscript" and not glyph_name.endswith(".numr"))
            or (glyph["role"] == "ligature" and glyph_name not in {"f_i", "f_l"})
        ):
            raise ReadinessContractError("source alignment type1 payload differs")
        expected_id = source_alignment_evidence_id(
            "type1",
            source_sha256=expected_source_sha256,
            parts=(
                page_index,
                font_ref,
                cid,
                glyph_name,
                bbox["x"],
                bbox["y"],
                occurrence_index,
            ),
        )
        if identifier != expected_id or identifier in type1_by_id:
            raise ReadinessContractError("source alignment type1 identity differs")
        type1_by_id[identifier] = glyph

    pages_by_index: dict[int, Mapping[str, Any]] = {}
    characters_by_id: dict[str, Mapping[str, Any]] = {}
    lines_by_id: dict[str, Mapping[str, Any]] = {}
    page_character_total = 0
    page_line_total = 0
    character_line_owner: dict[str, str] = {}
    type1_character_owner: dict[str, str] = {}
    for expected_page_index, page in enumerate(pages, start=1):
        if not isinstance(page, Mapping):
            raise ReadinessContractError("source alignment evidence page differs")
        _exact_keys(
            page,
            SOURCE_ALIGNMENT_EVIDENCE_PAGE_FIELDS,
            "source_alignment.evidence.page",
        )
        page_index = _index(
            page["page_index"],
            "source_alignment.evidence.page.page_index",
            maximum=page_count,
        )
        if page_index != expected_page_index or page["unit"] != "pt":
            raise ReadinessContractError("source alignment evidence page order differs")
        for field in ("page_width", "page_height"):
            dimension = page[field]
            if (
                isinstance(dimension, bool)
                or not isinstance(dimension, (int, float))
                or not math.isfinite(float(dimension))
                or float(dimension) <= 0
            ):
                raise ReadinessContractError(
                    "source alignment evidence page geometry differs"
                )
        characters = page["characters"]
        lines = page["lines"]
        if (
            not isinstance(characters, list)
            or len(characters) > MAX_SOURCE_CHARACTERS_PER_PAGE
            or not isinstance(lines, list)
        ):
            raise ReadinessContractError(
                "source alignment evidence page collections differ"
            )
        page_characters: dict[str, Mapping[str, Any]] = {}
        prior_character_index = -1
        for character in characters:
            if not isinstance(character, Mapping):
                raise ReadinessContractError(
                    "source alignment character evidence differs"
                )
            _exact_keys(
                character,
                SOURCE_ALIGNMENT_EVIDENCE_CHARACTER_FIELDS,
                "source_alignment.evidence.character",
            )
            identifier = _string(
                character["id"], "source_alignment.evidence.character.id"
            )
            if character["page_index"] != page_index:
                raise ReadinessContractError("source alignment character page differs")
            character_index = _count(
                character["character_index"],
                "source_alignment.evidence.character.character_index",
            )
            raw_code_point = _count(
                character["raw_code_point"],
                "source_alignment.evidence.character.raw_code_point",
                maximum=0x10FFFF,
            )
            raw_text = character["raw_text"]
            text = character["text"]
            if (
                character_index <= prior_character_index
                or not isinstance(raw_text, str)
                or not isinstance(text, str)
                or len(raw_text) != 1
                or len(text) > 2
            ):
                raise ReadinessContractError(
                    "source alignment character order/text differs"
                )
            prior_character_index = character_index
            bbox = character["bbox"]
            canonical_bbox = (
                None
                if bbox is None
                else _source_alignment_bbox(
                    bbox, path="source_alignment.evidence.character.bbox"
                )
            )
            fill = character["fill_rgba"]
            if fill is not None and (
                not isinstance(fill, list)
                or len(fill) != 4
                or any(
                    isinstance(channel, bool)
                    or not isinstance(channel, int)
                    or not 0 <= channel <= 255
                    for channel in fill
                )
            ):
                raise ReadinessContractError("source alignment character fill differs")
            for field in ("font_size", "baseline"):
                scalar = character[field]
                if scalar is not None and (
                    isinstance(scalar, bool)
                    or not isinstance(scalar, (int, float))
                    or not math.isfinite(float(scalar))
                ):
                    raise ReadinessContractError(
                        "source alignment character metric differs"
                    )
            if (
                (
                    character["font_ref"] is not None
                    and not isinstance(character["font_ref"], str)
                )
                or not isinstance(character["pdfium_is_hyphen"], bool)
                or not isinstance(character["space_supported"], bool)
                or (
                    character["excluded_reason"] is not None
                    and not isinstance(character["excluded_reason"], str)
                )
                or character["role"] not in {None, "superscript"}
            ):
                raise ReadinessContractError(
                    "source alignment character metadata differs"
                )
            for field in ("type1_evidence_ids", "corroborating_line_ids"):
                references = character[field]
                if (
                    not isinstance(references, list)
                    or len(references) > MAX_REFERENCES_PER_RECORD
                    or len(references) != len(set(references))
                    or any(
                        not isinstance(reference, str) or not reference
                        for reference in references
                    )
                ):
                    raise ReadinessContractError(
                        "source alignment character references differ"
                    )
            if any(
                reference not in type1_by_id
                or type1_by_id[reference]["page_index"] != page_index
                for reference in character["type1_evidence_ids"]
            ):
                raise ReadinessContractError(
                    "source alignment character type1 ownership differs"
                )
            for reference in character["type1_evidence_ids"]:
                prior_owner = type1_character_owner.setdefault(reference, identifier)
                if prior_owner != identifier:
                    raise ReadinessContractError(
                        "source alignment type1 evidence has multiple owners"
                    )
            expected_id = source_alignment_evidence_id(
                "char",
                source_sha256=expected_source_sha256,
                parts=(
                    page_index,
                    character_index,
                    raw_code_point,
                    "" if canonical_bbox is None else canonical_bbox["x"],
                    "" if canonical_bbox is None else canonical_bbox["y"],
                ),
            )
            stable_id_matches = identifier == expected_id
            if raw_code_point == 0x20 and character["space_supported"] is True:
                # Phase-02 freezes the character ID before replacing PDFium's
                # space bbox with the geometry-derived supported gap bbox.
                stable_id_matches = bool(re.fullmatch(r"char-[0-9a-f]{24}", identifier))
            if not stable_id_matches or identifier in characters_by_id:
                raise ReadinessContractError(
                    "source alignment character identity differs"
                )
            page_characters[identifier] = character
            characters_by_id[identifier] = character

        for character_position, character in enumerate(characters):
            _validate_source_alignment_character_text(
                character,
                following=(
                    characters[character_position + 1]
                    if character_position + 1 < len(characters)
                    else None
                ),
                type1_by_id=type1_by_id,
            )

        for line_position, line in enumerate(lines):
            if not isinstance(line, Mapping):
                raise ReadinessContractError("source alignment line evidence differs")
            _exact_keys(
                line,
                SOURCE_ALIGNMENT_EVIDENCE_LINE_FIELDS,
                "source_alignment.evidence.line",
            )
            identifier = _string(line["id"], "source_alignment.evidence.line.id")
            if line["page_index"] != page_index:
                raise ReadinessContractError("source alignment line page differs")
            bbox = _source_alignment_bbox(
                line["bbox"], path="source_alignment.evidence.line.bbox"
            )
            character_ids = line["source_character_ids"]
            character_indexes = line["source_character_indexes"]
            type1_ids = line["type1_evidence_ids"]
            if (
                not isinstance(character_ids, list)
                or not character_ids
                or len(character_ids) != len(set(character_ids))
                or any(reference not in page_characters for reference in character_ids)
                or not isinstance(character_indexes, list)
                or not isinstance(type1_ids, list)
                or len(type1_ids) != len(set(type1_ids))
                or any(reference not in type1_by_id for reference in type1_ids)
                or not isinstance(line["has_unsafe_character"], bool)
                or not isinstance(line["terminal_semantic_hyphen"], bool)
            ):
                raise ReadinessContractError("source alignment line references differ")
            ordered = [page_characters[reference] for reference in character_ids]
            expected_indexes = [value["character_index"] for value in ordered]
            expected_type1_ids = list(
                dict.fromkeys(
                    reference
                    for value in ordered
                    for reference in value["type1_evidence_ids"]
                )
            )
            expected_text = _source_alignment_line_text(ordered, raw=False)
            expected_raw_text = _source_alignment_line_text(ordered, raw=True)
            expected_bbox = _source_alignment_bbox_union(
                ordered, path="source_alignment.evidence.line"
            )
            unsafe = any(
                value["excluded_reason"]
                in {
                    "unsafe_unicode",
                    "invalid_hyphen_sentinel_bbox",
                    "uncorroborated_hyphen_sentinel",
                    "ambiguous_type1_geometry",
                    "conflicting_type1_geometry",
                }
                for value in ordered
            )
            nonspace = [
                value
                for value in ordered
                if value["text"]
                and value["text"] != " "
                and value["excluded_reason"] is None
            ]
            terminal_semantic = bool(
                nonspace
                and nonspace[-1]["pdfium_is_hyphen"] is True
                and nonspace[-1]["text"] == "-"
            )
            expected_id = source_alignment_evidence_id(
                "line",
                source_sha256=expected_source_sha256,
                parts=(
                    page_index,
                    line_position,
                    expected_text,
                    bbox["x"],
                    bbox["y"],
                ),
            )
            if (
                line["text"] != expected_text
                or line["raw_text"] != expected_raw_text
                or bbox != expected_bbox
                or character_indexes != expected_indexes
                or type1_ids != expected_type1_ids
                or line["has_unsafe_character"] is not unsafe
                or line["terminal_semantic_hyphen"] is not terminal_semantic
                or identifier != expected_id
                or identifier in lines_by_id
            ):
                raise ReadinessContractError("source alignment line derivation differs")
            for character_id in character_ids:
                if character_id in character_line_owner:
                    raise ReadinessContractError(
                        "source alignment character has multiple line owners"
                    )
                character_line_owner[character_id] = identifier
            lines_by_id[identifier] = line
        pages_by_index[page_index] = page
        page_character_total += len(characters)
        page_line_total += len(lines)

    if page_character_total != character_count or page_line_total != line_count:
        raise ReadinessContractError("source alignment evidence counts differ")
    for character in characters_by_id.values():
        if any(
            reference not in lines_by_id
            for reference in character["corroborating_line_ids"]
        ):
            raise ReadinessContractError("source alignment corroborating line differs")
    return {
        "pages": pages_by_index,
        "characters": characters_by_id,
        "lines": lines_by_id,
        "type1": type1_by_id,
    }


def _explicit_ir_public_owner_ids(element: Mapping[str, Any]) -> frozenset[str]:
    """Return only explicit public-owner IDs carried by one IR element."""

    owner_ids: set[str] = set()
    direct_owner_id = element.get("source_public_item_id")
    if isinstance(direct_owner_id, str) and direct_owner_id:
        owner_ids.add(direct_owner_id)
    properties = element.get("properties")
    if isinstance(properties, Mapping):
        property_owner_id = properties.get("source_public_item_id")
        if isinstance(property_owner_id, str) and property_owner_id:
            owner_ids.add(property_owner_id)
        legacy_item = properties.get("legacy_item")
        if isinstance(legacy_item, Mapping):
            legacy_owner_id = legacy_item.get("id")
            if isinstance(legacy_owner_id, str) and legacy_owner_id:
                owner_ids.add(legacy_owner_id)
    return frozenset(owner_ids)


def _source_alignment_owner_bindings(
    public_document: Mapping[str, Any], ir_document: Mapping[str, Any]
) -> bytes:
    """Freeze explicit public-ID -> IR-ID -> canonical-block ownership."""

    ir_elements_by_page: dict[str, list[Mapping[str, Any]]] = {}
    for element in ir_document["elements"]:
        ir_elements_by_page.setdefault(element["page_id"], []).append(element)
    canonical_pages = public_document["canonical_presentation"]["pages"]
    bindings: list[dict[str, Any]] = []
    binding_keys: set[tuple[int, str]] = set()
    claimed_ir_ids: set[str] = set()
    claimed_block_ids: set[str] = set()
    for page_offset, (public_page, canonical_page) in enumerate(
        zip(public_document["pages"], canonical_pages, strict=True)
    ):
        page_id = canonical_page["page_id"]
        page_index = public_page["page_index"]
        for item_offset, item in enumerate(public_page["items"]):
            if not isinstance(item, Mapping):
                continue
            public_item_id = item.get("id")
            if not isinstance(public_item_id, str) or not public_item_id:
                continue
            element_matches = [
                element
                for element in ir_elements_by_page.get(page_id, [])
                if public_item_id in _explicit_ir_public_owner_ids(element)
            ]
            if not element_matches:
                continue
            if len(element_matches) != 1:
                raise ReadinessContractError(
                    "source alignment explicit IR owner is ambiguous"
                )
            element_id = element_matches[0]["id"]
            block_matches = [
                block
                for block in canonical_page["blocks"]
                if block.get("primary_element_id") == element_id
            ]
            if len(block_matches) != 1:
                raise ReadinessContractError(
                    "source alignment explicit canonical owner is ambiguous"
                )
            binding_key = (page_index, public_item_id)
            canonical_block_id = block_matches[0]["id"]
            if (
                binding_key in binding_keys
                or element_id in claimed_ir_ids
                or canonical_block_id in claimed_block_ids
                or len(bindings) >= MAX_RUNNING_REGIONS_PER_DOCUMENT
            ):
                raise ReadinessContractError(
                    "source alignment explicit owner custody is shared"
                )
            binding_keys.add(binding_key)
            claimed_ir_ids.add(element_id)
            claimed_block_ids.add(canonical_block_id)
            bindings.append(
                {
                    "page_index": page_index,
                    "page_offset": page_offset,
                    "item_offset": item_offset,
                    "public_item_id": public_item_id,
                    "ir_element_id": element_id,
                    "canonical_block_id": canonical_block_id,
                }
            )
    return strict_json_bytes({"bindings": bindings})


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class _ValidatedSourceAlignmentEvidence:
    """Opaque, identity-authorized result of fixed production extraction."""

    source_sha256: str
    predecessor_sha256: str
    evidence_json: bytes = dataclass_field(repr=False)
    owner_bindings_json: bytes = dataclass_field(repr=False)

    def __new__(cls) -> Self:
        raise ReadinessContractError(
            "source alignment evidence authority must be factory-issued"
        )


MAX_LIVE_SOURCE_ALIGNMENT_AUTHORITIES = 8
_ISSUED_SOURCE_ALIGNMENT_AUTHORITIES: dict[
    int,
    tuple[
        weakref.ReferenceType[_ValidatedSourceAlignmentEvidence],
        bytes,
    ],
] = {}


def _source_alignment_authority_fingerprint(
    authority: _ValidatedSourceAlignmentEvidence,
) -> bytes:
    return hashlib.sha256(
        b"\x1e".join(
            (
                authority.source_sha256.encode(),
                authority.predecessor_sha256.encode(),
                authority.evidence_json,
                authority.owner_bindings_json,
            )
        )
    ).digest()


def _require_issued_source_alignment_authority(
    authority: Any,
) -> _ValidatedSourceAlignmentEvidence:
    if not isinstance(authority, _ValidatedSourceAlignmentEvidence):
        raise ReadinessContractError("terminal alignment evidence authority differs")
    try:
        issued = _ISSUED_SOURCE_ALIGNMENT_AUTHORITIES.get(id(authority))
        if (
            issued is None
            or issued[0]() is not authority
            or issued[1] != _source_alignment_authority_fingerprint(authority)
        ):
            raise ReadinessContractError(
                "terminal alignment evidence authority was not factory-issued"
            )
    except AttributeError as exc:
        raise ReadinessContractError(
            "terminal alignment evidence authority is uninitialized"
        ) from exc
    return authority


def _issue_source_alignment_authority(
    *,
    source_sha256: str,
    predecessor_sha256: str,
    evidence_json: bytes,
    owner_bindings_json: bytes,
) -> _ValidatedSourceAlignmentEvidence:
    if len(_ISSUED_SOURCE_ALIGNMENT_AUTHORITIES) >= (
        MAX_LIVE_SOURCE_ALIGNMENT_AUTHORITIES
    ):
        raise ReadinessContractError(
            "source alignment evidence authority registry is full"
        )
    authority = object.__new__(_ValidatedSourceAlignmentEvidence)
    object.__setattr__(authority, "source_sha256", source_sha256)
    object.__setattr__(authority, "predecessor_sha256", predecessor_sha256)
    object.__setattr__(authority, "evidence_json", evidence_json)
    object.__setattr__(authority, "owner_bindings_json", owner_bindings_json)
    authority_id = id(authority)

    def revoke(reference: weakref.ReferenceType[Any]) -> None:
        current = _ISSUED_SOURCE_ALIGNMENT_AUTHORITIES.get(authority_id)
        if current is not None and current[0] is reference:
            _ISSUED_SOURCE_ALIGNMENT_AUTHORITIES.pop(authority_id, None)

    reference = weakref.ref(authority, revoke)
    _ISSUED_SOURCE_ALIGNMENT_AUTHORITIES[authority_id] = (
        reference,
        _source_alignment_authority_fingerprint(authority),
    )
    return authority


def _source_alignment_evidence_semantic_payload(
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    payload = deepcopy(dict(evidence))
    payload["elapsed_ms"] = 0.0
    return payload


_SOURCE_ALIGNMENT_OWNER_BINDING_FIELDS = (
    "page_index",
    "page_offset",
    "item_offset",
    "public_item_id",
    "ir_element_id",
    "canonical_block_id",
)


def _source_alignment_owner_binding_index(
    authority: _ValidatedSourceAlignmentEvidence,
) -> dict[tuple[int, str], Mapping[str, Any]]:
    try:
        payload = json.loads(authority.owner_bindings_json)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ReadinessContractError(
            "source alignment owner authority is malformed"
        ) from exc
    if not isinstance(payload, Mapping) or set(payload) != {"bindings"}:
        raise ReadinessContractError(
            "source alignment owner authority envelope differs"
        )
    bindings = payload["bindings"]
    if (
        not isinstance(bindings, list)
        or len(bindings) > MAX_RUNNING_REGIONS_PER_DOCUMENT
    ):
        raise ReadinessContractError("source alignment owner authority count differs")
    output: dict[tuple[int, str], Mapping[str, Any]] = {}
    prior_position = (-1, -1)
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise ReadinessContractError(
                "source alignment owner authority binding differs"
            )
        _exact_keys(
            binding,
            _SOURCE_ALIGNMENT_OWNER_BINDING_FIELDS,
            "source_alignment.owner_binding",
        )
        page_index = _index(
            binding["page_index"],
            "source_alignment.owner_binding.page_index",
            maximum=MAX_PAGES_PER_DOCUMENT,
        )
        page_offset = _count(
            binding["page_offset"],
            "source_alignment.owner_binding.page_offset",
        )
        item_offset = _count(
            binding["item_offset"],
            "source_alignment.owner_binding.item_offset",
        )
        public_item_id = _string(
            binding["public_item_id"],
            "source_alignment.owner_binding.public_item_id",
        )
        _string(
            binding["ir_element_id"],
            "source_alignment.owner_binding.ir_element_id",
        )
        _string(
            binding["canonical_block_id"],
            "source_alignment.owner_binding.canonical_block_id",
        )
        if (page_offset, item_offset) <= prior_position:
            raise ReadinessContractError(
                "source alignment owner authority order differs"
            )
        prior_position = (page_offset, item_offset)
        key = (page_index, public_item_id)
        if key in output:
            raise ReadinessContractError(
                "source alignment owner authority identity differs"
            )
        output[key] = binding
    return output


def _validate_source_alignment_predecessor_geometry(
    evidence: Mapping[str, Any], public_document: Mapping[str, Any]
) -> None:
    if evidence["page_count"] != len(public_document["pages"]):
        raise ReadinessContractError(
            "source alignment evidence/predecessor page coverage differs"
        )
    for source_page, public_page in zip(
        evidence["pages"], public_document["pages"], strict=True
    ):
        if (
            source_page["page_index"] != public_page.get("page_index")
            or float(source_page["page_width"])
            != float(public_page.get("page_width", -1))
            or float(source_page["page_height"])
            != float(public_page.get("page_height", -1))
            or source_page["unit"] != public_page.get("unit")
        ):
            raise ReadinessContractError(
                "source alignment evidence/predecessor geometry differs"
            )


def prepare_source_alignment_evidence(
    configured_predecessor: Mapping[str, Any], source_pdf_bytes: bytes
) -> _ValidatedSourceAlignmentEvidence:
    """Derive and freeze Phase-02 evidence from exact configured PDF bytes."""

    if not isinstance(source_pdf_bytes, bytes):
        raise ReadinessContractError(
            "source alignment evidence requires exact PDF bytes"
        )
    if not source_pdf_bytes or len(source_pdf_bytes) > MAX_SOURCE_PDF_BYTES:
        raise ReadinessContractError(
            "source alignment evidence PDF bytes exceed the boundary"
        )
    if len(_ISSUED_SOURCE_ALIGNMENT_AUTHORITIES) >= (
        MAX_LIVE_SOURCE_ALIGNMENT_AUTHORITIES
    ):
        raise ReadinessContractError(
            "source alignment evidence authority registry is full"
        )
    predecessor = deepcopy(dict(configured_predecessor))
    public_document, ir_document = _validate_predecessor_state_bundle(predecessor)
    source_sha256 = hashlib.sha256(source_pdf_bytes).hexdigest()
    if source_sha256 != public_document["document"]["sha256"]:
        raise ReadinessContractError(
            "source alignment PDF/configured source hash differs"
        )

    extracted_reports: list[dict[str, Any]] = []
    for _run in range(2):
        try:
            report = _extract_phase02_source_text_evidence(source_pdf_bytes)
            evidence = report.to_dict()
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            raise ReadinessContractError(
                "fixed Phase-02 source extraction failed"
            ) from exc
        _validate_source_alignment_evidence(
            evidence, expected_source_sha256=source_sha256
        )
        _validate_source_alignment_predecessor_geometry(evidence, public_document)
        extracted_reports.append(evidence)
    if strict_json_bytes(
        _source_alignment_evidence_semantic_payload(extracted_reports[0])
    ) != strict_json_bytes(
        _source_alignment_evidence_semantic_payload(extracted_reports[1])
    ):
        raise ReadinessContractError(
            "fixed Phase-02 source extraction is nondeterministic"
        )

    return _issue_source_alignment_authority(
        source_sha256=source_sha256,
        predecessor_sha256=sha256_json(predecessor),
        evidence_json=strict_json_bytes(extracted_reports[0]),
        owner_bindings_json=_source_alignment_owner_bindings(
            public_document, ir_document
        ),
    )


def _is_table_owned_source_suppression(selection: Mapping[str, Any]) -> bool:
    return (
        selection.get("terminal_reason")
        == SOURCE_ALIGNMENT_TABLE_OWNED_REASON
    )


def source_alignment_ocr_contributor_id(value: Mapping[str, Any]) -> str:
    """Recompute the full source-bound OCR contributor identifier."""

    if not isinstance(value, Mapping):
        raise ReadinessContractError(
            "terminal table-owned OCR contributor is not an object"
        )
    _exact_keys(
        value,
        SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_FIELDS,
        "terminal_alignment.selection.ocr_contributor",
    )
    payload = {
        field: value[field]
        for field in SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_FIELDS
        if field != "id"
    }
    return "ocr-contributor-" + hashlib.sha256(
        strict_json_bytes(payload)
    ).hexdigest()


def _table_owned_ocr_contributor(
    selection: Mapping[str, Any],
    *,
    expected_source_sha256: str | None = None,
) -> Mapping[str, Any]:
    """Validate retained OCR lineage for one table-owned suppression."""

    rejected = selection.get("rejected_ocr_alternative")
    if not isinstance(rejected, Mapping):
        raise ReadinessContractError(
            "terminal table-owned OCR alternative is absent"
        )
    contributor = rejected.get("ocr_contributor")
    if not isinstance(contributor, Mapping):
        raise ReadinessContractError(
            "terminal table-owned OCR contributor is absent"
        )
    _exact_keys(
        contributor,
        SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_FIELDS,
        "terminal_alignment.selection.ocr_contributor",
    )
    source_document_identity = contributor["source_document_identity"]
    page_index = _index(
        contributor["page_index"],
        "terminal_alignment.selection.ocr_contributor.page_index",
        maximum=MAX_PAGES_PER_DOCUMENT,
    )
    _count(
        contributor["region_object_index"],
        "terminal_alignment.selection.ocr_contributor.region_object_index",
    )
    _count(
        contributor["line_index"],
        "terminal_alignment.selection.ocr_contributor.line_index",
    )
    region_origin = contributor["region_origin"]
    ocr_pass = contributor["ocr_pass"]
    if (
        contributor["schema_version"]
        != SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_SCHEMA_VERSION
        or contributor["policy_id"]
        != SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_POLICY_ID
        or not _is_hash(source_document_identity)
        or (
            expected_source_sha256 is not None
            and source_document_identity != expected_source_sha256
        )
        or page_index != selection.get("page_index")
        or not isinstance(region_origin, str)
        or not region_origin
        or len(region_origin) > 128
        or contributor["region_role"] != "page_source"
        or not isinstance(ocr_pass, str)
        or not ocr_pass
        or len(ocr_pass) > 128
        or contributor["coordinate_unit"] != "pt"
    ):
        raise ReadinessContractError(
            "terminal table-owned OCR contributor identity differs"
        )
    contributor_bbox = _source_alignment_bbox(
        contributor["bbox"],
        path="terminal_alignment.selection.ocr_contributor.bbox",
    )
    owner_bbox = _source_alignment_bbox(
        selection.get("owner_bbox"),
        path="terminal_alignment.selection.owner_bbox",
    )
    rejected_bbox = _source_alignment_bbox(
        rejected.get("bbox"),
        path="terminal_alignment.selection.rejected_ocr_alternative.bbox",
    )
    raw_text = contributor["raw_text"]
    confidence = contributor["confidence"]
    if (
        contributor_bbox != owner_bbox
        or rejected_bbox != owner_bbox
        or not isinstance(raw_text, str)
        or not raw_text
        or len(raw_text) > 4_096
        or _source_alignment_skeleton(raw_text)
        != _source_alignment_skeleton(selection.get("original_text", ""))
        or not isinstance(confidence, float)
        or not math.isfinite(confidence)
        or not 0.0 <= confidence <= 1.0
        or rejected.get("confidence") != confidence
        or rejected.get("text") != selection.get("original_text")
        or rejected.get("source") != "ocr"
        or contributor["id"] != source_alignment_ocr_contributor_id(contributor)
    ):
        raise ReadinessContractError(
            "terminal table-owned OCR contributor proof differs"
        )
    return contributor


def _table_owned_canonical_owner(
    selection: Mapping[str, Any],
    *,
    expected_source_sha256: str | None = None,
) -> Mapping[str, Any]:
    """Validate the closed public provenance link for one removed OCR owner."""

    rejected = selection.get("rejected_ocr_alternative")
    if not isinstance(rejected, Mapping):
        raise ReadinessContractError(
            "terminal table-owned OCR alternative is absent"
        )
    _exact_keys(
        rejected,
        SOURCE_ALIGNMENT_TABLE_OWNED_REJECTED_OCR_FIELDS,
        "terminal_alignment.selection.rejected_ocr_alternative",
    )
    _table_owned_ocr_contributor(
        selection,
        expected_source_sha256=expected_source_sha256,
    )
    canonical_owner = rejected["canonical_owner"]
    if not isinstance(canonical_owner, Mapping):
        raise ReadinessContractError(
            "terminal table-owned canonical owner is absent"
        )
    _exact_keys(
        canonical_owner,
        SOURCE_ALIGNMENT_TABLE_OWNED_CANONICAL_OWNER_FIELDS,
        "terminal_alignment.selection.canonical_owner",
    )
    if (
        canonical_owner["policy_id"]
        != SOURCE_ALIGNMENT_TABLE_OWNED_POLICY_ID
        or canonical_owner["suppression_reason"]
        != SOURCE_ALIGNMENT_TABLE_OWNED_REASON
        or canonical_owner["page_index"] != selection.get("page_index")
        or canonical_owner["coordinate_unit"] != "pt"
        or rejected.get("reason") != SOURCE_ALIGNMENT_TABLE_OWNED_REASON
    ):
        raise ReadinessContractError(
            "terminal table-owned canonical owner policy differs"
        )
    for field in ("table_item_id", "table_id", "candidate_id"):
        _string(
            canonical_owner[field],
            f"terminal_alignment.selection.canonical_owner.{field}",
        )
    _count(
        canonical_owner["table_order"],
        "terminal_alignment.selection.canonical_owner.table_order",
    )
    _count(
        canonical_owner["row_index"],
        "terminal_alignment.selection.canonical_owner.row_index",
    )
    for field in ("cell_ids", "source_object_ids", "evidence_ids"):
        _references(
            canonical_owner[field],
            f"terminal_alignment.selection.canonical_owner.{field}",
            allow_empty=False,
        )
    for field in ("table_bbox", "row_bbox", "source_line_bbox"):
        _source_alignment_bbox(
            canonical_owner[field],
            path=f"terminal_alignment.selection.canonical_owner.{field}",
        )
    for field in (
        "content_coverage",
        "source_character_geometry_coverage",
    ):
        coverage = canonical_owner[field]
        if (
            isinstance(coverage, bool)
            or not isinstance(coverage, (int, float))
            or not math.isfinite(float(coverage))
            or float(coverage) != 1.0
        ):
            raise ReadinessContractError(
                "terminal table-owned canonical coverage differs"
            )
    return canonical_owner


def _validate_terminal_alignment_summary(
    summary: Mapping[str, Any], *, source_sha256: str
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(summary, Mapping):
        raise ReadinessContractError("terminal alignment summary is not an object")
    _exact_keys(summary, SOURCE_ALIGNMENT_SUMMARY_FIELDS, "terminal_alignment.summary")
    if (
        summary["schema_version"] != "1.0"
        or summary["policy_id"] != SOURCE_ALIGNMENT_POLICY_ID
        or summary["source_sha256"] != source_sha256
        or summary["status"] != "selected"
    ):
        raise ReadinessContractError("terminal alignment summary identity differs")
    counts = {
        field: _count(summary[field], f"terminal_alignment.summary.{field}")
        for field in (
            "considered_count",
            "selected_count",
            "unchanged_count",
            "unresolved_count",
        )
    }
    selections = summary["selections"]
    concerns = summary["concerns"]
    if (
        not isinstance(selections, list)
        or not selections
        or len(selections) != counts["selected_count"]
        or counts["selected_count"] > MAX_RUNNING_REGIONS_PER_DOCUMENT
        or not isinstance(concerns, list)
        or len(concerns) != counts["unresolved_count"]
        or any(
            not isinstance(concern, Mapping) or concern.get("status") != "unresolved"
            for concern in concerns
        )
        or counts["considered_count"]
        != counts["selected_count"]
        + counts["unchanged_count"]
        + counts["unresolved_count"]
    ):
        raise ReadinessContractError("terminal alignment summary counts differ")
    _duration(summary["elapsed_ms"], "terminal_alignment.summary.elapsed_ms")
    normalized: list[Mapping[str, Any]] = []
    owner_keys: list[tuple[int, str]] = []
    selection_ids: list[str] = []
    for value in selections:
        if not isinstance(value, Mapping):
            raise ReadinessContractError(
                "terminal alignment selection is not an object"
            )
        _exact_keys(
            value,
            SOURCE_ALIGNMENT_SELECTION_FIELDS,
            "terminal_alignment.selection",
        )
        page_index = _index(
            value["page_index"],
            "terminal_alignment.selection.page_index",
            maximum=MAX_PAGES_PER_DOCUMENT,
        )
        owner_id = _string(value["owner_id"], "terminal_alignment.selection.owner_id")
        _string(value["owner_type"], "terminal_alignment.selection.owner_type")
        original_text = _string(
            value["original_text"], "terminal_alignment.selection.original_text"
        )
        selected_text = value["selected_text"]
        if not isinstance(selected_text, str):
            raise ReadinessContractError(
                "terminal alignment selection selected_text differs"
            )
        if original_text == selected_text:
            raise ReadinessContractError(
                "terminal alignment selection did not change source text"
            )
        method = value["method"]
        table_owned_suppression = _is_table_owned_source_suppression(value)
        if (
            value["selected_source"] != "pdf_source_text"
            or method not in _SOURCE_ALIGNMENT_METHOD_CHECKS
            or (
                value["terminal_reason"] != "selected_source_safe_candidate"
                and not table_owned_suppression
            )
            or (not selected_text and method != "source_safe_native_token")
            or (
                table_owned_suppression
                and (
                    selected_text != ""
                    or method != "source_safe_native_token"
                    or value["owner_type"] == "table_cell"
                )
            )
        ):
            raise ReadinessContractError(
                "terminal alignment selection policy terminal differs"
            )
        validate_bbox(
            value["owner_bbox"], path="terminal_alignment.selection.owner_bbox"
        )
        for field in (
            "source_line_ids",
            "source_character_ids",
            "type1_mapping_ids",
        ):
            references = value[field]
            if (
                not isinstance(references, list)
                or any(
                    not isinstance(reference, str) or not reference
                    for reference in references
                )
                or len(references) != len(set(references))
            ):
                raise ReadinessContractError(
                    f"terminal alignment selection {field} differs"
                )
        if not value["source_line_ids"] or not value["source_character_ids"]:
            raise ReadinessContractError(
                "terminal alignment selection source evidence is absent"
            )
        source_roles = value["source_roles"]
        checks = value["checks"]
        if (
            not isinstance(source_roles, list)
            or any(
                not isinstance(role, Mapping)
                or set(role) != set(SOURCE_ALIGNMENT_SOURCE_ROLE_FIELDS)
                for role in source_roles
            )
            or not isinstance(checks, Mapping)
            or not checks
            or any(
                not isinstance(name, str) or not name or result is not True
                for name, result in checks.items()
            )
        ):
            raise ReadinessContractError("terminal alignment selection proof differs")
        if table_owned_suppression:
            _table_owned_canonical_owner(
                value,
                expected_source_sha256=source_sha256,
            )
        elif method == "source_safe_native_token":
            rejected = value["rejected_ocr_alternative"]
            if not isinstance(rejected, Mapping):
                raise ReadinessContractError(
                    "terminal alignment OCR alternative is absent"
                )
            _exact_keys(
                rejected,
                SOURCE_ALIGNMENT_REJECTED_OCR_FIELDS,
                "terminal_alignment.selection.rejected_ocr_alternative",
            )
        elif value["rejected_ocr_alternative"] is not None:
            raise ReadinessContractError(
                "terminal alignment rejected OCR alternative differs"
            )
        expected_id = source_alignment_selection_id(
            source_sha256=source_sha256,
            page_index=page_index,
            owner_id=owner_id,
            original_text=original_text,
            selected_text=selected_text,
        )
        if value["id"] != expected_id:
            raise ReadinessContractError(
                "terminal alignment selection stable ID differs"
            )
        owner_keys.append((page_index, owner_id))
        selection_ids.append(value["id"])
        normalized.append(value)
    if len(owner_keys) != len(set(owner_keys)) or len(selection_ids) != len(
        set(selection_ids)
    ):
        raise ReadinessContractError("terminal alignment selection owner/order differs")
    return tuple(normalized)


def _source_alignment_skeleton(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(
        character
        for character in decomposed
        if character.isalnum() and unicodedata.category(character) != "Mn"
    )


def _source_alignment_single_substitution(first: str, second: str) -> bool:
    return len(first) == len(second) and sum(
        left != right for left, right in zip(first, second, strict=True)
    ) == 1


def _source_alignment_whitespace_gaps(value: str) -> frozenset[int]:
    gaps: set[int] = set()
    compact_index = 0
    in_whitespace = False
    for character in value:
        if character.isspace():
            in_whitespace = compact_index > 0
            continue
        if in_whitespace:
            gaps.add(compact_index)
        compact_index += 1
        in_whitespace = False
    return frozenset(gaps)


def _supported_source_line_space_replacement(
    original: str, source_line_text: str
) -> str | None:
    needle = _source_alignment_skeleton(source_line_text)
    skeleton_characters: list[str] = []
    source_positions: list[int] = []
    for position, character in enumerate(original):
        normalized = unicodedata.normalize("NFD", character.casefold())
        for part in normalized:
            if part.isalnum() and unicodedata.category(part) != "Mn":
                skeleton_characters.append(part)
                source_positions.append(position)
    flattened = "".join(skeleton_characters)
    if not needle or flattened.count(needle) != 1:
        return None
    start_in_skeleton = flattened.find(needle)
    start = source_positions[start_in_skeleton]
    alnum_end = source_positions[start_in_skeleton + len(needle) - 1] + 1
    for end in range(alnum_end, min(len(original), alnum_end + 8) + 1):
        old_span = original[start:end]
        if "".join(old_span.split()) != "".join(source_line_text.split()):
            continue
        if not (
            _source_alignment_whitespace_gaps(old_span)
            < _source_alignment_whitespace_gaps(source_line_text)
        ):
            continue
        selected = original[:start] + source_line_text + original[end:]
        return selected if selected != original else None
    return None


def _validate_selection_against_source_evidence(
    selection: Mapping[str, Any], *, evidence_index: Mapping[str, Any]
) -> None:
    """Rebuild one source selection from frozen character/line evidence."""

    page_index = selection["page_index"]
    page = evidence_index["pages"].get(page_index)
    if not isinstance(page, Mapping):
        raise ReadinessContractError(
            "terminal alignment selection source page is absent"
        )
    owner_bbox = _source_alignment_bbox(
        selection["owner_bbox"], path="terminal_alignment.selection.owner_bbox"
    )
    page_characters = {character["id"]: character for character in page["characters"]}
    fragments: list[tuple[Mapping[str, Any], list[Mapping[str, Any]], str, str]] = []
    for line in page["lines"]:
        ordered = [
            page_characters[identifier] for identifier in line["source_character_ids"]
        ]
        physically_selected: list[int] = []
        for index, character in enumerate(ordered):
            if character["bbox"] is None:
                continue
            bbox = _source_alignment_bbox(
                character["bbox"],
                path="terminal_alignment.selection.character_bbox",
            )
            center_x = float(bbox["x"]) + float(bbox["width"]) / 2
            center_y = float(bbox["y"]) + float(bbox["height"]) / 2
            if float(owner_bbox["x"]) <= center_x <= float(owner_bbox["x"]) + float(
                owner_bbox["width"]
            ) and float(owner_bbox["y"]) <= center_y <= float(owner_bbox["y"]) + float(
                owner_bbox["height"]
            ):
                physically_selected.append(index)
        if not physically_selected:
            continue
        selected = ordered[min(physically_selected) : max(physically_selected) + 1]
        if any(
            character["excluded_reason"] in _SOURCE_ALIGNMENT_FATAL_SELECTION_EXCLUSIONS
            for character in selected
        ):
            raise ReadinessContractError(
                "terminal alignment selected unsafe source evidence"
            )
        canonical = "".join(
            character["text"]
            for character in selected
            if character["excluded_reason"] not in _SOURCE_ALIGNMENT_EMISSION_EXCLUSIONS
        ).strip(" ")
        raw = "".join(
            character["raw_text"]
            for character in selected
            if character["excluded_reason"] not in _SOURCE_ALIGNMENT_EMISSION_EXCLUSIONS
        ).strip(" ")
        if canonical:
            fragments.append((line, selected, canonical, raw))
    if not fragments:
        raise ReadinessContractError("terminal alignment source selection is empty")

    bbox_line_ids = [line["id"] for line, *_rest in fragments]
    bbox_character_ids = [
        character["id"]
        for _line, characters, _canonical, _raw in fragments
        for character in characters
    ]
    bbox_text = " ".join(fragment[2] for fragment in fragments)
    claimed_lines = [
        evidence_index["lines"].get(identifier)
        for identifier in selection["source_line_ids"]
    ]
    if any(not isinstance(line, Mapping) for line in claimed_lines):
        raise ReadinessContractError("terminal alignment claimed source line is absent")
    table_owned_suppression = _is_table_owned_source_suppression(selection)
    if table_owned_suppression:
        canonical_owner = _table_owned_canonical_owner(selection)
        if len(claimed_lines) != 1:
            raise ReadinessContractError(
                "terminal table-owned source line is not unique"
            )
        complete_line = claimed_lines[0]
        assert isinstance(complete_line, Mapping)
        token = " ".join(bbox_text.split())
        complete_text = " ".join(str(complete_line["text"]).split())
        token_occurrences = f" {complete_text} ".count(f" {token} ")
        original_skeleton = _source_alignment_skeleton(
            selection["original_text"]
        )
        token_skeleton = _source_alignment_skeleton(token)
        if (
            not token
            or not original_skeleton
            or complete_line["id"] not in bbox_line_ids
            or complete_line["has_unsafe_character"] is not False
            or len(complete_text.split()) < 2
            or token_occurrences != 1
            or not (
                original_skeleton == token_skeleton
                or _source_alignment_single_substitution(
                    original_skeleton, token_skeleton
                )
            )
            or _source_alignment_bbox(
                canonical_owner["source_line_bbox"],
                path=(
                    "terminal_alignment.selection.canonical_owner."
                    "source_line_bbox"
                ),
            )
            != _source_alignment_bbox(
                complete_line["bbox"],
                path="terminal_alignment.table_owned_source_line_bbox",
            )
        ):
            raise ReadinessContractError(
                "terminal table-owned complete source line differs"
            )
        complete_characters = [
            page_characters[identifier]
            for identifier in complete_line["source_character_ids"]
        ]
        if any(
            character["bbox"] is None
            for character in complete_characters
            if character["excluded_reason"]
            not in _SOURCE_ALIGNMENT_EMISSION_EXCLUSIONS
            and str(character["text"]).strip()
        ):
            raise ReadinessContractError(
                "terminal table-owned source character geometry is incomplete"
            )
        fragments = [
            (
                complete_line,
                complete_characters,
                complete_line["text"],
                complete_line["raw_text"],
            )
        ]
    elif selection["method"] == "source_safe_native_token":
        token = bbox_text.strip()
        complete_candidates = [
            line
            for line in page["lines"]
            if line["id"] in bbox_line_ids
            and line["has_unsafe_character"] is False
            and line["text"].startswith(f"{token} ")
            and len(line["text"].split()) >= 3
        ]
        if (
            not token.isalpha()
            or not token.isupper()
            or not 3 <= len(token) <= 8
            or len(complete_candidates) != 1
            or selection["source_line_ids"] != [complete_candidates[0]["id"]]
        ):
            raise ReadinessContractError("terminal native-token complete line differs")
        complete_line = complete_candidates[0]
        complete_characters = [
            page_characters[identifier]
            for identifier in complete_line["source_character_ids"]
        ]
        fragments = [
            (
                complete_line,
                complete_characters,
                complete_line["text"],
                complete_line["raw_text"],
            )
        ]
    elif selection["method"] == "pdfium_source_space" and (
        selection["source_line_ids"] != list(dict.fromkeys(bbox_line_ids))
        or selection["source_character_ids"] != bbox_character_ids
    ):
        space_candidates: list[
            tuple[Mapping[str, Any], list[Mapping[str, Any]], str]
        ] = []
        for source_line in page["lines"]:
            line_bbox = _source_alignment_bbox(
                source_line["bbox"],
                path="terminal_alignment.supported_space_bbox",
            )
            intersection_width = max(
                min(
                    float(owner_bbox["x"]) + float(owner_bbox["width"]),
                    float(line_bbox["x"]) + float(line_bbox["width"]),
                )
                - max(float(owner_bbox["x"]), float(line_bbox["x"])),
                0.0,
            )
            intersection_height = max(
                min(
                    float(owner_bbox["y"]) + float(owner_bbox["height"]),
                    float(line_bbox["y"]) + float(line_bbox["height"]),
                )
                - max(float(owner_bbox["y"]), float(line_bbox["y"])),
                0.0,
            )
            intersection = intersection_width * intersection_height
            smaller_area = min(
                float(owner_bbox["width"]) * float(owner_bbox["height"]),
                float(line_bbox["width"]) * float(line_bbox["height"]),
            )
            line_characters = [
                page_characters[identifier]
                for identifier in source_line["source_character_ids"]
            ]
            replacement = _supported_source_line_space_replacement(
                selection["original_text"], source_line["text"]
            )
            if (
                source_line["has_unsafe_character"] is False
                and len(_source_alignment_skeleton(source_line["text"])) >= 12
                and smaller_area
                and intersection / smaller_area >= 0.15
                and any(
                    character["raw_code_point"] == 0x20
                    and character["space_supported"] is True
                    for character in line_characters
                )
                and replacement is not None
            ):
                space_candidates.append((source_line, line_characters, replacement))
        if (
            len(space_candidates) != 1
            or selection["source_line_ids"] != [space_candidates[0][0]["id"]]
            or selection["selected_text"] != space_candidates[0][2]
        ):
            raise ReadinessContractError("terminal supported-space source line differs")
        source_line, complete_characters, _replacement = space_candidates[0]
        fragments = [
            (
                source_line,
                complete_characters,
                source_line["text"],
                source_line["raw_text"],
            )
        ]

    canonical_parts: list[str] = []
    raw_parts: list[str] = []
    all_characters: list[Mapping[str, Any]] = []
    for fragment_index, (line, characters, canonical, raw) in enumerate(fragments):
        if fragment_index:
            previous_line, previous_characters, previous_text, _ = fragments[
                fragment_index - 1
            ]
            separator = (
                ""
                if (
                    previous_line["terminal_semantic_hyphen"] is True
                    and previous_text.endswith("-")
                )
                or (
                    previous_characters
                    and previous_characters[-1]["raw_text"] == "-"
                    and previous_text.endswith("-")
                )
                else " "
            )
            canonical_parts.append(separator)
            raw_parts.append(separator)
        canonical_parts.append(canonical)
        raw_parts.append(raw)
        all_characters.extend(characters)
    evidence_text = "".join(canonical_parts)
    evidence_raw_text = "".join(raw_parts)
    expected_line_ids = list(dict.fromkeys(line["id"] for line, *_rest in fragments))
    expected_character_ids = [character["id"] for character in all_characters]
    expected_type1_ids = list(
        dict.fromkeys(
            evidence_id
            for character in all_characters
            for evidence_id in character["type1_evidence_ids"]
        )
    )
    expected_roles = _source_alignment_roles(all_characters)
    if (
        selection["source_line_ids"] != expected_line_ids
        or selection["source_character_ids"] != expected_character_ids
        or selection["type1_mapping_ids"] != expected_type1_ids
        or selection["source_roles"] != expected_roles
    ):
        raise ReadinessContractError(
            "terminal alignment selection evidence binding differs"
        )

    selection_variants = [""]
    for character in sorted(all_characters, key=lambda value: value["character_index"]):
        if character["excluded_reason"] in {
            "unsafe_unicode",
            "invalid_hyphen_sentinel_bbox",
            "uncorroborated_hyphen_sentinel",
            "transparent_text",
        }:
            continue
        options = [character["text"]]
        if character["type1_evidence_ids"]:
            options.append(character["raw_text"])
        elif character["excluded_reason"] == "white_icon_overlay":
            options = ["", character["raw_text"]]
        options = list(dict.fromkeys(options))
        selection_variants = [
            prefix + option for prefix in selection_variants for option in options
        ][:8]
    projection_text = "".join(
        character["raw_text"]
        for character in sorted(
            all_characters, key=lambda value: value["character_index"]
        )
        if character["excluded_reason"]
        not in {
            "unsafe_unicode",
            "invalid_hyphen_sentinel_bbox",
            "uncorroborated_hyphen_sentinel",
            "transparent_text",
        }
    )
    old_skeleton = _source_alignment_skeleton(selection["original_text"])
    candidate_skeletons = {
        _source_alignment_skeleton(value)
        for value in (
            evidence_text,
            evidence_raw_text,
            projection_text,
            *selection_variants,
        )
    }
    special_complete_line = selection["method"] == "source_safe_native_token" or (
        selection["method"] == "pdfium_source_space"
        and selection["selected_text"] != evidence_text
    )
    if not special_complete_line:
        if len(old_skeleton) < 3 or old_skeleton not in candidate_skeletons:
            raise ReadinessContractError(
                "terminal alignment original text is not source-grounded"
            )
        if not expected_type1_ids:
            canonical_page = _source_alignment_skeleton(
                "".join(
                    character["text"]
                    for character in page["characters"]
                    if character["excluded_reason"]
                    not in {
                        "unsafe_unicode",
                        "invalid_hyphen_sentinel_bbox",
                        "uncorroborated_hyphen_sentinel",
                        "transparent_text",
                        "white_icon_overlay",
                    }
                )
            )
            raw_page = _source_alignment_skeleton(
                "".join(
                    character["raw_text"]
                    for character in page["characters"]
                    if character["excluded_reason"]
                    not in {
                        "unsafe_unicode",
                        "invalid_hyphen_sentinel_bbox",
                        "uncorroborated_hyphen_sentinel",
                        "transparent_text",
                    }
                )
            )
            if all(
                value.count(old_skeleton) != 1 for value in {canonical_page, raw_page}
            ):
                raise ReadinessContractError(
                    "terminal alignment original source occurrence is ambiguous"
                )

    original = selection["original_text"]
    selected = selection["selected_text"]
    method = selection["method"]
    checks = set(selection["checks"])
    expected_checks = set(_SOURCE_ALIGNMENT_BASE_CHECKS)
    derived_method: str | None = None
    if expected_type1_ids:
        derived_method = "type1_encoding_differences"
        expected_checks.update(_SOURCE_ALIGNMENT_METHOD_CHECKS[derived_method])
    elif any(
        character["pdfium_is_hyphen"] is True and character["text"] == "-"
        for character in all_characters
    ):
        derived_method = "pdfium_semantic_hyphen"
        expected_checks.update(_SOURCE_ALIGNMENT_METHOD_CHECKS[derived_method])
        if not all(
            character["corroborating_line_ids"]
            for character in all_characters
            if character["pdfium_is_hyphen"] is True and character["text"] == "-"
        ):
            raise ReadinessContractError(
                "terminal semantic-hyphen corroboration differs"
            )
    elif any(
        character["excluded_reason"] == "spacing_diaeresis_composed"
        for character in all_characters
    ):
        derived_method = "pdfium_spacing_diaeresis"
        expected_checks.update(_SOURCE_ALIGNMENT_METHOD_CHECKS[derived_method])
    elif any(
        character["excluded_reason"] == "white_icon_overlay"
        for character in all_characters
    ):
        derived_method = "pdfium_nonlexical_overlay"
        expected_checks.update(_SOURCE_ALIGNMENT_METHOD_CHECKS[derived_method])
    elif (
        "".join(original.split()) == "".join(selected.split())
        and _source_alignment_whitespace_gaps(original)
        < _source_alignment_whitespace_gaps(selected)
        and any(
            character["raw_code_point"] == 0x20 and character["space_supported"] is True
            for character in all_characters
        )
    ):
        derived_method = "pdfium_source_space"
        expected_checks.update(_SOURCE_ALIGNMENT_METHOD_CHECKS[derived_method])
        if selected != evidence_text:
            expected_checks.add("unique_owner_alignment")
    elif (
        any(character in evidence_text for character in ("“", "”", "‘", "’"))
        and len(re.findall(r"\s['\"]\s", original)) >= 4
    ):
        derived_method = "pdfium_native_text"
        expected_checks.update({"literal_source_punctuation", "unique_owner_alignment"})
    elif "−" in evidence_text and re.search(r"(?:^|[\s(])- ?", original):
        if not re.search(r"\d,\d", evidence_text):
            raise ReadinessContractError(
                "terminal native-minus selection is outside policy"
            )
        derived_method = "pdfium_native_text"
        expected_checks.update({"literal_source_minus", "unique_owner_alignment"})
    elif method == "source_safe_native_token":
        derived_method = method
        expected_checks.update(_SOURCE_ALIGNMENT_METHOD_CHECKS[derived_method])
        if table_owned_suppression:
            expected_checks.update(_SOURCE_ALIGNMENT_TABLE_OWNED_CHECKS)

    if (
        derived_method != method
        or checks != expected_checks
        or (
            selected != evidence_text
            and not (method == "source_safe_native_token" and selected == "")
            and not (
                method == "pdfium_source_space"
                and "".join(original.split()) == "".join(selected.split())
                and evidence_text in selected
            )
        )
    ):
        raise ReadinessContractError(
            "terminal alignment method/check/source text differs"
        )


def _alignment_summary_semantic_payload(
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    payload = deepcopy(dict(summary))
    payload["elapsed_ms"] = 0.0
    return payload


@dataclass(frozen=True, slots=True)
class _AlignmentOwnerLocation:
    page_offset: int
    item_offset: int
    row: int | None = None
    column: int | None = None


def _alignment_owner_at(
    document: Mapping[str, Any],
    *,
    page_index: int,
    owner_id: str,
    owner_type: str,
) -> tuple[_AlignmentOwnerLocation, Mapping[str, Any], Mapping[str, Any]]:
    matches: list[
        tuple[_AlignmentOwnerLocation, Mapping[str, Any], Mapping[str, Any]]
    ] = []
    pages = document.get("pages")
    if not isinstance(pages, list):
        raise ReadinessContractError("terminal alignment public pages differ")
    for page_offset, page in enumerate(pages):
        if not isinstance(page, Mapping) or page.get("page_index") != page_index:
            continue
        items = page.get("items")
        if not isinstance(items, list):
            continue
        for item_offset, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            if owner_type != "table_cell":
                if item.get("id") == owner_id:
                    matches.append(
                        (
                            _AlignmentOwnerLocation(page_offset, item_offset),
                            item,
                            item,
                        )
                    )
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str) or not owner_id.startswith(f"{item_id}:r"):
                continue
            match = re.fullmatch(rf"{re.escape(item_id)}:r([0-9]+):c([0-9]+)", owner_id)
            if match is None:
                continue
            row, column = (int(value) for value in match.groups())
            cells = item.get("cells")
            if not isinstance(cells, list):
                continue
            cell_matches = [
                cell
                for cell in cells
                if isinstance(cell, Mapping)
                and max(int(cell.get("row", 0)), 0) == row
                and max(int(cell.get("column", 0)), 0) == column
            ]
            if len(cell_matches) == 1:
                matches.append(
                    (
                        _AlignmentOwnerLocation(
                            page_offset, item_offset, row=row, column=column
                        ),
                        item,
                        cell_matches[0],
                    )
                )
    if len(matches) != 1:
        raise ReadinessContractError(
            "terminal alignment selected owner is absent or multiply owned"
        )
    return matches[0]


def _normalize_alignment_scalar_record(
    aligned: Mapping[str, Any],
    configured: Mapping[str, Any],
    *,
    selections: Sequence[Mapping[str, Any]],
    fields: frozenset[str],
    path: str,
) -> dict[str, Any]:
    """Normalize only named derived text scalars; graph metadata stays exact."""

    if set(aligned) != set(configured):
        raise ReadinessContractError(f"{path} keys differ")
    expected = deepcopy(dict(configured))
    for field in fields:
        configured_value = configured.get(field)
        if not isinstance(configured_value, str):
            continue
        derived = configured_value
        for selection in selections:
            original = selection["original_text"]
            selected = selection["selected_text"]
            if original and derived.count(original) == 1:
                derived = derived.replace(original, selected, 1)
        expected[field] = derived
    if dict(aligned) != expected:
        raise ReadinessContractError(f"{path} scalar propagation differs")
    return deepcopy(dict(configured))


def _public_owner_at(
    document: Mapping[str, Any], *, page_index: int, owner_id: str
) -> tuple[int, int, Mapping[str, Any]]:
    matches: list[tuple[int, int, Mapping[str, Any]]] = []
    pages = document.get("pages")
    if not isinstance(pages, list):
        raise ReadinessContractError("terminal alignment public pages differ")
    for page_offset, page in enumerate(pages):
        if not isinstance(page, Mapping):
            continue
        items = page.get("items")
        if not isinstance(items, list):
            continue
        for item_offset, item in enumerate(items):
            if (
                page.get("page_index") == page_index
                and isinstance(item, Mapping)
                and item.get("id") == owner_id
            ):
                matches.append((page_offset, item_offset, item))
    if len(matches) != 1:
        raise ReadinessContractError(
            "terminal alignment selected owner is absent or multiply owned"
        )
    return matches[0]


def _expected_aligned_scalar(
    before: Any,
    *,
    original_text: str,
    selected_text: str,
    path: str,
) -> str:
    if not isinstance(before, str) or before.count(original_text) != 1:
        raise ReadinessContractError(f"{path} does not uniquely contain original text")
    return before.replace(original_text, selected_text, 1)


def _validate_alignment_trace(
    trace: Any,
    *,
    selection: Mapping[str, Any],
    source_sha256: str,
) -> None:
    if not isinstance(trace, Mapping):
        raise ReadinessContractError("terminal alignment owner trace is absent")
    _exact_keys(trace, SOURCE_ALIGNMENT_TRACE_FIELDS, "terminal_alignment.trace")
    expected = {
        "schema_version": "1.0",
        "policy_id": SOURCE_ALIGNMENT_POLICY_ID,
        "source_sha256": source_sha256,
        "selection_id": selection["id"],
        **{
            field: selection[field]
            for field in (
                "original_text",
                "selected_text",
                "selected_source",
                "source_line_ids",
                "source_character_ids",
                "type1_mapping_ids",
                "source_roles",
                "method",
                "checks",
                "terminal_reason",
                "rejected_ocr_alternative",
            )
        },
    }
    if dict(trace) != expected:
        raise ReadinessContractError("terminal alignment owner trace differs")


def _normalize_selected_owner(
    aligned_owner: Mapping[str, Any],
    configured_owner: Mapping[str, Any],
    *,
    selection: Mapping[str, Any],
    source_sha256: str,
) -> dict[str, Any]:
    configured_descriptor = configured_owner.get("running_region")
    configured_owner_type = (
        configured_descriptor.get("predecessor_type")
        if isinstance(configured_descriptor, Mapping)
        else configured_owner.get("type")
    )
    if (
        configured_owner.get("id") != selection["owner_id"]
        or configured_owner_type != selection["owner_type"]
        or configured_owner.get("value") != selection["original_text"]
        or aligned_owner.get("value") != selection["selected_text"]
        or aligned_owner.get("source") != "native"
        or _canonical_bbox(
            configured_owner.get("bbox"), path="terminal_alignment.owner_bbox"
        )
        != _canonical_bbox(
            selection["owner_bbox"], path="terminal_alignment.selection_bbox"
        )
    ):
        raise ReadinessContractError("terminal alignment owner binding differs")
    _validate_alignment_trace(
        aligned_owner.get("source_alignment"),
        selection=selection,
        source_sha256=source_sha256,
    )
    if configured_owner_type == "heading":
        try:
            level = min(max(int(configured_owner.get("level") or 1), 1), 6)
        except (TypeError, ValueError):
            level = 1
        expected_md = f"{'#' * level} {selection['selected_text']}"
    else:
        expected_md = selection["selected_text"]
    expected = deepcopy(dict(configured_owner))
    expected["value"] = selection["selected_text"]
    expected["md"] = expected_md
    expected["source"] = "native"
    expected["source_alignment"] = deepcopy(dict(aligned_owner["source_alignment"]))
    if dict(aligned_owner) != expected:
        raise ReadinessContractError(
            "terminal alignment owner changed a non-production field"
        )
    return deepcopy(dict(configured_owner))


def _normalize_selected_table(
    aligned_item: Mapping[str, Any],
    configured_item: Mapping[str, Any],
    *,
    selections: Sequence[Mapping[str, Any]],
    source_sha256: str,
) -> dict[str, Any]:
    trace = aligned_item.get("source_alignment")
    if not isinstance(trace, Mapping):
        raise ReadinessContractError("terminal table alignment trace is absent")
    _exact_keys(
        trace, SOURCE_ALIGNMENT_TABLE_TRACE_FIELDS, "terminal_alignment.table_trace"
    )
    expected_trace = {
        "schema_version": "1.0",
        "policy_id": SOURCE_ALIGNMENT_POLICY_ID,
        "source_sha256": source_sha256,
        "selection_ids": [selection["id"] for selection in selections],
    }
    if dict(trace) != expected_trace:
        raise ReadinessContractError("terminal table alignment trace differs")
    normalized = deepcopy(dict(aligned_item))
    normalized.pop("source_alignment")
    configured_rows = configured_item.get("rows") or configured_item.get("value")
    normalized_rows = normalized.get("rows") or normalized.get("value")
    if not isinstance(configured_rows, list) or not isinstance(normalized_rows, list):
        raise ReadinessContractError("terminal table rows differ")
    cells = normalized.get("cells")
    configured_cells = configured_item.get("cells")
    if not isinstance(cells, list) or not isinstance(configured_cells, list):
        raise ReadinessContractError("terminal table cells differ")
    for selection in selections:
        match = re.search(r":r([0-9]+):c([0-9]+)$", selection["owner_id"])
        if match is None:
            raise ReadinessContractError("terminal table owner path differs")
        row, column = (int(value) for value in match.groups())
        configured_matches = [
            cell
            for cell in configured_cells
            if isinstance(cell, Mapping)
            and max(int(cell.get("row", 0)), 0) == row
            and max(int(cell.get("column", 0)), 0) == column
        ]
        normalized_matches = [
            cell
            for cell in cells
            if isinstance(cell, dict)
            and max(int(cell.get("row", 0)), 0) == row
            and max(int(cell.get("column", 0)), 0) == column
        ]
        if (
            len(configured_matches) != 1
            or len(normalized_matches) != 1
            or configured_matches[0].get("text") != selection["original_text"]
            or normalized_matches[0].get("text") != selection["selected_text"]
            or row >= len(configured_rows)
            or row >= len(normalized_rows)
            or column >= len(configured_rows[row])
            or column >= len(normalized_rows[row])
            or configured_rows[row][column] != selection["original_text"]
            or normalized_rows[row][column] != selection["selected_text"]
        ):
            raise ReadinessContractError("terminal table selection differs")
        normalized_matches[0]["text"] = selection["original_text"]
        normalized_rows[row][column] = selection["original_text"]
        if isinstance(normalized.get("value"), list):
            normalized["value"][row][column] = selection["original_text"]
        if isinstance(normalized.get("rows"), list):
            normalized["rows"][row][column] = selection["original_text"]
        for field in ("html", "md", "csv"):
            configured_scalar = configured_item.get(field)
            aligned_scalar = normalized.get(field)
            if (
                isinstance(configured_scalar, str)
                and isinstance(aligned_scalar, str)
                and aligned_scalar.count(selection["selected_text"]) == 1
            ):
                normalized[field] = aligned_scalar.replace(
                    selection["selected_text"], selection["original_text"], 1
                )
    if normalized != configured_item:
        raise ReadinessContractError(
            "terminal table alignment changed a non-production field"
        )
    return deepcopy(dict(configured_item))


def _table_owned_center_inside(
    inner: Mapping[str, Any], outer: Mapping[str, Any]
) -> bool:
    inner_box = _canonical_bbox(inner, path="table_owned.inner_bbox")
    outer_box = _canonical_bbox(outer, path="table_owned.outer_bbox")
    center_x = float(inner_box["x"]) + float(inner_box["width"]) / 2
    center_y = float(inner_box["y"]) + float(inner_box["height"]) / 2
    return (
        float(outer_box["x"])
        <= center_x
        <= float(outer_box["x"]) + float(outer_box["width"])
        and float(outer_box["y"])
        <= center_y
        <= float(outer_box["y"]) + float(outer_box["height"])
    )


def _table_owned_intersection_area(
    first: Mapping[str, Any], second: Mapping[str, Any]
) -> float:
    first_box = _canonical_bbox(first, path="table_owned.first_bbox")
    second_box = _canonical_bbox(second, path="table_owned.second_bbox")
    width = max(
        min(
            float(first_box["x"]) + float(first_box["width"]),
            float(second_box["x"]) + float(second_box["width"]),
        )
        - max(float(first_box["x"]), float(second_box["x"])),
        0.0,
    )
    height = max(
        min(
            float(first_box["y"]) + float(first_box["height"]),
            float(second_box["y"]) + float(second_box["height"]),
        )
        - max(float(first_box["y"]), float(second_box["y"])),
        0.0,
    )
    return width * height


def _table_owned_overlap_of_smaller(
    first: Mapping[str, Any], second: Mapping[str, Any]
) -> float:
    first_box = _canonical_bbox(first, path="table_owned.first_bbox")
    second_box = _canonical_bbox(second, path="table_owned.second_bbox")
    smaller = min(
        float(first_box["width"]) * float(first_box["height"]),
        float(second_box["width"]) * float(second_box["height"]),
    )
    if smaller <= 0:
        return 0.0
    return _table_owned_intersection_area(first_box, second_box) / smaller


def _table_owned_ordered_references(values: Sequence[Any]) -> list[str] | None:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            return None
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _table_owned_whitespace_normalized(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFC", value),
    ).strip()


def _table_owned_cell_covers_source_fragment(
    fragment: Sequence[Mapping[str, Any]],
    cell_text: str,
) -> bool:
    """Independently reconstruct bounded native-boundary cell coverage.

    The ordinary path retains the historical NFC/whitespace-collapse
    comparison.  The only additional equivalence is one or more canonical
    spaces immediately before unchanged allowlisted punctuation where the
    source character evidence proves a direct nonspace font-run transition.
    Character order and punctuation count make the boundary map linear; no
    production helper or production constant is imported here.
    """

    if (
        not isinstance(fragment, Sequence)
        or isinstance(fragment, (str, bytes, bytearray))
        or not isinstance(cell_text, str)
    ):
        return False
    try:
        if len(cell_text.encode("utf-8")) > MAX_CANDIDATE_TEXT_UTF8_BYTES:
            return False
    except UnicodeEncodeError:
        return False

    source_parts: list[str] = []
    source_bytes = 0
    for character in fragment:
        if not isinstance(character, Mapping):
            return False
        text = character.get("text")
        if not isinstance(text, str):
            return False
        try:
            source_bytes += len(text.encode("utf-8"))
        except UnicodeEncodeError:
            return False
        if source_bytes > MAX_CANDIDATE_TEXT_UTF8_BYTES:
            return False
        source_parts.append(text)

    source_text = _table_owned_whitespace_normalized("".join(source_parts))
    canonical_text = _table_owned_whitespace_normalized(cell_text)
    if source_text == canonical_text:
        return True
    if not source_text or not canonical_text:
        return False

    punctuation_offsets = [
        index
        for index, character in enumerate(source_text)
        if character in _SOURCE_ALIGNMENT_NATIVE_BOUNDARY_PUNCTUATION
    ]
    boundary_flags: list[bool] = []
    for character_index, current in enumerate(fragment):
        current_text = current.get("text")
        if not isinstance(current_text, str):
            return False
        previous = fragment[character_index - 1] if character_index else None
        eligible = bool(
            current_text in _SOURCE_ALIGNMENT_NATIVE_BOUNDARY_PUNCTUATION
            and isinstance(previous, Mapping)
            and isinstance(previous.get("text"), str)
            and previous["text"]
            and not previous["text"].isspace()
            and isinstance(previous.get("font_ref"), str)
            and previous["font_ref"]
            and isinstance(current.get("font_ref"), str)
            and current["font_ref"]
            and previous["font_ref"] != current["font_ref"]
        )
        for normalized_character in unicodedata.normalize("NFC", current_text):
            if (
                normalized_character
                in _SOURCE_ALIGNMENT_NATIVE_BOUNDARY_PUNCTUATION
            ):
                # A multi-codepoint source character is not the exact closed
                # one-character boundary witness, but its punctuation still
                # occupies an offset and therefore receives an explicit False.
                boundary_flags.append(eligible and len(current_text) == 1)

    if (
        len(boundary_flags) != len(punctuation_offsets)
        or not any(boundary_flags)
    ):
        return False
    allowed_offsets = {
        offset
        for offset, eligible in zip(
            punctuation_offsets,
            boundary_flags,
            strict=True,
        )
        if eligible
    }

    source_index = 0
    canonical_index = 0
    while source_index < len(source_text) and canonical_index < len(
        canonical_text
    ):
        if source_text[source_index] == canonical_text[canonical_index]:
            source_index += 1
            canonical_index += 1
            continue
        if (
            source_index in allowed_offsets
            and canonical_text[canonical_index] == " "
            and source_text[source_index]
            in _SOURCE_ALIGNMENT_NATIVE_BOUNDARY_PUNCTUATION
        ):
            canonical_index += 1
            continue
        return False
    return source_index == len(source_text) and canonical_index == len(
        canonical_text
    )


def _table_owned_row_candidates(
    selection: Mapping[str, Any],
    *,
    evidence_index: Mapping[str, Any],
    authoritative_table_views: Mapping[int, Sequence[Mapping[str, Any]]] | None,
    source_sha256: str,
) -> tuple[Mapping[str, Any], ...]:
    """Reconstruct every complete table owner; the caller requires exactly one."""

    if not isinstance(authoritative_table_views, Mapping):
        return ()
    page_index = selection["page_index"]
    raw_tables = authoritative_table_views.get(page_index)
    if (
        not isinstance(raw_tables, Sequence)
        or isinstance(raw_tables, (str, bytes, bytearray))
        or len(raw_tables) > MAX_RUNNING_REGIONS_PER_DOCUMENT
    ):
        return ()
    page = evidence_index["pages"].get(page_index)
    if not isinstance(page, Mapping) or len(selection["source_line_ids"]) != 1:
        return ()
    source_line = evidence_index["lines"].get(selection["source_line_ids"][0])
    if not isinstance(source_line, Mapping):
        return ()
    page_characters = {
        character["id"]: character for character in page["characters"]
    }
    try:
        line_characters = [
            page_characters[identifier]
            for identifier in source_line["source_character_ids"]
        ]
    except KeyError:
        return ()
    emitted_characters = [
        character
        for character in line_characters
        if character["excluded_reason"]
        not in _SOURCE_ALIGNMENT_EMISSION_EXCLUSIONS
    ]
    substantive = [
        character
        for character in emitted_characters
        if str(character["text"]).strip()
    ]
    if not substantive:
        return ()

    from app.services.table_semantics import validate_table_semantics

    owner_bbox = selection["owner_bbox"]
    matches: list[Mapping[str, Any]] = []
    for view_order, table in enumerate(raw_tables):
        if not isinstance(table, Mapping):
            continue
        sidecar = table.get("table_evidence")
        gate = sidecar.get("gate") if isinstance(sidecar, Mapping) else None
        try:
            admitted = bool(validate_table_semantics(table, source_sha256))
        except (MemoryError, RecursionError, TypeError, ValueError):
            admitted = False
        if (
            not admitted
            or table.get("type") != "table"
            or "_p04_predecessor_snapshot" in table
            or not isinstance(sidecar, Mapping)
            or sidecar.get("status") != "valid"
            or sidecar.get("page_index") != page_index
            or not isinstance(gate, Mapping)
            or gate.get("outcome") != "canonical_table"
        ):
            continue
        table_bbox = table.get("bbox")
        rows = table.get("rows") or table.get("value")
        cells = table.get("cells")
        source_objects = sidecar.get("source_objects")
        evidence_records = sidecar.get("evidence")
        if (
            not isinstance(table_bbox, Mapping)
            or not isinstance(rows, Sequence)
            or isinstance(rows, (str, bytes, bytearray))
            or not isinstance(cells, list)
            or not isinstance(source_objects, list)
            or not isinstance(evidence_records, list)
        ):
            continue
        try:
            canonical_table_bbox = _canonical_bbox(
                table_bbox, path="terminal_alignment.table_owned.table_bbox"
            )
            if canonical_table_bbox["unit"] != "pt":
                raise ReadinessContractError(
                    "terminal table-owned table coordinate unit differs"
                )
        except ReadinessContractError:
            continue
        table_item_id = table.get("id")
        table_id = sidecar.get("table_id")
        candidate_id = sidecar.get("candidate_id")
        if not all(
            isinstance(identifier, str) and identifier
            for identifier in (table_item_id, table_id, candidate_id)
        ):
            continue
        source_by_id = {
            record.get("id"): record
            for record in source_objects
            if isinstance(record, Mapping)
            and isinstance(record.get("id"), str)
        }
        evidence_by_id = {
            record.get("id"): record
            for record in evidence_records
            if isinstance(record, Mapping)
            and isinstance(record.get("id"), str)
        }
        row_indexes = sorted(
            {
                cell.get("row")
                for cell in cells
                if isinstance(cell, Mapping)
                and isinstance(cell.get("row"), int)
                and not isinstance(cell.get("row"), bool)
            }
        )
        for row_index in row_indexes:
            if not 0 <= row_index < len(rows):
                continue
            row_value = rows[row_index]
            if (
                not isinstance(row_value, Sequence)
                or isinstance(row_value, (str, bytes, bytearray))
            ):
                continue
            row_cells = sorted(
                (
                    cell
                    for cell in cells
                    if isinstance(cell, Mapping)
                    and cell.get("row") == row_index
                ),
                key=lambda cell: (
                    cell.get("column")
                    if isinstance(cell.get("column"), int)
                    else MAX_RUNNING_REGIONS_PER_DOCUMENT
                ),
            )
            if len(row_cells) < 2 or len(row_cells) != len(row_value):
                continue
            cell_boxes: list[Mapping[str, Any]] = []
            cell_ids: list[str] = []
            cell_source_ids: list[list[str]] = []
            cell_evidence_ids: list[list[str]] = []
            structurally_complete = True
            for column, cell in enumerate(row_cells):
                source_ids = _table_owned_ordered_references(
                    list(cell.get("source_object_ids") or ())
                )
                evidence_ids = _table_owned_ordered_references(
                    list(cell.get("evidence_ids") or ())
                )
                cell_bbox = cell.get("bbox")
                if (
                    cell.get("column") != column
                    or cell.get("row_span") != 1
                    or cell.get("col_span") != 1
                    or cell.get("source") != "native"
                    or cell.get("page_index") != page_index
                    or not isinstance(cell.get("id"), str)
                    or not cell.get("id")
                    or not isinstance(cell.get("text"), str)
                    or not isinstance(cell_bbox, Mapping)
                    or source_ids is None
                    or not source_ids
                    or len(source_ids) > MAX_REFERENCES_PER_RECORD
                    or evidence_ids is None
                    or not evidence_ids
                    or len(evidence_ids) > MAX_REFERENCES_PER_RECORD
                    or " ".join(str(row_value[column]).split())
                    != " ".join(str(cell["text"]).split())
                ):
                    structurally_complete = False
                    break
                try:
                    canonical_cell_bbox = _canonical_bbox(
                        cell_bbox,
                        path="terminal_alignment.table_owned.cell_bbox",
                    )
                    if canonical_cell_bbox["unit"] != "pt":
                        raise ReadinessContractError(
                            "terminal table-owned cell coordinate unit differs"
                        )
                except ReadinessContractError:
                    structurally_complete = False
                    break
                linked_sources = [source_by_id.get(value) for value in source_ids]
                linked_evidence = [
                    evidence_by_id.get(value) for value in evidence_ids
                ]
                if (
                    any(not isinstance(value, Mapping) for value in linked_sources)
                    or any(
                        value.get("page_index") != page_index
                        or value.get("engine") not in {"docling", "pdfplumber"}
                        for value in linked_sources
                        if isinstance(value, Mapping)
                    )
                    or any(
                        not isinstance(value, Mapping)
                        or value.get("page_index") != page_index
                        for value in linked_evidence
                    )
                    or not any(
                        set(value.get("source_object_ids") or ())
                        & set(source_ids)
                        for value in linked_evidence
                        if isinstance(value, Mapping)
                    )
                ):
                    structurally_complete = False
                    break
                cell_boxes.append(canonical_cell_bbox)
                cell_ids.append(str(cell["id"]))
                cell_source_ids.append(source_ids)
                cell_evidence_ids.append(evidence_ids)
            if (
                not structurally_complete
                or any(
                    _table_owned_intersection_area(first, second) > 0.000001
                    for index, first in enumerate(cell_boxes)
                    for second in cell_boxes[index + 1 :]
                )
            ):
                continue
            row_bbox = _bbox_union(
                cell_boxes, path="terminal_alignment.table_owned.row_bbox"
            )
            if (
                not _table_owned_center_inside(owner_bbox, row_bbox)
                or _table_owned_overlap_of_smaller(
                    source_line["bbox"], row_bbox
                )
                < 0.90
                or max(
                    _table_owned_overlap_of_smaller(owner_bbox, cell_bbox)
                    for cell_bbox in cell_boxes
                )
                < 0.80
            ):
                continue
            fragments: list[list[Mapping[str, Any]]] = [
                [] for _cell in row_cells
            ]
            covered_substantive = 0
            coverage_conflict = False
            for character in emitted_characters:
                character_bbox = character.get("bbox")
                if not isinstance(character_bbox, Mapping):
                    if not str(character["text"]).strip():
                        continue
                    coverage_conflict = True
                    break
                owners = [
                    index
                    for index, cell_bbox in enumerate(cell_boxes)
                    if _table_owned_center_inside(character_bbox, cell_bbox)
                ]
                if not str(character["text"]).strip() and not owners:
                    continue
                if len(owners) != 1:
                    coverage_conflict = True
                    break
                fragments[owners[0]].append(character)
                if str(character["text"]).strip():
                    covered_substantive += 1
            if (
                coverage_conflict
                or covered_substantive != len(substantive)
                or any(
                    not _table_owned_cell_covers_source_fragment(
                        fragment,
                        str(cell["text"]),
                    )
                    for fragment, cell in zip(fragments, row_cells, strict=True)
                )
            ):
                continue
            reading_order = table.get("reading_order")
            table_order = (
                reading_order
                if isinstance(reading_order, int)
                and not isinstance(reading_order, bool)
                and reading_order >= 0
                else view_order
            )
            flattened_source_ids = _table_owned_ordered_references(
                [value for values in cell_source_ids for value in values]
            )
            flattened_evidence_ids = _table_owned_ordered_references(
                [value for values in cell_evidence_ids for value in values]
            )
            if flattened_source_ids is None or flattened_evidence_ids is None:
                continue
            matches.append(
                {
                    "policy_id": SOURCE_ALIGNMENT_TABLE_OWNED_POLICY_ID,
                    "suppression_reason": SOURCE_ALIGNMENT_TABLE_OWNED_REASON,
                    "page_index": page_index,
                    "coordinate_unit": "pt",
                    "table_item_id": table_item_id,
                    "table_id": table_id,
                    "candidate_id": candidate_id,
                    "table_order": table_order,
                    "row_index": row_index,
                    "cell_ids": cell_ids,
                    "source_object_ids": flattened_source_ids,
                    "evidence_ids": flattened_evidence_ids,
                    "table_bbox": canonical_table_bbox,
                    "row_bbox": row_bbox,
                    "source_line_bbox": _source_alignment_bbox(
                        source_line["bbox"],
                        path="terminal_alignment.table_owned.source_line_bbox",
                    ),
                    "content_coverage": 1.0,
                    "source_character_geometry_coverage": 1.0,
                }
            )
    return tuple(matches[:2])


def _validate_table_owned_canonical_custody(
    selection: Mapping[str, Any],
    *,
    evidence_index: Mapping[str, Any],
    authoritative_table_views: Mapping[int, Sequence[Mapping[str, Any]]] | None,
    source_sha256: str,
) -> None:
    canonical_owner = _table_owned_canonical_owner(
        selection,
        expected_source_sha256=source_sha256,
    )
    matches = _table_owned_row_candidates(
        selection,
        evidence_index=evidence_index,
        authoritative_table_views=authoritative_table_views,
        source_sha256=source_sha256,
    )
    if len(matches) != 1 or dict(matches[0]) != dict(canonical_owner):
        raise ReadinessContractError(
            "terminal table-owned canonical custody differs"
        )


def _table_owned_record_references(value: Any, identifier: str) -> bool:
    if isinstance(value, Mapping):
        return any(
            _table_owned_record_references(child, identifier)
            for child in value.values()
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(
            _table_owned_record_references(child, identifier)
            for child in value
        )
    return value == identifier


def _expected_ir_after_table_owned_suppressions(
    configured_ir: Mapping[str, Any],
    suppressions: Sequence[
        tuple[_AlignmentOwnerLocation, Mapping[str, Any], Mapping[str, Any]]
    ],
) -> dict[str, Any]:
    """Project only the closed IR ownership removed with supplemental items."""

    expected = deepcopy(dict(configured_ir))
    prior_locations: list[_AlignmentOwnerLocation] = []
    for location, _configured_item, binding in suppressions:
        element_id = binding["ir_element_id"]
        element_matches = [
            (offset, element)
            for offset, element in enumerate(expected["elements"])
            if element.get("id") == element_id
        ]
        if len(element_matches) != 1:
            raise ReadinessContractError(
                "terminal table-owned IR owner is ambiguous"
            )
        element_offset, element = element_matches[0]
        removed_before = sum(
            1
            for prior in prior_locations
            if prior.page_offset == location.page_offset
            and prior.item_offset < location.item_offset
        )
        expected_source_position = location.item_offset - removed_before
        element_properties = element.get("properties")
        if (
            not isinstance(element_properties, Mapping)
            or element_properties.get("source_position")
            != expected_source_position
        ):
            raise ReadinessContractError(
                "terminal table-owned IR source position differs"
            )
        page_matches = [
            page
            for page in expected["pages"]
            if page.get("id") == element.get("page_id")
        ]
        if len(page_matches) != 1:
            raise ReadinessContractError(
                "terminal table-owned IR page custody differs"
            )
        page = page_matches[0]
        element_ids = page.get("element_ids")
        presentation_ids = page.get("presentation_element_ids")
        if (
            not isinstance(element_ids, list)
            or element_ids.count(element_id) != 1
            or not isinstance(presentation_ids, list)
            or presentation_ids.count(element_id) > 1
        ):
            raise ReadinessContractError(
                "terminal table-owned IR page ownership differs"
            )
        element_ids.remove(element_id)
        if element_id in presentation_ids:
            presentation_ids.remove(element_id)

        claimed_evidence_ids = element.get("evidence_ids") or []
        if (
            not isinstance(claimed_evidence_ids, list)
            or len(claimed_evidence_ids) != len(set(claimed_evidence_ids))
            or any(
                not isinstance(identifier, str) or not identifier
                for identifier in claimed_evidence_ids
            )
        ):
            raise ReadinessContractError(
                "terminal table-owned IR evidence custody differs"
            )
        owned_evidence = [
            record
            for record in expected["evidence"]
            if record.get("element_id") == element_id
        ]
        if {record.get("id") for record in owned_evidence} != set(
            claimed_evidence_ids
        ):
            raise ReadinessContractError(
                "terminal table-owned IR evidence binding differs"
            )
        if any(
            _table_owned_record_references(record, element_id)
            for record in expected["elements"]
            if record.get("id") != element_id
        ) or any(
            _table_owned_record_references(record, element_id)
            for record in expected.get("concerns", [])
        ):
            raise ReadinessContractError(
                "terminal table-owned IR owner has independent graph custody"
            )
        for region in expected.get("regions", []):
            if not _table_owned_record_references(region, element_id):
                continue
            region_element_ids = region.get("element_ids")
            if (
                region.get("role") != "page"
                or region.get("page_id") != element.get("page_id")
                or not isinstance(region_element_ids, list)
                or region_element_ids.count(element_id) != 1
            ):
                raise ReadinessContractError(
                    "terminal table-owned IR owner has independent graph custody"
                )
            region_element_ids.remove(element_id)

        page_element_id_set = {*element_ids, element_id}
        reading_relationship_offsets = [
            offset
            for offset, relationship in enumerate(expected["relationships"])
            if relationship.get("type") == "reading_before"
            and relationship.get("metadata") == {"basis": "legacy_reading_order"}
            and relationship.get("source_id") in page_element_id_set
            and relationship.get("target_id") in page_element_id_set
        ]
        for relationship in expected["relationships"]:
            if not _table_owned_record_references(relationship, element_id):
                continue
            if (
                relationship.get("type") != "reading_before"
                or relationship.get("metadata")
                != {"basis": "legacy_reading_order"}
                or relationship.get("evidence_ids") not in (None, [])
            ):
                raise ReadinessContractError(
                    "terminal table-owned IR owner has independent graph custody"
                )
        if any(
            _table_owned_record_references(relationship, evidence_id)
            for relationship in expected["relationships"]
            for evidence_id in claimed_evidence_ids
        ):
            raise ReadinessContractError(
                "terminal table-owned IR evidence has independent graph custody"
            )
        if reading_relationship_offsets:
            insertion_offset = min(reading_relationship_offsets)
            expected["relationships"] = [
                relationship
                for offset, relationship in enumerate(expected["relationships"])
                if offset not in set(reading_relationship_offsets)
            ]
            rebuilt_reading = [
                {
                    "id": stable_id(
                        "rel", "reading_before", source_id, target_id
                    ),
                    "type": "reading_before",
                    "source_id": source_id,
                    "target_id": target_id,
                    "evidence_ids": [],
                    "metadata": {"basis": "legacy_reading_order"},
                }
                for source_id, target_id in zip(
                    presentation_ids, presentation_ids[1:]
                )
            ]
            expected["relationships"][
                insertion_offset:insertion_offset
            ] = rebuilt_reading

        bbox_ids = {
            identifier
            for identifier in element.get("bbox_ids") or []
            if isinstance(identifier, str) and identifier
        }
        bbox_ids.update(
            record["bbox_id"]
            for record in owned_evidence
            if isinstance(record.get("bbox_id"), str)
            and record["bbox_id"]
        )
        expected["elements"].pop(element_offset)
        for remaining in expected["elements"]:
            if remaining.get("page_id") != element.get("page_id"):
                continue
            properties = remaining.get("properties")
            if not isinstance(properties, dict):
                continue
            source_position = properties.get("source_position")
            if (
                isinstance(source_position, int)
                and not isinstance(source_position, bool)
                and source_position > expected_source_position
            ):
                properties["source_position"] = source_position - 1
        expected["evidence"] = [
            record
            for record in expected["evidence"]
            if record.get("element_id") != element_id
        ]
        remaining_bbox_references = {
            identifier
            for remaining in expected["elements"]
            for identifier in remaining.get("bbox_ids") or []
            if isinstance(identifier, str) and identifier
        }
        remaining_bbox_references.update(
            record["bbox_id"]
            for record in expected["evidence"]
            if isinstance(record.get("bbox_id"), str)
            and record["bbox_id"]
        )
        remaining_bbox_references.update(
            identifier
            for region in expected.get("regions", [])
            for identifier in region.get("bbox_ids") or []
            if isinstance(identifier, str) and identifier
        )
        remaining_bbox_references.update(
            region["bbox_id"]
            for region in expected.get("regions", [])
            if isinstance(region.get("bbox_id"), str) and region["bbox_id"]
        )
        expected["bboxes"] = [
            bbox
            for bbox in expected["bboxes"]
            if bbox.get("id") not in bbox_ids
            or bbox.get("id") in remaining_bbox_references
        ]
        prior_locations.append(location)
    return expected


def _terminal_alignment_authorization(
    configured_predecessor: Mapping[str, Any],
    aligned_predecessor: Mapping[str, Any],
    *,
    replay_state_before: Mapping[str, Any],
    summary: Mapping[str, Any],
    evidence_authority: _ValidatedSourceAlignmentEvidence,
    forms_enabled: bool,
    outlines_enabled: bool,
    terminal_form_processing_summary: Mapping[str, Any] | None,
    terminal_outline_processing_summary: Mapping[str, Any] | None,
    authoritative_table_views: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None,
) -> dict[str, Any]:
    configured_public, configured_ir = _validate_predecessor_state_bundle(
        configured_predecessor
    )
    aligned_public, aligned_ir = _validate_predecessor_state_bundle(aligned_predecessor)
    source_sha256 = configured_public["document"]["sha256"]
    if aligned_public["document"]["sha256"] != source_sha256:
        raise ReadinessContractError("terminal aligned source identity differs")
    evidence_authority = _require_issued_source_alignment_authority(evidence_authority)
    if (
        evidence_authority.source_sha256 != source_sha256
        or evidence_authority.predecessor_sha256 != sha256_json(configured_predecessor)
    ):
        raise ReadinessContractError("terminal alignment evidence authority differs")
    try:
        evidence = json.loads(evidence_authority.evidence_json)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ReadinessContractError(
            "terminal alignment evidence authority is malformed"
        ) from exc
    evidence_index = _validate_source_alignment_evidence(
        evidence, expected_source_sha256=source_sha256
    )
    owner_binding_index = _source_alignment_owner_binding_index(evidence_authority)
    selections = _validate_terminal_alignment_summary(
        summary, source_sha256=source_sha256
    )
    for selection in selections:
        _validate_selection_against_source_evidence(
            selection, evidence_index=evidence_index
        )
        if _is_table_owned_source_suppression(selection):
            _validate_table_owned_canonical_custody(
                selection,
                evidence_index=evidence_index,
                authoritative_table_views=authoritative_table_views,
                source_sha256=source_sha256,
            )
    aligned_processing = aligned_public.get("processing")
    if (
        not isinstance(aligned_processing, Mapping)
        or not isinstance(aligned_processing.get("source_text_alignment"), Mapping)
        or _alignment_summary_semantic_payload(
            aligned_processing["source_text_alignment"]
        )
        != _alignment_summary_semantic_payload(summary)
    ):
        raise ReadinessContractError("terminal aligned predecessor summary differs")
    before_public, before_ir = _state_bundle_members(
        replay_state_before, path="pre_alignment_state"
    )
    validate_ir_bindings(before_ir, public_document=before_public)

    selections_by_owner: dict[str, Mapping[str, Any]] = {}
    owner_locations: dict[str, _AlignmentOwnerLocation] = {}
    item_selection_groups: dict[tuple[int, int], list[Mapping[str, Any]]] = {}
    canonical_block_selections: dict[str, list[Mapping[str, Any]]] = {}
    ir_element_selections: dict[str, list[Mapping[str, Any]]] = {}
    us08_owner_ids: set[str] = set()
    descriptor_ids: set[str] = set()
    canonical_block_ids: set[str] = set()
    canonical_block_owners: dict[str, str] = {}
    ir_element_ids: set[str] = set()
    ir_element_owners: dict[str, str] = {}
    table_owned_suppressions: list[
        tuple[_AlignmentOwnerLocation, Mapping[str, Any], Mapping[str, Any]]
    ] = []
    configured_canonical_pages = configured_public["canonical_presentation"]["pages"]
    for selection in selections:
        owner_id = selection["owner_id"]
        page_index = selection["page_index"]
        location, configured_item, configured_owner = _alignment_owner_at(
            configured_public,
            page_index=page_index,
            owner_id=owner_id,
            owner_type=selection["owner_type"],
        )
        binding = owner_binding_index.get((page_index, configured_item.get("id")))
        if (
            not isinstance(binding, Mapping)
            or binding["page_offset"] != location.page_offset
            or binding["item_offset"] != location.item_offset
        ):
            raise ReadinessContractError(
                "terminal alignment owner lacks frozen ID custody"
            )
        before_regions = [
            item["running_region"]
            for page in before_public["pages"]
            for item in page.get("items", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("running_region"), Mapping)
            and item["running_region"].get("physical_page_index") == page_index
            and item["running_region"].get("source_public_item_id")
            == configured_item.get("id")
        ]
        table_owned_suppression = _is_table_owned_source_suppression(selection)
        rejected = selection.get("rejected_ocr_alternative")
        if table_owned_suppression:
            aligned_owner_count = sum(
                1
                for page in aligned_public["pages"]
                if page.get("page_index") == page_index
                for item in page.get("items", [])
                if isinstance(item, Mapping) and item.get("id") == owner_id
            )
            configured_descriptor = configured_owner.get("running_region")
            configured_owner_type = (
                configured_descriptor.get("predecessor_type")
                if isinstance(configured_descriptor, Mapping)
                else configured_owner.get("type")
            )
            raw_ocr_text = configured_item.get("raw_ocr_text")
            confidence = configured_item.get("confidence")
            concerns = configured_item.get("parse_concerns")
            contributor = _table_owned_ocr_contributor(
                selection,
                expected_source_sha256=source_sha256,
            )
            if (
                aligned_owner_count != 0
                or selection["owner_type"] == "table_cell"
                or configured_owner_type != selection["owner_type"]
                or configured_owner.get("value") != selection["original_text"]
                or configured_item.get("source") != "ocr"
                or configured_item.get("label") != "ocr_text"
                or not isinstance(raw_ocr_text, str)
                or not raw_ocr_text
                or _source_alignment_skeleton(raw_ocr_text)
                != _source_alignment_skeleton(selection["original_text"])
                or isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
                or not 0.0 <= float(confidence) <= 1.0
                or not isinstance(concerns, Sequence)
                or isinstance(concerns, (str, bytes, bytearray))
                or "layout_omission_recovered_by_ocr" not in concerns
                or configured_item.get("ocr_contributor") != contributor
                or before_regions
                or not isinstance(rejected, Mapping)
                or rejected.get("text") != selection["original_text"]
                or rejected.get("source") != configured_item.get("source")
                or _canonical_bbox(
                    rejected.get("bbox"), path="terminal_alignment.rejected_bbox"
                )
                != _canonical_bbox(
                    selection["owner_bbox"],
                    path="terminal_alignment.selection_bbox",
                )
                or _canonical_bbox(
                    configured_owner.get("bbox"),
                    path="terminal_alignment.configured_owner_bbox",
                )
                != _canonical_bbox(
                    selection["owner_bbox"],
                    path="terminal_alignment.selection_bbox",
                )
                or rejected.get("confidence") != confidence
                or rejected.get("reason")
                != SOURCE_ALIGNMENT_TABLE_OWNED_REASON
            ):
                raise ReadinessContractError(
                    "terminal table-owned removed owner binding differs"
                )
            table_owned_suppressions.append((location, configured_item, binding))
        else:
            aligned_location, aligned_item, aligned_owner = _alignment_owner_at(
                aligned_public,
                page_index=page_index,
                owner_id=owner_id,
                owner_type=selection["owner_type"],
            )
            removed_before = sum(
                1
                for removed_location, _removed_item, _removed_binding
                in table_owned_suppressions
                if removed_location.page_offset == location.page_offset
                and removed_location.item_offset < location.item_offset
            )
            expected_aligned_location = _AlignmentOwnerLocation(
                location.page_offset,
                location.item_offset - removed_before,
                row=location.row,
                column=location.column,
            )
            if aligned_location != expected_aligned_location:
                raise ReadinessContractError(
                    "terminal alignment owner array position differs"
                )
        if (
            not table_owned_suppression
            and selection["method"] == "source_safe_native_token"
        ):
            rejected = selection["rejected_ocr_alternative"]
            if (
                not isinstance(rejected, Mapping)
                or rejected.get("text") != selection["original_text"]
                or rejected.get("source") != configured_item.get("source")
                or configured_item.get("source") != "ocr"
                or _canonical_bbox(
                    rejected.get("bbox"), path="terminal_alignment.rejected_bbox"
                )
                != _canonical_bbox(
                    selection["owner_bbox"],
                    path="terminal_alignment.selection_bbox",
                )
                or rejected.get("confidence") != configured_item.get("confidence")
                or rejected.get("reason")
                not in {"source_safe_native_conflict", "strict_source_subrange"}
            ):
                raise ReadinessContractError("terminal rejected OCR evidence differs")
        if table_owned_suppression:
            pass
        elif selection["owner_type"] == "table_cell":
            if (
                configured_owner.get("text") != selection["original_text"]
                or aligned_owner.get("text") != selection["selected_text"]
                or _canonical_bbox(
                    configured_owner.get("bbox"),
                    path="terminal_alignment.table_cell_bbox",
                )
                != _canonical_bbox(
                    selection["owner_bbox"],
                    path="terminal_alignment.selection_bbox",
                )
            ):
                raise ReadinessContractError(
                    "terminal table-cell alignment binding differs"
                )
        elif (
            _normalize_selected_owner(
                aligned_owner,
                configured_owner,
                selection=selection,
                source_sha256=source_sha256,
            )
            != configured_owner
        ):
            raise ReadinessContractError(
                "terminal alignment owner changed a non-content field"
            )
        if not table_owned_suppression:
            item_selection_groups.setdefault(
                (location.page_offset, location.item_offset), []
            ).append(selection)
        owner_block_ids = {binding["canonical_block_id"]}
        owner_ir_ids = {binding["ir_element_id"]}
        for descriptor in before_regions:
            us08_owner_ids.add(owner_id)
            descriptor_ids.add(descriptor["id"])
            if descriptor["source_method"] != "extracted_source_contribution" and (
                descriptor["canonical_block_id"] != binding["canonical_block_id"]
                or descriptor["source_element_id"] != binding["ir_element_id"]
            ):
                raise ReadinessContractError(
                    "terminal direct alignment descriptor ID custody differs"
                )
        if not table_owned_suppression:
            for block_id in owner_block_ids:
                canonical_block_selections.setdefault(block_id, []).append(selection)
            for element_id in owner_ir_ids:
                ir_element_selections.setdefault(element_id, []).append(selection)
        canonical_block_ids.update(owner_block_ids)
        if before_regions:
            for block_id in owner_block_ids:
                prior_owner_id = canonical_block_owners.setdefault(block_id, owner_id)
                if prior_owner_id != owner_id:
                    raise ReadinessContractError(
                        "terminal alignment canonical owner is shared"
                    )
        ir_element_ids.update(owner_ir_ids)
        if before_regions:
            for element_id in owner_ir_ids:
                prior_owner_id = ir_element_owners.setdefault(element_id, owner_id)
                if prior_owner_id != owner_id:
                    raise ReadinessContractError(
                        "terminal alignment IR owner is shared"
                    )
        selections_by_owner[owner_id] = selection
        owner_locations[owner_id] = location

    ordered_locations = [
        (
            owner_locations[selection["owner_id"]].page_offset,
            owner_locations[selection["owner_id"]].item_offset,
            owner_locations[selection["owner_id"]].row
            if owner_locations[selection["owner_id"]].row is not None
            else -1,
            owner_locations[selection["owner_id"]].column
            if owner_locations[selection["owner_id"]].column is not None
            else -1,
        )
        for selection in selections
    ]
    if ordered_locations != sorted(ordered_locations):
        raise ReadinessContractError(
            "terminal alignment selection traversal order differs"
        )

    normalized_public = deepcopy(dict(aligned_public))
    for (page_offset, item_offset), item_selections in item_selection_groups.items():
        configured_item = configured_public["pages"][page_offset]["items"][item_offset]
        removed_before = sum(
            1
            for removed_location, _removed_item, _removed_binding
            in table_owned_suppressions
            if removed_location.page_offset == page_offset
            and removed_location.item_offset < item_offset
        )
        aligned_item = normalized_public["pages"][page_offset]["items"][
            item_offset - removed_before
        ]
        if item_selections[0]["owner_type"] == "table_cell":
            normalized_item = _normalize_selected_table(
                aligned_item,
                configured_item,
                selections=item_selections,
                source_sha256=source_sha256,
            )
        elif len(item_selections) == 1:
            normalized_item = _normalize_selected_owner(
                aligned_item,
                configured_item,
                selection=item_selections[0],
                source_sha256=source_sha256,
            )
        else:
            raise ReadinessContractError(
                "terminal direct owner has multiple selections"
            )
        normalized_public["pages"][page_offset]["items"][
            item_offset - removed_before
        ] = normalized_item
    normalized_processing = normalized_public.get("processing")
    if not isinstance(normalized_processing, dict):
        raise ReadinessContractError("terminal aligned processing differs")
    normalized_processing.pop("source_text_alignment")
    configured_processing = configured_public.get("processing")
    if not isinstance(configured_processing, Mapping):
        configured_processing = {}
    if forms_enabled:
        initial_form = configured_processing.get("form_semantics")
        aligned_form = normalized_processing.get("form_semantics")
        if (
            not isinstance(initial_form, Mapping)
            or not isinstance(aligned_form, Mapping)
            or not isinstance(terminal_form_processing_summary, Mapping)
            or aligned_form
            != combine_terminal_form_processing_summaries(
                initial_form, terminal_form_processing_summary
            )
        ):
            raise ReadinessContractError("terminal form replay processing differs")
        normalized_processing["form_semantics"] = deepcopy(dict(initial_form))
    elif terminal_form_processing_summary is not None:
        raise ReadinessContractError("disabled terminal form summary is present")
    if outlines_enabled:
        initial_outline = configured_processing.get("outline_structure")
        aligned_outline = normalized_processing.get("outline_structure")
        if (
            not isinstance(initial_outline, Mapping)
            or not isinstance(aligned_outline, Mapping)
            or not isinstance(terminal_outline_processing_summary, Mapping)
            or aligned_outline
            != combine_terminal_outline_processing_summaries(
                initial_outline, terminal_outline_processing_summary
            )
        ):
            raise ReadinessContractError("terminal outline replay processing differs")
        normalized_processing["outline_structure"] = deepcopy(dict(initial_outline))
    elif terminal_outline_processing_summary is not None:
        raise ReadinessContractError("disabled terminal outline summary is present")
    if not normalized_processing:
        normalized_public.pop("processing")
    expected_public = deepcopy(dict(configured_public))
    for location, configured_item, binding in sorted(
        table_owned_suppressions,
        key=lambda value: (value[0].page_offset, value[0].item_offset),
        reverse=True,
    ):
        expected_items = expected_public["pages"][location.page_offset]["items"]
        if (
            location.item_offset >= len(expected_items)
            or expected_items[location.item_offset] != configured_item
        ):
            raise ReadinessContractError(
                "terminal table-owned public removal position differs"
            )
        expected_items.pop(location.item_offset)
        block_id = binding["canonical_block_id"]
        block_matches = [
            (page, offset)
            for page in expected_public["canonical_presentation"]["pages"]
            for offset, block in enumerate(page["blocks"])
            if block.get("id") == block_id
        ]
        if len(block_matches) != 1:
            raise ReadinessContractError(
                "terminal table-owned canonical projection is ambiguous"
            )
        block_page, block_offset = block_matches[0]
        block_page["blocks"].pop(block_offset)
    for page in expected_public["canonical_presentation"]["pages"]:
        _rebuild_canonical_views(page)
    _rebuild_canonical_document_views(expected_public["canonical_presentation"])
    configured_blocks = {
        block["id"]: block
        for page in configured_canonical_pages
        for block in page["blocks"]
    }
    for page in normalized_public["canonical_presentation"]["pages"]:
        for block in page["blocks"]:
            block_selections = canonical_block_selections.get(block["id"])
            if not block_selections:
                continue
            configured_block = configured_blocks.get(block["id"])
            if not isinstance(configured_block, Mapping):
                raise ReadinessContractError(
                    "terminal alignment canonical owner block is absent"
                )
            normalized_block = _normalize_alignment_scalar_record(
                block,
                configured_block,
                selections=block_selections,
                fields=frozenset({"text", "markdown"}),
                path="terminal_alignment.canonical",
            )
            block.clear()
            block.update(normalized_block)
        _rebuild_canonical_views(page)
    _rebuild_canonical_document_views(normalized_public["canonical_presentation"])
    if strict_json_bytes(normalized_public) != strict_json_bytes(expected_public):
        raise ReadinessContractError(
            "terminal aligned predecessor public drift is unauthorized"
        )

    normalized_ir = deepcopy(dict(aligned_ir))
    configured_elements = {
        element["id"]: element for element in configured_ir["elements"]
    }
    for element in normalized_ir["elements"]:
        element_selections = ir_element_selections.get(element["id"])
        if not element_selections:
            continue
        configured_element = configured_elements.get(element["id"])
        if not isinstance(configured_element, Mapping):
            raise ReadinessContractError(
                "terminal alignment IR owner element is absent"
            )
        properties = element.get("properties")
        configured_properties = configured_element.get("properties")
        if isinstance(properties, dict) and isinstance(configured_properties, Mapping):
            legacy_item = properties.get("legacy_item")
            configured_legacy = configured_properties.get("legacy_item")
            if isinstance(legacy_item, Mapping) and isinstance(
                configured_legacy, Mapping
            ):
                direct_selections = [
                    selection
                    for selection in element_selections
                    if selection["owner_type"] != "table_cell"
                    and configured_legacy.get("id") == selection["owner_id"]
                ]
                if len(direct_selections) == 1:
                    properties["legacy_item"] = _normalize_selected_owner(
                        legacy_item,
                        configured_legacy,
                        selection=direct_selections[0],
                        source_sha256=source_sha256,
                    )
        normalized_element = _normalize_alignment_scalar_record(
            element,
            configured_element,
            selections=element_selections,
            fields=frozenset({"value", "markdown"}),
            path="terminal_alignment.ir_owner",
        )
        element.clear()
        element.update(normalized_element)
    expected_ir = _expected_ir_after_table_owned_suppressions(
        configured_ir, table_owned_suppressions
    )
    if strict_json_bytes(normalized_ir) != strict_json_bytes(expected_ir):
        raise ReadinessContractError(
            "terminal aligned predecessor IR drift is unauthorized"
        )
    return {
        "source_sha256": source_sha256,
        "selections": selections_by_owner,
        "owner_locations": owner_locations,
        "us08_owner_ids": frozenset(us08_owner_ids),
        "descriptor_ids": frozenset(descriptor_ids),
        "canonical_block_ids": frozenset(canonical_block_ids),
        "canonical_block_owners": canonical_block_owners,
        "ir_element_ids": frozenset(ir_element_ids),
        "ir_element_owners": ir_element_owners,
    }


def _validate_terminal_plan_transition(
    before: Sequence[ExtractedContributionPlan],
    after: Sequence[ExtractedContributionPlan],
    *,
    selected_owner_ids: frozenset[str],
) -> None:
    validate_extracted_plan_ledger(before)
    validate_extracted_plan_ledger(after)
    if len(before) != len(after):
        raise ReadinessContractError("terminal extracted plan coverage differs")
    authorized_fields = {
        "owner_sha256_before",
        "owner_sha256_after",
        "predecessor_canonical",
        "residual_canonical",
        "predecessor_sha256",
        "removed_interval_sha256",
        "ordered_plan_sha256",
        "residual_sha256",
    }
    for before_plan, after_plan in zip(before, after):
        if before_plan.owner_public_item_id != after_plan.owner_public_item_id:
            raise ReadinessContractError("terminal extracted plan owner differs")
        for field in before_plan.__dataclass_fields__:
            if (
                field in authorized_fields
                and before_plan.owner_public_item_id in selected_owner_ids
            ):
                continue
            if getattr(before_plan, field) != getattr(after_plan, field):
                raise ReadinessContractError(
                    "terminal extracted plan graph identity differs"
                )


def _terminal_us08_replay_identity(
    public_document: Mapping[str, Any],
    *,
    normalized_descriptor_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return only the ordered US08 identity frozen by terminal policy."""

    page_identities: list[dict[str, Any]] = []
    regions: list[dict[str, Any]] = []
    replacements = normalized_descriptor_hashes or {}
    pages = public_document.get("pages")
    if not isinstance(pages, list):
        raise ReadinessContractError("terminal replay pages differ")
    for page_offset, page in enumerate(pages):
        if not isinstance(page, Mapping):
            raise ReadinessContractError("terminal replay page differs")
        identity = page.get("page_identity")
        if not isinstance(identity, Mapping):
            raise ReadinessContractError("terminal replay page identity is absent")
        page_identities.append(deepcopy(dict(identity)))
        items = page.get("items")
        if not isinstance(items, list):
            raise ReadinessContractError("terminal replay items differ")
        for item_offset, item in enumerate(items):
            descriptor = (
                item.get("running_region") if isinstance(item, Mapping) else None
            )
            if not isinstance(descriptor, Mapping):
                continue
            normalized_descriptor = deepcopy(dict(descriptor))
            descriptor_id = normalized_descriptor.get("id")
            if descriptor_id in replacements:
                normalized_descriptor["predecessor_item_sha256"] = replacements[
                    descriptor_id
                ]
            regions.append(
                {
                    "page_offset": page_offset,
                    "item_offset": item_offset,
                    "item_id": item.get("id"),
                    "descriptor": normalized_descriptor,
                }
            )
    return {"pages": page_identities, "regions": regions}


def _validate_terminal_replay_graph_identity(
    before_state: Mapping[str, Any],
    after_state: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any] | None,
    terminal_processing_summary: Mapping[str, Any],
) -> None:
    before_public, _before_ir = _state_bundle_members(
        before_state, path="pre_alignment_state"
    )
    after_public, _after_ir = _state_bundle_members(after_state, path="replayed_state")
    before_summary = before_public["processing"]["running_regions"]
    if any(
        terminal_processing_summary.get(field) != before_summary[field]
        for field in PROCESSING_SUMMARY_FIELDS
        if field not in {"extraction_ms", "projection_ms", "total_ms"}
    ):
        raise ReadinessContractError(
            "terminal running-region non-timing summary differs"
        )
    expected_after_summary = combine_terminal_processing_summaries(
        before_summary, terminal_processing_summary
    )
    if after_public["processing"]["running_regions"] != expected_after_summary:
        raise ReadinessContractError("terminal running-region timing differs")

    before_descriptors = {
        item["running_region"]["id"]: item["running_region"]
        for page in before_public["pages"]
        for item in page.get("items", [])
        if isinstance(item, Mapping) and isinstance(item.get("running_region"), Mapping)
    }
    descriptor_ids = (
        frozenset() if authorization is None else authorization["descriptor_ids"]
    )
    normalized_hashes = {
        descriptor_id: before_descriptors[descriptor_id]["predecessor_item_sha256"]
        for descriptor_id in descriptor_ids
        if descriptor_id in before_descriptors
    }
    before_identity = _terminal_us08_replay_identity(before_public)
    after_identity = _terminal_us08_replay_identity(
        after_public, normalized_descriptor_hashes=normalized_hashes
    )
    if strict_json_bytes(after_identity) != strict_json_bytes(before_identity):
        raise ReadinessContractError("terminal replay graph identity differs")


@dataclass(frozen=True, slots=True)
class TerminalReplayWitness:
    """Execute strip/align/replay with closed drift authorization and rollback."""

    configured_predecessor: Mapping[str, Any]
    replay_state_before: Mapping[str, Any]
    replay_state_after: Mapping[str, Any]
    terminal_processing_summary: Mapping[str, Any]
    forms_enabled: bool
    outlines_enabled: bool
    aligned_predecessor: Mapping[str, Any] | None = None
    alignment_summary: Mapping[str, Any] | None = None
    alignment_evidence: _ValidatedSourceAlignmentEvidence | None = None
    authoritative_table_views: Mapping[
        int, Sequence[Mapping[str, Any]]
    ] | None = None
    terminal_form_processing_summary: Mapping[str, Any] | None = None
    terminal_outline_processing_summary: Mapping[str, Any] | None = None
    fail_at: Literal["none", "alignment", "running_replay", "identity", "canonical"] = (
        "none"
    )
    pre_alignment_plans: Sequence[ExtractedContributionPlan] = ()
    replay_plans: Sequence[ExtractedContributionPlan] = ()

    def execute(self) -> ProjectionTransactionResult:
        configured_predecessor = deepcopy(dict(self.configured_predecessor))
        replay_snapshot = deepcopy(dict(self.replay_state_before))
        try:
            _validate_predecessor_state_bundle(configured_predecessor)
            _validate_projected_state_bundle(
                replay_snapshot,
                predecessor=configured_predecessor,
                plans=self.pre_alignment_plans,
            )
        except Exception as exc:
            if isinstance(exc, ReadinessContractError):
                raise
            raise ReadinessContractError(
                "pre-alignment replay snapshot validation failed"
            ) from exc
        events = terminal_reentry_order(
            forms_enabled=self.forms_enabled, outlines_enabled=self.outlines_enabled
        )
        if self.fail_at not in {
            "none",
            "alignment",
            "running_replay",
            "identity",
            "canonical",
        }:
            raise ReadinessContractError("terminal replay failure stage differs")

        def rollback(stop_event: str) -> ProjectionTransactionResult:
            stop = events.index(stop_event) + 1
            return ProjectionTransactionResult(
                deepcopy(replay_snapshot),
                False,
                (*events[:stop], "restore_pre_alignment_document"),
            )

        if self.fail_at == "alignment":
            return rollback("round_trip_once")
        if self.fail_at == "running_replay":
            return rollback("replay_running_regions")

        try:
            authorization: Mapping[str, Any] | None
            replay_predecessor: Mapping[str, Any]
            if self.aligned_predecessor is None:
                if (
                    self.alignment_summary is not None
                    or self.alignment_evidence is not None
                    or self.authoritative_table_views is not None
                    or self.terminal_form_processing_summary is not None
                    or self.terminal_outline_processing_summary is not None
                    or self.forms_enabled
                    or self.outlines_enabled
                ):
                    raise ReadinessContractError(
                        "terminal replay authority lacks an aligned predecessor"
                    )
                authorization = None
                replay_predecessor = configured_predecessor
            else:
                if not isinstance(self.alignment_summary, Mapping) or not isinstance(
                    self.alignment_evidence,
                    _ValidatedSourceAlignmentEvidence,
                ):
                    raise ReadinessContractError(
                        "terminal aligned predecessor lacks authorization"
                    )
                replay_predecessor = deepcopy(dict(self.aligned_predecessor))
                authorization = _terminal_alignment_authorization(
                    configured_predecessor,
                    replay_predecessor,
                    replay_state_before=replay_snapshot,
                    summary=self.alignment_summary,
                    evidence_authority=self.alignment_evidence,
                    forms_enabled=self.forms_enabled,
                    outlines_enabled=self.outlines_enabled,
                    terminal_form_processing_summary=(
                        self.terminal_form_processing_summary
                    ),
                    terminal_outline_processing_summary=(
                        self.terminal_outline_processing_summary
                    ),
                    authoritative_table_views=self.authoritative_table_views,
                )
            replay_public, replay_ir = _validate_projected_state_bundle(
                self.replay_state_after,
                predecessor=replay_predecessor,
                plans=self.replay_plans,
            )
            _validate_terminal_plan_transition(
                self.pre_alignment_plans,
                self.replay_plans,
                selected_owner_ids=(
                    frozenset()
                    if authorization is None
                    else frozenset(authorization["selections"])
                ),
            )
            _validate_terminal_replay_graph_identity(
                replay_snapshot,
                self.replay_state_after,
                authorization=authorization,
                terminal_processing_summary=self.terminal_processing_summary,
            )
        except Exception:  # noqa: BLE001 - transaction must fail closed
            return rollback("validate_replay_identity")
        if self.fail_at == "identity":
            return rollback("validate_replay_identity")
        if self.fail_at == "canonical":
            return rollback("canonical_dry_run")
        try:
            validate_ir_bindings(replay_ir, public_document=replay_public)
        except Exception:  # noqa: BLE001 - transaction must fail closed
            return rollback("validate_final_ir")
        return ProjectionTransactionResult(
            deepcopy(dict(self.replay_state_after)), True, events
        )


def contract_self_check() -> str:
    """Exercise selection, conflict, grammar, and terminal-order invariants."""

    assert normalize_detected_label("Page 2 of 28") == "2 of 28"
    assert normalize_detected_label("2 / 28") == "2/28"
    assert normalize_detected_label("PAGE | 7") == "7"
    evidence = {
        "method": "native_printed_label",
        "reader": "pdfplumber",
        "page_index": 1,
        "public_item_id": "item-1",
        "public_path": ["pages", 0, "items", 0],
        "element_id": "element-1",
        "bbox_id": "bbox-1",
        "evidence_ids": ["evidence-1"],
        "source_object_ids": ["word-1"],
    }
    identity = {
        "schema_version": SCHEMA_VERSION,
        "policy_id": POLICY_ID,
        "page_id": "page-1",
        "physical_page_index": 1,
        "embedded_label": "8",
        "detected_printed_label": "7",
        "visible_text": "7",
        "display_label": "8",
        "display_source": "embedded_label",
        "evidence_bbox": {
            "x": 290.0,
            "y": 760.0,
            "width": 8.0,
            "height": 10.0,
            "unit": "pt",
        },
        "evidence_source": evidence,
        "confidence": {
            "scope": "source_metadata",
            "score": 1.0,
            "unavailable_reason": None,
        },
        "concern_codes": ["page_identity_source_conflict"],
    }
    public_page = {
        "page_index": 1,
        "page_number": 1,
        "page_label": "1",
    }
    validate_page_identity(identity, public_page=public_page)
    physical_identity = {
        "schema_version": SCHEMA_VERSION,
        "policy_id": POLICY_ID,
        "page_id": "page-1",
        "physical_page_index": 1,
        "embedded_label": None,
        "detected_printed_label": None,
        "visible_text": None,
        "display_label": "1",
        "display_source": "physical",
        "evidence_bbox": None,
        "evidence_source": {
            "method": "physical_page_index",
            "reader": "configured_predecessor",
            "page_index": 1,
            "public_item_id": None,
            "public_path": [],
            "element_id": None,
            "bbox_id": None,
            "evidence_ids": [],
            "source_object_ids": [],
        },
        "confidence": {
            "scope": "unavailable",
            "score": None,
            "unavailable_reason": "page_identity_display_fallback_physical",
        },
        "concern_codes": ["page_identity_display_unsafe"],
    }
    validate_page_identity(
        physical_identity,
        public_page={**public_page, "page_label": "<unsafe>"},
    )
    cluster_top = validate_effective_bottom_cluster(
        (
            {
                "id": "cluster-nav",
                "presentation_index": 10,
                "bbox": {
                    "x": 72.0,
                    "y": 650.0,
                    "width": 60.0,
                    "height": 12.0,
                    "unit": "pt",
                },
                "navigation_cue": "HOME",
                "normalized_label": None,
                "claimed": False,
            },
            {
                "id": "cluster-middle",
                "presentation_index": 11,
                "bbox": {
                    "x": 180.0,
                    "y": 650.0,
                    "width": 60.0,
                    "height": 12.0,
                    "unit": "pt",
                },
                "navigation_cue": None,
                "normalized_label": None,
                "claimed": False,
            },
            {
                "id": "cluster-label",
                "presentation_index": 12,
                "bbox": {
                    "x": 300.0,
                    "y": 650.0,
                    "width": 20.0,
                    "height": 12.0,
                    "unit": "pt",
                },
                "navigation_cue": None,
                "normalized_label": "80",
                "claimed": False,
            },
        ),
        remaining_body_bboxes=(
            {"x": 72.0, "y": 100.0, "width": 468.0, "height": 500.0, "unit": "pt"},
        ),
        page_width=612.0,
        page_height=792.0,
        candidate_cut_count=1,
    )
    if cluster_top != 650.0:
        raise ReadinessContractError("effective-bottom cluster witness drifted")
    owner = {"id": "owner-1", "type": "text", "value": "RUNNING HEADER\nBody content"}
    owner_hash = sha256_json(owner)
    source_contribution = "NIST AMS 100-76 February 2026"
    fragment_one = "NIST AMS 100-76"
    fragment_two = "February 2026"
    intervening = "CHART BODY\n"
    predecessor_canonical = (
        fragment_one + "\n" + intervening + fragment_two + "\nBody content\n"
    )
    second_start = len((fragment_one + "\n" + intervening).encode("utf-8"))
    plan = build_extracted_contribution_plan(
        physical_page_index=1,
        owner_public_item_id="owner-1",
        owner_sha256=owner_hash,
        predecessor_canonical=predecessor_canonical,
        source_text=source_contribution,
        presentation_fragments=(fragment_one, fragment_two),
        delimiters=("\n", "\n"),
        predecessor_intervals=(
            (0, len((fragment_one + "\n").encode("utf-8"))),
            (second_start, second_start + len((fragment_two + "\n").encode("utf-8"))),
        ),
        source_span_groups=(
            ((0, 15),),
            ((16, len(source_contribution.encode("utf-8"))),),
        ),
    )
    if plan.execute() != "CHART BODY\nBody content\n":
        raise ReadinessContractError("extracted contribution witness drifted")
    replay_events = terminal_reentry_order(forms_enabled=True, outlines_enabled=True)
    if replay_events[-1] != "commit":
        raise ReadinessContractError("terminal replay ordering drifted")
    return sha256_json(
        {
            "policy_id": POLICY_ID,
            "resource_limits": dict(RESOURCE_LIMITS),
            "page_identity_fields": PAGE_IDENTITY_FIELDS,
            "running_region_fields": RUNNING_REGION_FIELDS,
            "source_report_fields": SOURCE_REPORT_FIELDS,
            "terminal_order": replay_events,
        }
    )


__all__ = [
    "BBOX_FIELDS",
    "BOUNDARY_CANDIDATE_FIELDS",
    "CODE_CUSTODY_FIELDS",
    "CODE_CUSTODY_RECORD_FIELDS",
    "COMPARISON_LEDGER_FIELDS",
    "CONCERN_CODES",
    "CONFIDENCE_FIELDS",
    "COORDINATE_SYSTEM_ID",
    "DEPENDENCY_CUSTODY_FIELDS",
    "DEPENDENCY_LOCAL_TOOL_FIELDS",
    "DEPENDENCY_MANIFEST_PATHS",
    "DEPENDENCY_PACKAGE_FIELDS",
    "DEPENDENCY_REQUIRED_LOCAL_TOOLS",
    "DEPENDENCY_REQUIRED_PYTHON_PACKAGES",
    "DEPENDENCY_RUNTIME_FIELDS",
    "DISPLAY_SOURCES",
    "EFFECTIVE_CLUSTER_ITEM_FIELDS",
    "EVIDENCE_SOURCE_FIELDS",
    "EXTRACTED_EVIDENCE_CONFIDENCE",
    "EXTRACTED_EVIDENCE_FIELDS",
    "EXTRACTED_EVIDENCE_METADATA_FIELDS",
    "EXTRACTED_NATIVE_MIN_CANDIDATE_AREA_COVERAGE",
    "EXTRACTED_NATIVE_MIN_CHILD_AREA_COVERAGE",
    "FAILED_METRICS_ARTIFACT_PATTERN",
    "FINAL_METRICS_ARTIFACT_PATH",
    "FORM_PROCESSING_SUMMARY_FIELDS",
    "ISOLATED_ALLOCATION_SAMPLES",
    "ISOLATED_ALLOCATION_WARMUPS",
    "ISOLATED_LATENCY_SAMPLES",
    "ISOLATED_LATENCY_WARMUPS",
    "ISOLATED_PROJECTION_P95_SECONDS",
    "ISOLATED_SOURCE_EXTRACTION_P95_SECONDS",
    "LABEL_CANDIDATE_FIELDS",
    "MAXIMUM_PAGE_FIXTURE_ID",
    "MAXIMUM_PAGE_WORKLOAD",
    "MAXIMUM_PAGE_WORKLOAD_FIELDS",
    "MAX_BOUNDARY_CANDIDATES_PER_DOCUMENT",
    "MAX_BOUNDARY_CANDIDATES_PER_PAGE",
    "MAX_CANDIDATE_TEXT_UTF8_BYTES",
    "MAX_COMPARISONS_PER_DOCUMENT",
    "MAX_COMPARISONS_PER_PAGE",
    "MAX_CONCERNS_PER_DOCUMENT",
    "MAX_CONCERNS_PER_PAGE",
    "MAX_EXTRACTED_CONTRIBUTIONS_PER_DOCUMENT",
    "MAX_EXTRACTED_CONTRIBUTIONS_PER_PAGE",
    "MAX_EXTRACTED_CONTRIBUTION_UTF8_BYTES",
    "MAX_EXTRACTED_INTERVALS_PER_CONTRIBUTION",
    "MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_DOCUMENT",
    "MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_PAGE",
    "MAX_LABEL_CANDIDATES_PER_PAGE",
    "MAX_LABEL_UTF8_BYTES",
    "MAX_LIVE_SOURCE_ALIGNMENT_AUTHORITIES",
    "MAX_LIVE_SOURCE_PROJECTION_AUTHORITIES",
    "MAX_PAGES_PER_DOCUMENT",
    "MAX_PAGE_IDENTITY_BYTES",
    "MAX_PRINTED_LABEL_CMYK_CUSTODY_CHANNEL_DELTA",
    "MAX_PRINTED_LABEL_NON_STROKING_FILLS",
    "MAX_PRINTED_LABEL_PAGE_DIMENSION_PT",
    "MAX_PRINTED_LABEL_RENDER_DIMENSION_PX",
    "MAX_PRINTED_LABEL_RENDER_PIXELS",
    "MAX_PRINTED_LABEL_TEXT_OBJECTS",
    "MAX_PRINTED_LABEL_TEXT_OBJECT_SCAN",
    "MAX_PUBLIC_PATH_SEGMENTS",
    "MAX_REFERENCES_PER_RECORD",
    "MAX_REPETITION_GROUPS_PER_DOCUMENT",
    "MAX_REPETITION_MEMBERS",
    "MAX_REPORT_BYTES",
    "MAX_RUNNING_DESCRIPTOR_BYTES",
    "MAX_RUNNING_REGIONS_PER_DOCUMENT",
    "MAX_RUNNING_REGIONS_PER_PAGE",
    "MAX_SOURCE_CHARACTERS_PER_DOCUMENT",
    "MAX_SOURCE_CHARACTERS_PER_PAGE",
    "MAX_SOURCE_PDF_BYTES",
    "MAX_SOURCE_WORDS_PER_DOCUMENT",
    "MAX_SOURCE_WORDS_PER_PAGE",
    "MAX_VISIBLE_TEXT_UTF8_BYTES",
    "METRICS_ARTIFACT_FIELDS",
    "METRICS_FAILURE_FIELDS",
    "NATIVE_LABEL_MAX_VERTICAL_CENTER_DELTA_RATIO",
    "NATIVE_LABEL_MIN_CANDIDATE_AREA_COVERAGE",
    "OFFLINE_ENVIRONMENT",
    "OFFLINE_ENVIRONMENT_FIELDS",
    "OUTLINE_POLICY_ID",
    "OUTLINE_PROCESSING_SUMMARY_FIELDS",
    "OUTPUT_IDENTITY_FIELDS",
    "OUTPUT_SAMPLE_FIELDS",
    "OUTPUT_SIZES_FIELDS",
    "OUTPUT_VARIANTS",
    "PAGE_IDENTITY_CONCERN_CODES",
    "PAGE_IDENTITY_FIELDS",
    "PAIRED_CASES",
    "PAIRED_FIXED_CEILINGS_SECONDS",
    "PAIRED_STATE_ORDER",
    "PAIRED_WORKER_COUNT",
    "PEAK_MEMORY_DELTA_CEILING_BYTES",
    "PERFORMANCE_TARGETS",
    "POLICY_ID",
    "PRINTED_LABEL_MAX_FORM_DEPTH",
    "PRINTED_LABEL_MIN_RGB_CHANNEL_DELTA",
    "PRINTED_LABEL_PAINTED_FILL_RENDER_MODES",
    "PRINTED_LABEL_RENDER_SCALE_PX_PER_PT",
    "PROCESSING_STATUSES",
    "PROCESSING_SUMMARY_FIELDS",
    "PROJECTED_CONCERN_FIELDS",
    "PROJECTION_DOCUMENT_DEADLINE_SECONDS",
    "PROJECTION_PAGE_DEADLINE_SECONDS",
    "PUBLIC_PAGE_IDENTITY_KEY",
    "PUBLIC_RUNNING_REGION_KEYS",
    "REPORT_STATUSES",
    "REPORT_VERSION",
    "RESOURCE_LIMITS",
    "ROLE_TYPE_SCOPE",
    "RUNNING_REGION_FIELDS",
    "RUNNING_REGION_ROLES",
    "RUNNING_REGION_SIDECAR_FIELDS",
    "SCHEMA_VERSION",
    "SOURCE_ALIGNMENT_EVIDENCE_BBOX_FIELDS",
    "SOURCE_ALIGNMENT_EVIDENCE_CHARACTER_FIELDS",
    "SOURCE_ALIGNMENT_EVIDENCE_FIELDS",
    "SOURCE_ALIGNMENT_EVIDENCE_LINE_FIELDS",
    "SOURCE_ALIGNMENT_EVIDENCE_PAGE_FIELDS",
    "SOURCE_ALIGNMENT_EVIDENCE_TYPE1_FIELDS",
    "SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_FIELDS",
    "SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_POLICY_ID",
    "SOURCE_ALIGNMENT_OCR_CONTRIBUTOR_SCHEMA_VERSION",
    "SOURCE_ALIGNMENT_POLICY_ID",
    "SOURCE_ALIGNMENT_REJECTED_OCR_FIELDS",
    "SOURCE_ALIGNMENT_SELECTION_FIELDS",
    "SOURCE_ALIGNMENT_SOURCE_ROLE_FIELDS",
    "SOURCE_ALIGNMENT_SUMMARY_FIELDS",
    "SOURCE_ALIGNMENT_TABLE_OWNED_CANONICAL_OWNER_FIELDS",
    "SOURCE_ALIGNMENT_TABLE_OWNED_POLICY_ID",
    "SOURCE_ALIGNMENT_TABLE_OWNED_REASON",
    "SOURCE_ALIGNMENT_TABLE_OWNED_REJECTED_OCR_FIELDS",
    "SOURCE_ALIGNMENT_TABLE_TRACE_FIELDS",
    "SOURCE_ALIGNMENT_TRACE_FIELDS",
    "SOURCE_COUNT_FIELDS",
    "SOURCE_EXTRACTION_DEADLINE_SECONDS",
    "SOURCE_METHODS",
    "SOURCE_PAGE_FIELDS",
    "SOURCE_REPORT_FIELDS",
    "WHOLE_OUTPUT_TIMING_PATHS",
    "ExtractedContributionPlan",
    "IdempotenceWitness",
    "ProjectionTransactionResult",
    "ReadinessContractError",
    "TerminalReplayWitness",
    "boundary_candidate_id",
    "build_extracted_contribution_plan",
    "combine_terminal_form_processing_summaries",
    "combine_terminal_outline_processing_summaries",
    "combine_terminal_processing_summaries",
    "contract_self_check",
    "execute_flag_off_witness",
    "execute_paired_performance_harness",
    "execute_transaction_witness",
    "expected_candidate_role",
    "extracted_evidence_record_id",
    "extracted_plan_json_bytes",
    "inclusive_nearest_rank",
    "isolated_measurement_protocol",
    "label_candidate_id",
    "metrics_artifact_semantic_payload",
    "normalize_detected_label",
    "normalize_embedded_label",
    "normalize_pdf_non_stroking_fill",
    "normalize_ru_maxrss",
    "paired_worker_plan",
    "predecessor_item_sha256",
    "prepare_flag_off_witness",
    "prepare_source_alignment_evidence",
    "prepare_source_projection_authority",
    "resolve_public_path",
    "sha256_json",
    "source_alignment_evidence_id",
    "source_alignment_ocr_contributor_id",
    "source_alignment_selection_id",
    "source_report_semantic_payload",
    "stable_id",
    "strict_json_bytes",
    "strip_complete_running_region_sidecars",
    "summarize_isolated_measurement",
    "summarize_paired_performance",
    "terminal_reentry_order",
    "validate_bbox",
    "validate_boundary_method_proof",
    "validate_canonical_binding",
    "validate_comparison_ledger",
    "validate_confidence",
    "validate_deadline_window",
    "validate_effective_bottom_cluster",
    "validate_evidence_source",
    "validate_extracted_candidate_eligibility",
    "validate_extracted_contribution",
    "validate_extracted_evidence_record",
    "validate_extracted_evidence_strip",
    "validate_extracted_plan_ledger",
    "validate_form_processing_summary",
    "validate_ir_bindings",
    "validate_isolated_measurement_protocol",
    "validate_metrics_artifact_custody",
    "validate_outline_processing_summary",
    "validate_page_identity",
    "validate_processing_summary",
    "validate_projected_concerns",
    "validate_projected_document",
    "validate_public_path",
    "validate_rendered_label_visibility",
    "validate_repetition_group_bindings",
    "validate_resource_payload",
    "validate_running_region",
    "validate_running_region_sidecar",
    "validate_source_owner_admission",
    "validate_source_projection_bindings",
    "validate_source_report",
    "whole_output_semantic_payload",
]
