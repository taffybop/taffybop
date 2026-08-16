from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import pytest

from app.services.ir import build_document_ir
from app.services.presentation import (
    augment_canonical_visual_model_evidence,
    build_canonical_presentation,
)
from app.services.serializer import to_markdown
from app.services.visual_model_contracts import (
    VisualModelConfidenceDimensions,
    VisualModelEvidenceBundle,
    VisualModelIdentity,
    VisualModelObservation,
)


def _stable_id(prefix: str, *parts: Any) -> str:
    import json

    encoded = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _document(*, with_bundle: bool = True) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "visual-1",
        "type": "image",
        "reading_order": 0,
        "value": "Source visual caption",
        "md": "Source visual caption",
        "caption": "Source visual caption",
        "caption_source": "document_caption",
        "region_role": "content_region",
        "source": "native",
        "confidence": 0.95,
        "bbox": {
            "x": 10,
            "y": 20,
            "width": 100,
            "height": 80,
            "unit": "pt",
        },
    }
    if with_bundle:
        item["visual_model_evidence"] = _bundle().model_dump(
            mode="json",
            exclude_none=True,
        )
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "visual-model-projection.pdf",
            "mime_type": "application/pdf",
            "sha256": "7" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612,
                "page_height": 792,
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


def _bundle() -> VisualModelEvidenceBundle:
    identity = VisualModelIdentity(
        adapter_kind="test_double",
        adapter_name="deterministic-adapter",
        adapter_version="1.0.0",
        model_name="fixture-model",
        model_version="fixture-v1",
        prompt_version="grounded-v1",
        response_schema_version="1.0",
    )
    return VisualModelEvidenceBundle(
        schema_version="1.0",
        merge_version="p06-additive-merge-v1",
        validation_version="p06-grounding-p05-v1",
        public_item_id="visual-1",
        region_id="region-1",
        page_index=1,
        source_evidence_preserved=True,
        observations=[
            VisualModelObservation(
                id="observation-1",
                operation="add",
                observation_type="generated_description",
                origin="model_generated_description",
                explicitness="generated",
                method="generated_description",
                text="Revenue <script>alert(1)</script> | **not source**\nnext",
                region_id="region-1",
                page_index=1,
                evidence_ids=["phase05-evidence-1"],
                identity=identity,
                confidence=VisualModelConfidenceDimensions(model=0.9),
            )
        ],
    )


def _baseline_canonical() -> tuple[dict[str, Any], Any]:
    without_bundle = _document(with_bundle=False)
    canonical = build_canonical_presentation(
        build_document_ir(deepcopy(without_bundle))
    )
    return without_bundle, canonical


def test_canonical_augmentation_is_additive_origin_labelled_and_deterministic(
) -> None:
    baseline_document, baseline = _baseline_canonical()
    source_block = baseline.pages[0].blocks[0].model_dump(mode="json")
    merged_document = _document()

    first = augment_canonical_visual_model_evidence(
        baseline.model_dump(mode="json"),
        merged_document["pages"],
    )
    second = augment_canonical_visual_model_evidence(
        baseline.model_dump(mode="json"),
        deepcopy(merged_document["pages"]),
    )

    assert first == second
    block = first.pages[0].blocks[0]
    assert block.markdown.startswith(source_block["markdown"])
    assert block.text.startswith(source_block["text"])
    assert block.markdown.count("Model-generated evidence") == 1
    assert block.text.count("Model-generated evidence") == 1
    assert "<script>" not in block.markdown
    assert "&lt;script&gt;" in block.markdown
    assert "\\| \\*\\*not source\\*\\* next" in block.markdown
    assert first.full.markdown == first.pages[0].full.markdown
    assert first.full.text == first.pages[0].full.text
    assert (
        baseline.model_dump(mode="json")
        == build_canonical_presentation(
            build_document_ir(deepcopy(baseline_document))
        ).model_dump(mode="json")
    )


def test_canonical_augmentation_rejects_bad_binding_without_mutating_baseline(
) -> None:
    _baseline_document, baseline = _baseline_canonical()
    before = baseline.model_dump(mode="json")
    malformed_pages = deepcopy(_document()["pages"])
    malformed_pages[0]["items"][0]["type"] = "chart"

    with pytest.raises(ValueError, match="type order"):
        augment_canonical_visual_model_evidence(baseline, malformed_pages)

    assert baseline.model_dump(mode="json") == before


