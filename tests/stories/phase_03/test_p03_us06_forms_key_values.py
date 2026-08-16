"""Acceptance coverage for P03-US06 form and key/value semantics."""

from __future__ import annotations

import hashlib
import io
import json
import math
from copy import deepcopy
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import pdfplumber
import pytest
from pdfminer.psparser import LIT

from app.config import Settings
from app.services.acroform import (
    AcroFormPageInput,
    inspect_acroform,
    validate_acroform_graph,
)
from app.services.acroform_raw import RawAcroFormAuditError
from app.services.form_semantics import (
    PublicFormControl,
    PublicFormField,
    PublicFormGroup,
    PublicFormLabel,
    PublicKeyValuePair,
    _complete_public_static_parties_and_insurers,
    _render_static_parties_and_insurers,
    extract_form_evidence,
    form_processing_summary,
    strip_form_semantics_public,
)
from app.services.pipeline import parse_document
from tests.fixtures.phase_03.form_semantics.oracle import (
    ACORD_CANONICAL_INERT_ORACLE,
    ACORD_CONTROL_ORACLE,
    ACORD_EMPTY_FIELD_ORACLE,
    ACORD_FIELD_BOUNDARY_SOURCE_OBJECTS,
    ACORD_GROUP_ORACLE,
    ACORD_LABEL_ORACLE,
    ACORD_REVIEWED_COUNTS,
    COMPONENT_CANONICAL_ORACLE,
    COMPONENT_KEY_VALUE_ORACLE,
    COMPONENT_REVIEWED_COUNTS,
    SOURCE_IDENTITIES,
)
from tests.fixtures.phase_03.form_semantics.synthetic import (
    ACROFORM_GRAPH_CASES,
    build_acroform_graph,
    build_synthetic_fixture,
)


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
FORM_RELATIONSHIP_TYPES = frozenset(
    {
        "contains",
        "label_of",
        "value_of",
        "control_of",
        "key_of",
        "form_overlay_of",
    }
)


def _settings(*, forms: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
        layout_text_run_semantics_enabled=True,
        layout_forms_enabled=forms,
    )


@lru_cache(maxsize=None)
def _parse(case: str, forms: bool) -> dict[str, Any]:
    path = CORPUS / f"{case}.pdf"
    return parse_document(
        path.read_bytes(),
        path.name,
        _settings(forms=forms),
    ).model_dump(mode="json", exclude_none=False)


@lru_cache(maxsize=None)
def _parse_synthetic(fixture_id: str, forms: bool) -> dict[str, Any]:
    payload = build_synthetic_fixture(fixture_id)["payload"]
    assert isinstance(payload, dict)
    source = payload["pdf_bytes"]
    assert isinstance(source, bytes)
    return parse_document(
        source,
        f"{fixture_id.rsplit(':', maxsplit=1)[-1]}.pdf",
        _settings(forms=forms),
    ).model_dump(mode="json", exclude_none=False)


def _anchors(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for page in payload["pages"]
        for item in page["items"]
        if item.get("layout_forms_projected") is True
    ]


def _inspect_synthetic_acroform(fixture_id: str) -> tuple[dict[str, Any], Any]:
    fixture = build_synthetic_fixture(fixture_id)
    payload = fixture["payload"]
    assert isinstance(payload, dict)
    source = payload["pdf_bytes"]
    assert isinstance(source, bytes)
    return payload, _inspect_acroform_bytes(source)


def _inspect_acroform_bytes(source: bytes) -> Any:
    with pdfplumber.open(io.BytesIO(source)) as pdf:
        pages = tuple(
            AcroFormPageInput(
                page_index=page_index,
                width=float(page.width),
                height=float(page.height),
                annotations=page.page_obj.attrs.get("Annots", ()),
                annotations_present="Annots" in page.page_obj.attrs,
                rotation=int(page.rotation or 0),
                page_object_id=int(page.page_obj.pageid),
                media_box=page.page_obj.attrs.get("MediaBox"),
                crop_box=page.page_obj.attrs.get(
                    "CropBox",
                    page.page_obj.attrs.get("MediaBox"),
                ),
                user_unit=page.page_obj.attrs.get("UserUnit", 1),
            )
            for page_index, page in enumerate(pdf.pages, start=1)
        )
        result = inspect_acroform(
            catalog=pdf.doc.catalog,
            pages=pages,
            source_sha256=hashlib.sha256(source).hexdigest(),
        )
    return result


