"""P00-US09 acceptance tests for the finite benchmark-control registry."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

import pytest

from tests.benchmarks.control_registry import (
    CONTROL_REGISTRY_EVIDENCE_PATH,
    GAP_TO_STORY_MATRIX_PATH,
    BenchmarkControlRegistry,
    ControlRegistryError,
    ControlRole,
    ExpectedBehavior,
    build_benchmark_control_registry,
    canonical_control_registry_json,
    load_benchmark_control_registry,
    load_control_registry,
    validate_benchmark_control_registry,
)
from tests.benchmarks.corpus_registry import (
    PortableCorpusRegistry,
    load_corpus_registry,
    sha256_file,
)
from tests.benchmarks.reviewed_claim_inventory import (
    BATCH_A_EVIDENCE_PATH,
    BATCH_B_EVIDENCE_PATH,
    BATCH_C_EVIDENCE_PATH,
    load_reviewed_claim_batch_a,
    load_reviewed_claim_batch_b,
    load_reviewed_claim_batch_c,
)
from tests.benchmarks.reviewed_claims import (
    ClaimReviewStatus,
    ReviewBatch,
    canonical_review_batch_json,
    review_batch_sha256,
    validate_review_batch_against_registry,
)


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS_REGISTRY_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US04-corpus-registry.json"
)
CONTROL_REGISTRY_PATH = WORKSPACE / CONTROL_REGISTRY_EVIDENCE_PATH
MATRIX_PATH = WORKSPACE / GAP_TO_STORY_MATRIX_PATH

PINNED_MATRIX_FILE_SHA256 = (
    "b89373d7a790de3edac5a38ade1af36ae45085b7f056c2515f1b463b5592542c"
)
PINNED_MATRIX_ROWS_SHA256 = (
    "85e871613bcf788e220af80659f94bbd30b626d935db35e6cedb60498c3d4c86"
)
PINNED_CASE_GAP_ROWS_SHA256 = (
    "994f3e963e1e51b03dc288814052679841a2a0dca96a7096f7a70e211f35605c"
)
PINNED_CASE_GAP_SEQUENCE_SHA256 = (
    "4fafc3d37d621d7187d400e914fb826f40d8821cd03f20818dbb6b13c8d12292"
)
PINNED_BATCH_IDENTITIES = {
    "p00-us06-reviewed-claims-batch-a": (
        71,
        "f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4",
        "f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee",
    ),
    "p00-us07-reviewed-claims-batch-b": (
        76,
        "7e4728c1c5d76a6453d42c640de8a25c24989ed3a160cac2fe4640b22a55814e",
        "9afe6c098adcd32e3a8370af5ecb2b27ac4730f098e39128e787eef991990d0f",
    ),
    "p00-us08-reviewed-claims-batch-c": (
        63,
        "1411d75d2701e51b815f9f3c0e0e5ba5f799f6ec32ca2788cd31ee4f69f05be1",
        "69c58b8ab7a3b9bdd21bc49183fb5334ee88bee1a4850061820b551ae416eb89",
    ),
}
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
EXPECTED_GAP_FREQUENCIES = {
    "GAP-BBOX-001": 13,
    "GAP-CHART-001": 6,
    "GAP-CHART-002": 5,
    "GAP-DIAGNOSTICS-001": 2,
    "GAP-DIAGRAM-001": 3,
    "GAP-FORM-001": 1,
    "GAP-LAYOUT-001": 2,
    "GAP-LINK-001": 3,
    "GAP-LIST-001": 1,
    "GAP-OCR-001": 6,
    "GAP-ORDER-001": 6,
    "GAP-PAGE-001": 10,
    "GAP-PROVENANCE-001": 13,
    "GAP-REDLINE-001": 2,
    "GAP-SERIALIZATION-001": 12,
    "GAP-TABLE-001": 2,
    "GAP-TABLE-002": 6,
    "GAP-TABLE-003": 4,
    "GAP-TEXT-001": 5,
    "GAP-UNICODE-001": 1,
    "GAP-VISUAL-001": 6,
}
SUPPORTED_STATUSES = {
    ClaimReviewStatus.VERIFIED,
    ClaimReviewStatus.PARTIALLY_VERIFIED,
}
UNSUPPORTED_STATUSES = {
    ClaimReviewStatus.INCORRECT,
    ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE,
    ClaimReviewStatus.POTENTIALLY_INFERRED,
}
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
GAP_PATTERN = re.compile(r"^GAP-[A-Z]+-\d{3}$")


@pytest.fixture(scope="module")
def corpus_registry() -> PortableCorpusRegistry:
    return load_corpus_registry(CORPUS_REGISTRY_PATH)


@pytest.fixture(scope="module")
def review_batches(
    corpus_registry: PortableCorpusRegistry,
) -> tuple[ReviewBatch, ...]:
    return (
        load_reviewed_claim_batch_a(
            WORKSPACE / BATCH_A_EVIDENCE_PATH,
            WORKSPACE,
            corpus_registry,
        ),
        load_reviewed_claim_batch_b(
            WORKSPACE / BATCH_B_EVIDENCE_PATH,
            WORKSPACE,
            corpus_registry,
        ),
        load_reviewed_claim_batch_c(
            WORKSPACE / BATCH_C_EVIDENCE_PATH,
            WORKSPACE,
            corpus_registry,
        ),
    )


@pytest.fixture(scope="module")
def control_registry(
    corpus_registry: PortableCorpusRegistry,
    review_batches: tuple[ReviewBatch, ...],
) -> BenchmarkControlRegistry:
    return load_benchmark_control_registry(
        CONTROL_REGISTRY_PATH,
        WORKSPACE,
        corpus_registry,
        review_batches,
    )


def _split_markdown_row(line: str) -> tuple[str, ...]:
    """Independently split a Markdown row with escaped and inline-code pipes."""

    stripped = line.strip()
    assert stripped.startswith("|") and stripped.endswith("|")
    cells: list[str] = []
    current: list[str] = []
    code_span = False
    index = 1
    while index < len(stripped) - 1:
        char = stripped[index]
        if char == "\\" and index + 1 < len(stripped) - 1:
            current.extend((char, stripped[index + 1]))
            index += 2
            continue
        if char == "`":
            code_span = not code_span
            current.append(char)
        elif char == "|" and not code_span:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    assert code_span is False
    return tuple(cells)


def _table_rows(
    path: Path,
    expected_headers: set[tuple[str, ...]],
    *,
    heading: str | None = None,
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if heading is not None:
        heading_indexes = [
            index for index, line in enumerate(lines) if line == heading
        ]
        assert len(heading_indexes) == 1
        start = heading_indexes[0] + 1
        end = next(
            (
                index
                for index in range(start, len(lines))
                if lines[index].startswith("## ")
            ),
            len(lines),
        )
        lines = lines[start:end]

    header_indexes = [
        index
        for index, line in enumerate(lines)
        if line.lstrip().startswith("|")
        and _split_markdown_row(line) in expected_headers
    ]
    assert len(header_indexes) == 1
    header_index = header_indexes[0]
    headers = _split_markdown_row(lines[header_index])
    separator = _split_markdown_row(lines[header_index + 1])
    assert all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)

    rows = []
    for line in lines[header_index + 2 :]:
        if not line.lstrip().startswith("|"):
            break
        cells = _split_markdown_row(line)
        assert len(cells) == len(headers)
        rows.append((line, cells))
    return headers, tuple(rows)


def _gap_id(value: str) -> str:
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    assert GAP_PATTERN.fullmatch(value)
    return value


def _sha256_lines(lines: list[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def _matrix_source_rows() -> tuple[tuple[str, tuple[str, ...]], ...]:
    _, rows = _table_rows(
        MATRIX_PATH,
        {
            (
                "Gap",
                "Primary story",
                "Secondary stories",
                "Story action",
                "Dedicated test anchor",
                "Milestone",
            )
        },
    )
    return rows


def _case_source_rows(
    corpus_registry: PortableCorpusRegistry,
) -> dict[str, tuple[tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]]:
    recognized_headers = {
        ("Gap", "Mapped capability", "Exact evidence"),
        ("Gap", "Origin", "Mapped capability", "Exact evidence"),
        (
            "Gap",
            "Mapped capability",
            "Exact source region",
            "Why reusable",
        ),
    }
    return {
        case.case_id: _table_rows(
            WORKSPACE / case.review_path,
            recognized_headers,
            heading="## Mapped gaps",
        )
        for case in corpus_registry.cases
    }


def _claim_index(
    review_batches: tuple[ReviewBatch, ...],
) -> dict[str, object]:
    claims = [
        claim for review_batch in review_batches for claim in review_batch.claims
    ]
    assert len(claims) == len({claim.claim_id for claim in claims}) == 210
    return {claim.claim_id: claim for claim in claims}


def _replace_first_assignment_evidence(
    control_registry: BenchmarkControlRegistry,
    **updates: str,
) -> BenchmarkControlRegistry:
    first_control = control_registry.gap_controls[0]
    first_assignment = first_control.assignments[0]
    changed_evidence = first_assignment.evidence.model_copy(update=updates)
    changed_assignment = first_assignment.model_copy(
        update={"evidence": changed_evidence}
    )
    changed_control = first_control.model_copy(
        update={
            "assignments": (
                changed_assignment,
                *first_control.assignments[1:],
            )
        }
    )
    return control_registry.model_copy(
        update={
            "gap_controls": (
                changed_control,
                *control_registry.gap_controls[1:],
            )
        }
    )


def test_frozen_sources_independently_reconcile_to_25_and_109_rows(
    corpus_registry: PortableCorpusRegistry,
    control_registry: BenchmarkControlRegistry,
) -> None:
    matrix_rows = _matrix_source_rows()
    case_tables = _case_source_rows(corpus_registry)
    case_rows = [
        (case_id, raw_line, cells)
        for case_id, (_, rows) in case_tables.items()
        for raw_line, cells in rows
    ]

    assert sha256_file(MATRIX_PATH) == PINNED_MATRIX_FILE_SHA256
    assert len(matrix_rows) == 25
    assert _sha256_lines([raw for raw, _ in matrix_rows]) == (
        PINNED_MATRIX_ROWS_SHA256
    )
    assert len(case_rows) == 109
    assert _sha256_lines([raw for _, raw, _ in case_rows]) == (
        PINNED_CASE_GAP_ROWS_SHA256
    )
    assert _sha256_lines(
        [f"{case_id}\t{_gap_id(cells[0])}" for case_id, _, cells in case_rows]
    ) == PINNED_CASE_GAP_SEQUENCE_SHA256
    assert {
        case_id: len(rows)
        for case_id, (_, rows) in case_tables.items()
    } == EXPECTED_CASE_GAP_COUNTS
    assert Counter(_gap_id(cells[0]) for _, _, cells in case_rows) == (
        EXPECTED_GAP_FREQUENCIES
    )

    for source_index, ((raw_line, cells), control) in enumerate(
        zip(matrix_rows, control_registry.gap_controls, strict=True),
        start=1,
    ):
        assert (
            control.matrix_row_index,
            control.matrix_row_sha256,
            control.gap_id,
            control.primary_story_id,
            control.secondary_stories,
            control.story_action,
            control.dedicated_test_anchor,
            control.milestone,
        ) == (
            source_index,
            hashlib.sha256(raw_line.encode("utf-8")).hexdigest(),
            _gap_id(cells[0]),
            *cells[1:],
        )


def test_all_case_gap_rows_losslessly_match_their_independent_sources(
    corpus_registry: PortableCorpusRegistry,
    control_registry: BenchmarkControlRegistry,
) -> None:
    case_tables = _case_source_rows(corpus_registry)
    registry_rows: dict[str, list[object]] = defaultdict(list)
    for row in control_registry.case_gap_rows:
        registry_rows[row.case_id].append(row)

    assert set(registry_rows) == set(case_tables)
    for case_id, (headers, source_rows) in case_tables.items():
        actual_rows = sorted(
            registry_rows[case_id],
            key=lambda row: row.report_row_index,
        )
        assert len(actual_rows) == len(source_rows)
        for row_index, ((raw_line, cells), actual) in enumerate(
            zip(source_rows, actual_rows, strict=True),
            start=1,
        ):
            values = dict(zip(headers, cells, strict=True))
            assert (
                actual.row_id,
                actual.report_row_index,
                actual.gap_id,
                actual.raw_row_sha256,
                actual.origin,
                actual.mapped_capability,
                actual.exact_evidence,
                actual.exact_source_region,
                actual.why_reusable,
            ) == (
                f"p00-us09:{case_id}:mapped-gap-row-{row_index:02d}",
                row_index,
                _gap_id(cells[0]),
                hashlib.sha256(raw_line.encode("utf-8")).hexdigest(),
                values.get("Origin"),
                values["Mapped capability"],
                values.get("Exact evidence"),
                values.get("Exact source region"),
                values.get("Why reusable"),
            )


def test_registry_is_exactly_25_owners_100_roles_109_rows_and_210_claims(
    control_registry: BenchmarkControlRegistry,
    review_batches: tuple[ReviewBatch, ...],
) -> None:
    assignments = [
        assignment
        for control in control_registry.gap_controls
        for assignment in control.assignments
    ]
    claims = [
        claim for review_batch in review_batches for claim in review_batch.claims
    ]

    assert (
        control_registry.gap_owner_count,
        len(control_registry.gap_controls),
    ) == (25, 25)
    assert (
        control_registry.role_assignment_count,
        len(assignments),
    ) == (100, 100)
    assert (
        control_registry.case_gap_row_count,
        len(control_registry.case_gap_rows),
    ) == (109, 109)
    assert (
        control_registry.reviewed_claim_count,
        len(claims),
        len({claim.claim_id for claim in claims}),
    ) == (210, 210, 210)
    assert Counter(assignment.role for assignment in assignments) == {
        role: 25 for role in ControlRole
    }
    assert all(
        len({assignment.evidence.claim_id for assignment in control.assignments})
        == 4
        for control in control_registry.gap_controls
    )


def test_every_control_and_case_row_resolves_an_exact_owned_locator(
    control_registry: BenchmarkControlRegistry,
    review_batches: tuple[ReviewBatch, ...],
) -> None:
    claims_by_id = _claim_index(review_batches)
    references = [
        assignment.evidence
        for control in control_registry.gap_controls
        for assignment in control.assignments
    ] + [row.claim_locator for row in control_registry.case_gap_rows]

    assert len(references) == 209
    for reference in references:
        claim = claims_by_id[reference.claim_id]
        assert claim.case_id == reference.case_id
        assert (
            sum(
                locator.region_id == reference.region_id
                for locator in claim.locators
            )
            == 1
        )


def test_role_behaviors_preserve_supported_and_unsupported_truth(
    control_registry: BenchmarkControlRegistry,
    review_batches: tuple[ReviewBatch, ...],
) -> None:
    claims_by_id = _claim_index(review_batches)

    for control in control_registry.gap_controls:
        for assignment in control.assignments:
            claim = claims_by_id[assignment.evidence.claim_id]
            assert assignment.expected_behavior is EXPECTED_BEHAVIOR_BY_ROLE[
                assignment.role
            ]
            if assignment.role is ControlRole.NEGATIVE_OR_AMBIGUOUS:
                assert claim.review_status in UNSUPPORTED_STATUSES
                assert claim.inclusion_mask.literal_parity is False
                assert claim.inclusion_mask.semantic_parity is False
            else:
                assert claim.review_status in SUPPORTED_STATUSES
                assert claim.inclusion_mask.semantic_parity is True


def test_registry_rebuilds_reloads_and_serializes_to_one_canonical_identity(
    corpus_registry: PortableCorpusRegistry,
    review_batches: tuple[ReviewBatch, ...],
    control_registry: BenchmarkControlRegistry,
) -> None:
    first = build_benchmark_control_registry(
        WORKSPACE,
        corpus_registry,
        review_batches,
    )
    second = build_benchmark_control_registry(
        WORKSPACE,
        corpus_registry,
        review_batches,
    )
    canonical = canonical_control_registry_json(control_registry)

    assert control_registry == first == second
    assert load_control_registry(CONTROL_REGISTRY_PATH) == control_registry
    assert canonical == canonical_control_registry_json(first)
    assert CONTROL_REGISTRY_PATH.read_text(encoding="utf-8") == canonical + "\n"


def test_persisted_policy_drift_fails_closed(
    corpus_registry: PortableCorpusRegistry,
    review_batches: tuple[ReviewBatch, ...],
    control_registry: BenchmarkControlRegistry,
    tmp_path: Path,
) -> None:
    payload = json.loads(canonical_control_registry_json(control_registry))
    payload["gap_controls"][0]["assignments"][0]["rationale"] += " Drift."
    drifted_path = tmp_path / "drifted-control-registry.json"
    drifted_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ControlRegistryError,
        match=(
            "changed its frozen role policy"
            "|does not match frozen sources and policies"
        ),
    ):
        load_benchmark_control_registry(
            drifted_path,
            WORKSPACE,
            corpus_registry,
            review_batches,
        )


@pytest.mark.parametrize(
    ("reference_update", "message"),
    (
        ({"claim_id": "p00-us06:unknown-case:expert-row-99"}, "unknown reviewed claim"),
        ({"case_id": "unknown-case"}, "does not belong"),
        ({"region_id": "unknown-region"}, "does not own exactly one locator"),
    ),
)
def test_unknown_or_mismatched_claim_locator_references_fail_closed(
    reference_update: dict[str, str],
    message: str,
    corpus_registry: PortableCorpusRegistry,
    review_batches: tuple[ReviewBatch, ...],
    control_registry: BenchmarkControlRegistry,
) -> None:
    changed = _replace_first_assignment_evidence(
        control_registry,
        **reference_update,
    )

    with pytest.raises(ControlRegistryError, match=message):
        validate_benchmark_control_registry(
            changed,
            WORKSPACE,
            corpus_registry,
            review_batches,
        )


def test_mutated_gap_story_and_case_row_sources_fail_closed(
    corpus_registry: PortableCorpusRegistry,
    review_batches: tuple[ReviewBatch, ...],
    control_registry: BenchmarkControlRegistry,
) -> None:
    first_control = control_registry.gap_controls[0]
    changed_control = first_control.model_copy(
        update={"primary_story_id": "P99-US99"}
    )
    story_drift = control_registry.model_copy(
        update={
            "gap_controls": (
                changed_control,
                *control_registry.gap_controls[1:],
            )
        }
    )
    with pytest.raises(ControlRegistryError, match="gap owner rows"):
        validate_benchmark_control_registry(
            story_drift,
            WORKSPACE,
            corpus_registry,
            review_batches,
        )

    first_case_row = control_registry.case_gap_rows[0]
    changed_case_row = first_case_row.model_copy(
        update={"gap_id": "GAP-UNKNOWN-999"}
    )
    case_gap_drift = control_registry.model_copy(
        update={
            "case_gap_rows": (
                changed_case_row,
                *control_registry.case_gap_rows[1:],
            )
        }
    )
    with pytest.raises(ControlRegistryError, match="frozen source row"):
        validate_benchmark_control_registry(
            case_gap_drift,
            WORKSPACE,
            corpus_registry,
            review_batches,
        )


def test_batches_a_b_and_c_remain_immutable_rollback_boundaries(
    corpus_registry: PortableCorpusRegistry,
    review_batches: tuple[ReviewBatch, ...],
) -> None:
    batch_paths = {
        "p00-us06-reviewed-claims-batch-a": (
            WORKSPACE / BATCH_A_EVIDENCE_PATH
        ),
        "p00-us07-reviewed-claims-batch-b": (
            WORKSPACE / BATCH_B_EVIDENCE_PATH
        ),
        "p00-us08-reviewed-claims-batch-c": (
            WORKSPACE / BATCH_C_EVIDENCE_PATH
        ),
    }
    before = tuple(
        canonical_review_batch_json(review_batch)
        for review_batch in review_batches
    )
    built = build_benchmark_control_registry(
        WORKSPACE,
        corpus_registry,
        review_batches,
    )
    after = tuple(
        canonical_review_batch_json(review_batch)
        for review_batch in review_batches
    )

    assert before == after
    assert sum(review_batch.claim_count for review_batch in review_batches) == 210
    for review_batch in review_batches:
        expected_count, expected_file_hash, expected_semantic_hash = (
            PINNED_BATCH_IDENTITIES[review_batch.batch_id]
        )
        assert validate_review_batch_against_registry(
            review_batch,
            corpus_registry,
        ) is review_batch
        assert review_batch.claim_count == expected_count
        assert sha256_file(batch_paths[review_batch.batch_id]) == (
            expected_file_hash
        )
        assert review_batch_sha256(review_batch) == expected_semantic_hash

    assert [
        binding.batch_id for binding in built.review_batches
    ] == list(PINNED_BATCH_IDENTITIES)
    assert [
        binding.evidence_file_sha256 for binding in built.review_batches
    ] == [
        identity[1] for identity in PINNED_BATCH_IDENTITIES.values()
    ]
    assert [
        binding.semantic_sha256 for binding in built.review_batches
    ] == [
        identity[2] for identity in PINNED_BATCH_IDENTITIES.values()
    ]
