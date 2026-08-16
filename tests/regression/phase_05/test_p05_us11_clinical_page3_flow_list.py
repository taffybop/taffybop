"""Real page-3 acceptance for source-grounded raster flowchart lists."""

from __future__ import annotations

import hashlib
from collections import Counter

import pytest

from app.models import ParseResult
from app.services.serializer import to_markdown
from app.services.visual_contracts import VisualStructure
from tests.regression.phase_03.test_p03_us02_real_visual_benchmarks import (
    CORPUS,
    _parse_local_fidelity,
)

SOURCE_SHA256 = (
    "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2"
)
FIGURE_DOI = "https://doi.org/10.1371/journal.pmed.1004460.g001"

EXPECTED_LIST = """- Assessed for eligibility (n = 826)
  - Excluded (n = 230)
    - Acute suicidality (n = 83)
    - Low symptoms (n = 73)
    - Age < 18 (n = 73)
    - Duplicate account (n = 1)
  - Included (n = 596)
    - baseline non-completion (n = 58)
    - Randomized (n = 538)
      - Allocated to SbS + CAU (n = 266)
        - Non-completer (n = 168)
          - Non-starter (n = 21)
          - Completed introduction (n = 209)
          - Completed session 1 (n = 177)
          - Completed session 2 (n = 133)
          - Completed session 3 (n = 102)
          - Completed session 4 (n = 98)
          - Completed session 5 (n = 68)
        - Completed post-assessment (n = 207)
          - Completed follow-up (n = 174)
            - Intention-to-treat sample (n = 266)
      - Allocated to CAU (n = 272)
        - Non-completer (n = 65)
          - Non-starter (n = 21)
          - Completed information session (n = 207)
        - Completed post-assessment (n = 186)
          - Completed follow-up (n = 170)
            - Intention-to-treat sample (n = 272)"""

EXPECTED_NODE_LABELS = Counter(
    {
        "Assessed for eligibility (n = 826)": 1,
        "Excluded (n = 230)": 1,
        "Included (n = 596)": 1,
        "baseline non-completion (n = 58)": 1,
        "Randomized (n = 538)": 1,
        "Allocated to SbS + CAU (n = 266)": 1,
        "Allocated to CAU (n = 272)": 1,
        "Non-completer (n = 168)": 1,
        "Non-completer (n = 65)": 1,
        "Completed post-assessment (n = 207)": 1,
        "Completed post-assessment (n = 186)": 1,
        "Completed follow-up (n = 174)": 1,
        "Completed follow-up (n = 170)": 1,
        "Intention-to-treat sample (n = 266)": 1,
        "Intention-to-treat sample (n = 272)": 1,
    }
)

EXPECTED_DETAILS = {
    "Excluded (n = 230)": [
        "Acute suicidality (n = 83)",
        "Low symptoms (n = 73)",
        "Age < 18 (n = 73)",
        "Duplicate account (n = 1)",
    ],
    "Non-completer (n = 168)": [
        "Non-starter (n = 21)",
        "Completed introduction (n = 209)",
        "Completed session 1 (n = 177)",
        "Completed session 2 (n = 133)",
        "Completed session 3 (n = 102)",
        "Completed session 4 (n = 98)",
        "Completed session 5 (n = 68)",
    ],
    "Non-completer (n = 65)": [
        "Non-starter (n = 21)",
        "Completed information session (n = 207)",
    ],
}

EXPECTED_EDGES = {
    ("Assessed for eligibility (n = 826)", "Excluded (n = 230)"),
    ("Assessed for eligibility (n = 826)", "Included (n = 596)"),
    ("Included (n = 596)", "baseline non-completion (n = 58)"),
    ("Included (n = 596)", "Randomized (n = 538)"),
    ("Randomized (n = 538)", "Allocated to SbS + CAU (n = 266)"),
    ("Randomized (n = 538)", "Allocated to CAU (n = 272)"),
    ("Allocated to SbS + CAU (n = 266)", "Non-completer (n = 168)"),
    (
        "Allocated to SbS + CAU (n = 266)",
        "Completed post-assessment (n = 207)",
    ),
    ("Allocated to CAU (n = 272)", "Non-completer (n = 65)"),
    ("Allocated to CAU (n = 272)", "Completed post-assessment (n = 186)"),
    (
        "Completed post-assessment (n = 207)",
        "Completed follow-up (n = 174)",
    ),
    (
        "Completed post-assessment (n = 186)",
        "Completed follow-up (n = 170)",
    ),
    (
        "Completed follow-up (n = 174)",
        "Intention-to-treat sample (n = 266)",
    ),
    (
        "Completed follow-up (n = 170)",
        "Intention-to-treat sample (n = 272)",
    ),
}


