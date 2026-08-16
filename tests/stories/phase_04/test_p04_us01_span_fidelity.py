"""P04-US01 readiness contracts only; no production behavior is exercised."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pdfplumber
import pytest
from pydantic import ValidationError

from tests.fixtures.phase_04.tables.contract import (
    CONCERN_CODES,
    POLICY_ID,
    SIDECAR_VERSION,
    TABLE_LIMITS,
    CellTruth,
    EvidenceTruth,
    FiniteBBox,
    P04Us01Oracle,
    ReviewedDenominator,
    SourceIdentity,
    SpanDecisionTruth,
    resolve_workspace_path,
    validate_oracle,
    validate_portable_workspace_path,
)
from tests.fixtures.phase_04.tables.oracle import (
    EXHIBIT7_EXACT,
    EXHIBIT7_TRUTH_IDENTITY,
    P04_US01_REAL_ORACLE,
    exhibit7_source_projection,
    oracle_sha256,
)
from tests.fixtures.phase_04.tables.synthetic import (
    REQUIRED_SYNTHETIC_COVERAGE,
    SYNTHETIC_FIXTURES,
    SyntheticGrid,
    build_flag_off_witness,
    build_invalid_payload,
    build_resource_boundary_witness,
    build_synthetic_fixture,
    registry_sha256,
    self_check,
)


WORKSPACE = Path(__file__).resolve().parents[3]
EXPECTED_ORACLE_SHA256 = "b0506a443e7275f911be1b5d43d28a994f68203cd42ae4f194c8c88bd89690d1"
EXPECTED_SYNTHETIC_SHA256 = "0ef6b9689c9f4edbde4e273c9d1a0e2f63366ea0cbcd5ce3c909eecaa17b8bee"
EXPECTED_LIMITS = {
    "maximum_rows_per_table": 4_096,
    "maximum_columns_per_table": 256,
    "maximum_cells_per_table": 65_536,
    "maximum_cell_text_utf8_bytes": 16_384,
    "maximum_concerns_per_table": 64,
    "maximum_oracle_tables": 64,
    "maximum_evidence_ids_per_record": 64,
    "maximum_source_object_ids_per_record": 64,
    "maximum_identity_utf8_bytes": 256,
    "maximum_reference_utf8_bytes": 256,
    "maximum_portable_path_utf8_bytes": 256,
    "maximum_table_sidecar_bytes": 8_388_608,
    "maximum_phase04_sidecars_per_document_bytes": 67_108_864,
    "maximum_span_fidelity_page_seconds": 0.500,
    "maximum_span_fidelity_document_seconds": 5.000,
    "maximum_table_stage_p95_overhead_ratio": 0.10,
    "maximum_peak_rss_delta_bytes": 67_108_864,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _denominators(oracle_id: str) -> dict[str, ReviewedDenominator]:
    table = next(
        item
        for item in P04_US01_REAL_ORACLE.qualified_tables
        if item.oracle_id == oracle_id
    )
    return {item.dimension: item for item in table.denominators}


def _cell_payload(**overrides: object) -> dict[str, object]:
    payload = EXHIBIT7_EXACT.cells[0].model_dump(mode="python")
    payload.update(overrides)
    return payload


def test_readiness_contract_is_versioned_closed_and_bounded() -> None:
    assert POLICY_ID == "p04-table-evidence-v1"
    assert SIDECAR_VERSION == "1.1"
    assert set(CONCERN_CODES) == {
        "table_source_cell_grid_unresolved",
        "table_source_span_evidence_unresolved",
        "table_source_cell_bbox_unresolved",
        "table_source_provenance_unresolved",
        "table_source_header_ownership_unresolved",
        "table_source_row_boundary_unresolved",
        "table_source_rotation_mapping_unresolved",
        "table_source_form_grid_topology_unresolved",
        "table_ambiguous_border_evidence",
        "table_malformed_source_evidence",
        "table_resource_limit_exceeded",
    }
    assert dict(TABLE_LIMITS) == EXPECTED_LIMITS
    with pytest.raises(TypeError):
        TABLE_LIMITS["maximum_rows_per_table"] = 1  # type: ignore[index]


def test_all_six_reviewed_source_identities_match_immutable_bytes() -> None:
    for source in P04_US01_REAL_ORACLE.sources:
        path = resolve_workspace_path(WORKSPACE, source.path)
        assert path.stat().st_size == source.size_bytes
        assert _sha256(path) == source.sha256
        assert resolve_workspace_path(WORKSPACE, source.review_path).is_file()
        with pdfplumber.open(path) as document:
            assert len(document.pages) == source.page_count
            assert all(float(page.width) == source.page_width_pt for page in document.pages)
            assert all(float(page.height) == source.page_height_pt for page in document.pages)


def test_exhibit7_cross_checks_the_exact_p00_source_truth() -> None:
    truth_path = resolve_workspace_path(WORKSPACE, EXHIBIT7_TRUTH_IDENTITY["path"])
    assert _sha256(truth_path) == EXHIBIT7_TRUTH_IDENTITY["sha256"]
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    projection = exhibit7_source_projection()

    assert projection["row_count"] == truth["table"]["row_count"]
    assert projection["column_count"] == truth["table"]["column_count"]
    assert projection["cell_count"] == truth["table"]["cell_count"]
    expected_cells = tuple(
        {
            "row": cell["row"],
            "column": cell["column"],
            "row_span": cell["row_span"],
            "col_span": cell["col_span"],
            "text": cell["text"],
            "bbox": tuple(cell["bbox"]),
        }
        for cell in truth["table_cells"]
    )
    assert projection["cells"] == expected_cells


def test_exhibit7_freezes_30_explicit_cells_and_five_repeated_values() -> None:
    assert (EXHIBIT7_EXACT.row_count, EXHIBIT7_EXACT.column_count) == (6, 5)
    assert EXHIBIT7_EXACT.cell_count == len(EXHIBIT7_EXACT.cells) == 30
    assert sum(cell.text == "United States" for cell in EXHIBIT7_EXACT.cells) == 5
    assert all((cell.row_span, cell.col_span) == (1, 1) for cell in EXHIBIT7_EXACT.cells)
    assert len({(cell.row, cell.column) for cell in EXHIBIT7_EXACT.cells}) == 30
    assert all(cell.bbox.unit == "pt" for cell in EXHIBIT7_EXACT.cells)
    assert all("p00_source_truth" in cell.evidence_basis for cell in EXHIBIT7_EXACT.cells)


def test_finance_denominators_score_only_reviewed_spans_and_wrapped_row() -> None:
    p1 = _denominators("finance-p1-operations")
    p2 = _denominators("finance-p2-balance-sheet")
    p3 = _denominators("finance-p3-cash-flow")
    assert p1["column_count"].expected == 4
    assert p1["supported_col_span"].members == (3,)
    assert p2["column_count"].expected == 3
    assert p2["logical_wrapped_row_count"].expected == 1
    assert p3["column_count"].expected == 4
    assert p3["supported_col_span"].members == (3,)


def test_postal_denominators_include_exact_header_cells_and_fers_boundary() -> None:
    glossary = next(
        item
        for item in P04_US01_REAL_ORACLE.qualified_tables
        if item.oracle_id == "postal-p1-glossary"
    )
    claims = _denominators(glossary.oracle_id)
    assert claims["row_count_including_header"].expected == 40
    assert claims["data_row_count"].expected == 39
    assert claims["column_count"].expected == 2
    assert claims["cell_count"].expected == 80
    assert claims["header_ownership"].expected == 2
    assert claims["row_boundary"].expected == 1
    assert glossary.reviewed_rows[0].role == "column_header"
    assert glossary.reviewed_rows[0].values == ("Term or Acronym", "Definition")
    assert glossary.reviewed_rows[-1].source_table_row_index == 39
    assert glossary.reviewed_rows[-1].values == (
        "FERS",
        "Federal Employees Retirement System",
    )
    assert glossary.reviewed_rows[-1].bbox == FiniteBBox(
        x=58.5, y=708.75, width=495.0, height=15.75
    )
    assert set(glossary.unresolved_dimensions) == {
        "cell_bbox_count",
        "cell_provenance_count",
    }
    for page in (2, 3):
        financial = _denominators(f"postal-p{page}-financial")
        assert financial["column_count"].expected == 4
        assert financial["supported_col_span"].members == (3,)


def test_clinical_denominators_forbid_invented_shape_and_bind_headers() -> None:
    table1 = _denominators("clinical-p2-table-1")
    table2 = _denominators("clinical-p4-table-2")
    assert table1["column_count"].expected == 6
    assert table1["header_ownership"].expected == 6
    assert table1["stub_only_section_row_count"].expected == 5
    assert table1["false_span_count"].expected == 0
    assert table2["column_count"].expected == 9
    assert table2["header_ownership"].expected == 9
    assert table2["stub_only_section_row_count"].expected == 2
    assert table2["supported_col_span"].members == (4, 3)
    assert table2["false_span_count"].expected == 0
    assert table1["header_ownership"].evidence_basis == "reviewed_visual_render"
    assert table2["header_ownership"].evidence_basis == "reviewed_visual_render"


def test_timetable_denominators_and_known_bad_expert_row_are_source_bound() -> None:
    timetable = [
        item
        for item in P04_US01_REAL_ORACLE.qualified_tables
        if item.case_id == "ny-timetable"
    ]
    assert len(timetable) == 3
    assert sum(
        _denominators(item.oracle_id)["data_row_count"].expected
        for item in timetable
    ) == 150
    assert all(
        _denominators(item.oracle_id)["column_count"].expected == 13
        for item in timetable
    )
    assert all(
        _denominators(item.oracle_id)["visual_row_count"].expected == 52
        for item in timetable
    )
    page3 = next(item for item in timetable if item.physical_page == 3)
    assert page3.reviewed_rows[0].source_table_row_index == 28
    assert page3.reviewed_rows[0].values == (
        "",
        "3:01",
        "3:05",
        "3:18",
        "3:24",
        "3:30",
        "3:32",
        "3:38",
        "3:43",
        "3:48",
        "3:51",
        "3:55",
        "3:57",
    )


def test_acord_observations_are_addressable_but_topology_stays_unresolved() -> None:
    acord = next(
        item
        for item in P04_US01_REAL_ORACLE.qualified_tables
        if item.oracle_id == "acord-p1-coverage-grid"
    )
    assert acord.review_state == "unresolved"
    assert acord.canonical_action == "retain_candidate_with_concern"
    assert {item.dimension for item in acord.denominators} == {"table_count"}
    assert [item.text for item in acord.reviewed_source_objects] == [
        None,
        "INSR\nLTR",
        "TYPE OF INSURANCE",
        "LIMITS",
    ]
    assert all(item.source_ref.startswith("benchmark-expertmodeldata/") for item in acord.reviewed_source_objects)
    assert {item.dimension for item in acord.required_concerns} == set(
        acord.unresolved_dimensions
    )
    assert {
        "form_grid_topology",
        "header_ownership",
        "cell_bbox_count",
        "cell_provenance_count",
    } <= set(acord.unresolved_dimensions)


def test_every_unreviewed_dimension_has_exactly_one_fail_closed_concern() -> None:
    allowed = set(CONCERN_CODES)
    for table in P04_US01_REAL_ORACLE.qualified_tables:
        assert {concern.code for concern in table.required_concerns} <= allowed
        assert len(table.required_concerns) == len(table.unresolved_dimensions)
        assert {concern.dimension for concern in table.required_concerns} == set(
            table.unresolved_dimensions
        )
        assert not (
            {claim.dimension for claim in table.denominators}
            & set(table.unresolved_dimensions)
        )


def test_oracle_uses_reviewed_sources_and_never_expert_topology_as_truth() -> None:
    assert all(
        table.evidence_path.endswith(".md")
        and "/cases/" in table.evidence_path
        and "expertmodeldata" not in table.evidence_path
        for table in P04_US01_REAL_ORACLE.qualified_tables
    )
    assert all(
        claim.evidence_basis
        in {
            "p00_source_truth",
            "reviewed_native_text",
            "reviewed_vector_geometry",
            "reviewed_visual_render",
            "reviewed_source_comparison",
        }
        for table in P04_US01_REAL_ORACLE.qualified_tables
        for claim in table.denominators
    )


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -float("inf")])
def test_bbox_contract_rejects_nonfinite_values(bad_value: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        FiniteBBox(x=bad_value, y=0.0, width=1.0, height=1.0)


def test_closed_contract_rejects_extras_coercion_and_negative_indices() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        FiniteBBox.model_validate(
            {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "extra": 1},
            strict=True,
        )
    with pytest.raises(ValidationError):
        FiniteBBox.model_validate(
            {"x": "0", "y": 0.0, "width": 1.0, "height": 1.0}, strict=True
        )
    with pytest.raises(ValidationError):
        CellTruth.model_validate(_cell_payload(row=-1), strict=True)


def test_root_oracle_strictly_round_trips_and_rejects_unknown_fields() -> None:
    payload = P04_US01_REAL_ORACLE.model_dump(mode="python")
    assert validate_oracle(payload) == P04_US01_REAL_ORACLE
    payload["unknown"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        P04Us01Oracle.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    ("dimension", "unit", "limit"),
    (
        ("table_count", "tables", 64),
        ("row_count_including_header", "rows", 4_096),
        ("visual_row_count", "rows", 4_096),
        ("data_row_count", "rows", 4_096),
        ("column_count", "columns", 256),
        ("cell_count", "cells", 65_536),
        ("repeated_value_count", "values", 65_536),
        ("false_span_count", "spans", 65_536),
        ("stub_only_section_row_count", "rows", 4_096),
        ("logical_wrapped_row_count", "rows", 4_096),
        ("cell_bbox_count", "cells", 65_536),
        ("cell_provenance_count", "cells", 65_536),
        ("header_ownership", "cells", 65_536),
        ("row_boundary", "rows", 4_096),
        ("rotation_mapping", "cells", 65_536),
        ("form_grid_topology", "cells", 65_536),
    ),
)
def test_every_nonspan_denominator_accepts_limit_and_rejects_plus_one(
    dimension: str,
    unit: str,
    limit: int,
) -> None:
    common = {
        "denominator_id": f"cap-{dimension.replace('_', '-')}",
        "dimension": dimension,
        "unit": unit,
        "members": (),
        "evidence_basis": "reviewed_source_comparison",
        "qualification": "Executable denominator cap witness.",
    }
    assert ReviewedDenominator(expected=limit, **common).expected == limit
    with pytest.raises(ValidationError, match="expected value"):
        ReviewedDenominator(expected=limit + 1, **common)


@pytest.mark.parametrize(
    ("dimension", "member_limit"),
    (("supported_col_span", 256), ("supported_row_span", 4_096)),
)
def test_span_member_bounds_are_dimension_specific(
    dimension: str, member_limit: int
) -> None:
    common = {
        "denominator_id": f"cap-{dimension.replace('_', '-')}",
        "dimension": dimension,
        "expected": 1,
        "unit": "spans",
        "evidence_basis": "reviewed_source_comparison",
        "qualification": "Executable span-member cap witness.",
    }
    assert ReviewedDenominator(members=(member_limit,), **common).members == (
        member_limit,
    )
    with pytest.raises(ValidationError, match="outside readiness limits"):
        ReviewedDenominator(members=(member_limit + 1,), **common)
    with pytest.raises(ValidationError, match="one width"):
        ReviewedDenominator(members=(), **common)
    overflow = {**common, "expected": 65_537, "members": ()}
    with pytest.raises(ValidationError, match="expected value"):
        ReviewedDenominator(**overflow)


def test_denominator_unit_cannot_bypass_its_dimension_cap() -> None:
    with pytest.raises(ValidationError, match="unit differs"):
        ReviewedDenominator(
            denominator_id="column-unit-bypass",
            dimension="column_count",
            expected=256,
            unit="cells",
            members=(),
            evidence_basis="reviewed_source_comparison",
            qualification="Wrong units cannot reinterpret a bounded denominator.",
        )


@pytest.mark.parametrize(
    "bad_path",
    (
        "../evidence.md",
        "evidence/../secret.md",
        "evidence/..",
        "evidence/../../secret.md",
        "evidence//record.md",
        "evidence/./record.md",
        "evidence\\record.md",
        "/absolute/evidence.md",
        "C:/absolute/evidence.md",
        "file:///absolute/evidence.md",
        "evidence/%2e%2e/secret.md",
        "~/evidence.md",
        "evidence..record.md",
        " evidence/record.md",
        "evidence/record.md ",
        "evidence/record\x00.md",
    ),
)
def test_portable_paths_reject_every_traversal_and_string_bypass(
    bad_path: str,
) -> None:
    with pytest.raises(ValueError):
        validate_portable_workspace_path(bad_path)


def test_portable_path_accepts_256_bytes_and_rejects_257() -> None:
    exact = f"a/{'b' * 254}"
    assert len(exact.encode("utf-8")) == 256
    assert validate_portable_workspace_path(exact) == exact
    with pytest.raises(ValueError, match="byte limit"):
        validate_portable_workspace_path(f"{exact}c")


def test_workspace_resolution_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "inside").mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)

    assert resolve_workspace_path(workspace, "inside/evidence.md").parent == (
        workspace / "inside"
    )
    with pytest.raises(ValueError, match="outside the workspace"):
        resolve_workspace_path(workspace, "escape/evidence.md")


def test_identifier_and_reference_byte_caps_are_enforced() -> None:
    exact_id = "a" * TABLE_LIMITS["maximum_identity_utf8_bytes"]
    assert CellTruth.model_validate(_cell_payload(cell_id=exact_id), strict=True).cell_id == exact_id
    with pytest.raises(ValidationError, match="byte limit"):
        CellTruth.model_validate(_cell_payload(cell_id=f"{exact_id}a"), strict=True)

    exact_ref = "r" * TABLE_LIMITS["maximum_reference_utf8_bytes"]
    assert CellTruth.model_validate(_cell_payload(source_ref=exact_ref), strict=True).source_ref == exact_ref
    with pytest.raises(ValidationError, match="byte limit"):
        CellTruth.model_validate(_cell_payload(source_ref=f"{exact_ref}r"), strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("text", "safe\x00unsafe"),
        ("text", "safe\x1funsafe"),
        ("text", "safe\ud800unsafe"),
        ("source_ref", "source\nref"),
        ("source_ref", " source-ref"),
    ),
)
def test_cell_string_fields_reject_control_and_outer_whitespace(
    field: str, value: str
) -> None:
    with pytest.raises(
        ValidationError, match="unsafe control|outer whitespace|valid UTF-8"
    ):
        CellTruth.model_validate(_cell_payload(**{field: value}), strict=True)


def test_source_identity_rejects_oversized_or_unsafe_metadata() -> None:
    payload = P04_US01_REAL_ORACLE.sources[0].model_dump(mode="python")
    payload["case_id"] = "a" * 257
    with pytest.raises(ValidationError, match="byte limit"):
        SourceIdentity.model_validate(payload, strict=True)
    payload = P04_US01_REAL_ORACLE.sources[0].model_dump(mode="python")
    payload["custody_limitation"] = "unsafe\x00metadata"
    with pytest.raises(ValidationError, match="unsafe control"):
        SourceIdentity.model_validate(payload, strict=True)


def test_synthetic_registry_is_complete_deterministic_and_executable() -> None:
    self_check()
    assert tuple(item.fixture_id for item in SYNTHETIC_FIXTURES) == (
        REQUIRED_SYNTHETIC_COVERAGE
    )
    assert registry_sha256() == EXPECTED_SYNTHETIC_SHA256
    repeated = build_synthetic_fixture("repeated_values_without_span")
    assert sum(cell.text == "Same" for cell in repeated.cells) == 3
    assert all((cell.row_span, cell.col_span) == (1, 1) for cell in repeated.cells)


def test_material_synthetic_controls_have_distinct_executable_shapes() -> None:
    rotated = build_synthetic_fixture("rotated_multiline_headers")
    bottom = build_synthetic_fixture("bottom_boundary_completeness")
    partial = build_synthetic_fixture("partial_grid_refusal")
    form = build_synthetic_fixture("decorative_form_rule_refusal")

    assert (rotated.row_count, rotated.column_count, len(rotated.cells)) == (2, 3, 6)
    assert all("\n" in cell.text for cell in rotated.cells[:3])
    assert {item.dimension for item in rotated.evidence} == {"header"}
    assert (bottom.row_count, bottom.column_count, len(bottom.cells)) == (3, 2, 6)
    assert [cell.text for cell in bottom.cells[-2:]] == [
        "FERS",
        "Federal Employees Retirement System",
    ]
    assert len(partial.cells) == 5 < partial.row_count * partial.column_count
    assert partial.required_concern == "table_ambiguous_border_evidence"
    assert len(form.cells) == form.row_count * form.column_count == 6
    assert form.required_concern == "table_source_form_grid_topology_unresolved"


def test_legitimate_spans_have_linked_source_objects_evidence_and_decisions() -> None:
    for fixture_id, expected in (
        ("legitimate_colspan", (1, 3)),
        ("legitimate_rowspan", (2, 1)),
    ):
        fixture = build_synthetic_fixture(fixture_id)
        assert len(fixture.source_objects) == 2
        assert len(fixture.evidence) == 2
        assert {item.dimension for item in fixture.evidence} == {
            "geometry",
            "structure",
        }
        assert len(fixture.span_decisions) == 1
        decision = fixture.span_decisions[0]
        assert (decision.emitted_row_span, decision.emitted_col_span) == expected
        assert set(decision.evidence_ids) == {item.id for item in fixture.evidence}


@pytest.mark.parametrize(
    "bypass",
    (
        "missing_decision",
        "missing_evidence",
        "wrong_dimension",
        "one_source_object",
        "missing_source_object",
        "duplicate_evidence_id",
    ),
)
def test_supported_span_rejects_every_evidence_linkage_bypass(bypass: str) -> None:
    payload = deepcopy(
        build_synthetic_fixture("legitimate_colspan").model_dump(mode="python")
    )
    if bypass == "missing_decision":
        payload["span_decisions"] = ()
    elif bypass == "missing_evidence":
        payload["evidence"] = payload["evidence"][:1]
    elif bypass == "wrong_dimension":
        payload["evidence"][1]["dimension"] = "structure"
    elif bypass == "one_source_object":
        payload["evidence"][1]["source_object_ids"] = payload["evidence"][0][
            "source_object_ids"
        ]
    elif bypass == "missing_source_object":
        payload["source_objects"] = payload["source_objects"][:1]
    elif bypass == "duplicate_evidence_id":
        duplicate = payload["span_decisions"][0]["evidence_ids"][0]
        payload["span_decisions"][0]["evidence_ids"] = (duplicate, duplicate)
    with pytest.raises(ValidationError):
        SyntheticGrid.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    "fixture_id",
    (
        "duplicate_position_refusal",
        "overlapping_span_refusal",
        "negative_index_refusal",
        "nonfinite_bbox_refusal",
        "resource_boundaries",
    ),
)
def test_malformed_synthetic_payloads_are_rejected(fixture_id: str) -> None:
    payload = build_invalid_payload(fixture_id)
    if fixture_id == "overlapping_span_refusal":
        assert payload["cells"][0]["col_span"] == 2
        assert payload["cells"][1]["column"] == 1
    with pytest.raises(ValidationError):
        SyntheticGrid.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    "counter",
    (
        "rows",
        "columns",
        "cells",
        "cell_text_utf8_bytes",
        "concerns",
        "evidence_ids",
        "source_object_ids",
        "identity_utf8_bytes",
        "reference_utf8_bytes",
        "portable_path_utf8_bytes",
        "table_sidecar_bytes",
        "document_sidecars_bytes",
        "span_page_seconds",
        "span_document_seconds",
        "p95_overhead_ratio",
        "peak_rss_delta_bytes",
    ),
)
def test_every_resource_boundary_accepts_exact_and_rejects_maximum_plus_one(
    counter: str,
) -> None:
    assert build_resource_boundary_witness(counter, overflow=False).execute() is True
    assert build_resource_boundary_witness(counter, overflow=True).execute() is False


def test_evidence_and_decision_fanout_caps_are_model_enforced() -> None:
    source_ids = tuple(f"source-{index}" for index in range(64))
    common_evidence = {
        "id": "evidence-cap",
        "method": "source_grid",
        "dimension": "structure",
        "page_index": 0,
        "bbox": None,
        "confidence": 1.0,
        "content_sha256": "0" * 64,
    }
    assert len(EvidenceTruth(source_object_ids=source_ids, **common_evidence).source_object_ids) == 64
    with pytest.raises(ValidationError):
        EvidenceTruth(source_object_ids=(*source_ids, "source-overflow"), **common_evidence)

    evidence_ids = tuple(f"evidence-{index}" for index in range(64))
    common_decision = {
        "id": "span-cap",
        "cell_id": "cell-cap",
        "claimed_row_span": 1,
        "claimed_col_span": 2,
        "emitted_row_span": 1,
        "emitted_col_span": 1,
        "outcome": "refused",
        "concern_codes": ("table_source_span_evidence_unresolved",),
    }
    assert len(SpanDecisionTruth(evidence_ids=evidence_ids, **common_decision).evidence_ids) == 64
    with pytest.raises(ValidationError):
        SpanDecisionTruth(evidence_ids=(*evidence_ids, "evidence-overflow"), **common_decision)


def test_fixture_text_preserves_distinct_inert_html_source_values() -> None:
    fixture = build_synthetic_fixture("html_escaping")
    values = [cell.text for cell in fixture.cells]
    assert values == [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "AT&T",
        'javascript:alert("x")',
    ]
    encoded = json.dumps(fixture.model_dump(mode="json"), ensure_ascii=True)
    assert [cell["text"] for cell in json.loads(encoded)["cells"]] == values


def test_flag_off_witness_is_distinct_and_byte_identical() -> None:
    predecessor = b'{"schema_version":"1.0","pages":[]}'
    witness = build_flag_off_witness(predecessor)
    assert witness.fixture_load_count == 0
    assert witness.phase04_stage_call_count == 0
    assert witness.predecessor_sha256 == witness.output_sha256
    assert all(enabled is False for _, enabled in witness.flags)
    payload = witness.model_dump(mode="python")
    payload["output_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="exact predecessor"):
        type(witness).model_validate(payload, strict=True)


def test_frontend_readiness_test_path_and_implementation_plan_are_explicit() -> None:
    readiness_test = WORKSPACE / "frontend/tests/p04-us01-table-readiness.test.mts"
    story = WORKSPACE / "tracker/phase-04-tables/stories/P04-US01.md"
    assert readiness_test.is_file()
    readiness_text = readiness_test.read_text(encoding="utf-8")
    story_text = story.read_text(encoding="utf-8")
    assert "readiness-only" in readiness_text
    assert "p04-us01-table-span-fidelity.test.mts" in readiness_text
    assert "escaped-react-grid" in readiness_text
    assert "predecessor-fallback" in readiness_text
    assert readiness_test.name in story_text
    assert "Status: In Progress" in story_text or "Status: Done" in story_text
    assert "Started: 2026-08-04" in story_text
    assert "Status: Done — release-first core functionality validated" in story_text
    assert "Completed: 2026-08-11" in story_text
    assert "## Release-first completion comment" in story_text
    assert "Completion evidence belongs" in story_text


def test_readiness_identities_are_exact_and_json_is_finite() -> None:
    assert oracle_sha256() == EXPECTED_ORACLE_SHA256
    assert registry_sha256() == EXPECTED_SYNTHETIC_SHA256
    encoded = json.dumps(
        P04_US01_REAL_ORACLE.model_dump(mode="json"),
        sort_keys=True,
        allow_nan=False,
    )
    assert encoded
    assert "NaN" not in encoded and "Infinity" not in encoded
