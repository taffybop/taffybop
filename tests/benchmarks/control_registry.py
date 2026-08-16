"""Deterministic Phase 0 benchmark-control registry.

This module is test/reporting infrastructure only. It binds the frozen
gap-to-story matrix and all case-level mapped-gap rows to the completed
reviewed-claim corpus without changing parser behavior.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from tests.benchmarks.contracts import (
    CONTRACT_VERSION,
    ContractModel,
    NonEmptyString,
    SchemaVersion,
    Sha256,
)
from tests.benchmarks.corpus_registry import (
    PortableCorpusRegistry,
    resolve_portable_path,
    sha256_file,
)
from tests.benchmarks.reviewed_claim_inventory import (
    BATCH_A_EVIDENCE_PATH,
    BATCH_A_ID,
    BATCH_B_EVIDENCE_PATH,
    BATCH_B_ID,
    BATCH_C_EVIDENCE_PATH,
    BATCH_C_ID,
)
from tests.benchmarks.reviewed_claims import (
    ClaimReviewStatus,
    ClaimType,
    ReviewBatch,
    ReviewedClaimRecord,
    corpus_registry_sha256,
    review_batch_sha256,
    validate_review_batch_against_registry,
)


CONTROL_REGISTRY_ID = "p00-us09-benchmark-control-registry"
CONTROL_REGISTRY_EVIDENCE_PATH = (
    "tracker/phase-00-baseline/evidence/P00-US09-control-registry.json"
)
GAP_TO_STORY_MATRIX_PATH = (
    "tracker/benchmarks/llamaparse-15/gap-to-story-matrix.md"
)
GAP_TO_STORY_MATRIX_SHA256 = (
    "b89373d7a790de3edac5a38ade1af36ae45085b7f056c2515f1b463b5592542c"
)

EXPECTED_GAP_OWNER_COUNT = 25
EXPECTED_ROLE_ASSIGNMENT_COUNT = 100
EXPECTED_CASE_GAP_ROW_COUNT = 109
EXPECTED_REVIEWED_CLAIM_COUNT = 210

EXPECTED_CASE_GAP_COUNTS = {
    "catastrophe-recap": 5,
    "clean-energy": 5,
    "clinical-study": 7,
    "component-datasheet": 6,
    "egov-survey": 5,
    "esg-metrics": 9,
    "finance-10k": 7,
    "health-report": 9,
    "insurance-acord": 9,
    "manufacturing-report": 12,
    "ny-timetable": 6,
    "postal-10k": 9,
    "purchase-agreement": 5,
    "settlement-agreement": 6,
    "uber-earnings": 9,
}

EXPECTED_CASE_REPORT_SHA256 = {
    "catastrophe-recap": (
        "99b2110820d01d6a63e3677c0b49a3b17d3b5958ec186df0df552009ba976770"
    ),
    "clean-energy": (
        "1345fc03e3f55f415dd7682c827e24b6022d25b46ef0ee68e8437bc145f0ca5a"
    ),
    "clinical-study": (
        "fa5c1e863b7cee50ca4eea4b6c2debd042c7d9bbe143663cad64a26a07f5806f"
    ),
    "component-datasheet": (
        "6e41940bd8ffd61dbf7fce8ec4882f8935f6a94c481c844d7dc828812c4b53fe"
    ),
    "egov-survey": (
        "bbdb74c3c05204006c67d5868ad9f7229221c469d6e31a04906a67ac4980bc25"
    ),
    "esg-metrics": (
        "174180aa1cb2b42dd2a7deb8692b2c12e69d3edbb3c3d91b3c9934edb07da563"
    ),
    "finance-10k": (
        "3a2a661df038536eb95d72febe43189248df37b243194bfede441e1d38c61aff"
    ),
    "health-report": (
        "13e74b08061571472993123e5bcfa1ac00ca96a5191a4887bcb94589ccc876f5"
    ),
    "insurance-acord": (
        "327e9ed62a2703075e00434d5b02bead11525692d43178198a9377ca0adeaddb"
    ),
    "manufacturing-report": (
        "4c38cafd256c090fc9d4041a4465d12f34c0855f8568d25c66fe7eb896a11dd1"
    ),
    "ny-timetable": (
        "68e1ce268850da1fa09180c0bd0262976ba983dcc5de039c21b1bbde91c7822b"
    ),
    "postal-10k": (
        "e0eb3d81b012018a1b1a2d4d37a17f5c9f62c0014e52bd652845d6ac7fc9cce7"
    ),
    "purchase-agreement": (
        "715e14ee37fd5263939d01dd9090b30d2a3c1f6ea6fc703bbb7ca80e529213a4"
    ),
    "settlement-agreement": (
        "1e1680bd2b28eca6c68c364a32e1381d64ae7d5c8155325ac03c10e4d8addba9"
    ),
    "uber-earnings": (
        "344aa02fc3e0315b912e42489331951c39f6bdbb9b7e0e4fdfc17ebb44018567"
    ),
}

_STABLE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[a-z0-9._:-]*[a-z0-9])?$")
_GAP_ID_PATTERN = re.compile(r"^GAP-[A-Z]+-\d{3}$")
_STORY_ID_PATTERN = re.compile(r"^P\d{2}-US\d{2}$")
StableId = Annotated[str, Field(pattern=_STABLE_ID_PATTERN.pattern)]
GapId = Annotated[str, Field(pattern=_GAP_ID_PATTERN.pattern)]
StoryId = Annotated[str, Field(pattern=_STORY_ID_PATTERN.pattern)]


class ControlRole(str, Enum):
    """The four required roles in every reusable story-control set."""

    TARGET = "target"
    RELATED_POSITIVE = "related_positive"
    NON_TARGET_REGRESSION = "non_target_regression"
    NEGATIVE_OR_AMBIGUOUS = "negative_or_ambiguous"


class ExpectedBehavior(str, Enum):
    """How a future capability test must treat its referenced claim."""

    ASSERT_SUPPORTED_CAPABILITY = "assert_supported_capability"
    ASSERT_RELATED_SUPPORTED_BEHAVIOR = "assert_related_supported_behavior"
    PRESERVE_NON_TARGET_BEHAVIOR = "preserve_non_target_behavior"
    REJECT_OR_FLAG_UNSUPPORTED = "reject_or_flag_unsupported"


CONTROL_ROLE_ORDER = (
    ControlRole.TARGET,
    ControlRole.RELATED_POSITIVE,
    ControlRole.NON_TARGET_REGRESSION,
    ControlRole.NEGATIVE_OR_AMBIGUOUS,
)
EXPECTED_BEHAVIOR_BY_ROLE = {
    ControlRole.TARGET: ExpectedBehavior.ASSERT_SUPPORTED_CAPABILITY,
    ControlRole.RELATED_POSITIVE: (
        ExpectedBehavior.ASSERT_RELATED_SUPPORTED_BEHAVIOR
    ),
    ControlRole.NON_TARGET_REGRESSION: (
        ExpectedBehavior.PRESERVE_NON_TARGET_BEHAVIOR
    ),
    ControlRole.NEGATIVE_OR_AMBIGUOUS: (
        ExpectedBehavior.REJECT_OR_FLAG_UNSUPPORTED
    ),
}
_SUPPORTED_CONTROL_STATUSES = {
    ClaimReviewStatus.VERIFIED,
    ClaimReviewStatus.PARTIALLY_VERIFIED,
}
_UNSUPPORTED_CONTROL_STATUSES = {
    ClaimReviewStatus.INCORRECT,
    ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE,
    ClaimReviewStatus.POTENTIALLY_INFERRED,
}


def _portable_path(value: str) -> str:
    if value != value.strip() or "\\" in value or "\x00" in value:
        raise ValueError("source paths must be trimmed portable POSIX paths")
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or value.split("/", 1)[0].startswith("~")
        or ":" in value.split("/", 1)[0]
    ):
        raise ValueError("source paths must be canonical workspace-relative paths")
    return value


class SourceBinding(ContractModel):
    """One frozen Markdown source used to construct the control registry."""

    path: NonEmptyString
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def require_portable_path(cls, value: str) -> str:
        return _portable_path(value)


class ReviewBatchBinding(ContractModel):
    """One immutable reviewed-claim batch consumed by the registry."""

    batch_id: StableId
    evidence_path: NonEmptyString
    evidence_file_sha256: Sha256
    semantic_sha256: Sha256
    claim_count: int = Field(gt=0)

    @field_validator("evidence_path")
    @classmethod
    def require_portable_path(cls, value: str) -> str:
        return _portable_path(value)


class CaseReportBinding(ContractModel):
    """One frozen case report and its exact mapped-gap row count."""

    case_id: StableId
    report_path: NonEmptyString
    report_sha256: Sha256
    mapped_gap_row_count: int = Field(gt=0)

    @field_validator("report_path")
    @classmethod
    def require_portable_path(cls, value: str) -> str:
        return _portable_path(value)


class ClaimLocatorRef(ContractModel):
    """An exact locator already owned by one reviewed claim."""

    case_id: StableId
    claim_id: StableId
    region_id: StableId


class ControlAssignment(ContractModel):
    """One role assignment in a gap-owner control quartet."""

    assignment_id: StableId
    role: ControlRole
    expected_behavior: ExpectedBehavior
    evidence: ClaimLocatorRef
    rationale: NonEmptyString

    @field_validator("rationale")
    @classmethod
    def require_trimmed_rationale(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("control rationale must be trimmed")
        return value

    @model_validator(mode="after")
    def require_role_behavior_pair(self) -> "ControlAssignment":
        if self.expected_behavior is not EXPECTED_BEHAVIOR_BY_ROLE[self.role]:
            raise ValueError("expected_behavior must match the control role")
        return self


class GapControlSet(ContractModel):
    """One primary matrix owner and its complete four-role control set."""

    matrix_row_index: int = Field(ge=1)
    matrix_row_sha256: Sha256
    gap_id: GapId
    primary_story_id: StoryId
    secondary_stories: NonEmptyString
    story_action: NonEmptyString
    dedicated_test_anchor: NonEmptyString
    milestone: NonEmptyString
    assignments: tuple[ControlAssignment, ...] = Field(
        min_length=4,
        max_length=4,
    )

    @model_validator(mode="after")
    def require_complete_canonical_quartet(self) -> "GapControlSet":
        roles = tuple(assignment.role for assignment in self.assignments)
        if roles != CONTROL_ROLE_ORDER:
            raise ValueError("control assignments must contain all roles in order")
        assignment_ids = [
            assignment.assignment_id for assignment in self.assignments
        ]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("control assignment IDs must be unique")
        claim_ids = [
            assignment.evidence.claim_id for assignment in self.assignments
        ]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("a gap control quartet must use four distinct claims")
        return self


class CaseGapRow(ContractModel):
    """One losslessly identified row from a case's mapped-gap table."""

    row_id: StableId
    case_id: StableId
    report_row_index: int = Field(ge=1)
    gap_id: GapId
    raw_row_sha256: Sha256
    origin: NonEmptyString | None = None
    mapped_capability: NonEmptyString
    exact_evidence: NonEmptyString | None = None
    exact_source_region: NonEmptyString | None = None
    why_reusable: NonEmptyString | None = None
    claim_locator: ClaimLocatorRef

    @model_validator(mode="after")
    def require_recognized_source_shape(self) -> "CaseGapRow":
        evidence_shape = (
            self.exact_evidence is not None
            and self.exact_source_region is None
            and self.why_reusable is None
        )
        source_region_shape = (
            self.origin is None
            and self.exact_evidence is None
            and self.exact_source_region is not None
            and self.why_reusable is not None
        )
        if not (evidence_shape or source_region_shape):
            raise ValueError("case-gap row must retain one recognized table schema")
        if self.claim_locator.case_id != self.case_id:
            raise ValueError("case-gap claim locator must use the row case_id")
        return self


