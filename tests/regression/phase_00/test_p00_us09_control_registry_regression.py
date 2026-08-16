"""Regression anchors for the P00-US09 benchmark-control registry."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path

from app.main import create_app
from app.models import ErrorResponse, ParseResult
from tests.benchmarks.control_registry import (
    CONTROL_REGISTRY_EVIDENCE_PATH,
    GAP_TO_STORY_MATRIX_PATH,
    ControlRole,
    control_registry_sha256,
    load_benchmark_control_registry,
)
from tests.benchmarks.corpus_registry import (
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
    review_batch_sha256,
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

# These are the frozen deterministic identities of the reviewed canonical
# payload; they must not be silently recomputed at test time.
PINNED_CONTROL_REGISTRY_FILE_SHA256 = (
    "a383938d41d067e0b3e01729d12def7b573764092100ef76228e4c23707c86b5"
)
PINNED_CONTROL_REGISTRY_SEMANTIC_SHA256 = (
    "d3c734957b507f07508f8eeffe43ac450f50f53d5f42f8cf63e354fe60738fce"
)
PINNED_MATRIX_FILE_SHA256 = (
    "b89373d7a790de3edac5a38ade1af36ae45085b7f056c2515f1b463b5592542c"
)
PINNED_CASE_REPORT_HASHES = {
    "tracker/benchmarks/llamaparse-15/cases/catastrophe-recap.md": (
        "99b2110820d01d6a63e3677c0b49a3b17d3b5958ec186df0df552009ba976770"
    ),
    "tracker/benchmarks/llamaparse-15/cases/clean-energy.md": (
        "1345fc03e3f55f415dd7682c827e24b6022d25b46ef0ee68e8437bc145f0ca5a"
    ),
    "tracker/benchmarks/llamaparse-15/cases/clinical-study.md": (
        "fa5c1e863b7cee50ca4eea4b6c2debd042c7d9bbe143663cad64a26a07f5806f"
    ),
    "tracker/benchmarks/llamaparse-15/cases/component-datasheet.md": (
        "6e41940bd8ffd61dbf7fce8ec4882f8935f6a94c481c844d7dc828812c4b53fe"
    ),
    "tracker/benchmarks/llamaparse-15/cases/egov-survey.md": (
        "bbdb74c3c05204006c67d5868ad9f7229221c469d6e31a04906a67ac4980bc25"
    ),
    "tracker/benchmarks/llamaparse-15/cases/esg-metrics.md": (
        "174180aa1cb2b42dd2a7deb8692b2c12e69d3edbb3c3d91b3c9934edb07da563"
    ),
    "tracker/benchmarks/llamaparse-15/cases/finance-10k.md": (
        "3a2a661df038536eb95d72febe43189248df37b243194bfede441e1d38c61aff"
    ),
    "tracker/benchmarks/llamaparse-15/cases/health-report.md": (
        "13e74b08061571472993123e5bcfa1ac00ca96a5191a4887bcb94589ccc876f5"
    ),
    "tracker/benchmarks/llamaparse-15/cases/insurance-acord.md": (
        "327e9ed62a2703075e00434d5b02bead11525692d43178198a9377ca0adeaddb"
    ),
    "tracker/benchmarks/llamaparse-15/cases/manufacturing-report.md": (
        "4c38cafd256c090fc9d4041a4465d12f34c0855f8568d25c66fe7eb896a11dd1"
    ),
    "tracker/benchmarks/llamaparse-15/cases/ny-timetable.md": (
        "68e1ce268850da1fa09180c0bd0262976ba983dcc5de039c21b1bbde91c7822b"
    ),
    "tracker/benchmarks/llamaparse-15/cases/postal-10k.md": (
        "e0eb3d81b012018a1b1a2d4d37a17f5c9f62c0014e52bd652845d6ac7fc9cce7"
    ),
    "tracker/benchmarks/llamaparse-15/cases/purchase-agreement.md": (
        "715e14ee37fd5263939d01dd9090b30d2a3c1f6ea6fc703bbb7ca80e529213a4"
    ),
    "tracker/benchmarks/llamaparse-15/cases/settlement-agreement.md": (
        "1e1680bd2b28eca6c68c364a32e1381d64ae7d5c8155325ac03c10e4d8addba9"
    ),
    "tracker/benchmarks/llamaparse-15/cases/uber-earnings.md": (
        "344aa02fc3e0315b912e42489331951c39f6bdbb9b7e0e4fdfc17ebb44018567"
    ),
}
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
EXPECTED_ROLE_FREQUENCIES = {
    ControlRole.TARGET: 25,
    ControlRole.RELATED_POSITIVE: 25,
    ControlRole.NON_TARGET_REGRESSION: 25,
    ControlRole.NEGATIVE_OR_AMBIGUOUS: 25,
}
EXPECTED_CASE_GAP_FREQUENCIES = {
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
EXPECTED_UNMAPPED_OWNER_GAPS = {
    "GAP-BENCHMARK-001",
    "GAP-BENCHMARK-002",
    "GAP-COVERAGE-001",
    "GAP-PERFORMANCE-001",
}
EXPECTED_API_SCHEMA_HASHES = {
    "openapi": (
        "3c71271be81fc55e8f85229e1ffdf01ef6a7977c4638a87449617749a1a2983a"
    ),
    "parse_result": (
        "706a1f63bf77eaa6cc3f114b9b5c976d07d764de04a8beffa45cd2b04aafa91f"
    ),
    "error_response": (
        "3fde7027b8452307282b52870914475672aed4b4326018867fdf467922d1a5a6"
    ),
}


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_inputs():
    corpus_registry = load_corpus_registry(CORPUS_REGISTRY_PATH)
    review_batches = (
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
    return corpus_registry, review_batches


def test_control_registry_and_all_frozen_sources_retain_pinned_hashes() -> None:
    assert (
        sha256_file(CONTROL_REGISTRY_PATH)
        == PINNED_CONTROL_REGISTRY_FILE_SHA256
    )
    assert sha256_file(MATRIX_PATH) == PINNED_MATRIX_FILE_SHA256
    assert {
        path: sha256_file(WORKSPACE / path)
        for path in PINNED_CASE_REPORT_HASHES
    } == PINNED_CASE_REPORT_HASHES


def test_all_review_batches_retain_pinned_file_and_semantic_identities() -> None:
    corpus_registry, review_batches = _load_inputs()
    paths = {
        "p00-us06-reviewed-claims-batch-a": BATCH_A_EVIDENCE_PATH,
        "p00-us07-reviewed-claims-batch-b": BATCH_B_EVIDENCE_PATH,
        "p00-us08-reviewed-claims-batch-c": BATCH_C_EVIDENCE_PATH,
    }

    assert {
        batch.batch_id: (
            batch.claim_count,
            sha256_file(WORKSPACE / paths[batch.batch_id]),
            review_batch_sha256(batch),
        )
        for batch in review_batches
    } == PINNED_BATCH_IDENTITIES
    assert sum(batch.claim_count for batch in review_batches) == 210
    assert corpus_registry.case_count == 15


def test_control_registry_retains_pinned_identity_counts_and_frequencies() -> None:
    corpus_registry, review_batches = _load_inputs()
    control_registry = load_benchmark_control_registry(
        CONTROL_REGISTRY_PATH,
        WORKSPACE,
        corpus_registry,
        review_batches,
    )

    assert (
        control_registry_sha256(control_registry)
        == PINNED_CONTROL_REGISTRY_SEMANTIC_SHA256
    )
    assert control_registry.reviewed_claim_count == 210
    assert control_registry.gap_owner_count == 25
    assert control_registry.role_assignment_count == 100
    assert control_registry.case_gap_row_count == 109
    assert len(control_registry.gap_controls) == 25
    assert len(control_registry.case_gap_rows) == 109

    assignments = [
        assignment
        for control in control_registry.gap_controls
        for assignment in control.assignments
    ]
    assert len(assignments) == 100
    assert Counter(assignment.role for assignment in assignments) == (
        EXPECTED_ROLE_FREQUENCIES
    )
    assert Counter(
        row.gap_id for row in control_registry.case_gap_rows
    ) == EXPECTED_CASE_GAP_FREQUENCIES

    owner_gaps = {control.gap_id for control in control_registry.gap_controls}
    mapped_gaps = {row.gap_id for row in control_registry.case_gap_rows}
    assert owner_gaps - mapped_gaps == EXPECTED_UNMAPPED_OWNER_GAPS
    assert Counter(
        control.gap_id
        for control in control_registry.gap_controls
        for _assignment in control.assignments
    ) == {gap_id: 4 for gap_id in owner_gaps}


def test_production_tree_cannot_import_or_embed_control_registry() -> None:
    violations: list[tuple[str, str]] = []
    for path in sorted((WORKSPACE / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        modules = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        modules.extend(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        for module in modules:
            if module == "tests" or module.startswith("tests."):
                violations.append(
                    (path.relative_to(WORKSPACE).as_posix(), module)
                )
        if (
            "control_registry" in source
            or CONTROL_REGISTRY_EVIDENCE_PATH in source
            or GAP_TO_STORY_MATRIX_PATH in source
        ):
            violations.append(
                (path.relative_to(WORKSPACE).as_posix(), "p00-us09")
            )

    assert violations == []


def test_public_api_and_serializer_schemas_remain_unchanged() -> None:
    schemas = {
        "openapi": create_app().openapi(),
        "parse_result": ParseResult.model_json_schema(),
        "error_response": ErrorResponse.model_json_schema(),
    }
    assert {
        name: _canonical_sha256(schema)
        for name, schema in schemas.items()
    } == EXPECTED_API_SCHEMA_HASHES
