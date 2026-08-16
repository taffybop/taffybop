"""P02-US04 regressions for table-owned supplemental page OCR."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from app.config import Settings
from app.models import ParseResult
from app.services import pipeline
from app.services import table_semantics
from app.services.ocr import ImageRegion, OCRLine
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
from app.services.source_text_alignment import (
    TABLE_OWNED_SUPPLEMENTAL_REASON,
)
from tests.fixtures.phase_03.running_regions.oracle import (
    PREDECESSOR_CONFIGURATION,
    PREDECESSOR_OUTPUT_IDENTITIES,
    PREDECESSOR_OUTPUT_ROOT,
    SOURCE_IDENTITIES,
)


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
FRONTEND = WORKSPACE / "frontend"
SOURCE_SHA256 = {
    "postal-10k": (
        "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74"
    ),
    "ny-timetable": (
        "f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30"
    ),
    "finance-10k": (
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086"
    ),
}


def _region(*lines: tuple[str, dict[str, float]]) -> ImageRegion:
    return ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 320, "h": 180},
        pixel_width=320,
        pixel_height=180,
        area_ratio=1.0,
        lines=[
            OCRLine(
                text=text,
                bbox=bbox,
                confidence=0.94,
                word_count=max(len(text.split()), 1),
            )
            for text, bbox in lines
        ],
        content_type="page_image",
        region_role="page_source",
        region_origin="pdf_page_render",
        coordinate_unit="pt",
    )


def _supported_table() -> dict[str, Any]:
    return {
        "type": "table",
        "bbox": pipeline._bbox(10, 10, 200, 100),
        "rows": [["CIO", "Chief Information Officer"]],
        "table_candidate_gate_reasons": [
            "source_supported_rectangular_grid"
        ],
        "parse_concerns": [],
    }


def _empty_page() -> dict[str, Any]:
    return {
        "page_index": 1,
        "page_number": 1,
        "page_label": "1",
        "page_width": 320.0,
        "page_height": 180.0,
        "unit": "pt",
        "success": True,
        "items": [],
        "warnings": [],
    }


def _supplement_then_merge(
    *,
    table: dict[str, Any],
    region: ImageRegion,
    body: dict[int, list[dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    body_items = body if body is not None else {1: []}
    source_identity = hashlib.sha256(b"generic pipeline boundary source").hexdigest()
    pipeline._supplement_unrepresented_raster_ocr(
        body_items,
        {1: [table]},
        {1: [region]},
        source_document_identity=source_identity,
    )
    supplemented = deepcopy(body_items[1])
    page = _empty_page()
    pipeline._merge_body_items(
        [page],
        body_items,
        {1: [table]},
        {1: [region]},
        {},
        {},
        source_document_identity=source_identity,
    )
    return page, supplemented


def _assert_pipeline_issued_contributor(
    item: dict[str, Any],
    *,
    expected_text: str,
) -> None:
    contributor = item.get("ocr_contributor")
    # FFD-011 stamps a closed contributor record before terminal alignment.
    # Keeping this assertion here makes the supplement/merge regression cover
    # that provenance seam without reconstructing a benchmark-specific ID.
    assert isinstance(contributor, dict)
    assert set(contributor) == {
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
    }
    assert contributor["schema_version"] == "1.0"
    assert contributor["policy_id"] == "p02-supplemental-ocr-contributor-v1"
    assert contributor["source_document_identity"] == hashlib.sha256(
        b"generic pipeline boundary source"
    ).hexdigest()
    assert contributor["page_index"] == 1
    assert contributor["region_object_index"] == 0
    assert contributor["region_origin"] == "pdf_page_render"
    assert contributor["region_role"] == "page_source"
    assert contributor["line_index"] == 0
    assert contributor["ocr_pass"] == "standard"
    assert contributor["coordinate_unit"] == "pt"
    assert contributor["raw_text"] == expected_text
    assert contributor["confidence"] == pytest.approx(0.94)
    canonical = {
        key: value for key, value in contributor.items() if key != "id"
    }
    expected_digest = hashlib.sha256(
        json.dumps(
            canonical,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert contributor["id"] == f"ocr-contributor-{expected_digest}"


def test_table_region_without_complete_cell_lineage_fails_closed(
) -> None:
    region = _region(
        ("ClO", {"x": 20, "y": 30, "w": 25, "h": 8}),
    )
    table = _supported_table()
    original_rows = [row[:] for row in table["rows"]]
    body: dict[int, list[dict[str, Any]]] = {1: []}

    pipeline._supplement_unrepresented_raster_ocr(
        body,
        {1: [table]},
        {1: [region]},
    )

    assert [item["value"] for item in body[1]] == ["ClO"]
    assert table["rows"] == original_rows
    assert [line.text for line in region.lines] == ["ClO"]


def test_source_supported_table_cannot_suppress_outside_ocr() -> None:
    region = _region(
        ("OUTSIDE TABLE", {"x": 20, "y": 150, "w": 90, "h": 8}),
    )
    body: dict[int, list[dict[str, Any]]] = {1: []}

    pipeline._supplement_unrepresented_raster_ocr(
        body,
        {1: [_supported_table()]},
        {1: [region]},
    )

    assert [item["value"] for item in body[1]] == ["OUTSIDE TABLE"]


def test_unresolved_table_cannot_suppress_contained_supplemental_ocr() -> None:
    region = _region(
        ("RECOVER ME", {"x": 20, "y": 30, "w": 70, "h": 8}),
    )
    unresolved = {
        "type": "table_candidate",
        "bbox": pipeline._bbox(10, 10, 200, 100),
        "rows": [["Unreadable", "grid"]],
        "table_candidate_gate": {"outcome": "unresolved"},
        "table_candidate_gate_reasons": ["insufficient_table_support"],
        "parse_concerns": ["table_candidate_ownership_ambiguous"],
    }
    body: dict[int, list[dict[str, Any]]] = {1: []}

    pipeline._supplement_unrepresented_raster_ocr(
        body,
        {1: [unresolved]},
        {1: [region]},
    )

    assert [item["value"] for item in body[1]] == ["RECOVER ME"]


def test_gate_without_complete_cell_lineage_cannot_suppress_fallback(
) -> None:
    region = _region(
        ("TABLE CELL OCR", {"x": 20, "y": 30, "w": 90, "h": 8}),
    )
    table = {
        "type": "table",
        "bbox": pipeline._bbox(10, 10, 200, 100),
        "rows": [["Canonical", "cell"]],
        "table_candidate_gate": {"outcome": "canonical_table"},
    }
    body: dict[int, list[dict[str, Any]]] = {1: []}

    pipeline._supplement_unrepresented_raster_ocr(
        body,
        {1: [table]},
        {1: [region]},
    )

    assert [item["value"] for item in body[1]] == ["TABLE CELL OCR"]
    assert table["rows"] == [["Canonical", "cell"]]
    assert region.lines[0].text == "TABLE CELL OCR"


def test_partial_table_cell_ocr_survives_supplement_and_merge_until_proof() -> None:
    table = _supported_table()
    region = _region(
        ("Chief Information", {"x": 82, "y": 30, "w": 92, "h": 8}),
    )

    page, supplemented = _supplement_then_merge(table=table, region=region)

    assert [item["value"] for item in supplemented] == ["Chief Information"]
    surviving = [
        item
        for item in page["items"]
        if item.get("type") != "table"
        and item.get("value") == "Chief Information"
    ]
    assert len(surviving) == 1
    assert surviving[0]["source"] == "ocr"
    assert "layout_omission_recovered_by_ocr" in surviving[0]["parse_concerns"]
    _assert_pipeline_issued_contributor(
        surviving[0],
        expected_text="Chief Information",
    )


def test_independent_ocr_and_nearby_caption_survive_merge_until_proof() -> None:
    table = _supported_table()
    region = _region()
    independent = {
        "type": "text",
        "value": "CIO",
        "md": "CIO",
        "bbox": pipeline._bbox(20, 30, 25, 8),
        "source": "independent_vision_ocr",
        "confidence": 0.91,
        "label": "ocr_text",
        "raw_ocr_text": "CIO",
        "parse_concerns": ["independent_ocr_candidate"],
        "ocr_contributor": {
            "schema_version": "1.0",
            "policy_id": "independent-ocr-v1",
            "id": "independent-candidate",
        },
    }
    caption = {
        "type": "caption",
        "value": "CIO",
        "md": "CIO",
        "bbox": pipeline._bbox(12, 2, 30, 8),
        "source": "native",
        "confidence": None,
        "label": "table_caption",
    }
    page = _empty_page()

    pipeline._merge_body_items(
        [page],
        {1: [independent, caption]},
        {1: [table]},
        {1: [region]},
        {},
        {},
    )

    survivors = [item for item in page["items"] if item.get("type") != "table"]
    assert [(item["type"], item["source"], item["label"]) for item in survivors] == [
        ("caption", "native", "table_caption"),
        ("text", "independent_vision_ocr", "ocr_text"),
    ]
    assert survivors[1]["ocr_contributor"] == independent["ocr_contributor"]


def test_nearby_table_caption_does_not_block_attributable_supplemental_ocr() -> None:
    table = _supported_table()
    region = _region(
        ("CIO", {"x": 20, "y": 30, "w": 25, "h": 8}),
    )
    caption = {
        "type": "caption",
        "value": "Glossary of roles",
        "md": "Glossary of roles",
        "bbox": pipeline._bbox(10, 1, 100, 8),
        "source": "native",
        "confidence": None,
        "label": "table_caption",
    }

    page, supplemented = _supplement_then_merge(
        table=table,
        region=region,
        body={1: [caption]},
    )

    assert [item["value"] for item in supplemented] == ["Glossary of roles", "CIO"]
    assert [
        (item["type"], item["value"])
        for item in page["items"]
        if item.get("type") != "table"
    ] == [
        ("caption", "Glossary of roles"),
        ("text", "CIO"),
    ]
    _assert_pipeline_issued_contributor(
        next(item for item in page["items"] if item.get("value") == "CIO"),
        expected_text="CIO",
    )


@pytest.mark.parametrize("fragment", ("ew", "741"))
def test_ny_short_fragments_survive_pipeline_boundary_without_structural_proof(
    fragment: str,
) -> None:
    table = {
        "type": "table",
        "bbox": pipeline._bbox(10, 10, 280, 130),
        "rows": [["Weekdays to The Bronx", "741"], ["Notes", "ew"]],
        "source": "native",
    }
    region = _region(
        (fragment, {"x": 40, "y": 60, "w": 22, "h": 8}),
    )

    page, supplemented = _supplement_then_merge(table=table, region=region)

    assert [item["value"] for item in supplemented] == [fragment]
    surviving = [
        item
        for item in page["items"]
        if item.get("type") != "table" and item.get("value") == fragment
    ]
    assert len(surviving) == 1
    _assert_pipeline_issued_contributor(surviving[0], expected_text=fragment)


def _local_fidelity_settings() -> Settings:
    return Settings(
        docling_artifacts_path=str(WORKSPACE / ".models" / "docling"),
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
    )


@lru_cache(maxsize=None)
def _parse(case: str) -> dict[str, Any]:
    path = CORPUS / f"{case}.pdf"
    source = path.read_bytes()
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256[case]
    return parse_document(
        source,
        path.name,
        _local_fidelity_settings(),
    ).model_dump(mode="json", exclude_none=False)


def _render_public_dom(
    payload: dict[str, Any],
    output_root: Path,
    *,
    case: str,
) -> str:
    case_dir = output_root / case
    case_dir.mkdir(parents=True)
    (case_dir / "response.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "node",
            str(FRONTEND / "tools" / "capture-rendered-ui.mjs"),
            "--run-dir",
            str(output_root),
            "--case",
            case,
            "--view",
            "full",
        ],
        cwd=FRONTEND,
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = json.loads(
        (case_dir / "pages" / "page-1" / "rendered-dom.json").read_text(
            encoding="utf-8"
        )
    )
    return str(rendered["html"])


def _rows_sha256(rows: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _finance_p04_fail_closed_settings() -> Settings:
    settings = Settings(
        **PREDECESSOR_CONFIGURATION,
        table_span_fidelity_enabled=True,
    )
    assert settings.text_integrity_source_alignment_enabled is False
    assert settings.table_evidence_reconciliation_enabled is False
    assert settings.table_candidate_gate_enabled is False
    assert settings.table_multi_page_merge_enabled is False
    return settings


@lru_cache(maxsize=1)
def _parse_finance_p04_fail_closed() -> dict[str, Any]:
    case = "finance-10k"
    identity = SOURCE_IDENTITIES[case]
    path = WORKSPACE / identity["path"]
    source = path.read_bytes()
    assert len(source) == identity["size_bytes"]
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256[case]
    return parse_document(
        source,
        path.name,
        _finance_p04_fail_closed_settings(),
    ).model_dump(mode="json", exclude_none=True)


def _frozen_finance_predecessor() -> dict[str, Any]:
    case = "finance-10k"
    path = WORKSPACE / PREDECESSOR_OUTPUT_ROOT / case / "our-output.json"
    raw = path.read_bytes()
    identity = PREDECESSOR_OUTPUT_IDENTITIES[case]
    assert len(raw) == identity["size_bytes"]
    assert hashlib.sha256(raw).hexdigest() == identity["sha256"]
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def _bbox_intersection_area(
    first: dict[str, Any],
    second: dict[str, Any],
) -> float:
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
    return max(0.0, right - left) * max(0.0, bottom - top)


@pytest.mark.integration
def test_real_postal_table_owns_cio_and_fers_without_detached_ocr() -> None:
    payload = _parse("postal-10k")
    scalar_values = [
        item["value"]
        for page in payload["pages"]
        for item in page["items"]
        if isinstance(item.get("value"), str)
    ]
    glossary = next(
        item
        for item in payload["pages"][0]["items"]
        if item.get("type") == "table"
        and ["CIO", "Chief Information Officer"] in item.get("rows", [])
    )

    assert ["CIO", "Chief Information Officer"] in glossary["rows"]
    assert ["FERS", "Federal Employees Retirement System"] in glossary["rows"]
    assert len(glossary["rows"]) == 40
    assert _rows_sha256(glossary["rows"]) == (
        "cabcd3437307c5d51fafbc0c3de21594a15388327d767537a81a78864a3d3d98"
    )
    assert glossary["rows"][10] == [
        "CARES Act",
        "Coronavirus Aid, Relief, and Economic Security Act , enacted as "
        "Public Law 116-136",
    ]
    assert glossary["rows"][15] == ["CIO", "Chief Information Officer"]
    assert glossary["rows"][33] == [
        "Exchange Act",
        "Securities and Exchange Act of 1934 , enacted as Public Law 73-291",
    ]
    assert glossary["rows"][37:40] == [
        ["FEGLI", "Federal Employees Group Life Insurance"],
        ["FEHB", "Federal Employees Health Benefits"],
        ["FERS", "Federal Employees Retirement System"],
    ]
    page_2_table = next(
        item
        for item in payload["pages"][1]["items"]
        if isinstance(item.get("rows"), list)
    )
    page_3_table = next(
        item
        for item in payload["pages"][2]["items"]
        if isinstance(item.get("rows"), list)
    )
    assert (page_2_table["row_count"], page_2_table["column_count"]) == (
        17,
        4,
    )
    assert (page_3_table["row_count"], page_3_table["column_count"]) == (
        37,
        4,
    )
    assert _rows_sha256(page_2_table["rows"]) == (
        "f10cb1ba5dfda7b706537c60a7cd2cccc38d85ac2fc452de1cc0e941b06275a2"
    )
    assert _rows_sha256(page_3_table["rows"]) == (
        "1d7e072d0e7eb1eaa427e294c78358338b3994f1c6a1dc44b069ec6cae7574c7"
    )
    assert "ClO" not in scalar_values
    assert "FERS" not in scalar_values
    assert payload["processing"]["source_text_alignment"]["status"] in {
        "selected",
        "unchanged",
    }
    assert payload["processing"]["running_regions"]["status"] == "projected"


@pytest.mark.integration
def test_real_postal_has_no_detached_complete_fers_line(
    tmp_path: Path,
) -> None:
    payload = _parse("postal-10k")
    target_row = ["FERS", "Federal Employees Retirement System"]
    detached_text = " ".join(target_row)
    collateral_fragments = {
        "CARES Act",
        (
            "Coronavirus Aid, Relief, and Economic Security Act, enacted as "
            "Public Law 116-136"
        ),
        (
            "Coronavirus Aid, Relief, and Economic Security Act , enacted as "
            "Public Law 116-136"
        ),
        "Exchange Act",
        (
            "Securities and Exchange Act of 1934, enacted as Public Law "
            "73-291"
        ),
        (
            "Securities and Exchange Act of 1934 , enacted as Public Law "
            "73-291"
        ),
    }
    tables = [
        item
        for page in payload["pages"]
        for item in page["items"]
        if item.get("type") == "table"
    ]
    matching_rows = [
        (table, row_index)
        for table in tables
        for row_index, row in enumerate(table.get("rows") or [])
        if row == target_row
    ]
    detached_items = [
        item
        for page in payload["pages"]
        for item in page["items"]
        if item.get("type") != "table"
        and isinstance(item.get("value"), str)
        and detached_text in " ".join(item["value"].split())
    ]
    detached_collateral_items = [
        item
        for item in payload["pages"][0]["items"]
        if item.get("type") != "table"
        and isinstance(item.get("value"), str)
        and " ".join(item["value"].split())
        in {" ".join(value.split()) for value in collateral_fragments}
    ]

    validated = ParseResult.model_validate(payload)
    ParseResult.model_validate_json(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    raw_markdown = to_markdown(validated)
    canonical_markdown = payload["canonical_presentation"]["full"]["markdown"]
    dom = _render_public_dom(payload, tmp_path, case="postal-regression")

    table_owned_suppressions = [
        selection
        for selection in payload["processing"]["source_text_alignment"][
            "selections"
        ]
        if selection.get("terminal_reason")
        == "table_owned_complete_source_line_duplicate"
    ]
    failures: list[str] = []
    if len(matching_rows) != 1:
        failures.append(f"authoritative row count={len(matching_rows)}")
    if matching_rows:
        table, row_index = matching_rows[0]
        if table.get("table_evidence", {}).get("status") != "valid":
            failures.append("table evidence is not valid")
        if (
            table.get("table_evidence", {})
            .get("gate", {})
            .get("outcome")
            != "canonical_table"
        ):
            failures.append("table is not the canonical table owner")
        cells = [
            cell
            for cell in table.get("cells") or []
            if cell.get("row") == row_index
        ]
        if [cell.get("text") for cell in cells] != target_row:
            failures.append("row-cell custody does not preserve both values")
        if any(
            not cell.get("source_object_ids") or not cell.get("evidence_ids")
            for cell in cells
        ):
            failures.append("row-cell source/evidence lineage is incomplete")
        target_suppressions = [
            selection
            for selection in table_owned_suppressions
            if (
                selection.get("rejected_ocr_alternative") or {}
            ).get("canonical_owner", {}).get("table_item_id")
            == table.get("id")
            and (
                selection.get("rejected_ocr_alternative") or {}
            ).get("canonical_owner", {}).get("row_index")
            == row_index
            and (
                selection.get("rejected_ocr_alternative") or {}
            ).get("canonical_owner", {}).get("cell_ids")
            == [cell.get("id") for cell in cells]
        ]
        if len(target_suppressions) < 1:
            failures.append(
                "target suppression ledger is absent; count="
                f"{len(target_suppressions)}"
            )
        elif any(
            not suppression["rejected_ocr_alternative"][
                "canonical_owner"
            ].get(field)
            for suppression in target_suppressions
            for field in (
                "source_object_ids",
                "evidence_ids",
                "table_bbox",
                "row_bbox",
                "source_line_bbox",
            )
        ):
            failures.append("target suppression ownership proof is incomplete")
        elif any(
            not isinstance(
                suppression["rejected_ocr_alternative"].get(
                    "ocr_contributor"
                ),
                dict,
            )
            or suppression["rejected_ocr_alternative"][
                "ocr_contributor"
            ].get("source_document_identity")
            != SOURCE_SHA256["postal-10k"]
            for suppression in target_suppressions
        ):
            failures.append("target OCR contributor lineage is incomplete")
    if detached_items:
        identities = [
            {
                "item_id": item.get("id"),
                "bbox": item.get("bbox"),
                "source_line_id": (
                    item.get("source_text_alignment") or {}
                ).get("source_line_id"),
            }
            for item in detached_items
        ]
        failures.append(f"detached public items survived: {identities!r}")
    if detached_collateral_items:
        identities = [
            {
                "item_id": item.get("id"),
                "value": item.get("value"),
                "bbox": item.get("bbox"),
                "source": item.get("source"),
                "ocr_contributor_id": (
                    item.get("ocr_contributor") or {}
                ).get("id"),
            }
            for item in detached_collateral_items
        ]
        failures.append(
            "detached CARES/Exchange public items survived: "
            f"{identities!r}"
        )
    if raw_markdown.encode("utf-8") != canonical_markdown.encode("utf-8"):
        failures.append("raw Markdown differs from canonical full Markdown")
    if raw_markdown.count("<td>FERS</td>") != 1:
        failures.append("Markdown does not contain exactly one first cell")
    if raw_markdown.count(
        "<td>Federal Employees Retirement System</td>"
    ) != 1:
        failures.append("Markdown does not contain exactly one second cell")
    if f"\n\n{detached_text}\n\n" in f"\n\n{raw_markdown}\n\n":
        failures.append("Markdown contains the detached paragraph")
    detached_markdown_fragments = sorted(
        fragment
        for fragment in collateral_fragments
        if f"\n\n{fragment}\n\n" in f"\n\n{raw_markdown}\n\n"
    )
    if detached_markdown_fragments:
        failures.append(
            "Markdown contains detached CARES/Exchange paragraphs: "
            f"{detached_markdown_fragments!r}"
        )
    if dom.count(">FERS</td>") != 1:
        failures.append("rendered DOM does not contain exactly one first cell")
    if dom.count(">Federal Employees Retirement System</td>") != 1:
        failures.append("rendered DOM does not contain exactly one second cell")
    if (
        'class="parsed-paragraph"' in dom
        and f">{detached_text}</p>" in dom
    ):
        failures.append("rendered DOM contains the detached paragraph")
    detached_dom_fragments = sorted(
        fragment
        for fragment in collateral_fragments
        if f">{fragment}</p>" in dom
    )
    if detached_dom_fragments:
        failures.append(
            "rendered DOM contains detached CARES/Exchange paragraphs: "
            f"{detached_dom_fragments!r}"
        )

    assert not failures, "FFD-011 public-surface failures:\n- " + "\n- ".join(
        failures
    )


@pytest.mark.integration
def test_real_finance_unresolved_tables_keep_attributable_ocr_fail_closed(
) -> None:
    payload = _parse_finance_p04_fail_closed()
    predecessor = _frozen_finance_predecessor()
    source_identity = SOURCE_SHA256["finance-10k"]

    assert [page["page_index"] for page in payload["pages"]] == [1, 2, 3]
    assert [page["page_index"] for page in predecessor["pages"]] == [1, 2, 3]
    current_tables: dict[int, dict[str, Any]] = {}
    for current_page, predecessor_page in zip(
        payload["pages"],
        predecessor["pages"],
        strict=True,
    ):
        page_index = current_page["page_index"]
        current_positions = [
            index
            for index, item in enumerate(current_page["items"])
            if item.get("type") == "table"
        ]
        predecessor_positions = [
            index
            for index, item in enumerate(predecessor_page["items"])
            if item.get("type") == "table"
        ]
        assert len(current_positions) == len(predecessor_positions) == 1
        assert current_positions == predecessor_positions

        current_table = current_page["items"][current_positions[0]]
        predecessor_table = predecessor_page["items"][predecessor_positions[0]]
        sidecar = current_table.get("table_evidence")
        assert isinstance(sidecar, dict)
        assert sidecar.get("status") == "unresolved"
        assert sidecar.get("status") != "valid"
        assert sidecar.get("gate") is None
        assert table_semantics.validate_table_semantics(
            current_table,
            source_identity,
        )

        public_projection = deepcopy(current_table)
        public_projection.pop("table_evidence")
        assert public_projection == predecessor_table
        current_tables[page_index] = current_table

    # Freeze one attributable survivor, rather than the incidental total of
    # page-image OCR lines.  The unresolved table has no authority to delete
    # this overlapping source candidate.
    survivors = [
        (page["page_index"], item)
        for page in payload["pages"]
        for item in page["items"]
        if page["page_index"] == 1
        and item.get("type") == "text"
        and item.get("value") == "Cost of sales:"
    ]
    assert len(survivors) == 1
    page_index, survivor = survivors[0]
    assert page_index == 1
    assert survivor.get("source") == "ocr"
    assert survivor.get("label") == "ocr_text"
    assert survivor.get("parse_concerns") == [
        "layout_omission_recovered_by_ocr"
    ]
    assert survivor.get("raw_ocr_text") == "Cost of sales:"
    assert survivor.get("confidence") == pytest.approx(0.9658)
    assert survivor.get("bbox") == {
        "x": 52.4,
        "y": 208.0,
        "width": 53.4,
        "height": 6.8,
        "unit": "pt",
        "w": 53.4,
        "h": 6.8,
    }
    survivor_area = float(survivor["bbox"]["width"]) * float(
        survivor["bbox"]["height"]
    )
    assert _bbox_intersection_area(
        survivor["bbox"],
        current_tables[page_index]["bbox"],
    ) == pytest.approx(survivor_area)

    contributor = survivor.get("ocr_contributor")
    assert isinstance(contributor, dict)
    assert set(contributor) == {
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
    }
    assert contributor["schema_version"] == "1.0"
    assert contributor["policy_id"] == "p02-supplemental-ocr-contributor-v1"
    assert contributor["source_document_identity"] == source_identity
    assert contributor["page_index"] == page_index
    assert contributor["region_origin"] == "pdf_page_render"
    assert contributor["region_role"] == "page_source"
    assert contributor["coordinate_unit"] == "pt"
    assert contributor["bbox"] == {
        key: survivor["bbox"][key]
        for key in ("x", "y", "width", "height", "unit")
    }
    assert contributor["raw_text"] == survivor["raw_ocr_text"]
    assert contributor["confidence"] == survivor["confidence"]
    closed_contributor = {
        key: value for key, value in contributor.items() if key != "id"
    }
    contributor_digest = hashlib.sha256(
        json.dumps(
            closed_contributor,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert contributor["id"] == f"ocr-contributor-{contributor_digest}"

    public_json = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    ParseResult.model_validate(payload)
    ParseResult.model_validate_json(public_json)
    assert TABLE_OWNED_SUPPLEMENTAL_REASON not in public_json
    assert payload["processing"].get("source_text_alignment") is None
    assert all(
        item.get("source_alignment_suppressed") is not True
        for page in payload["pages"]
        for item in page["items"]
    )


@pytest.mark.integration
def test_real_ny_tables_remain_exact_and_uncertain_ocr_fails_closed() -> None:
    payload = _parse("ny-timetable")
    uncertain_ocr = [
        (page["page_index"], item)
        for page in payload["pages"]
        for item in page["items"]
        if isinstance(item.get("value"), str)
        and item.get("value") in {"ew", "741"}
    ]
    tables = [
        item
        for page in payload["pages"]
        for item in page["items"]
        if item.get("type") == "table"
    ]

    assert len(tables) == 3
    assert all(len(table["rows"][0]) == 13 for table in tables)
    assert all(table["rows"][0][0] == "Weekdays to The Bronx" for table in tables)
    assert all(table["rows"][1][0] == "Notes" for table in tables)
    assert [
        hashlib.sha256(
            json.dumps(
                table["rows"],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        for table in tables
    ] == [
        "08a23117540bc200d4ca8c5bd80340db8aeef186843592f469c84a589a44bb3a",
        "095590b16e3e96079d76d151e4166a5294e407d26d32ee320ec17051ed566fcd",
        "1eb9f2cff9fe121930c19acbfb740ec66a9d2f4993150c157a3ae53aef97cace",
    ]
    assert [
        (page_index, item["value"])
        for page_index, item in uncertain_ocr
    ] == [(1, "ew"), (1, "741"), (2, "ew")]
    assert all(
        item.get("source") == "ocr"
        and item.get("label") == "ocr_text"
        and item.get("raw_ocr_text") == item.get("value")
        and "layout_omission_recovered_by_ocr"
        in (item.get("parse_concerns") or [])
        for _page_index, item in uncertain_ocr
    )
    selected_owner_ids = {
        selection.get("owner_id")
        for selection in payload["processing"]["source_text_alignment"][
            "selections"
        ]
    }
    assert selected_owner_ids.isdisjoint(
        {item["id"] for _page_index, item in uncertain_ocr}
    )
