"""Generic source-owned and compact-OCR visual-label recovery contracts."""

from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest

from app.models import ParseResult
from app.services.layout import (
    _grounded_primary_visual_source_text,
    _grounded_proven_visual_owner_output,
)
from app.services.ocr import OCRLine
from app.services.ir import build_document_ir
from app.services.presentation import build_canonical_presentation
from app.services.serializer import to_markdown
from app.services.visual_source_text import (
    attach_visual_source_text,
    compact_visual_ocr_primary_evidence,
    compact_visual_overlay_lineage_sha256,
    owned_visual_source_lineage_sha256,
    recover_owned_visual_source_text,
    revalidate_compact_visual_ocr_primary_evidence,
)


def _bbox(x: float, y: float, width: float, height: float) -> dict[str, object]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": "pt",
    }


def _source_evidence(
    *,
    source_sha256: str,
    page_index: int,
    lines: list[tuple[str, str, dict[str, object], tuple[int, int, int, int]]],
) -> dict[str, object]:
    characters: list[dict[str, object]] = []
    source_lines: list[dict[str, object]] = []
    for line_id, text, bbox, fill in lines:
        character_ids: list[str] = []
        for character_index, character in enumerate(text):
            character_id = f"{line_id}-character-{character_index}"
            character_ids.append(character_id)
            characters.append(
                {
                    "id": character_id,
                    "page_index": page_index,
                    "raw_text": character,
                    "text": character,
                    "bbox": deepcopy(bbox),
                    "fill_rgba": fill,
                    "excluded_reason": None,
                }
            )
        source_lines.append(
            {
                "id": line_id,
                "page_index": page_index,
                "text": text,
                "raw_text": text,
                "bbox": deepcopy(bbox),
                "source_character_ids": character_ids,
            }
        )
    return {
        "usable": True,
        "source_sha256": source_sha256,
        "pages": [
            {
                "page_index": page_index,
                "page_width": 1000.0,
                "page_height": 1000.0,
                "unit": "pt",
                "characters": characters,
                "lines": source_lines,
            }
        ],
    }


def _project_native_visual_graph(
    owner: dict[str, object],
    source_children: list[dict[str, object]],
    *,
    owner_id: str = "native-visual-owner",
) -> list[dict[str, object]]:
    """Project the complete public contains graph used by the proof gate."""

    owner["id"] = owner_id
    contained: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []
    for index, child in enumerate(source_children):
        public_child_id = f"native-public-child-{index}"
        relationship_id = f"native-contains-{index}"
        contained.append(
            {
                "id": public_child_id,
                "type": "visual_text",
                "content_type": "visual_text",
                "page_index": child["page_index"],
                "value": child["text"],
                "md": child["text"],
                "bbox": deepcopy(child["bbox"]),
                "source": "native",
                "presentation_role": "subordinate",
                "contained_by": owner_id,
                "relationship_id": relationship_id,
                "relationship_type": "contains",
                "relationship_basis": "graph_and_geometry",
            }
        )
        relationships.append(
            {
                "id": relationship_id,
                "source_id": owner_id,
                "target_id": public_child_id,
                "type": "contains",
            }
        )
    owner.update(
        {
            "layout_visual_relationships_projected": True,
            "contains_ids": [child["id"] for child in contained],
            "contained_items": contained,
            "relationships": relationships,
        }
    )
    return contained


@pytest.mark.parametrize(
    ("source_sha256", "page_index", "owner", "child", "source_line", "expected"),
    (
        (
            "1" * 64,
            1,
            _bbox(18.0, 41.0, 132.0, 19.0),
            _bbox(29.0, 48.2, 105.0, 9.1),
            _bbox(29.4, 48.0, 103.8, 8.0),
            "SHARED LICENSE",
        ),
        (
            "e" * 64,
            7,
            _bbox(432.0, 311.0, 91.0, 15.0),
            _bbox(443.0, 318.4, 70.0, 8.2),
            # Independent extractors disagree at the edge by 0.6 pt.
            _bbox(443.4, 318.0, 69.1, 8.6),
            "PUBLIC RECORD",
        ),
    ),
    ids=("renamed-wide-page", "page-offset-narrow-page"),
)
def test_owned_native_visual_label_uses_graph_source_and_geometry(
    source_sha256: str,
    page_index: int,
    owner: dict[str, object],
    child: dict[str, object],
    source_line: dict[str, object],
    expected: str,
) -> None:
    item = {
        "type": "image",
        "content_type": "image",
        "region_role": "content_region",
        "bbox": owner,
    }
    children = [
        {
            "id": "#/texts/native-label",
            "text": expected.replace(" ", ""),
            "bbox": child,
            "page_index": page_index,
        }
    ]
    evidence = _source_evidence(
        source_sha256=source_sha256,
        page_index=page_index,
        lines=[("source-line-label", expected, source_line, (20, 40, 70, 255))],
    )

    recovered = recover_owned_visual_source_text(
        item,
        children,
        source_text_evidence=evidence,
        source_document_identity=source_sha256,
        page_index=page_index,
    )

    assert recovered is not None
    assert recovered["text"] == expected
    assert recovered["method"] == "pdf_source_line_owned_by_visual_child"
    assert recovered["source_line_ids"] == ["source-line-label"]
    projected = attach_visual_source_text(item, recovered, promote_primary=True)
    contained = _project_native_visual_graph(projected, children)
    primary, rejection = _grounded_primary_visual_source_text(
        projected,
        contained,
    )
    assert primary == expected
    assert rejection is None


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-child-geometry",
        "source-hash-conflict",
        "ambiguous-source-line",
        "outside-one-point-tolerance",
        "white-source-label",
        "independent-child-conflict",
        "punctuation-conflict",
        "uppercase-source-hash",
        "duplicate-character-id",
        "non-string-character-id",
        "glyph-text-conflict",
        "boolean-page-index",
        "invalid-page-dimensions",
        "missing-child-id",
        "duplicate-child-id",
    ),
)
def test_owned_native_visual_label_fails_closed_on_ambiguous_evidence(
    mutation: str,
) -> None:
    source_sha256 = "a" * 64
    owner = _bbox(80.0, 100.0, 120.0, 24.0)
    child = _bbox(91.0, 108.0, 83.0, 9.0)
    line_box = _bbox(91.3, 107.8, 82.4, 8.4)
    item = {
        "type": "image",
        "content_type": "image",
        "region_role": "content_region",
        "bbox": owner,
    }
    children = [
        {
            "id": "#/texts/label-a",
            "text": "AUDITCOPY",
            "bbox": child,
            "page_index": 3,
        }
    ]
    lines = [("line-a", "AUDIT COPY", line_box, (0, 0, 0, 255))]
    identity = source_sha256
    if mutation == "missing-child-geometry":
        children[0]["bbox"] = None
    elif mutation == "source-hash-conflict":
        identity = "b" * 64
    elif mutation == "ambiguous-source-line":
        lines.append(("line-b", "AUDIT COPY", deepcopy(line_box), (0, 0, 0, 255)))
    elif mutation == "outside-one-point-tolerance":
        lines[0] = ("line-a", "AUDIT COPY", _bbox(91.3, 108.0, 82.4, 17.1), (0, 0, 0, 255))
    elif mutation == "white-source-label":
        lines[0] = ("line-a", "AUDIT COPY", line_box, (255, 255, 255, 255))
    elif mutation == "independent-child-conflict":
        children.append(
            {
                "id": "#/texts/label-b",
                "text": "SECONDLABEL",
                "bbox": _bbox(92.0, 117.0, 77.0, 6.0),
                "page_index": 3,
            }
        )
    elif mutation == "punctuation-conflict":
        lines[0] = ("line-a", "AUDIT-COPY", line_box, (0, 0, 0, 255))
    elif mutation == "uppercase-source-hash":
        identity = "A" * 64
        source_sha256 = identity
    elif mutation == "missing-child-id":
        children[0].pop("id")
    elif mutation == "duplicate-child-id":
        children.append(deepcopy(children[0]))
    evidence = _source_evidence(
        source_sha256=source_sha256,
        page_index=3,
        lines=lines,
    )
    if mutation == "duplicate-character-id":
        character_ids = evidence["pages"][0]["lines"][0][
            "source_character_ids"
        ]
        character_ids.append(character_ids[0])
    elif mutation == "non-string-character-id":
        evidence["pages"][0]["lines"][0]["source_character_ids"][0] = {}
    elif mutation == "glyph-text-conflict":
        evidence["pages"][0]["characters"][0]["raw_text"] = "X"
    elif mutation == "boolean-page-index":
        evidence["pages"][0]["page_index"] = True
    elif mutation == "invalid-page-dimensions":
        evidence["pages"][0]["page_width"] = 0.0

    assert (
        recover_owned_visual_source_text(
            item,
            children,
            source_text_evidence=evidence,
            source_document_identity=identity,
            page_index=3,
        )
        is None
    )