def test_canonical_augmentation_accepts_typed_public_pages() -> None:
    from app.models import ParseResult

    _baseline_document, baseline = _baseline_canonical()
    typed = ParseResult.model_validate(_document())

    augmented = augment_canonical_visual_model_evidence(
        baseline,
        typed.pages,
    )

    assert augmented.full.markdown.count("Model-generated evidence") == 1


def test_canonical_augmentation_rejects_omitted_owner_and_repeat_projection(
) -> None:
    _baseline_document, baseline = _baseline_canonical()
    omitted = baseline.model_dump(mode="json")
    block = omitted["pages"][0]["blocks"][0]
    block.update(
        markdown="",
        text="",
        contributing_element_ids=[],
        omission_reason="empty_visual",
    )
    for scope in ("full", "body"):
        omitted["pages"][0][scope] = {
            "block_ids": [],
            "markdown": "",
            "text": "",
        }
        omitted[scope] = {
            "block_ids": [],
            "markdown": "",
            "text": "",
        }

    with pytest.raises(ValueError, match="owner block is omitted"):
        augment_canonical_visual_model_evidence(omitted, _document()["pages"])

    augmented = augment_canonical_visual_model_evidence(
        baseline,
        _document()["pages"],
    )
    with pytest.raises(ValueError, match="already contains"):
        augment_canonical_visual_model_evidence(
            augmented,
            _document()["pages"],
        )


def test_legacy_markdown_appends_strict_bundle_once_and_fails_closed(
) -> None:
    document = _document()
    source_item = deepcopy(document["pages"][0]["items"][0])
    source_item.pop("visual_model_evidence")

    rendered = to_markdown(document)

    assert rendered.startswith("Source visual caption")
    assert rendered.count("Source visual caption") == 1
    assert rendered.count("Model-generated evidence") == 1
    assert "&lt;script&gt;" in rendered
    assert document["pages"][0]["items"][0]["value"] == source_item["value"]
    assert document["pages"][0]["items"][0]["md"] == source_item["md"]
    assert document["pages"][0]["items"][0]["caption"] == source_item["caption"]

    malformed = deepcopy(document)
    malformed["pages"][0]["items"][0]["visual_model_evidence"][
        "public_item_id"
    ] = "wrong-owner"
    assert to_markdown(malformed) == "Source visual caption\n"


def test_model_only_visual_remains_a_canonical_included_block() -> None:
    document = _document()
    item = document["pages"][0]["items"][0]
    item["value"] = ""
    item["md"] = ""
    item.pop("caption")
    item.pop("caption_source")

    canonical = build_canonical_presentation(build_document_ir(document))
    block = canonical.pages[0].blocks[0]

    assert block.omission_reason is None
    assert block.markdown.count("Model-generated evidence") == 1
    assert block.text.count("Model-generated evidence") == 1


def test_structured_phase05_visual_and_model_evidence_each_render_once() -> None:
    from app.config import Settings
    from app.services.input_documents import InputKind
    from app.services.visual_semantics import apply_visual_semantics
    from tests.stories.phase_05.test_p05_us05_chart_validation import _source

    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        visual_structure_schema_enabled=True,
        charts_vector_inventory_enabled=True,
        charts_structure_enabled=True,
        charts_vector_values_enabled=True,
        charts_structured_output_enabled=True,
    )
    document = apply_visual_semantics(
        _source(),
        settings,
        input_kind=InputKind.PDF,
    )
    item = document["pages"][0]["items"][0]
    structure = item["visual_structure"]
    bundle = _bundle().model_dump(mode="json", exclude_none=True)
    bundle["public_item_id"] = item["id"]
    bundle["region_id"] = structure["region"]["id"]
    bundle["observations"][0]["region_id"] = structure["region"]["id"]
    bundle["observations"][0]["evidence_ids"] = [
        structure["evidence"][0]["id"]
    ]
    item["visual_model_evidence"] = bundle

    canonical = build_canonical_presentation(build_document_ir(document))
    block = canonical.pages[0].blocks[0]

    assert block.markdown.count(
        "| Category | Series | Value | Method | Tolerance |"
    ) == 1
    assert block.markdown.count("Model-generated evidence") == 1
    assert block.text.count("Model-generated evidence") == 1