def _bbox(record: Mapping[str, Any]) -> tuple[float, float, float, float]:
    bbox = record["bbox"]
    return (
        float(bbox["x"]),
        float(bbox["y"]),
        float(bbox["width"]),
        float(bbox["height"]),
    )


def _form_relationships(anchor: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        relationship
        for relationship in anchor["relationships"]
        if relationship.get("type") in FORM_RELATIONSHIP_TYPES
        and relationship.get("canonical_inert") is True
    ]


def _source_objects(
    record: Mapping[str, Any],
) -> tuple[tuple[Any, ...], ...]:
    normalized: list[tuple[Any, ...]] = []
    for source in record["source_objects"]:
        if source["kind"] == "character_range":
            normalized.append(
                ("character_range", source["start"], source["end"])
            )
        elif source["kind"] in {"line", "rect"}:
            normalized.append((source["kind"], source["index"]))
        else:
            normalized.append(
                (source["kind"], source["object_ref_digest"])
            )
    return tuple(normalized)


def _canonical_block(
    payload: Mapping[str, Any],
    primary_element_id: str,
) -> dict[str, Any]:
    matches = [
        block
        for page in payload["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block["primary_element_id"] == primary_element_id
    ]
    assert len(matches) == 1
    return matches[0]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _semantic_without_timings(payload: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    processing = detached.get("processing") or {}
    processing.pop("duration_ms", None)
    form_summary = processing.get("form_semantics")
    if isinstance(form_summary, dict):
        for key in ("extraction_ms", "projection_ms", "total_ms"):
            form_summary.pop(key, None)
    return detached


def test_processing_summary_is_exact_bounded_and_nonfinite_safe() -> None:
    assert form_processing_summary(None) == {
        "extraction_ms": 0.0,
        "projection_ms": 0.0,
        "total_ms": 0.0,
    }
    assert form_processing_summary(
        {
            "extraction_ms": 1.23456,
            "projection_ms": 2.34567,
            "total_ms": 1.0,
            "ignored": 99.0,
        }
    ) == {
        "extraction_ms": 1.235,
        "projection_ms": 2.346,
        "total_ms": 3.58,
    }
    summary = form_processing_summary(
        {
            "extraction_ms": math.inf,
            "projection_ms": math.nan,
            "total_ms": -1.0,
        }
    )
    assert summary == {
        "extraction_ms": 0.0,
        "projection_ms": 0.0,
        "total_ms": 0.0,
    }


def test_strip_removes_only_sidecar_referenced_form_descriptors() -> None:
    form_relationship = {
        "id": "form-rel-1",
        "type": "contains",
        "source_id": "form-group-1",
        "target_id": "form-pair-1",
        "evidence_ids": [],
        "canonical_inert": True,
    }
    unrelated = {
        "id": "predecessor-rel",
        "type": "contains",
        "source_id": "legacy-a",
        "target_id": "legacy-b",
        "evidence_ids": [],
        "canonical_inert": True,
    }
    source = {
        "pages": [
            {
                "items": [
                    {
                        "id": "p1-i1",
                        "layout_forms_projected": True,
                        "form_policy": "p03-form-semantics-v1",
                        "form_group": {
                            "relationship_ids": ["form-rel-1"],
                            "anchor_relationship_ids": [],
                        },
                        "relationships": [unrelated, form_relationship],
                    }
                ]
            }
        ]
    }
    cleaned = strip_form_semantics_public(source)
    assert source["pages"][0]["items"][0]["layout_forms_projected"] is True
    assert cleaned == {
        "pages": [
            {
                "items": [
                    {
                        "id": "p1-i1",
                        "relationships": [unrelated],
                    }
                ]
            }
        ]
    }


@pytest.mark.parametrize(
    ("fixture_id", "expected_states"),
    [
        (
            "synthetic:p03-us06:interactive-controls-v1",
            (
                ("selected-checkbox", "checkbox", "checked"),
                ("unselected-checkbox", "checkbox", "unchecked"),
                ("inherited-radio", "radio", "checked"),
                ("inherited-radio", "radio", "unchecked"),
                (
                    "explicit-not-applicable",
                    "checkbox",
                    "not_applicable",
                ),
            ),
        ),
        (
            "synthetic:p03-us06:mixed-static-interactive-v1",
            (("mixed-widget", "checkbox", "checked"),),
        ),
    ],
)
def test_acroform_widgets_are_bounded_typed_and_source_grounded(
    fixture_id: str,
    expected_states: tuple[tuple[str, str, str], ...],
) -> None:
    payload, result = _inspect_synthetic_acroform(fixture_id)

    assert result.interactivity == "interactive"
    assert result.concern_codes == ()
    controls = tuple(
        control for page in result.pages for control in page.controls
    )
    assert tuple(
        (control.field_name, control.control_type, control.state)
        for control in controls
    ) == expected_states
    assert all(
        control.bbox[2:] == (12.0, 12.0)
        and len(control.object_ref_digest) == 64
        and len(control.field_ref_digest) == 64
        for control in controls
    )
    excluded = {
        record["record_key"]
        for record in payload["expected_records"]
        if record.get("expected_action") == "exclude"
    }
    assert excluded == (
        {"excluded-pushbutton"}
        if fixture_id.endswith("interactive-controls-v1")
        else set()
    )
    assert all(control.field_name not in excluded for control in controls)


@pytest.mark.parametrize(
    ("fixture_id", "expected_interactivity", "expected_states"),
    [
        (
            "synthetic:p03-us06:interactive-controls-v1",
            "interactive",
            ("checked", "unchecked", "checked", "unchecked", "not_applicable"),
        ),
        (
            "synthetic:p03-us06:mixed-static-interactive-v1",
            "mixed",
            ("checked",),
        ),
        (
            "synthetic:p03-us06:orphan-widget-v1",
            "unknown",
            ("ambiguous",),
        ),
    ],
)
def test_acroform_inspection_is_threaded_into_immutable_source_report(
    fixture_id: str,
    expected_interactivity: str,
    expected_states: tuple[str, ...],
) -> None:
    payload = build_synthetic_fixture(fixture_id)["payload"]
    assert isinstance(payload, dict)
    source = payload["pdf_bytes"]
    assert isinstance(source, bytes)

    report = extract_form_evidence(source)

    assert report.interactivity == expected_interactivity
    assert tuple(
        control.state
        for page in report.pages
        for control in page.interactive_controls
    ) == expected_states
    assert len(report.concern_codes) == len(set(report.concern_codes))
    assert report.concern_codes == (
        ("form_interactivity_unknown",)
        if expected_interactivity == "unknown"
        else ()
    )


def test_cyclic_acroform_fails_the_raw_production_gate_closed() -> None:
    payload = build_synthetic_fixture(
        "synthetic:p03-us06:cyclic-acroform-v1"
    )["payload"]
    assert isinstance(payload, dict)
    source = payload["pdf_bytes"]
    assert isinstance(source, bytes)

    with pytest.raises(
        RawAcroFormAuditError,
        match="structural audit failed closed",
    ):
        extract_form_evidence(source)


def test_interactive_controls_project_through_the_ordinary_parser() -> None:
    payload = _parse_synthetic(
        "synthetic:p03-us06:interactive-controls-v1",
        True,
    )
    anchors = _anchors(payload)

    assert len(anchors) == 1
    [anchor] = anchors
    assert anchor["form_group"]["interactivity"] == "interactive"
    assert anchor["form_group"]["canonical_mode"] == "inert"
    assert tuple(
        (
            control["control_type"],
            control["state"],
            control["origin"],
            _bbox(control),
        )
        for control in anchor["form_controls"]
    ) == (
        ("checkbox", "checked", "interactive_widget", (50.0, 38.0, 12.0, 12.0)),
        (
            "checkbox",
            "unchecked",
            "interactive_widget",
            (50.0, 73.0, 12.0, 12.0),
        ),
        ("radio", "checked", "interactive_widget", (50.0, 108.0, 12.0, 12.0)),
        (
            "radio",
            "unchecked",
            "interactive_widget",
            (50.0, 143.0, 12.0, 12.0),
        ),
        (
            "checkbox",
            "not_applicable",
            "interactive_widget",
            (50.0, 213.0, 12.0, 12.0),
        ),
    )
    assert all(
        control["evidence_methods"] == ["native"]
        and {source["kind"] for source in control["source_objects"]}
        == {"field", "widget"}
        for control in anchor["form_controls"]
    )
    assert {label["text"] for label in anchor["form_labels"]} == {
        "Selected checkbox",
        "Unselected checkbox",
        "Selected radio",
        "Unselected radio",
        "Explicit not applicable",
    }
    assert Counter(
        relationship["type"] for relationship in _form_relationships(anchor)
    ) == {"contains": 10, "label_of": 5, "control_of": 5}


def test_mixed_static_and_interactive_controls_share_exact_page_state() -> None:
    payload = _parse_synthetic(
        "synthetic:p03-us06:mixed-static-interactive-v1",
        True,
    )
    anchors = _anchors(payload)

    assert len(anchors) == 1
    [anchor] = anchors
    assert anchor["form_group"]["interactivity"] == "mixed"
    assert {
        (control["origin"], control["state"], _bbox(control))
        for control in anchor["form_controls"]
    } == {
        ("static_vector", "unchecked", (50.0, 58.0, 12.0, 12.0)),
        ("interactive_widget", "checked", (50.0, 98.0, 12.0, 12.0)),
    }


def test_static_checked_and_unchecked_controls_project_exactly() -> None:
    payload = _parse_synthetic(
        "synthetic:p03-us06:static-controls-v1",
        True,
    )
    anchors = _anchors(payload)

    assert len(anchors) == 1
    [anchor] = anchors
    assert anchor["form_group"]["interactivity"] == "static"
    assert {
        (control["state"], control["origin"], _bbox(control))
        for control in anchor["form_controls"]
    } == {
        ("unchecked", "static_vector", (72.0, 58.0, 12.0, 12.0)),
        ("checked", "static_vector", (72.0, 98.0, 12.0, 12.0)),
    }
    assert {label["text"] for label in anchor["form_labels"]} == {
        "Unchecked source control",
        "Checked source control",
    }


def test_present_and_ambiguous_ruled_fields_project_without_fabrication() -> None:
    payload = _parse_synthetic(
        "synthetic:p03-us06:field-values-v1",
        True,
    )
    anchors = _anchors(payload)

    fields = [
        field for anchor in anchors for field in anchor.get("form_fields", [])
    ]
    assert {
        (_bbox(field), field["value"], field["value_state"])
        for field in fields
    } == {
        ((130.0, 50.0, 100.0, 20.0), "ALPHA", "present"),
        ((130.0, 100.0, 100.0, 20.0), None, "ambiguous"),
    }
    ambiguous = next(
        field for field in fields if field["value_state"] == "ambiguous"
    )
    assert "form_value_state_ambiguous" in ambiguous["concern_codes"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert '"value": ""' not in serialized


@pytest.mark.parametrize(
    "fixture_id",
    [
        "synthetic:p03-us06:orphan-widget-v1",
        "synthetic:p03-us06:cyclic-acroform-v1",
    ],
)
def test_malformed_acroform_fails_closed_without_source_diagnostics(
    fixture_id: str,
) -> None:
    payload, result = _inspect_synthetic_acroform(fixture_id)

    assert result.interactivity == payload["expected_interactivity"] == "unknown"
    assert result.concern_codes == ("form_interactivity_unknown",)
    assert all(
        page.interactivity == "unknown"
        and page.concern_codes == ("form_interactivity_unknown",)
        for page in result.pages
    )
    controls = tuple(
        control for page in result.pages for control in page.controls
    )
    if fixture_id.endswith("orphan-widget-v1"):
        assert tuple(control.state for control in controls) == ("ambiguous",)
        assert controls[0].concern_codes == (
            "form_control_state_ambiguous",
        )
    else:
        assert controls == ()
    serialized = repr(result)
    assert "orphan-widget" not in serialized
    assert "cycle-parent" not in serialized


@pytest.mark.parametrize("case_id", tuple(ACROFORM_GRAPH_CASES))
def test_acroform_exact_and_max_plus_one_limits(case_id: str) -> None:
    case = ACROFORM_GRAPH_CASES[case_id]
    result = validate_acroform_graph(build_acroform_graph(case_id))

    if case["expected"] == "accepted":
        assert result.accepted is True
        assert result.violated_limit is None
    else:
        assert result.accepted is False
        assert result.violated_limit == case["violated_limit"]


@pytest.mark.parametrize(
    ("pages", "accepted", "violated_limit"),
    [
        ((2_048,), True, None),
        ((2_049,), False, "form_source_limit"),
        ((2_000, 2_000, 2_000, 2_000, 2_000), True, None),
        ((2_000, 2_000, 2_000, 2_000, 2_001), False, "form_source_limit"),
    ],
)
def test_annotation_page_and_document_limits_are_inclusive(
    pages: tuple[int, ...],
    accepted: bool,
    violated_limit: str | None,
) -> None:
    link = {"Subtype": LIT("Link")}
    result = inspect_acroform(
        catalog={},
        pages=tuple(
            AcroFormPageInput(
                page_index=index,
                width=300.0,
                height=300.0,
                annotations=tuple(link for _ in range(annotation_count)),
            )
            for index, annotation_count in enumerate(pages, start=1)
        ),
        source_sha256="0" * 64,
    )

    assert (result.interactivity != "unknown") is accepted
    assert result.concern_codes == (
        () if violated_limit is None else (violated_limit,)
    )


def test_acroform_deadline_fails_closed_with_sanitized_concern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def monotonic() -> float:
        nonlocal calls
        calls += 1
        return 0.0 if calls == 1 else 3.0

    monkeypatch.setattr("app.services.acroform.time.monotonic", monotonic)
    result = inspect_acroform(
        catalog={},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=300.0,
                height=300.0,
                annotations=(),
            ),
        ),
        source_sha256="0" * 64,
        deadline_seconds=2.0,
    )

    assert result.interactivity == "unknown"
    assert result.concern_codes == ("form_source_evidence_unavailable",)
    assert result.pages[0].controls == ()


@pytest.mark.integration
def test_real_link_annotations_are_not_form_widgets() -> None:
    source = (CORPUS / "component-datasheet.pdf").read_bytes()
    result = _inspect_acroform_bytes(source)

    assert result.interactivity == "none"
    assert result.concern_codes == ()
    assert result.field_node_count == 0
    assert all(page.controls == () for page in result.pages)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("case", "identity_key"),
    [
        ("insurance-acord", "insurance-acord"),
        ("component-datasheet", "component-datasheet"),
    ],
)
def test_real_source_report_is_local_immutable_and_hash_bound(
    case: str,
    identity_key: str,
) -> None:
    identity = SOURCE_IDENTITIES[identity_key]
    path = CORPUS / f"{case}.pdf"
    source = path.read_bytes()
    report = extract_form_evidence(source, max_pages=100)

    assert len(source) == identity["size_bytes"]
    assert hashlib.sha256(source).hexdigest() == identity["sha256"]
    assert report.source_sha256 == identity["sha256"]
    assert len(report.pages) == identity["page_count"]
    assert report.report_version == "p03-form-source-evidence-v1"
    assert report.policy_id == "p03-form-semantics-v1"
    assert report.extraction_ms >= 0
    with pytest.raises(AttributeError):
        report.pages = ()  # type: ignore[misc]


