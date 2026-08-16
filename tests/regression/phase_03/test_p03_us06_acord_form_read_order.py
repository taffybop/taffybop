"""Source-grounded ACORD static-form canonical ownership regression."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder

from app.config import Settings
from app.models import ParseResult
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown


WORKSPACE = Path(__file__).resolve().parents[3]
SOURCE = WORKSPACE / "benchmark-expertmodeldata" / "insurance-acord.pdf"
LOCAL_DOCLING = (WORKSPACE / ".models" / "docling").resolve()
SOURCE_SHA256 = (
    "85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4"
)


def _release_fidelity_settings() -> Settings:
    """Mirror the deterministic all-capabilities benchmark profile."""

    return Settings(
        docling_artifacts_path=str(LOCAL_DOCLING),
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        text_integrity_font_audit_enabled=True,
        text_integrity_font_recovery_enabled=True,
        text_integrity_selective_span_ocr_enabled=True,
        text_reconciliation_enabled=True,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        text_integrity_source_alignment_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
        layout_text_run_semantics_enabled=True,
        layout_forms_enabled=True,
        layout_outline_structure_enabled=True,
        layout_running_regions_enabled=True,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
        table_multi_page_merge_enabled=True,
        visual_structure_schema_enabled=True,
        charts_vector_inventory_enabled=True,
        charts_structure_enabled=True,
        charts_vector_values_enabled=True,
        charts_structured_output_enabled=True,
        charts_raster_structure_enabled=True,
        charts_raster_bar_values_enabled=True,
        charts_raster_line_values_enabled=True,
        charts_raster_analysis_enabled=True,
        diagrams_topology_enabled=True,
    )


@lru_cache(maxsize=1)
def _release_payload() -> dict[str, Any]:
    source = SOURCE.read_bytes()
    assert len(source) == 17_086
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256
    result = parse_document(source, SOURCE.name, _release_fidelity_settings())
    # Exercise the same JSON encoding and public-model revalidation boundary
    # as the HTTP API, not merely the internal model dump.
    encoded = jsonable_encoder(result)
    return ParseResult.model_validate(encoded).model_dump(
        mode="json",
        exclude_none=False,
    )


@pytest.mark.integration
def test_acord_complete_blank_parties_form_owns_canonical_region_once() -> None:
    payload = _release_payload()
    anchors = [
        item
        for page in payload["pages"]
        for item in page["items"]
        if item.get("layout_forms_projected") is True
    ]
    groups = {item["form_group"]["group_key"]: item for item in anchors}
    parties = groups["parties-and-insurers"]
    group = parties["form_group"]

    assert group["status"] == "resolved"
    assert group["interactivity"] == "static"
    assert group["canonical_mode"] == "replace"
    assert {
        key: item["form_group"]["canonical_mode"]
        for key, item in groups.items()
        if key != "parties-and-insurers"
    } == {
        key: "inert"
        for key in groups
        if key != "parties-and-insurers"
    }
    assert len(parties["form_fields"]) == 18
    assert len(parties["form_labels"]) == 14
    assert all(
        field["value"] is None and field["value_state"] == "empty"
        for field in parties["form_fields"]
    )

    canonical = payload["canonical_presentation"]
    block = next(
        candidate
        for candidate in canonical["pages"][0]["blocks"]
        if candidate["primary_element_id"] == group["anchor_element_id"]
    )
    assert block["contributing_element_ids"] == [
        group["anchor_element_id"],
        *(
            element_id
            for element_id in group["contributor_element_ids"]
            if element_id != group["anchor_element_id"]
        ),
    ]
    assert (
        block["markdown"].count(
            "| --- | --- | --- | --- | --- | --- |"
        )
        == 1
    )
    assert block["markdown"].splitlines()[:6] == [
        "| PRODUCER |  | CONTACT NAME: |  |  |  |",
        "| --- | --- | --- | --- | --- | --- |",
        "|  |  | PHONE (A/C, No, Ext): |  | FAX (A/C, No): |  |",
        "|  |  | E-MAIL ADDRESS: |  |  |  |",
        "|  |  | INSURER(S) AFFORDING COVERAGE |  | NAIC # |  |",
        "|  |  | INSURER A : |  |  |  |",
    ]
    for label in parties["form_labels"]:
        assert block["markdown"].count(label["text"]) == 1

    suppressed = {
        candidate["primary_element_id"]: candidate
        for candidate in canonical["pages"][0]["blocks"]
        if candidate["primary_element_id"]
        in set(group["contributor_element_ids"]) - {group["anchor_element_id"]}
    }
    assert set(suppressed) == set(group["contributor_element_ids"]) - {
        group["anchor_element_id"]
    }
    assert all(
        candidate["markdown"] == ""
        and candidate["text"] == ""
        and candidate["omission_reason"] == "consumed_by_relationship"
        and candidate["suppressed_by_element_id"] == group["anchor_element_id"]
        for candidate in suppressed.values()
    )

    markdown = to_markdown(ParseResult.model_validate(payload))
    assert markdown == canonical["full"]["markdown"]
    lowered = markdown.casefold()
    assert "empty source-visible field" not in lowered
    assert "phone name:" not in lowered
    assert "[signature]" not in lowered
