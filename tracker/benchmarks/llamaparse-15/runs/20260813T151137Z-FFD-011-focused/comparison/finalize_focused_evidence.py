#!/usr/bin/env python3
"""Finalize FFD-011 evidence after the independent artifact review."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = RUN_ROOT.parents[4]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def changed_file_record() -> dict[str, Any]:
    records = {
        "production": {
            "app/services/source_text_alignment.py": "Generic authenticated table-owned supplemental matching, complete coverage, ambiguity, diagnostics, and terminal reconstruction.",
            "app/services/pipeline.py": "Private P04 authority-view transport, OCR contributor issuance, and dependency rollback.",
            "app/services/text_run_semantics.py": "Non-destructive exclusion of authenticated supplemental OCR from native formatting-target competition.",
        },
        "backend_tests_and_contracts": {
            "tests/stories/phase_02/test_p02_us04_table_owned_supplemental_reconciliation.py": "Generic positives, identity/page/batch independence, and fail-closed adversaries.",
            "tests/regression/phase_02/test_p02_us04_table_owned_ocr_regression.py": "Complete Postal three-surface regression, named collateral, and Finance fail-closed control.",
            "tests/contract/test_p03_source_alignment_table_owned_suppression_contract.py": "Independent suppression/provenance reconstruction contract.",
            "tests/fixtures/phase_03/running_regions/contract.py": "Terminal table-owned witness and independent coverage validation.",
            "tests/stories/phase_04/test_p04_us01_table_dependency_rollback.py": "Exact timeout/integrity/resource rollback and successful dependency commit.",
            "tests/stories/phase_03/test_p03_us05_algorithm_hardening.py": "Supplemental OCR/native text-run custody control.",
            "tests/stories/phase_02/test_source_text_alignment_service.py": "Legacy lineage fail-closed expectation update.",
            "tests/regression/phase_02/test_p02_phase_exit_text_targets.py": "Legacy lineage fail-closed and FFD-011 phase-exit expectation update.",
            "tests/regression/phase_04/test_p04_us01_public_projection_regression.py": "Semantic footer lookup after legitimate deterministic ID repair.",
        },
        "frontend_test": {
            "frontend/tests/rendered-ui-capture.test.mts": "Real renderer exactly-once table custody regression."
        },
        "tracker_and_evidence": {
            "tracker/functional-fidelity-defects/issues/FFD-011-postal-detached-fers-duplicate.md": "Readiness, implementation, immediate validation, and closure blocker.",
            "tracker/functional-fidelity-defects/README.md": "Current WIP validation state.",
            "tracker/functional-fidelity-defects/execution-order.md": "Slice-1 target pass and named-control blocker.",
            "tracker/functional-fidelity-defects/index.md": "Validating release-tracking state.",
            "tracker/functional-fidelity-defects/source-gap-coverage.md": "SG-020 targeted-pass/open-card disposition.",
            "tracker/phase-02-text-integrity/stories/P02-US04.md": "FFD-011 capability/acceptance addendum.",
            "tracker/phase-04-tables/stories/P04-US01.md": "FFD-011 custody/rollback addendum.",
        },
    }
    output: dict[str, Any] = {
        "schema_version": "ffd-011-changed-files-v1",
        "backend_git_metadata_available": False,
        "backend_diff_method": "retained file hashes, focused searches, tests, and independent production review",
        "frontend_worktree_note": "The frontend worktree already contained unrelated tracked and untracked changes; they were preserved.",
        "files": {},
    }
    for category, files in records.items():
        output["files"][category] = []
        for relative, purpose in files.items():
            path = WORKSPACE / relative
            output["files"][category].append(
                {
                    "path": relative,
                    "exists": path.is_file(),
                    "size_bytes": path.stat().st_size if path.is_file() else None,
                    "sha256": sha256(path) if path.is_file() else None,
                    "purpose": purpose,
                }
            )
    return output


def main() -> None:
    completed_at = datetime.now(timezone.utc).isoformat()
    targeted = json.loads(
        (RUN_ROOT / "comparison/targeted-review.json").read_text(encoding="utf-8")
    )
    assert targeted["status"] == "pass"
    assert all(targeted["checks"].values())

    dump_json(RUN_ROOT / "comparison/changed-files.json", changed_file_record())
    dump_json(
        RUN_ROOT / "comparison/genericity-search.json",
        {
            "schema_version": "ffd-011-production-search-v1",
            "reviewed_files": [
                "app/services/source_text_alignment.py",
                "app/services/pipeline.py",
                "app/services/text_run_semantics.py",
                "app/services/table_semantics.py",
            ],
            "forbidden_search": {
                "patterns": [
                    "FFD-011",
                    "postal-10k",
                    "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74",
                    "Federal Employees Retirement System",
                    "FERS",
                    "llamaparse",
                    "benchmark-expertmodeldata",
                    "expected glossary",
                    "glossary row",
                ],
                "matches": [],
            },
            "suspicious_constant_search": {
                "matches": [
                    {
                        "path": "app/services/source_text_alignment.py",
                        "line": 924,
                        "text": "rebuilt[\"source_document_identity\"] == source_sha256",
                        "adjudication": "Generic validation that an issued contributor is bound to the current input source; no fixture value is present.",
                    }
                ]
            },
            "production_hashes": {
                "app/services/source_text_alignment.py": "4efbcf6e159c4e5f9164cd27504d37346faeba8739468bc2f80d5f05ffd825db",
                "app/services/pipeline.py": "2c841e2f3fc3b75bff52abc1e96b06bdee253f4c629f5c11eae8b09284e95bb9",
                "app/services/text_run_semantics.py": "5e679c53f21d72db302a35a07852a638cd0a1caa5083d54be1f239a718453fd8",
            },
            "verdict": "pass: no fixture-specific activation rule or oracle leak found",
        },
    )

    closure_record = {
        "schema_version": "ffd-011-immediate-closure-record-v1",
        "defect_id": "FFD-011",
        "implementation_slice": 1,
        "affected_case": "postal-10k",
        "source_sha256": "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74",
        "source_size_bytes": 83589,
        "source_page_count": 3,
        "immediate_affected_benchmark_attempt_result": "pass",
        "overall_defect_status": "Validating",
        "surface_verdicts": {
            "source": "pass: one table row; no detached source paragraph",
            "service_raw_and_canonical_markdown": "pass: byte-identical; one row and zero detached target/collateral paragraphs",
            "service_full_public_json": "pass: context-free validation, unique canonical row, no detached item, complete suppression provenance",
            "actual_clearleaf_ui_dom": "pass: 40 table rows, one FERS row, one introductory paragraph, no post-table duplicate",
            "llamaparse_raw_markdown": "pass: byte-identical to selected reference; one row and no detached paragraph",
            "llamaparse_full_json": "pass: semantic payload equal to selected reference; fresh job/asset identities retained raw",
            "actual_llamaparse_ui_dom": "pass: heading/text/table/footer, 40 rows, one FERS row, no post-table text item",
        },
        "collateral_verdict": {
            "all_39_glossary_rows": "pass: exact selected content and order",
            "CIO_CARES_Exchange_neighbors": "pass: table-owned and no detached paragraphs; ClO absent",
            "postal_page_2_table": "pass: complete table object equal to selected service",
            "postal_page_3_table": "pass: complete table object equal to selected service",
            "unexpected_material_pre_post_service_changes": [],
        },
        "drift": {
            "service_markdown": "only detached FERS paragraph removal",
            "service_dom_pages_2_3": "identical",
            "service_json": "intended complete supplemental suppression ledger/provenance and deterministic custody repair",
            "llamaparse_markdown": "identical",
            "llamaparse_semantic_json": "identical except fresh job and asset identities/URLs",
            "raw_paths": "comparison/drift",
            "generic_analyzer": "30 pre-existing cross-system signals owned by other tracker work or envelope differences; not an FFD-011 target verdict",
        },
        "reviewers": [
            {
                "reviewer": "/root/settled_prod_review",
                "role": "independent production implementation reviewer",
                "verdict": "clean; no correctness, genericity, provenance, ambiguity, performance-bound, atomicity, schema, collateral, or rollback finding",
                "evidence": "61 focused passes, 13 complete-PDF regression passes, terminal/text-run checks, production hashes, and forbidden search",
            },
            {
                "reviewer": "/root/fresh_artifact_review",
                "role": "independent source/Markdown/UI-DOM/JSON and drift reviewer",
                "verdict": "pass for the immediate FFD-011 targeted attempt; keep the overall card Validating because mandatory named P04 controls remain red",
                "evidence": "source renders, both raw Markdown files, both full JSON files, actual UI screenshots/DOM/accessibility, downloaded assets, and complete drift bundle",
            },
            {
                "reviewer": "/root/closure_tracker_audit",
                "role": "independent closure-policy reviewer",
                "verdict": "not eligible for Done while three named P04 custody controls remain red",
            },
        ],
        "closure_blockers": [
            {
                "test": "test_clinical_headers_sections_and_group_spans_are_source_supported",
                "cause": "fixed five-second P04 active wall deadline restores exact predecessor without expected table_evidence",
            },
            {
                "test": "test_timetable_fails_closed_without_shifting_or_silently_merging_rows",
                "cause": "fixed five-second P04 active wall deadline restores exact predecessor without expected table_evidence",
            },
            {
                "test": "test_clinical_output_context_free_json_round_trip_is_exact_and_bounded",
                "cause": "fixed five-second P04 active wall deadline restores exact predecessor without expected canonical_source_custody",
            },
        ],
        "blocker_scope_adjudication": "The failing tests disable source alignment and the selected pre-fix artifacts already lack the sidecars. They are not an FFD-011 content regression, but literal named-control/P04-custody closure requirements remain unsatisfied. Resolving or waiving them requires authority outside this FFD-011-only slice.",
        "safest_next_action": "Keep FFD-011 Validating; separately authorize correction of the P04 deadline/custody gate or explicitly approve a bounded closure exception. Do not start FFD-012.",
        "wave_a_all_15_drift_gate": "pending",
        "final_frozen_all_15_campaign": "pending",
        "local_pass_replaces_later_gates": False,
        "reviewed_at_utc": completed_at,
    }
    dump_json(RUN_ROOT / "comparison/closure-record.json", closure_record)

    dump_json(
        RUN_ROOT / "attempt-status.json",
        {
            "run_id": RUN_ROOT.name,
            "immutable": True,
            "status": "targeted_pass_overall_closure_blocked",
            "immediate_affected_benchmark_attempt_result": "pass",
            "overall_defect_status": "Validating",
            "fresh_llamaparse_job": "pjb-frndkxx9xo4bww7bjg78oxfvhqqe",
            "fresh_service_status": "success",
            "targeted_review_status": targeted["status"],
            "closure_record": "comparison/closure-record.json",
            "closure_blocker_count": 3,
            "wave_a_all_15_drift_gate": "pending",
            "final_frozen_all_15_campaign": "pending",
        },
    )
    run_metadata = json.loads(
        (RUN_ROOT / "run-metadata.json").read_text(encoding="utf-8")
    )
    run_metadata["status"] = "targeted_pass_overall_closure_blocked"
    run_metadata["completed_at_utc"] = completed_at
    run_metadata["immediate_attempt_result"] = "pass"
    run_metadata["overall_defect_status"] = "Validating"
    run_metadata["closure_record"] = "comparison/closure-record.json"
    run_metadata["artifact_manifest"] = "artifact-sha256.txt"
    run_metadata["artifact_manifest_sha256"] = "artifact-sha256.sha256"
    dump_json(RUN_ROOT / "run-metadata.json", run_metadata)

    manifest_paths = sorted(
        path
        for path in RUN_ROOT.rglob("*")
        if path.is_file()
        and path.name not in {"artifact-sha256.txt", "artifact-sha256.sha256"}
        and "__pycache__" not in path.parts
    )
    manifest_lines = [
        f"{sha256(path)}  ./{path.relative_to(RUN_ROOT).as_posix()}"
        for path in manifest_paths
    ]
    manifest = RUN_ROOT / "artifact-sha256.txt"
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    (RUN_ROOT / "artifact-sha256.sha256").write_text(
        f"{sha256(manifest)}  artifact-sha256.txt\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "attempt": "pass",
                "overall_status": "Validating",
                "closure_blockers": 3,
                "artifact_count": len(manifest_paths),
                "manifest_sha256": sha256(manifest),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