def _compact_case(
    *,
    source_sha256: str,
    page_index: int,
    offset_x: float,
    offset_y: float,
    classification: str,
    first_text: str,
    second_text: str,
    owner_width: float = 92.0,
    owner_height: float = 72.0,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[OCRLine],
    list[dict[str, object]],
    dict[str, object],
    dict[str, object],
]:
    owner = _bbox(offset_x, offset_y, owner_width, owner_height)
    child_bbox = _bbox(
        offset_x + 3.0,
        offset_y + 3.0,
        owner_width - 8.0,
        9.0,
    )
    child_text = "q8888888888"
    item = {
        "type": "image",
        "content_type": "image",
        "region_role": "content_region",
        "bbox": owner,
    }
    children = [
        {
            "id": "#/texts/nonlexical-overlay",
            "text": child_text,
            "bbox": child_bbox,
            "page_index": page_index,
        }
    ]
    first_bbox = _bbox(offset_x + 21.0, offset_y + 38.0, 48.0, 7.0)
    second_bbox = _bbox(offset_x + 24.0, offset_y + 49.0, 42.0, 7.0)
    accepted = [
        OCRLine(
            text=first_text,
            bbox=first_bbox,
            confidence=0.97,
            word_count=len(first_text.split()),
            ocr_pass="standard",
        ),
        OCRLine(
            text=second_text,
            bbox=second_bbox,
            confidence=0.96,
            word_count=len(second_text.split()),
            ocr_pass="sparse",
        ),
    ]
    rejected = [
        {
            "text": first_text,
            "bbox": deepcopy(first_bbox),
            "confidence": 0.965,
            "word_count": len(first_text.split()),
            "ocr_pass": "sparse",
        },
        {
            "text": second_text,
            "bbox": deepcopy(second_bbox),
            "confidence": 0.955,
            "word_count": len(second_text.split()),
            "ocr_pass": "standard",
        },
    ]
    evidence = _source_evidence(
        source_sha256=source_sha256,
        page_index=page_index,
        lines=[
            (
                "line-overlay",
                child_text,
                _bbox(
                    offset_x + 3.3,
                    offset_y + 3.1,
                    owner_width - 8.7,
                    8.6,
                ),
                (255, 255, 255, 255),
            )
        ],
    )
    return (
        item,
        children,
        accepted,
        rejected,
        evidence,
        {"class_name": classification, "confidence": 0.98},
    )


@pytest.mark.parametrize(
    ("source_sha256", "page_index", "offset_x", "offset_y", "classification", "lines"),
    (
        ("2" * 64, 1, 17.0, 51.0, "icon", ("Review state", "current")),
        ("f" * 64, 9, 407.0, 233.0, "logo", ("Refresh", "available data")),
    ),
    ids=("renamed-icon-two-lines", "page-offset-logo-two-lines"),
)
def test_compact_icon_ocr_requires_full_cross_pass_source_bound_consensus(
    source_sha256: str,
    page_index: int,
    offset_x: float,
    offset_y: float,
    classification: str,
    lines: tuple[str, str],
) -> None:
    item, children, accepted, rejected, evidence, classifier = _compact_case(
        source_sha256=source_sha256,
        page_index=page_index,
        offset_x=offset_x,
        offset_y=offset_y,
        classification=classification,
        first_text=lines[0],
        second_text=lines[1],
    )

    proof = compact_visual_ocr_primary_evidence(
        item,
        children,
        accepted,
        rejected,
        "\n".join(line.text for line in accepted),
        source_text_evidence=evidence,
        source_document_identity=source_sha256,
        page_index=page_index,
        classification=classifier,
    )

    assert proof is not None
    assert proof["method"] == "source_bound_multi_pass_compact_visual_ocr"
    assert proof["accepted_line_count"] == proof["corroborating_line_count"] == 2
    assert proof["ocr_passes"] == ["sparse", "standard"]


