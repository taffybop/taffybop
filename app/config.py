"""Application configuration loaded from environment variables."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache


MEBIBYTE = 1024 * 1024


def parser_latency_prewarm_requested() -> bool:
    """Read only the rollback-boundary flag without parsing auxiliary values."""

    return _read_bool("PARSER_LATENCY_PREWARM_ENABLED", False)


def _read_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc

    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _read_float(
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc

    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


def _parse_bool_environment(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"{name} must be one of true/false, yes/no, on/off, or 1/0"
    )


def _read_bool(name: str, default: bool) -> bool:
    """Read a boolean after applying shipping rollback controls first.

    Registered optional behaviors must become inert before their auxiliary
    configuration is parsed.  This lets the emergency kill switch and a
    capability rollback recover from stale malformed child configuration
    instead of failing startup on values that can no longer be used.
    """

    if name not in {
        "PARSER_SHIPPING_KILL_SWITCH",
        "PARSER_SHIPPING_DISABLED_CAPABILITIES",
    }:
        from app.services.feature_flags import shipping_flag_registry

        flag = next(
            (
                candidate
                for candidate in shipping_flag_registry().flags
                if candidate.environment == name
            ),
            None,
        )
        if flag is not None:
            if _parse_bool_environment("PARSER_SHIPPING_KILL_SWITCH", False):
                return False
            disabled = _read_identifiers(
                "PARSER_SHIPPING_DISABLED_CAPABILITIES"
            )
            by_setting = {
                candidate.setting: candidate
                for candidate in shipping_flag_registry().flags
            }

            def disabled_by_rollback(candidate: object, visiting: set[str]) -> bool:
                setting = str(getattr(candidate, "setting"))
                if setting in visiting:
                    return True
                if str(getattr(candidate, "capability")) in disabled:
                    return True
                dependencies = tuple(getattr(candidate, "dependencies"))
                next_visiting = {*visiting, setting}
                for dependency in dependencies:
                    owner = by_setting[dependency]
                    if disabled_by_rollback(owner, next_visiting):
                        return True
                return False

            if disabled_by_rollback(flag, set()):
                return False
    return _parse_bool_environment(name, default)


def _read_sha256(name: str) -> str:
    raw_value = os.getenv(name)
    if raw_value is None:
        raise ValueError(f"{name} is required when parser prewarming is enabled")
    value = raw_value.strip().casefold()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _read_required_text(name: str, *, maximum_length: int) -> str:
    raw_value = os.getenv(name)
    if raw_value is None:
        raise ValueError(f"{name} is required")
    value = raw_value.strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    if len(value) > maximum_length or any(ord(character) < 32 for character in value):
        raise ValueError(
            f"{name} must contain at most {maximum_length} printable characters"
        )
    return value


def _read_optional_text(name: str, *, maximum_length: int) -> str | None:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return None
    value = raw_value.strip()
    if len(value) > maximum_length or any(ord(character) < 32 for character in value):
        raise ValueError(
            f"{name} must contain at most {maximum_length} printable characters"
        )
    return value


def _read_required_sha256(name: str) -> str:
    value = _read_required_text(name, maximum_length=64).casefold()
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _read_languages(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    languages = tuple(
        language.strip() for language in raw_value.split(",") if language.strip()
    )
    if not languages:
        raise ValueError(f"{name} must contain at least one language")
    return languages


def _read_identifiers(name: str) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return ()
    values = tuple(
        value.strip().casefold()
        for value in raw_value.split(",")
        if value.strip()
    )
    if len(values) > 32 or len(set(values)) != len(values):
        raise ValueError(f"{name} must contain at most 32 unique identifiers")
    for value in values:
        if len(value) > 64 or not value[0].isalnum() or any(
            not (character.isalnum() or character in "_-")
            for character in value
        ):
            raise ValueError(
                f"{name} values must be bounded letters, numbers, '_' or '-'"
            )
    return values


def _read_page_limit() -> int:
    if os.getenv("MAX_DOCUMENT_PAGES") is not None:
        return _read_int("MAX_DOCUMENT_PAGES", 100)
    return _read_int("MAX_PDF_PAGES", 100)


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime limits and local extraction-engine configuration."""

    max_upload_bytes: int = 20 * MEBIBYTE
    max_pages: int = 100
    max_image_pixels: int = 50_000_000
    max_image_total_pixels: int = 100_000_000
    document_timeout_seconds: float = 300.0
    ocr_languages: tuple[str, ...] = ("eng",)
    tesseract_cmd: str = "tesseract"
    tesseract_data_path: str | None = None
    targeted_ocr_timeout_seconds: float = 30.0
    targeted_ocr_scale: float = 5.0
    targeted_ocr_max_pixels: int = 16_000_000
    docling_artifacts_path: str | None = None
    parser_latency_prewarm_enabled: bool = False
    parser_latency_prewarm_timeout_seconds: float = 300.0
    parser_latency_prewarm_shutdown_grace_seconds: float = 2.0
    parser_latency_prewarm_artifacts_sha256: str | None = None
    parser_latency_prewarm_dependency_sha256: str | None = None
    image_primary_ocr_min_confidence: float = 0.45
    image_low_confidence_min_alnum_chars: int = 8
    image_heading_min_confidence: float = 0.75
    image_heading_height_ratio: float = 1.8
    image_heading_min_page_height_ratio: float = 0.025
    image_picture_classification_threshold: float = 0.6
    image_captioning_enabled: bool = False
    image_captioning_prompt: str = (
        "Describe this visible image faithfully in one concise sentence. "
        "Do not infer hidden text, values, or relationships."
    )
    pdf_visual_analysis_enabled: bool = True
    pdf_render_ocr_min_native_alnum_chars: int = 24
    pdf_render_ocr_min_layout_coverage: float = 0.55
    shared_ir_enabled: bool = False
    shared_ir_normalization_enabled: bool = False
    canonical_serialization_enabled: bool = False
    text_integrity_font_audit_enabled: bool = False
    text_integrity_font_recovery_enabled: bool = False
    text_integrity_selective_span_ocr_enabled: bool = False
    text_reconciliation_enabled: bool = False
    ocr_numeric_cleanup_v2_enabled: bool = False
    ocr_spatial_token_preservation_enabled: bool = False
    text_integrity_source_alignment_enabled: bool = False
    layout_table_captions_enabled: bool = False
    layout_visual_relationships_enabled: bool = False
    layout_source_notes_enabled: bool = False
    layout_relationship_order_enabled: bool = False
    layout_text_run_semantics_enabled: bool = False
    layout_forms_enabled: bool = False
    layout_outline_structure_enabled: bool = False
    layout_running_regions_enabled: bool = False
    table_span_fidelity_enabled: bool = False
    table_evidence_reconciliation_enabled: bool = False
    table_candidate_gate_enabled: bool = False
    table_multi_page_merge_enabled: bool = False
    visual_structure_schema_enabled: bool = False
    charts_vector_inventory_enabled: bool = False
    charts_structure_enabled: bool = False
    charts_vector_values_enabled: bool = False
    charts_structured_output_enabled: bool = False
    charts_raster_structure_enabled: bool = False
    charts_raster_bar_values_enabled: bool = False
    charts_raster_line_values_enabled: bool = False
    charts_raster_analysis_enabled: bool = False
    diagrams_topology_enabled: bool = False
    charts_raster_max_crop_width: int = 2_048
    charts_raster_max_crop_height: int = 2_048
    charts_raster_max_total_pixels: int = 4_000_000
    charts_raster_max_work_units: int = 10_000
    charts_raster_timeout_seconds: float = 2.0
    charts_raster_minimum_quality: float = 0.6
    charts_raster_coordinate_tolerance: float = 0.5
    visual_models_contract_enabled: bool = False
    visual_models_max_crop_width: int = 2_048
    visual_models_max_crop_height: int = 2_048
    visual_models_max_crop_pixels: int = 4_000_000
    visual_models_max_request_bytes: int = 8 * MEBIBYTE
    visual_models_max_response_bytes: int = 262_144
    visual_models_max_observations: int = 32
    visual_models_local_enabled: bool = False
    visual_models_local_usage_approved: bool = False
    visual_models_local_usage_approval_id: str | None = None
    visual_models_local_artifact_path: str | None = None
    visual_models_local_artifact_sha256: str | None = None
    visual_models_local_artifact_source: str | None = None
    visual_models_local_license_id: str | None = None
    visual_models_local_model_name: str | None = None
    visual_models_local_model_version: str | None = None
    visual_models_local_adapter_name: str = "local-visual-model-adapter"
    visual_models_local_adapter_version: str = "1.0.0"
    visual_models_local_prompt_version: str = "grounded-v1"
    visual_models_local_hardware: str = "cpu"
    visual_models_local_timeout_seconds: float = 2.0
    visual_models_local_max_work_units: int = 10_000
    visual_models_local_max_concurrency: int = 1
    visual_models_local_max_memory_bytes: int = 1024 * MEBIBYTE
    visual_models_local_max_artifact_bytes: int = 2 * 1024 * MEBIBYTE
    visual_models_hosted_enabled: bool = False
    visual_models_hosted_policy_approved: bool = False
    visual_models_hosted_data_approved: bool = False
    visual_models_hosted_minimization_approved: bool = False
    visual_models_hosted_retention_approved: bool = False
    visual_models_hosted_vendor: str | None = None
    visual_models_hosted_model: str | None = None
    visual_models_hosted_processing_region: str | None = None
    visual_models_hosted_data_class: str | None = None
    visual_models_hosted_retention_policy: str | None = None
    visual_models_hosted_redaction_decision: str | None = None
    visual_models_hosted_redaction_context_id: str | None = None
    visual_models_hosted_max_requests: int = 0
    visual_models_hosted_max_request_pixels: int = 0
    visual_models_hosted_max_document_pixels: int = 0
    visual_models_hosted_max_cost_microunits: int = 0
    visual_models_hosted_max_output_tokens: int = 0
    visual_models_hosted_max_timeout_ms: int = 0
    visual_models_hosted_reserved_cost_microunits: int = 0
    visual_models_hosted_request_max_output_tokens: int = 0
    visual_models_hosted_request_timeout_ms: int = 0
    visual_models_hosted_max_attempts: int = 1
    visual_models_routing_enabled: bool = False
    visual_models_routing_preference: str = "local_first"
    visual_models_routing_max_regions_per_document: int = 8
    visual_models_routing_max_document_pixels: int = 8_000_000
    visual_models_grounding_enabled: bool = False
    visual_models_grounding_bbox_tolerance: float = 0.0
    visual_models_merge_enabled: bool = False
    visual_models_merge_max_observations: int = 32
    visual_models_merge_max_added_bytes: int = 262_144
    # Phase 07 cross-format adapters are deliberately default-off.  Each
    # flag is an independent rollback boundary, while the dependency checks
    # below prevent a format adapter from bypassing the shared conformance or
    # bounded OOXML intake layers.
    adapters_conformance_enabled: bool = False
    adapters_image_parity_enabled: bool = False
    adapters_ooxml_intake_enabled: bool = False
    adapters_docx_native_enabled: bool = False
    adapters_pptx_native_enabled: bool = False
    adapters_xlsx_native_enabled: bool = False
    adapters_office_charts_enabled: bool = False
    adapters_office_fallback_enabled: bool = False
    adapters_future_conformance_gate_enabled: bool = False
    adapters_ooxml_max_entries: int = 2_048
    adapters_ooxml_max_compressed_bytes: int = 25 * MEBIBYTE
    adapters_ooxml_max_uncompressed_bytes: int = 100 * MEBIBYTE
    adapters_ooxml_max_part_bytes: int = 25 * MEBIBYTE
    adapters_ooxml_max_xml_nodes: int = 250_000
    adapters_ooxml_max_xml_depth: int = 64
    adapters_ooxml_max_relationships: int = 10_000
    adapters_ooxml_timeout_seconds: float = 5.0
    adapters_xlsx_max_sheets: int = 256
    adapters_xlsx_max_cells: int = 100_000
    adapters_xlsx_max_rows: int = 1_048_576
    adapters_xlsx_max_columns: int = 16_384
    adapters_office_fallback_max_regions: int = 16
    adapters_office_fallback_max_width: int = 2_048
    adapters_office_fallback_max_height: int = 2_048
    adapters_office_fallback_max_total_pixels: int = 8_000_000
    adapters_office_fallback_max_renderer_bytes: int = 32 * MEBIBYTE
    adapters_office_fallback_timeout_seconds: float = 5.0
    # Phase 08 release controls are optional and default off.  The control
    # registry preserves every existing environment name and applies only
    # deterministic disable/cascade behavior.
    telemetry_enabled: bool = False
    telemetry_resources_enabled: bool = False
    telemetry_quality_enabled: bool = False
    deterministic_confidence_enabled: bool = False
    visual_confidence_enabled: bool = False
    review_escalation_enabled: bool = False
    telemetry_queue_size: int = 128
    telemetry_exporter_timeout_ms: int = 50
    telemetry_max_event_bytes: int = 4_096
    telemetry_max_labels: int = 8
    telemetry_max_cardinality_per_label: int = 16
    parser_shipping_kill_switch: bool = False
    parser_shipping_disabled_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # The emergency global kill switch takes precedence over every
        # subordinate flag, including stale or partially rolled-out values.
        # Setting frozen fields here establishes the effective immutable
        # profile before any dependency validator can reject the shutdown.
        if (
            self.parser_shipping_kill_switch
            or self.parser_shipping_disabled_capabilities
        ):
            from app.services.feature_flags import shipping_flag_registry

            registry = shipping_flag_registry()
            effective = registry.resolve(self)
            for flag in registry.flags:
                object.__setattr__(
                    self,
                    flag.setting,
                    bool(getattr(effective, flag.setting)),
                )
        if self.parser_latency_prewarm_enabled:
            for name, value, minimum, maximum in (
                (
                    "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS",
                    self.parser_latency_prewarm_timeout_seconds,
                    1.0,
                    900.0,
                ),
                (
                    "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS",
                    self.parser_latency_prewarm_shutdown_grace_seconds,
                    0.1,
                    30.0,
                ),
            ):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not minimum <= value <= maximum
                ):
                    raise ValueError(
                        f"{name} must be between {minimum:g} and {maximum:g}"
                    )
            if not self.docling_artifacts_path:
                raise ValueError(
                    "PARSER_LATENCY_PREWARM_ENABLED requires DOCLING_ARTIFACTS_PATH"
                )
            for name, value in (
                (
                    "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256",
                    self.parser_latency_prewarm_artifacts_sha256,
                ),
                (
                    "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256",
                    self.parser_latency_prewarm_dependency_sha256,
                ),
            ):
                if (
                    not isinstance(value, str)
                    or len(value) != 64
                    or any(character not in "0123456789abcdef" for character in value)
                ):
                    raise ValueError(
                        f"{name} must be a lowercase SHA-256 digest when parser "
                        "prewarming is enabled"
                    )
            if (
                not os.path.isabs(self.docling_artifacts_path)
                or os.path.realpath(self.docling_artifacts_path)
                != self.docling_artifacts_path
            ):
                raise ValueError(
                    "PARSER_LATENCY_PREWARM_ENABLED requires an absolute, "
                    "resolved DOCLING_ARTIFACTS_PATH"
                )
            if (
                not os.path.isabs(self.tesseract_cmd)
                or os.path.realpath(self.tesseract_cmd) != self.tesseract_cmd
            ):
                raise ValueError(
                    "PARSER_LATENCY_PREWARM_ENABLED requires an absolute "
                    "TESSERACT_CMD that is fully resolved"
                )
            if (
                not self.tesseract_data_path
                or not os.path.isabs(self.tesseract_data_path)
                or os.path.realpath(self.tesseract_data_path)
                != self.tesseract_data_path
            ):
                raise ValueError(
                    "PARSER_LATENCY_PREWARM_ENABLED requires an absolute "
                    "TESSERACT_DATA_PATH that is fully resolved"
                )
        if self.shared_ir_normalization_enabled and not self.shared_ir_enabled:
            raise ValueError(
                "PARSER_SHARED_IR_NORMALIZATION_ENABLED requires "
                "PARSER_SHARED_IR_ENABLED"
            )
        if (
            self.canonical_serialization_enabled
            and not self.shared_ir_normalization_enabled
        ):
            raise ValueError(
                "PARSER_CANONICAL_SERIALIZATION_ENABLED requires "
                "PARSER_SHARED_IR_NORMALIZATION_ENABLED"
            )
        if (
            self.text_integrity_font_audit_enabled
            and not self.shared_ir_normalization_enabled
        ):
            raise ValueError(
                "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED requires "
                "PARSER_SHARED_IR_NORMALIZATION_ENABLED"
            )
        if (
            self.text_integrity_font_recovery_enabled
            and not self.text_integrity_font_audit_enabled
        ):
            raise ValueError(
                "PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED requires "
                "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED"
            )
        if self.text_integrity_selective_span_ocr_enabled:
            if (
                not self.shared_ir_normalization_enabled
                or not self.text_integrity_font_audit_enabled
                or not self.text_integrity_font_recovery_enabled
                or not self.pdf_visual_analysis_enabled
            ):
                raise ValueError(
                    "PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED "
                    "requires shared IR normalization, font audit, font "
                    "recovery, and PDF visual analysis"
                )
        if self.text_reconciliation_enabled:
            if (
                not self.shared_ir_enabled
                or not self.shared_ir_normalization_enabled
                or not self.text_integrity_font_audit_enabled
                or not self.text_integrity_font_recovery_enabled
                or not self.text_integrity_selective_span_ocr_enabled
            ):
                raise ValueError(
                    "PARSER_TEXT_RECONCILIATION_ENABLED requires shared IR, "
                    "shared IR normalization, font audit, font recovery, "
                    "and selective span OCR"
                )
        if (
            self.ocr_spatial_token_preservation_enabled
            and not self.ocr_numeric_cleanup_v2_enabled
        ):
            raise ValueError(
                "PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED requires "
                "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED"
            )
        if self.text_integrity_source_alignment_enabled:
            if (
                not self.text_reconciliation_enabled
                or not self.ocr_numeric_cleanup_v2_enabled
                or not self.ocr_spatial_token_preservation_enabled
            ):
                raise ValueError(
                    "PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED requires "
                    "text reconciliation, numeric cleanup v2, and OCR spatial "
                    "token preservation"
                )
        if (
            self.layout_table_captions_enabled
            or self.layout_visual_relationships_enabled
            or self.layout_source_notes_enabled
            or self.layout_relationship_order_enabled
            or self.layout_text_run_semantics_enabled
            or self.layout_forms_enabled
            or self.layout_outline_structure_enabled
            or self.layout_running_regions_enabled
        ) and not self.shared_ir_normalization_enabled:
            raise ValueError(
                "Phase 03 layout flags require shared IR normalization"
            )
        if self.layout_text_run_semantics_enabled and (
            not self.canonical_serialization_enabled
            or not self.layout_relationship_order_enabled
        ):
            raise ValueError(
                "PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED requires shared IR "
                "normalization, canonical serialization, and layout "
                "relationship order"
            )
        if self.layout_forms_enabled and (
            not self.shared_ir_enabled
            or not self.shared_ir_normalization_enabled
            or not self.canonical_serialization_enabled
            or not self.layout_relationship_order_enabled
        ):
            raise ValueError(
                "PARSER_LAYOUT_FORMS_ENABLED requires shared IR, shared IR "
                "normalization, canonical serialization, and layout "
                "relationship order"
            )
        if self.layout_outline_structure_enabled and (
            not self.shared_ir_enabled
            or not self.shared_ir_normalization_enabled
            or not self.canonical_serialization_enabled
            or not self.layout_relationship_order_enabled
        ):
            raise ValueError(
                "PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED requires shared IR, "
                "shared IR normalization, canonical serialization, and layout "
                "relationship order"
            )
        if self.layout_running_regions_enabled and (
            not self.shared_ir_enabled
            or not self.shared_ir_normalization_enabled
            or not self.canonical_serialization_enabled
            or not self.layout_relationship_order_enabled
        ):
            raise ValueError(
                "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED requires shared IR, "
                "shared IR normalization, canonical serialization, and "
                "layout relationship order"
            )
        if self.table_span_fidelity_enabled and (
            not self.shared_ir_enabled
            or not self.shared_ir_normalization_enabled
            or not self.canonical_serialization_enabled
        ):
            raise ValueError("PARSER_TABLES_SPAN_FIDELITY_ENABLED requires PARSER_SHARED_IR_ENABLED, PARSER_SHARED_IR_NORMALIZATION_ENABLED, and PARSER_CANONICAL_SERIALIZATION_ENABLED")
        if self.table_evidence_reconciliation_enabled and not self.table_span_fidelity_enabled:
            raise ValueError("PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED requires PARSER_TABLES_SPAN_FIDELITY_ENABLED")
        if self.table_candidate_gate_enabled and not self.table_evidence_reconciliation_enabled:
            raise ValueError("PARSER_TABLES_CANDIDATE_GATE_ENABLED requires PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED")
        if self.table_multi_page_merge_enabled and not self.table_candidate_gate_enabled:
            raise ValueError("PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED requires PARSER_TABLES_CANDIDATE_GATE_ENABLED")
        if (
            self.charts_vector_inventory_enabled
            and not self.visual_structure_schema_enabled
        ):
            raise ValueError(
                "PARSER_CHARTS_VECTOR_INVENTORY_ENABLED requires "
                "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED"
            )
        if (
            self.charts_structure_enabled
            and not self.charts_vector_inventory_enabled
        ):
            raise ValueError(
                "PARSER_CHARTS_STRUCTURE_ENABLED requires "
                "PARSER_CHARTS_VECTOR_INVENTORY_ENABLED"
            )
        if self.charts_vector_values_enabled and not self.charts_structure_enabled:
            raise ValueError(
                "PARSER_CHARTS_VECTOR_VALUES_ENABLED requires "
                "PARSER_CHARTS_STRUCTURE_ENABLED"
            )
        if self.charts_structured_output_enabled and (
            not self.visual_structure_schema_enabled
            or not self.shared_ir_enabled
            or not self.shared_ir_normalization_enabled
            or not self.canonical_serialization_enabled
        ):
            raise ValueError(
                "PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED requires "
                "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED, PARSER_SHARED_IR_ENABLED, "
                "PARSER_SHARED_IR_NORMALIZATION_ENABLED, and "
                "PARSER_CANONICAL_SERIALIZATION_ENABLED"
            )
        if self.charts_raster_structure_enabled and (
            not self.visual_structure_schema_enabled
            or not self.ocr_spatial_token_preservation_enabled
        ):
            raise ValueError(
                "PARSER_CHARTS_RASTER_STRUCTURE_ENABLED requires "
                "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED, "
                "and PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED"
            )
        if self.charts_raster_bar_values_enabled and (
            not self.charts_raster_structure_enabled
            or not self.charts_structured_output_enabled
        ):
            raise ValueError(
                "PARSER_CHARTS_RASTER_BAR_VALUES_ENABLED requires "
                "PARSER_CHARTS_RASTER_STRUCTURE_ENABLED and "
                "PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED"
            )
        if self.charts_raster_line_values_enabled and (
            not self.charts_raster_structure_enabled
            or not self.charts_structured_output_enabled
        ):
            raise ValueError(
                "PARSER_CHARTS_RASTER_LINE_VALUES_ENABLED requires "
                "PARSER_CHARTS_RASTER_STRUCTURE_ENABLED and "
                "PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED"
            )
        if self.charts_raster_analysis_enabled and (
            not self.visual_structure_schema_enabled
            or not self.ocr_spatial_token_preservation_enabled
            or not self.charts_raster_structure_enabled
            or not self.charts_structured_output_enabled
        ):
            raise ValueError(
                "PARSER_CHARTS_RASTER_ANALYSIS_ENABLED requires the visual "
                "schema, spatial OCR, raster structure, and structured output"
            )
        if self.diagrams_topology_enabled and (
            not self.visual_structure_schema_enabled
            or not self.ocr_spatial_token_preservation_enabled
        ):
            raise ValueError(
                "PARSER_DIAGRAMS_TOPOLOGY_ENABLED requires "
                "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED and "
                "PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED"
            )
        if self.visual_models_contract_enabled and not self.visual_structure_schema_enabled:
            raise ValueError(
                "PARSER_VISUAL_MODELS_CONTRACT_ENABLED requires "
                "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED"
            )
        if self.visual_models_contract_enabled:
            for name, value, minimum, maximum in (
                ("PARSER_VISUAL_MODELS_MAX_CROP_WIDTH", self.visual_models_max_crop_width, 1, 8_192),
                ("PARSER_VISUAL_MODELS_MAX_CROP_HEIGHT", self.visual_models_max_crop_height, 1, 8_192),
                ("PARSER_VISUAL_MODELS_MAX_CROP_PIXELS", self.visual_models_max_crop_pixels, 1, 16_000_000),
                ("PARSER_VISUAL_MODELS_MAX_REQUEST_BYTES", self.visual_models_max_request_bytes, 1_024, 25 * MEBIBYTE),
                ("PARSER_VISUAL_MODELS_MAX_RESPONSE_BYTES", self.visual_models_max_response_bytes, 1_024, MEBIBYTE),
                ("PARSER_VISUAL_MODELS_MAX_OBSERVATIONS", self.visual_models_max_observations, 1, 256),
            ):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not minimum <= value <= maximum
                ):
                    raise ValueError(
                        f"{name} must be between {minimum} and {maximum}"
                    )
        if (
            self.visual_models_local_enabled
            and not self.visual_models_contract_enabled
        ):
            raise ValueError(
                "PARSER_VISUAL_MODELS_LOCAL_ENABLED requires "
                "PARSER_VISUAL_MODELS_CONTRACT_ENABLED"
            )
        if self.visual_models_local_enabled:
            for name, value, minimum, maximum in (
                (
                    "PARSER_VISUAL_MODELS_LOCAL_MAX_WORK_UNITS",
                    self.visual_models_local_max_work_units,
                    1,
                    100_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_LOCAL_MAX_CONCURRENCY",
                    self.visual_models_local_max_concurrency,
                    1,
                    8,
                ),
                (
                    "PARSER_VISUAL_MODELS_LOCAL_MAX_MEMORY_BYTES",
                    self.visual_models_local_max_memory_bytes,
                    MEBIBYTE,
                    128 * 1024 * MEBIBYTE,
                ),
                (
                    "PARSER_VISUAL_MODELS_LOCAL_MAX_ARTIFACT_BYTES",
                    self.visual_models_local_max_artifact_bytes,
                    MEBIBYTE,
                    16 * 1024 * MEBIBYTE,
                ),
            ):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not minimum <= value <= maximum
                ):
                    raise ValueError(
                        f"{name} must be between {minimum} and {maximum}"
                    )
            timeout = self.visual_models_local_timeout_seconds
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or not 0.001 <= float(timeout) <= 30.0
            ):
                raise ValueError(
                    "PARSER_VISUAL_MODELS_LOCAL_TIMEOUT_SECONDS must be "
                    "between 0.001 and 30"
                )
            if self.visual_models_local_hardware not in {
                "cpu",
                "gpu",
                "accelerator",
            }:
                raise ValueError(
                    "PARSER_VISUAL_MODELS_LOCAL_HARDWARE must be one of "
                    "cpu, gpu, or accelerator"
                )
            for name, value, maximum in (
                (
                    "PARSER_VISUAL_MODELS_LOCAL_ADAPTER_NAME",
                    self.visual_models_local_adapter_name,
                    128,
                ),
                (
                    "PARSER_VISUAL_MODELS_LOCAL_ADAPTER_VERSION",
                    self.visual_models_local_adapter_version,
                    64,
                ),
                (
                    "PARSER_VISUAL_MODELS_LOCAL_PROMPT_VERSION",
                    self.visual_models_local_prompt_version,
                    64,
                ),
            ):
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value) > maximum
                    or any(ord(character) < 32 for character in value)
                ):
                    raise ValueError(
                        f"{name} must be a non-empty printable value no longer "
                        f"than {maximum} characters"
                    )
            if self.visual_models_local_usage_approved:
                for name, value, maximum in (
                    (
                        "PARSER_VISUAL_MODELS_LOCAL_USAGE_APPROVAL_ID",
                        self.visual_models_local_usage_approval_id,
                        256,
                    ),
                    (
                        "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_PATH",
                        self.visual_models_local_artifact_path,
                        4_096,
                    ),
                    (
                        "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_SOURCE",
                        self.visual_models_local_artifact_source,
                        512,
                    ),
                    (
                        "PARSER_VISUAL_MODELS_LOCAL_LICENSE_ID",
                        self.visual_models_local_license_id,
                        256,
                    ),
                    (
                        "PARSER_VISUAL_MODELS_LOCAL_MODEL_NAME",
                        self.visual_models_local_model_name,
                        128,
                    ),
                    (
                        "PARSER_VISUAL_MODELS_LOCAL_MODEL_VERSION",
                        self.visual_models_local_model_version,
                        128,
                    ),
                ):
                    if (
                        not isinstance(value, str)
                        or not value.strip()
                        or len(value) > maximum
                        or any(ord(character) < 32 for character in value)
                    ):
                        raise ValueError(
                            f"{name} is required as a bounded printable value "
                            "when local visual-model usage is approved"
                        )
                digest = self.visual_models_local_artifact_sha256
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                ):
                    raise ValueError(
                        "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_SHA256 must be a "
                        "lowercase SHA-256 digest when local visual-model usage "
                        "is approved"
                    )
                artifact_path = self.visual_models_local_artifact_path
                if (
                    not isinstance(artifact_path, str)
                    or not os.path.isabs(artifact_path)
                    or os.path.realpath(artifact_path) != artifact_path
                ):
                    raise ValueError(
                        "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_PATH must be an "
                        "absolute, resolved path when local visual-model usage "
                        "is approved"
                    )
        if (
            self.visual_models_hosted_enabled
            and not self.visual_models_contract_enabled
        ):
            raise ValueError(
                "PARSER_VISUAL_MODELS_HOSTED_ENABLED requires "
                "PARSER_VISUAL_MODELS_CONTRACT_ENABLED"
            )
        if self.visual_models_hosted_enabled:
            approvals = (
                (
                    "PARSER_VISUAL_MODELS_HOSTED_POLICY_APPROVED",
                    self.visual_models_hosted_policy_approved,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_DATA_APPROVED",
                    self.visual_models_hosted_data_approved,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_MINIMIZATION_APPROVED",
                    self.visual_models_hosted_minimization_approved,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_RETENTION_APPROVED",
                    self.visual_models_hosted_retention_approved,
                ),
            )
            if any(not isinstance(value, bool) for _, value in approvals):
                raise ValueError("hosted visual-model approvals must be booleans")

            identifiers = (
                (
                    "PARSER_VISUAL_MODELS_HOSTED_VENDOR",
                    self.visual_models_hosted_vendor,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_MODEL",
                    self.visual_models_hosted_model,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_PROCESSING_REGION",
                    self.visual_models_hosted_processing_region,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_DATA_CLASS",
                    self.visual_models_hosted_data_class,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_RETENTION_POLICY",
                    self.visual_models_hosted_retention_policy,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_REDACTION_CONTEXT_ID",
                    self.visual_models_hosted_redaction_context_id,
                ),
            )
            for name, value in identifiers:
                if value is not None and (
                    not isinstance(value, str)
                    or value != value.strip()
                    or not value
                    or len(value) > 128
                    or any(ord(character) < 32 for character in value)
                ):
                    raise ValueError(
                        f"{name} must be a non-empty printable identifier no "
                        "longer than 128 characters"
                    )
            redaction_context = self.visual_models_hosted_redaction_context_id
            if redaction_context is not None and (
                not redaction_context[0].isalnum()
                or any(
                    not (character.isalnum() or character in "_.:-")
                    for character in redaction_context
                )
            ):
                raise ValueError(
                    "PARSER_VISUAL_MODELS_HOSTED_REDACTION_CONTEXT_ID must "
                    "contain only letters, numbers, underscores, periods, "
                    "colons, or hyphens"
                )
            if self.visual_models_hosted_redaction_decision not in {
                None,
                "applied",
                "not_required",
            }:
                raise ValueError(
                    "PARSER_VISUAL_MODELS_HOSTED_REDACTION_DECISION must be "
                    "applied or not_required"
                )

            budgets = (
                (
                    "PARSER_VISUAL_MODELS_HOSTED_MAX_REQUESTS",
                    self.visual_models_hosted_max_requests,
                    1_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_MAX_REQUEST_PIXELS",
                    self.visual_models_hosted_max_request_pixels,
                    16_000_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_MAX_DOCUMENT_PIXELS",
                    self.visual_models_hosted_max_document_pixels,
                    1_000_000_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_MAX_COST_MICROUNITS",
                    self.visual_models_hosted_max_cost_microunits,
                    1_000_000_000_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_MAX_OUTPUT_TOKENS",
                    self.visual_models_hosted_max_output_tokens,
                    10_000_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_MAX_TIMEOUT_MS",
                    self.visual_models_hosted_max_timeout_ms,
                    86_400_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_RESERVED_COST_MICROUNITS",
                    self.visual_models_hosted_reserved_cost_microunits,
                    1_000_000_000_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_REQUEST_MAX_OUTPUT_TOKENS",
                    self.visual_models_hosted_request_max_output_tokens,
                    1_000_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_HOSTED_REQUEST_TIMEOUT_MS",
                    self.visual_models_hosted_request_timeout_ms,
                    300_000,
                ),
            )
            for name, value, maximum in budgets:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not 0 <= value <= maximum
                ):
                    raise ValueError(f"{name} must be between 0 and {maximum}")
            if self.visual_models_hosted_max_attempts != 1:
                raise ValueError(
                    "PARSER_VISUAL_MODELS_HOSTED_MAX_ATTEMPTS must be exactly 1"
                )

            if self.visual_models_hosted_policy_approved:
                for name, value in identifiers[:3]:
                    if value is None:
                        raise ValueError(f"{name} is required for policy approval")
            if (
                self.visual_models_hosted_data_approved
                and self.visual_models_hosted_data_class is None
            ):
                raise ValueError(
                    "PARSER_VISUAL_MODELS_HOSTED_DATA_CLASS is required for "
                    "data approval"
                )
            if (
                self.visual_models_hosted_retention_approved
                and self.visual_models_hosted_retention_policy is None
            ):
                raise ValueError(
                    "PARSER_VISUAL_MODELS_HOSTED_RETENTION_POLICY is required "
                    "for retention approval"
                )
            if self.visual_models_hosted_minimization_approved and (
                self.visual_models_hosted_redaction_decision is None
                or self.visual_models_hosted_redaction_context_id is None
            ):
                raise ValueError(
                    "hosted minimization approval requires an explicit "
                    "redaction decision and context ID"
                )

            fully_approved = all(value for _, value in approvals)
            if fully_approved:
                if any(value <= 0 for _, value, _ in budgets):
                    raise ValueError(
                        "fully approved hosted visual-model dispatch requires "
                        "positive request, document, cost, token, and timeout "
                        "budgets"
                    )
                if (
                    self.visual_models_hosted_max_request_pixels
                    > self.visual_models_hosted_max_document_pixels
                    or self.visual_models_hosted_reserved_cost_microunits
                    > self.visual_models_hosted_max_cost_microunits
                    or self.visual_models_hosted_request_max_output_tokens
                    > self.visual_models_hosted_max_output_tokens
                    or self.visual_models_hosted_request_timeout_ms
                    > self.visual_models_hosted_max_timeout_ms
                ):
                    raise ValueError(
                        "hosted per-request reservations must not exceed their "
                        "document budgets"
                    )
        if (
            self.visual_models_routing_enabled
            and not self.visual_models_contract_enabled
        ):
            raise ValueError(
                "PARSER_VISUAL_MODELS_ROUTING_ENABLED requires "
                "PARSER_VISUAL_MODELS_CONTRACT_ENABLED"
            )
        if self.visual_models_routing_enabled:
            if self.visual_models_routing_preference not in {
                "local_first",
                "local_only",
                "hosted_first",
                "hosted_only",
            }:
                raise ValueError(
                    "PARSER_VISUAL_MODELS_ROUTING_PREFERENCE must be one of "
                    "local_first, local_only, hosted_first, or hosted_only"
                )
            for name, value, maximum in (
                (
                    "PARSER_VISUAL_MODELS_ROUTING_MAX_REGIONS_PER_DOCUMENT",
                    self.visual_models_routing_max_regions_per_document,
                    1_000,
                ),
                (
                    "PARSER_VISUAL_MODELS_ROUTING_MAX_DOCUMENT_PIXELS",
                    self.visual_models_routing_max_document_pixels,
                    1_000_000_000,
                ),
            ):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not 1 <= value <= maximum
                ):
                    raise ValueError(f"{name} must be between 1 and {maximum}")
        if (
            self.visual_models_grounding_enabled
            and not self.visual_models_routing_enabled
        ):
            raise ValueError(
                "PARSER_VISUAL_MODELS_GROUNDING_ENABLED requires "
                "PARSER_VISUAL_MODELS_ROUTING_ENABLED"
            )
        if self.visual_models_grounding_enabled:
            tolerance = self.visual_models_grounding_bbox_tolerance
            if (
                isinstance(tolerance, bool)
                or not isinstance(tolerance, (int, float))
                or not math.isfinite(tolerance)
                or not 0.0 <= float(tolerance) <= 10.0
            ):
                raise ValueError(
                    "PARSER_VISUAL_MODELS_GROUNDING_BBOX_TOLERANCE must be "
                    "between 0 and 10"
                )
        if self.visual_models_merge_enabled:
            merge_dependencies = (
                (
                    "PARSER_VISUAL_MODELS_CONTRACT_ENABLED",
                    self.visual_models_contract_enabled,
                ),
                (
                    "PARSER_VISUAL_MODELS_ROUTING_ENABLED",
                    self.visual_models_routing_enabled,
                ),
                (
                    "PARSER_VISUAL_MODELS_GROUNDING_ENABLED",
                    self.visual_models_grounding_enabled,
                ),
                ("PARSER_SHARED_IR_ENABLED", self.shared_ir_enabled),
                (
                    "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
                    self.shared_ir_normalization_enabled,
                ),
                (
                    "PARSER_CANONICAL_SERIALIZATION_ENABLED",
                    self.canonical_serialization_enabled,
                ),
            )
            missing_dependencies = tuple(
                name for name, enabled in merge_dependencies if not enabled
            )
            if missing_dependencies:
                raise ValueError(
                    "PARSER_VISUAL_MODELS_MERGE_ENABLED requires "
                    + ", ".join(missing_dependencies)
                )
            for name, value, maximum in (
                (
                    "PARSER_VISUAL_MODELS_MERGE_MAX_OBSERVATIONS",
                    self.visual_models_merge_max_observations,
                    256,
                ),
                (
                    "PARSER_VISUAL_MODELS_MERGE_MAX_ADDED_BYTES",
                    self.visual_models_merge_max_added_bytes,
                    MEBIBYTE,
                ),
            ):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not 1 <= value <= maximum
                ):
                    raise ValueError(f"{name} must be between 1 and {maximum}")
        if self.charts_raster_analysis_enabled:
            for name, value, minimum, maximum in (
                ("PARSER_CHARTS_RASTER_MAX_CROP_WIDTH", self.charts_raster_max_crop_width, 1, 8_192),
                ("PARSER_CHARTS_RASTER_MAX_CROP_HEIGHT", self.charts_raster_max_crop_height, 1, 8_192),
                ("PARSER_CHARTS_RASTER_MAX_TOTAL_PIXELS", self.charts_raster_max_total_pixels, 1, 16_000_000),
                ("PARSER_CHARTS_RASTER_MAX_WORK_UNITS", self.charts_raster_max_work_units, 1, 100_000),
            ):
                if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                    raise ValueError(f"{name} must be between {minimum} and {maximum}")
            for name, value, minimum, maximum in (
                ("PARSER_CHARTS_RASTER_TIMEOUT_SECONDS", self.charts_raster_timeout_seconds, 0.001, 30.0),
                ("PARSER_CHARTS_RASTER_MINIMUM_QUALITY", self.charts_raster_minimum_quality, 0.0, 1.0),
                ("PARSER_CHARTS_RASTER_COORDINATE_TOLERANCE", self.charts_raster_coordinate_tolerance, 0.0, 10.0),
            ):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= float(value) <= maximum:
                    raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")

        phase07_dependencies = (
            (
                "PARSER_ADAPTERS_IMAGE_PARITY_ENABLED",
                self.adapters_image_parity_enabled,
                (
                    (
                        "PARSER_ADAPTERS_CONFORMANCE_ENABLED",
                        self.adapters_conformance_enabled,
                    ),
                ),
            ),
            (
                "PARSER_ADAPTERS_OOXML_INTAKE_ENABLED",
                self.adapters_ooxml_intake_enabled,
                (
                    (
                        "PARSER_ADAPTERS_CONFORMANCE_ENABLED",
                        self.adapters_conformance_enabled,
                    ),
                ),
            ),
            *(
                (
                    flag_name,
                    enabled,
                    (
                        (
                            "PARSER_ADAPTERS_CONFORMANCE_ENABLED",
                            self.adapters_conformance_enabled,
                        ),
                        (
                            "PARSER_ADAPTERS_OOXML_INTAKE_ENABLED",
                            self.adapters_ooxml_intake_enabled,
                        ),
                    ),
                )
                for flag_name, enabled in (
                    (
                        "PARSER_ADAPTERS_DOCX_NATIVE_ENABLED",
                        self.adapters_docx_native_enabled,
                    ),
                    (
                        "PARSER_ADAPTERS_PPTX_NATIVE_ENABLED",
                        self.adapters_pptx_native_enabled,
                    ),
                    (
                        "PARSER_ADAPTERS_XLSX_NATIVE_ENABLED",
                        self.adapters_xlsx_native_enabled,
                    ),
                )
            ),
            (
                "PARSER_ADAPTERS_OFFICE_CHARTS_ENABLED",
                self.adapters_office_charts_enabled,
                (
                    (
                        "PARSER_ADAPTERS_PPTX_NATIVE_ENABLED",
                        self.adapters_pptx_native_enabled,
                    ),
                    (
                        "PARSER_ADAPTERS_XLSX_NATIVE_ENABLED",
                        self.adapters_xlsx_native_enabled,
                    ),
                ),
            ),
            (
                "PARSER_ADAPTERS_OFFICE_FALLBACK_ENABLED",
                self.adapters_office_fallback_enabled,
                (
                    (
                        "PARSER_ADAPTERS_IMAGE_PARITY_ENABLED",
                        self.adapters_image_parity_enabled,
                    ),
                    (
                        "PARSER_ADAPTERS_DOCX_NATIVE_ENABLED",
                        self.adapters_docx_native_enabled,
                    ),
                    (
                        "PARSER_ADAPTERS_PPTX_NATIVE_ENABLED",
                        self.adapters_pptx_native_enabled,
                    ),
                    (
                        "PARSER_ADAPTERS_XLSX_NATIVE_ENABLED",
                        self.adapters_xlsx_native_enabled,
                    ),
                    (
                        "PARSER_ADAPTERS_OFFICE_CHARTS_ENABLED",
                        self.adapters_office_charts_enabled,
                    ),
                ),
            ),
            (
                "PARSER_ADAPTERS_FUTURE_CONFORMANCE_GATE_ENABLED",
                self.adapters_future_conformance_gate_enabled,
                (
                    (
                        "PARSER_ADAPTERS_CONFORMANCE_ENABLED",
                        self.adapters_conformance_enabled,
                    ),
                    (
                        "PARSER_ADAPTERS_OFFICE_FALLBACK_ENABLED",
                        self.adapters_office_fallback_enabled,
                    ),
                ),
            ),
        )
        for flag_name, enabled, dependencies in phase07_dependencies:
            if not enabled:
                continue
            missing = [name for name, present in dependencies if not present]
            if missing:
                raise ValueError(f"{flag_name} requires " + ", ".join(missing))

        if self.adapters_ooxml_intake_enabled:
            for name, value, minimum, maximum in (
                ("PARSER_ADAPTERS_OOXML_MAX_ENTRIES", self.adapters_ooxml_max_entries, 1, 100_000),
                ("PARSER_ADAPTERS_OOXML_MAX_COMPRESSED_BYTES", self.adapters_ooxml_max_compressed_bytes, 1_024, 1024 * MEBIBYTE),
                ("PARSER_ADAPTERS_OOXML_MAX_UNCOMPRESSED_BYTES", self.adapters_ooxml_max_uncompressed_bytes, 1_024, 4 * 1024 * MEBIBYTE),
                ("PARSER_ADAPTERS_OOXML_MAX_PART_BYTES", self.adapters_ooxml_max_part_bytes, 1, 1024 * MEBIBYTE),
                ("PARSER_ADAPTERS_OOXML_MAX_XML_NODES", self.adapters_ooxml_max_xml_nodes, 1, 10_000_000),
                ("PARSER_ADAPTERS_OOXML_MAX_XML_DEPTH", self.adapters_ooxml_max_xml_depth, 1, 256),
                ("PARSER_ADAPTERS_OOXML_MAX_RELATIONSHIPS", self.adapters_ooxml_max_relationships, 1, 1_000_000),
            ):
                if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                    raise ValueError(f"{name} must be between {minimum} and {maximum}")
            if self.adapters_ooxml_max_part_bytes > self.adapters_ooxml_max_uncompressed_bytes:
                raise ValueError(
                    "PARSER_ADAPTERS_OOXML_MAX_PART_BYTES must not exceed "
                    "PARSER_ADAPTERS_OOXML_MAX_UNCOMPRESSED_BYTES"
                )
            timeout = self.adapters_ooxml_timeout_seconds
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or not 0.001 <= float(timeout) <= 30.0
            ):
                raise ValueError(
                    "PARSER_ADAPTERS_OOXML_TIMEOUT_SECONDS must be between "
                    "0.001 and 30"
                )

        if self.adapters_xlsx_native_enabled:
            for name, value, maximum in (
                ("PARSER_ADAPTERS_XLSX_MAX_SHEETS", self.adapters_xlsx_max_sheets, 16_384),
                ("PARSER_ADAPTERS_XLSX_MAX_CELLS", self.adapters_xlsx_max_cells, 10_000_000),
                ("PARSER_ADAPTERS_XLSX_MAX_ROWS", self.adapters_xlsx_max_rows, 1_048_576),
                ("PARSER_ADAPTERS_XLSX_MAX_COLUMNS", self.adapters_xlsx_max_columns, 16_384),
            ):
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                    raise ValueError(f"{name} must be between 1 and {maximum}")

        if self.adapters_office_fallback_enabled:
            for name, value, maximum in (
                ("PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_REGIONS", self.adapters_office_fallback_max_regions, 1_000),
                ("PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_WIDTH", self.adapters_office_fallback_max_width, 8_192),
                ("PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_HEIGHT", self.adapters_office_fallback_max_height, 8_192),
                ("PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_TOTAL_PIXELS", self.adapters_office_fallback_max_total_pixels, 1_000_000_000),
                ("PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_RENDERER_BYTES", self.adapters_office_fallback_max_renderer_bytes, 256 * MEBIBYTE),
            ):
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                    raise ValueError(f"{name} must be between 1 and {maximum}")
            timeout = self.adapters_office_fallback_timeout_seconds
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or not 0.001 <= float(timeout) <= 30.0
            ):
                raise ValueError(
                    "PARSER_ADAPTERS_OFFICE_FALLBACK_TIMEOUT_SECONDS must be "
                    "between 0.001 and 30"
                )

        from app.services.feature_flags import shipping_flag_registry

        shipping_flag_registry().validate(self)
        if self.telemetry_enabled:
            for name, value, minimum, maximum in (
                ("PARSER_TELEMETRY_QUEUE_SIZE", self.telemetry_queue_size, 1, 1_024),
                ("PARSER_TELEMETRY_EXPORTER_TIMEOUT_MS", self.telemetry_exporter_timeout_ms, 1, 5_000),
                ("PARSER_TELEMETRY_MAX_EVENT_BYTES", self.telemetry_max_event_bytes, 256, 16_384),
                ("PARSER_TELEMETRY_MAX_LABELS", self.telemetry_max_labels, 1, 16),
                ("PARSER_TELEMETRY_MAX_CARDINALITY_PER_LABEL", self.telemetry_max_cardinality_per_label, 1, 64),
            ):
                if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                    raise ValueError(f"{name} must be between {minimum} and {maximum}")

    @classmethod
    def from_env(cls) -> "Settings":
        prewarm_enabled = _read_bool(
            "PARSER_LATENCY_PREWARM_ENABLED",
            False,
        )
        # The feature flag is the complete rollback boundary. Stale or malformed
        # auxiliary values are deliberately ignored while it is false so the
        # predecessor's lazy settings/startup behavior remains available.
        prewarm_timeout_seconds = 300.0
        prewarm_shutdown_grace_seconds = 2.0
        prewarm_artifacts_sha256: str | None = None
        prewarm_dependency_sha256: str | None = None
        if prewarm_enabled:
            prewarm_timeout_seconds = _read_float(
                "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS",
                300.0,
                minimum=1.0,
                maximum=900.0,
            )
            prewarm_shutdown_grace_seconds = _read_float(
                "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS",
                2.0,
                minimum=0.1,
                maximum=30.0,
            )
            prewarm_artifacts_sha256 = _read_sha256(
                "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256"
            )
            prewarm_dependency_sha256 = _read_sha256(
                "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256"
            )
        raster_analysis_enabled = _read_bool(
            "PARSER_CHARTS_RASTER_ANALYSIS_ENABLED",
            False,
        )
        # The umbrella is the public rollback boundary.  Auxiliary resource
        # settings are ignored while it is disabled, just like prewarm-only
        # settings above, so stale deployment values cannot perturb startup.
        raster_max_crop_width = 2_048
        raster_max_crop_height = 2_048
        raster_max_total_pixels = 4_000_000
        raster_max_work_units = 10_000
        raster_timeout_seconds = 2.0
        raster_minimum_quality = 0.6
        raster_coordinate_tolerance = 0.5
        if raster_analysis_enabled:
            raster_max_crop_width = _read_int(
                "PARSER_CHARTS_RASTER_MAX_CROP_WIDTH", 2_048
            )
            raster_max_crop_height = _read_int(
                "PARSER_CHARTS_RASTER_MAX_CROP_HEIGHT", 2_048
            )
            raster_max_total_pixels = _read_int(
                "PARSER_CHARTS_RASTER_MAX_TOTAL_PIXELS", 4_000_000
            )
            raster_max_work_units = _read_int(
                "PARSER_CHARTS_RASTER_MAX_WORK_UNITS", 10_000
            )
            raster_timeout_seconds = _read_float(
                "PARSER_CHARTS_RASTER_TIMEOUT_SECONDS",
                2.0,
                minimum=0.001,
                maximum=30.0,
            )
            raster_minimum_quality = _read_float(
                "PARSER_CHARTS_RASTER_MINIMUM_QUALITY", 0.6, maximum=1.0
            )
            raster_coordinate_tolerance = _read_float(
                "PARSER_CHARTS_RASTER_COORDINATE_TOLERANCE", 0.5, maximum=10.0
            )
        visual_models_contract_enabled = _read_bool(
            "PARSER_VISUAL_MODELS_CONTRACT_ENABLED",
            False,
        )
        visual_models_max_crop_width = 2_048
        visual_models_max_crop_height = 2_048
        visual_models_max_crop_pixels = 4_000_000
        visual_models_max_request_bytes = 8 * MEBIBYTE
        visual_models_max_response_bytes = 262_144
        visual_models_max_observations = 32
        if visual_models_contract_enabled:
            visual_models_max_crop_width = _read_int(
                "PARSER_VISUAL_MODELS_MAX_CROP_WIDTH", 2_048
            )
            visual_models_max_crop_height = _read_int(
                "PARSER_VISUAL_MODELS_MAX_CROP_HEIGHT", 2_048
            )
            visual_models_max_crop_pixels = _read_int(
                "PARSER_VISUAL_MODELS_MAX_CROP_PIXELS", 4_000_000
            )
            visual_models_max_request_bytes = _read_int(
                "PARSER_VISUAL_MODELS_MAX_REQUEST_BYTES", 8 * MEBIBYTE
            )
            visual_models_max_response_bytes = _read_int(
                "PARSER_VISUAL_MODELS_MAX_RESPONSE_BYTES", 262_144
            )
            visual_models_max_observations = _read_int(
                "PARSER_VISUAL_MODELS_MAX_OBSERVATIONS", 32
            )
        visual_models_local_enabled = _read_bool(
            "PARSER_VISUAL_MODELS_LOCAL_ENABLED",
            False,
        )
        visual_models_local_usage_approved = False
        visual_models_local_usage_approval_id: str | None = None
        visual_models_local_artifact_path: str | None = None
        visual_models_local_artifact_sha256: str | None = None
        visual_models_local_artifact_source: str | None = None
        visual_models_local_license_id: str | None = None
        visual_models_local_model_name: str | None = None
        visual_models_local_model_version: str | None = None
        visual_models_local_adapter_name = "local-visual-model-adapter"
        visual_models_local_adapter_version = "1.0.0"
        visual_models_local_prompt_version = "grounded-v1"
        visual_models_local_hardware = "cpu"
        visual_models_local_timeout_seconds = 2.0
        visual_models_local_max_work_units = 10_000
        visual_models_local_max_concurrency = 1
        visual_models_local_max_memory_bytes = 1024 * MEBIBYTE
        visual_models_local_max_artifact_bytes = 2 * 1024 * MEBIBYTE
        if visual_models_local_enabled:
            visual_models_local_usage_approved = _read_bool(
                "PARSER_VISUAL_MODELS_LOCAL_USAGE_APPROVED",
                False,
            )
            visual_models_local_adapter_name = os.getenv(
                "PARSER_VISUAL_MODELS_LOCAL_ADAPTER_NAME",
                "local-visual-model-adapter",
            ).strip()
            visual_models_local_adapter_version = os.getenv(
                "PARSER_VISUAL_MODELS_LOCAL_ADAPTER_VERSION",
                "1.0.0",
            ).strip()
            visual_models_local_prompt_version = os.getenv(
                "PARSER_VISUAL_MODELS_LOCAL_PROMPT_VERSION",
                "grounded-v1",
            ).strip()
            visual_models_local_hardware = os.getenv(
                "PARSER_VISUAL_MODELS_LOCAL_HARDWARE",
                "cpu",
            ).strip().casefold()
            visual_models_local_timeout_seconds = _read_float(
                "PARSER_VISUAL_MODELS_LOCAL_TIMEOUT_SECONDS",
                2.0,
                minimum=0.001,
                maximum=30.0,
            )
            visual_models_local_max_work_units = _read_int(
                "PARSER_VISUAL_MODELS_LOCAL_MAX_WORK_UNITS",
                10_000,
            )
            visual_models_local_max_concurrency = _read_int(
                "PARSER_VISUAL_MODELS_LOCAL_MAX_CONCURRENCY",
                1,
            )
            visual_models_local_max_memory_bytes = _read_int(
                "PARSER_VISUAL_MODELS_LOCAL_MAX_MEMORY_BYTES",
                1024 * MEBIBYTE,
            )
            visual_models_local_max_artifact_bytes = _read_int(
                "PARSER_VISUAL_MODELS_LOCAL_MAX_ARTIFACT_BYTES",
                2 * 1024 * MEBIBYTE,
            )
            if visual_models_local_usage_approved:
                visual_models_local_usage_approval_id = _read_required_text(
                    "PARSER_VISUAL_MODELS_LOCAL_USAGE_APPROVAL_ID",
                    maximum_length=256,
                )
                visual_models_local_artifact_path = _read_required_text(
                    "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_PATH",
                    maximum_length=4_096,
                )
                visual_models_local_artifact_sha256 = _read_required_sha256(
                    "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_SHA256"
                )
                visual_models_local_artifact_source = _read_required_text(
                    "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_SOURCE",
                    maximum_length=512,
                )
                visual_models_local_license_id = _read_required_text(
                    "PARSER_VISUAL_MODELS_LOCAL_LICENSE_ID",
                    maximum_length=256,
                )
                visual_models_local_model_name = _read_required_text(
                    "PARSER_VISUAL_MODELS_LOCAL_MODEL_NAME",
                    maximum_length=128,
                )
                visual_models_local_model_version = _read_required_text(
                    "PARSER_VISUAL_MODELS_LOCAL_MODEL_VERSION",
                    maximum_length=128,
                )
        visual_models_hosted_enabled = _read_bool(
            "PARSER_VISUAL_MODELS_HOSTED_ENABLED",
            False,
        )
        visual_models_hosted_policy_approved = False
        visual_models_hosted_data_approved = False
        visual_models_hosted_minimization_approved = False
        visual_models_hosted_retention_approved = False
        visual_models_hosted_vendor: str | None = None
        visual_models_hosted_model: str | None = None
        visual_models_hosted_processing_region: str | None = None
        visual_models_hosted_data_class: str | None = None
        visual_models_hosted_retention_policy: str | None = None
        visual_models_hosted_redaction_decision: str | None = None
        visual_models_hosted_redaction_context_id: str | None = None
        visual_models_hosted_max_requests = 0
        visual_models_hosted_max_request_pixels = 0
        visual_models_hosted_max_document_pixels = 0
        visual_models_hosted_max_cost_microunits = 0
        visual_models_hosted_max_output_tokens = 0
        visual_models_hosted_max_timeout_ms = 0
        visual_models_hosted_reserved_cost_microunits = 0
        visual_models_hosted_request_max_output_tokens = 0
        visual_models_hosted_request_timeout_ms = 0
        visual_models_hosted_max_attempts = 1
        if visual_models_hosted_enabled:
            visual_models_hosted_policy_approved = _read_bool(
                "PARSER_VISUAL_MODELS_HOSTED_POLICY_APPROVED",
                False,
            )
            visual_models_hosted_data_approved = _read_bool(
                "PARSER_VISUAL_MODELS_HOSTED_DATA_APPROVED",
                False,
            )
            visual_models_hosted_minimization_approved = _read_bool(
                "PARSER_VISUAL_MODELS_HOSTED_MINIMIZATION_APPROVED",
                False,
            )
            visual_models_hosted_retention_approved = _read_bool(
                "PARSER_VISUAL_MODELS_HOSTED_RETENTION_APPROVED",
                False,
            )
            visual_models_hosted_vendor = _read_optional_text(
                "PARSER_VISUAL_MODELS_HOSTED_VENDOR",
                maximum_length=128,
            )
            visual_models_hosted_model = _read_optional_text(
                "PARSER_VISUAL_MODELS_HOSTED_MODEL",
                maximum_length=128,
            )
            visual_models_hosted_processing_region = _read_optional_text(
                "PARSER_VISUAL_MODELS_HOSTED_PROCESSING_REGION",
                maximum_length=128,
            )
            visual_models_hosted_data_class = _read_optional_text(
                "PARSER_VISUAL_MODELS_HOSTED_DATA_CLASS",
                maximum_length=128,
            )
            visual_models_hosted_retention_policy = _read_optional_text(
                "PARSER_VISUAL_MODELS_HOSTED_RETENTION_POLICY",
                maximum_length=128,
            )
            visual_models_hosted_redaction_decision = _read_optional_text(
                "PARSER_VISUAL_MODELS_HOSTED_REDACTION_DECISION",
                maximum_length=32,
            )
            visual_models_hosted_redaction_context_id = _read_optional_text(
                "PARSER_VISUAL_MODELS_HOSTED_REDACTION_CONTEXT_ID",
                maximum_length=128,
            )
            visual_models_hosted_max_requests = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_MAX_REQUESTS",
                0,
                minimum=0,
            )
            visual_models_hosted_max_request_pixels = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_MAX_REQUEST_PIXELS",
                0,
                minimum=0,
            )
            visual_models_hosted_max_document_pixels = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_MAX_DOCUMENT_PIXELS",
                0,
                minimum=0,
            )
            visual_models_hosted_max_cost_microunits = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_MAX_COST_MICROUNITS",
                0,
                minimum=0,
            )
            visual_models_hosted_max_output_tokens = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_MAX_OUTPUT_TOKENS",
                0,
                minimum=0,
            )
            visual_models_hosted_max_timeout_ms = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_MAX_TIMEOUT_MS",
                0,
                minimum=0,
            )
            visual_models_hosted_reserved_cost_microunits = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_RESERVED_COST_MICROUNITS",
                0,
                minimum=0,
            )
            visual_models_hosted_request_max_output_tokens = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_REQUEST_MAX_OUTPUT_TOKENS",
                0,
                minimum=0,
            )
            visual_models_hosted_request_timeout_ms = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_REQUEST_TIMEOUT_MS",
                0,
                minimum=0,
            )
            visual_models_hosted_max_attempts = _read_int(
                "PARSER_VISUAL_MODELS_HOSTED_MAX_ATTEMPTS",
                1,
            )
        visual_models_routing_enabled = _read_bool(
            "PARSER_VISUAL_MODELS_ROUTING_ENABLED",
            False,
        )
        visual_models_routing_preference = "local_first"
        visual_models_routing_max_regions_per_document = 8
        visual_models_routing_max_document_pixels = 8_000_000
        if visual_models_routing_enabled:
            visual_models_routing_preference = os.getenv(
                "PARSER_VISUAL_MODELS_ROUTING_PREFERENCE",
                "local_first",
            ).strip().casefold()
            visual_models_routing_max_regions_per_document = _read_int(
                "PARSER_VISUAL_MODELS_ROUTING_MAX_REGIONS_PER_DOCUMENT",
                8,
            )
            visual_models_routing_max_document_pixels = _read_int(
                "PARSER_VISUAL_MODELS_ROUTING_MAX_DOCUMENT_PIXELS",
                8_000_000,
            )
        visual_models_grounding_enabled = _read_bool(
            "PARSER_VISUAL_MODELS_GROUNDING_ENABLED",
            False,
        )
        visual_models_grounding_bbox_tolerance = 0.0
        if visual_models_grounding_enabled:
            visual_models_grounding_bbox_tolerance = _read_float(
                "PARSER_VISUAL_MODELS_GROUNDING_BBOX_TOLERANCE",
                0.0,
                maximum=10.0,
            )
        visual_models_merge_enabled = _read_bool(
            "PARSER_VISUAL_MODELS_MERGE_ENABLED",
            False,
        )
        visual_models_merge_max_observations = 32
        visual_models_merge_max_added_bytes = 262_144
        # Merge is a complete rollback boundary. Auxiliary resource settings
        # are deliberately ignored while disabled so stale deployment values
        # cannot perturb the unchanged Phase 05 path.
        if visual_models_merge_enabled:
            visual_models_merge_max_observations = _read_int(
                "PARSER_VISUAL_MODELS_MERGE_MAX_OBSERVATIONS",
                32,
            )
            visual_models_merge_max_added_bytes = _read_int(
                "PARSER_VISUAL_MODELS_MERGE_MAX_ADDED_BYTES",
                262_144,
            )
        adapters_conformance_enabled = _read_bool(
            "PARSER_ADAPTERS_CONFORMANCE_ENABLED",
            False,
        )
        adapters_image_parity_enabled = _read_bool(
            "PARSER_ADAPTERS_IMAGE_PARITY_ENABLED",
            False,
        )
        adapters_ooxml_intake_enabled = _read_bool(
            "PARSER_ADAPTERS_OOXML_INTAKE_ENABLED",
            False,
        )
        adapters_docx_native_enabled = _read_bool(
            "PARSER_ADAPTERS_DOCX_NATIVE_ENABLED",
            False,
        )
        adapters_pptx_native_enabled = _read_bool(
            "PARSER_ADAPTERS_PPTX_NATIVE_ENABLED",
            False,
        )
        adapters_xlsx_native_enabled = _read_bool(
            "PARSER_ADAPTERS_XLSX_NATIVE_ENABLED",
            False,
        )
        adapters_office_charts_enabled = _read_bool(
            "PARSER_ADAPTERS_OFFICE_CHARTS_ENABLED",
            False,
        )
        adapters_office_fallback_enabled = _read_bool(
            "PARSER_ADAPTERS_OFFICE_FALLBACK_ENABLED",
            False,
        )
        adapters_future_conformance_gate_enabled = _read_bool(
            "PARSER_ADAPTERS_FUTURE_CONFORMANCE_GATE_ENABLED",
            False,
        )

        adapters_ooxml_max_entries = 2_048
        adapters_ooxml_max_compressed_bytes = 25 * MEBIBYTE
        adapters_ooxml_max_uncompressed_bytes = 100 * MEBIBYTE
        adapters_ooxml_max_part_bytes = 25 * MEBIBYTE
        adapters_ooxml_max_xml_nodes = 250_000
        adapters_ooxml_max_xml_depth = 64
        adapters_ooxml_max_relationships = 10_000
        adapters_ooxml_timeout_seconds = 5.0
        if adapters_ooxml_intake_enabled:
            adapters_ooxml_max_entries = _read_int(
                "PARSER_ADAPTERS_OOXML_MAX_ENTRIES", 2_048
            )
            adapters_ooxml_max_compressed_bytes = _read_int(
                "PARSER_ADAPTERS_OOXML_MAX_COMPRESSED_BYTES", 25 * MEBIBYTE
            )
            adapters_ooxml_max_uncompressed_bytes = _read_int(
                "PARSER_ADAPTERS_OOXML_MAX_UNCOMPRESSED_BYTES", 100 * MEBIBYTE
            )
            adapters_ooxml_max_part_bytes = _read_int(
                "PARSER_ADAPTERS_OOXML_MAX_PART_BYTES", 25 * MEBIBYTE
            )
            adapters_ooxml_max_xml_nodes = _read_int(
                "PARSER_ADAPTERS_OOXML_MAX_XML_NODES", 250_000
            )
            adapters_ooxml_max_xml_depth = _read_int(
                "PARSER_ADAPTERS_OOXML_MAX_XML_DEPTH", 64
            )
            adapters_ooxml_max_relationships = _read_int(
                "PARSER_ADAPTERS_OOXML_MAX_RELATIONSHIPS", 10_000
            )
            adapters_ooxml_timeout_seconds = _read_float(
                "PARSER_ADAPTERS_OOXML_TIMEOUT_SECONDS",
                5.0,
                minimum=0.001,
                maximum=30.0,
            )

        adapters_xlsx_max_sheets = 256
        adapters_xlsx_max_cells = 100_000
        adapters_xlsx_max_rows = 1_048_576
        adapters_xlsx_max_columns = 16_384
        if adapters_xlsx_native_enabled:
            adapters_xlsx_max_sheets = _read_int(
                "PARSER_ADAPTERS_XLSX_MAX_SHEETS", 256
            )
            adapters_xlsx_max_cells = _read_int(
                "PARSER_ADAPTERS_XLSX_MAX_CELLS", 100_000
            )
            adapters_xlsx_max_rows = _read_int(
                "PARSER_ADAPTERS_XLSX_MAX_ROWS", 1_048_576
            )
            adapters_xlsx_max_columns = _read_int(
                "PARSER_ADAPTERS_XLSX_MAX_COLUMNS", 16_384
            )

        adapters_office_fallback_max_regions = 16
        adapters_office_fallback_max_width = 2_048
        adapters_office_fallback_max_height = 2_048
        adapters_office_fallback_max_total_pixels = 8_000_000
        adapters_office_fallback_max_renderer_bytes = 32 * MEBIBYTE
        adapters_office_fallback_timeout_seconds = 5.0
        if adapters_office_fallback_enabled:
            adapters_office_fallback_max_regions = _read_int(
                "PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_REGIONS", 16
            )
            adapters_office_fallback_max_width = _read_int(
                "PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_WIDTH", 2_048
            )
            adapters_office_fallback_max_height = _read_int(
                "PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_HEIGHT", 2_048
            )
            adapters_office_fallback_max_total_pixels = _read_int(
                "PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_TOTAL_PIXELS", 8_000_000
            )
            adapters_office_fallback_max_renderer_bytes = _read_int(
                "PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_RENDERER_BYTES",
                32 * MEBIBYTE,
            )
            adapters_office_fallback_timeout_seconds = _read_float(
                "PARSER_ADAPTERS_OFFICE_FALLBACK_TIMEOUT_SECONDS",
                5.0,
                minimum=0.001,
                maximum=30.0,
            )
        telemetry_enabled = _read_bool("PARSER_TELEMETRY_ENABLED", False)
        telemetry_queue_size = 128
        telemetry_exporter_timeout_ms = 50
        telemetry_max_event_bytes = 4_096
        telemetry_max_labels = 8
        telemetry_max_cardinality_per_label = 16
        if telemetry_enabled:
            telemetry_queue_size = _read_int("PARSER_TELEMETRY_QUEUE_SIZE", 128)
            telemetry_exporter_timeout_ms = _read_int(
                "PARSER_TELEMETRY_EXPORTER_TIMEOUT_MS", 50
            )
            telemetry_max_event_bytes = _read_int(
                "PARSER_TELEMETRY_MAX_EVENT_BYTES", 4_096
            )
            telemetry_max_labels = _read_int("PARSER_TELEMETRY_MAX_LABELS", 8)
            telemetry_max_cardinality_per_label = _read_int(
                "PARSER_TELEMETRY_MAX_CARDINALITY_PER_LABEL", 16
            )
        configured = cls(
            max_upload_bytes=_read_int(
                "MAX_UPLOAD_BYTES",
                20 * MEBIBYTE,
            ),
            max_pages=_read_page_limit(),
            max_image_pixels=_read_int(
                "MAX_IMAGE_PIXELS",
                50_000_000,
            ),
            max_image_total_pixels=_read_int(
                "MAX_IMAGE_TOTAL_PIXELS",
                100_000_000,
            ),
            document_timeout_seconds=_read_float(
                "DOCUMENT_TIMEOUT_SECONDS",
                300.0,
                minimum=1.0,
            ),
            ocr_languages=_read_languages("OCR_LANGUAGES", ("eng",)),
            tesseract_cmd=os.getenv("TESSERACT_CMD", "tesseract"),
            tesseract_data_path=os.getenv("TESSERACT_DATA_PATH") or None,
            targeted_ocr_timeout_seconds=_read_float(
                "TARGETED_OCR_TIMEOUT_SECONDS",
                30.0,
                minimum=1.0,
            ),
            targeted_ocr_scale=_read_float(
                "TARGETED_OCR_SCALE",
                5.0,
                minimum=1.0,
            ),
            targeted_ocr_max_pixels=_read_int(
                "TARGETED_OCR_MAX_PIXELS",
                16_000_000,
            ),
            docling_artifacts_path=os.getenv("DOCLING_ARTIFACTS_PATH") or None,
            parser_latency_prewarm_enabled=prewarm_enabled,
            parser_latency_prewarm_timeout_seconds=prewarm_timeout_seconds,
            parser_latency_prewarm_shutdown_grace_seconds=(
                prewarm_shutdown_grace_seconds
            ),
            parser_latency_prewarm_artifacts_sha256=prewarm_artifacts_sha256,
            parser_latency_prewarm_dependency_sha256=prewarm_dependency_sha256,
            image_primary_ocr_min_confidence=_read_float(
                "IMAGE_PRIMARY_OCR_MIN_CONFIDENCE",
                0.45,
                maximum=1.0,
            ),
            image_low_confidence_min_alnum_chars=_read_int(
                "IMAGE_LOW_CONFIDENCE_MIN_ALNUM_CHARS",
                8,
            ),
            image_heading_min_confidence=_read_float(
                "IMAGE_HEADING_MIN_CONFIDENCE",
                0.75,
                maximum=1.0,
            ),
            image_heading_height_ratio=_read_float(
                "IMAGE_HEADING_HEIGHT_RATIO",
                1.8,
                minimum=1.0,
            ),
            image_heading_min_page_height_ratio=_read_float(
                "IMAGE_HEADING_MIN_PAGE_HEIGHT_RATIO",
                0.025,
                maximum=1.0,
            ),
            image_picture_classification_threshold=_read_float(
                "IMAGE_PICTURE_CLASSIFICATION_THRESHOLD",
                0.6,
                maximum=1.0,
            ),
            image_captioning_enabled=_read_bool(
                "IMAGE_CAPTIONING_ENABLED",
                False,
            ),
            image_captioning_prompt=(
                os.getenv("IMAGE_CAPTIONING_PROMPT")
                or (
                    "Describe this visible image faithfully in one concise "
                    "sentence. Do not infer hidden text, values, or "
                    "relationships."
                )
            ),
            pdf_visual_analysis_enabled=_read_bool(
                "PDF_VISUAL_ANALYSIS_ENABLED",
                True,
            ),
            pdf_render_ocr_min_native_alnum_chars=_read_int(
                "PDF_RENDER_OCR_MIN_NATIVE_ALNUM_CHARS",
                24,
            ),
            pdf_render_ocr_min_layout_coverage=_read_float(
                "PDF_RENDER_OCR_MIN_LAYOUT_COVERAGE",
                0.55,
                maximum=1.0,
            ),
            shared_ir_enabled=_read_bool(
                "PARSER_SHARED_IR_ENABLED",
                False,
            ),
            shared_ir_normalization_enabled=_read_bool(
                "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
                False,
            ),
            canonical_serialization_enabled=_read_bool(
                "PARSER_CANONICAL_SERIALIZATION_ENABLED",
                False,
            ),
            text_integrity_font_audit_enabled=_read_bool(
                "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED",
                False,
            ),
            text_integrity_font_recovery_enabled=_read_bool(
                "PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED",
                False,
            ),
            text_integrity_selective_span_ocr_enabled=_read_bool(
                "PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED",
                False,
            ),
            text_reconciliation_enabled=_read_bool(
                "PARSER_TEXT_RECONCILIATION_ENABLED",
                False,
            ),
            ocr_numeric_cleanup_v2_enabled=_read_bool(
                "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
                False,
            ),
            ocr_spatial_token_preservation_enabled=_read_bool(
                "PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED",
                False,
            ),
            text_integrity_source_alignment_enabled=_read_bool(
                "PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED",
                False,
            ),
            layout_table_captions_enabled=_read_bool(
                "PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED",
                False,
            ),
            layout_visual_relationships_enabled=_read_bool(
                "PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED",
                False,
            ),
            layout_source_notes_enabled=_read_bool(
                "PARSER_LAYOUT_SOURCE_NOTES_ENABLED",
                False,
            ),
            layout_relationship_order_enabled=_read_bool(
                "PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED",
                False,
            ),
            layout_text_run_semantics_enabled=_read_bool(
                "PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED",
                False,
            ),
            layout_forms_enabled=_read_bool(
                "PARSER_LAYOUT_FORMS_ENABLED",
                False,
            ),
            layout_outline_structure_enabled=_read_bool(
                "PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED",
                False,
            ),
            layout_running_regions_enabled=_read_bool(
                "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED",
                False,
            ),
            table_span_fidelity_enabled=_read_bool(
                "PARSER_TABLES_SPAN_FIDELITY_ENABLED",
                False,
            ),
            table_evidence_reconciliation_enabled=_read_bool(
                "PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED",
                False,
            ),
            table_candidate_gate_enabled=_read_bool(
                "PARSER_TABLES_CANDIDATE_GATE_ENABLED",
                False,
            ),
            table_multi_page_merge_enabled=_read_bool(
                "PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED",
                False,
            ),
            visual_structure_schema_enabled=_read_bool(
                "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED",
                False,
            ),
            charts_vector_inventory_enabled=_read_bool(
                "PARSER_CHARTS_VECTOR_INVENTORY_ENABLED",
                False,
            ),
            charts_structure_enabled=_read_bool(
                "PARSER_CHARTS_STRUCTURE_ENABLED",
                False,
            ),
            charts_vector_values_enabled=_read_bool(
                "PARSER_CHARTS_VECTOR_VALUES_ENABLED",
                False,
            ),
            charts_structured_output_enabled=_read_bool(
                "PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED",
                False,
            ),
            charts_raster_structure_enabled=_read_bool(
                "PARSER_CHARTS_RASTER_STRUCTURE_ENABLED",
                False,
            ),
            charts_raster_bar_values_enabled=_read_bool(
                "PARSER_CHARTS_RASTER_BAR_VALUES_ENABLED",
                False,
            ),
            charts_raster_line_values_enabled=_read_bool(
                "PARSER_CHARTS_RASTER_LINE_VALUES_ENABLED",
                False,
            ),
            charts_raster_analysis_enabled=raster_analysis_enabled,
            diagrams_topology_enabled=_read_bool(
                "PARSER_DIAGRAMS_TOPOLOGY_ENABLED",
                False,
            ),
            charts_raster_max_crop_width=raster_max_crop_width,
            charts_raster_max_crop_height=raster_max_crop_height,
            charts_raster_max_total_pixels=raster_max_total_pixels,
            charts_raster_max_work_units=raster_max_work_units,
            charts_raster_timeout_seconds=raster_timeout_seconds,
            charts_raster_minimum_quality=raster_minimum_quality,
            charts_raster_coordinate_tolerance=raster_coordinate_tolerance,
            visual_models_contract_enabled=visual_models_contract_enabled,
            visual_models_max_crop_width=visual_models_max_crop_width,
            visual_models_max_crop_height=visual_models_max_crop_height,
            visual_models_max_crop_pixels=visual_models_max_crop_pixels,
            visual_models_max_request_bytes=visual_models_max_request_bytes,
            visual_models_max_response_bytes=visual_models_max_response_bytes,
            visual_models_max_observations=visual_models_max_observations,
            visual_models_local_enabled=visual_models_local_enabled,
            visual_models_local_usage_approved=(
                visual_models_local_usage_approved
            ),
            visual_models_local_usage_approval_id=(
                visual_models_local_usage_approval_id
            ),
            visual_models_local_artifact_path=visual_models_local_artifact_path,
            visual_models_local_artifact_sha256=(
                visual_models_local_artifact_sha256
            ),
            visual_models_local_artifact_source=(
                visual_models_local_artifact_source
            ),
            visual_models_local_license_id=visual_models_local_license_id,
            visual_models_local_model_name=visual_models_local_model_name,
            visual_models_local_model_version=visual_models_local_model_version,
            visual_models_local_adapter_name=visual_models_local_adapter_name,
            visual_models_local_adapter_version=(
                visual_models_local_adapter_version
            ),
            visual_models_local_prompt_version=visual_models_local_prompt_version,
            visual_models_local_hardware=visual_models_local_hardware,
            visual_models_local_timeout_seconds=(
                visual_models_local_timeout_seconds
            ),
            visual_models_local_max_work_units=visual_models_local_max_work_units,
            visual_models_local_max_concurrency=(
                visual_models_local_max_concurrency
            ),
            visual_models_local_max_memory_bytes=(
                visual_models_local_max_memory_bytes
            ),
            visual_models_local_max_artifact_bytes=(
                visual_models_local_max_artifact_bytes
            ),
            visual_models_hosted_enabled=visual_models_hosted_enabled,
            visual_models_hosted_policy_approved=(
                visual_models_hosted_policy_approved
            ),
            visual_models_hosted_data_approved=(
                visual_models_hosted_data_approved
            ),
            visual_models_hosted_minimization_approved=(
                visual_models_hosted_minimization_approved
            ),
            visual_models_hosted_retention_approved=(
                visual_models_hosted_retention_approved
            ),
            visual_models_hosted_vendor=visual_models_hosted_vendor,
            visual_models_hosted_model=visual_models_hosted_model,
            visual_models_hosted_processing_region=(
                visual_models_hosted_processing_region
            ),
            visual_models_hosted_data_class=visual_models_hosted_data_class,
            visual_models_hosted_retention_policy=(
                visual_models_hosted_retention_policy
            ),
            visual_models_hosted_redaction_decision=(
                visual_models_hosted_redaction_decision
            ),
            visual_models_hosted_redaction_context_id=(
                visual_models_hosted_redaction_context_id
            ),
            visual_models_hosted_max_requests=visual_models_hosted_max_requests,
            visual_models_hosted_max_request_pixels=(
                visual_models_hosted_max_request_pixels
            ),
            visual_models_hosted_max_document_pixels=(
                visual_models_hosted_max_document_pixels
            ),
            visual_models_hosted_max_cost_microunits=(
                visual_models_hosted_max_cost_microunits
            ),
            visual_models_hosted_max_output_tokens=(
                visual_models_hosted_max_output_tokens
            ),
            visual_models_hosted_max_timeout_ms=(
                visual_models_hosted_max_timeout_ms
            ),
            visual_models_hosted_reserved_cost_microunits=(
                visual_models_hosted_reserved_cost_microunits
            ),
            visual_models_hosted_request_max_output_tokens=(
                visual_models_hosted_request_max_output_tokens
            ),
            visual_models_hosted_request_timeout_ms=(
                visual_models_hosted_request_timeout_ms
            ),
            visual_models_hosted_max_attempts=visual_models_hosted_max_attempts,
            visual_models_routing_enabled=visual_models_routing_enabled,
            visual_models_routing_preference=visual_models_routing_preference,
            visual_models_routing_max_regions_per_document=(
                visual_models_routing_max_regions_per_document
            ),
            visual_models_routing_max_document_pixels=(
                visual_models_routing_max_document_pixels
            ),
            visual_models_grounding_enabled=visual_models_grounding_enabled,
            visual_models_grounding_bbox_tolerance=(
                visual_models_grounding_bbox_tolerance
            ),
            visual_models_merge_enabled=visual_models_merge_enabled,
            visual_models_merge_max_observations=(
                visual_models_merge_max_observations
            ),
            visual_models_merge_max_added_bytes=(
                visual_models_merge_max_added_bytes
            ),
            adapters_conformance_enabled=adapters_conformance_enabled,
            adapters_image_parity_enabled=adapters_image_parity_enabled,
            adapters_ooxml_intake_enabled=adapters_ooxml_intake_enabled,
            adapters_docx_native_enabled=adapters_docx_native_enabled,
            adapters_pptx_native_enabled=adapters_pptx_native_enabled,
            adapters_xlsx_native_enabled=adapters_xlsx_native_enabled,
            adapters_office_charts_enabled=adapters_office_charts_enabled,
            adapters_office_fallback_enabled=adapters_office_fallback_enabled,
            adapters_future_conformance_gate_enabled=(
                adapters_future_conformance_gate_enabled
            ),
            adapters_ooxml_max_entries=adapters_ooxml_max_entries,
            adapters_ooxml_max_compressed_bytes=(
                adapters_ooxml_max_compressed_bytes
            ),
            adapters_ooxml_max_uncompressed_bytes=(
                adapters_ooxml_max_uncompressed_bytes
            ),
            adapters_ooxml_max_part_bytes=adapters_ooxml_max_part_bytes,
            adapters_ooxml_max_xml_nodes=adapters_ooxml_max_xml_nodes,
            adapters_ooxml_max_xml_depth=adapters_ooxml_max_xml_depth,
            adapters_ooxml_max_relationships=(
                adapters_ooxml_max_relationships
            ),
            adapters_ooxml_timeout_seconds=adapters_ooxml_timeout_seconds,
            adapters_xlsx_max_sheets=adapters_xlsx_max_sheets,
            adapters_xlsx_max_cells=adapters_xlsx_max_cells,
            adapters_xlsx_max_rows=adapters_xlsx_max_rows,
            adapters_xlsx_max_columns=adapters_xlsx_max_columns,
            adapters_office_fallback_max_regions=(
                adapters_office_fallback_max_regions
            ),
            adapters_office_fallback_max_width=(
                adapters_office_fallback_max_width
            ),
            adapters_office_fallback_max_height=(
                adapters_office_fallback_max_height
            ),
            adapters_office_fallback_max_total_pixels=(
                adapters_office_fallback_max_total_pixels
            ),
            adapters_office_fallback_max_renderer_bytes=(
                adapters_office_fallback_max_renderer_bytes
            ),
            adapters_office_fallback_timeout_seconds=(
                adapters_office_fallback_timeout_seconds
            ),
            telemetry_enabled=telemetry_enabled,
            telemetry_resources_enabled=_read_bool(
                "PARSER_TELEMETRY_RESOURCES_ENABLED", False
            ),
            telemetry_quality_enabled=_read_bool(
                "PARSER_TELEMETRY_QUALITY_ENABLED", False
            ),
            deterministic_confidence_enabled=_read_bool(
                "PARSER_CONFIDENCE_DETERMINISTIC_CALIBRATION_ENABLED", False
            ),
            visual_confidence_enabled=_read_bool(
                "PARSER_CONFIDENCE_VISUAL_CALIBRATION_ENABLED", False
            ),
            review_escalation_enabled=_read_bool(
                "PARSER_REVIEW_ESCALATION_ENABLED", False
            ),
            telemetry_queue_size=telemetry_queue_size,
            telemetry_exporter_timeout_ms=telemetry_exporter_timeout_ms,
            telemetry_max_event_bytes=telemetry_max_event_bytes,
            telemetry_max_labels=telemetry_max_labels,
            telemetry_max_cardinality_per_label=(
                telemetry_max_cardinality_per_label
            ),
            parser_shipping_kill_switch=_read_bool(
                "PARSER_SHIPPING_KILL_SWITCH", False
            ),
            parser_shipping_disabled_capabilities=_read_identifiers(
                "PARSER_SHIPPING_DISABLED_CAPABILITIES"
            ),
        )
        from app.services.feature_flags import shipping_flag_registry

        return shipping_flag_registry().resolve(configured)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable settings instance per application process."""

    return Settings.from_env()
