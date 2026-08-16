"""P04-US01 must remain a terminal overlay on the exact P03 projection.

The fixture deliberately combines a literal P04 table marker, an opaque
Docling group that owns that table, and the reviewed P03-US08 synthetic with
both top- and bottom-navigation regions.  The table marker is replaced by its
sealed predecessor before any Phase 03 consumer runs.  Raw relationships are
*not* detached from that predecessor path; only the P04 table dictionary is
transacted.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import time
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from app.config import Settings
from app.models import (
    CanonicalSourceCustody,
    ContentItem,
    ParseResult,
    _TrustedTableValidationContext,
    _canonical_presentation_sha256,
    _context_free_ir_delta_is_closed,
    _context_free_ir_identity_projection,
    _context_free_inert_raw_group_owner_is_closed,
    _context_free_visual_ledger_mode_payload,
    _context_free_visual_ocr_predecessor_is_closed,
    _context_free_visual_source_sensitive_children,
    _layout_note_basis_is_closed,
    _layout_predecessor_item_payload,
    _trusted_table_baseline_from_context,
    _trusted_table_validation_context,
)
from app.services import opaque_group_custody as custody
from app.services import pipeline
from app.services import presentation
from app.services import running_regions
from app.services import source_text_alignment
from app.services import table_semantics
from app.services.input_documents import InputKind, LoadedDocument
from app.services.ir import DocumentIR, build_document_ir
from app.services.presentation import build_canonical_presentation
from tests.contract.test_p03_us08_running_region_contract import (
    _line_predecessor_inputs,
)
from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
    _raw_cell,
    _raw_table,
    _spanned_table,
)
from tests.contract.test_p04_us01_opaque_group_custody import (
    _base_raw_graph,
    _detach_restore_project,
    _fixture as _opaque_fixture,
    _reseal_sidecar,
)
from tests.fixtures.phase_03.running_regions.contract import strict_json_bytes


TABLE_ID = "p1-p04-boundary-table"
RUNNING_TIMING_FIELDS = ("extraction_ms", "projection_ms", "total_ms")
_MISSING = object()


@dataclass(frozen=True, slots=True)
class _BoundaryFixture:
    marked: dict[str, Any]
    predecessor: dict[str, Any]
    raw_graph: dict[str, Any]
    native_texts: tuple[str, ...]
    source_pdf_bytes: bytes


def _projected_note_item(
    *,
    basis: str,
    source: str = "native",
    value: str = "See https://example.test/source",
    links: Any = _MISSING,
) -> ContentItem:
    payload: dict[str, Any] = {
        "id": "layout-note-00000000000000000001",
        "type": "footnote",
        "reading_order": 1,
        "value": value,
        "md": value,
        "source": source,
        "footnote_of": "p1-owner",
        "relationship_id": "layout-rel-00000000000000000001",
        "relationship_type": "footnote_of",
        "relationship_basis": basis,
    }
    if links is not _MISSING:
        payload["links"] = links
    return ContentItem.model_validate(payload)


def _round_public_bboxes(payload: Mapping[str, Any]) -> None:
    """Match the frozen P03 public three-decimal bbox contract."""

    for page in payload.get("pages") or []:
        for item in page.get("items") or []:
            bbox = item.get("bbox")
            if type(bbox) is not dict:
                continue
            for key in ("x", "y", "width", "height"):
                bbox[key] = round(float(bbox[key]), 3)


def _boundary_fixture(
    *,
    raw_table_override: dict[str, Any] | None = None,
) -> _BoundaryFixture:
    public, _ir, source = _line_predecessor_inputs(
        "synthetic:p03-us08:single-navigation-v1"
    )
    public = deepcopy(public)
    _round_public_bboxes(public)
    public.pop("canonical_presentation", None)

    # Build the marker against this fixture's exact source identity.  Reusing
    # the generic runtime helper would seal it to that helper's `a…a` source
    # control and correctly force a terminal rollback here.
    raw_table = deepcopy(
        _spanned_table()
        if raw_table_override is None
        else raw_table_override
    )
    raw_table["prov"] = [
        {
            "page_no": 1,
            "bbox": {
                "l": 0.0,
                "t": 10.0,
                "r": 300.0,
                "b": 120.0,
                "coord_origin": "TOPLEFT",
            },
        }
    ]
    raw_table["parent"] = {"$ref": "#/groups/0"}
    native_table_text = " ".join(
        str(cell.get("text") or "")
        for cell in raw_table["data"]["table_cells"]
    )
    _page_index, marker = pipeline._docling_table_item(
        deepcopy(raw_table),
        {1: float(public["pages"][0]["page_height"])},
        {},
        [native_table_text],
        public["document"]["sha256"],
        table_span_fidelity_enabled=True,
    )
    marker["id"] = TABLE_ID
    # Place the body table before the bottom navigation so the exact P03
    # layout projection keeps a stable table slot while still projecting the
    # footer after it.
    marker["reading_order"] = 2
    snapshot = marker["_p04_predecessor_snapshot"]
    snapshot["id"] = TABLE_ID
    snapshot["reading_order"] = marker["reading_order"]
    marker_page = {
        **{
            key: deepcopy(public["pages"][0][key])
            for key in (
                "page_index",
                "page_number",
                "page_label",
                "page_width",
                "page_height",
                "unit",
                "success",
                "warnings",
            )
        },
        "items": [marker],
    }
    table_semantics.seal_table_pages(
        [marker_page],
        public["document"]["sha256"],
        [native_table_text],
        table_span_fidelity_enabled=True,
    )
    marker = marker_page["items"][0]
    snapshot = marker["_p04_predecessor_snapshot"]
    public["pages"][0]["items"][2]["reading_order"] = 3
    public["pages"][0]["items"].insert(2, marker)

    predecessor = deepcopy(public)
    predecessor["pages"][0]["items"][2] = deepcopy(snapshot)

    # The group relationship is deliberately table-targeted.  P03 must see it
    # unchanged, while terminal no-raw canonical reconstruction may treat only
    # the table block as the P04/custody target.
    raw_graph = {
        "tables": [raw_table],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [{"$ref": "#/tables/0"}],
            }
        ],
    }
    native_texts = (
        "CONTENTS\nBody paragraph unique to this physical page.\nNEXT",
    )
    return _BoundaryFixture(
        marked=public,
        predecessor=predecessor,
        raw_graph=raw_graph,
        native_texts=native_texts,
        source_pdf_bytes=source,
    )


def _p03_settings(*, table_enabled: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_relationship_order_enabled=True,
        layout_running_regions_enabled=True,
        table_span_fidelity_enabled=table_enabled,
    )


def _terminal_settings() -> Settings:
    return Settings(
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
        layout_relationship_order_enabled=True,
        layout_running_regions_enabled=True,
        table_span_fidelity_enabled=True,
    )


def _projected_predecessor(
    fixture: _BoundaryFixture | None = None,
) -> tuple[
    _BoundaryFixture,
    tuple[Any, ...],
    dict[str, Any],
    DocumentIR,
]:
    fixture = fixture or _boundary_fixture()
    pages = deepcopy(fixture.marked["pages"])
    transaction = _detach(pages)
    predecessor = deepcopy(fixture.predecessor)
    predecessor["pages"] = pages
    sink: dict[str, Any] = {}
    projected = pipeline._apply_shared_ir_compatibility_projection(
        predecessor,
        _p03_settings(table_enabled=True),
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        internal_ir_sink=sink,
    )
    assert isinstance(sink.get("ir"), DocumentIR)
    return fixture, transaction, projected, sink["ir"]


def _terminal_custody_ir_inputs() -> tuple[
    DocumentIR,
    DocumentIR,
    tuple[Any, ...],
]:
    _fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    deadline = time.perf_counter() + 5.0
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
    candidate["pages"] = table_semantics.rebind_table_overlays_after_phase03(
        baseline.get("pages"),
        transaction,
        deadline=deadline,
        transaction_is_owned=True,
    )
    table_semantics.finalize_table_pages(
        candidate["pages"],
        str((candidate.get("document") or {}).get("sha256") or ""),
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=deadline,
        table_span_fidelity_page_deadlines=None,
        table_span_fidelity_state={},
    )
    authoritative_ir = build_document_ir(candidate)
    return baseline_ir, authoritative_ir, transaction


def _without_running_timing(payload: Mapping[str, Any]) -> dict[str, Any]:
    stable = deepcopy(dict(payload))
    summary = stable.get("processing", {}).get("running_regions")
    if type(summary) is dict:
        for field in RUNNING_TIMING_FIELDS:
            summary.pop(field, None)
    return stable


def _without_table_items(payload: Mapping[str, Any]) -> dict[str, Any]:
    stable = deepcopy(dict(payload))
    for page in stable.get("pages") or []:
        page["items"] = [
            item for item in page.get("items") or [] if item.get("id") != TABLE_ID
        ]
    return stable


def _non_table_public_closure(payload: Mapping[str, Any]) -> dict[str, Any]:
    stable = _without_table_items(payload)
    stable.pop("canonical_presentation", None)
    stable.pop("canonical_source_custody", None)
    return stable


def _non_table_canonical_blocks(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        deepcopy(block)
        for page in payload["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block.get("primary_element_type") != "table"
    ]


def _render_canonical_view(blocks: list[Mapping[str, Any]]) -> dict[str, Any]:
    included = [
        block for block in blocks if block.get("omission_reason") is None
    ]

    def render(field: str) -> str:
        values = [
            str(block.get(field) or "").strip()
            for block in included
            if str(block.get(field) or "").strip()
        ]
        return "\n\n".join(values).rstrip() + "\n" if values else ""

    return {
        "block_ids": [str(block["id"]) for block in included],
        "markdown": render("markdown"),
        "text": render("text"),
    }


def _refresh_canonical_views(payload: dict[str, Any]) -> None:
    canonical = payload["canonical_presentation"]
    all_blocks: list[Mapping[str, Any]] = []
    for page in canonical["pages"]:
        blocks = page["blocks"]
        all_blocks.extend(blocks)
        page["full"] = _render_canonical_view(blocks)
        for scope in ("body", "header", "footer"):
            page[scope] = _render_canonical_view(
                [block for block in blocks if block["scope"] == scope]
            )
    canonical["full"] = _render_canonical_view(all_blocks)
    for scope in ("body", "header", "footer"):
        canonical[scope] = _render_canonical_view(
            [block for block in all_blocks if block["scope"] == scope]
        )


def _reseal_canonical_presentation(payload: dict[str, Any]) -> None:
    payload["canonical_source_custody"][
        "canonical_presentation_sha256"
    ] = _canonical_presentation_sha256(payload["canonical_presentation"])


def _trusted_terminal_candidate() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    now = time.perf_counter()
    state: dict[str, Any] = {}
    candidate = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )
    assert custody.has_literal_table_marker(candidate)
    assert state.get("custody_rejected") is not True
    return deepcopy(baseline), deepcopy(candidate)


def _with_inert_raw_group_remnant(
    candidate: dict[str, Any],
    *,
    group_ordinal: int = 1,
    block_offset: int = 1,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    augmented = deepcopy(candidate)
    block = augmented["canonical_presentation"]["pages"][0]["blocks"][
        block_offset
    ]
    document_id = custody.stable_id(
        "doc",
        augmented["document"]["sha256"],
    )
    group_id = custody.stable_id(
        "el",
        document_id,
        "raw_ref",
        f"#/groups/{group_ordinal}",
    )
    relationship_id = custody.stable_id(
        "rel",
        "contains",
        group_id,
        block["primary_element_id"],
        "children",
    )
    block["relationship_ids"].append(relationship_id)
    block["relationship_ids"].sort()
    block["excluded_contributions"].append(
        {
            "element_id": group_id,
            "reason": "evidence_only_relationship",
            "relationship_ids": [relationship_id],
        }
    )
    block["excluded_contributions"].sort(
        key=lambda value: (value["element_id"], value["reason"])
    )
    _refresh_canonical_views(augmented)
    _reseal_canonical_presentation(augmented)
    return augmented, block, group_id, relationship_id


def _trusted_nonvalid_candidate() -> tuple[dict[str, Any], dict[str, Any]]:
    from tests.contract.test_p04_us01_table_api_schema import (
        _bound_payload,
        _hash,
        _production_diagnostic,
    )

    candidate = _bound_payload(
        _production_diagnostic(),
        source_sha256=_hash("a"),
    )
    _reseal_canonical_presentation(candidate)
    target = candidate["pages"][0]["items"][0]
    assert target["table_evidence"]["status"] == "structural_failure"

    baseline = deepcopy(candidate)
    baseline["pages"][0]["items"][0].pop("table_evidence")
    baseline.pop("canonical_source_custody")
    baseline_result = ParseResult.model_validate(deepcopy(baseline))
    ParseResult.model_validate(
        deepcopy(candidate),
        context=_trusted_table_validation_context(baseline_result),
    )
    return baseline, candidate


def _target_caption_overlay_blocks() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    owner = "el-00000000000000000001"
    caption = "el-00000000000000000002"
    old_cell = "el-00000000000000000003"
    new_cell = "el-00000000000000000004"
    old_cell_rel = "rel-00000000000000000001"
    new_cell_rel = "rel-00000000000000000002"
    caption_rel = custody.stable_id(
        "rel",
        "caption_of",
        caption,
        owner,
        "children",
    )
    containment_rel = custody.stable_id(
        "rel",
        "contains",
        owner,
        caption,
        "parent",
    )
    identity = {
        "id": "pb-00000000000000000001",
        "page_id": "page-00000000000000000001",
        "primary_element_id": owner,
        "primary_element_type": "table",
        "scope": "body",
    }
    predecessor = {
        **identity,
        "markdown": "<table><tr><td>old</td></tr></table>",
        "text": "old",
        "contributing_element_ids": [owner, old_cell],
        "relationship_ids": [old_cell_rel],
        "excluded_contributions": [],
    }
    baseline = {
        **deepcopy(predecessor),
        "markdown": "Source caption\n\n" + predecessor["markdown"],
        "text": "Source caption\n\n" + predecessor["text"],
        "contributing_element_ids": [owner, caption, old_cell],
        "relationship_ids": sorted(
            [old_cell_rel, caption_rel, containment_rel]
        ),
        "excluded_contributions": [
            {
                "element_id": caption,
                "reason": "evidence_only_relationship",
                "relationship_ids": [containment_rel],
            }
        ],
    }
    candidate = {
        **identity,
        "markdown": '<table><tr><th scope="col">new</th></tr></table>',
        "text": "new",
        "contributing_element_ids": [owner, new_cell],
        "relationship_ids": [new_cell_rel],
        "excluded_contributions": [],
    }
    public_item = {
        "id": "public-table",
        "type": "table",
        "caption_ids": [caption],
        "caption_of": [caption],
        "relationships": [
            {
                "id": "layout-rel-00000000000000000001",
                "source_id": caption,
                "target_id": "public-table",
                "type": "caption_of",
            }
        ],
    }
    return baseline, predecessor, candidate, public_item


def _without_source_alignment_outcome(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    stable = deepcopy(dict(payload))
    stable.get("processing", {}).pop("source_text_alignment", None)
    warnings = stable.get("warnings")
    if (
        type(warnings) is list
        and warnings
        and str(warnings[-1]).startswith("Source text alignment failed closed:")
    ):
        warnings.pop()
    return stable


def _detach(
    pages: list[dict[str, Any]],
) -> tuple[Any, ...]:
    return table_semantics.detach_table_overlays_for_phase03(
        pages,
        deadline=time.perf_counter() + 2.0,
    )


def _rebind(
    pages: list[dict[str, Any]],
    transaction: tuple[Any, ...],
) -> list[dict[str, Any]]:
    return table_semantics.rebind_table_overlays_after_phase03(
        pages,
        transaction,
        deadline=time.perf_counter() + 2.0,
    )


def test_table_transaction_replaces_only_literal_marker_with_exact_predecessor() -> None:
    fixture = _boundary_fixture()
    pages = deepcopy(fixture.marked["pages"])
    before = deepcopy(pages)

    transaction = _detach(pages)

    assert type(transaction) is tuple
    assert strict_json_bytes(fixture.marked["pages"]) == strict_json_bytes(before)
    assert strict_json_bytes(pages) == strict_json_bytes(
        fixture.predecessor["pages"]
    )
    assert not custody.has_literal_table_marker({"pages": pages})
    assert all(
        "_p04_predecessor_snapshot" not in item
        for page in pages
        for item in page["items"]
    )


def test_enabled_p03_path_is_exact_flag_off_path_and_never_detaches_raw_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _boundary_fixture()
    pages = deepcopy(fixture.marked["pages"])
    _detach(pages)
    predecessor = deepcopy(fixture.predecessor)
    predecessor["pages"] = pages

    monkeypatch.setattr(
        custody,
        "detach_opaque_group_edges",
        lambda *_args, **_kwargs: pytest.fail(
            "the predecessor P03 path detached raw group relationships"
        ),
    )
    common = {
        "source_pdf_bytes": fixture.source_pdf_bytes,
        "input_kind": InputKind.PDF,
        "raw_graph": fixture.raw_graph,
        "native_texts": fixture.native_texts,
    }
    explicit_off = pipeline._apply_shared_ir_compatibility_projection(
        deepcopy(predecessor),
        _p03_settings(table_enabled=False),
        **common,
    )
    enabled_predecessor = pipeline._apply_shared_ir_compatibility_projection(
        deepcopy(predecessor),
        _p03_settings(table_enabled=True),
        **common,
    )

    # P03 explicitly excludes its measured timings from replay identity.  No
    # other field is normalized or waived here.
    assert strict_json_bytes(_without_running_timing(enabled_predecessor)) == (
        strict_json_bytes(_without_running_timing(explicit_off))
    )
    assert running_regions.running_region_replay_identity(
        enabled_predecessor
    ) == running_regions.running_region_replay_identity(explicit_off)
    assert enabled_predecessor["pages"][0]["page_identity"] == (
        explicit_off["pages"][0]["page_identity"]
    )
    assert enabled_predecessor["warnings"] == explicit_off["warnings"]
    assert [
        (item["type"], item.get("running_region", {}).get("role"))
        for item in enabled_predecessor["pages"][0]["items"]
        if item.get("layout_running_region_projected") is True
    ] == [("header", "navigation_top"), ("footer", "navigation_bottom")]


def test_terminal_non_target_overlay_classifier_is_closed_to_public_p03() -> None:
    expected = frozenset(
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

    assert pipeline._P03_MANUAL_CANONICAL_OVERLAY_KEYS == expected
    assert expected.isdisjoint(
        {
            "_p04_predecessor_snapshot",
            "canonical_source_custody",
            "children",
            "detached_custody",
            "normalization_origin",
            "parent",
            "raw_graph",
            "raw_ref",
            "relationships",
            "self_ref",
            "table_evidence",
        }
    )


@pytest.mark.parametrize(
    "item",
    (
        _projected_note_item(basis="graph_and_geometry"),
        _projected_note_item(
            basis="graph_and_geometry",
            links=[
                {
                    "kind": "hyperlink",
                    "target": "https://example.test/source",
                }
            ],
        ),
        _projected_note_item(basis="geometry_and_source_evidence"),
        _projected_note_item(basis="ocr_and_geometry", source="ocr"),
        _projected_note_item(
            basis="annotation_and_geometry",
            links=[
                {
                    "kind": "hyperlink",
                    "target": "https://example.test/source",
                }
            ],
        ),
        _projected_note_item(
            basis="source_link_and_geometry",
            links=[
                {
                    "kind": "source_link",
                    "target": "https://example.test/source",
                }
            ],
        ),
    ),
    ids=(
        "graph-no-link",
        "graph-safe-visible-link",
        "source-evidence-no-link",
        "ocr-source-no-link",
        "annotation-safe-visible-link",
        "source-link-safe-visible-link",
    ),
)
def test_p03_source_note_basis_accepts_only_closed_positive_proof(
    item: ContentItem,
) -> None:
    assert _layout_note_basis_is_closed(item) is True


@pytest.mark.parametrize(
    "item",
    (
        _projected_note_item(basis="unknown_and_geometry"),
        _projected_note_item(
            basis="geometry_and_source_evidence",
            links=[],
        ),
        _projected_note_item(
            basis="ocr_and_geometry",
            source="native",
        ),
        _projected_note_item(basis="annotation_and_geometry"),
        _projected_note_item(
            basis="annotation_and_geometry",
            links=[],
        ),
        _projected_note_item(
            basis="annotation_and_geometry",
            links=[
                {
                    "kind": "hyperlink",
                    "target": "https://elsewhere.test/source",
                }
            ],
        ),
        _projected_note_item(
            basis="source_link_and_geometry",
            links=[
                {
                    "kind": "source_link",
                    "target": "https://user@example.test/source",
                }
            ],
            value="See https://user@example.test/source",
        ),
        _projected_note_item(
            basis="graph_and_geometry",
            links=[
                {
                    "kind": "unexpected",
                    "target": "https://example.test/source",
                }
            ],
        ),
        _projected_note_item(
            basis="graph_and_geometry",
            links=[
                {
                    "kind": "hyperlink",
                    "target": "https://example.test/source",
                    "authority": True,
                }
            ],
        ),
        _projected_note_item(
            basis="graph_and_geometry",
            source="derived",
        ),
    ),
    ids=(
        "unknown-basis",
        "nonlink-basis-gained-links",
        "ocr-basis-wrong-source",
        "annotation-link-absent",
        "annotation-link-empty",
        "link-not-visible",
        "unsafe-authority-url",
        "unknown-link-kind",
        "link-object-gained-field",
        "altered-derived-source",
    ),
)
def test_p03_source_note_basis_rejects_malformed_or_mismatched_proof(
    item: ContentItem,
) -> None:
    assert _layout_note_basis_is_closed(item) is False


def _visual_projection_item(*, raw_ocr_text: str, ocr_text: str) -> ContentItem:
    return ContentItem.model_validate(
        {
            "id": "p1-visual",
            "type": "image",
            "reading_order": 0,
            "value": "",
            "md": "[Image detected; no reliable text extracted.]",
            "source": "derived",
            "bbox": {
                "x": 40.0,
                "y": 40.0,
                "width": 120.0,
                "height": 80.0,
                "unit": "pt",
            },
            "content_type": "image",
            "include_ocr_in_primary": False,
            "raw_ocr_text": raw_ocr_text,
            "ocr_text": ocr_text,
            "detected_text": bool(raw_ocr_text),
            "items": (
                [
                    {"source": "ocr", "text": "noise", "accepted": False},
                    {"source": "ocr", "text": "kept", "accepted": True},
                ]
                if raw_ocr_text
                else []
            ),
            "annotations": [{"kind": "classification", "label": "logo"}],
            "layout_visual_relationships_projected": True,
            "contains_ids": ["el-contained"],
            "contained_items": [
                {
                    "id": "el-contained",
                    "type": "visual_text",
                    "value": "OPENACCESS",
                    "source": "native",
                    "presentation_role": "subordinate",
                    "contained_by": "p1-visual",
                    "relationship_id": "layout-rel-contained",
                    "relationship_type": "contains",
                    "relationship_basis": "graph_and_geometry",
                }
            ],
        }
    )


def test_empty_ocr_visual_ledger_cannot_infer_predecessor_owner_source() -> None:
    item = _visual_projection_item(raw_ocr_text="", ocr_text="")

    assert _layout_predecessor_item_payload(item)["source"] == "derived"


def test_exact_ocr_ledger_cannot_mutate_primary_predecessor_source() -> None:
    item = _visual_projection_item(
        raw_ocr_text="noise\nkept",
        ocr_text="kept",
    )
    post_layout = item.model_dump(mode="json", exclude_unset=True)
    predecessor = _layout_predecessor_item_payload(item)
    explicit_predecessor = deepcopy(post_layout)
    explicit_predecessor["source"] = "ocr"

    def annotation_identity(payload: Mapping[str, Any]) -> tuple[str, str]:
        ir = build_document_ir(
            {
                "document": {"sha256": "a" * 64},
                "pages": [
                    {
                        "page_index": 1,
                        "page_number": 1,
                        "page_label": "1",
                        "page_width": 612.0,
                        "page_height": 792.0,
                        "unit": "pt",
                        "success": True,
                        "items": [deepcopy(dict(payload))],
                        "warnings": [],
                    }
                ],
            }
        )
        relationship = next(
            member
            for member in ir.relationships
            if member.type.value == "annotation_of"
        )
        return relationship.source_id, relationship.id

    assert predecessor["source"] == "derived"
    assert predecessor == post_layout
    assert annotation_identity(predecessor) != annotation_identity(
        explicit_predecessor
    )


@pytest.mark.parametrize("include_ocr", (False, True), ids=("off", "on"))
def test_context_free_visual_source_proof_accepts_both_exact_bool_modes(
    include_ocr: bool,
) -> None:
    payload = _visual_projection_item(
        raw_ocr_text="noise\nkept",
        ocr_text="kept",
    ).model_dump(mode="json", exclude_unset=True)
    payload["include_ocr_in_primary"] = include_ocr
    item = ContentItem.model_validate(payload)

    assert _context_free_visual_ocr_predecessor_is_closed(item)


def test_context_free_visual_deduplicated_ledger_is_exactly_classified() -> None:
    payload = _visual_projection_item(
        raw_ocr_text="noise\nkept",
        ocr_text="kept",
    ).model_dump(mode="json", exclude_unset=True)
    payload["items"] = [
        {"source": "ocr", "text": "noise", "accepted": False},
        {"source": "ocr", "text": "kept", "accepted": True},
        {"source": "ocr", "text": "kept", "accepted": True},
    ]
    item = ContentItem.model_validate(payload)

    assert (
        _context_free_visual_ledger_mode_payload(item.model_extra or {})
        == "nonempty_deduplicated"
    )
    assert _context_free_visual_ocr_predecessor_is_closed(item)


@pytest.mark.parametrize(
    "mutation",
    (
        "non_bool_ocr_mode",
        "source",
        "value",
        "markdown",
        "raw_ledger_order",
        "accepted_ledger_content",
        "semantic_child_owner",
        "visual_type",
    ),
)
def test_context_free_visual_source_proof_rejects_non_source_drift(
    mutation: str,
) -> None:
    payload = _visual_projection_item(
        raw_ocr_text="noise\nkept",
        ocr_text="kept",
    ).model_dump(mode="json", exclude_unset=True)
    if mutation == "non_bool_ocr_mode":
        payload["include_ocr_in_primary"] = 1
    elif mutation == "source":
        payload["source"] = "ocr"
    elif mutation == "value":
        payload["value"] = "forged"
    elif mutation == "markdown":
        payload["md"] = "forged"
    elif mutation == "raw_ledger_order":
        payload["raw_ocr_text"] = "kept\nnoise"
    elif mutation == "accepted_ledger_content":
        payload["ocr_text"] = "noise"
    elif mutation == "semantic_child_owner":
        payload["contained_items"][0]["contained_by"] = "p1-other"
    elif mutation == "visual_type":
        payload["type"] = "text"
    else:  # pragma: no cover - the parameter list is closed above.
        raise AssertionError(mutation)
    item = ContentItem.model_validate(payload)

    assert _context_free_visual_ocr_predecessor_is_closed(item) is False


@pytest.mark.parametrize("transport", ("direct", "json"))
def test_context_free_inert_raw_group_remnant_round_trips_exactly(
    transport: str,
) -> None:
    _baseline, candidate = _trusted_terminal_candidate()
    candidate, _block, group_id, relationship_id = (
        _with_inert_raw_group_remnant(candidate)
    )

    validated = (
        ParseResult.model_validate(deepcopy(candidate))
        if transport == "direct"
        else ParseResult.model_validate_json(strict_json_bytes(candidate))
    )
    round_tripped = validated.model_dump(mode="json", exclude_unset=True)

    assert strict_json_bytes(round_tripped) == strict_json_bytes(candidate)
    assert group_id in json.dumps(round_tripped["canonical_presentation"])
    assert relationship_id in json.dumps(
        round_tripped["canonical_presentation"]
    )


def _inert_form_heading_owner() -> tuple[ContentItem, str]:
    primary_id = "el-11111111111111111111"
    public_id = "p1-inert-form-anchor"
    return ContentItem.model_validate(
        {
            "id": public_id,
            "type": "heading",
            "reading_order": 1,
            "value": "DATE (MM/DD/YYYY)",
            "md": "DATE (MM/DD/YYYY)",
            "source": "native",
            "layout_forms_projected": True,
            "form_group": {
                "canonical_mode": "inert",
                "anchor_public_item_id": public_id,
                "anchor_element_id": primary_id,
                "contributor_public_item_ids": [public_id],
                "contributor_element_ids": [primary_id],
            },
        }
    ), primary_id


def test_context_free_inert_form_heading_owner_is_narrowly_admitted() -> None:
    item, primary_id = _inert_form_heading_owner()

    assert _context_free_inert_raw_group_owner_is_closed(item, primary_id)


@pytest.mark.parametrize(
    "mutation",
    (
        "non_heading",
        "projection_absent",
        "replace_mode",
        "public_anchor_mismatch",
        "element_anchor_mismatch",
        "public_contributor_mismatch",
        "element_contributor_mismatch",
    ),
)
def test_context_free_inert_form_heading_owner_rejects_broader_authority(
    mutation: str,
) -> None:
    item, primary_id = _inert_form_heading_owner()
    payload = item.model_dump(mode="json", exclude_unset=True)
    form_group = payload["form_group"]
    if mutation == "non_heading":
        payload["type"] = "code"
    elif mutation == "projection_absent":
        payload.pop("layout_forms_projected")
    elif mutation == "replace_mode":
        form_group["canonical_mode"] = "replace"
    elif mutation == "public_anchor_mismatch":
        form_group["anchor_public_item_id"] = "p1-other"
    elif mutation == "element_anchor_mismatch":
        form_group["anchor_element_id"] = "el-22222222222222222222"
    elif mutation == "public_contributor_mismatch":
        form_group["contributor_public_item_ids"] = ["p1-other"]
    elif mutation == "element_contributor_mismatch":
        form_group["contributor_element_ids"] = [
            "el-22222222222222222222"
        ]
    else:  # pragma: no cover - the parameter list is closed above.
        raise AssertionError(mutation)

    assert not _context_free_inert_raw_group_owner_is_closed(
        ContentItem.model_validate(payload),
        primary_id,
    )


@pytest.mark.parametrize("transport", ("direct", "json"))
@pytest.mark.parametrize(
    "mutation",
    (
        "non_group_raw_ref",
        "outside_bounded_group_ordinal",
        "custody_endpoint",
        "canonical_contributor_endpoint",
        "marked_table_owner",
        "swapped_direction",
        "wrong_field",
        "alternative_relationship",
        "reference_relationship",
        "caption_relationship",
        "multiple_remnants",
        "cross_block_reuse",
        "reason",
        "content",
        "contributor",
    ),
)
def test_context_free_inert_raw_group_remnant_rejects_authority_or_drift(
    transport: str,
    mutation: str,
) -> None:
    _baseline, original = _trusted_terminal_candidate()
    candidate, block, group_id, relationship_id = (
        _with_inert_raw_group_remnant(original)
    )
    document_id = custody.stable_id(
        "doc",
        candidate["document"]["sha256"],
    )

    def replace_remnant(
        endpoint_id: str,
        replacement_relationship_id: str,
    ) -> None:
        block["relationship_ids"].remove(relationship_id)
        block["relationship_ids"].append(replacement_relationship_id)
        block["relationship_ids"].sort()
        exclusion = next(
            value
            for value in block["excluded_contributions"]
            if value["relationship_ids"] == [relationship_id]
        )
        exclusion["element_id"] = endpoint_id
        exclusion["relationship_ids"] = [replacement_relationship_id]
        block["excluded_contributions"].sort(
            key=lambda value: (value["element_id"], value["reason"])
        )

    if mutation == "non_group_raw_ref":
        endpoint_id = custody.stable_id(
            "el", document_id, "raw_ref", "#/texts/1"
        )
        replace_remnant(
            endpoint_id,
            custody.stable_id(
                "rel",
                "contains",
                endpoint_id,
                block["primary_element_id"],
                "children",
            ),
        )
    elif mutation == "outside_bounded_group_ordinal":
        endpoint_id = custody.stable_id(
            "el", document_id, "raw_ref", "#/groups/4096"
        )
        replace_remnant(
            endpoint_id,
            custody.stable_id(
                "rel",
                "contains",
                endpoint_id,
                block["primary_element_id"],
                "children",
            ),
        )
    elif mutation == "custody_endpoint":
        endpoint_id = candidate["canonical_source_custody"]["records"][0][
            "group_element_id"
        ]
        replace_remnant(
            endpoint_id,
            custody.stable_id(
                "rel",
                "contains",
                endpoint_id,
                block["primary_element_id"],
                "children",
            ),
        )
    elif mutation == "canonical_contributor_endpoint":
        endpoint_id = candidate["canonical_presentation"]["pages"][0][
            "blocks"
        ][0]["primary_element_id"]
        replace_remnant(
            endpoint_id,
            custody.stable_id(
                "rel",
                "contains",
                endpoint_id,
                block["primary_element_id"],
                "children",
            ),
        )
    elif mutation == "marked_table_owner":
        block["relationship_ids"].remove(relationship_id)
        block["excluded_contributions"] = [
            value
            for value in block["excluded_contributions"]
            if value["relationship_ids"] != [relationship_id]
        ]
        block = candidate["canonical_presentation"]["pages"][0]["blocks"][2]
        relationship_id = custody.stable_id(
            "rel",
            "contains",
            group_id,
            block["primary_element_id"],
            "children",
        )
        block["relationship_ids"].append(relationship_id)
        block["relationship_ids"].sort()
        block["excluded_contributions"].append(
            {
                "element_id": group_id,
                "reason": "evidence_only_relationship",
                "relationship_ids": [relationship_id],
            }
        )
        block["excluded_contributions"].sort(
            key=lambda value: (value["element_id"], value["reason"])
        )
    elif mutation == "swapped_direction":
        replace_remnant(
            group_id,
            custody.stable_id(
                "rel",
                "contains",
                block["primary_element_id"],
                group_id,
                "parent",
            ),
        )
    elif mutation == "wrong_field":
        replace_remnant(
            group_id,
            custody.stable_id(
                "rel",
                "contains",
                group_id,
                block["primary_element_id"],
                "parent",
            ),
        )
    elif mutation in {
        "alternative_relationship",
        "reference_relationship",
        "caption_relationship",
    }:
        relationship_type = {
            "alternative_relationship": "alternative_of",
            "reference_relationship": "reference_of",
            "caption_relationship": "caption_of",
        }[mutation]
        replace_remnant(
            group_id,
            custody.stable_id(
                "rel",
                relationship_type,
                group_id,
                block["primary_element_id"],
                "children",
            ),
        )
    elif mutation == "multiple_remnants":
        candidate, block, _second_group, _second_relationship = (
            _with_inert_raw_group_remnant(
                candidate,
                group_ordinal=2,
            )
        )
    elif mutation == "cross_block_reuse":
        other = candidate["canonical_presentation"]["pages"][0]["blocks"][0]
        other["relationship_ids"].append(relationship_id)
        other["relationship_ids"].sort()
        other["excluded_contributions"].append(
            {
                "element_id": group_id,
                "reason": "evidence_only_relationship",
                "relationship_ids": [relationship_id],
            }
        )
        other["excluded_contributions"].sort(
            key=lambda value: (value["element_id"], value["reason"])
        )
    elif mutation == "reason":
        next(
            value
            for value in block["excluded_contributions"]
            if value["relationship_ids"] == [relationship_id]
        )["reason"] = "already_claimed"
    elif mutation == "content":
        block["markdown"] += " forged"
    elif mutation == "contributor":
        block["contributing_element_ids"].append(group_id)
    else:  # pragma: no cover - the parameter list is closed above.
        raise AssertionError(mutation)
    _refresh_canonical_views(candidate)
    _reseal_canonical_presentation(candidate)

    with pytest.raises(ValueError):
        if transport == "direct":
            ParseResult.model_validate(candidate)
        else:
            ParseResult.model_validate_json(strict_json_bytes(candidate))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("form_group", {"canonical_mode": "inert"}),
        ("layout_forms_projected", True),
        ("outline_group", {}),
        ("outline_items", []),
        ("layout_outline_structure_projected", True),
        ("layout_running_region_projected", True),
        ("running_region_policy", "p03-running-regions-v1"),
        ("running_region", None),
    ),
)
def test_context_free_visual_source_alternative_rejects_other_p03_ownership(
    field: str,
    value: Any,
) -> None:
    payload = _visual_projection_item(
        raw_ocr_text="",
        ocr_text="",
    ).model_dump(mode="json", exclude_unset=True)
    payload[field] = value
    try:
        item = ContentItem.model_validate(payload)
    except ValueError:
        return

    assert _context_free_visual_ocr_predecessor_is_closed(item) is False


def _context_free_visual_ir_pair(
    *,
    raw_ocr_text: str,
    ocr_text: str,
) -> tuple[DocumentIR, DocumentIR, str, dict[str, tuple[str, tuple[Any, ...]]]]:
    visual = _visual_projection_item(
        raw_ocr_text=raw_ocr_text,
        ocr_text=ocr_text,
    )
    assert _context_free_visual_ocr_predecessor_is_closed(visual)
    visual_payload = visual.model_dump(mode="json", exclude_unset=True)
    document = {
        "document": {"sha256": "a" * 64},
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [
                    visual_payload,
                    {
                        "id": "p1-text",
                        "type": "text",
                        "reading_order": 1,
                        "value": "unrelated",
                        "md": "unrelated",
                        "source": "native",
                    },
                ],
                "warnings": [],
            }
        ],
    }
    base_ir = build_document_ir(document)
    alternate_document = deepcopy(document)
    alternate_document["pages"][0]["items"][0]["source"] = "ocr"
    alternate_ir = build_document_ir(alternate_document)
    owner_id = next(
        element.id
        for element in base_ir.elements
        if element.properties.get("legacy_item", {}).get("id")
        == "p1-visual"
    )
    mode = "nonempty" if raw_ocr_text else "empty"
    source_sensitive_owners = {
        owner_id: (
            mode,
            _context_free_visual_source_sensitive_children(visual),
        )
    }
    return base_ir, alternate_ir, owner_id, source_sensitive_owners


@pytest.mark.parametrize(
    ("raw_ocr_text", "ocr_text"),
    (("", ""), ("noise\nkept", "kept")),
    ids=("empty-ledger", "nonempty-ledger"),
)
def test_context_free_visual_source_delta_has_complete_exact_ir_closure(
    raw_ocr_text: str,
    ocr_text: str,
) -> None:
    base_ir, alternate_ir, owner_id, source_sensitive_owners = (
        _context_free_visual_ir_pair(
            raw_ocr_text=raw_ocr_text,
            ocr_text=ocr_text,
        )
    )
    base = _context_free_ir_identity_projection(
        base_ir,
        source_sensitive_owners,
    )
    alternate = _context_free_ir_identity_projection(
        alternate_ir,
        source_sensitive_owners,
    )

    assert [name for name, _records in base[1]] == [
        "coordinate_systems",
        "bboxes",
        "pages",
        "regions",
        "elements",
        "evidence",
        "text_rules",
        "text_runs",
        "relationships",
        "concerns",
    ]
    assert base[:2] == alternate[:2]
    assert _context_free_ir_delta_is_closed(
        base,
        alternate,
        {owner_id},
    )


@pytest.mark.parametrize(
    "collection",
    (
        "coordinate_systems",
        "bboxes",
        "pages",
        "regions",
        "elements",
        "evidence",
        "text_rules",
        "text_runs",
        "relationships",
        "concerns",
    ),
)
def test_context_free_ir_projection_rejects_drift_in_every_collection(
    collection: str,
) -> None:
    base_ir, alternate_ir, owner_id, source_sensitive_owners = (
        _context_free_visual_ir_pair(
            raw_ocr_text="noise\nkept",
            ocr_text="kept",
        )
    )
    base = _context_free_ir_identity_projection(
        base_ir,
        source_sensitive_owners,
    )
    if collection == "coordinate_systems":
        alternate_ir.coordinate_systems[0].origin = "bottom_left"
    elif collection == "bboxes":
        alternate_ir.bboxes[0].x += 1.0
    elif collection == "pages":
        alternate_ir.pages[0].page_label = "forged"
    elif collection == "regions":
        alternate_ir.regions[0].role = "forged"
    elif collection == "elements":
        next(
            element
            for element in alternate_ir.elements
            if element.properties.get("legacy_item", {}).get("id")
            == "p1-text"
        ).value = "forged"
    elif collection == "evidence":
        text_id = next(
            element.id
            for element in alternate_ir.elements
            if element.properties.get("legacy_item", {}).get("id")
            == "p1-text"
        )
        next(
            record
            for record in alternate_ir.evidence
            if record.element_id == text_id
        ).metadata["forged"] = True
    elif collection in {"text_rules", "text_runs", "concerns"}:
        getattr(alternate_ir, collection).append(
            SimpleNamespace(
                id=f"{collection}-forged",
                model_dump=lambda **_kwargs: {
                    "id": f"{collection}-forged",
                    "forged": True,
                },
            )
        )
    elif collection == "relationships":
        next(
            relationship
            for relationship in alternate_ir.relationships
            if relationship.type.value == "reading_before"
        ).metadata["forged"] = True
    else:  # pragma: no cover - the parameter list is closed above.
        raise AssertionError(collection)

    alternate = _context_free_ir_identity_projection(
        alternate_ir,
        source_sensitive_owners,
    )
    assert not _context_free_ir_delta_is_closed(
        base,
        alternate,
        {owner_id},
    )


@pytest.mark.parametrize(
    "mutation",
    ("method", "value", "bbox", "source_metadata", "extra_metadata"),
)
def test_context_free_owner_evidence_never_masks_non_source_drift(
    mutation: str,
) -> None:
    base_ir, alternate_ir, owner_id, source_sensitive_owners = (
        _context_free_visual_ir_pair(
            raw_ocr_text="noise\nkept",
            ocr_text="kept",
        )
    )
    base = _context_free_ir_identity_projection(
        base_ir,
        source_sensitive_owners,
    )
    evidence = next(
        record
        for record in alternate_ir.evidence
        if record.element_id == owner_id
    )
    if mutation == "method":
        evidence.method = type(evidence.method).NATIVE
    elif mutation == "value":
        evidence.value = "forged"
    elif mutation == "bbox":
        evidence.bbox_id = "box-forged"
    elif mutation == "source_metadata":
        evidence.metadata["source"] = "derived"
    elif mutation == "extra_metadata":
        evidence.metadata["authority"] = True
    else:  # pragma: no cover - the parameter list is closed above.
        raise AssertionError(mutation)

    if mutation == "extra_metadata":
        alternate = _context_free_ir_identity_projection(
            alternate_ir,
            source_sensitive_owners,
        )
        assert not _context_free_ir_delta_is_closed(
            base,
            alternate,
            {owner_id},
        )
    else:
        with pytest.raises(ValueError, match="owner evidence"):
            _context_free_ir_identity_projection(
                alternate_ir,
                source_sensitive_owners,
            )


def test_private_trusted_context_is_identity_bound_and_not_serializable() -> None:
    baseline, candidate = _trusted_terminal_candidate()
    baseline_result = ParseResult.model_validate(baseline)
    context = _trusted_table_validation_context(baseline_result)

    validated = ParseResult.model_validate(candidate, context=context)

    assert _trusted_table_baseline_from_context(context) is baseline_result
    assert not hasattr(context, "model_dump")
    with pytest.raises(TypeError):
        json.dumps(context)
    serialized = validated.model_dump(mode="json", exclude_none=True)
    assert "trusted_table" not in json.dumps(serialized, sort_keys=True)

    wrong_token = _TrustedTableValidationContext(object(), baseline_result)
    assert _trusted_table_baseline_from_context(wrong_token) is None
    assert _trusted_table_baseline_from_context({"baseline": baseline_result}) is None
    assert _trusted_table_baseline_from_context(object()) is None


@pytest.mark.parametrize("transport", ("direct", "json"))
@pytest.mark.parametrize(
    "mutation",
    (
        "delete_normalized",
        "delete_merged",
        "lower_assertion_count",
        "raise_assertion_count",
    ),
)
def test_custody_normalized_assertion_multiplicity_is_closed(
    transport: str,
    mutation: str,
) -> None:
    _baseline, candidate = _trusted_terminal_candidate()
    sidecar = candidate["canonical_source_custody"]
    assert sidecar["record_count"] == 2
    assert {record["normalized_assertion_count"] for record in sidecar["records"]} == {
        2
    }
    assert {record["normalization_outcome"] for record in sidecar["records"]} == {
        "normalized_edge",
        "merged_edge",
    }

    if mutation == "delete_normalized":
        sidecar["records"] = [
            record
            for record in sidecar["records"]
            if record["normalization_outcome"] != "normalized_edge"
        ]
    elif mutation == "delete_merged":
        sidecar["records"] = [
            record
            for record in sidecar["records"]
            if record["normalization_outcome"] != "merged_edge"
        ]
    elif mutation == "lower_assertion_count":
        for record in sidecar["records"]:
            record["normalized_assertion_count"] = 1
    elif mutation == "raise_assertion_count":
        for record in sidecar["records"]:
            record["normalized_assertion_count"] = 3
    else:  # pragma: no cover - the parameter list is closed above.
        raise AssertionError(mutation)
    _reseal_sidecar(sidecar)

    with pytest.raises(
        ValueError,
        match="canonical source custody normalized assertion count differs",
    ):
        if transport == "direct":
            ParseResult.model_validate(candidate)
        else:
            ParseResult.model_validate_json(
                json.dumps(candidate, allow_nan=False, separators=(",", ":"))
            )


def test_custody_normalized_assertion_count_is_required_by_schema() -> None:
    schema = ParseResult.model_json_schema()
    record_schema = schema["$defs"]["OpaqueRawGroupCustodyRecord"]

    assert "normalized_assertion_count" in record_schema["required"]
    assertion_count = record_schema["properties"]["normalized_assertion_count"]
    assert assertion_count["minimum"] == 1
    assert assertion_count["maximum"] == 65_536


@pytest.mark.parametrize("transport", ("direct", "json"))
def test_private_terminal_context_anchors_whole_custody_sidecar(
    transport: str,
) -> None:
    baseline, candidate = _trusted_terminal_candidate()
    baseline_result = ParseResult.model_validate(baseline)
    expected_custody = CanonicalSourceCustody.model_validate(
        deepcopy(candidate["canonical_source_custody"])
    )
    context = _trusted_table_validation_context(
        baseline_result,
        expected_custody,
    )
    sidecar = candidate["canonical_source_custody"]
    sidecar["records"] = []
    _reseal_sidecar(sidecar)

    with pytest.raises(
        ValueError,
        match="trusted table canonical source custody differs",
    ):
        if transport == "direct":
            ParseResult.model_validate(candidate, context=context)
        else:
            ParseResult.model_validate_json(
                json.dumps(candidate, allow_nan=False, separators=(",", ":")),
                context=context,
            )


def test_private_terminal_context_identity_includes_canonical_digest() -> None:
    baseline, candidate = _trusted_terminal_candidate()
    baseline_result = ParseResult.model_validate(baseline)
    expected_payload = deepcopy(candidate["canonical_source_custody"])
    actual_digest = expected_payload["canonical_presentation_sha256"]
    expected_payload["canonical_presentation_sha256"] = (
        "f" * 64 if actual_digest != "f" * 64 else "e" * 64
    )
    expected_custody = CanonicalSourceCustody.model_validate(expected_payload)
    context = _trusted_table_validation_context(
        baseline_result,
        expected_custody,
    )

    with pytest.raises(
        ValueError,
        match="trusted table canonical source custody differs",
    ):
        ParseResult.model_validate(candidate, context=context)


def test_trusted_context_rejects_every_non_target_or_baseline_delta() -> None:
    baseline, candidate = _trusted_terminal_candidate()

    def validate(
        raw_candidate: dict[str, Any],
        raw_baseline: dict[str, Any] | None = None,
    ) -> None:
        baseline_result = ParseResult.model_validate(
            deepcopy(raw_baseline if raw_baseline is not None else baseline)
        )
        ParseResult.model_validate(
            deepcopy(raw_candidate),
            context=_trusted_table_validation_context(baseline_result),
        )

    validate(candidate)

    wrong_document = deepcopy(candidate)
    wrong_document["document"]["filename"] = "forged.pdf"
    with pytest.raises(ValueError, match="trusted P03 baseline document differs"):
        validate(wrong_document)

    altered_public = deepcopy(candidate)
    public_item = next(
        item
        for item in altered_public["pages"][0]["items"]
        if item["id"] != TABLE_ID and item["type"] == "text"
    )
    public_item["value"] = "forged non-target"
    public_item["md"] = "forged non-target"
    with pytest.raises(
        ValueError,
        match="trusted P03 baseline non-target item differs",
    ):
        validate(altered_public)

    altered_block = deepcopy(candidate)
    block = next(
        value
        for value in altered_block["canonical_presentation"]["pages"][0][
            "blocks"
        ]
        if value["primary_element_type"] == "text"
    )
    block["markdown"] = "forged non-target"
    block["text"] = "forged non-target"
    _refresh_canonical_views(altered_block)
    _reseal_canonical_presentation(altered_block)
    with pytest.raises(
        ValueError,
        match="trusted P03 baseline non-target canonical block differs",
    ):
        validate(altered_block)

    altered_baseline = ParseResult.model_validate(deepcopy(baseline))
    context = _trusted_table_validation_context(altered_baseline)
    altered_baseline.document.filename = "mutated-after-validation.pdf"
    with pytest.raises(ValueError, match="trusted P03 baseline document differs"):
        ParseResult.model_validate(deepcopy(candidate), context=context)


def test_trusted_context_never_waives_table_target_or_custody_contracts() -> None:
    baseline, candidate = _trusted_nonvalid_candidate()

    def rejects(
        raw_candidate: dict[str, Any],
        match: str,
        *,
        raw_baseline: dict[str, Any] = baseline,
    ) -> None:
        baseline_result = ParseResult.model_validate(deepcopy(raw_baseline))
        with pytest.raises(ValueError, match=match):
            ParseResult.model_validate(
                raw_candidate,
                context=_trusted_table_validation_context(baseline_result),
            )

    second_field_delta = deepcopy(candidate)
    target = next(
        item
        for item in second_field_delta["pages"][0]["items"]
        if item.get("table_evidence") is not None
    )
    target["warnings"] = ["forged non-sidecar delta"]
    rejects(
        second_field_delta,
        "trusted P03 baseline nonvalid table representation differs",
    )

    forged_valid = deepcopy(candidate)
    target = next(
        item
        for item in forged_valid["pages"][0]["items"]
        if item.get("table_evidence") is not None
    )
    target["table_evidence"]["status"] = "valid"
    rejects(forged_valid, "valid table")

    forged_target_block = deepcopy(candidate)
    block = next(
        value
        for value in forged_target_block["canonical_presentation"]["pages"][0][
            "blocks"
        ]
        if value["primary_element_type"] == "table"
    )
    block["markdown"] += "\n\nforged target"
    block["text"] += "\n\nforged target"
    _refresh_canonical_views(forged_target_block)
    _reseal_canonical_presentation(forged_target_block)
    rejects(forged_target_block, "table canonical block differs")

    altered_baseline_target = ParseResult.model_validate(deepcopy(baseline))
    baseline_canonical = altered_baseline_target.model_extra[
        "canonical_presentation"
    ]
    baseline_block = next(
        value
        for value in baseline_canonical["pages"][0]["blocks"]
        if value["primary_element_type"] == "table"
    )
    baseline_block["markdown"] += "\n\nforged baseline target"
    baseline_block["text"] += "\n\nforged baseline target"
    baseline_payload = altered_baseline_target.model_dump(
        mode="json",
        exclude_unset=True,
    )
    _refresh_canonical_views(baseline_payload)
    altered_baseline_target = ParseResult.model_validate(baseline_payload)
    with pytest.raises(ValueError, match="table canonical block differs"):
        ParseResult.model_validate(
            deepcopy(candidate),
            context=_trusted_table_validation_context(
                altered_baseline_target
            ),
        )

    forged_audit = deepcopy(candidate)
    custody_baseline, forged_audit = _trusted_terminal_candidate()
    custody_relationship_id = forged_audit["canonical_source_custody"][
        "records"
    ][0]["relationship_id"]
    audit_block = next(
        value
        for value in forged_audit["canonical_presentation"]["pages"][0][
            "blocks"
        ]
        if value["primary_element_type"] == "text"
    )
    audit_block["relationship_ids"] = sorted(
        [*audit_block["relationship_ids"], custody_relationship_id]
    )
    audit_block["excluded_contributions"].append(
        {
            "element_id": "el-forged-custody-audit",
            "reason": "evidence_only_relationship",
            "relationship_ids": [custody_relationship_id],
        }
    )
    _reseal_canonical_presentation(forged_audit)
    rejects(
        forged_audit,
        "diagnostic canonical source custody carries authority",
        raw_baseline=custody_baseline,
    )


def _grandfathered_non_target_splice_case() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    tuple[Any, ...],
]:
    document = {
        "sha256": "b" * 64,
    }
    page = {
        "page_index": 1,
        "page_number": 1,
        "page_label": "1",
        "page_width": 612.0,
        "page_height": 792.0,
        "unit": "pt",
        "success": True,
        "items": [
            {
                "id": "p1-text",
                "type": "text",
                "reading_order": 0,
                "value": "Received:",
                "md": "Received:",
                "source": "native",
            },
            {
                "id": "p1-table",
                "type": "table",
                "reading_order": 1,
                "value": [["old"]],
                "md": "old",
                "source": "native",
            },
        ],
        "warnings": [],
    }
    baseline = {"document": document, "pages": [page]}
    baseline["canonical_presentation"] = build_canonical_presentation(
        build_document_ir(baseline)
    ).model_dump(mode="json", exclude_none=True)
    baseline_non_target = baseline["canonical_presentation"]["pages"][0][
        "blocks"
    ][0]
    relationship_id = "rel-00000000000000000011"
    baseline_non_target["relationship_ids"] = [relationship_id]
    baseline_non_target["excluded_contributions"] = [
        {
            "element_id": "el-00000000000000000012",
            "reason": "evidence_only_relationship",
            "relationship_ids": [relationship_id],
        }
    ]
    _refresh_canonical_views(baseline)

    candidate = deepcopy(baseline)
    candidate["pages"][0]["items"][1]["value"] = [["new"]]
    candidate["pages"][0]["items"][1]["md"] = "new"
    canonical = build_canonical_presentation(
        build_document_ir(
            {
                "document": candidate["document"],
                "pages": candidate["pages"],
            }
        )
    ).model_dump(mode="json", exclude_none=True)
    transaction = ((1, 0, 0, "p1-table", None, None, None),)
    return baseline, candidate, canonical, transaction


def test_terminal_non_target_requires_predecessor_then_restores_exact_p03_block() -> None:
    baseline, candidate, canonical, transaction = (
        _grandfathered_non_target_splice_case()
    )
    predecessor_non_target = deepcopy(canonical["pages"][0]["blocks"][0])
    baseline_non_target = baseline["canonical_presentation"]["pages"][0][
        "blocks"
    ][0]

    result = pipeline._splice_terminal_table_canonical(
        baseline,
        candidate,
        canonical,
        transaction,
    )

    assert predecessor_non_target["relationship_ids"] == []
    assert predecessor_non_target["excluded_contributions"] == []
    assert strict_json_bytes(result["pages"][0]["blocks"][0]) == (
        strict_json_bytes(baseline_non_target)
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "candidate_relationship",
        "candidate_exclusion",
        "scalar_drift",
        "contributor_drift",
        "public_item_drift",
        "grandfathered_candidate_copy",
    ),
)
def test_terminal_non_target_rejects_every_nonpredecessor_change(
    mutation: str,
) -> None:
    baseline, candidate, canonical, transaction = (
        _grandfathered_non_target_splice_case()
    )
    block = canonical["pages"][0]["blocks"][0]
    if mutation == "candidate_relationship":
        block["relationship_ids"] = ["rel-00000000000000000099"]
    elif mutation == "candidate_exclusion":
        block["excluded_contributions"] = [
            {
                "element_id": "el-00000000000000000099",
                "reason": "evidence_only_relationship",
                "relationship_ids": ["rel-00000000000000000099"],
            }
        ]
    elif mutation == "scalar_drift":
        block["text"] = "Received: attacker"
    elif mutation == "contributor_drift":
        block["contributing_element_ids"].append(
            "el-00000000000000000099"
        )
    elif mutation == "public_item_drift":
        candidate["pages"][0]["items"][0]["value"] = "attacker"
    elif mutation == "grandfathered_candidate_copy":
        canonical["pages"][0]["blocks"][0] = deepcopy(
            baseline["canonical_presentation"]["pages"][0]["blocks"][0]
        )
    else:  # pragma: no cover - the parameter list is closed above.
        raise AssertionError(mutation)

    with pytest.raises(ValueError, match="non-target"):
        pipeline._splice_terminal_table_canonical(
            baseline,
            candidate,
            canonical,
            transaction,
        )


def test_rebind_is_terminal_and_preserves_running_and_non_table_closure() -> None:
    fixture = _boundary_fixture()
    phase03_pages = deepcopy(fixture.marked["pages"])
    transaction = _detach(phase03_pages)
    predecessor = deepcopy(fixture.predecessor)
    predecessor["pages"] = phase03_pages
    projected = pipeline._apply_shared_ir_compatibility_projection(
        predecessor,
        _p03_settings(table_enabled=True),
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
    )
    before = deepcopy(projected)

    rebound_pages = _rebind(deepcopy(projected["pages"]), transaction)
    candidate = deepcopy(projected)
    candidate["pages"] = rebound_pages

    assert custody.has_literal_table_marker(candidate)
    assert strict_json_bytes(_without_table_items(candidate)) == strict_json_bytes(
        _without_table_items(before)
    )
    assert running_regions.running_region_replay_identity(candidate) == (
        running_regions.running_region_replay_identity(before)
    )
    assert candidate["pages"][0]["page_identity"] == before["pages"][0][
        "page_identity"
    ]
    assert candidate["processing"]["running_regions"] == before["processing"][
        "running_regions"
    ]
    assert candidate["warnings"] == before["warnings"]


def test_rebind_preserves_embedded_images_and_arbitrary_future_p03_extras() -> None:
    fixture = _boundary_fixture()
    pages = deepcopy(fixture.marked["pages"])
    transaction = _detach(pages)
    predecessor_table = pages[0]["items"][2]
    p03_images = [
        {
            "id": "p03-owned-image",
            "bbox": {
                "x": 10.0,
                "y": 40.0,
                "width": 20.0,
                "height": 10.0,
                "unit": "pt",
            },
        }
    ]
    predecessor_table["embedded_images"] = deepcopy(p03_images)
    predecessor_table["future_p03_sidecar"] = {
        "policy_id": "future-p03-control-v1",
        "opaque": [1, {"retained": True}],
    }

    rebound = _rebind(pages, transaction)
    table = rebound[0]["items"][2]

    assert table["embedded_images"] == p03_images
    assert table["future_p03_sidecar"] == predecessor_table[
        "future_p03_sidecar"
    ]
    assert table["table_evidence"] == fixture.marked["pages"][0]["items"][2][
        "table_evidence"
    ]
    assert table["_p04_predecessor_snapshot"]["embedded_images"] == p03_images
    assert table["_p04_predecessor_snapshot"]["future_p03_sidecar"] == (
        predecessor_table["future_p03_sidecar"]
    )


def test_embedded_images_cannot_be_smuggled_as_a_p04_owned_delta() -> None:
    fixture = _boundary_fixture()
    pages = deepcopy(fixture.marked["pages"])
    pages[0]["items"][2]["embedded_images"] = [
        {"id": "forged-p04-image"}
    ]

    with pytest.raises(ValueError, match="table overlay P04 delta differs"):
        _detach(pages)


def test_same_page_p03_reorder_uses_stable_id_and_adopts_terminal_order() -> None:
    fixture = _boundary_fixture()
    pages = deepcopy(fixture.marked["pages"])
    transaction = _detach(pages)

    # P03 may legitimately change the order of items on the same physical
    # page.  The held P04 overlay follows the stable public item identity, not
    # its stale pre-P03 offset or reading_order.
    table_predecessor = pages[0]["items"].pop(2)
    pages[0]["items"].insert(1, table_predecessor)
    for reading_order, item in enumerate(pages[0]["items"]):
        item["reading_order"] = reading_order
    predecessor = deepcopy(fixture.predecessor)
    predecessor["pages"] = pages
    sink: dict[str, Any] = {}
    baseline = pipeline._apply_shared_ir_compatibility_projection(
        predecessor,
        _p03_settings(table_enabled=True),
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        internal_ir_sink=sink,
    )
    assert isinstance(sink.get("ir"), DocumentIR)
    before = deepcopy(baseline)

    rebound = _rebind(deepcopy(baseline["pages"]), transaction)
    rebound_table = rebound[0]["items"][1]
    assert rebound_table["id"] == TABLE_ID
    assert rebound_table["reading_order"] == 1
    assert rebound_table["_p04_predecessor_snapshot"]["reading_order"] == 1

    now = time.perf_counter()
    result = pipeline._apply_terminal_table_authority(
        baseline,
        sink["ir"],
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state={},
    )

    assert strict_json_bytes(baseline) == strict_json_bytes(before)
    assert custody.has_literal_table_marker(result)
    assert result["pages"][0]["items"][1]["id"] == TABLE_ID
    assert result["pages"][0]["items"][1]["reading_order"] == 1
    assert strict_json_bytes(_non_table_public_closure(result)) == (
        strict_json_bytes(_non_table_public_closure(before))
    )
    assert running_regions.running_region_replay_identity(result) == (
        running_regions.running_region_replay_identity(before)
    )


def test_word_geometry_disable_state_blocks_terminal_table_authority() -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    before = deepcopy(baseline)
    now = time.perf_counter()
    state = {
        "span_fidelity_disabled": True,
        "span_fidelity_failure_reason": "table_word_geometry_unavailable",
    }

    result = pipeline._apply_terminal_table_authority(  # noqa: SLF001
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(result) == strict_json_bytes(before)
    assert strict_json_bytes(baseline) == strict_json_bytes(before)
    assert not custody.has_literal_table_marker(result)
    assert state["span_fidelity_disabled"] is True
    assert state["span_fidelity_failure_reason"] == (
        "table_word_geometry_unavailable"
    )


@pytest.mark.parametrize(
    ("locator_case", "message"),
    (
        ("page_migration", "table overlay terminal item binding differs"),
        ("same_page_duplicate", "table overlay terminal item identity differs"),
        ("cross_page_duplicate", "table overlay terminal item identity differs"),
        ("missing_id", "table overlay terminal item identity differs"),
        ("noncontiguous_order", "table overlay terminal reading order differs"),
    ),
    ids=(
        "page-migration",
        "same-page-duplicate-id",
        "cross-page-duplicate-id",
        "missing-id",
        "noncontiguous-order",
    ),
)
def test_invalid_terminal_locator_rejects_p04_and_returns_exact_p03_baseline(
    monkeypatch: pytest.MonkeyPatch,
    locator_case: str,
    message: str,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    malformed_pages = deepcopy(baseline["pages"])
    target = malformed_pages[0]["items"][2]

    if locator_case == "page_migration":
        migrated = malformed_pages[0]["items"].pop(2)
        for reading_order, item in enumerate(malformed_pages[0]["items"]):
            item["reading_order"] = reading_order
        migrated["reading_order"] = 0
        malformed_pages.append(
            {
                "page_index": 2,
                "page_number": 2,
                "page_label": "2",
                "page_width": malformed_pages[0]["page_width"],
                "page_height": malformed_pages[0]["page_height"],
                "unit": malformed_pages[0]["unit"],
                "success": True,
                "items": [migrated],
                "warnings": [],
            }
        )
    elif locator_case == "same_page_duplicate":
        malformed_pages[0]["items"][1]["id"] = TABLE_ID
    elif locator_case == "cross_page_duplicate":
        duplicate = deepcopy(target)
        duplicate["reading_order"] = 0
        malformed_pages.append(
            {
                "page_index": 2,
                "page_number": 2,
                "page_label": "2",
                "page_width": malformed_pages[0]["page_width"],
                "page_height": malformed_pages[0]["page_height"],
                "unit": malformed_pages[0]["unit"],
                "success": True,
                "items": [duplicate],
                "warnings": [],
            }
        )
    elif locator_case == "missing_id":
        target.pop("id")
    elif locator_case == "noncontiguous_order":
        target["reading_order"] = 9
    else:  # pragma: no cover - the closed parameter matrix owns this branch.
        raise AssertionError(f"unknown locator case: {locator_case}")

    actual_rebind = table_semantics.rebind_table_overlays_after_phase03
    with pytest.raises(ValueError, match=message):
        actual_rebind(
            malformed_pages,
            transaction,
            deadline=time.perf_counter() + 2.0,
        )

    def malformed_terminal_rebind(
        _pages: list[dict[str, Any]],
        held_transaction: tuple[Any, ...],
        *,
        deadline: float,
    ) -> list[dict[str, Any]]:
        return actual_rebind(
            deepcopy(malformed_pages),
            held_transaction,
            deadline=deadline,
        )

    monkeypatch.setattr(
        table_semantics,
        "rebind_table_overlays_after_phase03",
        malformed_terminal_rebind,
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_shared_ir_compatibility_projection",
        lambda *_args, **_kwargs: pytest.fail(
            "locator rollback reran shared P03"
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_terminal_source_text_alignment",
        lambda *_args, **_kwargs: pytest.fail(
            "locator rollback reran terminal source alignment"
        ),
    )
    state: dict[str, Any] = {}
    now = time.perf_counter()
    result = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(result) == strict_json_bytes(baseline)
    assert not custody.has_literal_table_marker(result)
    assert state.get("custody_rejected") is True
    assert state.get("timed_out") is not True


def test_parse_orders_one_table_transaction_after_both_p03_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _boundary_fixture()
    loaded = LoadedDocument(
        kind=InputKind.PDF,
        original_bytes=fixture.source_pdf_bytes,
        processing_bytes=fixture.source_pdf_bytes,
        original_filename="p04-p03-boundary.pdf",
        processing_filename="p04-p03-boundary.pdf",
        mime_type="application/pdf",
        source_format="PDF",
    )
    order: list[str] = []
    held_transaction: tuple[Any, ...] | None = None
    actual_detach = table_semantics.detach_table_overlays_for_phase03

    def detach_spy(
        pages: list[dict[str, Any]], *, deadline: float
    ) -> tuple[Any, ...]:
        nonlocal held_transaction
        order.append("detach_table")
        held_transaction = actual_detach(pages, deadline=deadline)
        return held_transaction

    def shared_spy(
        payload: dict[str, Any],
        _settings: Settings,
        **kwargs: Any,
    ) -> dict[str, Any]:
        order.append("shared_p03")
        assert not custody.has_literal_table_marker(payload)
        assert payload["pages"][0]["items"][2] == fixture.predecessor["pages"][
            0
        ]["items"][2]
        sink = kwargs.get("internal_ir_sink")
        assert type(sink) is dict
        sink["ir"] = build_document_ir(payload, raw_graph=fixture.raw_graph)
        return payload

    def source_spy(
        payload: dict[str, Any],
        _settings: Settings,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        order.append("source_alignment_p03")
        assert not custody.has_literal_table_marker(payload)
        return payload

    def terminal_spy(
        baseline: dict[str, Any],
        _baseline_ir: DocumentIR,
        transaction: tuple[Any, ...],
        _settings: Settings,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        order.append("terminal_table")
        assert transaction is held_transaction
        assert not custody.has_literal_table_marker(baseline)
        return baseline

    monkeypatch.setattr(pipeline.shutil, "which", lambda _name: "/ocr")
    monkeypatch.setattr(
        pipeline,
        "_native_pdf_pages",
        lambda *_args, **_kwargs: (
            deepcopy(fixture.marked["pages"]),
            list(fixture.native_texts),
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (deepcopy(fixture.raw_graph), []),
    )
    monkeypatch.setattr(pipeline, "extract_image_ocr", lambda *_a, **_k: {})
    monkeypatch.setattr(
        pipeline, "_select_pdf_render_requests", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        pipeline, "extract_rendered_pdf_ocr", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(pipeline, "extract_vector_tables", lambda *_a, **_k: {})
    monkeypatch.setattr(
        pipeline,
        "_extract_partitioned_table_repair_words",
        lambda _pdf, _raw, deadline, _page_deadlines, _state: (
            {},
            deadline,
            None,
        ),
    )
    monkeypatch.setattr(pipeline, "_analyze_shared_pages", lambda _context: None)
    monkeypatch.setattr(
        table_semantics,
        "detach_table_overlays_for_phase03",
        detach_spy,
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_shared_ir_compatibility_projection",
        shared_spy,
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_terminal_source_text_alignment",
        source_spy,
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_terminal_table_authority",
        terminal_spy,
    )
    monkeypatch.setattr(
        custody,
        "detach_opaque_group_edges",
        lambda *_args, **_kwargs: pytest.fail(
            "parse predecessor path detached raw group relationships"
        ),
    )

    result = pipeline._parse_loaded_document(
        loaded,
        _p03_settings(table_enabled=True),
    )

    assert result.document.filename == "p04-p03-boundary.pdf"
    assert order == [
        "detach_table",
        "shared_p03",
        "source_alignment_p03",
        "terminal_table",
    ]


def test_corrupt_private_predecessor_aborts_before_any_p03_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _boundary_fixture()
    loaded = LoadedDocument(
        kind=InputKind.PDF,
        original_bytes=fixture.source_pdf_bytes,
        processing_bytes=fixture.source_pdf_bytes,
        original_filename="p04-corrupt-predecessor.pdf",
        processing_filename="p04-corrupt-predecessor.pdf",
        mime_type="application/pdf",
        source_format="PDF",
    )
    emitted_pages = deepcopy(fixture.marked["pages"])
    marked = emitted_pages[0]["items"][2]
    hostile_snapshot: dict[str, Any] = {"type": "table"}
    hostile_snapshot["cycle"] = hostile_snapshot
    marked["_p04_predecessor_snapshot"] = hostile_snapshot
    marked["rows"][0][0] = "UNAUTHORIZED P04 PROJECTION"
    p03_calls: list[str] = []

    def forbidden_p03(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        p03_calls.append("invoked")
        pytest.fail("corrupt table predecessor reached a P03 consumer")

    monkeypatch.setattr(pipeline.shutil, "which", lambda _name: "/ocr")
    monkeypatch.setattr(
        pipeline,
        "_native_pdf_pages",
        lambda *_args, **_kwargs: (emitted_pages, list(fixture.native_texts)),
    )
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (deepcopy(fixture.raw_graph), []),
    )
    monkeypatch.setattr(pipeline, "extract_image_ocr", lambda *_a, **_k: {})
    monkeypatch.setattr(
        pipeline, "_select_pdf_render_requests", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        pipeline, "extract_rendered_pdf_ocr", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(pipeline, "extract_vector_tables", lambda *_a, **_k: {})
    monkeypatch.setattr(
        pipeline,
        "_extract_partitioned_table_repair_words",
        lambda _pdf, _raw, deadline, _page_deadlines, _state: (
            {},
            deadline,
            None,
        ),
    )
    monkeypatch.setattr(pipeline, "_analyze_shared_pages", lambda _context: None)
    monkeypatch.setattr(
        pipeline,
        "_apply_shared_ir_compatibility_projection",
        forbidden_p03,
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_terminal_source_text_alignment",
        forbidden_p03,
    )

    with pytest.raises(ValueError, match="predecessor.*unavailable"):
        pipeline._parse_loaded_document(
            loaded,
            _p03_settings(table_enabled=True),
        )

    assert p03_calls == []
    assert emitted_pages[0]["items"][2] == {}


@pytest.mark.parametrize("failure_type", [MemoryError, RecursionError])
def test_detachment_resource_failure_restores_before_p03_continues(
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    fixture = _boundary_fixture()
    loaded = LoadedDocument(
        kind=InputKind.PDF,
        original_bytes=fixture.source_pdf_bytes,
        processing_bytes=fixture.source_pdf_bytes,
        original_filename="p04-detach-resource.pdf",
        processing_filename="p04-detach-resource.pdf",
        mime_type="application/pdf",
        source_format="PDF",
    )
    emitted_pages = deepcopy(fixture.marked["pages"])
    expected_table = deepcopy(fixture.predecessor["pages"][0]["items"][2])
    p03_calls: list[str] = []
    captured_state: dict[str, Any] = {}
    restore_calls = 0
    actual_segment = pipeline._run_table_custody_document_segment
    actual_restore = table_semantics._restore_all_table_predecessors

    def failed_detach(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        raise failure_type("injected table detachment resource failure")

    def segment_spy(
        document_deadline: float,
        page_deadlines: dict[int, float],
        state: dict[str, Any],
        operation: Any,
    ) -> Any:
        captured_state["value"] = state
        return actual_segment(
            document_deadline,
            page_deadlines,
            state,
            operation,
        )

    def restore_spy(pages: Any, deadline: float) -> None:
        nonlocal restore_calls
        restore_calls += 1
        actual_restore(pages, deadline)

    def shared_spy(
        payload: dict[str, Any],
        _settings: Settings,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        p03_calls.append("shared")
        assert not custody.has_literal_table_marker(payload)
        assert payload["pages"][0]["items"][2] == expected_table
        return payload

    def source_spy(
        payload: dict[str, Any],
        _settings: Settings,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        p03_calls.append("source")
        assert not custody.has_literal_table_marker(payload)
        assert payload["pages"][0]["items"][2] == expected_table
        return payload

    monkeypatch.setattr(pipeline.shutil, "which", lambda _name: "/ocr")
    monkeypatch.setattr(
        pipeline,
        "_native_pdf_pages",
        lambda *_args, **_kwargs: (emitted_pages, list(fixture.native_texts)),
    )
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (deepcopy(fixture.raw_graph), []),
    )
    monkeypatch.setattr(pipeline, "extract_image_ocr", lambda *_a, **_k: {})
    monkeypatch.setattr(
        pipeline, "_select_pdf_render_requests", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        pipeline, "extract_rendered_pdf_ocr", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(pipeline, "extract_vector_tables", lambda *_a, **_k: {})
    monkeypatch.setattr(
        pipeline,
        "_extract_partitioned_table_repair_words",
        lambda _pdf, _raw, deadline, _page_deadlines, _state: (
            {},
            deadline,
            None,
        ),
    )
    monkeypatch.setattr(pipeline, "_analyze_shared_pages", lambda _context: None)
    monkeypatch.setattr(
        table_semantics,
        "detach_table_overlays_for_phase03",
        failed_detach,
    )
    monkeypatch.setattr(
        table_semantics,
        "_restore_all_table_predecessors",
        restore_spy,
    )
    monkeypatch.setattr(
        pipeline,
        "_run_table_custody_document_segment",
        segment_spy,
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_shared_ir_compatibility_projection",
        shared_spy,
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_terminal_source_text_alignment",
        source_spy,
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_terminal_table_authority",
        lambda *_args, **_kwargs: pytest.fail(
            "empty table transaction reached terminal table authority"
        ),
    )

    result = pipeline._parse_loaded_document(
        loaded,
        _p03_settings(table_enabled=True),
    )

    assert p03_calls == ["shared", "source"]
    assert restore_calls == 1
    assert captured_state["value"]["custody_rejected"] is True
    assert emitted_pages[0]["items"][2] == expected_table
    assert result.pages[0].items[2].table_evidence is None


def test_zero_selection_keeps_exact_p03_closure_and_does_not_reenter_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, _transaction, baseline, _baseline_ir = _projected_predecessor()
    summary = {
        "schema_version": "1.0",
        "policy_id": source_text_alignment.SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        "source_sha256": baseline["document"]["sha256"],
        "status": "unchanged",
        "considered_count": 0,
        "selected_count": 0,
        "unchanged_count": 0,
        "unresolved_count": 0,
        "selections": [],
        "concerns": [],
        "elapsed_ms": 0.0,
    }

    def unchanged(
        pages: list[dict[str, Any]], _evidence: Any
    ) -> SimpleNamespace:
        assert not custody.has_literal_table_marker({"pages": pages})
        return SimpleNamespace(to_dict=lambda: deepcopy(summary))

    monkeypatch.setattr(source_text_alignment, "align_pages_to_source", unchanged)
    from app.services import ir as ir_service

    monkeypatch.setattr(
        ir_service,
        "round_trip_document",
        lambda *_args, **_kwargs: pytest.fail(
            "zero-selection terminal alignment re-entered P03 layout"
        ),
    )
    actual = pipeline._apply_terminal_source_text_alignment(
        baseline,
        _terminal_settings(),
        source_pdf_bytes=fixture.source_pdf_bytes,
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256=baseline["document"]["sha256"],
        input_kind=InputKind.PDF,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
    )

    assert actual["processing"]["source_text_alignment"] == summary
    assert strict_json_bytes(_without_source_alignment_outcome(actual)) == (
        strict_json_bytes(baseline)
    )
    assert running_regions.running_region_replay_identity(actual) == (
        running_regions.running_region_replay_identity(baseline)
    )
    assert not custody.has_literal_table_marker(actual)


def test_selected_alignment_replays_running_regions_before_table_rebind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, _transaction, baseline, _baseline_ir = _projected_predecessor()
    original_text = "Body paragraph unique to this physical page."
    selected_text = "Body paragraph aligned to source."

    def selected(
        pages: list[dict[str, Any]], _evidence: Any
    ) -> SimpleNamespace:
        assert not custody.has_literal_table_marker({"pages": pages})
        owner = next(
            item for item in pages[0]["items"] if item["id"] == "p1-i2"
        )
        owner["value"] = selected_text
        owner["md"] = selected_text
        summary = {
            "schema_version": "1.0",
            "policy_id": source_text_alignment.SOURCE_TEXT_ALIGNMENT_POLICY_ID,
            "source_sha256": baseline["document"]["sha256"],
            "status": "selected",
            "considered_count": 1,
            "selected_count": 1,
            "unchanged_count": 0,
            "unresolved_count": 0,
            "selections": [
                {
                    "id": "alignment-p04-p03-boundary",
                    "page_index": 1,
                    "owner_id": "p1-i2",
                    "owner_type": "text",
                    "owner_bbox": deepcopy(owner["bbox"]),
                    "original_text": original_text,
                    "selected_text": selected_text,
                    "selected_source": "native",
                    "source_line_ids": [],
                    "source_character_ids": [],
                    "type1_mapping_ids": [],
                    "source_roles": [],
                    "method": "source_text_alignment",
                    "checks": {},
                    "terminal_reason": "selected",
                    "rejected_ocr_alternative": None,
                }
            ],
            "concerns": [],
            "elapsed_ms": 0.0,
        }
        return SimpleNamespace(to_dict=lambda: summary)

    monkeypatch.setattr(source_text_alignment, "align_pages_to_source", selected)
    monkeypatch.setattr(
        pipeline,
        "_apply_shared_ir_compatibility_projection",
        lambda *_args, **_kwargs: pytest.fail(
            "terminal alignment restarted the initial P03 pipeline"
        ),
    )
    actual = pipeline._apply_terminal_source_text_alignment(
        baseline,
        _terminal_settings(),
        source_pdf_bytes=fixture.source_pdf_bytes,
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256=baseline["document"]["sha256"],
        input_kind=InputKind.PDF,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
    )

    owner = next(
        item for item in actual["pages"][0]["items"] if item["id"] == "p1-i2"
    )
    assert owner["value"] == selected_text
    assert running_regions.running_region_replay_identity(actual) == (
        running_regions.running_region_replay_identity(baseline)
    )
    assert actual["pages"][0]["page_identity"] == baseline["pages"][0][
        "page_identity"
    ]
    assert actual["warnings"] == baseline["warnings"]
    assert not custody.has_literal_table_marker(actual)


@pytest.mark.parametrize("failure_stage", ("alignment", "running_replay"))
def test_terminal_p03_failure_is_closed_once_and_preserves_predecessor_closure(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    fixture, _transaction, baseline, _baseline_ir = _projected_predecessor()

    def mutate_then_raise(
        pages: list[dict[str, Any]], _evidence: Any
    ) -> SimpleNamespace:
        pages[0]["items"][0]["value"] = "partial mutation"
        raise RuntimeError("injected terminal alignment failure")

    if failure_stage == "alignment":
        monkeypatch.setattr(
            source_text_alignment,
            "align_pages_to_source",
            mutate_then_raise,
        )
    else:
        original_text = "Body paragraph unique to this physical page."
        selected_text = "Body paragraph aligned to source."

        def select_for_replay(
            pages: list[dict[str, Any]], _evidence: Any
        ) -> SimpleNamespace:
            owner = next(
                item for item in pages[0]["items"] if item["id"] == "p1-i2"
            )
            owner["value"] = selected_text
            owner["md"] = selected_text
            return SimpleNamespace(
                to_dict=lambda: {
                    "schema_version": "1.0",
                    "policy_id": (
                        source_text_alignment.SOURCE_TEXT_ALIGNMENT_POLICY_ID
                    ),
                    "source_sha256": baseline["document"]["sha256"],
                    "status": "selected",
                    "considered_count": 1,
                    "selected_count": 1,
                    "unchanged_count": 0,
                    "unresolved_count": 0,
                    "selections": [
                        {
                            "id": "alignment-before-replay-failure",
                            "page_index": 1,
                            "owner_id": "p1-i2",
                            "owner_type": "text",
                            "owner_bbox": deepcopy(owner["bbox"]),
                            "original_text": original_text,
                            "selected_text": selected_text,
                            "selected_source": "native",
                            "source_line_ids": [],
                            "source_character_ids": [],
                            "type1_mapping_ids": [],
                            "source_roles": [],
                            "method": "source_text_alignment",
                            "checks": {},
                            "terminal_reason": "selected",
                            "rejected_ocr_alternative": None,
                        }
                    ],
                    "concerns": [],
                    "elapsed_ms": 0.0,
                }
            )

        monkeypatch.setattr(
            source_text_alignment,
            "align_pages_to_source",
            select_for_replay,
        )
        monkeypatch.setattr(
            running_regions,
            "replay_running_regions",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected running replay failure")
            ),
        )
    monkeypatch.setattr(
        pipeline,
        "_apply_shared_ir_compatibility_projection",
        lambda *_args, **_kwargs: pytest.fail(
            "terminal failure restarted the predecessor P03 pipeline"
        ),
    )
    actual = pipeline._apply_terminal_source_text_alignment(
        baseline,
        _terminal_settings(),
        source_pdf_bytes=fixture.source_pdf_bytes,
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256=baseline["document"]["sha256"],
        input_kind=InputKind.PDF,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
    )

    terminal = actual["processing"]["source_text_alignment"]
    assert terminal["status"] == "unavailable"
    assert terminal["concerns"] == [
        {
            "status": "unresolved",
            "reason": "source_alignment_failed_closed",
            "error_type": "RuntimeError",
        }
    ]
    assert strict_json_bytes(_without_source_alignment_outcome(actual)) == (
        strict_json_bytes(baseline)
    )
    assert running_regions.running_region_replay_identity(actual) == (
        running_regions.running_region_replay_identity(baseline)
    )
    assert not custody.has_literal_table_marker(actual)


def test_valid_failed_closed_terminal_p03_outcome_can_receive_table_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()

    def fail_alignment(
        pages: list[dict[str, Any]], _evidence: Any
    ) -> SimpleNamespace:
        assert not custody.has_literal_table_marker({"pages": pages})
        pages[0]["items"][0]["value"] = "partial mutation"
        raise RuntimeError("injected terminal alignment failure")

    monkeypatch.setattr(
        source_text_alignment,
        "align_pages_to_source",
        fail_alignment,
    )
    terminal = pipeline._apply_terminal_source_text_alignment(
        baseline,
        _terminal_settings(),
        source_pdf_bytes=fixture.source_pdf_bytes,
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256=baseline["document"]["sha256"],
        input_kind=InputKind.PDF,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
    )
    now = time.perf_counter()
    result = pipeline._apply_terminal_table_authority(
        terminal,
        baseline_ir,
        transaction,
        _terminal_settings(),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state={},
    )

    assert custody.has_literal_table_marker(result)
    assert strict_json_bytes(_non_table_public_closure(result)) == (
        strict_json_bytes(_non_table_public_closure(terminal))
    )
    assert result["processing"]["source_text_alignment"] == terminal[
        "processing"
    ]["source_text_alignment"]
    assert result["warnings"] == terminal["warnings"]
    assert running_regions.running_region_replay_identity(result) == (
        running_regions.running_region_replay_identity(terminal)
    )
    assert strict_json_bytes(_non_table_canonical_blocks(result)) == (
        strict_json_bytes(_non_table_canonical_blocks(terminal))
    )


def test_raw_only_and_merged_assertion_order_changes_custody_not_canonical() -> None:
    first_raw = _base_raw_graph()
    second_raw = _base_raw_graph()
    second_raw["groups"][0]["children"].reverse()

    first_document, first_raw, first_ir = _opaque_fixture(raw_graph=first_raw)
    second_document, second_raw, second_ir = _opaque_fixture(raw_graph=second_raw)
    first_canonical, first_sidecar, _first_detached = _detach_restore_project(
        first_document,
        first_raw,
        first_ir,
    )
    second_canonical, second_sidecar, _second_detached = _detach_restore_project(
        second_document,
        second_raw,
        second_ir,
    )

    assert strict_json_bytes(first_canonical) == strict_json_bytes(
        second_canonical
    )
    assert first_sidecar["records_sha256"] != second_sidecar["records_sha256"]
    assert strict_json_bytes(first_sidecar["records"]) != strict_json_bytes(
        second_sidecar["records"]
    )
    assert "merged_edge" in {
        record["normalization_outcome"] for record in first_sidecar["records"]
    }


def test_mutation_after_raw_closure_capture_rejects_custody_without_canonical_drift() -> None:
    document, raw_graph, raw_ir = _opaque_fixture(raw_graph=_base_raw_graph())
    clean_ir = build_document_ir(document)
    canonical_before = build_canonical_presentation(clean_ir).model_dump(
        mode="json",
        exclude_none=True,
    )
    detached_ir, detached = custody.detach_opaque_group_edges(raw_ir, raw_graph)
    restored_ir = custody.restore_diagnostic_group_edges(detached_ir, detached)

    raw_graph["groups"][0]["children"].reverse()
    canonical_after = build_canonical_presentation(clean_ir).model_dump(
        mode="json",
        exclude_none=True,
    )
    assert strict_json_bytes(canonical_after) == strict_json_bytes(
        canonical_before
    )
    with pytest.raises(
        custody.OpaqueGroupCustodyIntegrityError,
        match="raw closure changed after capture",
    ):
        custody.seal_diagnostic_custody(
            document,
            restored_ir,
            raw_graph=raw_graph,
            detached_custody=detached,
            deadline=time.perf_counter() + 1.0,
        )


def test_target_table_composes_only_closed_p03_caption_delta_onto_new_cells() -> None:
    baseline, predecessor, candidate, public_item = (
        _target_caption_overlay_blocks()
    )

    composed = pipeline._compose_terminal_target_p03_overlay(
        baseline,
        predecessor,
        candidate,
        public_item,
    )

    caption_id = public_item["caption_ids"][0]
    assert composed["contributing_element_ids"] == [
        candidate["primary_element_id"],
        caption_id,
        candidate["contributing_element_ids"][1],
    ]
    assert predecessor["contributing_element_ids"][1] not in (
        composed["contributing_element_ids"]
    )
    assert set(composed["relationship_ids"]) == {
        candidate["relationship_ids"][0],
        *(
            set(baseline["relationship_ids"])
            - set(predecessor["relationship_ids"])
        ),
    }
    assert composed["markdown"] == (
        "Source caption\n\n" + candidate["markdown"]
    )
    assert composed["text"] == "Source caption\n\nnew"
    assert composed["excluded_contributions"] == (
        baseline["excluded_contributions"]
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown_contributor",
        "missing_scalar_suffix",
        "duplicate_candidate_contributor",
        "unknown_relationship",
        "unknown_exclusion_relationship",
    ),
)
def test_target_table_rejects_unknown_or_inconsistent_p03_delta(
    mutation: str,
) -> None:
    baseline, predecessor, candidate, public_item = (
        _target_caption_overlay_blocks()
    )
    if mutation == "unknown_contributor":
        baseline["contributing_element_ids"].insert(
            1,
            "el-00000000000000000009",
        )
    elif mutation == "missing_scalar_suffix":
        baseline["markdown"] = "Source caption\n\nnot the predecessor"
    elif mutation == "duplicate_candidate_contributor":
        candidate["contributing_element_ids"].append(
            candidate["contributing_element_ids"][-1]
        )
    elif mutation == "unknown_relationship":
        baseline["relationship_ids"].append(
            "rel-ffffffffffffffffffff"
        )
        baseline["relationship_ids"].sort()
    elif mutation == "unknown_exclusion_relationship":
        baseline["excluded_contributions"][0]["relationship_ids"] = [
            "rel-ffffffffffffffffffff"
        ]
    else:  # pragma: no cover - the parameter list is closed above.
        raise AssertionError(mutation)

    with pytest.raises(ValueError, match="terminal table canonical"):
        pipeline._compose_terminal_target_p03_overlay(
            baseline,
            predecessor,
            candidate,
            public_item,
        )


def test_terminal_no_raw_canonical_keeps_every_non_table_block_and_view_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _boundary_fixture()
    pages = deepcopy(fixture.marked["pages"])
    transaction = _detach(pages)
    predecessor = deepcopy(fixture.predecessor)
    predecessor["pages"] = pages
    baseline = pipeline._apply_shared_ir_compatibility_projection(
        predecessor,
        _p03_settings(table_enabled=True),
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
    )
    baseline_ir = build_document_ir(deepcopy(baseline), raw_graph=fixture.raw_graph)
    state: dict[str, Any] = {}
    now = time.perf_counter()
    canonical_calls: list[dict[str, Any]] = []
    original_builder = presentation.build_canonical_presentation

    def canonical_spy(
        authoritative_ir: DocumentIR,
    ) -> Any:
        projected = original_builder(authoritative_ir)
        inert_relationships = [
            relationship
            for relationship in authoritative_ir.relationships
            if relationship.metadata.get("canonical_presentation_inert") is True
        ]
        canonical_calls.append(
            {
                "canonical": projected.model_dump(
                    mode="json",
                    exclude_none=True,
                ),
                "inert_ids": {
                    relationship.id for relationship in inert_relationships
                },
                "relationship_ids": {
                    relationship.id
                    for relationship in authoritative_ir.relationships
                },
                "element_ids": {
                    element.id for element in authoritative_ir.elements
                },
                "relationship_endpoints": {
                    endpoint_id
                    for relationship in authoritative_ir.relationships
                    for endpoint_id in (
                        relationship.source_id,
                        relationship.target_id,
                    )
                },
            }
        )
        return projected

    monkeypatch.setattr(presentation, "build_canonical_presentation", canonical_spy)

    result = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert canonical_calls
    diagnostic_relationship_ids = {
        record["relationship_id"]
        for record in result["canonical_source_custody"]["records"]
    }
    diagnostic_group_ids = {
        record["group_element_id"]
        for record in result["canonical_source_custody"]["records"]
    }
    assert all(call["inert_ids"] == set() for call in canonical_calls)
    assert all(
        diagnostic_relationship_ids.isdisjoint(call["relationship_ids"])
        for call in canonical_calls
    )
    assert all(
        diagnostic_group_ids.isdisjoint(call["element_ids"])
        for call in canonical_calls
    )
    assert all(
        diagnostic_group_ids.isdisjoint(call["relationship_endpoints"])
        for call in canonical_calls
    )
    assert custody.has_literal_table_marker(result)
    target_id = next(
        record[3] for record in transaction if record[3] == TABLE_ID
    )
    result_target = next(
        block
        for page in result["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if next(
            item.get("id")
            for item, candidate_block in zip(
                result["pages"][page["page_index"] - 1]["items"],
                page["blocks"],
                strict=True,
            )
            if candidate_block is block
        )
        == target_id
    )
    raw_target = next(
        block
        for page, public_page in zip(
            canonical_calls[0]["canonical"]["pages"],
            result["pages"],
            strict=True,
        )
        for block, item in zip(page["blocks"], public_page["items"], strict=True)
        if item.get("id") == target_id
    )
    assert strict_json_bytes(result_target) == strict_json_bytes(raw_target)
    assert state.get("timed_out") is not True
    assert state.get("custody_rejected") is not True
    assert strict_json_bytes(_non_table_public_closure(result)) == strict_json_bytes(
        _non_table_public_closure(baseline)
    )
    assert strict_json_bytes(_non_table_canonical_blocks(result)) == (
        strict_json_bytes(_non_table_canonical_blocks(baseline))
    )
    # The target block's source-supported `<th scope=...>` changes full/body
    # bytes.  Those affected views are independently reconstructed from the
    # final spliced blocks; unaffected header/footer views stay byte-exact.
    canonical = result["canonical_presentation"]
    page = canonical["pages"][0]
    assert page["full"] == _render_canonical_view(page["blocks"])
    assert page["body"] == _render_canonical_view(
        [block for block in page["blocks"] if block["scope"] == "body"]
    )
    assert canonical["full"] == _render_canonical_view(page["blocks"])
    assert canonical["body"] == _render_canonical_view(
        [block for block in page["blocks"] if block["scope"] == "body"]
    )
    for view in ("header", "footer"):
        assert strict_json_bytes(result["canonical_presentation"][view]) == (
            strict_json_bytes(baseline["canonical_presentation"][view])
        )
        assert strict_json_bytes(
            result["canonical_presentation"]["pages"][0][view]
        ) == strict_json_bytes(
            baseline["canonical_presentation"]["pages"][0][view]
        )


def test_structural_failure_table_in_raw_group_round_trips_without_authority() -> None:
    colliding_table = _raw_table(
        1,
        2,
        [
            _raw_cell(
                0,
                0,
                "wide source cell",
                col_span=2,
                column_header=True,
            ),
            _raw_cell(0, 1, "colliding source cell"),
        ],
    )
    fixture = _boundary_fixture(raw_table_override=colliding_table)
    fixture, transaction, baseline, baseline_ir = _projected_predecessor(
        fixture
    )
    state: dict[str, Any] = {}
    now = time.perf_counter()
    result = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    target = next(
        item
        for page in result["pages"]
        for item in page["items"]
        if item.get("id") == TABLE_ID
    )
    predecessor_target = next(
        item
        for page in baseline["pages"]
        for item in page["items"]
        if item.get("id") == TABLE_ID
    )
    assert target["table_evidence"]["status"] == "structural_failure"
    target_without_sidecar = deepcopy(target)
    target_without_sidecar.pop("table_evidence")
    assert strict_json_bytes(target_without_sidecar) == strict_json_bytes(
        predecessor_target
    )
    custody_relationship_ids = {
        record["relationship_id"]
        for record in result["canonical_source_custody"]["records"]
    }
    canonical_relationship_ids = {
        relationship_id
        for page in result["canonical_presentation"]["pages"]
        for block in page["blocks"]
        for relationship_id in block["relationship_ids"]
    }
    canonical_relationship_ids.update(
        relationship_id
        for page in result["canonical_presentation"]["pages"]
        for block in page["blocks"]
        for exclusion in block["excluded_contributions"]
        for relationship_id in exclusion["relationship_ids"]
    )
    assert custody_relationship_ids.isdisjoint(canonical_relationship_ids)

    validated = ParseResult.model_validate_json(strict_json_bytes(result))
    assert strict_json_bytes(
        validated.model_dump(mode="json", exclude_unset=True)
    ) == strict_json_bytes(result)
    assert state.get("custody_rejected") is not True
    assert state.get("timed_out") is not True


def test_terminal_diagnostic_id_collision_in_non_target_rolls_back_exactly() -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    now = time.perf_counter()
    successful = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state={},
    )
    diagnostic_relationship_id = successful["canonical_source_custody"][
        "records"
    ][0]["relationship_id"]

    colliding_baseline = deepcopy(baseline)
    non_target = next(
        block
        for page in colliding_baseline["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block["primary_element_type"] != "table"
    )
    non_target["relationship_ids"] = sorted(
        [*non_target["relationship_ids"], diagnostic_relationship_id]
    )
    non_target["excluded_contributions"].append(
        {
            "element_id": "el-preexisting-diagnostic-collision",
            "reason": "evidence_only_relationship",
            "relationship_ids": [diagnostic_relationship_id],
        }
    )
    _refresh_canonical_views(colliding_baseline)
    ParseResult.model_validate(deepcopy(colliding_baseline))

    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        colliding_baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(actual) == strict_json_bytes(colliding_baseline)
    assert state.get("custody_rejected") is True
    assert state.get("timed_out") is not True
    assert "canonical_source_custody" not in actual


def test_owned_terminal_custody_projection_matches_prior_bytes_and_has_no_alias(
) -> None:
    baseline_ir, authoritative_ir, transaction = (
        _terminal_custody_ir_inputs()
    )
    baseline_before = strict_json_bytes(baseline_ir.model_dump(mode="json"))
    authoritative_before = strict_json_bytes(
        authoritative_ir.model_dump(mode="json")
    )
    transaction_before = strict_json_bytes(transaction)

    # Exact migration oracle for the previous copy -> mutate -> dump ->
    # validate implementation. This stays test-only and proves that the
    # private owned-JSON path changes allocation, not authority or bytes.
    target_ids = {record[3] for record in transaction}
    authoritative_by_public_id = {
        legacy.get("id"): element
        for element in authoritative_ir.elements
        if isinstance(
            (legacy := element.properties.get("legacy_item")),
            Mapping,
        )
        and isinstance(legacy.get("id"), str)
    }
    prior_working = baseline_ir.model_copy(deep=True)
    prior_rebound_ids: set[str] = set()
    for element in prior_working.elements:
        legacy = element.properties.get("legacy_item")
        public_id = legacy.get("id") if isinstance(legacy, Mapping) else None
        if public_id not in target_ids:
            continue
        authoritative = authoritative_by_public_id[public_id]
        assert authoritative.id == element.id
        element.type = authoritative.type
        element.value = deepcopy(authoritative.value)
        element.markdown = authoritative.markdown
        element.presentation_role = authoritative.presentation_role
        retained_properties = {
            key: deepcopy(value)
            for key, value in element.properties.items()
            if key != "legacy_item"
        }
        retained_properties["legacy_item"] = deepcopy(
            authoritative.properties.get("legacy_item")
        )
        element.properties = retained_properties
        prior_rebound_ids.add(public_id)
    assert prior_rebound_ids == target_ids
    expected = DocumentIR.model_validate(
        prior_working.model_dump(mode="json")
    )

    observed = pipeline._rebind_terminal_table_custody_ir(
        baseline_ir,
        authoritative_ir,
        transaction,
    )
    expected_bytes = strict_json_bytes(expected.model_dump(mode="json"))
    observed_bytes = strict_json_bytes(observed.model_dump(mode="json"))

    assert observed_bytes == expected_bytes
    assert hashlib.sha256(observed_bytes).hexdigest() == hashlib.sha256(
        expected_bytes
    ).hexdigest()
    assert strict_json_bytes(baseline_ir.model_dump(mode="json")) == (
        baseline_before
    )
    assert strict_json_bytes(authoritative_ir.model_dump(mode="json")) == (
        authoritative_before
    )
    assert strict_json_bytes(transaction) == transaction_before

    observed.elements[0].properties["output_mutation"] = {"value": [1]}
    assert strict_json_bytes(baseline_ir.model_dump(mode="json")) == (
        baseline_before
    )
    assert strict_json_bytes(authoritative_ir.model_dump(mode="json")) == (
        authoritative_before
    )
    output_after_own_mutation = strict_json_bytes(
        observed.model_dump(mode="json")
    )
    baseline_ir.elements[0].properties["baseline_mutation"] = [2]
    authoritative_ir.elements[0].properties["authority_mutation"] = [3]
    transaction[0][5]["transaction_mutation"] = [4]
    assert strict_json_bytes(observed.model_dump(mode="json")) == (
        output_after_own_mutation
    )


def test_terminal_custody_rebind_uses_one_validation_and_no_model_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_ir, authoritative_ir, transaction = (
        _terminal_custody_ir_inputs()
    )
    original_validate = DocumentIR.model_validate
    validation_calls = 0

    def counted_validate(
        _cls: type[DocumentIR],
        value: Any,
        *args: Any,
        **kwargs: Any,
    ) -> DocumentIR:
        nonlocal validation_calls
        validation_calls += 1
        return original_validate(value, *args, **kwargs)

    def forbidden_model_copy(
        _self: DocumentIR,
        *_args: Any,
        **_kwargs: Any,
    ) -> DocumentIR:
        pytest.fail("terminal custody rebind repeated the complete IR copy")

    monkeypatch.setattr(
        DocumentIR,
        "model_validate",
        classmethod(counted_validate),
    )
    monkeypatch.setattr(DocumentIR, "model_copy", forbidden_model_copy)

    observed = pipeline._rebind_terminal_table_custody_ir(
        baseline_ir,
        authoritative_ir,
        transaction,
    )

    assert isinstance(observed, DocumentIR)
    assert validation_calls == 1


@pytest.mark.parametrize(
    "attack",
    ("baseline_type", "authority_type", "transaction_type", "duplicate"),
)
def test_owned_terminal_custody_projection_rejects_untrusted_shapes(
    attack: str,
) -> None:
    baseline_ir, authoritative_ir, transaction = (
        _terminal_custody_ir_inputs()
    )
    baseline: Any = baseline_ir
    authority: Any = authoritative_ir
    held: Any = transaction
    if attack == "baseline_type":
        baseline = baseline_ir.model_dump(mode="json")
    elif attack == "authority_type":
        authority = authoritative_ir.model_dump(mode="json")
    elif attack == "transaction_type":
        held = list(transaction)
    else:
        held = (*transaction, transaction[0])

    with pytest.raises(ValueError, match="terminal table custody"):
        pipeline._owned_terminal_table_custody_ir_projection(
            baseline,
            authority,
            held,
        )


def test_terminal_presentation_receives_same_authoritative_ir_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    original_rebind = pipeline._rebind_terminal_table_custody_ir
    original_builder = presentation.build_canonical_presentation
    authoritative_inputs: list[DocumentIR] = []
    presentation_inputs: list[DocumentIR] = []

    def rebind_spy(
        predecessor: DocumentIR,
        authoritative: DocumentIR,
        held: tuple[Any, ...],
    ) -> DocumentIR:
        authoritative_inputs.append(authoritative)
        return original_rebind(predecessor, authoritative, held)

    def presentation_spy(ir: DocumentIR) -> Any:
        if not presentation_inputs:
            assert authoritative_inputs
            assert ir is authoritative_inputs[0]
            before = strict_json_bytes(ir.model_dump(mode="json"))
            projected = original_builder(ir)
            assert strict_json_bytes(ir.model_dump(mode="json")) == before
        else:
            projected = original_builder(ir)
        presentation_inputs.append(ir)
        return projected

    monkeypatch.setattr(
        pipeline,
        "_rebind_terminal_table_custody_ir",
        rebind_spy,
    )
    monkeypatch.setattr(
        presentation,
        "build_canonical_presentation",
        presentation_spy,
    )
    now = time.perf_counter()
    result = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state={},
    )

    assert authoritative_inputs
    assert presentation_inputs
    assert custody.has_literal_table_marker(result)


def test_hostile_authoritative_value_fails_closed_to_exact_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    baseline_before = strict_json_bytes(baseline)
    target_ids = {record[3] for record in transaction}
    original_ir_builder = build_document_ir

    def hostile_ir_builder(*args: Any, **kwargs: Any) -> DocumentIR:
        authoritative = original_ir_builder(*args, **kwargs)
        target = next(
            element
            for element in authoritative.elements
            if isinstance(
                (legacy := element.properties.get("legacy_item")),
                Mapping,
            )
            and legacy.get("id") in target_ids
        )
        target.value = object()
        return authoritative

    monkeypatch.setattr(
        "app.services.ir.build_document_ir",
        hostile_ir_builder,
    )
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(actual) == baseline_before
    assert strict_json_bytes(baseline) == baseline_before
    assert state.get("custody_rejected") is True
    assert state.get("timed_out") is not True


@pytest.mark.parametrize(
    "authority_tamper",
    ("raw_only_group_element", "diagnostic_id_rebound"),
)
def test_terminal_diagnostic_authority_injection_rolls_back_exactly(
    monkeypatch: pytest.MonkeyPatch,
    authority_tamper: str,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    original_rebind = pipeline._rebind_terminal_table_custody_ir

    def tampered_rebind(
        predecessor_ir: DocumentIR,
        authoritative_ir: DocumentIR,
        held_transaction: tuple[Any, ...],
    ) -> DocumentIR:
        custody_ir = original_rebind(
            predecessor_ir,
            authoritative_ir,
            held_transaction,
        )
        raw_group_ids = {
            element.id
            for element in custody_ir.elements
            if element.type in {"group", "list"}
            and element.properties.get("normalization_origin")
            == "docling_reference_graph"
        }
        diagnostic_relationship = next(
            relationship
            for relationship in custody_ir.relationships
            if relationship.source_id in raw_group_ids
            or relationship.target_id in raw_group_ids
        )
        if authority_tamper == "raw_only_group_element":
            raw_group = deepcopy(
                next(
                    element
                    for element in custody_ir.elements
                    if element.id in raw_group_ids
                )
            )
            authoritative_ir.elements.append(raw_group)
            page = next(
                value
                for value in authoritative_ir.pages
                if value.id == raw_group.page_id
            )
            page.element_ids.append(raw_group.id)
        elif authority_tamper == "diagnostic_id_rebound":
            public_element_ids = {
                element.id for element in authoritative_ir.elements
            }
            rebound = deepcopy(
                next(
                    relationship
                    for relationship in authoritative_ir.relationships
                    if relationship.source_id in public_element_ids
                    and relationship.target_id in public_element_ids
                )
            )
            rebound.id = diagnostic_relationship.id
            authoritative_ir.relationships.append(rebound)
        else:  # pragma: no cover - the parameter list is closed above.
            raise AssertionError(authority_tamper)
        return custody_ir

    monkeypatch.setattr(
        pipeline,
        "_rebind_terminal_table_custody_ir",
        tampered_rebind,
    )
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(actual) == strict_json_bytes(baseline)
    assert state.get("custody_rejected") is True
    assert state.get("timed_out") is not True
    assert "canonical_source_custody" not in actual


@pytest.mark.parametrize(
    "failure",
    (
        custody.OpaqueGroupCustodyIntegrityError("injected integrity failure"),
        custody.OpaqueGroupCustodyResourceError("injected resource failure"),
        custody.OpaqueGroupCustodyTimeoutError("injected timeout failure"),
    ),
    ids=("integrity", "resource", "timeout"),
)
def test_late_table_authority_failure_returns_exact_p03_baseline_without_reentry(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    fixture = _boundary_fixture()
    pages = deepcopy(fixture.marked["pages"])
    transaction = _detach(pages)
    baseline = deepcopy(fixture.predecessor)
    baseline["pages"] = pages
    baseline_ir = build_document_ir(baseline, raw_graph=fixture.raw_graph)

    monkeypatch.setattr(
        custody,
        "seal_diagnostic_custody",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_shared_ir_compatibility_projection",
        lambda *_args, **_kwargs: pytest.fail("late rollback reran shared P03"),
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_terminal_source_text_alignment",
        lambda *_args, **_kwargs: pytest.fail(
            "late rollback reran terminal source alignment"
        ),
    )
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state={},
    )

    assert strict_json_bytes(actual) == strict_json_bytes(baseline)


def test_terminal_presentation_timeout_is_classified_and_rolls_back_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    monkeypatch.setattr(
        presentation,
        "build_canonical_presentation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TimeoutError("injected presentation timeout")
        ),
    )
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(actual) == strict_json_bytes(baseline)
    assert state.get("timed_out") is True
    assert state.get("custody_rejected") is not True
    assert not custody.has_literal_table_marker(actual)
    assert "canonical_source_custody" not in actual


def test_elapsed_document_deadline_after_presentation_rolls_back_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    original_builder = presentation.build_canonical_presentation
    builder_calls = 0

    def presentation_spy(ir: DocumentIR) -> Any:
        nonlocal builder_calls
        builder_calls += 1
        return original_builder(ir)

    monotonic_base = time.perf_counter()

    def deadline_clock() -> float:
        return (
            monotonic_base
            if builder_calls == 0
            else monotonic_base + 10.0
        )

    monkeypatch.setattr(presentation, "build_canonical_presentation", presentation_spy)
    monkeypatch.setattr(
        pipeline,
        "time",
        SimpleNamespace(perf_counter=deadline_clock),
    )
    state: dict[str, Any] = {}
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=monotonic_base + 5.0,
        page_deadlines={1: monotonic_base + 0.5},
        state=state,
    )

    assert builder_calls >= 1
    assert strict_json_bytes(actual) == strict_json_bytes(baseline)
    assert state.get("timed_out") is True
    assert state.get("custody_rejected") is not True
    assert not custody.has_literal_table_marker(actual)
    assert "canonical_source_custody" not in actual


@pytest.mark.parametrize(
    "tamper",
    (
        "missing_id",
        "extra_id",
        "duplicate_ids",
        "non_tuple_ids",
        "record_id_mismatch",
        "already_inert",
    ),
)
def test_terminal_seal_output_tampering_rolls_back_without_partial_authority(
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    original_seal = custody.seal_diagnostic_custody

    def tampered_seal(
        document: Mapping[str, Any],
        custody_ir: DocumentIR,
        **kwargs: Any,
    ) -> tuple[Any, Any]:
        sidecar, relationship_ids = original_seal(
            document,
            custody_ir,
            **kwargs,
        )
        assert relationship_ids
        if tamper == "missing_id":
            return sidecar, relationship_ids[:-1]
        if tamper == "extra_id":
            return sidecar, (*relationship_ids, "rel-ffffffffffffffffffff")
        if tamper == "duplicate_ids":
            return sidecar, (*relationship_ids, relationship_ids[0])
        if tamper == "non_tuple_ids":
            return sidecar, list(relationship_ids)
        if tamper == "record_id_mismatch":
            return sidecar, (
                "rel-ffffffffffffffffffff",
                *relationship_ids[1:],
            )
        if tamper == "already_inert":
            relationship = next(
                value
                for value in custody_ir.relationships
                if value.id == relationship_ids[0]
            )
            relationship.metadata["canonical_presentation_inert"] = True
            return sidecar, relationship_ids
        raise AssertionError(tamper)

    monkeypatch.setattr(custody, "seal_diagnostic_custody", tampered_seal)
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(actual) == strict_json_bytes(baseline)
    assert state.get("custody_rejected") is True
    assert not custody.has_literal_table_marker(actual)
    assert "canonical_source_custody" not in actual


def test_target_scoped_custody_ignores_disconnected_malformed_raw_group() -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    raw_graph = deepcopy(fixture.raw_graph)
    raw_graph["groups"].append(
        {
            "self_ref": "#/groups/1",
            "label": "group",
            "children": [{}],
        }
    )
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert custody.has_literal_table_marker(actual)
    assert "canonical_source_custody" in actual
    assert state.get("custody_rejected") is not True
    assert state.get("timed_out") is not True


def test_target_scoped_custody_rejects_selected_malformed_raw_group_exactly() -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    raw_graph = deepcopy(fixture.raw_graph)
    raw_graph["groups"][0]["children"] = [{}]
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(actual) == strict_json_bytes(baseline)
    assert state.get("custody_rejected") is True
    assert state.get("timed_out") is not True
    assert not custody.has_literal_table_marker(actual)
    assert "canonical_source_custody" not in actual


def test_empty_target_scope_captures_no_raw_graph_state() -> None:
    _fixture, _transaction, _baseline, baseline_ir = _projected_predecessor()

    class _NoRawAccess(Mapping[str, Any]):
        def __getitem__(self, key: str) -> Any:
            pytest.fail(f"empty target scope read raw key {key!r}")

        def __iter__(self) -> Any:
            pytest.fail("empty target scope iterated raw graph")

        def __len__(self) -> int:
            pytest.fail("empty target scope measured raw graph")

        def get(self, key: str, default: Any = None) -> Any:
            pytest.fail(f"empty target scope read raw key {key!r}")

    captured = custody.capture_opaque_group_edges(
        baseline_ir,
        _NoRawAccess(),
        target_element_ids=frozenset(),
    )

    assert captured.detached == ()
    assert captured.raw_closure.definitions == ()
    assert captured.raw_closure.assertions == ()


def test_target_scoped_custody_ignores_disconnected_alternative_group() -> None:
    fixture, transaction, baseline, _baseline_ir = _projected_predecessor()
    raw_graph = deepcopy(fixture.raw_graph)
    raw_graph["groups"].extend(
        [
            {
                "self_ref": "#/groups/1",
                "label": "group",
                "alternatives": [{"$ref": "#/groups/2"}],
            },
            {
                "self_ref": "#/groups/2",
                "label": "group",
            },
        ]
    )
    augmented_ir = build_document_ir(
        baseline,
        raw_graph=raw_graph,
        native_texts=fixture.native_texts,
    )
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        augmented_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert custody.has_literal_table_marker(actual)
    assert actual["canonical_source_custody"]["record_count"] == 2
    assert state.get("custody_rejected") is not True
    assert state.get("timed_out") is not True


def test_target_scoped_custody_rejects_selected_alternative_group_exactly() -> None:
    fixture, transaction, baseline, _baseline_ir = _projected_predecessor()
    raw_graph = deepcopy(fixture.raw_graph)
    raw_graph["groups"][0].pop("children")
    raw_graph["groups"][0]["alternatives"] = [
        {"$ref": "#/tables/0"}
    ]
    raw_graph["tables"][0].pop("parent", None)
    augmented_ir = build_document_ir(
        baseline,
        raw_graph=raw_graph,
        native_texts=fixture.native_texts,
    )
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        augmented_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(actual) == strict_json_bytes(baseline)
    assert state.get("custody_rejected") is True
    assert state.get("timed_out") is not True
    assert not custody.has_literal_table_marker(actual)
    assert "canonical_source_custody" not in actual


def test_selected_duplicate_and_reciprocal_raw_assertions_are_all_retained() -> None:
    source_fixture = _boundary_fixture()
    raw_graph = deepcopy(source_fixture.raw_graph)
    raw_graph["groups"][0]["children"].append(
        {"$ref": "#/tables/0"}
    )
    fixture = _BoundaryFixture(
        marked=source_fixture.marked,
        predecessor=source_fixture.predecessor,
        raw_graph=raw_graph,
        native_texts=source_fixture.native_texts,
        source_pdf_bytes=source_fixture.source_pdf_bytes,
    )
    fixture, transaction, baseline, baseline_ir = _projected_predecessor(
        fixture
    )
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    records = actual["canonical_source_custody"]["records"]
    assert len(records) == 3
    assert len({record["relationship_id"] for record in records}) == 1
    assert {record["normalized_assertion_count"] for record in records} == {3}
    assert [
        record["relationship_field"] for record in records
    ].count("children") == 2
    assert [
        record["relationship_field"] for record in records
    ].count("parent") == 1
    assert [
        record["normalization_outcome"] for record in records
    ].count("normalized_edge") == 1
    assert [
        record["normalization_outcome"] for record in records
    ].count("merged_edge") == 2
    assert custody.has_literal_table_marker(actual)
    assert state.get("custody_rejected") is not True
    assert state.get("timed_out") is not True


def test_final_candidate_model_validation_failure_returns_exact_p03_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    original_validate = pipeline.ParseResult.model_validate
    candidate_attempts = 0

    def reject_marked_candidate(value: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal candidate_attempts
        if isinstance(value, Mapping) and custody.has_literal_table_marker(value):
            candidate_attempts += 1
            raise ValueError("injected final P04 model validation failure")
        return original_validate(value, *args, **kwargs)

    monkeypatch.setattr(
        pipeline.ParseResult,
        "model_validate",
        reject_marked_candidate,
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_shared_ir_compatibility_projection",
        lambda *_args, **_kwargs: pytest.fail(
            "final validation rollback reran shared P03"
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_terminal_source_text_alignment",
        lambda *_args, **_kwargs: pytest.fail(
            "final validation rollback reran terminal source alignment"
        ),
    )
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state={},
    )

    assert candidate_attempts == 1
    assert strict_json_bytes(actual) == strict_json_bytes(baseline)