@pytest.mark.parametrize(
    (
        "source_sha256",
        "page_index",
        "offset_x",
        "offset_y",
        "owner_width",
        "owner_height",
        "lines",
    ),
    (
        (
            "5" * 64,
            2,
            31.0,
            77.0,
            92.0,
            72.0,
            ("Verify record", "online"),
        ),
        (
            "b" * 64,
            11,
            506.0,
            412.0,
            76.0,
            61.0,
            ("Current", "release"),
        ),
    ),
    ids=("unclassified-wide-icon", "unclassified-offset-compact-logo"),
)
def test_compact_visual_ocr_can_use_complete_proof_without_classifier(
    source_sha256: str,
    page_index: int,
    offset_x: float,
    offset_y: float,
    owner_width: float,
    owner_height: float,
    lines: tuple[str, str],
) -> None:
    item, children, accepted, rejected, evidence, _classifier = _compact_case(
        source_sha256=source_sha256,
        page_index=page_index,
        offset_x=offset_x,
        offset_y=offset_y,
        classification="icon",
        first_text=lines[0],
        second_text=lines[1],
        owner_width=owner_width,
        owner_height=owner_height,
    )
    promoted_text = "\n".join(line.text for line in accepted)

    proof = compact_visual_ocr_primary_evidence(
        item,
        children,
        accepted,
        rejected,
        promoted_text,
        source_text_evidence=evidence,
        source_document_identity=source_sha256,
        page_index=page_index,
        classification=None,
    )

    assert proof is not None
    assert proof["classifier_status"] == "unavailable"
    assert proof["text_sha256"] == hashlib.sha256(
        promoted_text.encode("utf-8")
    ).hexdigest()
    assert (
        proof["accepted_width_ratio"] >= 0.40
        or proof["accepted_union_area_ratio"] >= 0.08
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "single-pass",
        "low-confidence",
        "photo-classification",
        "black-native-alternative",
        "lexical-native-alternative",
        "conflicting-ocr",
        "missing-geometry",
        "ambiguous-source-owner",
        "punctuation-conflict",
        "extra-spatial-lexical-line",
        "reused-corroborator",
        "promoted-text-mismatch",
        "malformed-rejected-line",
        "oversized-unclassified-visual",
        "undercovered-unclassified-visual",
        "nonfinite-confidence-floor",
        "missing-native-contributor-id",
        "duplicate-native-contributor-id",
    ),
)
def test_compact_icon_ocr_fails_closed_without_complete_independent_proof(
    mutation: str,
) -> None:
    source_sha256 = "3" * 64
    item, children, accepted, rejected, evidence, classifier = _compact_case(
        source_sha256=source_sha256,
        page_index=4,
        offset_x=66.0,
        offset_y=183.0,
        classification="icon",
        first_text="Status check",
        second_text="ready",
    )
    classification: dict[str, object] | None = classifier
    promoted_text = "\n".join(line.text for line in accepted)
    confidence_floor = 0.90
    if mutation == "single-pass":
        rejected.pop()
    elif mutation == "low-confidence":
        accepted[0].confidence = 0.71
    elif mutation == "photo-classification":
        classifier["class_name"] = "photograph"
    elif mutation == "black-native-alternative":
        evidence["pages"][0]["characters"][0]["fill_rgba"] = (0, 0, 0, 255)
    elif mutation == "lexical-native-alternative":
        children[0]["text"] = "VISIBLEWORD"
        evidence = _source_evidence(
            source_sha256=source_sha256,
            page_index=4,
            lines=[
                (
                    "line-overlay",
                    "VISIBLE WORD",
                    _bbox(69.3, 186.1, 93.3, 8.6),
                    (255, 255, 255, 255),
                )
            ],
        )
    elif mutation == "conflicting-ocr":
        rejected.append(
            {
                "text": "Status wrong",
                "bbox": deepcopy(accepted[0].bbox),
                "confidence": 0.97,
                "word_count": 2,
                "ocr_pass": "sparse",
            }
        )
    elif mutation == "missing-geometry":
        accepted[0].bbox = {}
    elif mutation == "ambiguous-source-owner":
        duplicate_line = deepcopy(evidence["pages"][0]["lines"][0])
        duplicate_line["id"] = "line-overlay-duplicate"
        evidence["pages"][0]["lines"].append(duplicate_line)
    elif mutation == "punctuation-conflict":
        rejected[0]["text"] = "Status: check"
    elif mutation == "extra-spatial-lexical-line":
        rejected.append(
            {
                "text": "other",
                "bbox": _bbox(68.0, 205.0, 19.0, 6.0),
                "confidence": 0.98,
                "word_count": 1,
                "ocr_pass": "standard",
            }
        )
    elif mutation == "reused-corroborator":
        accepted[1].text = accepted[0].text
        accepted[1].bbox = deepcopy(accepted[0].bbox)
        accepted[1].ocr_pass = "standard"
        rejected[:] = [rejected[0]]
        promoted_text = "\n".join(line.text for line in accepted)
    elif mutation == "promoted-text-mismatch":
        promoted_text = "Status check\nready!"
    elif mutation == "malformed-rejected-line":
        rejected.append([])
    elif mutation == "oversized-unclassified-visual":
        item["bbox"] = _bbox(66.0, 183.0, 120.0, 80.0)
        classification = None
    elif mutation == "undercovered-unclassified-visual":
        classification = None
        accepted[0].bbox = _bbox(76.0, 221.0, 5.0, 5.0)
        accepted[1].bbox = _bbox(76.0, 230.0, 5.0, 5.0)
        rejected[0]["bbox"] = deepcopy(accepted[0].bbox)
        rejected[1]["bbox"] = deepcopy(accepted[1].bbox)
    elif mutation == "nonfinite-confidence-floor":
        confidence_floor = float("nan")
    elif mutation == "missing-native-contributor-id":
        children[0].pop("id")
    elif mutation == "duplicate-native-contributor-id":
        children.append(deepcopy(children[0]))

    assert (
        compact_visual_ocr_primary_evidence(
            item,
            children,
            accepted,
            rejected,
            promoted_text,
            source_text_evidence=evidence,
            source_document_identity=source_sha256,
            page_index=4,
            classification=classification,
            confidence_floor=confidence_floor,
        )
        is None
    )