@pytest.mark.integration
def test_clinical_page_three_raster_flowchart_is_one_grounded_nested_list() -> None:
    source = CORPUS / "clinical-study.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA256

    payload = _parse_local_fidelity("clinical-study")
    public = ParseResult.model_validate(payload)
    page = next(value for value in payload["pages"] if value["page_index"] == 3)
    diagrams = [item for item in page["items"] if item.get("type") == "diagram"]
    assert len(diagrams) == 1
    diagram = diagrams[0]
    structure = VisualStructure.model_validate(diagram["visual_structure"])

    assert structure.fallback.active is False
    assert structure.serialization is not None
    assert structure.serialization.status == "diagram_topology"
    assert structure.serialization.caption_occurrences == 0
    assert structure.serialization.row_count == len(structure.connectors) == 14
    assert len(structure.nodes) == 15
    assert structure.serialization.markdown == EXPECTED_LIST
    assert diagram["value"] == diagram["md"] == EXPECTED_LIST
    assert "diagram_relationships_not_structured" not in (
        diagram.get("parse_concerns") or []
    )
    assert diagram["bbox"] == {
        "x": 123.364,
        "y": 78.009,
        "width": 452.636,
        "height": 572.372,
        "unit": "pt",
    }
    assert structure.region.page_bbox.model_dump(mode="json") == {
        "x": 123.364,
        "y": 78.009,
        "width": 452.636,
        "height": 572.372,
        "unit": "pt",
    }

    labels = {label.id: label for label in structure.labels}
    node_labels = {
        node.id: labels[node.label_id].text
        for node in structure.nodes
        if node.label_id is not None
    }
    assert len(node_labels) == len(structure.nodes)
    assert Counter(node_labels.values()) == EXPECTED_NODE_LABELS

    details = {
        node_labels[node.id]: [labels[label_id].text for label_id in node.detail_label_ids]
        for node in structure.nodes
        if node.detail_label_ids
    }
    assert details == EXPECTED_DETAILS
    assert sum(map(len, details.values())) == 13
    assert {
        (node_labels[edge.source_node_id], node_labels[edge.target_node_id])
        for edge in structure.connectors
    } == EXPECTED_EDGES
    assert all(edge.label_id is None for edge in structure.connectors)

    evidence = {record.id: record for record in structure.evidence}
    for node in structure.nodes:
        raster_evidence = [
            evidence[evidence_id]
            for evidence_id in node.evidence_ids
            if evidence[evidence_id].provenance.extraction_method == "raster"
        ]
        assert raster_evidence
        assert all(record.raster_pixel_bbox is not None for record in raster_evidence)
        assert all(record.transform_ids for record in raster_evidence)
    for edge in structure.connectors:
        asserted = [
            evidence[edge.path_evidence_id],
            *(evidence[value] for value in edge.endpoint_evidence_ids),
            evidence[edge.direction_evidence_id],
        ]
        assert all(
            record.provenance.extraction_method == "raster"
            for record in asserted
        )
        assert all(record.raster_pixel_bbox is not None for record in asserted)
        assert all(record.transform_ids for record in asserted)

    captions = [
        item
        for item in page["items"]
        if item.get("type") == "caption" and item.get("caption_of") == diagram["id"]
    ]
    assert len(captions) == 1
    assert captions[0]["value"] == captions[0]["md"] == "Fig 1. Flowchart."

    page_two = next(
        value for value in payload["pages"] if value["page_index"] == 2
    )
    assert all(
        FIGURE_DOI not in str(item.get("value") or "")
        and FIGURE_DOI not in str(item.get("md") or "")
        for item in page_two["items"]
    )
    figure_notes = [
        item
        for item in page["items"]
        if item.get("type") == "footnote" and item.get("value") == FIGURE_DOI
    ]
    assert len(figure_notes) == 1
    figure_note = figure_notes[0]
    assert figure_note["md"] == FIGURE_DOI
    assert figure_note["footnote_of"] == diagram["id"]
    assert figure_note["links"] == [{"kind": "hyperlink", "target": FIGURE_DOI}]
    partition = figure_note["source_partition"]
    assert partition["policy"] == (
        "annotation_backed_cross_page_visual_note_partition_v1"
    )
    assert partition["role"] == "detached_visual_note"
    assert partition["raw_ref"] == "#/texts/36"
    assert partition["provenance_index"] == 1
    assert partition["charspan"] == [648, 697]
    assert partition["source_sha256"] == SOURCE_SHA256
    assert partition["annotation_raw_ref"] == (
        "#/texts/layout-source-note-annotation-8312b0f52d3a3ad4dfa1dee4"
    )
    assert partition["visual_raw_ref"] == "#/pictures/2"
    assert partition["caption_raw_ref"] == "#/texts/41"
    assert partition["source_line_ids"]
    assert len(partition["source_line_ids"]) == len(
        set(partition["source_line_ids"])
    )
    assert partition["source_character_ids"]
    assert len(partition["source_character_ids"]) == len(
        set(partition["source_character_ids"])
    )

    markdown = to_markdown(public)
    assert markdown.count(EXPECTED_LIST) == 1
    assert markdown.count("Fig 1. Flowchart.") == 1
    assert markdown.count(FIGURE_DOI) == 1
    assert "graph TD" not in markdown
    assert "### Nodes" not in markdown
    assert "### Connections" not in markdown
    assert "e Acute suicidality" not in markdown
    assert "Age <18" not in markdown
    assert "Completed information\n\nsession" not in markdown

    canonical_page = next(
        value
        for value in payload["canonical_presentation"]["pages"]
        if value["page_index"] == 3
    )
    diagram_blocks = [
        block
        for block in canonical_page["blocks"]
        if block["primary_element_type"] == "diagram"
        and block.get("omission_reason") is None
    ]
    assert len(diagram_blocks) == 1
    assert diagram_blocks[0]["text"] == diagram_blocks[0]["markdown"] == EXPECTED_LIST
    assert payload["canonical_presentation"]["full"]["markdown"] == markdown