class BenchmarkControlRegistry(ContractModel):
    """The complete, finite P00-US09 benchmark-control registry."""

    schema_version: SchemaVersion
    registry_id: Literal["p00-us09-benchmark-control-registry"]
    corpus_registry_sha256: Sha256
    reviewed_claim_count: Literal[210]
    gap_owner_count: Literal[25]
    role_assignment_count: Literal[100]
    case_gap_row_count: Literal[109]
    matrix_source: SourceBinding
    review_batches: tuple[ReviewBatchBinding, ...] = Field(
        min_length=3,
        max_length=3,
    )
    case_reports: tuple[CaseReportBinding, ...] = Field(
        min_length=15,
        max_length=15,
    )
    gap_controls: tuple[GapControlSet, ...] = Field(
        min_length=25,
        max_length=25,
    )
    case_gap_rows: tuple[CaseGapRow, ...] = Field(
        min_length=109,
        max_length=109,
    )

    @model_validator(mode="after")
    def require_complete_canonical_registry(self) -> "BenchmarkControlRegistry":
        if len(self.gap_controls) != self.gap_owner_count:
            raise ValueError("gap_owner_count must match gap_controls")
        if sum(
            len(control.assignments) for control in self.gap_controls
        ) != self.role_assignment_count:
            raise ValueError("role_assignment_count must match all assignments")
        if len(self.case_gap_rows) != self.case_gap_row_count:
            raise ValueError("case_gap_row_count must match case_gap_rows")

        matrix_indexes = [
            control.matrix_row_index for control in self.gap_controls
        ]
        if matrix_indexes != list(range(1, self.gap_owner_count + 1)):
            raise ValueError("gap controls must preserve contiguous matrix order")
        gap_ids = [control.gap_id for control in self.gap_controls]
        if len(gap_ids) != len(set(gap_ids)):
            raise ValueError("gap owners must be unique")

        batch_ids = [binding.batch_id for binding in self.review_batches]
        if len(batch_ids) != len(set(batch_ids)):
            raise ValueError("review batch bindings must be unique")
        if sum(
            binding.claim_count for binding in self.review_batches
        ) != self.reviewed_claim_count:
            raise ValueError("review batch claims must total reviewed_claim_count")

        report_cases = [binding.case_id for binding in self.case_reports]
        if report_cases != sorted(report_cases):
            raise ValueError("case report bindings must use canonical case order")
        if len(report_cases) != len(set(report_cases)):
            raise ValueError("case report bindings must be unique")

        row_ids = [row.row_id for row in self.case_gap_rows]
        if row_ids != sorted(row_ids):
            raise ValueError("case-gap rows must use canonical row_id order")
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("case-gap row IDs must be unique")
        owner_ids = set(gap_ids)
        if any(row.gap_id not in owner_ids for row in self.case_gap_rows):
            raise ValueError("every case-gap row must resolve to a gap owner")
        actual_counts = Counter(row.case_id for row in self.case_gap_rows)
        declared_counts = {
            binding.case_id: binding.mapped_gap_row_count
            for binding in self.case_reports
        }
        if dict(sorted(actual_counts.items())) != declared_counts:
            raise ValueError("case report counts must match case-gap rows")
        return self