def test_owned_source_layout_rejects_tampered_child_lineage() -> None:
    source_sha256 = "4" * 64
    item = {
        "type": "image",
        "content_type": "image",
        "region_role": "content_region",
        "bbox": _bbox(210.0, 80.0, 95.0, 18.0),
    }
    child = {
        "id": "#/texts/source-label",
        "text": "RELEASEMARK",
        "bbox": _bbox(219.0, 86.0, 77.0, 8.0),
        "page_index": 2,
    }
    evidence = _source_evidence(
        source_sha256=source_sha256,
        page_index=2,
        lines=[
            (
                "source-line",
                "RELEASE MARK",
                _bbox(219.3, 85.8, 76.4, 8.1),
                (0, 0, 0, 255),
            )
        ],
    )
    recovered = recover_owned_visual_source_text(
        item,
        [child],
        source_text_evidence=evidence,
        source_document_identity=source_sha256,
        page_index=2,
    )
    assert recovered is not None
    projected = attach_visual_source_text(item, recovered, promote_primary=True)
    contained = _project_native_visual_graph(projected, [child])
    contained[0]["value"] = "DIFFERENT MARK"

    primary, rejection = _grounded_primary_visual_source_text(projected, contained)

    assert primary == ""
    assert rejection == "visual_source_child_ownership_mismatch"


@pytest.mark.parametrize(
    "mutation",
    (
        "duplicate-proof-child-id",
        "duplicate-proof-line-id",
        "unhashable-declared-child-id",
        "unhashable-declared-line-id",
    ),
)
def test_owned_source_layout_requires_bijective_bounded_lineage(
    mutation: str,
) -> None:
    source_sha256 = "6" * 64
    item = {
        "type": "image",
        "content_type": "image",
        "region_role": "content_region",
        "bbox": _bbox(200.0, 70.0, 180.0, 40.0),
    }
    children = [
        {
            "id": "#/texts/first-label",
            "text": "FIRSTLABEL",
            "bbox": _bbox(210.0, 82.0, 65.0, 9.0),
            "page_index": 5,
        },
        {
            "id": "#/texts/second-label",
            "text": "SECONDLABEL",
            "bbox": _bbox(290.0, 82.0, 72.0, 9.0),
            "page_index": 5,
        },
    ]
    evidence = _source_evidence(
        source_sha256=source_sha256,
        page_index=5,
        lines=[
            (
                "source-line-first",
                "FIRST LABEL",
                _bbox(210.2, 81.8, 64.6, 8.6),
                (0, 0, 0, 255),
            ),
            (
                "source-line-second",
                "SECOND LABEL",
                _bbox(290.2, 81.8, 71.6, 8.6),
                (0, 0, 0, 255),
            ),
        ],
    )
    recovered = recover_owned_visual_source_text(
        item,
        children,
        source_text_evidence=evidence,
        source_document_identity=source_sha256,
        page_index=5,
    )
    assert recovered is not None
    projected = attach_visual_source_text(item, recovered, promote_primary=True)
    contained = _project_native_visual_graph(projected, children)
    source_meta = projected["meta"]["phase05_visual_source_text"]
    if mutation == "duplicate-proof-child-id":
        source_meta["owned_children"][1]["id"] = source_meta[
            "owned_children"
        ][0]["id"]
    elif mutation == "duplicate-proof-line-id":
        source_meta["owned_children"][1]["source_line_id"] = source_meta[
            "owned_children"
        ][0]["source_line_id"]
    elif mutation == "unhashable-declared-child-id":
        source_meta["owned_child_ids"][0] = {}
    elif mutation == "unhashable-declared-line-id":
        source_meta["source_line_ids"][0] = []

    primary, rejection = _grounded_primary_visual_source_text(
        projected,
        contained,
    )

    assert primary == ""
    assert rejection == "visual_source_child_ownership_mismatch"


