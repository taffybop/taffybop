"""Central ownership and rollback controls for shipped parser flags.

The registry is deliberately configuration-only.  It never enables a flag and
never reads document or secret-bearing values.  Existing ``Settings`` fields
and environment names remain the source of truth for compatibility; this
module adds one validated inventory and deterministic disable behavior around
them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any, Iterable


class FeatureFlagConfigurationError(ValueError):
    """Raised when a shipping flag graph or effective profile is unsafe."""


@dataclass(frozen=True, slots=True)
class ShippingFlag:
    """Non-secret operational metadata for one shipped optional behavior."""

    name: str
    setting: str
    environment: str
    owner: str
    capability: str
    default: bool = False
    dependencies: tuple[str, ...] = ()
    rollback: str = "disable_flag"


class ShippingFlagRegistry:
    """Validated flag inventory with fail-closed dependency resolution."""

    schema_version = "1.0"

    def __init__(self, flags: Iterable[ShippingFlag]) -> None:
        ordered = tuple(flags)
        by_setting = {flag.setting: flag for flag in ordered}
        by_name = {flag.name: flag for flag in ordered}
        by_environment = {flag.environment: flag for flag in ordered}
        if not ordered:
            raise FeatureFlagConfigurationError("shipping flag registry is empty")
        if len(by_setting) != len(ordered):
            raise FeatureFlagConfigurationError("duplicate shipping setting")
        if len(by_name) != len(ordered):
            raise FeatureFlagConfigurationError("duplicate shipping flag name")
        if len(by_environment) != len(ordered):
            raise FeatureFlagConfigurationError("duplicate shipping environment")
        for flag in ordered:
            if not flag.owner or not flag.capability or not flag.rollback:
                raise FeatureFlagConfigurationError(
                    f"{flag.environment} is missing ownership or rollback metadata"
                )
            missing = sorted(set(flag.dependencies) - set(by_setting))
            if missing:
                raise FeatureFlagConfigurationError(
                    f"{flag.environment} has unknown dependencies: "
                    + ", ".join(missing)
                )
        self._assert_acyclic(by_setting)
        self._flags = tuple(sorted(ordered, key=lambda value: value.name))
        self._by_setting = by_setting
        self._capabilities = frozenset(flag.capability for flag in ordered)

    @staticmethod
    def _assert_acyclic(by_setting: dict[str, ShippingFlag]) -> None:
        visiting: set[str] = set()
        complete: set[str] = set()

        def visit(setting: str) -> None:
            if setting in complete:
                return
            if setting in visiting:
                raise FeatureFlagConfigurationError(
                    f"shipping flag dependency cycle includes {setting}"
                )
            visiting.add(setting)
            for dependency in by_setting[setting].dependencies:
                visit(dependency)
            visiting.remove(setting)
            complete.add(setting)

        for setting in by_setting:
            visit(setting)

    @property
    def flags(self) -> tuple[ShippingFlag, ...]:
        return self._flags

    @property
    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    def validate(self, settings: Any) -> None:
        """Validate types, safe defaults, and every enabled dependency."""

        for flag in self._flags:
            if not hasattr(settings, flag.setting):
                raise FeatureFlagConfigurationError(
                    f"{flag.environment} has no Settings field {flag.setting}"
                )
            value = getattr(settings, flag.setting)
            if not isinstance(value, bool):
                raise FeatureFlagConfigurationError(
                    f"{flag.environment} must resolve to a boolean"
                )
            if value:
                missing = [
                    self._by_setting[dependency].environment
                    for dependency in flag.dependencies
                    if getattr(settings, dependency) is not True
                ]
                if missing:
                    raise FeatureFlagConfigurationError(
                        f"{flag.environment} requires " + ", ".join(missing)
                    )

    def resolve(self, settings: Any) -> Any:
        """Return an immutable effective profile after operational disables.

        Disabling a capability also disables its dependants, so rollback never
        leaves an invalid child flag enabled.  This resolution only changes
        registered booleans and cannot expose configuration values.
        """

        disabled = tuple(getattr(settings, "parser_shipping_disabled_capabilities", ()))
        unknown = sorted(set(disabled) - self._capabilities)
        if unknown:
            raise FeatureFlagConfigurationError(
                "PARSER_SHIPPING_DISABLED_CAPABILITIES contains unknown values: "
                + ", ".join(unknown)
            )
        values = {
            flag.setting: bool(getattr(settings, flag.setting))
            for flag in self._flags
        }
        if bool(getattr(settings, "parser_shipping_kill_switch", False)):
            values = {setting: False for setting in values}
        else:
            for flag in self._flags:
                if flag.capability in disabled:
                    values[flag.setting] = False

            changed = True
            while changed:
                changed = False
                for flag in self._flags:
                    if values[flag.setting] and any(
                        not values[dependency] for dependency in flag.dependencies
                    ):
                        values[flag.setting] = False
                        changed = True

        updates = {
            setting: value
            for setting, value in values.items()
            if getattr(settings, setting) is not value
        }
        effective = replace(settings, **updates) if updates else settings
        self.validate(effective)
        return effective

    def rollback(self, settings: Any, capability: str) -> Any:
        """Disable one capability and every dependent optional behavior."""

        if capability not in self._capabilities:
            raise FeatureFlagConfigurationError(
                f"unknown rollback capability: {capability}"
            )
        disabled = tuple(
            sorted(
                set(
                    getattr(settings, "parser_shipping_disabled_capabilities", ())
                )
                | {capability}
            )
        )
        return self.resolve(
            replace(
                settings,
                parser_shipping_disabled_capabilities=disabled,
            )
        )

    def effective_configuration(self, settings: Any) -> dict[str, Any]:
        """Return a bounded, non-secret configuration record."""

        effective = self.resolve(settings)
        return {
            "schema_version": self.schema_version,
            "global_kill_switch": bool(effective.parser_shipping_kill_switch),
            "disabled_capabilities": list(
                effective.parser_shipping_disabled_capabilities
            ),
            "flags": [
                {
                    "name": flag.name,
                    "environment": flag.environment,
                    "owner": flag.owner,
                    "capability": flag.capability,
                    "enabled": bool(getattr(effective, flag.setting)),
                    "default": flag.default,
                    "dependencies": [
                        self._by_setting[value].name
                        for value in flag.dependencies
                    ],
                    "rollback": flag.rollback,
                }
                for flag in self._flags
            ],
        }


def _flag(
    setting: str,
    environment: str,
    owner: str,
    capability: str,
    *dependencies: str,
) -> ShippingFlag:
    return ShippingFlag(
        name=environment.removeprefix("PARSER_").casefold().replace("_", "."),
        setting=setting,
        environment=environment,
        owner=owner,
        capability=capability,
        dependencies=tuple(dependencies),
        rollback=f"set {environment}=false",
    )


@lru_cache(maxsize=1)
def shipping_flag_registry() -> ShippingFlagRegistry:
    """Return the centralized Phase 01–08 shipping-flag registry."""

    flags = (
        _flag("shared_ir_enabled", "PARSER_SHARED_IR_ENABLED", "ir", "ir"),
        _flag(
            "shared_ir_normalization_enabled",
            "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
            "ir",
            "ir",
            "shared_ir_enabled",
        ),
        _flag(
            "canonical_serialization_enabled",
            "PARSER_CANONICAL_SERIALIZATION_ENABLED",
            "serialization",
            "ir",
            "shared_ir_normalization_enabled",
        ),
        _flag(
            "text_integrity_font_audit_enabled",
            "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED",
            "text-integrity",
            "text",
            "shared_ir_normalization_enabled",
        ),
        _flag(
            "text_integrity_font_recovery_enabled",
            "PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED",
            "text-integrity",
            "text",
            "text_integrity_font_audit_enabled",
        ),
        _flag(
            "text_integrity_selective_span_ocr_enabled",
            "PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED",
            "text-integrity",
            "text",
            "shared_ir_normalization_enabled",
            "text_integrity_font_audit_enabled",
            "text_integrity_font_recovery_enabled",
        ),
        _flag(
            "text_reconciliation_enabled",
            "PARSER_TEXT_RECONCILIATION_ENABLED",
            "text-integrity",
            "text",
            "shared_ir_enabled",
            "shared_ir_normalization_enabled",
            "text_integrity_font_audit_enabled",
            "text_integrity_font_recovery_enabled",
            "text_integrity_selective_span_ocr_enabled",
        ),
        _flag(
            "ocr_numeric_cleanup_v2_enabled",
            "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
            "ocr",
            "text",
        ),
        _flag(
            "ocr_spatial_token_preservation_enabled",
            "PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED",
            "ocr",
            "text",
            "ocr_numeric_cleanup_v2_enabled",
        ),
        _flag(
            "text_integrity_source_alignment_enabled",
            "PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED",
            "text-integrity",
            "text",
            "text_reconciliation_enabled",
            "ocr_numeric_cleanup_v2_enabled",
            "ocr_spatial_token_preservation_enabled",
        ),
        *(
            _flag(
                setting,
                environment,
                "layout",
                "layout",
                "shared_ir_normalization_enabled",
            )
            for setting, environment in (
                ("layout_table_captions_enabled", "PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED"),
                ("layout_visual_relationships_enabled", "PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED"),
                ("layout_source_notes_enabled", "PARSER_LAYOUT_SOURCE_NOTES_ENABLED"),
                ("layout_relationship_order_enabled", "PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED"),
            )
        ),
        *(
            _flag(
                setting,
                environment,
                "layout",
                "layout",
                "shared_ir_enabled",
                "shared_ir_normalization_enabled",
                "canonical_serialization_enabled",
                "layout_relationship_order_enabled",
            )
            for setting, environment in (
                ("layout_text_run_semantics_enabled", "PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED"),
                ("layout_forms_enabled", "PARSER_LAYOUT_FORMS_ENABLED"),
                ("layout_outline_structure_enabled", "PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED"),
                ("layout_running_regions_enabled", "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED"),
            )
        ),
        _flag(
            "table_span_fidelity_enabled",
            "PARSER_TABLES_SPAN_FIDELITY_ENABLED",
            "tables",
            "tables",
            "shared_ir_enabled",
            "shared_ir_normalization_enabled",
            "canonical_serialization_enabled",
        ),
        _flag(
            "table_evidence_reconciliation_enabled",
            "PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED",
            "tables",
            "tables",
            "table_span_fidelity_enabled",
        ),
        _flag(
            "table_candidate_gate_enabled",
            "PARSER_TABLES_CANDIDATE_GATE_ENABLED",
            "tables",
            "tables",
            "table_evidence_reconciliation_enabled",
        ),
        _flag(
            "table_multi_page_merge_enabled",
            "PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED",
            "tables",
            "tables",
            "table_candidate_gate_enabled",
        ),
        _flag(
            "visual_structure_schema_enabled",
            "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED",
            "visual",
            "visual",
        ),
        _flag(
            "charts_vector_inventory_enabled",
            "PARSER_CHARTS_VECTOR_INVENTORY_ENABLED",
            "charts",
            "visual",
            "visual_structure_schema_enabled",
        ),
        _flag(
            "charts_structure_enabled",
            "PARSER_CHARTS_STRUCTURE_ENABLED",
            "charts",
            "visual",
            "charts_vector_inventory_enabled",
        ),
        _flag(
            "charts_vector_values_enabled",
            "PARSER_CHARTS_VECTOR_VALUES_ENABLED",
            "charts",
            "visual",
            "charts_structure_enabled",
        ),
        _flag(
            "charts_structured_output_enabled",
            "PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED",
            "charts",
            "visual",
            "visual_structure_schema_enabled",
            "shared_ir_enabled",
            "shared_ir_normalization_enabled",
            "canonical_serialization_enabled",
        ),
        _flag(
            "charts_raster_structure_enabled",
            "PARSER_CHARTS_RASTER_STRUCTURE_ENABLED",
            "charts",
            "visual",
            "visual_structure_schema_enabled",
            "ocr_spatial_token_preservation_enabled",
        ),
        *(
            _flag(
                setting,
                environment,
                "charts",
                "visual",
                "charts_raster_structure_enabled",
                "charts_structured_output_enabled",
            )
            for setting, environment in (
                ("charts_raster_bar_values_enabled", "PARSER_CHARTS_RASTER_BAR_VALUES_ENABLED"),
                ("charts_raster_line_values_enabled", "PARSER_CHARTS_RASTER_LINE_VALUES_ENABLED"),
            )
        ),
        _flag(
            "charts_raster_analysis_enabled",
            "PARSER_CHARTS_RASTER_ANALYSIS_ENABLED",
            "charts",
            "visual",
            "visual_structure_schema_enabled",
            "ocr_spatial_token_preservation_enabled",
            "charts_raster_structure_enabled",
            "charts_structured_output_enabled",
        ),
        _flag(
            "diagrams_topology_enabled",
            "PARSER_DIAGRAMS_TOPOLOGY_ENABLED",
            "diagrams",
            "visual",
            "visual_structure_schema_enabled",
            "ocr_spatial_token_preservation_enabled",
        ),
        _flag(
            "visual_models_contract_enabled",
            "PARSER_VISUAL_MODELS_CONTRACT_ENABLED",
            "models",
            "visual_models",
            "visual_structure_schema_enabled",
        ),
        *(
            _flag(
                setting,
                environment,
                "models",
                "visual_models",
                "visual_models_contract_enabled",
            )
            for setting, environment in (
                ("visual_models_local_enabled", "PARSER_VISUAL_MODELS_LOCAL_ENABLED"),
                ("visual_models_hosted_enabled", "PARSER_VISUAL_MODELS_HOSTED_ENABLED"),
                ("visual_models_routing_enabled", "PARSER_VISUAL_MODELS_ROUTING_ENABLED"),
            )
        ),
        _flag(
            "visual_models_grounding_enabled",
            "PARSER_VISUAL_MODELS_GROUNDING_ENABLED",
            "models",
            "visual_models",
            "visual_models_routing_enabled",
        ),
        _flag(
            "visual_models_merge_enabled",
            "PARSER_VISUAL_MODELS_MERGE_ENABLED",
            "models",
            "visual_models",
            "visual_models_contract_enabled",
            "visual_models_routing_enabled",
            "visual_models_grounding_enabled",
            "shared_ir_enabled",
            "shared_ir_normalization_enabled",
            "canonical_serialization_enabled",
        ),
        _flag(
            "adapters_conformance_enabled",
            "PARSER_ADAPTERS_CONFORMANCE_ENABLED",
            "adapters",
            "adapters",
        ),
        *(
            _flag(
                setting,
                environment,
                "adapters",
                "adapters",
                "adapters_conformance_enabled",
            )
            for setting, environment in (
                ("adapters_image_parity_enabled", "PARSER_ADAPTERS_IMAGE_PARITY_ENABLED"),
                ("adapters_ooxml_intake_enabled", "PARSER_ADAPTERS_OOXML_INTAKE_ENABLED"),
            )
        ),
        *(
            _flag(
                setting,
                environment,
                "adapters",
                "adapters",
                "adapters_conformance_enabled",
                "adapters_ooxml_intake_enabled",
            )
            for setting, environment in (
                ("adapters_docx_native_enabled", "PARSER_ADAPTERS_DOCX_NATIVE_ENABLED"),
                ("adapters_pptx_native_enabled", "PARSER_ADAPTERS_PPTX_NATIVE_ENABLED"),
                ("adapters_xlsx_native_enabled", "PARSER_ADAPTERS_XLSX_NATIVE_ENABLED"),
            )
        ),
        _flag(
            "adapters_office_charts_enabled",
            "PARSER_ADAPTERS_OFFICE_CHARTS_ENABLED",
            "adapters",
            "adapters",
            "adapters_pptx_native_enabled",
            "adapters_xlsx_native_enabled",
        ),
        _flag(
            "adapters_office_fallback_enabled",
            "PARSER_ADAPTERS_OFFICE_FALLBACK_ENABLED",
            "adapters",
            "adapters_office_fallback",
            "adapters_image_parity_enabled",
            "adapters_docx_native_enabled",
            "adapters_pptx_native_enabled",
            "adapters_xlsx_native_enabled",
            "adapters_office_charts_enabled",
        ),
        _flag(
            "adapters_future_conformance_gate_enabled",
            "PARSER_ADAPTERS_FUTURE_CONFORMANCE_GATE_ENABLED",
            "adapters",
            "adapters",
            "adapters_conformance_enabled",
            "adapters_office_fallback_enabled",
        ),
        _flag(
            "telemetry_enabled",
            "PARSER_TELEMETRY_ENABLED",
            "observability",
            "telemetry",
        ),
        _flag(
            "telemetry_resources_enabled",
            "PARSER_TELEMETRY_RESOURCES_ENABLED",
            "observability",
            "telemetry",
            "telemetry_enabled",
        ),
        _flag(
            "telemetry_quality_enabled",
            "PARSER_TELEMETRY_QUALITY_ENABLED",
            "quality",
            "telemetry",
            "telemetry_enabled",
        ),
        _flag(
            "deterministic_confidence_enabled",
            "PARSER_CONFIDENCE_DETERMINISTIC_CALIBRATION_ENABLED",
            "quality",
            "confidence",
            "telemetry_resources_enabled",
            "telemetry_quality_enabled",
        ),
        _flag(
            "visual_confidence_enabled",
            "PARSER_CONFIDENCE_VISUAL_CALIBRATION_ENABLED",
            "quality",
            "confidence",
            "telemetry_resources_enabled",
            "telemetry_quality_enabled",
        ),
        _flag(
            "review_escalation_enabled",
            "PARSER_REVIEW_ESCALATION_ENABLED",
            "review",
            "review",
            "deterministic_confidence_enabled",
            "visual_confidence_enabled",
        ),
    )
    return ShippingFlagRegistry(flags)
