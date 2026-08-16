"""Deterministic Phase 0 reviewed-claim inventory construction.

This module maps each frozen expert-validation table row to one generalized
:class:`ReviewedClaimRecord`. It is benchmark/reporting infrastructure only
and must not be imported by production code.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re

from tests.benchmarks.contracts import CONTRACT_VERSION, TruthClass
from tests.benchmarks.corpus_registry import (
    PortableCorpusRegistry,
    resolve_portable_path,
    sha256_file,
)
from tests.benchmarks.reviewed_claims import (
    DISPLAY_PAGE_COORDINATES,
    ClaimReviewStatus,
    ClaimType,
    Derivation,
    InclusionMask,
    RegionScope,
    ReviewBatch,
    ReviewProvenance,
    ReviewRegistryError,
    ReviewedClaimRecord,
    ReviewerVersion,
    SourceLocator,
    canonical_review_batch_json,
    corpus_registry_sha256,
    load_review_batch,
    validate_review_batch_against_registry,
)


BATCH_A_ID = "p00-us06-reviewed-claims-batch-a"
BATCH_A_EVIDENCE_PATH = (
    "tracker/phase-00-baseline/evidence/"
    "P00-US06-reviewed-claims-batch-a.json"
)
BATCH_A_CASE_CLAIM_COUNTS = {
    "catastrophe-recap": 15,
    "esg-metrics": 13,
    "finance-10k": 11,
    "manufacturing-report": 21,
    "purchase-agreement": 11,
}
BATCH_A_CLAIM_COUNT = 71
BATCH_A_REVIEWER = ReviewerVersion(
    reviewer_id="LlamaParse-15 source review",
    review_version="2026-07-28-v1",
)
BATCH_B_ID = "p00-us07-reviewed-claims-batch-b"
BATCH_B_EVIDENCE_PATH = (
    "tracker/phase-00-baseline/evidence/"
    "P00-US07-reviewed-claims-batch-b.json"
)
BATCH_B_CASE_CLAIM_COUNTS = {
    "clean-energy": 14,
    "clinical-study": 21,
    "component-datasheet": 18,
    "insurance-acord": 13,
    "ny-timetable": 10,
}
BATCH_B_CLAIM_COUNT = 76
BATCH_B_REVIEWER = ReviewerVersion(
    reviewer_id="LlamaParse-15 source review",
    review_version="2026-07-28-v1",
)
BATCH_C_ID = "p00-us08-reviewed-claims-batch-c"
BATCH_C_EVIDENCE_PATH = (
    "tracker/phase-00-baseline/evidence/"
    "P00-US08-reviewed-claims-batch-c.json"
)
BATCH_C_CASE_CLAIM_COUNTS = {
    "egov-survey": 12,
    "health-report": 12,
    "postal-10k": 12,
    "settlement-agreement": 10,
    "uber-earnings": 17,
}
BATCH_C_CLAIM_COUNT = 63
BATCH_C_REVIEWER = ReviewerVersion(
    reviewer_id="LlamaParse-15 source review",
    review_version="2026-07-28-v1",
)


@dataclass(frozen=True)
class _ReviewRow:
    subject: str
    representation: str
    raw_status: str
    assessment: str


@dataclass(frozen=True)
class _FlexibleReviewRow:
    subject: str
    representation: str
    supplemental: tuple[tuple[str, str], ...]
    raw_status: str
    assessment: str


@dataclass(frozen=True)
class _RowPolicy:
    pages: tuple[int, ...]
    review_status: ClaimReviewStatus
    claim_type: ClaimType
    evidence_class: TruthClass
    derivation: Derivation | None = None

    @property
    def inclusion_mask(self) -> InclusionMask:
        semantic = self.review_status in {
            ClaimReviewStatus.VERIFIED,
            ClaimReviewStatus.PARTIALLY_VERIFIED,
        }
        literal = (
            self.review_status is ClaimReviewStatus.VERIFIED
            and self.evidence_class
            in {
                TruthClass.VISIBLE_TEXT,
                TruthClass.NATIVE_DATA,
                TruthClass.EMBEDDED_DATA,
            }
        )
        return InclusionMask(
            literal_parity=literal,
            semantic_parity=semantic,
        )


@dataclass(frozen=True)
class _CasePolicy:
    review_sha256: str
    rows: tuple[_RowPolicy, ...]


def _row(
    pages: int | tuple[int, ...],
    review_status: ClaimReviewStatus,
    claim_type: ClaimType,
    evidence_class: TruthClass,
    *,
    derivation: Derivation | None = None,
) -> _RowPolicy:
    page_tuple = (pages,) if isinstance(pages, int) else pages
    return _RowPolicy(
        pages=page_tuple,
        review_status=review_status,
        claim_type=claim_type,
        evidence_class=evidence_class,
        derivation=derivation,
    )


V = ClaimReviewStatus.VERIFIED
P = ClaimReviewStatus.PARTIALLY_VERIFIED
N = ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE
I = ClaimReviewStatus.INCORRECT
Q = ClaimReviewStatus.POTENTIALLY_INFERRED

TEXT = ClaimType.TEXT
PAGE = ClaimType.PAGE_IDENTITY
TABLE = ClaimType.TABLE
CHART = ClaimType.CHART
METADATA = ClaimType.METADATA

VISIBLE = TruthClass.VISIBLE_TEXT
NATIVE = TruthClass.NATIVE_DATA
INFERRED = TruthClass.INFERRED
UNKNOWABLE = TruthClass.UNKNOWABLE
EMBEDDED = TruthClass.EMBEDDED_DATA


_CASE_POLICIES: dict[str, _CasePolicy] = {
    "catastrophe-recap": _CasePolicy(
        review_sha256=(
            "99b2110820d01d6a63e3677c0b49a3b17d3b5958ec186df0df552009ba976770"
        ),
        rows=(
            _row(1, V, PAGE, NATIVE),
            _row(1, P, ClaimType.IMAGE, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TABLE, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, CHART, INFERRED),
            _row(
                1,
                I,
                CHART,
                TruthClass.MEASURED,
                derivation=Derivation(
                    method=(
                        "PDF vector bar extent calibrated by linear least-squares "
                        "against the vector baseline and five printed y-axis ticks"
                    ),
                    tolerance=1,
                    tolerance_unit="2025_USD_billions",
                ),
            ),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, PAGE, VISIBLE),
            _row(1, V, ClaimType.STRUCTURE, INFERRED),
            _row(1, P, ClaimType.GEOMETRY, NATIVE),
            _row(1, N, METADATA, UNKNOWABLE),
            _row(1, P, METADATA, NATIVE),
        ),
    ),
    "esg-metrics": _CasePolicy(
        review_sha256=(
            "174180aa1cb2b42dd2a7deb8692b2c12e69d3edbb3c3d91b3c9934edb07da563"
        ),
        rows=(
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, ClaimType.GEOMETRY, NATIVE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TABLE, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, CHART, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, ClaimType.RELATIONSHIP, NATIVE),
            _row(1, P, CHART, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, ClaimType.LINK, INFERRED),
            _row(1, N, METADATA, UNKNOWABLE),
        ),
    ),
    "finance-10k": _CasePolicy(
        review_sha256=(
            "3a2a661df038536eb95d72febe43189248df37b243194bfede441e1d38c61aff"
        ),
        rows=(
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, TABLE, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(2, V, TEXT, VISIBLE),
            _row(2, P, TABLE, INFERRED),
            _row(2, V, TEXT, VISIBLE),
            _row(3, V, TEXT, VISIBLE),
            _row(3, P, TABLE, INFERRED),
            _row(3, V, TEXT, VISIBLE),
            _row((1, 2, 3), V, ClaimType.GEOMETRY, INFERRED),
            _row((1, 2, 3), N, METADATA, UNKNOWABLE),
        ),
    ),
    "manufacturing-report": _CasePolicy(
        review_sha256=(
            "4c38cafd256c090fc9d4041a4465d12f34c0855f8568d25c66fe7eb896a11dd1"
        ),
        rows=(
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, TABLE, NATIVE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, TABLE, NATIVE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, PAGE, VISIBLE),
            _row(2, V, TEXT, VISIBLE),
            _row(2, N, TABLE, INFERRED),
            _row(2, V, TEXT, VISIBLE),
            _row(2, V, TEXT, VISIBLE),
            _row(2, I, TABLE, NATIVE),
            _row(2, V, TEXT, VISIBLE),
            _row(2, V, TEXT, VISIBLE),
            _row(2, V, PAGE, VISIBLE),
            _row(3, V, TEXT, VISIBLE),
            _row(3, N, TABLE, INFERRED),
            _row(3, V, TEXT, VISIBLE),
            _row(3, V, TEXT, VISIBLE),
            _row(3, P, PAGE, VISIBLE),
        ),
    ),
    "purchase-agreement": _CasePolicy(
        review_sha256=(
            "715e14ee37fd5263939d01dd9090b30d2a3c1f6ea6fc703bbb7ca80e529213a4"
        ),
        rows=(
            _row(1, P, ClaimType.TEXT_STYLE, NATIVE),
            _row(1, V, ClaimType.TEXT_STYLE, NATIVE),
            _row(1, V, ClaimType.STRUCTURE, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, I, ClaimType.TEXT_STYLE, NATIVE),
            _row(1, V, ClaimType.TEXT_STYLE, NATIVE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, ClaimType.GEOMETRY, NATIVE),
            _row(1, N, METADATA, UNKNOWABLE),
            _row(1, I, ClaimType.ARTIFACT_INVENTORY, NATIVE),
        ),
    ),
}


_BATCH_B_CASE_POLICIES: dict[str, _CasePolicy] = {
    "clean-energy": _CasePolicy(
        review_sha256=(
            "1345fc03e3f55f415dd7682c827e24b6022d25b46ef0ee68e8437bc145f0ca5a"
        ),
        rows=(
            _row(1, V, PAGE, NATIVE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, Q, CHART, INFERRED),
            _row(1, P, CHART, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, PAGE, VISIBLE),
            _row(1, V, ClaimType.STRUCTURE, INFERRED),
            _row(1, V, ClaimType.GEOMETRY, INFERRED),
            _row(1, N, METADATA, UNKNOWABLE),
            _row(1, P, METADATA, NATIVE),
        ),
    ),
    "clinical-study": _CasePolicy(
        review_sha256=(
            "fa5c1e863b7cee50ca4eea4b6c2debd042c7d9bbe143663cad64a26a07f5806f"
        ),
        rows=(
            _row((1, 2, 3, 4), V, PAGE, NATIVE),
            _row((1, 2, 3, 4), V, PAGE, VISIBLE),
            _row((1, 2, 3, 4), V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, Q, ClaimType.IMAGE, INFERRED),
            _row(1, V, ClaimType.STRUCTURE, INFERRED),
            _row(2, V, TABLE, VISIBLE),
            _row(2, P, TABLE, NATIVE),
            _row(2, V, TEXT, VISIBLE),
            _row(3, V, ClaimType.DIAGRAM, VISIBLE),
            _row(3, P, ClaimType.RELATIONSHIP, INFERRED),
            _row(4, V, TABLE, VISIBLE),
            _row(4, I, TABLE, NATIVE),
            _row(4, P, TEXT, VISIBLE),
            _row(4, V, TEXT, VISIBLE),
            _row((2, 3, 4), V, ClaimType.LINK, EMBEDDED),
            _row((2, 3, 4), V, ClaimType.GEOMETRY, INFERRED),
            _row(1, I, ClaimType.GEOMETRY, NATIVE),
            _row((1, 2, 3, 4), N, METADATA, UNKNOWABLE),
            _row((1, 2, 3, 4), P, METADATA, NATIVE),
        ),
    ),
    "component-datasheet": _CasePolicy(
        review_sha256=(
            "6e41940bd8ffd61dbf7fce8ec4882f8935f6a94c481c844d7dc828812c4b53fe"
        ),
        rows=(
            _row((1, 2, 3), V, PAGE, NATIVE),
            _row((1, 2, 3), V, PAGE, VISIBLE),
            _row((1, 2, 3), V, ClaimType.STRUCTURE, INFERRED),
            _row(1, V, ClaimType.STRUCTURE, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, Q, ClaimType.IMAGE, INFERRED),
            _row(1, P, ClaimType.IMAGE, VISIBLE),
            _row(2, V, TEXT, VISIBLE),
            _row(2, Q, ClaimType.DIAGRAM, INFERRED),
            _row(2, I, ClaimType.DIAGRAM, VISIBLE),
            _row(2, V, TEXT, VISIBLE),
            _row(3, V, TABLE, VISIBLE),
            _row(3, P, TABLE, INFERRED),
            _row(3, I, ClaimType.TEXT_STYLE, NATIVE),
            _row((1, 2, 3), V, PAGE, VISIBLE),
            _row((1, 2, 3), V, ClaimType.GEOMETRY, INFERRED),
            _row((1, 2, 3), N, METADATA, UNKNOWABLE),
            _row((1, 2, 3), P, METADATA, NATIVE),
        ),
    ),
    "insurance-acord": _CasePolicy(
        review_sha256=(
            "327e9ed62a2703075e00434d5b02bead11525692d43178198a9377ca0adeaddb"
        ),
        rows=(
            _row(1, Q, ClaimType.IMAGE, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, TABLE, INFERRED),
            _row(1, P, ClaimType.STRUCTURE, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, I, TABLE, NATIVE),
            _row(1, P, ClaimType.FORM, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, I, ClaimType.FORM, NATIVE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, N, METADATA, UNKNOWABLE),
            _row(1, P, METADATA, NATIVE),
        ),
    ),
    "ny-timetable": _CasePolicy(
        review_sha256=(
            "68e1ce268850da1fa09180c0bd0262976ba983dcc5de039c21b1bbde91c7822b"
        ),
        rows=(
            _row((1, 2, 3), V, PAGE, NATIVE),
            _row((1, 2, 3), V, TEXT, VISIBLE),
            _row(1, V, TABLE, VISIBLE),
            _row(2, V, TABLE, VISIBLE),
            _row(2, P, TABLE, VISIBLE),
            _row(3, I, TABLE, VISIBLE),
            _row((1, 2, 3), V, PAGE, VISIBLE),
            _row((1, 2, 3), P, ClaimType.GEOMETRY, NATIVE),
            _row((1, 2, 3), N, METADATA, UNKNOWABLE),
            _row(
                (1, 2, 3),
                I,
                ClaimType.ARTIFACT_INVENTORY,
                NATIVE,
            ),
        ),
    ),
}


_BATCH_C_CASE_POLICIES: dict[str, _CasePolicy] = {
    "egov-survey": _CasePolicy(
        review_sha256=(
            "bbdb74c3c05204006c67d5868ad9f7229221c469d6e31a04906a67ac4980bc25"
        ),
        rows=(
            _row(1, V, PAGE, NATIVE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TABLE, VISIBLE),
            _row(1, V, CHART, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, PAGE, VISIBLE),
            _row(1, P, ClaimType.GEOMETRY, NATIVE),
            _row(1, N, METADATA, UNKNOWABLE),
            _row(1, P, METADATA, NATIVE),
        ),
    ),
    "health-report": _CasePolicy(
        review_sha256=(
            "13e74b08061571472993123e5bcfa1ac00ca96a5191a4887bcb94589ccc876f5"
        ),
        rows=(
            _row(1, P, PAGE, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, N, TABLE, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, ClaimType.LINK, EMBEDDED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, I, CHART, INFERRED),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, ClaimType.LINK, EMBEDDED),
            _row(1, V, PAGE, VISIBLE),
            _row(1, N, METADATA, UNKNOWABLE),
        ),
    ),
    "postal-10k": _CasePolicy(
        review_sha256=(
            "e0eb3d81b012018a1b1a2d4d37a17f5c9f62c0014e52bd652845d6ac7fc9cce7"
        ),
        rows=(
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TABLE, VISIBLE),
            _row(1, V, ClaimType.TEXT_STYLE, NATIVE),
            _row((2, 3), V, TABLE, VISIBLE),
            _row(2, V, TABLE, NATIVE),
            _row(2, I, TABLE, NATIVE),
            _row(3, I, TABLE, NATIVE),
            _row((2, 3), I, TEXT, VISIBLE),
            _row((2, 3), P, ClaimType.STRUCTURE, INFERRED),
            _row((2, 3), I, METADATA, INFERRED),
            _row((1, 2, 3), N, METADATA, UNKNOWABLE),
            _row(
                (1, 2, 3),
                I,
                ClaimType.ARTIFACT_INVENTORY,
                NATIVE,
            ),
        ),
    ),
    "settlement-agreement": _CasePolicy(
        review_sha256=(
            "1e1680bd2b28eca6c68c364a32e1381d64ae7d5c8155325ac03c10e4d8addba9"
        ),
        rows=(
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, P, ClaimType.STRUCTURE, INFERRED),
            _row(1, V, TABLE, VISIBLE),
            _row(1, V, TEXT, VISIBLE),
            _row(1, V, PAGE, VISIBLE),
            _row(1, I, METADATA, INFERRED),
            _row(1, P, ClaimType.GEOMETRY, NATIVE),
            _row(1, N, METADATA, UNKNOWABLE),
            _row(1, I, ClaimType.ARTIFACT_INVENTORY, NATIVE),
        ),
    ),
    "uber-earnings": _CasePolicy(
        review_sha256=(
            "344aa02fc3e0315b912e42489331951c39f6bdbb9b7e0e4fdfc17ebb44018567"
        ),
        rows=(
            _row(1, V, TEXT, VISIBLE),
            _row(1, Q, ClaimType.IMAGE, INFERRED),
            _row(1, P, ClaimType.IMAGE, NATIVE),
            _row(2, V, TEXT, VISIBLE),
            _row(2, V, CHART, VISIBLE),
            _row(
                2,
                Q,
                CHART,
                TruthClass.MEASURED,
                derivation=Derivation(
                    method=(
                        "Linear interpolation of shared-baseline PDF vector "
                        "bar heights against the printed $56B (2022) and $82B "
                        "(Q1’25 ARR) endpoint labels"
                    ),
                    tolerance=2,
                    tolerance_unit="USD_billions",
                ),
            ),
            _row(2, V, CHART, VISIBLE),
            _row(
                2,
                Q,
                CHART,
                TruthClass.MEASURED,
                derivation=Derivation(
                    method=(
                        "Linear interpolation of shared-baseline PDF vector "
                        "bar heights against the printed $0.6B and $3.1B "
                        "endpoint labels"
                    ),
                    tolerance=0.25,
                    tolerance_unit="USD_billions",
                ),
            ),
            _row(2, V, CHART, VISIBLE),
            _row(
                2,
                Q,
                CHART,
                TruthClass.MEASURED,
                derivation=Derivation(
                    method=(
                        "Linear interpolation of PDF vector line-point y "
                        "positions against the printed 1.0% and 3.7% "
                        "endpoint labels"
                    ),
                    tolerance=0.25,
                    tolerance_unit="percentage_points",
                ),
            ),
            _row(2, I, ClaimType.IMAGE, INFERRED),
            _row(2, V, ClaimType.IMAGE, INFERRED),
            _row(3, V, ClaimType.DIAGRAM, VISIBLE),
            _row(3, Q, ClaimType.RELATIONSHIP, INFERRED),
            _row(3, P, ClaimType.DIAGRAM, INFERRED),
            _row((1, 2, 3), N, METADATA, UNKNOWABLE),
            _row(
                (1, 2, 3),
                P,
                ClaimType.ARTIFACT_INVENTORY,
                NATIVE,
            ),
        ),
    ),
}


_STATUS_PREFIXES = (
    ("Not independently verifiable", N),
    ("Partially verified", P),
    ("Potentially inferred", ClaimReviewStatus.POTENTIALLY_INFERRED),
    ("Incorrect", I),
    ("Verified", V),
)


def _split_markdown_row(line: str) -> tuple[str, ...]:
    """Split one pipe table row without splitting escaped or code-span pipes."""

    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        raise ValueError("expert-validation table rows must use outer pipes")

    cells: list[str] = []
    current: list[str] = []
    in_code = False
    index = 1
    while index < len(stripped) - 1:
        char = stripped[index]
        if char == "\\" and index + 1 < len(stripped) - 1:
            current.extend((char, stripped[index + 1]))
            index += 2
            continue
        if char == "`":
            in_code = not in_code
            current.append(char)
        elif char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return tuple(cells)


def _normalize_status(raw_status: str) -> ClaimReviewStatus:
    normalized = raw_status.replace("**", "").strip()
    for prefix, status in _STATUS_PREFIXES:
        if normalized == prefix or normalized.startswith(f"{prefix} "):
            return status
    raise ValueError(f"unsupported expert-validation status: {raw_status}")


def _expert_validation_rows(path: Path) -> tuple[_ReviewRow, ...]:
    """Return only data rows below the exact expert-validation H2."""

    in_section = False
    rows: list[_ReviewRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "## Expert element validation":
            if in_section:
                raise ValueError("duplicate expert-validation section")
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or not line.lstrip().startswith("|"):
            continue

        cells = _split_markdown_row(line)
        if len(cells) != 4:
            raise ValueError(
                "expert-validation rows must contain exactly four columns"
            )
        if cells[2] == "Status":
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(_ReviewRow(*cells))

    if not in_section:
        raise ValueError("missing expert-validation section")
    return tuple(rows)


def _flexible_expert_validation_rows(
    path: Path,
) -> tuple[_FlexibleReviewRow, ...]:
    """Read four- or five-column expert tables by their status header."""

    in_section = False
    headers: tuple[str, ...] | None = None
    rows: list[_FlexibleReviewRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "## Expert element validation":
            if in_section:
                raise ValueError("duplicate expert-validation section")
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or not line.lstrip().startswith("|"):
            continue

        cells = _split_markdown_row(line)
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if "Status" in cells:
            if len(cells) not in {4, 5}:
                raise ValueError(
                    "expert-validation tables must contain four or five columns"
                )
            headers = cells
            continue
        if headers is None or len(cells) != len(headers):
            raise ValueError(
                "expert-validation data rows must match a recognized header"
            )

        status_index = headers.index("Status")
        if status_index != len(headers) - 2:
            raise ValueError(
                "expert-validation status must precede the assessment column"
            )
        rows.append(
            _FlexibleReviewRow(
                subject=cells[0],
                representation=cells[1],
                supplemental=tuple(
                    zip(
                        headers[2:status_index],
                        cells[2:status_index],
                        strict=True,
                    )
                ),
                raw_status=cells[status_index],
                assessment=cells[-1],
            )
        )

    if not in_section:
        raise ValueError("missing expert-validation section")
    return tuple(rows)


def _claim_text(row: _ReviewRow) -> str:
    return (
        f"{row.subject} — {row.representation}. "
        f"Review verdict: {row.raw_status}. Assessment: {row.assessment}"
    )


def _flexible_claim_text(row: _FlexibleReviewRow) -> str:
    supplemental = "".join(
        f"{header}: {value}. "
        for header, value in row.supplemental
    )
    return (
        f"{row.subject} — {row.representation}. {supplemental}"
        f"Review verdict: {row.raw_status}. Assessment: {row.assessment}"
    )


def _region_scope(claim_type: ClaimType) -> RegionScope:
    if claim_type is ClaimType.PAGE_IDENTITY:
        return RegionScope.PAGE
    if claim_type in {ClaimType.METADATA, ClaimType.ARTIFACT_INVENTORY}:
        return RegionScope.DERIVED_ARTIFACT
    return RegionScope.SOURCE_REGION


def build_reviewed_claim_batch_a(
    workspace_root: str | Path,
    registry: PortableCorpusRegistry,
) -> ReviewBatch:
    """Build all 71 records from frozen review rows and explicit policies."""

    records: list[ReviewedClaimRecord] = []
    for case_id, case_policy in _CASE_POLICIES.items():
        case = registry.case_by_id(case_id)
        review_path = resolve_portable_path(workspace_root, case.review_path)
        current_review_sha256 = sha256_file(review_path)
        if current_review_sha256 != case_policy.review_sha256:
            raise ReviewRegistryError(
                f"{case_id} review SHA-256 changed: expected "
                f"{case_policy.review_sha256}, got {current_review_sha256}"
            )

        source_rows = _expert_validation_rows(review_path)
        if len(source_rows) != len(case_policy.rows):
            raise ReviewRegistryError(
                f"{case_id} expected {len(case_policy.rows)} review rows, "
                f"got {len(source_rows)}"
            )

        pages = {page.physical_page: page for page in case.pages}
        for ordinal, (source_row, row_policy) in enumerate(
            zip(source_rows, case_policy.rows, strict=True),
            start=1,
        ):
            source_status = _normalize_status(source_row.raw_status)
            if source_status is not row_policy.review_status:
                raise ReviewRegistryError(
                    f"{case_id} expert row {ordinal} status changed: expected "
                    f"{row_policy.review_status.value}, got {source_status.value}"
                )

            locators = []
            for physical_page in row_policy.pages:
                try:
                    page = pages[physical_page]
                except KeyError as exc:
                    raise ReviewRegistryError(
                        f"{case_id} expert row {ordinal} uses unregistered "
                        f"physical page {physical_page}"
                    ) from exc
                locators.append(
                    SourceLocator(
                        case_id=case_id,
                        physical_page=physical_page,
                        printed_page=page.printed_page,
                        region_id=(
                            f"expert-row:{ordinal:02d}:source:p{physical_page:02d}"
                        ),
                        region_scope=_region_scope(row_policy.claim_type),
                        bbox=None,
                        coordinates=DISPLAY_PAGE_COORDINATES,
                    )
                )

            claim_id = f"p00-us06:{case_id}:expert-row-{ordinal:02d}"
            records.append(
                ReviewedClaimRecord(
                    schema_version=CONTRACT_VERSION,
                    claim_id=claim_id,
                    case_id=case_id,
                    claim_type=row_policy.claim_type,
                    claim=_claim_text(source_row),
                    evidence_class=row_policy.evidence_class,
                    review_status=row_policy.review_status,
                    reviewer=BATCH_A_REVIEWER,
                    provenance=ReviewProvenance(
                        review_path=case.review_path,
                        review_sha256=case_policy.review_sha256,
                        review_row_id=(
                            f"{case_id}:expert-row-{ordinal:02d}"
                        ),
                    ),
                    locators=tuple(locators),
                    inclusion_mask=row_policy.inclusion_mask,
                    derivation=row_policy.derivation,
                )
            )

    ordered = tuple(sorted(records, key=lambda claim: claim.claim_id))
    counts = dict(sorted(Counter(
        claim.case_id for claim in ordered
    ).items()))
    if counts != BATCH_A_CASE_CLAIM_COUNTS or len(ordered) != BATCH_A_CLAIM_COUNT:
        raise ReviewRegistryError(
            "Batch A claim counts do not match the approved 71-row scope"
        )

    batch = ReviewBatch(
        schema_version=CONTRACT_VERSION,
        batch_id=BATCH_A_ID,
        corpus_registry_sha256=corpus_registry_sha256(registry),
        claim_count=BATCH_A_CLAIM_COUNT,
        case_claim_counts=BATCH_A_CASE_CLAIM_COUNTS,
        claims=ordered,
    )
    return validate_review_batch_against_registry(batch, registry)


def load_reviewed_claim_batch_a(
    path: str | Path,
    workspace_root: str | Path,
    registry: PortableCorpusRegistry,
) -> ReviewBatch:
    """Reload Batch A and fail on registry, report, policy, or byte drift."""

    loaded = validate_review_batch_against_registry(
        load_review_batch(path),
        registry,
    )
    expected = build_reviewed_claim_batch_a(workspace_root, registry)
    if canonical_review_batch_json(loaded) != canonical_review_batch_json(expected):
        raise ReviewRegistryError(
            "persisted Batch A does not match frozen review rows and policies"
        )
    return loaded


def build_reviewed_claim_batch_b(
    workspace_root: str | Path,
    registry: PortableCorpusRegistry,
) -> ReviewBatch:
    """Build all 76 Batch B records from frozen review rows and policies."""

    records: list[ReviewedClaimRecord] = []
    for case_id, case_policy in _BATCH_B_CASE_POLICIES.items():
        case = registry.case_by_id(case_id)
        review_path = resolve_portable_path(workspace_root, case.review_path)
        current_review_sha256 = sha256_file(review_path)
        if current_review_sha256 != case_policy.review_sha256:
            raise ReviewRegistryError(
                f"{case_id} review SHA-256 changed: expected "
                f"{case_policy.review_sha256}, got {current_review_sha256}"
            )

        source_rows = _flexible_expert_validation_rows(review_path)
        if len(source_rows) != len(case_policy.rows):
            raise ReviewRegistryError(
                f"{case_id} expected {len(case_policy.rows)} review rows, "
                f"got {len(source_rows)}"
            )

        pages = {page.physical_page: page for page in case.pages}
        for ordinal, (source_row, row_policy) in enumerate(
            zip(source_rows, case_policy.rows, strict=True),
            start=1,
        ):
            source_status = _normalize_status(source_row.raw_status)
            if source_status is not row_policy.review_status:
                raise ReviewRegistryError(
                    f"{case_id} expert row {ordinal} status changed: expected "
                    f"{row_policy.review_status.value}, got {source_status.value}"
                )

            locators = []
            for physical_page in row_policy.pages:
                try:
                    page = pages[physical_page]
                except KeyError as exc:
                    raise ReviewRegistryError(
                        f"{case_id} expert row {ordinal} uses unregistered "
                        f"physical page {physical_page}"
                    ) from exc
                locators.append(
                    SourceLocator(
                        case_id=case_id,
                        physical_page=physical_page,
                        printed_page=page.printed_page,
                        region_id=(
                            f"expert-row:{ordinal:02d}:source:p{physical_page:02d}"
                        ),
                        region_scope=_region_scope(row_policy.claim_type),
                        bbox=None,
                        coordinates=DISPLAY_PAGE_COORDINATES,
                    )
                )

            claim_id = f"p00-us07:{case_id}:expert-row-{ordinal:02d}"
            records.append(
                ReviewedClaimRecord(
                    schema_version=CONTRACT_VERSION,
                    claim_id=claim_id,
                    case_id=case_id,
                    claim_type=row_policy.claim_type,
                    claim=_flexible_claim_text(source_row),
                    evidence_class=row_policy.evidence_class,
                    review_status=row_policy.review_status,
                    reviewer=BATCH_B_REVIEWER,
                    provenance=ReviewProvenance(
                        review_path=case.review_path,
                        review_sha256=case_policy.review_sha256,
                        review_row_id=(
                            f"{case_id}:expert-row-{ordinal:02d}"
                        ),
                    ),
                    locators=tuple(locators),
                    inclusion_mask=row_policy.inclusion_mask,
                    derivation=row_policy.derivation,
                )
            )

    ordered = tuple(sorted(records, key=lambda claim: claim.claim_id))
    counts = dict(sorted(Counter(
        claim.case_id for claim in ordered
    ).items()))
    if counts != BATCH_B_CASE_CLAIM_COUNTS or len(ordered) != BATCH_B_CLAIM_COUNT:
        raise ReviewRegistryError(
            "Batch B claim counts do not match the approved 76-row scope"
        )

    batch = ReviewBatch(
        schema_version=CONTRACT_VERSION,
        batch_id=BATCH_B_ID,
        corpus_registry_sha256=corpus_registry_sha256(registry),
        claim_count=BATCH_B_CLAIM_COUNT,
        case_claim_counts=BATCH_B_CASE_CLAIM_COUNTS,
        claims=ordered,
    )
    return validate_review_batch_against_registry(batch, registry)


def load_reviewed_claim_batch_b(
    path: str | Path,
    workspace_root: str | Path,
    registry: PortableCorpusRegistry,
) -> ReviewBatch:
    """Reload Batch B and fail on registry, report, policy, or byte drift."""

    loaded = validate_review_batch_against_registry(
        load_review_batch(path),
        registry,
    )
    expected = build_reviewed_claim_batch_b(workspace_root, registry)
    if canonical_review_batch_json(loaded) != canonical_review_batch_json(expected):
        raise ReviewRegistryError(
            "persisted Batch B does not match frozen review rows and policies"
        )
    return loaded


def build_reviewed_claim_batch_c(
    workspace_root: str | Path,
    registry: PortableCorpusRegistry,
) -> ReviewBatch:
    """Build all 63 Batch C records from frozen review rows and policies."""

    records: list[ReviewedClaimRecord] = []
    for case_id, case_policy in _BATCH_C_CASE_POLICIES.items():
        case = registry.case_by_id(case_id)
        review_path = resolve_portable_path(workspace_root, case.review_path)
        current_review_sha256 = sha256_file(review_path)
        if current_review_sha256 != case_policy.review_sha256:
            raise ReviewRegistryError(
                f"{case_id} review SHA-256 changed: expected "
                f"{case_policy.review_sha256}, got {current_review_sha256}"
            )

        source_rows = _flexible_expert_validation_rows(review_path)
        if len(source_rows) != len(case_policy.rows):
            raise ReviewRegistryError(
                f"{case_id} expected {len(case_policy.rows)} review rows, "
                f"got {len(source_rows)}"
            )

        pages = {page.physical_page: page for page in case.pages}
        for ordinal, (source_row, row_policy) in enumerate(
            zip(source_rows, case_policy.rows, strict=True),
            start=1,
        ):
            source_status = _normalize_status(source_row.raw_status)
            if source_status is not row_policy.review_status:
                raise ReviewRegistryError(
                    f"{case_id} expert row {ordinal} status changed: expected "
                    f"{row_policy.review_status.value}, got {source_status.value}"
                )

            locators = []
            for physical_page in row_policy.pages:
                try:
                    page = pages[physical_page]
                except KeyError as exc:
                    raise ReviewRegistryError(
                        f"{case_id} expert row {ordinal} uses unregistered "
                        f"physical page {physical_page}"
                    ) from exc
                locators.append(
                    SourceLocator(
                        case_id=case_id,
                        physical_page=physical_page,
                        printed_page=page.printed_page,
                        region_id=(
                            f"expert-row:{ordinal:02d}:source:p{physical_page:02d}"
                        ),
                        region_scope=_region_scope(row_policy.claim_type),
                        bbox=None,
                        coordinates=DISPLAY_PAGE_COORDINATES,
                    )
                )

            claim_id = f"p00-us08:{case_id}:expert-row-{ordinal:02d}"
            records.append(
                ReviewedClaimRecord(
                    schema_version=CONTRACT_VERSION,
                    claim_id=claim_id,
                    case_id=case_id,
                    claim_type=row_policy.claim_type,
                    claim=_flexible_claim_text(source_row),
                    evidence_class=row_policy.evidence_class,
                    review_status=row_policy.review_status,
                    reviewer=BATCH_C_REVIEWER,
                    provenance=ReviewProvenance(
                        review_path=case.review_path,
                        review_sha256=case_policy.review_sha256,
                        review_row_id=(
                            f"{case_id}:expert-row-{ordinal:02d}"
                        ),
                    ),
                    locators=tuple(locators),
                    inclusion_mask=row_policy.inclusion_mask,
                    derivation=row_policy.derivation,
                )
            )

    ordered = tuple(sorted(records, key=lambda claim: claim.claim_id))
    counts = dict(sorted(Counter(
        claim.case_id for claim in ordered
    ).items()))
    if counts != BATCH_C_CASE_CLAIM_COUNTS or len(ordered) != BATCH_C_CLAIM_COUNT:
        raise ReviewRegistryError(
            "Batch C claim counts do not match the approved 63-row scope"
        )

    batch = ReviewBatch(
        schema_version=CONTRACT_VERSION,
        batch_id=BATCH_C_ID,
        corpus_registry_sha256=corpus_registry_sha256(registry),
        claim_count=BATCH_C_CLAIM_COUNT,
        case_claim_counts=BATCH_C_CASE_CLAIM_COUNTS,
        claims=ordered,
    )
    return validate_review_batch_against_registry(batch, registry)


def load_reviewed_claim_batch_c(
    path: str | Path,
    workspace_root: str | Path,
    registry: PortableCorpusRegistry,
) -> ReviewBatch:
    """Reload Batch C and fail on registry, report, policy, or byte drift."""

    loaded = validate_review_batch_against_registry(
        load_review_batch(path),
        registry,
    )
    expected = build_reviewed_claim_batch_c(workspace_root, registry)
    if canonical_review_batch_json(loaded) != canonical_review_batch_json(expected):
        raise ReviewRegistryError(
            "persisted Batch C does not match frozen review rows and policies"
        )
    return loaded