def _raw_free_document(
    item: dict[str, object],
    *,
    source_sha256: str,
    page_index: int,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "renamed-compact-source.pdf",
            "mime_type": "application/pdf",
            "sha256": source_sha256,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": page_index,
                "page_number": page_index,
                "page_label": str(page_index),
                "page_width": 1000.0,
                "page_height": 1000.0,
                "unit": "pt",
                "success": True,
                "items": [item],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "fixture",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _compact_public_owner(
    *,
    source_sha256: str = "7" * 64,
    page_index: int = 3,
    one_line: bool = False,
) -> tuple[dict[str, object], str]:
    item, children, accepted, rejected, evidence, classifier = _compact_case(
        source_sha256=source_sha256,
        page_index=page_index,
        offset_x=112.0,
        offset_y=206.0,
        classification="icon",
        first_text="Review state",
        second_text="current",
    )
    if one_line:
        accepted = accepted[:1]
        rejected = rejected[:1]
    promoted_text = "\n".join(line.text for line in accepted)
    proof = compact_visual_ocr_primary_evidence(
        item,
        children,
        accepted,
        rejected,
        promoted_text,
        source_text_evidence=evidence,
        source_document_identity=source_sha256,
        page_index=page_index,
        classification=classifier,
    )
    assert proof is not None
    public_id = "compact-owner"
    public_children: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []
    for index, child in enumerate(children):
        child_id = f"compact-public-child-{index}"
        relationship_id = f"compact-contains-{index}"
        public_children.append(
            {
                "id": child_id,
                "type": "visual_text",
                "content_type": "visual_text",
                "page_index": page_index,
                "value": child["text"],
                "md": child["text"],
                "bbox": deepcopy(child["bbox"]),
                "source": "native",
                "presentation_role": "subordinate",
                "contained_by": public_id,
                "relationship_id": relationship_id,
                "relationship_type": "contains",
                "relationship_basis": "graph_and_geometry",
            }
        )
        relationships.append(
            {
                "id": relationship_id,
                "source_id": public_id,
                "target_id": child_id,
                "type": "contains",
            }
        )
    proof["native_overlay_child_ids"] = [
        child["id"] for child in public_children
    ]

    occurrences: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    for line_index, line in enumerate(accepted):
        diagnostics.append(
            {
                "text": line.text,
                "value": line.text,
                "bbox": deepcopy(line.bbox),
                "confidence": line.confidence,
                "word_count": line.word_count,
                "source": "ocr",
                "accepted": True,
            }
        )
        words = line.text.split()
        line_box = line.bbox
        token_width = float(line_box["width"]) / len(words)
        opposite_pass = "sparse" if line.ocr_pass == "standard" else "standard"
        for word_index, word in enumerate(words):
            token_box = _bbox(
                float(line_box["x"]) + token_width * word_index,
                float(line_box["y"]),
                token_width,
                float(line_box["height"]),
            )
            primary_id = f"primary-token-{line_index}-{word_index}"
            occurrences.append(
                {
                    "occurrence_id": primary_id,
                    "line_occurrence_id": f"primary-line-{line_index}",
                    "text": word,
                    "bbox": deepcopy(token_box),
                    "confidence": line.confidence,
                    "ocr_pass": line.ocr_pass,
                    "word_index": word_index,
                    "selected": True,
                    "primary_selected": True,
                    "short_alternative": False,
                    "retention_reason": "primary_ocr_token",
                }
            )
            occurrences.append(
                {
                    "occurrence_id": (
                        f"corroborating-token-{line_index}-{word_index}"
                    ),
                    "line_occurrence_id": (
                        f"corroborating-line-{line_index}"
                    ),
                    "text": word,
                    "bbox": deepcopy(token_box),
                    "confidence": line.confidence,
                    "ocr_pass": opposite_pass,
                    "word_index": word_index,
                    "selected": False,
                    "primary_selected": False,
                    "short_alternative": False,
                    "retention_reason": (
                        "overlapping_equivalent_ocr_diagnostic"
                    ),
                    "duplicate_of": primary_id,
                }
            )
    owner = {
        **deepcopy(item),
        "id": public_id,
        "reading_order": 0,
        "value": promoted_text,
        "md": promoted_text,
        "source": "ocr",
        "ocr_text": promoted_text,
        "raw_ocr_text": promoted_text,
        "detected_text": True,
        "include_ocr_in_primary": True,
        "items": diagnostics,
        "ocr_token_occurrences": occurrences,
        "classification": classifier,
        "meta": {"compact_visual_ocr_primary": proof},
        "layout_visual_relationships_projected": True,
        "contains_ids": [child["id"] for child in public_children],
        "contained_items": public_children,
        "relationships": relationships,
    }
    return owner, promoted_text


@pytest.mark.parametrize("count_field", ("accepted_line_count", "corroborating_line_count"))
def test_compact_single_line_proof_rejects_boolean_count(
    count_field: str,
) -> None:
    source_sha256 = "1" * 64
    owner, promoted_text = _compact_public_owner(
        source_sha256=source_sha256,
        page_index=1,
        one_line=True,
    )
    proof = owner["meta"]["compact_visual_ocr_primary"]
    assert proof["accepted_line_count"] == 1
    assert proof["corroborating_line_count"] == 1
    proof[count_field] = True

    assert not revalidate_compact_visual_ocr_primary_evidence(
        owner,
        promoted_text,
        source_document_identity=source_sha256,
        page_index=1,
    )


def _rehash_compact_overlay(owner: dict[str, object]) -> str | None:
    proof = owner["meta"]["compact_visual_ocr_primary"]
    digest = compact_visual_overlay_lineage_sha256(
        source_sha256=proof["source_sha256"],
        page_index=proof["page_index"],
        coordinate_unit=proof["coordinate_unit"],
        source_child_ids=proof["native_overlay_source_child_ids"],
        source_line_ids=proof["native_overlay_source_line_ids"],
        children=proof["native_overlay_children"],
    )
    if digest is not None:
        proof["native_overlay_lineage_sha256"] = digest
    return digest


def _canonical_first_block(
    item: dict[str, object],
    *,
    source_sha256: str,
    page_index: int,
) -> dict[str, object]:
    canonical = build_canonical_presentation(
        build_document_ir(
            _raw_free_document(
                item,
                source_sha256=source_sha256,
                page_index=page_index,
            )
        )
    ).model_dump(mode="json", exclude_none=True)
    return canonical["pages"][0]["blocks"][0]


def _validated_raw_free_projection(
    item: dict[str, object],
    *,
    source_sha256: str,
    page_index: int,
) -> tuple[dict[str, object], dict[str, object]]:
    payload = _raw_free_document(
        item,
        source_sha256=source_sha256,
        page_index=page_index,
    )
    canonical = build_canonical_presentation(
        build_document_ir(payload)
    ).model_dump(mode="json", exclude_none=True)
    payload["canonical_presentation"] = canonical
    validated = ParseResult.model_validate(payload)
    assert to_markdown(validated) == canonical["full"]["markdown"]
    return payload, canonical["pages"][0]["blocks"][0]


def test_compact_visual_raw_free_projection_uses_exact_proven_owner_once() -> None:
    source_sha256 = "7" * 64
    owner, promoted_text = _compact_public_owner(
        source_sha256=source_sha256,
        page_index=3,
    )
    assert revalidate_compact_visual_ocr_primary_evidence(
        owner,
        promoted_text,
        source_document_identity=source_sha256,
        page_index=3,
    )

    block = _canonical_first_block(
        owner,
        source_sha256=source_sha256,
        page_index=3,
    )

    assert block["markdown"] == promoted_text
    assert block["text"] == promoted_text
    assert block.get("omission_reason") is None
    assert block["contributing_element_ids"] == [block["primary_element_id"]]
    assert block["excluded_contributions"]
    assert {
        exclusion["reason"] for exclusion in block["excluded_contributions"]
    } == {"evidence_only_relationship"}


@pytest.mark.parametrize(
    "mutation",
    (
        "foreign-source-sha",
        "wrong-page",
        "owner-value",
        "owner-source",
        "proof-text-hash",
        "accepted-text",
        "missing-corroborator",
        "conflicting-extra-token",
        "public-child-id",
        "source-child-id",
        "source-line-id",
        "rehashed-child-text",
        "child-geometry",
        "relationship-target",
        "extra-owner-contains",
        "boolean-proof-page",
        "boolean-corroborator-count",
        "source-proof-outside-owner",
        "nested-source-proof",
        "nested-owner-relationship",
        "oversized-relationships",
    ),
)
def test_compact_visual_raw_free_projection_rejects_tampered_proof(
    mutation: str,
) -> None:
    source_sha256 = "8" * 64
    owner, promoted_text = _compact_public_owner(
        source_sha256=source_sha256,
        page_index=4,
    )
    proof = owner["meta"]["compact_visual_ocr_primary"]
    if mutation == "foreign-source-sha":
        proof["source_sha256"] = "9" * 64
    elif mutation == "wrong-page":
        proof["page_index"] = 5
    elif mutation == "owner-value":
        owner["value"] = promoted_text + "!"
    elif mutation == "owner-source":
        owner["source"] = "native"
    elif mutation == "proof-text-hash":
        proof["text_sha256"] = "0" * 64
    elif mutation == "accepted-text":
        owner["items"][0]["text"] = "Review: state"
    elif mutation == "missing-corroborator":
        owner["ocr_token_occurrences"].pop(1)
    elif mutation == "conflicting-extra-token":
        extra = deepcopy(owner["ocr_token_occurrences"][0])
        extra.update(
            {
                "occurrence_id": "unused-conflicting-token",
                "line_occurrence_id": "unused-conflicting-line",
                "text": "other",
                "primary_selected": False,
                "retention_reason": "rejected_ocr_pass_diagnostic",
            }
        )
        owner["ocr_token_occurrences"].append(extra)
    elif mutation == "public-child-id":
        proof["native_overlay_child_ids"][0] = "different-public-child"
    elif mutation == "source-child-id":
        proof["native_overlay_source_child_ids"][0] = "#/texts/rehashed"
        proof["native_overlay_children"][0]["source_child_id"] = (
            "#/texts/rehashed"
        )
    elif mutation == "source-line-id":
        proof["native_overlay_source_line_ids"][0] = "line-rehashed"
        proof["native_overlay_children"][0]["source_line_id"] = "line-rehashed"
    elif mutation == "rehashed-child-text":
        owner["contained_items"][0]["value"] = "z7777777777"
        proof["native_overlay_children"][0]["normalized_text_sha256"] = (
            hashlib.sha256(b"z7777777777").hexdigest()
        )
    elif mutation == "child-geometry":
        owner["contained_items"][0]["bbox"]["x"] += 25.0
    elif mutation == "relationship-target":
        owner["relationships"][0]["target_id"] = "different-target"
    elif mutation == "extra-owner-contains":
        owner["relationships"].append(
            {
                "id": "undeclared-compact-contains",
                "source_id": owner["id"],
                "target_id": "independent-child",
                "type": "contains",
            }
        )
    elif mutation == "boolean-proof-page":
        proof["page_index"] = True
    elif mutation == "boolean-corroborator-count":
        proof["corroborating_line_count"] = True
    elif mutation == "source-proof-outside-owner":
        proof["native_overlay_children"][0]["bbox"] = _bbox(
            0.0, 0.0, 1000.0, 1000.0
        )
        assert _rehash_compact_overlay(owner) is not None
    elif mutation == "nested-source-proof":
        proof["native_overlay_children"][0]["nested"] = {
            "untrusted": ["payload"]
        }
    elif mutation == "nested-owner-relationship":
        owner["relationships"][0]["nested"] = {"untrusted": ["payload"]}
    elif mutation == "oversized-relationships":
        owner["relationships"].extend(
            {
                "id": f"caption-{index}",
                "source_id": f"caption-source-{index}",
                "target_id": owner["id"],
                "type": "caption_of",
            }
            for index in range(129)
        )

    value, source, _reason = _grounded_proven_visual_owner_output(
        owner,
        source_document_identity=source_sha256,
        page_index=4,
    )

    assert value == ""
    assert source is None


def _native_public_owner(
    *, source_sha256: str, page_index: int
) -> dict[str, object]:
    item = {
        "id": "native-owner",
        "type": "image",
        "content_type": "image",
        "region_role": "content_region",
        "reading_order": 0,
        "bbox": _bbox(210.0, 80.0, 95.0, 18.0),
    }
    child = {
        "id": "#/texts/native-label",
        "text": "RELEASEMARK",
        "bbox": _bbox(219.0, 86.0, 77.0, 8.0),
        "page_index": page_index,
    }
    evidence = _source_evidence(
        source_sha256=source_sha256,
        page_index=page_index,
        lines=[
            (
                "source-line-native",
                "RELEASE MARK",
                _bbox(219.3, 85.8, 76.4, 8.1),
                (0, 0, 0, 255),
            )
        ],
    )
    recovered = recover_owned_visual_source_text(
        item,
        [child],
        source_text_evidence=evidence,
        source_document_identity=source_sha256,
        page_index=page_index,
    )
    assert recovered is not None
    owner = attach_visual_source_text(item, recovered, promote_primary=True)
    relationship_id = "native-contains"
    public_child_id = "native-public-child"
    owner.update(
        {
            "layout_visual_relationships_projected": True,
            "contains_ids": [public_child_id],
            "contained_items": [
                {
                    "id": public_child_id,
                    "type": "visual_text",
                    "content_type": "visual_text",
                    "page_index": page_index,
                    "value": child["text"],
                    "md": child["text"],
                    "bbox": deepcopy(child["bbox"]),
                    "source": "native",
                    "presentation_role": "subordinate",
                    "contained_by": owner["id"],
                    "relationship_id": relationship_id,
                    "relationship_type": "contains",
                    "relationship_basis": "graph_and_geometry",
                }
            ],
            "relationships": [
                {
                    "id": relationship_id,
                    "source_id": owner["id"],
                    "target_id": public_child_id,
                    "type": "contains",
                }
            ],
            "items": [],
            "include_ocr_in_primary": False,
        }
    )
    return owner


def _rehash_native_lineage(owner: dict[str, object]) -> str | None:
    source_meta = owner["meta"]["phase05_visual_source_text"]
    digest = owned_visual_source_lineage_sha256(
        source_sha256=source_meta["source_sha256"],
        page_index=source_meta["page_index"],
        coordinate_unit=source_meta["coordinate_unit"],
        owned_child_ids=source_meta["owned_child_ids"],
        owned_children=source_meta["owned_children"],
        source_line_ids=source_meta["source_line_ids"],
        occurrences=owner["visual_source_text_occurrences"],
        lines=owner["visual_source_text_lines"],
    )
    if digest is not None:
        source_meta["source_lineage_sha256"] = digest
    return digest


def _append_independent_native_child(
    owner: dict[str, object],
    *,
    child_id: str,
    text: str,
    bbox: dict[str, object],
) -> None:
    relationship_id = f"contains-{child_id}"
    owner["contained_items"].append(
        {
            "id": child_id,
            "type": "visual_text",
            "content_type": "visual_text",
            "page_index": owner["meta"].get(
                "phase05_visual_source_text",
                owner["meta"].get("compact_visual_ocr_primary", {}),
            )["page_index"],
            "value": text,
            "md": text,
            "bbox": bbox,
            "source": "native",
            "presentation_role": "subordinate",
            "contained_by": owner["id"],
            "relationship_id": relationship_id,
            "relationship_type": "contains",
            "relationship_basis": "graph_and_geometry",
        }
    )
    owner["contains_ids"].append(child_id)
    owner["relationships"].append(
        {
            "id": relationship_id,
            "source_id": owner["id"],
            "target_id": child_id,
            "type": "contains",
        }
    )


def test_native_visual_raw_free_projection_uses_exact_proven_owner_once() -> None:
    source_sha256 = "c" * 64
    owner = _native_public_owner(source_sha256=source_sha256, page_index=6)

    block = _canonical_first_block(
        owner,
        source_sha256=source_sha256,
        page_index=6,
    )

    assert block["markdown"] == "RELEASE MARK"
    assert block["text"] == "RELEASE MARK"
    assert block.get("omission_reason") is None


def test_native_visual_fallback_preserves_proven_label_and_independent_child() -> None:
    source_sha256 = "2" * 64
    owner = _native_public_owner(source_sha256=source_sha256, page_index=8)
    _append_independent_native_child(
        owner,
        child_id="independent-native-child",
        text="INDEPENDENT CONTENT",
        bbox=_bbox(222.0, 82.0, 72.0, 7.0),
    )

    payload, block = _validated_raw_free_projection(
        owner,
        source_sha256=source_sha256,
        page_index=8,
    )

    assert block["markdown"] == "RELEASE MARK\n\nINDEPENDENT CONTENT"
    assert block["text"] == "RELEASE MARK\n\nINDEPENDENT CONTENT"
    assert block["markdown"].count("INDEPENDENT CONTENT") == 1
    assert "RELEASEMARK" not in block["markdown"]
    assert block["contributing_element_ids"] == [block["primary_element_id"]]
    assert payload["pages"][0]["items"][0]["contained_items"][-1][
        "value"
    ] == "INDEPENDENT CONTENT"


def test_compact_visual_fallback_preserves_ocr_and_independent_native_child() -> None:
    source_sha256 = "3" * 64
    owner, promoted_text = _compact_public_owner(
        source_sha256=source_sha256,
        page_index=9,
    )
    owner_box = owner["bbox"]
    _append_independent_native_child(
        owner,
        child_id="independent-compact-child",
        text="INDEPENDENT CONTENT",
        bbox=_bbox(
            float(owner_box["x"]) + 8.0,
            float(owner_box["y"]) + 20.0,
            68.0,
            7.0,
        ),
    )

    payload, block = _validated_raw_free_projection(
        owner,
        source_sha256=source_sha256,
        page_index=9,
    )

    assert block["markdown"] == f"{promoted_text}\n\nINDEPENDENT CONTENT"
    assert block["text"] == f"{promoted_text}\n\nINDEPENDENT CONTENT"
    assert block["markdown"].count("INDEPENDENT CONTENT") == 1
    assert "q8888888888" not in block["markdown"]
    assert block["contributing_element_ids"] == [block["primary_element_id"]]
    assert payload["pages"][0]["items"][0]["contained_items"][-1][
        "value"
    ] == "INDEPENDENT CONTENT"


def test_compact_visual_fallback_preserves_legitimate_repeated_code_text() -> None:
    source_sha256 = "0" * 64
    owner, promoted_text = _compact_public_owner(
        source_sha256=source_sha256,
        page_index=16,
    )
    owner_box = owner["bbox"]
    repeated = "q8888888888"
    _append_independent_native_child(
        owner,
        child_id="independent-repeated-code-child",
        text=repeated,
        bbox=_bbox(
            float(owner_box["x"]) + 8.0,
            float(owner_box["y"]) + 20.0,
            68.0,
            7.0,
        ),
    )

    _payload, block = _validated_raw_free_projection(
        owner,
        source_sha256=source_sha256,
        page_index=16,
    )

    assert block["markdown"] == f"{promoted_text}\n\n{repeated}"
    assert block["markdown"].count(repeated) == 1


def test_compact_visual_tamper_expands_preservation_instead_of_deleting() -> None:
    source_sha256 = "4" * 64
    owner, promoted_text = _compact_public_owner(
        source_sha256=source_sha256,
        page_index=10,
    )
    owner_box = owner["bbox"]
    _append_independent_native_child(
        owner,
        child_id="independent-tamper-child",
        text="INDEPENDENT CONTENT",
        bbox=_bbox(
            float(owner_box["x"]) + 8.0,
            float(owner_box["y"]) + 20.0,
            68.0,
            7.0,
        ),
    )
    owner["meta"]["compact_visual_ocr_primary"]["text_sha256"] = "0" * 64

    _payload, block = _validated_raw_free_projection(
        owner,
        source_sha256=source_sha256,
        page_index=10,
    )

    markdown = block["markdown"]
    assert markdown.count("Review state") == 1
    assert markdown.count("current") == 1
    assert markdown.count("q8888888888") == 1
    assert block["markdown"].count("INDEPENDENT CONTENT") == 1
    assert (
        markdown.index("Review state")
        < markdown.index("current")
        < markdown.index("q8888888888")
        < markdown.index("INDEPENDENT CONTENT")
    )


def test_native_malformed_proof_sibling_does_not_delete_independent_child() -> None:
    source_sha256 = "5" * 64
    owner = _native_public_owner(source_sha256=source_sha256, page_index=11)
    _append_independent_native_child(
        owner,
        child_id="independent-native-survivor",
        text="INDEPENDENT CONTENT",
        bbox=_bbox(222.0, 82.0, 72.0, 7.0),
    )
    owner["contained_items"][0]["md"] = "MISMATCH"
    owner["relationships"].append(42)

    _payload, block = _validated_raw_free_projection(
        owner,
        source_sha256=source_sha256,
        page_index=11,
    )

    assert block["markdown"] == "INDEPENDENT CONTENT"
    assert block["text"] == "INDEPENDENT CONTENT"
    assert block["contributing_element_ids"] == [block["primary_element_id"]]


def test_reordered_native_contains_ids_disable_suppression_without_content_loss() -> None:
    source_sha256 = "7" * 64
    owner = _native_public_owner(source_sha256=source_sha256, page_index=13)
    _append_independent_native_child(
        owner,
        child_id="independent-reordered-child",
        text="INDEPENDENT CONTENT",
        bbox=_bbox(222.0, 82.0, 72.0, 7.0),
    )
    owner["contains_ids"].reverse()

    _payload, block = _validated_raw_free_projection(
        owner,
        source_sha256=source_sha256,
        page_index=13,
    )

    assert block["markdown"] == "RELEASEMARK\n\nINDEPENDENT CONTENT"
    assert "RELEASE MARK" not in block["markdown"]


def test_duplicate_contains_relationship_id_disables_suppression_only() -> None:
    source_sha256 = "9" * 64
    owner = _native_public_owner(source_sha256=source_sha256, page_index=15)
    _append_independent_native_child(
        owner,
        child_id="independent-duplicate-edge-child",
        text="INDEPENDENT CONTENT",
        bbox=_bbox(222.0, 82.0, 72.0, 7.0),
    )
    duplicate_id = owner["relationships"][0]["id"]
    owner["relationships"][1]["id"] = duplicate_id
    owner["contained_items"][1]["relationship_id"] = duplicate_id

    _payload, block = _validated_raw_free_projection(
        owner,
        source_sha256=source_sha256,
        page_index=15,
    )

    assert block["markdown"] == "RELEASEMARK\n\nINDEPENDENT CONTENT"


def test_native_child_fallback_is_limited_to_routed_content_images() -> None:
    source_sha256 = "8" * 64
    owner = _native_public_owner(source_sha256=source_sha256, page_index=14)
    owner["region_role"] = "decorative"

    _payload, block = _validated_raw_free_projection(
        owner,
        source_sha256=source_sha256,
        page_index=14,
    )

    assert block["markdown"] == ""
    assert block["omission_reason"] == "empty_visual"


def test_compact_malformed_overlay_sibling_does_not_delete_independent_child() -> None:
    source_sha256 = "6" * 64
    owner, promoted_text = _compact_public_owner(
        source_sha256=source_sha256,
        page_index=12,
    )
    owner_box = owner["bbox"]
    _append_independent_native_child(
        owner,
        child_id="independent-compact-survivor",
        text="INDEPENDENT CONTENT",
        bbox=_bbox(
            float(owner_box["x"]) + 8.0,
            float(owner_box["y"]) + 20.0,
            68.0,
            7.0,
        ),
    )
    owner["contained_items"][0]["md"] = "MISMATCH"

    _payload, block = _validated_raw_free_projection(
        owner,
        source_sha256=source_sha256,
        page_index=12,
    )

    markdown = block["markdown"]
    assert markdown.count("Review state") == 1
    assert markdown.count("current") == 1
    assert markdown.count("INDEPENDENT CONTENT") == 1
    assert (
        markdown.index("Review state")
        < markdown.index("current")
        < markdown.index("INDEPENDENT CONTENT")
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "extra-contained-child",
        "duplicate-public-child-id",
        "wrong-source",
        "wrong-owner",
        "wrong-role",
        "wrong-basis",
        "missing-relationship",
        "wrong-relationship-target",
        "extra-owner-contains",
        "duplicate-line-binding",
        "missing-line-binding",
        "forged-line-text-with-rehashed-lineage",
        "public-child-outside-owner",
        "nested-proof-record",
        "oversized-proof-identifier",
        "oversized-relationships",
    ),
)
def test_native_visual_raw_free_projection_rejects_incomplete_custody(
    mutation: str,
) -> None:
    source_sha256 = "e" * 64
    owner = _native_public_owner(source_sha256=source_sha256, page_index=7)
    child = owner["contained_items"][0]
    if mutation == "extra-contained-child":
        extra = deepcopy(child)
        extra.update(
            {
                "id": "independent-child",
                "value": "INDEPENDENT CONTENT",
                "md": "INDEPENDENT CONTENT",
                "relationship_id": "independent-contains",
            }
        )
        owner["contained_items"].append(extra)
        owner["contains_ids"].append(extra["id"])
        owner["relationships"].append(
            {
                "id": "independent-contains",
                "source_id": owner["id"],
                "target_id": extra["id"],
                "type": "contains",
            }
        )
    elif mutation == "duplicate-public-child-id":
        owner["contains_ids"].append(owner["contains_ids"][0])
    elif mutation == "wrong-source":
        child["source"] = "ocr"
    elif mutation == "wrong-owner":
        child["contained_by"] = "different-owner"
    elif mutation == "wrong-role":
        child["presentation_role"] = "primary"
    elif mutation == "wrong-basis":
        child["relationship_basis"] = "geometry_only"
    elif mutation == "missing-relationship":
        owner["relationships"].clear()
    elif mutation == "wrong-relationship-target":
        owner["relationships"][0]["target_id"] = "different-child"
    elif mutation == "extra-owner-contains":
        owner["relationships"].append(
            {
                "id": "undeclared-contains",
                "source_id": owner["id"],
                "target_id": "independent-child",
                "type": "contains",
            }
        )
    elif mutation == "duplicate-line-binding":
        owner["visual_source_text_lines"].append(
            deepcopy(owner["visual_source_text_lines"][0])
        )
        assert _rehash_native_lineage(owner) is None
    elif mutation == "missing-line-binding":
        owner["visual_source_text_lines"][0].pop("source_line_id")
        assert _rehash_native_lineage(owner) is None
    elif mutation == "forged-line-text-with-rehashed-lineage":
        forged = "FORGED LABEL"
        owner["visual_source_text"] = forged
        owner["visual_source_text_lines"][0]["text"] = forged
        owner["value"] = forged
        owner["md"] = forged
        owner["meta"]["phase05_visual_source_text"]["text_sha256"] = (
            hashlib.sha256(forged.encode("utf-8")).hexdigest()
        )
        assert _rehash_native_lineage(owner) is not None
    elif mutation == "public-child-outside-owner":
        child["bbox"] = _bbox(0.0, 0.0, 1000.0, 1000.0)
    elif mutation == "nested-proof-record":
        owner["meta"]["phase05_visual_source_text"]["owned_children"][0][
            "nested"
        ] = {"untrusted": ["payload"]}
    elif mutation == "oversized-proof-identifier":
        oversized = "x" * 2_049
        source_meta = owner["meta"]["phase05_visual_source_text"]
        source_meta["owned_child_ids"][0] = oversized
        source_meta["owned_children"][0]["id"] = oversized
    elif mutation == "oversized-relationships":
        owner["relationships"].extend(
            {
                "id": f"caption-{index}",
                "source_id": f"caption-source-{index}",
                "target_id": owner["id"],
                "type": "caption_of",
            }
            for index in range(321)
        )

    value, source, _reason = _grounded_proven_visual_owner_output(
        owner,
        source_document_identity=source_sha256,
        page_index=7,
    )

    assert value == ""
    assert source is None


def test_unproven_visual_owner_value_remains_fail_closed_in_raw_free_view() -> None:
    source_sha256 = "d" * 64
    owner = {
        "id": "unproven-owner",
        "type": "image",
        "content_type": "image",
        "region_role": "content_region",
        "reading_order": 0,
        "bbox": _bbox(20.0, 20.0, 120.0, 80.0),
        "value": "incidental branding",
        "md": "incidental branding",
        "source": "derived",
        "include_ocr_in_primary": False,
        "items": [],
    }

    block = _canonical_first_block(
        owner,
        source_sha256=source_sha256,
        page_index=1,
    )

    assert block["markdown"] == ""
    assert block["omission_reason"] == "empty_visual"