@pytest.mark.integration
def test_component_pairs_and_canonical_replacements_match_reviewed_oracle() -> None:
    payload = _parse("component-datasheet", True)
    anchors = _anchors(payload)
    by_key = {anchor["form_group"]["group_key"]: anchor for anchor in anchors}

    assert set(by_key) == {
        oracle["group_key"] for oracle in COMPONENT_KEY_VALUE_ORACLE
    }
    assert sum(
        len(anchor.get("form_key_value_pairs", [])) for anchor in anchors
    ) == COMPONENT_REVIEWED_COUNTS["pair_count"]
    assert sum(
        len(_form_relationships(anchor)) for anchor in anchors
    ) == COMPONENT_REVIEWED_COUNTS["total_relationship_count"]

    for oracle in COMPONENT_KEY_VALUE_ORACLE:
        group_key = oracle["group_key"]
        anchor = by_key[group_key]
        group = anchor["form_group"]
        pairs = anchor["form_key_value_pairs"]
        assert anchor["id"] == oracle["anchor_public_item_id"]
        assert group["anchor_element_id"] == oracle["anchor_element_id"]
        assert tuple(group["contributor_public_item_ids"]) == oracle[
            "contributor_public_item_ids"
        ]
        assert tuple(group["contributor_element_ids"]) == oracle[
            "contributor_element_ids"
        ]
        assert group["canonical_mode"] == "replace"
        assert _bbox(group) == oracle["bbox"]
        assert tuple((pair["key"], pair["value"]) for pair in pairs) == oracle[
            "pairs"
        ]
        block = _canonical_block(payload, group["anchor_element_id"])
        expected = COMPONENT_CANONICAL_ORACLE[group_key]
        assert _sha256_text(block["markdown"]) == expected["markdown_sha256"]
        assert _sha256_text(block["text"]) == expected["text_sha256"]
        assert block["contributing_element_ids"] == [
            group["anchor_element_id"],
            *[
                element_id
                for element_id in group["contributor_element_ids"]
                if element_id != group["anchor_element_id"]
            ],
        ]

    relationship_counts = Counter(
        relationship["type"]
        for anchor in anchors
        for relationship in _form_relationships(anchor)
    )
    assert relationship_counts == {
        "contains": COMPONENT_REVIEWED_COUNTS[
            "contains_relationship_count"
        ],
        "key_of": COMPONENT_REVIEWED_COUNTS["key_relationship_count"],
        "value_of": COMPONENT_REVIEWED_COUNTS["value_relationship_count"],
    }


