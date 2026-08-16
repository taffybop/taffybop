"""Source-qualified P04-US01 oracle.

Only Exhibit 7 has exhaustive cell truth.  Other records score the exact
dimensions established by the reviewed source reports and attach closed
concerns to every unreviewed dimension.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from tests.fixtures.phase_04.tables.contract import (
    POLICY_ID,
    SIDECAR_VERSION,
    CellTruth,
    ExactTableTruth,
    FailClosedConcern,
    FiniteBBox,
    P04Us01Oracle,
    QualifiedTableDenominator,
    ReviewedDenominator,
    ReviewedRowTruth,
    ReviewedSourceObservation,
    SourceIdentity,
)


_CUSTODY_LIMITATION = (
    "Requester/provider attestation only; no independent license review or "
    "named license was supplied."
)


def _source(
    case_id: str,
    size_bytes: int,
    sha256: str,
    page_count: int,
) -> SourceIdentity:
    return SourceIdentity(
        case_id=case_id,
        path=f"benchmark-expertmodeldata/{case_id}.pdf",
        size_bytes=size_bytes,
        sha256=sha256,
        page_count=page_count,
        page_width_pt=612.0,
        page_height_pt=792.0,
        custody="public-redistributable",
        review_path=f"tracker/benchmarks/llamaparse-15/cases/{case_id}.md",
        custody_limitation=_CUSTODY_LIMITATION,
    )


SOURCE_IDENTITIES = (
    _source(
        "catastrophe-recap",
        58_779,
        "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e",
        1,
    ),
    _source(
        "finance-10k",
        87_105,
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086",
        3,
    ),
    _source(
        "postal-10k",
        83_589,
        "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74",
        3,
    ),
    _source(
        "clinical-study",
        750_004,
        "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2",
        4,
    ),
    _source(
        "ny-timetable",
        26_109,
        "f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30",
        3,
    ),
    _source(
        "insurance-acord",
        17_086,
        "85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4",
        1,
    ),
)

EXHIBIT7_TRUTH_IDENTITY = {
    "path": "tracker/phase-00-baseline/evidence/P00-US02-catastrophe-truth.json",
    "sha256": "d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac",
}

_EXHIBIT7_ROWS = (
    ("Date(s)", "Event", "Location", "Fatalities", "Insured Loss ($B)"),
    ("01/07-01/28", "Palisades Fire", "United States", "12", "23.0"),
    ("01/07-01/28", "Eaton Fire", "United States", "18", "17.5"),
    ("03/14-03/16", "Severe Convective Storm", "United States", "43", "8.0"),
    ("05/14-05/16", "Severe Convective Storm", "United States", "30", "8.0"),
    ("05/17-05/20", "Severe Convective Storm", "United States", "0", "4.0"),
)
_EXHIBIT7_X = (100.94, 163.82, 285.53, 398.23, 448.03, 543.82)
_EXHIBIT7_Y = (231.29, 247.73, 264.17, 280.61, 297.05, 313.49, 329.93)


def _exhibit7_cells() -> tuple[CellTruth, ...]:
    return tuple(
        CellTruth(
            cell_id=f"exhibit-7-r{row}-c{column}",
            row=row,
            column=column,
            row_span=1,
            col_span=1,
            text=text,
            bbox=FiniteBBox(
                x=float(_EXHIBIT7_X[column]),
                y=float(_EXHIBIT7_Y[row]),
                width=round(_EXHIBIT7_X[column + 1] - _EXHIBIT7_X[column], 2),
                height=round(_EXHIBIT7_Y[row + 1] - _EXHIBIT7_Y[row], 2),
            ),
            column_header=row == 0,
            row_header=False,
            evidence_basis=("visible_text", "vector_grid", "p00_source_truth"),
            source_ref=(
                f"{EXHIBIT7_TRUTH_IDENTITY['path']}#cell-exhibit-7-r{row}-c{column}"
            ),
        )
        for row, values in enumerate(_EXHIBIT7_ROWS)
        for column, text in enumerate(values)
    )


EXHIBIT7_EXACT = ExactTableTruth(
    oracle_id="exhibit-7",
    case_id="catastrophe-recap",
    physical_page=1,
    table_bbox=FiniteBBox(x=99.71, y=231.04, width=444.79, height=99.5),
    row_count=6,
    column_count=5,
    cell_count=30,
    header_row_count=1,
    repeated_value="United States",
    repeated_value_count=5,
    cells=_exhibit7_cells(),
    source_truth_path=EXHIBIT7_TRUTH_IDENTITY["path"],
    source_truth_sha256=EXHIBIT7_TRUTH_IDENTITY["sha256"],
)


def _denominator(
    denominator_id: str,
    dimension: str,
    expected: int,
    unit: str,
    qualification: str,
    *,
    evidence_basis: str = "reviewed_source_comparison",
    members: tuple[int, ...] = (),
) -> ReviewedDenominator:
    return ReviewedDenominator(
        denominator_id=denominator_id,
        dimension=dimension,
        expected=expected,
        unit=unit,
        members=members,
        evidence_basis=evidence_basis,
        qualification=qualification,
    )


_CONCERN_BY_DIMENSION = {
    "row_count_including_header": "table_source_cell_grid_unresolved",
    "column_count": "table_source_cell_grid_unresolved",
    "cell_count": "table_source_cell_grid_unresolved",
    "supported_col_span": "table_source_span_evidence_unresolved",
    "supported_row_span": "table_source_span_evidence_unresolved",
    "cell_bbox_count": "table_source_cell_bbox_unresolved",
    "cell_provenance_count": "table_source_provenance_unresolved",
    "header_ownership": "table_source_header_ownership_unresolved",
    "row_boundary": "table_source_row_boundary_unresolved",
    "rotation_mapping": "table_source_rotation_mapping_unresolved",
    "form_grid_topology": "table_source_form_grid_topology_unresolved",
}


def _concerns(dimensions: tuple[str, ...]) -> tuple[FailClosedConcern, ...]:
    return tuple(
        FailClosedConcern(
            code=_CONCERN_BY_DIMENSION[dimension],
            dimension=dimension,
            reason=(
                f"The reviewed source record does not establish exact {dimension}; "
                "retain source evidence and refuse to invent the missing structure."
            ),
        )
        for dimension in dimensions
    )


def _qualified(
    *,
    oracle_id: str,
    case_id: str,
    page: int,
    region_id: str,
    bbox: FiniteBBox | None,
    denominators: tuple[ReviewedDenominator, ...],
    unresolved: tuple[str, ...],
    evidence_path: str,
    reviewed_rows: tuple[ReviewedRowTruth, ...] = (),
    reviewed_source_objects: tuple[ReviewedSourceObservation, ...] = (),
    unresolved_source: bool = False,
) -> QualifiedTableDenominator:
    return QualifiedTableDenominator(
        oracle_id=oracle_id,
        case_id=case_id,
        physical_page=page,
        region_id=region_id,
        region_bbox=bbox,
        review_state="unresolved" if unresolved_source else "source_qualified",
        canonical_action=(
            "retain_candidate_with_concern"
            if unresolved_source
            else "score_reviewed_dimensions"
        ),
        denominators=denominators,
        reviewed_rows=reviewed_rows,
        reviewed_source_objects=reviewed_source_objects,
        unresolved_dimensions=unresolved,
        required_concerns=_concerns(unresolved),
        evidence_path=evidence_path,
    )


_COMMON_CELL_GAPS = ("cell_count", "cell_bbox_count", "cell_provenance_count")

QUALIFIED_TABLES = (
    _qualified(
        oracle_id="finance-p1-operations",
        case_id="finance-10k",
        page=1,
        region_id="operations-table",
        bbox=FiniteBBox(x=48.0, y=99.0, width=516.0, height=447.0, tolerance_pt=3.0),
        denominators=(
            _denominator("finance-p1-columns", "column_count", 4, "columns", "Stub plus three reviewed period columns."),
            _denominator("finance-p1-period-span", "supported_col_span", 1, "spans", "Years ended governs three date columns.", members=(3,)),
        ),
        unresolved=("row_count_including_header", *_COMMON_CELL_GAPS),
        evidence_path="tracker/benchmarks/llamaparse-15/cases/finance-10k.md",
    ),
    _qualified(
        oracle_id="finance-p2-balance-sheet",
        case_id="finance-10k",
        page=2,
        region_id="balance-sheet-table",
        bbox=FiniteBBox(x=48.0, y=100.0, width=516.0, height=602.0, tolerance_pt=3.0),
        denominators=(
            _denominator("finance-p2-columns", "column_count", 3, "columns", "Stub plus two reviewed amount columns."),
            _denominator("finance-p2-wrapped-row", "logical_wrapped_row_count", 1, "rows", "The visually wrapped common-stock label is one source row."),
        ),
        unresolved=("row_count_including_header", "supported_col_span", *_COMMON_CELL_GAPS),
        evidence_path="tracker/benchmarks/llamaparse-15/cases/finance-10k.md",
    ),
    _qualified(
        oracle_id="finance-p3-cash-flow",
        case_id="finance-10k",
        page=3,
        region_id="cash-flow-table",
        bbox=FiniteBBox(x=48.0, y=90.0, width=517.0, height=619.0, tolerance_pt=3.0),
        denominators=(
            _denominator("finance-p3-columns", "column_count", 4, "columns", "Stub plus three reviewed period columns."),
            _denominator("finance-p3-period-span", "supported_col_span", 1, "spans", "Years ended governs three date columns.", members=(3,)),
        ),
        unresolved=("row_count_including_header", *_COMMON_CELL_GAPS),
        evidence_path="tracker/benchmarks/llamaparse-15/cases/finance-10k.md",
    ),
    _qualified(
        oracle_id="postal-p1-glossary",
        case_id="postal-10k",
        page=1,
        region_id="glossary-table",
        bbox=None,
        denominators=(
            _denominator("postal-p1-rows", "row_count_including_header", 40, "rows", "One header plus 39 source glossary entries, including final FERS."),
            _denominator("postal-p1-data-rows", "data_row_count", 39, "rows", "The reviewed glossary has 39 entries."),
            _denominator("postal-p1-columns", "column_count", 2, "columns", "Acronym and definition columns."),
            _denominator("postal-p1-cells", "cell_count", 80, "cells", "The reviewed striped glossary has two explicit source values in each of 40 rows.", evidence_basis="reviewed_visual_render"),
            _denominator("postal-p1-header-ownership", "header_ownership", 2, "cells", "The visible first row owns the Acronym and Definition column headers.", evidence_basis="reviewed_visual_render"),
            _denominator("postal-p1-bottom-boundary", "row_boundary", 1, "rows", "The final striped FERS row is inside the source table boundary.", evidence_basis="reviewed_vector_geometry"),
        ),
        reviewed_rows=(
            ReviewedRowTruth(
                row_id="postal-p1-header-row",
                source_table_row_index=0,
                values=("Term or Acronym", "Definition"),
                bbox=FiniteBBox(x=58.5, y=94.5, width=495.0, height=15.75),
                evidence_basis="reviewed_native_text",
                qualification="The source-rendered first stripe is the two-column glossary header.",
                role="column_header",
                source_refs=(
                    "benchmark-expertmodeldata/postal-10k.pdf#page=1&text=Term-or-Acronym",
                    "benchmark-expertmodeldata/postal-10k.pdf#page=1&text=Definition",
                ),
            ),
            ReviewedRowTruth(
                row_id="postal-p1-fers-row",
                source_table_row_index=39,
                values=("FERS", "Federal Employees Retirement System"),
                bbox=FiniteBBox(x=58.5, y=708.75, width=495.0, height=15.75),
                evidence_basis="reviewed_native_text",
                qualification="The source-rendered final stripe is the complete FERS glossary row.",
                role="body",
                source_refs=(
                    "benchmark-expertmodeldata/postal-10k.pdf#page=1&text=FERS",
                    "benchmark-expertmodeldata/postal-10k.pdf#page=1&text=Federal-Employees-Retirement-System",
                ),
            ),
        ),
        unresolved=("cell_bbox_count", "cell_provenance_count"),
        evidence_path="tracker/benchmarks/llamaparse-15/cases/postal-10k.md",
    ),
    *tuple(
        _qualified(
            oracle_id=f"postal-p{page}-financial",
            case_id="postal-10k",
            page=page,
            region_id="financial-table",
            bbox=None,
            denominators=(
                _denominator(f"postal-p{page}-columns", "column_count", 4, "columns", "Stub plus 2025, 2024, and 2023 columns."),
                _denominator(f"postal-p{page}-period-span", "supported_col_span", 1, "spans", "The reviewed period heading spans three year columns.", members=(3,)),
            ),
            unresolved=("row_count_including_header", *_COMMON_CELL_GAPS),
            evidence_path="tracker/benchmarks/llamaparse-15/cases/postal-10k.md",
        )
        for page in (2, 3)
    ),
    _qualified(
        oracle_id="clinical-p2-table-1",
        case_id="clinical-study",
        page=2,
        region_id="table-1",
        bbox=FiniteBBox(x=34.10, y=86.34, width=542.81, height=411.92, tolerance_pt=2.0),
        denominators=(
            _denominator("clinical-p2-columns", "column_count", 6, "columns", "The source Table 1 has six columns."),
            _denominator("clinical-p2-header-ownership", "header_ownership", 6, "cells", "The source has one stub header slot and five visible data-column headers.", evidence_basis="reviewed_visual_render"),
            _denominator("clinical-p2-stub-sections", "stub_only_section_row_count", 5, "rows", "M (SD), % (n), Marital status, Education, and Occupation occupy only the stub."),
            _denominator("clinical-p2-false-spans", "false_span_count", 0, "spans", "The five section labels must not become full-width spans."),
        ),
        unresolved=("row_count_including_header", *_COMMON_CELL_GAPS),
        evidence_path="tracker/benchmarks/llamaparse-15/cases/clinical-study.md",
    ),
    _qualified(
        oracle_id="clinical-p4-table-2",
        case_id="clinical-study",
        page=4,
        region_id="table-2",
        bbox=FiniteBBox(x=34.25, y=87.94, width=542.68, height=201.25, tolerance_pt=2.0),
        denominators=(
            _denominator("clinical-p4-columns", "column_count", 9, "columns", "The source Table 2 has nine, not ten, columns."),
            _denominator("clinical-p4-header-ownership", "header_ownership", 9, "cells", "Nine visible leaf header slots remain owned by their source columns; group ownership is scored separately by spans.", evidence_basis="reviewed_visual_render"),
            _denominator("clinical-p4-stub-sections", "stub_only_section_row_count", 2, "rows", "Primary and Secondary remain in the stub with blanks."),
            _denominator("clinical-p4-group-spans", "supported_col_span", 2, "spans", "Reviewed group headers cover four treatment and three analysis columns.", members=(4, 3)),
            _denominator("clinical-p4-false-spans", "false_span_count", 0, "spans", "Primary and Secondary are not full-width spans."),
        ),
        unresolved=("row_count_including_header", *_COMMON_CELL_GAPS),
        evidence_path="tracker/benchmarks/llamaparse-15/cases/clinical-study.md",
    ),
    *tuple(
        _qualified(
            oracle_id=f"timetable-p{page}",
            case_id="ny-timetable",
            page=page,
            region_id="weekday-timetable",
            bbox=FiniteBBox(x=22.6, y=22.8, width=354.3, height=744.6, tolerance_pt=3.0),
            denominators=(
                _denominator(f"timetable-p{page}-visual-rows", "visual_row_count", 52, "rows", "One title row, one station-header row, and 50 service rows."),
                _denominator(f"timetable-p{page}-data-rows", "data_row_count", 50, "rows", "Native source review establishes 50 service rows."),
                _denominator(f"timetable-p{page}-columns", "column_count", 13, "columns", "Native source review establishes 13 columns."),
            ),
            reviewed_rows=(
                (
                    ReviewedRowTruth(
                        row_id="timetable-p3-source-row-28",
                        source_table_row_index=28,
                        values=("", "3:01", "3:05", "3:18", "3:24", "3:30", "3:32", "3:38", "3:43", "3:48", "3:51", "3:55", "3:57"),
                        bbox=FiniteBBox(x=24.49, y=476.17, width=350.51, height=11.98, tolerance_pt=0.5),
                        evidence_basis="reviewed_native_text",
                        qualification="This exact source row catches the expert's omitted 3:32 and shifted duplicate 3:57.",
                    ),
                )
                if page == 3
                else ()
            ),
            unresolved=("cell_count", "cell_bbox_count", "cell_provenance_count", "header_ownership", "rotation_mapping"),
            evidence_path="tracker/benchmarks/llamaparse-15/cases/ny-timetable.md",
        )
        for page in (1, 2, 3)
    ),
    _qualified(
        oracle_id="acord-p1-coverage-grid",
        case_id="insurance-acord",
        page=1,
        region_id="coverage-grid",
        bbox=FiniteBBox(x=17.99, y=287.406, width=576.327, height=277.886, tolerance_pt=1.0),
        denominators=(
            _denominator("acord-p1-table-region", "table_count", 1, "tables", "One isolated coverage-grid region is source-reviewed; its topology is not."),
        ),
        reviewed_source_objects=(
            ReviewedSourceObservation(
                observation_id="acord-p1-coverage-vector-region",
                kind="vector_region",
                physical_page=1,
                bbox=FiniteBBox(x=17.99, y=287.406, width=576.327, height=277.886, tolerance_pt=1.0),
                source_ref="benchmark-expertmodeldata/insurance-acord.pdf#page=1&region=coverage-grid",
                evidence_basis="reviewed_vector_geometry",
                qualification="This is the independently reviewed form-owned vector region, not canonical table topology.",
            ),
            ReviewedSourceObservation(
                observation_id="acord-p1-insr-ltr-header",
                kind="visible_text",
                physical_page=1,
                bbox=FiniteBBox(x=20.04, y=288.8009172, width=13.8552444, height=11.1996, tolerance_pt=0.1),
                text="INSR\nLTR",
                source_ref="benchmark-expertmodeldata/insurance-acord.pdf#page=1&text=INSR-LTR",
                evidence_basis="reviewed_native_text",
                qualification="Visible header text is addressable, but its surrounding form-grid ownership remains unresolved.",
            ),
            ReviewedSourceObservation(
                observation_id="acord-p1-type-of-insurance-header",
                kind="visible_text",
                physical_page=1,
                bbox=FiniteBBox(x=75.12, y=292.6809828, width=61.9601004, height=5.9004, tolerance_pt=0.1),
                text="TYPE OF INSURANCE",
                source_ref="benchmark-expertmodeldata/insurance-acord.pdf#page=1&text=TYPE-OF-INSURANCE",
                evidence_basis="reviewed_native_text",
                qualification="Visible header text is addressable without treating the form-owned grid as canonical.",
            ),
            ReviewedSourceObservation(
                observation_id="acord-p1-limits-header",
                kind="visible_text",
                physical_page=1,
                bbox=FiniteBBox(x=499.68, y=292.6809828, width=19.3415112, height=5.9004, tolerance_pt=0.1),
                text="LIMITS",
                source_ref="benchmark-expertmodeldata/insurance-acord.pdf#page=1&text=LIMITS",
                evidence_basis="reviewed_native_text",
                qualification="Visible header text is addressable; row and cell ownership remain unresolved.",
            ),
        ),
        unresolved=("row_count_including_header", "column_count", "cell_count", "supported_col_span", "cell_bbox_count", "cell_provenance_count", "header_ownership", "form_grid_topology"),
        evidence_path="tracker/benchmarks/llamaparse-15/cases/insurance-acord.md",
        unresolved_source=True,
    ),
)


P04_US01_REAL_ORACLE = P04Us01Oracle(
    sidecar_version=SIDECAR_VERSION,
    policy_id=POLICY_ID,
    story_id="P04-US01",
    sources=SOURCE_IDENTITIES,
    exact_tables=(EXHIBIT7_EXACT,),
    qualified_tables=QUALIFIED_TABLES,
)


def oracle_sha256(oracle: P04Us01Oracle = P04_US01_REAL_ORACLE) -> str:
    payload = json.dumps(
        oracle.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def exhibit7_source_projection() -> dict[str, Any]:
    """Return the exact legacy P00 shape expected by the cross-check test."""

    return {
        "row_count": EXHIBIT7_EXACT.row_count,
        "column_count": EXHIBIT7_EXACT.column_count,
        "cell_count": EXHIBIT7_EXACT.cell_count,
        "cells": tuple(
            {
                "row": cell.row,
                "column": cell.column,
                "row_span": cell.row_span,
                "col_span": cell.col_span,
                "text": cell.text,
                "bbox": (
                    cell.bbox.x,
                    cell.bbox.y,
                    cell.bbox.width,
                    cell.bbox.height,
                ),
            }
            for cell in EXHIBIT7_EXACT.cells
        ),
    }
