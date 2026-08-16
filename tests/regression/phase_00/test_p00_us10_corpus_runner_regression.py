"""Regression anchors for the retained P00-US10 two-case corpus run."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

from app.main import create_app
from app.models import ErrorResponse, ParseResult
from tests.benchmarks.corpus_runner import (
    DIMENSION_ORDER,
    ClaimTreatment,
    CorpusRunRecord,
    MetricDimension,
    application_source_sha256,
    canonical_model_bytes,
    load_benchmark_context,
    load_corpus_run,
    load_semantic_report,
    read_legacy_m0_run,
)
from tests.benchmarks.corpus_registry import sha256_file


WORKSPACE = Path(__file__).resolve().parents[3]
RUN_ROOT = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "p00-us10-integration-20260729-03"
)
RUN_RECORD_PATH = RUN_ROOT / "run-record.json"
REPORT_PATH = RUN_ROOT / "semantic-report.json"
REPORT_MARKDOWN_PATH = RUN_ROOT / "semantic-report.md"
COMMAND_PATH = RUN_ROOT / "command.txt"
FULL_RUN_ROOT = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "p00-us10-corpus-20260729-03"
)
FULL_RUN_RECORD_PATH = FULL_RUN_ROOT / "run-record.json"
FULL_REPORT_PATH = FULL_RUN_ROOT / "semantic-report.json"
FULL_REPORT_MARKDOWN_PATH = FULL_RUN_ROOT / "semantic-report.md"
LEGACY_M0_RUN_ROOT = (
    WORKSPACE
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "runs"
    / "baseline-20260728-current"
)
P00_US03_RUN_ROOT = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US03-baseline-runs-20260728"
)

PINNED_RUN_FILE_HASHES = {
    "run-record.json": (
        "5311ce3c5703f7b55aafe3a44432a6bba065e57d50338132ec550116c72c83d5"
    ),
    "semantic-report.json": (
        "7071d06c1e178e5bc98467b8d37e0d2ea806a252022a4dc4a67691f9e99bdcbc"
    ),
    "semantic-report.md": (
        "9be3178472bc9709492daa0296df507b7600dc8a09367e5efc001e04612937dc"
    ),
    "command.txt": (
        "a8675de87415978af1da22963b70f000e35b7381e82c1a793e70d7930712b9a3"
    ),
}
PINNED_CASE_FILE_HASHES = {
    "catastrophe-recap/case-record.json": (
        "1a68bbfc6b67313ca946582cd399a8b621c7865a0359bfce32af8ba1659961ad"
    ),
    "catastrophe-recap/coordinator-case-record.json": (
        "c7f9c74432dcf032edf99e4122ccd3aa2eddbae13ba833fe00337af34f3794e2"
    ),
    "catastrophe-recap/our-output.json": (
        "f127ae13e4d154901ca01821a85d4d89b120f7f128d4263b4492355fa8290f81"
    ),
    "catastrophe-recap/our-output.md": (
        "9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1"
    ),
    "clean-energy/case-record.json": (
        "e715005d703017963565e023037f14ca80eef87d6bb525068c7e907a5b720ea6"
    ),
    "clean-energy/coordinator-case-record.json": (
        "6f2bcb2560861303ff693de3ace97ffe646e6ab1c33f4d3c90a8a2f421bf9848"
    ),
    "clean-energy/our-output.json": (
        "8cc430cde5aeeeea5048887a3a867d3859b313d6ccd76f75dc5620fb061df15b"
    ),
    "clean-energy/our-output.md": (
        "e94fdcfd242a09cd33cc2198e7fca7bbea3e9abd3ef006eeaa833adf7c5264f3"
    ),
}
PINNED_RUN_TREE = (
    16,
    272_481,
    "461b53c1232d6c8d6a8997b70daac9ba4a815d100be0cd1cd1a279b464f48ac4",
)
PINNED_FULL_RUN_FILE_HASHES = {
    "run-record.json": (
        "aa6192f99e8c7ac8136aad7a7ed47278e02f9093d8d37b219e2068b020c310e2"
    ),
    "semantic-report.json": (
        "3d2e36fd6696039abaeb346fc458687f9f114a340bc895c8ee5b921efbb17c77"
    ),
    "semantic-report.md": (
        "e8448fc677adf1e31debb90e95b27c98d4f42cb3e94fb2fe9ae99102f2975c87"
    ),
    "command.txt": (
        "ba5acf7d97169a784639e75034c5b2336ac5c29fc186ad20ab3bf8b42ca69049"
    ),
}
PINNED_FULL_RUN_TREE = (
    94,
    5_922_586,
    "a145ac7e2b56a0631c27b565a131e7ec83061ebf69e7c8c66692f383126541da",
)
PINNED_FULL_RUN_SEMANTIC_SHA256 = (
    "e9037328dbd5f61fb770c69cc0f6acbd4ec7f64a80896cd50136d7f5b24a3ba7"
)
PINNED_FULL_REPORT_SEMANTIC_SHA256 = (
    "ceb8765bb06ad4c60bbaeb39f69fff932595163da1811611ff2f86ea2c7fb4cb"
)
PINNED_FULL_QUALITY_SIGNATURE = (
    "a18dfdeec1eda8840e269da046285aa518a9a6094e4943e174f0893dc216a1ed"
)
PINNED_FULL_STABLE_OUTPUT_SIGNATURE = (
    "a7b02cdee0e58c881122a692d2bfecdacb13eefbb35225be705ae3ff6c7113a0"
)
PINNED_RUN_SEMANTIC_SHA256 = (
    "48a938db0abc41255d602f0617f389777c25800ee10de030d1d684aaa98c00db"
)
PINNED_REPORT_SEMANTIC_SHA256 = (
    "ad925d63e3af61dc55a9475d169a15f30ef11212d0efdee8b403727330cec2a3"
)
PINNED_QUALITY_SIGNATURE = (
    "a8b7ff47f2652192752aac5e87fff35e14942ec78cf0c182f1c8ef2d7bc799bb"
)
PINNED_STABLE_OUTPUT_SIGNATURE = (
    "0969491618f29db4c0a7a9deb25b8231119e41941b60bb63ab3700c94118ee50"
)
PINNED_APPLICATION_SOURCE_SHA256 = (
    "72e3e1bfd2c3efe9abca2d916cb683d3c2c24e4e110014a034320ceff164a4fc"
)
PINNED_API_SCHEMA_HASHES = {
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
PINNED_FROZEN_INPUTS = {
    "llamaparse-15": (
        "tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json",
        "f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb",
        "f7c3bdf460f64c51a7d7e29765ab1e621dc5f59224ddeba8c8a66959c901e4ca",
    ),
    "p00-us09-benchmark-control-registry": (
        "tracker/phase-00-baseline/evidence/P00-US09-control-registry.json",
        "a383938d41d067e0b3e01729d12def7b573764092100ef76228e4c23707c86b5",
        "d3c734957b507f07508f8eeffe43ac450f50f53d5f42f8cf63e354fe60738fce",
    ),
    "p00-us06-reviewed-claims-batch-a": (
        (
            "tracker/phase-00-baseline/evidence/"
            "P00-US06-reviewed-claims-batch-a.json"
        ),
        "f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4",
        "f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee",
    ),
    "p00-us07-reviewed-claims-batch-b": (
        (
            "tracker/phase-00-baseline/evidence/"
            "P00-US07-reviewed-claims-batch-b.json"
        ),
        "7e4728c1c5d76a6453d42c640de8a25c24989ed3a160cac2fe4640b22a55814e",
        "9afe6c098adcd32e3a8370af5ecb2b27ac4730f098e39128e787eef991990d0f",
    ),
    "p00-us08-reviewed-claims-batch-c": (
        (
            "tracker/phase-00-baseline/evidence/"
            "P00-US08-reviewed-claims-batch-c.json"
        ),
        "1411d75d2701e51b815f9f3c0e0e5ba5f799f6ec32ca2788cd31ee4f69f05be1",
        "69c58b8ab7a3b9bdd21bc49183fb5334ee88bee1a4850061820b551ae416eb89",
    ),
}
PINNED_DIMENSION_COUNTS = {
    # claim, literal, semantic, scored, diagnostic-only, excluded, comparisons
    "text": (11, 11, 11, 0, 11, 0, 0),
    "layout": (7, 4, 7, 0, 7, 0, 0),
    "reading_order": (2, 0, 2, 0, 2, 0, 0),
    "table": (1, 1, 1, 0, 1, 0, 0),
    "chart": (4, 0, 2, 0, 2, 2, 0),
    "diagram": (0, 0, 0, 0, 0, 0, 0),
    "markdown": (0, 0, 0, 0, 0, 0, 2),
    "json": (4, 0, 2, 0, 2, 2, 2),
    "hallucination": (0, 0, 0, 0, 0, 0, 0),
    "diagnostics": (0, 0, 0, 0, 0, 0, 0),
    "performance": (0, 0, 0, 0, 0, 0, 0),
    "cost": (0, 0, 0, 0, 0, 0, 0),
}
PINNED_FULL_CASE_IDS = (
    "catastrophe-recap",
    "clean-energy",
    "clinical-study",
    "component-datasheet",
    "egov-survey",
    "esg-metrics",
    "finance-10k",
    "health-report",
    "insurance-acord",
    "manufacturing-report",
    "ny-timetable",
    "postal-10k",
    "purchase-agreement",
    "settlement-agreement",
    "uber-earnings",
)
PINNED_FULL_DIMENSION_COUNTS = {
    # claim, literal, semantic, scored, diagnostic-only, excluded, comparisons
    "text": (77, 72, 74, 0, 74, 3, 0),
    "layout": (45, 20, 38, 0, 38, 7, 0),
    "reading_order": (9, 0, 9, 0, 9, 0, 0),
    "table": (30, 12, 21, 0, 21, 9, 0),
    "chart": (14, 3, 8, 0, 8, 6, 0),
    "diagram": (8, 2, 5, 0, 5, 3, 0),
    "markdown": (0, 0, 0, 0, 0, 0, 15),
    "json": (27, 0, 7, 0, 7, 20, 15),
    "hallucination": (0, 0, 0, 0, 0, 0, 0),
    "diagnostics": (0, 0, 0, 0, 0, 0, 0),
    "performance": (0, 0, 0, 0, 0, 0, 0),
    "cost": (0, 0, 0, 0, 0, 0, 0),
}
PINNED_OUTPUT_IDENTITIES = {
    "catastrophe-recap": (
        "0d31d1cf81f71317c4ceaf6e317502ced47aa4443932eea4eb1afa4d19e3bbc9",
        "9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1",
    ),
    "clean-energy": (
        "26f222c20ddd2298bb6e37a3bb52f1b9476ff86a6cc04e8638d3ccac45f1c21a",
        "e94fdcfd242a09cd33cc2198e7fca7bbea3e9abd3ef006eeaa833adf7c5264f3",
    ),
}
PINNED_LEGACY_TOOL_HASHES = {
    "tracker/benchmarks/llamaparse-15/tools/run_baseline.py": (
        "d29fc85f8f0840c0dd36bed67146e2957c9e8388cb987e430aa968f74b89f05c"
    ),
    "tracker/benchmarks/llamaparse-15/tools/compare_outputs.py": (
        "2b2acf0e67209d2e4f358cdc31a5d6fc0ac651aa7a4a9af2e01d37a1d99430b9"
    ),
    "tracker/benchmarks/llamaparse-15/tools/corpus_audit.py": (
        "858b811a1fadd6967dfe615b08cc4b7df18151538f4ca4fbbbe1b869255d11e2"
    ),
}
PINNED_LEGACY_M0_TREE = (
    108,
    5_979_736,
    "2c32e9469d6ecd8750e483391cc36aef48fd0dd404ccd91651c4a46a4e854c27",
)
PINNED_P00_US03_TREE = (
    52,
    1_046_355,
    "1959f89fae6be5a5ad132d765261a3b33e07d95b3007f93c4452a5619d337ec1",
)


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tree_identity(root: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    total_bytes = 0
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        total_bytes += len(data)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return len(paths), total_bytes, digest.hexdigest()


def _input_identity_map(inputs: object) -> dict[str, tuple[str, str, str]]:
    bindings = (
        inputs.corpus_registry,  # type: ignore[attr-defined]
        inputs.control_registry,  # type: ignore[attr-defined]
        *inputs.review_batches,  # type: ignore[attr-defined]
    )
    return {
        binding.identity: (
            binding.path,
            binding.file_sha256,
            binding.semantic_sha256,
        )
        for binding in bindings
    }


def _assert_case_record_evidence(
    run: CorpusRunRecord,
    *,
    pinned_hashes: dict[str, str] | None = None,
) -> None:
    assert tuple(
        evidence.case_id for evidence in run.case_record_evidence
    ) == run.selected_case_ids
    for evidence in run.case_record_evidence:
        case_root = f"{run.run_dir}/{evidence.case_id}"
        for artifact, role, filename in (
            (
                evidence.worker_record,
                "worker_case_record",
                "case-record.json",
            ),
            (
                evidence.coordinator_record,
                "coordinator_case_record",
                "coordinator-case-record.json",
            ),
        ):
            assert artifact.role == role
            assert artifact.path == f"{case_root}/{filename}"
            if pinned_hashes is not None:
                assert artifact.sha256 == pinned_hashes[
                    f"{evidence.case_id}/{filename}"
                ]
            artifact_path = WORKSPACE / artifact.path
            assert sha256_file(artifact_path) == artifact.sha256
            assert artifact_path.stat().st_size == artifact.size_bytes


def test_retained_run_and_report_keep_pinned_file_and_semantic_identities() -> None:
    assert {
        name: sha256_file(RUN_ROOT / name)
        for name in PINNED_RUN_FILE_HASHES
    } == PINNED_RUN_FILE_HASHES
    assert {
        name: sha256_file(RUN_ROOT / name)
        for name in PINNED_CASE_FILE_HASHES
    } == PINNED_CASE_FILE_HASHES
    assert _tree_identity(RUN_ROOT) == PINNED_RUN_TREE

    run = load_corpus_run(RUN_RECORD_PATH)
    report = load_semantic_report(REPORT_PATH)
    assert hashlib.sha256(canonical_model_bytes(run)).hexdigest() == (
        PINNED_RUN_SEMANTIC_SHA256
    )
    assert hashlib.sha256(canonical_model_bytes(report)).hexdigest() == (
        PINNED_REPORT_SEMANTIC_SHA256
    )
    assert report.run_semantic_sha256 == PINNED_RUN_SEMANTIC_SHA256
    assert report.quality_signature_sha256 == PINNED_QUALITY_SIGNATURE
    assert (
        report.stable_output_signature_sha256
        == PINNED_STABLE_OUTPUT_SIGNATURE
    )


def test_retained_two_case_run_is_complete_and_output_stable() -> None:
    run = load_corpus_run(RUN_RECORD_PATH)

    assert run.run_id == "p00-us10-integration-20260729-03"
    assert run.run_dir == (
        "tracker/phase-00-baseline/evidence/"
        "p00-us10-integration-20260729-03"
    )
    assert run.status == "success"
    assert run.selected_case_ids == (
        "catastrophe-recap",
        "clean-energy",
    )
    _assert_case_record_evidence(
        run,
        pinned_hashes=PINNED_CASE_FILE_HASHES,
    )
    assert (
        run.requested_case_count,
        run.attempted_case_count,
        run.success_count,
        run.partial_count,
        run.error_count,
        run.timeout_count,
        run.skipped_count,
    ) == (2, 2, 2, 0, 0, 0, 0)
    assert (run.expected_page_count, run.successful_page_count) == (2, 2)
    assert run.diagnostics == ()

    assert {
        case.case_id: (
            case.output.semantic_json.sha256,
            case.output.markdown.sha256,
        )
        for case in run.cases
        if case.output is not None
    } == PINNED_OUTPUT_IDENTITIES
    for case in run.cases:
        assert case.status.value == "success"
        assert case.worker_exit_code == 0
        assert case.output is not None
        assert case.reference_comparison is not None
        assert case.output.observed_page_count == case.registered_page_count
        assert case.output.successful_page_count == case.registered_page_count
        assert case.reference_comparison.semantic_json_stable
        assert case.reference_comparison.markdown_stable


def test_report_retains_exact_review_masks_and_unscored_semantic_boundary() -> None:
    report = load_semantic_report(REPORT_PATH)

    assert (
        report.reviewed_claim_count,
        report.literal_eligible_count,
        report.semantic_eligible_count,
        report.excluded_unsupported_count,
        report.scored_claim_count,
        report.diagnostic_only_count,
    ) == (29, 16, 25, 4, 0, 25)
    assert len(report.claim_ledger) == 29
    assert Counter(claim.treatment for claim in report.claim_ledger) == {
        ClaimTreatment.DIAGNOSTIC_ONLY: 25,
        ClaimTreatment.EXCLUDED_UNSUPPORTED: 4,
    }
    assert all(
        claim.treatment is ClaimTreatment.DIAGNOSTIC_ONLY
        for claim in report.claim_ledger
        if claim.semantic_eligible
    )
    assert all(
        not claim.literal_eligible
        and not claim.semantic_eligible
        and claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
        for claim in report.claim_ledger
        if claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
    )


def test_report_retains_all_12_independent_dimensions() -> None:
    report = load_semantic_report(REPORT_PATH)

    assert tuple(item.dimension for item in report.dimensions) == DIMENSION_ORDER
    assert len(report.dimensions) == 12
    assert {
        item.dimension.value: (
            len(item.claim_ids),
            item.eligible_literal_count,
            item.eligible_semantic_count,
            item.scored_count,
            item.diagnostic_only_count,
            item.excluded_count,
            len(item.output_comparisons),
        )
        for item in report.dimensions
    } == PINNED_DIMENSION_COUNTS
    hallucination = next(
        item
        for item in report.dimensions
        if item.dimension is MetricDimension.HALLUCINATION
    )
    assert len(hallucination.cross_cutting_claim_ids) == 4
    assert set(hallucination.cross_cutting_claim_ids) == {
        claim.claim_id
        for claim in report.claim_ledger
        if claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
    }


def test_outputs_cost_and_performance_remain_honest() -> None:
    report = load_semantic_report(REPORT_PATH)

    assert report.all_outputs_stable
    assert report.cost.model_dump(mode="json") == {
        "hosted_requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "billed_usd": 0.0,
        "method": "fixed offline execution policy",
    }
    performance = report.performance
    assert performance.case_count == 2
    assert performance.environment_comparable
    assert performance.within_tolerance is True
    assert performance.tolerance_percent == 25.0
    assert performance.case_latency_ms.p50 <= (
        performance.reference_latency_p50_ms * 1.25
    )
    assert performance.case_latency_ms.p95 <= (
        performance.reference_latency_p95_ms * 1.25
    )
    assert performance.peak_rss_bytes.p50 <= (
        performance.reference_rss_p50_bytes * 1.25
    )
    assert performance.peak_rss_bytes.maximum <= (
        performance.reference_rss_max_bytes * 1.25
    )


def test_full_corpus_run_is_complete_stable_and_integrity_bound() -> None:
    assert {
        name: sha256_file(FULL_RUN_ROOT / name)
        for name in PINNED_FULL_RUN_FILE_HASHES
    } == PINNED_FULL_RUN_FILE_HASHES
    assert _tree_identity(FULL_RUN_ROOT) == PINNED_FULL_RUN_TREE

    run = load_corpus_run(FULL_RUN_RECORD_PATH)
    report = load_semantic_report(FULL_REPORT_PATH)
    assert hashlib.sha256(canonical_model_bytes(run)).hexdigest() == (
        PINNED_FULL_RUN_SEMANTIC_SHA256
    )
    assert hashlib.sha256(canonical_model_bytes(report)).hexdigest() == (
        PINNED_FULL_REPORT_SEMANTIC_SHA256
    )
    assert report.run_semantic_sha256 == PINNED_FULL_RUN_SEMANTIC_SHA256
    assert report.quality_signature_sha256 == PINNED_FULL_QUALITY_SIGNATURE
    assert (
        report.stable_output_signature_sha256
        == PINNED_FULL_STABLE_OUTPUT_SIGNATURE
    )

    assert run.run_id == "p00-us10-corpus-20260729-03"
    assert run.run_dir == (
        "tracker/phase-00-baseline/evidence/"
        "p00-us10-corpus-20260729-03"
    )
    assert run.status == "success"
    assert run.selected_case_ids == PINNED_FULL_CASE_IDS
    assert (
        run.requested_case_count,
        run.attempted_case_count,
        run.success_count,
        run.partial_count,
        run.error_count,
        run.timeout_count,
        run.skipped_count,
    ) == (15, 15, 15, 0, 0, 0, 0)
    assert (run.expected_page_count, run.successful_page_count) == (30, 30)
    assert run.diagnostics == ()
    _assert_case_record_evidence(run)

    for case in run.cases:
        assert case.status.value == "success"
        assert case.worker_exit_code == 0
        assert case.output is not None
        assert case.reference_comparison is not None
        assert case.output.observed_page_count == case.registered_page_count
        assert case.output.successful_page_count == case.registered_page_count
        assert case.reference_comparison.semantic_json_stable
        assert case.reference_comparison.markdown_stable


def test_full_corpus_report_retains_masks_dimensions_cost_and_performance() -> None:
    report = load_semantic_report(FULL_REPORT_PATH)

    assert (
        report.case_count,
        report.page_count,
        report.reviewed_claim_count,
        report.literal_eligible_count,
        report.semantic_eligible_count,
        report.excluded_unsupported_count,
        report.scored_claim_count,
        report.diagnostic_only_count,
    ) == (15, 30, 210, 109, 162, 48, 0, 162)
    assert len(report.claim_ledger) == 210
    assert Counter(claim.treatment for claim in report.claim_ledger) == {
        ClaimTreatment.DIAGNOSTIC_ONLY: 162,
        ClaimTreatment.EXCLUDED_UNSUPPORTED: 48,
    }
    assert all(
        claim.treatment is ClaimTreatment.DIAGNOSTIC_ONLY
        for claim in report.claim_ledger
        if claim.semantic_eligible
    )
    assert all(
        not claim.literal_eligible
        and not claim.semantic_eligible
        and claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
        for claim in report.claim_ledger
        if claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
    )

    assert tuple(item.dimension for item in report.dimensions) == DIMENSION_ORDER
    assert len(report.dimensions) == 12
    assert {
        item.dimension.value: (
            len(item.claim_ids),
            item.eligible_literal_count,
            item.eligible_semantic_count,
            item.scored_count,
            item.diagnostic_only_count,
            item.excluded_count,
            len(item.output_comparisons),
        )
        for item in report.dimensions
    } == PINNED_FULL_DIMENSION_COUNTS
    hallucination = next(
        item
        for item in report.dimensions
        if item.dimension is MetricDimension.HALLUCINATION
    )
    assert len(hallucination.cross_cutting_claim_ids) == 48
    assert set(hallucination.cross_cutting_claim_ids) == {
        claim.claim_id
        for claim in report.claim_ledger
        if claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
    }

    assert report.all_outputs_stable
    assert report.cost.model_dump(mode="json") == {
        "hosted_requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "billed_usd": 0.0,
        "method": "fixed offline execution policy",
    }
    performance = report.performance
    assert performance.case_count == 15
    assert performance.environment_comparable
    assert performance.within_tolerance is True
    assert performance.tolerance_percent == 25.0
    assert (
        performance.case_latency_ms.p50,
        performance.case_latency_ms.p95,
    ) == (9817.815916147083, 46706.959957955405)
    assert (
        performance.peak_rss_bytes.p50,
        performance.peak_rss_bytes.maximum,
    ) == (1_503_772_672.0, 2_569_650_176.0)
    assert performance.case_latency_ms.p50 <= (
        performance.reference_latency_p50_ms * 1.25
    )
    assert performance.case_latency_ms.p95 <= (
        performance.reference_latency_p95_ms * 1.25
    )
    assert performance.peak_rss_bytes.p50 <= (
        performance.reference_rss_p50_bytes * 1.25
    )
    assert performance.peak_rss_bytes.maximum <= (
        performance.reference_rss_max_bytes * 1.25
    )


def test_frozen_input_bindings_reconcile_with_current_sources() -> None:
    run = load_corpus_run(RUN_RECORD_PATH)
    full_run = load_corpus_run(FULL_RUN_RECORD_PATH)
    report = load_semantic_report(REPORT_PATH)
    full_report = load_semantic_report(FULL_REPORT_PATH)
    context = load_benchmark_context(WORKSPACE)

    assert (
        run.frozen_inputs
        == full_run.frozen_inputs
        == report.frozen_inputs
        == full_report.frozen_inputs
        == context.frozen_inputs
    )
    assert _input_identity_map(run.frozen_inputs) == PINNED_FROZEN_INPUTS
    assert {
        binding.path: sha256_file(WORKSPACE / binding.path)
        for binding in (
            run.frozen_inputs.corpus_registry,
            run.frozen_inputs.control_registry,
            *run.frozen_inputs.review_batches,
        )
    } == {
        path: file_sha
        for path, file_sha, _semantic_sha in PINNED_FROZEN_INPUTS.values()
    }


def test_read_only_verifier_rebuilds_without_mutating_retained_evidence() -> None:
    before = _tree_identity(RUN_ROOT)
    for interpreter in (".venv/bin/python", ".venv/bin/python3"):
        completed = subprocess.run(
            [
                str(WORKSPACE / interpreter),
                "-m",
                "tests.benchmarks.corpus_runner",
                "verify",
                "--workspace",
                str(WORKSPACE),
                "--run-record",
                str(RUN_RECORD_PATH),
            ],
            cwd=WORKSPACE,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == ""
        assert _tree_identity(RUN_ROOT) == before == PINNED_RUN_TREE
    assert sha256_file(REPORT_PATH) == PINNED_RUN_FILE_HASHES[
        "semantic-report.json"
    ]
    assert sha256_file(REPORT_MARKDOWN_PATH) == PINNED_RUN_FILE_HASHES[
        "semantic-report.md"
    ]


def test_full_corpus_verifier_is_read_only() -> None:
    before = _tree_identity(FULL_RUN_ROOT)
    completed = subprocess.run(
        [
            str(WORKSPACE / ".venv/bin/python3"),
            "-m",
            "tests.benchmarks.corpus_runner",
            "verify",
            "--workspace",
            str(WORKSPACE),
            "--run-record",
            str(FULL_RUN_RECORD_PATH),
        ],
        cwd=WORKSPACE,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert _tree_identity(FULL_RUN_ROOT) == before == PINNED_FULL_RUN_TREE
    assert sha256_file(FULL_REPORT_PATH) == PINNED_FULL_RUN_FILE_HASHES[
        "semantic-report.json"
    ]
    assert sha256_file(
        FULL_REPORT_MARKDOWN_PATH
    ) == PINNED_FULL_RUN_FILE_HASHES["semantic-report.md"]


def test_historical_source_and_live_public_api_identities_remain_valid() -> None:
    run = load_corpus_run(RUN_RECORD_PATH)
    assert (
        run.environment.application_source_sha256
        == PINNED_APPLICATION_SOURCE_SHA256
    )
    current_source_identity = application_source_sha256(WORKSPACE)
    assert len(current_source_identity) == 64
    assert set(current_source_identity) <= set("0123456789abcdef")

    schemas = {
        "openapi": create_app().openapi(),
        "parse_result": ParseResult.model_json_schema(),
        "error_response": ErrorResponse.model_json_schema(),
    }
    assert {
        name: _canonical_sha256(schema)
        for name, schema in schemas.items()
    } == PINNED_API_SCHEMA_HASHES

    violations: list[str] = []
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
        if any(module == "tests" or module.startswith("tests.") for module in modules):
            violations.append(path.relative_to(WORKSPACE).as_posix())
    assert violations == []


def test_frozen_legacy_tools_and_runs_remain_byte_stable_and_readable() -> None:
    assert {
        path: sha256_file(WORKSPACE / path)
        for path in PINNED_LEGACY_TOOL_HASHES
    } == PINNED_LEGACY_TOOL_HASHES
    assert _tree_identity(LEGACY_M0_RUN_ROOT) == PINNED_LEGACY_M0_TREE
    assert _tree_identity(P00_US03_RUN_ROOT) == PINNED_P00_US03_TREE

    before_m0 = _tree_identity(LEGACY_M0_RUN_ROOT)
    before_us03 = _tree_identity(P00_US03_RUN_ROOT)
    legacy = read_legacy_m0_run(WORKSPACE)
    assert (
        legacy.status,
        legacy.case_count,
        legacy.page_count,
        legacy.metadata_sha256,
        legacy.comparison_sha256,
    ) == (
        "success",
        15,
        30,
        "386c333bff8ec0678d1194fff5899f82ec9475d29be7d72999a58c3817e3128f",
        "2a23aabc812e6723621174f9c66027c2cf3e852de31a8481262e7a2708710e7b",
    )
    assert _tree_identity(LEGACY_M0_RUN_ROOT) == before_m0
    assert _tree_identity(P00_US03_RUN_ROOT) == before_us03
