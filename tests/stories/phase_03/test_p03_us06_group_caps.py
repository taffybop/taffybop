"""Focused exact/max+1 coverage for reconciled P03-US06 group caps."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

from app.services import form_semantics as semantics
from app.services.ir import DocumentIR, build_document_ir


CandidateFactory = Callable[[int], tuple[DocumentIR, semantics._GroupCandidate]]


def _predecessor(anchor_count: int) -> tuple[DocumentIR, tuple[tuple[str, str], ...]]:
    source_key = f"p03-us06-cap-boundary:{anchor_count}"
    items = [
        {
            "id": f"a{index}",
            "type": "text",
            "reading_order": index,
            "value": f"Anchor {index}",
            "md": f"Anchor {index}",
            "bbox": {
                "x": 10.0 + (index % 10) * 20.0,
                "y": 10.0 + (index // 10) * 15.0,
                "width": 15.0,
                "height": 10.0,
                "unit": "pt",
            },
            "source": "native",
        }
        for index in range(anchor_count)
    ]
    ir = build_document_ir(
        {
            "schema_version": "1.0",
            "document": {
                "filename": "p03-us06-cap-boundary.pdf",
                "mime_type": "application/pdf",
                "sha256": hashlib.sha256(source_key.encode()).hexdigest(),
                "page_count": 1,
            },
            "pages": [
                {
                    "page_index": 1,
                    "page_number": 1,
                    "page_label": "1",
                    "page_width": 320.0,
                    "page_height": 260.0,
                    "unit": "pt",
                    "success": True,
                    "items": items,
                    "warnings": [],
                }
            ],
            "processing": {
                "engine": "fixture",
                "ocr_engine": "none",
                "ocr_languages": [],
                "duration_ms": 0,
            },
            "warnings": [],
        }
    )
    anchors: list[tuple[str, str]] = []
    for index in range(anchor_count):
        public_id = f"a{index}"
        element = next(
            value
            for value in ir.elements
            if value.properties.get("legacy_item", {}).get("id") == public_id
        )
        anchors.append((public_id, element.id))
    return ir, tuple(anchors)


def _rect_source(index: int) -> tuple[tuple[str, int, None], ...]:
    return (("rect", index, None),)


def _character_source(index: int) -> tuple[tuple[str, int, int], ...]:
    return (("character_range", index, index + 1),)


def _bbox(index: int) -> tuple[float, float, float, float]:
    return (10.0 + (index % 20) * 2.0, 10.0, 1.0, 1.0)


def _candidate(
    anchors: tuple[tuple[str, str], ...],
    *,
    records: list[semantics._RecordCandidate],
    relationships: list[tuple[str, str, str]],
    source_objects: tuple[tuple[str, int, int | None], ...] | None = None,
    canonical_mode: str = "inert",
    concern_codes: tuple[str, ...] = (),
) -> semantics._GroupCandidate:
    return semantics._GroupCandidate(
        group_key="g",
        page_index=1,
        bbox=(1.0, 1.0, 300.0, 250.0),
        status="resolved",
        interactivity="static",
        canonical_mode=canonical_mode,  # type: ignore[arg-type]
        anchor_public_item_id=anchors[0][0],
        anchor_element_id=anchors[0][1],
        contributor_public_item_ids=tuple(value[0] for value in anchors),
        contributor_element_ids=tuple(value[1] for value in anchors),
        records=tuple(records),
        relationships=tuple(relationships),
        source_objects=source_objects or _rect_source(100_000),
        concern_codes=concern_codes,
    )


def _control_candidate(count: int) -> tuple[DocumentIR, semantics._GroupCandidate]:
    ir, anchors = _predecessor(1)
    records: list[semantics._RecordCandidate] = []
    relationships: list[tuple[str, str, str]] = []
    for index in range(count):
        token = f"control:{index}"
        records.append(
            semantics._RecordCandidate(
                token=token,
                role="control",
                key=f"c{index}",
                bbox=_bbox(index),
                source_objects=_rect_source(index),
                data={
                    "control_type": "checkbox",
                    "state": "unchecked",
                    "origin": "static_vector",
                },
            )
        )
        relationships.extend(
            (
                ("contains", "group:g", token),
                ("control_of", token, "group:g"),
            )
        )
    return ir, _candidate(
        anchors,
        records=records,
        relationships=relationships,
    )


def _field_candidate(count: int) -> tuple[DocumentIR, semantics._GroupCandidate]:
    ir, anchors = _predecessor(1)
    label_token = "label:shared"
    records = [
        semantics._RecordCandidate(
            token=label_token,
            role="label",
            key="shared",
            bbox=_bbox(10_000),
            source_objects=_rect_source(10_000),
            data={"label_role": "field", "text": "L", "raw_text": "L"},
        )
    ]
    relationships = [("contains", "group:g", label_token)]
    for index in range(count):
        field_token = f"field:{index}"
        value_token = f"value-region:{index}"
        source = _rect_source(index)
        records.extend(
            (
                semantics._RecordCandidate(
                    token=field_token,
                    role="field",
                    key=f"f{index}",
                    bbox=_bbox(index),
                    source_objects=source,
                    data={"value": None, "value_state": "empty"},
                ),
                semantics._RecordCandidate(
                    token=value_token,
                    role="value_region",
                    key=f"f{index}",
                    bbox=_bbox(index),
                    source_objects=source,
                    data={"value": None, "value_state": "empty"},
                ),
            )
        )
        relationships.extend(
            (
                ("contains", "group:g", field_token),
                ("contains", field_token, value_token),
                ("value_of", value_token, field_token),
                ("label_of", label_token, field_token),
            )
        )
    return ir, _candidate(
        anchors,
        records=records,
        relationships=relationships,
    )


def _label_candidate(count: int) -> tuple[DocumentIR, semantics._GroupCandidate]:
    ir, anchors = _predecessor(1)
    control_token = "control:owner"
    records = [
        semantics._RecordCandidate(
            token=control_token,
            role="control",
            key="owner",
            bbox=_bbox(10_000),
            source_objects=_rect_source(10_000),
            data={
                "control_type": "checkbox",
                "state": "unchecked",
                "origin": "static_vector",
            },
        )
    ]
    relationships = [
        ("contains", "group:g", control_token),
        ("control_of", control_token, "group:g"),
    ]
    for index in range(count):
        token = f"label:{index}"
        records.append(
            semantics._RecordCandidate(
                token=token,
                role="label",
                key=f"l{index}",
                bbox=_bbox(index),
                source_objects=_rect_source(index),
                data={"label_role": "group", "text": "L", "raw_text": "L"},
            )
        )
        relationships.extend(
            (
                ("contains", "group:g", token),
                ("label_of", token, "group:g"),
            )
        )
    return ir, _candidate(
        anchors,
        records=records,
        relationships=relationships,
    )


def _pair_candidate(
    count: int,
    *,
    exact_custody: bool = False,
) -> tuple[DocumentIR, semantics._GroupCandidate]:
    contributor_count = 2 * count if exact_custody else 2
    ir, anchors = _predecessor(contributor_count)
    records: list[semantics._RecordCandidate] = []
    relationships: list[tuple[str, str, str]] = []
    for index in range(count):
        pair_token = f"pair:{index}"
        label_token = f"label:{index}"
        value_token = f"value-region:{index}"
        key_anchor = anchors[2 * index if exact_custody else 0]
        value_anchor = anchors[2 * index + 1 if exact_custody else 1]
        key_source = _character_source(2 * index)
        value_source = _character_source(2 * index + 1)
        records.extend(
            (
                semantics._RecordCandidate(
                    token=pair_token,
                    role="key_value_pair",
                    key=f"p{index}",
                    bbox=_bbox(3 * index),
                    source_objects=(*key_source, *value_source),
                    data={
                        "key": "K",
                        "value": "V",
                        "key_source_item_id": key_anchor[0],
                        "value_source_item_id": value_anchor[0],
                        "key_source_element_id": key_anchor[1],
                        "value_source_element_id": value_anchor[1],
                    },
                ),
                semantics._RecordCandidate(
                    token=label_token,
                    role="label",
                    key=f"p{index}",
                    bbox=_bbox(3 * index + 1),
                    source_objects=key_source,
                    data={"label_role": "key", "text": "K", "raw_text": "K"},
                ),
                semantics._RecordCandidate(
                    token=value_token,
                    role="value_region",
                    key=f"p{index}",
                    bbox=_bbox(3 * index + 2),
                    source_objects=value_source,
                    data={"value": "V", "value_state": "present"},
                ),
            )
        )
        relationships.extend(
            (
                ("contains", "group:g", pair_token),
                ("contains", pair_token, label_token),
                ("contains", pair_token, value_token),
                ("key_of", label_token, pair_token),
                ("value_of", value_token, pair_token),
            )
        )
    return ir, _candidate(
        anchors,
        records=records,
        relationships=relationships,
        source_objects=_character_source(100_000),
        canonical_mode="replace",
    )


def _materialize(
    ir: DocumentIR,
    candidate: semantics._GroupCandidate,
) -> tuple[DocumentIR, dict[str, Any], int]:
    semantics._materialize_group(ir, candidate)
    validated = DocumentIR.model_validate(ir.model_dump(mode="json"))
    anchor = next(
        element
        for element in validated.elements
        if element.id == candidate.anchor_element_id
    )
    legacy = anchor.properties["legacy_item"]
    sidecar = {
        key: legacy[key]
        for key in semantics._PUBLIC_FORM_KEYS
        if key in legacy
    }
    sidecar["relationships"] = [
        value
        for value in legacy["relationships"]
        if value.get("canonical_inert") is True
    ]
    compact_size = semantics._compact_json_size(sidecar)
    assert compact_size == len(
        json.dumps(sidecar, ensure_ascii=False, separators=(",", ":")).encode()
    )
    return validated, sidecar, compact_size


@pytest.mark.parametrize(
    ("factory", "count", "expected_counts", "expected_size"),
    (
        (_control_candidate, 256, {"form_controls": 256}, 259_952),
        (
            _field_candidate,
            128,
            {"form_fields": 128, "form_value_regions": 128, "form_labels": 1},
            260_530,
        ),
        (
            _label_candidate,
            256,
            {"form_labels": 256, "form_controls": 1},
            247_413,
        ),
        (
            _pair_candidate,
            32,
            {
                "form_key_value_pairs": 32,
                "form_labels": 32,
                "form_value_regions": 32,
            },
            93_075,
        ),
    ),
)
def test_exact_group_caps_materialize_inside_full_public_json_limit(
    factory: CandidateFactory,
    count: int,
    expected_counts: dict[str, int],
    expected_size: int,
) -> None:
    ir, candidate = factory(count)

    assert semantics._page_candidates_within_limits((candidate,)) is True
    _validated, sidecar, compact_size = _materialize(ir, candidate)

    assert compact_size == expected_size
    assert compact_size <= semantics.MAX_PUBLIC_GROUP_BYTES
    assert {
        key: len(sidecar[key]) for key in expected_counts
    } == expected_counts


@pytest.mark.parametrize(
    ("factory", "exact_count", "overflow_count"),
    (
        (_control_candidate, 256, 257),
        (_field_candidate, 128, 129),
        (_label_candidate, 256, 257),
        (_pair_candidate, 32, 33),
    ),
)
def test_group_cap_max_plus_one_is_refused_before_materialization(
    factory: CandidateFactory,
    exact_count: int,
    overflow_count: int,
) -> None:
    _exact_ir, exact = factory(exact_count)
    _overflow_ir, overflow = factory(overflow_count)

    assert semantics._page_candidates_within_limits((exact,)) is True
    assert semantics._page_candidates_within_limits((overflow,)) is False


def test_pair_32_real_custody_succeeds_and_pair_33_contributors_refuse() -> None:
    exact_ir, exact = _pair_candidate(32, exact_custody=True)
    _validated, sidecar, compact_size = _materialize(exact_ir, exact)

    assert len(sidecar["form_group"]["contributor_element_ids"]) == 64
    assert len(sidecar["form_key_value_pairs"]) == 32
    assert compact_size == 95_105
    assert compact_size <= semantics.MAX_PUBLIC_GROUP_BYTES

    overflow_ir, overflow = _pair_candidate(33, exact_custody=True)
    assert semantics._page_candidates_within_limits((overflow,)) is False
    with pytest.raises(ValidationError, match="at most 64 items"):
        semantics._materialize_group(overflow_ir, overflow)


def test_thirteen_distinct_concerns_succeed_and_fourteen_refuse() -> None:
    codes = tuple(sorted(semantics._ALLOWED_CONCERNS))
    assert len(codes) == 13
    ir, base = _control_candidate(1)
    exact = replace(base, concern_codes=codes)

    assert semantics._page_candidates_within_limits((exact,)) is True
    _validated, sidecar, _compact_size = _materialize(ir, exact)
    assert sidecar["form_group"]["concern_codes"] == list(codes)

    overflow_ir, overflow_base = _control_candidate(1)
    overflow = replace(overflow_base, concern_codes=(*codes, codes[0]))
    assert semantics._page_candidates_within_limits((overflow,)) is False
    with pytest.raises(ValueError, match="unsupported concerns"):
        semantics._materialize_group(overflow_ir, overflow)