class ControlRegistryError(ValueError):
    """The control registry does not match its frozen source or claim corpus."""


@dataclass(frozen=True)
class _ParsedTableRow:
    raw_line: str
    headers: tuple[str, ...]
    cells: tuple[str, ...]


_MATRIX_HEADER = (
    "Gap",
    "Primary story",
    "Secondary stories",
    "Story action",
    "Dedicated test anchor",
    "Milestone",
)
_CASE_HEADERS = {
    (
        "Gap",
        "Mapped capability",
        "Exact evidence",
    ),
    (
        "Gap",
        "Origin",
        "Mapped capability",
        "Exact evidence",
    ),
    (
        "Gap",
        "Mapped capability",
        "Exact source region",
        "Why reusable",
    ),
}


def _split_markdown_row(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        raise ValueError("Markdown table rows must use outer pipes")
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
    if in_code:
        raise ValueError("unterminated inline-code span in Markdown table")
    cells.append("".join(current).strip())
    return tuple(cells)


def _is_separator(cells: tuple[str, ...]) -> bool:
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in cells
    )


def _table_below_header(
    lines: list[str],
    expected_headers: set[tuple[str, ...]],
) -> tuple[_ParsedTableRow, ...]:
    matches = [
        index
        for index, line in enumerate(lines)
        if line.lstrip().startswith("|")
        and _split_markdown_row(line) in expected_headers
    ]
    if len(matches) != 1:
        raise ControlRegistryError(
            "expected exactly one recognized Markdown table header"
        )
    header_index = matches[0]
    headers = _split_markdown_row(lines[header_index])
    separator_index = header_index + 1
    if (
        separator_index >= len(lines)
        or not lines[separator_index].lstrip().startswith("|")
        or not _is_separator(_split_markdown_row(lines[separator_index]))
    ):
        raise ControlRegistryError("recognized table header lacks a separator")

    rows: list[_ParsedTableRow] = []
    for line in lines[separator_index + 1:]:
        if not line.lstrip().startswith("|"):
            break
        cells = _split_markdown_row(line)
        if len(cells) != len(headers):
            raise ControlRegistryError("Markdown data row width changed")
        rows.append(_ParsedTableRow(line, headers, cells))
    return tuple(rows)


def _parse_matrix(path: Path) -> tuple[_ParsedTableRow, ...]:
    rows = _table_below_header(
        path.read_text(encoding="utf-8").splitlines(),
        {_MATRIX_HEADER},
    )
    if len(rows) != EXPECTED_GAP_OWNER_COUNT:
        raise ControlRegistryError("primary matrix must contain exactly 25 rows")
    return rows