@pytest.mark.integration
def test_acord_static_form_graph_is_exact_with_selective_canonical_replacement() -> None:
    payload = _parse("insurance-acord", True)
    anchors = _anchors(payload)
    by_key = {anchor["form_group"]["group_key"]: anchor for anchor in anchors}

    assert len(anchors) == ACORD_REVIEWED_COUNTS["group_count"]
    assert set(by_key) == {oracle["group_key"] for oracle in ACORD_GROUP_ORACLE}
    assert sum(len(anchor.get("form_labels", [])) for anchor in anchors) == (
        ACORD_REVIEWED_COUNTS["total_label_count"]
    )
    assert sum(len(anchor.get("form_fields", [])) for anchor in anchors) == (
        ACORD_REVIEWED_COUNTS["empty_field_count"]
    )
    assert sum(len(anchor.get("form_controls", [])) for anchor in anchors) == (
        ACORD_REVIEWED_COUNTS["control_count"]
    )
    assert sum(
        len(_form_relationships(anchor)) for anchor in anchors
    ) == ACORD_REVIEWED_COUNTS["total_relationship_count"]

    for oracle in ACORD_GROUP_ORACLE:
        anchor = by_key[oracle["group_key"]]
        group = anchor["form_group"]
        assert anchor["id"] == oracle["anchor_public_item_id"]
        assert group["anchor_element_id"] == oracle["anchor_element_id"]
        assert tuple(group["contributor_public_item_ids"]) == oracle[
            "contributor_public_item_ids"
        ]
        assert tuple(group["contributor_element_ids"]) == oracle[
            "contributor_element_ids"
        ]
        assert group["canonical_mode"] == oracle["canonical_mode"]
        assert group["status"] == oracle["status"]
        assert _bbox(group) == oracle["bbox"]
        assert _source_objects(group) == oracle["source_objects"]
        assert {field["field_key"] for field in anchor.get("form_fields", [])} == (
            set(oracle["field_keys"])
        )
        assert {label["text"] for label in anchor.get("form_labels", [])}
        assert all(
            field["value"] is None and field["value_state"] == "empty"
            for field in anchor.get("form_fields", [])
        )

    controls = [
        control
        for anchor in anchors
        for control in anchor.get("form_controls", [])
    ]
    assert Counter(control["state"] for control in controls) == {
        "unchecked": ACORD_REVIEWED_COUNTS["unchecked_control_count"],
        "ambiguous": ACORD_REVIEWED_COUNTS["ambiguous_control_count"],
    }
    fields_by_key = {
        field["field_key"]: field
        for anchor in anchors
        for field in anchor.get("form_fields", [])
    }
    for expected in ACORD_EMPTY_FIELD_ORACLE:
        actual = fields_by_key[expected["field_key"]]
        assert _bbox(actual) == expected["bbox"]
        assert actual["value"] is None
        assert actual["value_state"] == "empty"
        assert _source_objects(actual) == ACORD_FIELD_BOUNDARY_SOURCE_OBJECTS[
            expected["field_key"]
        ]

    labels = [
        label
        for anchor in anchors
        for label in anchor.get("form_labels", [])
    ]
    labels_by_text_bbox = {
        (label["text"], _bbox(label)): label for label in labels
    }
    for expected in ACORD_LABEL_ORACLE:
        actual = labels_by_text_bbox[(expected["text"], expected["bbox"])]
        assert actual["raw_text"] == expected["raw_text"]
        assert actual["label_role"] == expected["label_role"]
        assert _source_objects(actual) == tuple(
            ("character_range", start, end)
            for start, end in expected["source_character_ranges"]
        )

    labels_by_id = {label["id"]: label for label in labels}
    controls_by_bbox = {_bbox(control): control for control in controls}
    for expected in ACORD_CONTROL_ORACLE:
        actual = controls_by_bbox[expected["bbox"]]
        assert actual["control_type"] == expected["control_type"]
        assert actual["origin"] == expected["origin"]
        assert actual["state"] == expected["state"]
        assert _source_objects(actual) == expected["source_objects"]
        if expected["label"] is None:
            assert actual["label_id"] is None
        else:
            assert labels_by_id[actual["label_id"]]["text"] == expected["label"]

    relationship_counts = Counter(
        relationship["type"]
        for anchor in anchors
        for relationship in _form_relationships(anchor)
    )
    assert relationship_counts == {
        "contains": ACORD_REVIEWED_COUNTS["contains_relationship_count"],
        "label_of": ACORD_REVIEWED_COUNTS[
            "total_label_relationship_count"
        ],
        "value_of": ACORD_REVIEWED_COUNTS["value_relationship_count"],
        "control_of": ACORD_REVIEWED_COUNTS[
            "control_relationship_count"
        ],
        "form_overlay_of": ACORD_REVIEWED_COUNTS[
            "form_overlay_relationship_count"
        ],
    }

    canonical = payload["canonical_presentation"]
    for scope in ("body", "full"):
        for representation in ("markdown", "text"):
            value = canonical[scope][representation]
            prefix = f"{scope}_{representation}"
            assert len(value.encode("utf-8")) == ACORD_CANONICAL_INERT_ORACLE[
                f"{prefix}_utf8_bytes"
            ]
            assert _sha256_text(value) == ACORD_CANONICAL_INERT_ORACLE[
                f"{prefix}_sha256"
            ]

    parties = by_key["parties-and-insurers"]
    parties_group = parties["form_group"]
    parties_block = next(
        block
        for block in canonical["pages"][0]["blocks"]
        if block["primary_element_id"] == parties_group["anchor_element_id"]
    )
    assert parties_block["primary_element_type"] == "table"
    assert parties_block["contributing_element_ids"] == [
        parties_group["anchor_element_id"],
        *(
            element_id
            for element_id in parties_group["contributor_element_ids"]
            if element_id != parties_group["anchor_element_id"]
        ),
    ]
    assert (
        parties_block["markdown"].count(
            "| --- | --- | --- | --- | --- | --- |"
        )
        == 1
    )
    for label in parties["form_labels"]:
        assert parties_block["markdown"].count(label["text"]) == 1
    for contributor_element_id in parties_group["contributor_element_ids"]:
        if contributor_element_id == parties_group["anchor_element_id"]:
            continue
        suppressed = next(
            block
            for block in canonical["pages"][0]["blocks"]
            if block["primary_element_id"] == contributor_element_id
        )
        assert suppressed["markdown"] == ""
        assert suppressed["text"] == ""
        assert suppressed["omission_reason"] == "consumed_by_relationship"
        assert (
            suppressed["suppressed_by_element_id"]
            == parties_group["anchor_element_id"]
        )

    serialized = json.dumps(payload, ensure_ascii=False).casefold()
    assert "[signature]" not in serialized
    assert "empty source-visible field" not in serialized
    assert "phone name:" not in canonical["full"]["markdown"].casefold()


