"""Production configuration, custody, rollback, and security contracts for US07."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError
import pytest

from app.config import Settings
from app.services import outline_structure as outlines
from app.services import pipeline
from app.services import presentation
from app.services.ir import (
    DocumentIR,
    OutlineGroupSemanticDescriptor,
    project_legacy_pages,
    round_trip_document,
)
from app.services.presentation import build_canonical_presentation
from tests.fixtures.phase_03.outline_structure.oracle import (
    CANONICAL_EXPECTATIONS,
    COMPONENT_GROUPS,
    SETTLEMENT_GROUP,
    SOURCE_REPORTS,
)


WORKSPACE = Path(__file__).resolve().parents[2]
BASELINE = (
    WORKSPACE
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "runs"
    / "baseline-20260728-current"
)
CORPUS = WORKSPACE / "benchmark-expertmodeldata"


def _baseline(case: str) -> dict[str, Any]:
    return json.loads((BASELINE / case / "our-output.json").read_text())


def _inputs(case: str) -> tuple[dict[str, Any], DocumentIR, Any]:
    source = (CORPUS / f"{case}.pdf").read_bytes()
    predecessor = _baseline(case)
    _, ir = round_trip_document(predecessor)
    return predecessor, ir, outlines.extract_outline_evidence(source)


def _project(case: str) -> tuple[dict[str, Any], DocumentIR, dict[str, Any]]:
    predecessor, ir, evidence = _inputs(case)
    metrics: dict[str, Any] = {}
    projected = outlines.project_outline_structure(ir, evidence, metrics)
    payload = deepcopy(predecessor)
    payload["pages"] = project_legacy_pages(projected, predecessor["pages"])
    payload["canonical_presentation"] = build_canonical_presentation(
        projected
    ).model_dump(mode="json", exclude_none=True)
    return payload, projected, metrics


def _anchors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for page in payload["pages"]
        for item in page["items"]
        if item.get("layout_outline_structure_projected") is True
    ]


def test_outline_flag_defaults_off_is_env_addressable_and_has_exact_prerequisites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().layout_outline_structure_enabled is False
    for name in (
        "PARSER_SHARED_IR_ENABLED",
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
        "PARSER_CANONICAL_SERIALIZATION_ENABLED",
        "PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED",
        "PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    settings = Settings.from_env()
    assert settings.layout_outline_structure_enabled is True
    assert settings.layout_forms_enabled is False

    with pytest.raises(
        ValueError,
        match="PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED requires",
    ):
        Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            canonical_serialization_enabled=False,
            layout_relationship_order_enabled=True,
            layout_outline_structure_enabled=True,
        )


def test_round_trip_flag_off_does_not_forward_outline_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def apply(ir: DocumentIR, _settings: Settings, **kwargs: Any) -> DocumentIR:
        captured.update(kwargs)
        return ir

    monkeypatch.setattr("app.services.layout.apply_layout_projection", apply)
    round_trip_document(
        _baseline("settlement-agreement"),
        layout_settings=Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            canonical_serialization_enabled=True,
            layout_relationship_order_enabled=True,
        ),
    )
    assert "outline_evidence" not in captured
    assert "outline_metrics" not in captured


@pytest.mark.parametrize("case", ["component-datasheet", "settlement-agreement"])
def test_native_source_report_matches_the_frozen_oracle_exactly(case: str) -> None:
    report = outlines.extract_outline_evidence((CORPUS / f"{case}.pdf").read_bytes())
    actual = asdict(report)
    expected = dict(SOURCE_REPORTS[case])
    actual.pop("extraction_ms")
    expected.pop("extraction_ms")
    assert actual == expected


def test_tampered_source_report_fails_closed_before_projection() -> None:
    _predecessor, ir, evidence = _inputs("component-datasheet")
    tampered = replace(
        evidence,
        counts=replace(
            evidence.counts,
            marker_candidates=evidence.counts.marker_candidates - 1,
        ),
    )
    metrics: dict[str, Any] = {}
    result = outlines.project_outline_structure(ir, tampered, metrics)
    assert metrics["status"] == "failed_closed"
    assert metrics["group_count"] == 0
    assert any(
        concern.code == "outline_projection_failed_closed"
        for concern in result.concerns
    )


def test_page_source_refusal_is_preserved_without_refusing_other_pages() -> None:
    _predecessor, ir, evidence = _inputs("component-datasheet")
    source_page = replace(
        evidence.pages[0],
        markers=(),
        concern_codes=("outline_source_limit",),
    )
    page_report = replace(
        evidence,
        pages=(source_page,),
        counts=replace(
            evidence.counts,
            marker_candidates=0,
            concerns=1,
        ),
    )
    metrics: dict[str, Any] = {}
    result = outlines.project_outline_structure(ir, page_report, metrics)
    assert metrics["status"] == "no_candidates"
    assert metrics["group_count"] == 0
    assert [
        (concern.code, concern.source_ref)
        for concern in result.concerns
        if concern.code.startswith("outline_")
    ] == [("outline_source_limit", "page:1")]


@pytest.mark.parametrize(
    ("case", "expected_ids"),
    [
        (
            "component-datasheet",
            tuple(value["id"] for value in COMPONENT_GROUPS),
        ),
        ("settlement-agreement", (SETTLEMENT_GROUP["id"],)),
    ],
)
def test_projection_and_canonical_replacement_bind_exact_reviewed_groups(
    case: str,
    expected_ids: tuple[str, ...],
) -> None:
    payload, _ir, metrics = _project(case)
    anchors = _anchors(payload)
    assert metrics["status"] == "projected"
    assert tuple(value["outline_group"]["id"] for value in anchors) == expected_ids
    blocks = {
        block["id"]: block
        for page in payload["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block.get("omission_reason") is None
    }
    for anchor in anchors:
        group = anchor["outline_group"]
        block = blocks[group["canonical_block_id"]]
        assert (
            outlines._sha256_text(block["markdown"])
            == group["canonical_markdown_sha256"]
        )
        assert outlines._sha256_text(block["text"]) == group["canonical_text_sha256"]
        expectation = CANONICAL_EXPECTATIONS[
            next(
                value["oracle_id"]
                for value in (*COMPONENT_GROUPS, SETTLEMENT_GROUP)
                if value["id"] == group["id"]
            )
        ]
        assert block["id"] == expectation["block_id"]


@pytest.mark.parametrize(
    ("case", "project_outline"),
    [
        ("component-datasheet", True),
        ("settlement-agreement", True),
        ("egov-survey", False),
    ],
)
def test_validated_canonical_helper_is_exactly_public_builder_equivalent(
    case: str,
    project_outline: bool,
) -> None:
    _, ir = round_trip_document(_baseline(case))
    if project_outline:
        evidence = outlines.extract_outline_evidence(
            (CORPUS / f"{case}.pdf").read_bytes()
        )
        metrics: dict[str, Any] = {}
        ir = outlines.project_outline_structure(ir, evidence, metrics)
        assert metrics["status"] == "projected"
    validated = DocumentIR.model_validate(ir.model_dump(mode="json"))
    expected = build_canonical_presentation(ir).model_dump(mode="json")
    actual = presentation._build_canonical_presentation_from_validated(
        validated
    ).model_dump(mode="json")
    assert actual == expected


def test_incomplete_existing_list_membership_rolls_back_the_page() -> None:
    _predecessor, ir, evidence = _inputs("component-datasheet")
    page = evidence.pages[0]
    incomplete_page = replace(page, markers=page.markers[1:])
    incomplete = replace(
        evidence,
        pages=(incomplete_page,),
        counts=replace(
            evidence.counts,
            marker_candidates=len(incomplete_page.markers),
        ),
    )
    metrics: dict[str, Any] = {}
    result = outlines.project_outline_structure(ir, incomplete, metrics)
    assert metrics["status"] == "no_candidates"
    assert metrics["group_count"] == 0
    assert any(
        concern.source_ref == "page:1"
        and concern.code == "outline_projection_failed_closed"
        for concern in result.concerns
    )


def test_page_candidate_detachment_prevents_partial_mutation_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _predecessor, ir, evidence = _inputs("settlement-agreement")
    before = ir.model_dump(mode="json")

    def fail_after_mutation(
        candidate: DocumentIR,
        plan: Any,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        anchor = next(
            value for value in candidate.elements if value.id == plan.anchor_element_id
        )
        anchor.properties["partial_outline_write"] = True
        raise ValueError("injected page failure")

    monkeypatch.setattr(outlines, "_materialize_group", fail_after_mutation)
    metrics: dict[str, Any] = {}
    result = outlines.project_outline_structure(ir, evidence, metrics)
    assert ir.model_dump(mode="json") == before
    assert metrics["status"] == "no_candidates"
    assert metrics["group_count"] == 0
    assert all(
        "partial_outline_write" not in value.properties for value in result.elements
    )


def test_ir_descriptors_reject_crossed_kind_style_and_parent_stack() -> None:
    _payload, projected, _metrics = _project("component-datasheet")
    group_element = next(
        value for value in projected.elements if value.outline_group is not None
    )
    descriptor = group_element.outline_group
    assert descriptor is not None
    crossed = descriptor.model_dump(mode="json")
    crossed.update(sequence_kind="legal", marker_style="decimal")
    with pytest.raises(ValidationError, match="kind/marker style"):
        OutlineGroupSemanticDescriptor.model_validate(crossed)

    raw = projected.model_dump(mode="json")
    first_member_id = descriptor.member_element_ids[0]
    first_member = next(
        value for value in raw["elements"] if value["id"] == first_member_id
    )
    first_member["outline_item"]["level"] = 1
    first_member["outline_item"]["parent_element_id"] = descriptor.member_element_ids[
        -1
    ]
    with pytest.raises(ValidationError, match="parent|hierarchy"):
        DocumentIR.model_validate(raw)


@pytest.mark.parametrize(
    "mutation",
    ["root_level", "page_id", "anchor_id", "kind_style", "next_edge"],
)
def test_stripper_leaves_semantically_malformed_sidecars_untouched(
    mutation: str,
) -> None:
    payload, _ir, _metrics = _project("component-datasheet")
    malformed = deepcopy(payload)
    anchor = _anchors(malformed)[0]
    if mutation == "root_level":
        anchor["outline_items"][0]["level"] = 7
    elif mutation == "page_id":
        anchor["outline_group"]["page_id"] = "page-bogus"
    elif mutation == "anchor_id":
        anchor["outline_group"]["anchor_element_id"] = "element-bogus"
    elif mutation == "kind_style":
        anchor["outline_group"]["sequence_kind"] = "legal"
        anchor["outline_group"]["marker_style"] = "decimal"
        for item in anchor["outline_items"]:
            item["sequence_kind"] = "legal"
            item["marker_style"] = "decimal"
    else:
        edge = next(
            value
            for value in anchor["relationships"]
            if value.get("outline_policy") == outlines.POLICY_ID
            and value["type"] == "outline_next"
        )
        edge["source_id"], edge["target_id"] = (
            edge["target_id"],
            edge["source_id"],
        )

    stripped = outlines.strip_outline_structure_public(malformed)
    assert _anchors(stripped)


def test_continuation_renderer_rejects_active_markdown_and_accepts_settlement_table() -> (
    None
):
    _predecessor, ir, _evidence = _inputs("settlement-agreement")
    predecessor = build_canonical_presentation(ir)
    table = next(
        block
        for page in predecessor.pages
        for block in page.blocks
        if block.primary_element_id
        == SETTLEMENT_GROUP["continuations"][0]["element_id"]
    )
    outlines._validate_continuation_markdown(table.markdown)
    for unsafe in (
        "| cell |\n| --- |\n| <script>alert(1)</script> |",
        "| cell |\n| --- |\n| [open](javascript:alert(1)) |",
        "| cell |\n| --- |\n| [open](%6aavascript:alert(1)) |",
        '<table><tr><td><a href="javascript:x">x</a></td></tr></table>',
    ):
        with pytest.raises(ValueError, match="unsafe"):
            outlines._validate_continuation_markdown(unsafe)


def test_processing_summary_enforces_status_reason_and_count_equivalence() -> None:
    unavailable = outlines.outline_processing_summary(
        {"status": "unavailable", "reason": "outline_geometry_ambiguous"}
    )
    assert unavailable["reason"] == "outline_source_evidence_unavailable"
    failed = outlines.outline_processing_summary(
        {"status": "failed_closed", "reason": "outline_source_limit"}
    )
    assert failed["reason"] == "outline_projection_failed_closed"
    empty_projected = outlines.outline_processing_summary({"status": "projected"})
    assert empty_projected["status"] == "no_candidates"


def test_one_page_clock_identity_is_shared_across_every_projection_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _predecessor, ir, evidence = _inputs("settlement-agreement")
    real_check = outlines._check_projection_deadlines
    observed: list[tuple[float, float]] = []

    def record(*, started_at: float, page_started_at: float) -> None:
        observed.append((started_at, page_started_at))
        real_check(started_at=started_at, page_started_at=page_started_at)

    monkeypatch.setattr(outlines, "_check_projection_deadlines", record)
    metrics: dict[str, Any] = {}
    outlines.project_outline_structure(ir, evidence, metrics)
    assert metrics["status"] == "projected"
    assert observed
    assert len({value[0] for value in observed}) == 1
    assert len({value[1] for value in observed}) == 1


def test_terminal_outline_replay_identity_detects_fewer_or_different_groups() -> None:
    payload, _ir, _metrics = _project("component-datasheet")
    identity = pipeline._outline_replay_identity(payload)
    assert len(identity) == 2
    fewer = deepcopy(payload)
    anchor = _anchors(fewer)[0]
    anchor.pop("layout_outline_structure_projected")
    assert pipeline._outline_replay_identity(fewer) != identity