def _parse_case_report(path: Path) -> tuple[_ParsedTableRow, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    headings = [
        index for index, line in enumerate(lines) if line == "## Mapped gaps"
    ]
    if len(headings) != 1:
        raise ControlRegistryError(
            "case report must contain exactly one mapped-gaps section"
        )
    start = headings[0] + 1
    end = next(
        (
            index
            for index in range(start, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    return _table_below_header(lines[start:end], _CASE_HEADERS)


def _unquote_gap_id(value: str) -> str:
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    if not _GAP_ID_PATTERN.fullmatch(value):
        raise ControlRegistryError(f"unsupported gap ID: {value}")
    return value


def _row_sha256(raw_line: str) -> str:
    return hashlib.sha256(raw_line.encode("utf-8")).hexdigest()


_CONTROL_CLAIM_POLICIES: dict[str, tuple[str, str, str, str]] = {
    "GAP-BENCHMARK-001": (
        "p00-us06:catastrophe-recap:expert-row-03",
        "p00-us08:egov-survey:expert-row-05",
        "p00-us06:purchase-agreement:expert-row-02",
        "p00-us08:health-report:expert-row-03",
    ),
    "GAP-BENCHMARK-002": (
        "p00-us07:ny-timetable:expert-row-03",
        "p00-us08:uber-earnings:expert-row-05",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us08:health-report:expert-row-03",
    ),
    "GAP-COVERAGE-001": (
        "p00-us07:component-datasheet:expert-row-07",
        "p00-us08:uber-earnings:expert-row-12",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us07:component-datasheet:expert-row-06",
    ),
    "GAP-UNICODE-001": (
        "p00-us06:catastrophe-recap:expert-row-03",
        "p00-us07:clinical-study:expert-row-04",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us08:postal-10k:expert-row-08",
    ),
    "GAP-TEXT-001": (
        "p00-us08:settlement-agreement:expert-row-02",
        "p00-us06:esg-metrics:expert-row-05",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us08:postal-10k:expert-row-08",
    ),
    "GAP-OCR-001": (
        "p00-us08:egov-survey:expert-row-05",
        "p00-us07:ny-timetable:expert-row-03",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us07:clinical-study:expert-row-06",
    ),
    "GAP-LAYOUT-001": (
        "p00-us08:health-report:expert-row-02",
        "p00-us06:manufacturing-report:expert-row-14",
        "p00-us06:purchase-agreement:expert-row-02",
        "p00-us07:clinical-study:expert-row-19",
    ),
    "GAP-ORDER-001": (
        "p00-us07:ny-timetable:expert-row-02",
        "p00-us07:clean-energy:expert-row-11",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us07:ny-timetable:expert-row-06",
    ),
    "GAP-PAGE-001": (
        "p00-us07:clinical-study:expert-row-02",
        "p00-us08:egov-survey:expert-row-09",
        "p00-us06:purchase-agreement:expert-row-02",
        "p00-us07:clinical-study:expert-row-20",
    ),
    "GAP-REDLINE-001": (
        "p00-us06:purchase-agreement:expert-row-01",
        "p00-us08:postal-10k:expert-row-03",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us06:purchase-agreement:expert-row-05",
    ),
    "GAP-FORM-001": (
        "p00-us07:insurance-acord:expert-row-08",
        "p00-us07:component-datasheet:expert-row-13",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us07:insurance-acord:expert-row-10",
    ),
    "GAP-LIST-001": (
        "p00-us08:settlement-agreement:expert-row-03",
        "p00-us07:component-datasheet:expert-row-04",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us07:component-datasheet:expert-row-14",
    ),
    "GAP-LINK-001": (
        "p00-us08:health-report:expert-row-05",
        "p00-us07:clinical-study:expert-row-17",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us07:component-datasheet:expert-row-06",
    ),
    "GAP-BBOX-001": (
        "p00-us07:clean-energy:expert-row-12",
        "p00-us06:finance-10k:expert-row-10",
        "p00-us08:postal-10k:expert-row-01",
        "p00-us07:clinical-study:expert-row-19",
    ),
    "GAP-TABLE-001": (
        "p00-us07:insurance-acord:expert-row-04",
        "p00-us07:component-datasheet:expert-row-13",
        "p00-us06:purchase-agreement:expert-row-02",
        "p00-us08:health-report:expert-row-03",
    ),
    "GAP-TABLE-002": (
        "p00-us07:clinical-study:expert-row-09",
        "p00-us08:postal-10k:expert-row-05",
        "p00-us06:purchase-agreement:expert-row-02",
        "p00-us07:clinical-study:expert-row-14",
    ),
    "GAP-TABLE-003": (
        "p00-us08:postal-10k:expert-row-05",
        "p00-us06:finance-10k:expert-row-02",
        "p00-us06:purchase-agreement:expert-row-02",
        "p00-us07:component-datasheet:expert-row-14",
    ),
    "GAP-CHART-001": (
        "p00-us08:egov-survey:expert-row-05",
        "p00-us08:uber-earnings:expert-row-05",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us08:health-report:expert-row-03",
    ),
    "GAP-CHART-002": (
        "p00-us08:uber-earnings:expert-row-05",
        "p00-us06:catastrophe-recap:expert-row-08",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us08:uber-earnings:expert-row-06",
    ),
    "GAP-DIAGRAM-001": (
        "p00-us07:clinical-study:expert-row-11",
        "p00-us08:uber-earnings:expert-row-13",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us08:uber-earnings:expert-row-14",
    ),
    "GAP-VISUAL-001": (
        "p00-us08:uber-earnings:expert-row-12",
        "p00-us06:catastrophe-recap:expert-row-02",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us08:uber-earnings:expert-row-11",
    ),
    "GAP-SERIALIZATION-001": (
        "p00-us08:postal-10k:expert-row-05",
        "p00-us08:egov-survey:expert-row-09",
        "p00-us06:purchase-agreement:expert-row-02",
        "p00-us07:component-datasheet:expert-row-14",
    ),
    "GAP-PROVENANCE-001": (
        "p00-us08:egov-survey:expert-row-06",
        "p00-us08:postal-10k:expert-row-03",
        "p00-us08:uber-earnings:expert-row-01",
        "p00-us08:health-report:expert-row-03",
    ),
    "GAP-DIAGNOSTICS-001": (
        "p00-us08:postal-10k:expert-row-09",
        "p00-us08:settlement-agreement:expert-row-04",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us08:postal-10k:expert-row-10",
    ),
    "GAP-PERFORMANCE-001": (
        "p00-us07:ny-timetable:expert-row-03",
        "p00-us08:uber-earnings:expert-row-13",
        "p00-us06:finance-10k:expert-row-01",
        "p00-us06:manufacturing-report:expert-row-10",
    ),
}

_GAP_CLAIM_TYPE_PREFERENCES = {
    "GAP-UNICODE-001": (ClaimType.TEXT, ClaimType.TEXT_STYLE),
    "GAP-TEXT-001": (ClaimType.TEXT, ClaimType.TEXT_STYLE, ClaimType.TABLE),
    "GAP-OCR-001": (
        ClaimType.CHART,
        ClaimType.IMAGE,
        ClaimType.TABLE,
        ClaimType.TEXT,
    ),
    "GAP-LAYOUT-001": (
        ClaimType.TEXT,
        ClaimType.STRUCTURE,
        ClaimType.TABLE,
        ClaimType.GEOMETRY,
    ),
    "GAP-ORDER-001": (
        ClaimType.STRUCTURE,
        ClaimType.TEXT,
        ClaimType.PAGE_IDENTITY,
        ClaimType.TABLE,
    ),
    "GAP-PAGE-001": (
        ClaimType.PAGE_IDENTITY,
        ClaimType.TEXT,
        ClaimType.METADATA,
    ),
    "GAP-REDLINE-001": (
        ClaimType.TEXT_STYLE,
        ClaimType.TEXT,
        ClaimType.GEOMETRY,
    ),
    "GAP-FORM-001": (
        ClaimType.FORM,
        ClaimType.STRUCTURE,
        ClaimType.TABLE,
        ClaimType.TEXT,
    ),
    "GAP-LIST-001": (ClaimType.STRUCTURE, ClaimType.TEXT),
    "GAP-LINK-001": (ClaimType.LINK, ClaimType.TEXT),
    "GAP-BBOX-001": (
        ClaimType.GEOMETRY,
        ClaimType.STRUCTURE,
        ClaimType.TABLE,
        ClaimType.FORM,
        ClaimType.CHART,
        ClaimType.DIAGRAM,
        ClaimType.IMAGE,
        ClaimType.METADATA,
    ),
    "GAP-TABLE-001": (
        ClaimType.TABLE,
        ClaimType.FORM,
        ClaimType.STRUCTURE,
        ClaimType.CHART,
    ),
    "GAP-TABLE-002": (
        ClaimType.TABLE,
        ClaimType.STRUCTURE,
        ClaimType.TEXT_STYLE,
    ),
    "GAP-TABLE-003": (
        ClaimType.TABLE,
        ClaimType.STRUCTURE,
        ClaimType.TEXT_STYLE,
        ClaimType.ARTIFACT_INVENTORY,
    ),
    "GAP-CHART-001": (
        ClaimType.CHART,
        ClaimType.TABLE,
        ClaimType.TEXT,
        ClaimType.RELATIONSHIP,
    ),
    "GAP-CHART-002": (
        ClaimType.CHART,
        ClaimType.TABLE,
        ClaimType.METADATA,
    ),
    "GAP-DIAGRAM-001": (
        ClaimType.RELATIONSHIP,
        ClaimType.DIAGRAM,
        ClaimType.IMAGE,
        ClaimType.STRUCTURE,
    ),
    "GAP-VISUAL-001": (
        ClaimType.IMAGE,
        ClaimType.DIAGRAM,
        ClaimType.FORM,
        ClaimType.ARTIFACT_INVENTORY,
        ClaimType.TEXT,
        ClaimType.CHART,
        ClaimType.TABLE,
    ),
    "GAP-SERIALIZATION-001": (
        ClaimType.STRUCTURE,
        ClaimType.PAGE_IDENTITY,
        ClaimType.TEXT_STYLE,
        ClaimType.ARTIFACT_INVENTORY,
        ClaimType.TEXT,
        ClaimType.TABLE,
        ClaimType.METADATA,
    ),
    "GAP-PROVENANCE-001": (
        ClaimType.METADATA,
        ClaimType.GEOMETRY,
        ClaimType.ARTIFACT_INVENTORY,
        ClaimType.LINK,
        ClaimType.CHART,
        ClaimType.TABLE,
        ClaimType.TEXT_STYLE,
    ),
    "GAP-DIAGNOSTICS-001": (
        ClaimType.METADATA,
        ClaimType.ARTIFACT_INVENTORY,
        ClaimType.STRUCTURE,
        ClaimType.TABLE,
    ),
}

# The generic scorer gives every frozen row a deterministic case-local claim
# locator. These audited exceptions bind rows whose decisive evidence is more
# specific than their shared gap vocabulary (for example, a blank signature
# region rather than a generic image claim). The third key component is the
# one-based occurrence of that gap within the case report.
_CASE_GAP_ANCHOR_OVERRIDES: dict[tuple[str, str, int], str] = {
    ("catastrophe-recap", "GAP-SERIALIZATION-001", 1): (
        "p00-us06:catastrophe-recap:expert-row-11"
    ),
    ("clean-energy", "GAP-CHART-002", 1): (
        "p00-us07:clean-energy:expert-row-07"
    ),
    ("clean-energy", "GAP-PAGE-001", 1): (
        "p00-us07:clean-energy:expert-row-14"
    ),
    ("clean-energy", "GAP-SERIALIZATION-001", 1): (
        "p00-us07:clean-energy:expert-row-10"
    ),
    ("clinical-study", "GAP-SERIALIZATION-001", 1): (
        "p00-us07:clinical-study:expert-row-21"
    ),
    ("component-datasheet", "GAP-VISUAL-001", 1): (
        "p00-us07:component-datasheet:expert-row-06"
    ),
    ("component-datasheet", "GAP-TABLE-003", 1): (
        "p00-us07:component-datasheet:expert-row-14"
    ),
    ("component-datasheet", "GAP-PROVENANCE-001", 1): (
        "p00-us07:component-datasheet:expert-row-09"
    ),
    ("component-datasheet", "GAP-BBOX-001", 1): (
        "p00-us07:component-datasheet:expert-row-10"
    ),
    ("esg-metrics", "GAP-OCR-001", 1): (
        "p00-us06:esg-metrics:expert-row-07"
    ),
    ("esg-metrics", "GAP-SERIALIZATION-001", 1): (
        "p00-us06:esg-metrics:expert-row-07"
    ),
    ("esg-metrics", "GAP-ORDER-001", 1): (
        "p00-us06:esg-metrics:expert-row-12"
    ),
    ("esg-metrics", "GAP-SERIALIZATION-001", 2): (
        "p00-us06:esg-metrics:expert-row-12"
    ),
    ("health-report", "GAP-OCR-001", 1): (
        "p00-us08:health-report:expert-row-01"
    ),
    ("health-report", "GAP-LAYOUT-001", 1): (
        "p00-us08:health-report:expert-row-02"
    ),
    ("insurance-acord", "GAP-TABLE-002", 1): (
        "p00-us07:insurance-acord:expert-row-07"
    ),
    ("insurance-acord", "GAP-BBOX-001", 1): (
        "p00-us07:insurance-acord:expert-row-07"
    ),
    ("insurance-acord", "GAP-VISUAL-001", 1): (
        "p00-us07:insurance-acord:expert-row-10"
    ),
    ("insurance-acord", "GAP-ORDER-001", 1): (
        "p00-us07:insurance-acord:expert-row-04"
    ),
    ("insurance-acord", "GAP-SERIALIZATION-001", 1): (
        "p00-us07:insurance-acord:expert-row-11"
    ),
    ("manufacturing-report", "GAP-CHART-001", 1): (
        "p00-us06:manufacturing-report:expert-row-10"
    ),
    ("manufacturing-report", "GAP-BBOX-001", 1): (
        "p00-us06:manufacturing-report:expert-row-10"
    ),
    ("manufacturing-report", "GAP-LAYOUT-001", 1): (
        "p00-us06:manufacturing-report:expert-row-14"
    ),
    ("manufacturing-report", "GAP-ORDER-001", 1): (
        "p00-us06:manufacturing-report:expert-row-11"
    ),
    ("manufacturing-report", "GAP-VISUAL-001", 1): (
        "p00-us06:manufacturing-report:expert-row-20"
    ),
    ("ny-timetable", "GAP-TABLE-002", 1): (
        "p00-us07:ny-timetable:expert-row-06"
    ),
    ("ny-timetable", "GAP-TABLE-003", 1): (
        "p00-us07:ny-timetable:expert-row-02"
    ),
    ("postal-10k", "GAP-TEXT-001", 2): (
        "p00-us08:postal-10k:expert-row-02"
    ),
    ("postal-10k", "GAP-OCR-001", 1): (
        "p00-us08:postal-10k:expert-row-02"
    ),
    # No reviewed page-identity claim exists for postal-10k. Its all-page
    # metadata claim is the narrowest explicit proxy for the missing printed
    # page-label field; the source row itself remains losslessly preserved.
    ("postal-10k", "GAP-PAGE-001", 1): (
        "p00-us08:postal-10k:expert-row-11"
    ),
    ("settlement-agreement", "GAP-TEXT-001", 1): (
        "p00-us08:settlement-agreement:expert-row-02"
    ),
    ("uber-earnings", "GAP-BBOX-001", 1): (
        "p00-us08:uber-earnings:expert-row-15"
    ),
    ("uber-earnings", "GAP-PAGE-001", 1): (
        "p00-us08:uber-earnings:expert-row-01"
    ),
}

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_TOKEN_STOPWORDS = {
    "and",
    "the",
    "for",
    "from",
    "with",
    "into",
    "one",
    "item",
    "items",
    "tests",
    "whether",
    "source",
    "expert",
    "output",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN_PATTERN.findall(value.lower())
        if len(token) > 2 and token not in _TOKEN_STOPWORDS
    }


def _claim_index(
    review_batches: tuple[ReviewBatch, ...],
) -> dict[str, ReviewedClaimRecord]:
    claims = [
        claim for batch in review_batches for claim in batch.claims
    ]
    if len(claims) != EXPECTED_REVIEWED_CLAIM_COUNT:
        raise ControlRegistryError("review batches must contain exactly 210 claims")
    index = {claim.claim_id: claim for claim in claims}
    if len(index) != len(claims):
        raise ControlRegistryError("review claim IDs must be globally unique")
    provenance = {
        (claim.provenance.review_path, claim.provenance.review_row_id)
        for claim in claims
    }
    if len(provenance) != len(claims):
        raise ControlRegistryError(
            "review path/row identities must be globally unique"
        )
    return index


def _locator_ref(claim: ReviewedClaimRecord) -> ClaimLocatorRef:
    locator = claim.locators[0]
    return ClaimLocatorRef(
        case_id=claim.case_id,
        claim_id=claim.claim_id,
        region_id=locator.region_id,
    )


def _case_gap_anchor(
    case_id: str,
    gap_id: str,
    occurrence: int,
    row: _ParsedTableRow,
    claims: tuple[ReviewedClaimRecord, ...],
    used_claim_ids: set[str],
) -> ReviewedClaimRecord:
    override_claim_id = _CASE_GAP_ANCHOR_OVERRIDES.get(
        (case_id, gap_id, occurrence)
    )
    if override_claim_id is not None:
        matching = [
            claim for claim in claims if claim.claim_id == override_claim_id
        ]
        if len(matching) != 1:
            raise ControlRegistryError(
                f"{case_id} {gap_id} occurrence {occurrence} uses an "
                f"unavailable anchor override {override_claim_id}"
            )
        return matching[0]

    preferences = _GAP_CLAIM_TYPE_PREFERENCES.get(gap_id, ())
    row_tokens = _tokens(" ".join(row.cells[1:]))

    def score(claim: ReviewedClaimRecord) -> tuple[int, int, str]:
        try:
            type_index = preferences.index(claim.claim_type)
        except ValueError:
            type_bonus = 0
        else:
            type_bonus = (len(preferences) - type_index) * 20
        overlap = len(row_tokens & _tokens(claim.claim))
        unused_bonus = 50 if claim.claim_id not in used_claim_ids else 0
        semantic_bonus = 1 if claim.inclusion_mask.semantic_parity else 0
        return (
            unused_bonus + overlap * 5 + type_bonus + semantic_bonus,
            -len(claim.claim),
            claim.claim_id,
        )

    return max(claims, key=score)


def _control_rationale(gap_id: str, role: ControlRole) -> str:
    if role is ControlRole.TARGET:
        return f"Primary source-reviewed capability anchor for {gap_id}."
    if role is ControlRole.RELATED_POSITIVE:
        return (
            f"Related supported evidence exercises adjacent {gap_id} behavior."
        )
    if role is ControlRole.NON_TARGET_REGRESSION:
        return (
            f"Supported evidence outside the {gap_id} target must remain stable."
        )
    return (
        f"Unsupported or ambiguous evidence for {gap_id} must be rejected or "
        "flagged without truth promotion."
    )


def _review_batch_bindings(
    workspace_root: str | Path,
    review_batches: tuple[ReviewBatch, ...],
) -> tuple[ReviewBatchBinding, ...]:
    paths = {
        BATCH_A_ID: BATCH_A_EVIDENCE_PATH,
        BATCH_B_ID: BATCH_B_EVIDENCE_PATH,
        BATCH_C_ID: BATCH_C_EVIDENCE_PATH,
    }
    by_id = {batch.batch_id: batch for batch in review_batches}
    if set(by_id) != set(paths):
        raise ControlRegistryError("expected reviewed-claim Batches A, B, and C")
    return tuple(
        ReviewBatchBinding(
            batch_id=batch_id,
            evidence_path=paths[batch_id],
            evidence_file_sha256=sha256_file(
                resolve_portable_path(workspace_root, paths[batch_id])
            ),
            semantic_sha256=review_batch_sha256(by_id[batch_id]),
            claim_count=by_id[batch_id].claim_count,
        )
        for batch_id in (BATCH_A_ID, BATCH_B_ID, BATCH_C_ID)
    )


def build_benchmark_control_registry(
    workspace_root: str | Path,
    corpus_registry: PortableCorpusRegistry,
    review_batches: tuple[ReviewBatch, ...],
) -> BenchmarkControlRegistry:
    """Build the exact 25/100/109 control registry from frozen sources."""

    for batch in review_batches:
        validate_review_batch_against_registry(batch, corpus_registry)
    claims_by_id = _claim_index(review_batches)

    matrix_path = resolve_portable_path(
        workspace_root,
        GAP_TO_STORY_MATRIX_PATH,
    )
    matrix_sha256 = sha256_file(matrix_path)
    if matrix_sha256 != GAP_TO_STORY_MATRIX_SHA256:
        raise ControlRegistryError(
            "gap-to-story matrix SHA-256 changed: expected "
            f"{GAP_TO_STORY_MATRIX_SHA256}, got {matrix_sha256}"
        )
    matrix_rows = _parse_matrix(matrix_path)
    matrix_gap_ids = tuple(_unquote_gap_id(row.cells[0]) for row in matrix_rows)
    if set(matrix_gap_ids) != set(_CONTROL_CLAIM_POLICIES):
        raise ControlRegistryError(
            "control claim policies must cover every primary matrix gap"
        )

    gap_controls: list[GapControlSet] = []
    for row_index, row in enumerate(matrix_rows, start=1):
        gap_id = _unquote_gap_id(row.cells[0])
        assignments = []
        for role, claim_id in zip(
            CONTROL_ROLE_ORDER,
            _CONTROL_CLAIM_POLICIES[gap_id],
            strict=True,
        ):
            try:
                claim = claims_by_id[claim_id]
            except KeyError as exc:
                raise ControlRegistryError(
                    f"{gap_id} control uses unknown claim {claim_id}"
                ) from exc
            assignments.append(
                ControlAssignment(
                    assignment_id=(
                        f"p00-us09:{gap_id.lower()}:{role.value}"
                    ),
                    role=role,
                    expected_behavior=EXPECTED_BEHAVIOR_BY_ROLE[role],
                    evidence=_locator_ref(claim),
                    rationale=_control_rationale(gap_id, role),
                )
            )
        gap_controls.append(
            GapControlSet(
                matrix_row_index=row_index,
                matrix_row_sha256=_row_sha256(row.raw_line),
                gap_id=gap_id,
                primary_story_id=row.cells[1],
                secondary_stories=row.cells[2],
                story_action=row.cells[3],
                dedicated_test_anchor=row.cells[4],
                milestone=row.cells[5],
                assignments=tuple(assignments),
            )
        )

    case_reports: list[CaseReportBinding] = []
    case_gap_rows: list[CaseGapRow] = []
    for case in corpus_registry.cases:
        expected_count = EXPECTED_CASE_GAP_COUNTS.get(case.case_id)
        if expected_count is None:
            raise ControlRegistryError(
                f"no mapped-gap count policy for {case.case_id}"
            )
        report_path = resolve_portable_path(workspace_root, case.review_path)
        report_sha256 = sha256_file(report_path)
        expected_sha256 = EXPECTED_CASE_REPORT_SHA256[case.case_id]
        if report_sha256 != expected_sha256:
            raise ControlRegistryError(
                f"{case.case_id} report SHA-256 changed: expected "
                f"{expected_sha256}, got {report_sha256}"
            )
        rows = _parse_case_report(report_path)
        if len(rows) != expected_count:
            raise ControlRegistryError(
                f"{case.case_id} expected {expected_count} mapped-gap rows, "
                f"got {len(rows)}"
            )
        case_reports.append(
            CaseReportBinding(
                case_id=case.case_id,
                report_path=case.review_path,
                report_sha256=report_sha256,
                mapped_gap_row_count=len(rows),
            )
        )

        case_claims = tuple(
            sorted(
                (
                    claim
                    for claim in claims_by_id.values()
                    if claim.case_id == case.case_id
                ),
                key=lambda claim: claim.claim_id,
            )
        )
        used_by_gap: dict[str, set[str]] = defaultdict(set)
        occurrences_by_gap: Counter[str] = Counter()
        for row_index, row in enumerate(rows, start=1):
            gap_id = _unquote_gap_id(row.cells[0])
            if gap_id not in matrix_gap_ids:
                raise ControlRegistryError(
                    f"{case.case_id} uses unknown mapped gap {gap_id}"
                )
            occurrences_by_gap[gap_id] += 1
            anchor = _case_gap_anchor(
                case.case_id,
                gap_id,
                occurrences_by_gap[gap_id],
                row,
                case_claims,
                used_by_gap[gap_id],
            )
            used_by_gap[gap_id].add(anchor.claim_id)
            values = dict(zip(row.headers, row.cells, strict=True))
            case_gap_rows.append(
                CaseGapRow(
                    row_id=(
                        f"p00-us09:{case.case_id}:mapped-gap-row-{row_index:02d}"
                    ),
                    case_id=case.case_id,
                    report_row_index=row_index,
                    gap_id=gap_id,
                    raw_row_sha256=_row_sha256(row.raw_line),
                    origin=values.get("Origin"),
                    mapped_capability=values["Mapped capability"],
                    exact_evidence=values.get("Exact evidence"),
                    exact_source_region=values.get("Exact source region"),
                    why_reusable=values.get("Why reusable"),
                    claim_locator=_locator_ref(anchor),
                )
            )

    if len(case_gap_rows) != EXPECTED_CASE_GAP_ROW_COUNT:
        raise ControlRegistryError("case reports must contain exactly 109 rows")

    control_registry = BenchmarkControlRegistry(
        schema_version=CONTRACT_VERSION,
        registry_id=CONTROL_REGISTRY_ID,
        corpus_registry_sha256=corpus_registry_sha256(corpus_registry),
        reviewed_claim_count=EXPECTED_REVIEWED_CLAIM_COUNT,
        gap_owner_count=EXPECTED_GAP_OWNER_COUNT,
        role_assignment_count=EXPECTED_ROLE_ASSIGNMENT_COUNT,
        case_gap_row_count=EXPECTED_CASE_GAP_ROW_COUNT,
        matrix_source=SourceBinding(
            path=GAP_TO_STORY_MATRIX_PATH,
            sha256=matrix_sha256,
        ),
        review_batches=_review_batch_bindings(
            workspace_root,
            review_batches,
        ),
        case_reports=tuple(case_reports),
        gap_controls=tuple(gap_controls),
        case_gap_rows=tuple(sorted(
            case_gap_rows,
            key=lambda row: row.row_id,
        )),
    )
    return validate_benchmark_control_registry(
        control_registry,
        workspace_root,
        corpus_registry,
        review_batches,
    )


def _resolve_claim_locator(
    reference: ClaimLocatorRef,
    claims_by_id: dict[str, ReviewedClaimRecord],
) -> ReviewedClaimRecord:
    try:
        claim = claims_by_id[reference.claim_id]
    except KeyError as exc:
        raise ControlRegistryError(
            f"unknown reviewed claim {reference.claim_id}"
        ) from exc
    if claim.case_id != reference.case_id:
        raise ControlRegistryError(
            f"{reference.claim_id} does not belong to {reference.case_id}"
        )
    matching = [
        locator
        for locator in claim.locators
        if locator.region_id == reference.region_id
    ]
    if len(matching) != 1:
        raise ControlRegistryError(
            f"{reference.claim_id} does not own exactly one locator "
            f"{reference.region_id}"
        )
    return claim


def validate_benchmark_control_registry(
    control_registry: BenchmarkControlRegistry,
    workspace_root: str | Path,
    corpus_registry: PortableCorpusRegistry,
    review_batches: tuple[ReviewBatch, ...],
) -> BenchmarkControlRegistry:
    """Fail closed on source, owner, claim, locator, or truth-policy drift."""

    if (
        control_registry.corpus_registry_sha256
        != corpus_registry_sha256(corpus_registry)
    ):
        raise ControlRegistryError(
            "control registry corpus identity does not match the corpus registry"
        )
    for batch in review_batches:
        validate_review_batch_against_registry(batch, corpus_registry)
    claims_by_id = _claim_index(review_batches)

    expected_bindings = _review_batch_bindings(
        workspace_root,
        review_batches,
    )
    if control_registry.review_batches != expected_bindings:
        raise ControlRegistryError("review batch bindings changed")
    if (
        control_registry.matrix_source.path != GAP_TO_STORY_MATRIX_PATH
        or control_registry.matrix_source.sha256
        != GAP_TO_STORY_MATRIX_SHA256
    ):
        raise ControlRegistryError("gap-to-story matrix binding changed")

    matrix_path = resolve_portable_path(
        workspace_root,
        control_registry.matrix_source.path,
    )
    if sha256_file(matrix_path) != control_registry.matrix_source.sha256:
        raise ControlRegistryError("gap-to-story matrix source changed")
    matrix_rows = _parse_matrix(matrix_path)
    expected_matrix = [
        (
            index,
            _row_sha256(row.raw_line),
            _unquote_gap_id(row.cells[0]),
            *row.cells[1:],
        )
        for index, row in enumerate(matrix_rows, start=1)
    ]
    actual_matrix = [
        (
            control.matrix_row_index,
            control.matrix_row_sha256,
            control.gap_id,
            control.primary_story_id,
            control.secondary_stories,
            control.story_action,
            control.dedicated_test_anchor,
            control.milestone,
        )
        for control in control_registry.gap_controls
    ]
    if actual_matrix != expected_matrix:
        raise ControlRegistryError("gap owner rows do not match the frozen matrix")

    for control in control_registry.gap_controls:
        expected_claim_ids = _CONTROL_CLAIM_POLICIES[control.gap_id]
        for assignment, expected_claim_id in zip(
            control.assignments,
            expected_claim_ids,
            strict=True,
        ):
            claim = _resolve_claim_locator(assignment.evidence, claims_by_id)
            expected_assignment_id = (
                f"p00-us09:{control.gap_id.lower()}:{assignment.role.value}"
            )
            if (
                assignment.assignment_id != expected_assignment_id
                or assignment.evidence.claim_id != expected_claim_id
                or assignment.rationale
                != _control_rationale(control.gap_id, assignment.role)
            ):
                raise ControlRegistryError(
                    f"{assignment.assignment_id} changed its frozen role policy"
                )
            if assignment.evidence != _locator_ref(claim):
                raise ControlRegistryError(
                    f"{assignment.assignment_id} changed its exact claim locator"
                )
            if assignment.role is ControlRole.NEGATIVE_OR_AMBIGUOUS:
                if (
                    claim.review_status not in _UNSUPPORTED_CONTROL_STATUSES
                    or claim.inclusion_mask.literal_parity
                    or claim.inclusion_mask.semantic_parity
                ):
                    raise ControlRegistryError(
                        f"{assignment.assignment_id} promotes unsupported truth"
                    )
            elif (
                claim.review_status not in _SUPPORTED_CONTROL_STATUSES
                or not claim.inclusion_mask.semantic_parity
            ):
                raise ControlRegistryError(
                    f"{assignment.assignment_id} lacks supported semantic evidence"
                )

    report_bindings = {
        binding.case_id: binding
        for binding in control_registry.case_reports
    }
    rows_by_case: dict[str, list[CaseGapRow]] = defaultdict(list)
    for row in control_registry.case_gap_rows:
        rows_by_case[row.case_id].append(row)
        _resolve_claim_locator(row.claim_locator, claims_by_id)

    for case in corpus_registry.cases:
        try:
            binding = report_bindings[case.case_id]
        except KeyError as exc:
            raise ControlRegistryError(
                f"missing case report binding for {case.case_id}"
            ) from exc
        if binding.report_path != case.review_path:
            raise ControlRegistryError(
                f"{case.case_id} report path does not match the corpus registry"
            )
        if (
            binding.report_sha256
            != EXPECTED_CASE_REPORT_SHA256[case.case_id]
            or binding.mapped_gap_row_count
            != EXPECTED_CASE_GAP_COUNTS[case.case_id]
        ):
            raise ControlRegistryError(
                f"{case.case_id} frozen report binding changed"
            )
        report_path = resolve_portable_path(
            workspace_root,
            binding.report_path,
        )
        if sha256_file(report_path) != binding.report_sha256:
            raise ControlRegistryError(
                f"{case.case_id} frozen report source changed"
            )
        source_rows = _parse_case_report(report_path)
        actual_rows = sorted(
            rows_by_case[case.case_id],
            key=lambda row: row.report_row_index,
        )
        if len(source_rows) != len(actual_rows):
            raise ControlRegistryError(
                f"{case.case_id} mapped-gap row count changed"
            )
        case_claims = tuple(
            sorted(
                (
                    claim
                    for claim in claims_by_id.values()
                    if claim.case_id == case.case_id
                ),
                key=lambda claim: claim.claim_id,
            )
        )
        used_by_gap: dict[str, set[str]] = defaultdict(set)
        occurrences_by_gap: Counter[str] = Counter()
        for source, actual in zip(source_rows, actual_rows, strict=True):
            values = dict(zip(source.headers, source.cells, strict=True))
            expected = (
                _unquote_gap_id(source.cells[0]),
                _row_sha256(source.raw_line),
                values.get("Origin"),
                values["Mapped capability"],
                values.get("Exact evidence"),
                values.get("Exact source region"),
                values.get("Why reusable"),
            )
            observed = (
                actual.gap_id,
                actual.raw_row_sha256,
                actual.origin,
                actual.mapped_capability,
                actual.exact_evidence,
                actual.exact_source_region,
                actual.why_reusable,
            )
            if observed != expected:
                raise ControlRegistryError(
                    f"{actual.row_id} does not match its frozen source row"
                )
            occurrences_by_gap[actual.gap_id] += 1
            expected_anchor = _case_gap_anchor(
                case.case_id,
                actual.gap_id,
                occurrences_by_gap[actual.gap_id],
                source,
                case_claims,
                used_by_gap[actual.gap_id],
            )
            used_by_gap[actual.gap_id].add(expected_anchor.claim_id)
            if actual.claim_locator != _locator_ref(expected_anchor):
                raise ControlRegistryError(
                    f"{actual.row_id} changed its frozen claim locator"
                )
    return control_registry


def canonical_control_registry_json(
    control_registry: BenchmarkControlRegistry,
) -> str:
    """Serialize the validated registry deterministically."""

    return json.dumps(
        control_registry.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def control_registry_sha256(
    control_registry: BenchmarkControlRegistry,
) -> str:
    """Return the deterministic semantic identity of the registry."""

    return hashlib.sha256(
        canonical_control_registry_json(control_registry).encode("utf-8")
    ).hexdigest()


def load_control_registry(path: str | Path) -> BenchmarkControlRegistry:
    """Load one strict versioned registry without source reconciliation."""

    return BenchmarkControlRegistry.model_validate_json(Path(path).read_bytes())


def load_benchmark_control_registry(
    path: str | Path,
    workspace_root: str | Path,
    corpus_registry: PortableCorpusRegistry,
    review_batches: tuple[ReviewBatch, ...],
) -> BenchmarkControlRegistry:
    """Reload and compare the persisted registry with a fresh frozen-source build."""

    loaded = validate_benchmark_control_registry(
        load_control_registry(path),
        workspace_root,
        corpus_registry,
        review_batches,
    )
    expected = build_benchmark_control_registry(
        workspace_root,
        corpus_registry,
        review_batches,
    )
    if (
        canonical_control_registry_json(loaded)
        != canonical_control_registry_json(expected)
    ):
        raise ControlRegistryError(
            "persisted control registry does not match frozen sources and policies"
        )
    return loaded