@pytest.mark.integration
def test_acord_parties_replacement_revalidates_complete_blank_source_graph() -> None:
    payload = _parse("insurance-acord", True)
    anchor = next(
        item
        for item in _anchors(payload)
        if item["form_group"]["group_key"] == "parties-and-insurers"
    )
    group = PublicFormGroup.model_validate(anchor["form_group"])
    fields = [
        PublicFormField.model_validate(field)
        for field in anchor["form_fields"]
    ]
    labels = [
        PublicFormLabel.model_validate(label)
        for label in anchor["form_labels"]
    ]
    controls = [
        PublicFormControl.model_validate(control)
        for control in anchor.get("form_controls", [])
    ]
    pairs = [
        PublicKeyValuePair.model_validate(pair)
        for pair in anchor.get("key_value_pairs", [])
    ]

    def complete(
        *,
        candidate_group: PublicFormGroup = group,
        candidate_fields: list[PublicFormField] = fields,
        candidate_labels: list[PublicFormLabel] = labels,
    ) -> tuple[str, ...] | None:
        return _complete_public_static_parties_and_insurers(
            group=candidate_group,
            fields=candidate_fields,
            labels=candidate_labels,
            controls=controls,
            pairs=pairs,
        )

    assert complete() == ("a", "b", "c", "d", "e", "f")
    rendered = _render_static_parties_and_insurers(
        group=group,
        fields=fields,
        labels=labels,
        controls=controls,
        pairs=pairs,
    )
    assert rendered is not None
    rendered_markdown, rendered_text = rendered
    assert "| --- | --- | --- | --- |" in rendered_markdown
    assert "empty source-visible field" not in rendered_markdown.casefold()
    assert "empty source-visible field" not in rendered_text.casefold()
    assert all(field.value is None for field in fields)
    assert all(field.value_state == "empty" for field in fields)

    entered_fields = deepcopy(fields)
    entered_index = next(
        index
        for index, field in enumerate(entered_fields)
        if field.field_key == "contact-name"
    )
    entered_fields[entered_index] = entered_fields[entered_index].model_copy(
        update={"value": "Synthetic entry", "value_state": "present"}
    )
    assert complete(candidate_fields=entered_fields) is None

    incomplete_fields = [
        field for field in fields if field.field_key != "insurer-f-naic"
    ]
    assert complete(candidate_fields=incomplete_fields) is None

    nonvector_fields = deepcopy(fields)
    nonvector_fields[0] = nonvector_fields[0].model_copy(
        update={"evidence_methods": ["native"]}
    )
    assert complete(candidate_fields=nonvector_fields) is None

    outside_fields = deepcopy(fields)
    outside_fields[0] = outside_fields[0].model_copy(
        update={
            "bbox": outside_fields[0].bbox.model_copy(
                update={"x": group.bbox.x + group.bbox.width + 10.0}
            )
        }
    )
    assert complete(candidate_fields=outside_fields) is None

    changed_labels = deepcopy(labels)
    changed_index = next(
        index
        for index, label in enumerate(changed_labels)
        if label.text == "CONTACT NAME:"
    )
    changed_labels[changed_index] = changed_labels[changed_index].model_copy(
        update={"text": "CONTACT PERSON:"}
    )
    assert complete(candidate_labels=changed_labels) is None

    assert complete(
        candidate_group=group.model_copy(update={"status": "unresolved"})
    ) is None
    assert complete(
        candidate_group=group.model_copy(update={"group_key": "other-static-form"})
    ) is None


@pytest.mark.integration
def test_flag_off_is_exact_predecessor_shape_and_does_no_form_work() -> None:
    disabled = _parse("component-datasheet", False)
    assert _settings(forms=False) == Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
        layout_text_run_semantics_enabled=True,
    )
    assert "form_semantics" not in disabled["processing"]
    serialized = json.dumps(disabled, ensure_ascii=False, sort_keys=True)
    for marker in (
        "layout_forms_projected",
        "form_policy",
        "form_group",
        "form_fields",
        "form_labels",
        "form_value_regions",
        "form_controls",
        "form_key_value_pairs",
    ):
        assert marker not in serialized
    assert _semantic_without_timings(disabled) == _semantic_without_timings(
        _parse("component-datasheet", False)
    )
