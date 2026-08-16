"""Executable, candidate-specific P03-US08 latency exception custody."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import tomllib
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from tests.benchmarks import running_region_metrics as metrics
from tests.fixtures.phase_03.running_regions import contract as readiness
from tests.fixtures.phase_04.tables import metrics as table_metrics

WAIVER_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-provisional-latency-waiver.json"
)
RENEWAL_WAIVER_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-frontend-bbox-latency-waiver-renewal.json"
)
PHASE04_RENEWAL_WAIVER_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-phase04-tables-latency-waiver-renewal.json"
)
HARDENED_PHASE04_RENEWAL_WAIVER_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-phase04-tables-latency-waiver-hardened-renewal.json"
)
SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-phase04-tables-latency-waiver-semantic-isolation-renewal.json"
)
SEMANTIC_ISOLATION_PHASE04_VERIFICATION_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-phase04-tables-latency-waiver-semantic-isolation-"
    "verification.json"
)
SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-phase04-tables-latency-waiver-semantic-isolation-"
    "independent-approval.json"
)
SEMANTIC_ISOLATION_PHASE04_FOCUSED_GATE_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-phase04-tables-latency-waiver-semantic-isolation-"
    "focused-gate.json"
)
SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-phase04-tables-latency-waiver-semantic-isolation-"
    "P04-US01-final-gates.json"
)
SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT = PurePosixPath(
    "tracker/phase-04-tables/evidence/P04-US01-preapproval"
)
SEMANTIC_ISOLATION_PHASE04_PRODUCTION_SECURITY_REVIEW_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-phase04-tables-latency-waiver-semantic-isolation-"
    "production-security-review.json"
)
SEMANTIC_ISOLATION_PHASE04_METRICS_CUSTODY_REVIEW_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-phase04-tables-latency-waiver-semantic-isolation-"
    "metrics-custody-review.json"
)
SEMANTIC_ISOLATION_GUARD_PATH = PurePosixPath(
    "tests/fixtures/phase_03/running_regions/performance_exception.py"
)
SEMANTIC_ISOLATION_FOCUSED_TEST_PATH = PurePosixPath(
    "tests/performance/test_p03_us08_provisional_latency_exception.py"
)
EXPECTED_SEMANTIC_ISOLATION_NON_AUTHORITATIVE_STATUS_SUMMARY_PATHS = (
    "tracker/phase-04-tables/metrics.md",
    "tracker/phase-04-tables/phase-regression.md",
)
SEMANTIC_ISOLATION_STATUS_OWNER_PATHS = (
    "tracker/README.md",
    "tracker/dependencies.md",
    "tracker/roadmap.md",
    "tracker/phase-04-tables/README.md",
    "tracker/phase-04-tables/backlog.md",
    *EXPECTED_SEMANTIC_ISOLATION_NON_AUTHORITATIVE_STATUS_SUMMARY_PATHS,
    "tracker/phase-04-tables/stories/P04-US01.md",
    "tracker/phase-04-tables/stories/P04-US02.md",
    "tracker/phase-04-tables/stories/P04-US03.md",
    "tracker/phase-04-tables/stories/P04-US04.md",
    "tracker/phase-05-charts-diagrams/README.md",
    "tracker/phase-05-charts-diagrams/backlog.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US01.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US02.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US03.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US04.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US05.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US06.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US07.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US08.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US09.md",
    "tracker/phase-05-charts-diagrams/stories/P05-US10.md",
)
SEMANTIC_ISOLATION_TERMINAL_CONFIGURATION_PATHS = (
    ".env.example",
    "Dockerfile",
    "app/config.py",
    "frontend/.env.example",
    "frontend/.openai/hosting.json",
    "frontend/app/expertmodel.json",
    "frontend/eslint.config.mjs",
    "frontend/next.config.ts",
    "frontend/package-lock.json",
    "frontend/package.json",
    "frontend/postcss.config.mjs",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    "pyproject.toml",
    "uv.lock",
)
_SEMANTIC_ISOLATION_FINDING_FIELDS = (
    "blocking_findings",
    "compatibility_findings",
    "correctness_findings",
    "custody_findings",
    "major_findings",
    "performance_findings",
    "security_findings",
)
_SEMANTIC_ISOLATION_FOCUSED_COMMANDS = (
    (
        ".venv/bin/python",
        "-m",
        "py_compile",
        str(SEMANTIC_ISOLATION_GUARD_PATH),
        str(SEMANTIC_ISOLATION_FOCUSED_TEST_PATH),
    ),
    (
        ".venv/bin/pytest",
        "-q",
        str(SEMANTIC_ISOLATION_FOCUSED_TEST_PATH),
    ),
)
_SEMANTIC_ISOLATION_AUTHORIZED_ON = date(2026, 8, 5)
_SEMANTIC_ISOLATION_REVIEW_DUE_ON = date(2026, 9, 2)
_SEMANTIC_ISOLATION_US01_GATE_CATEGORIES = (
    "product_correctness_quality",
    "production_security",
    "resource_timeout_output",
    "api_schema_serializer_compatibility",
    "frontend_compatibility",
    "paired_latency_rss",
    "rollback_default_off",
    "dependency_custody",
)
_SEMANTIC_ISOLATION_US01_GATE_RESULT_KEYS = {
    "product_correctness_quality": frozenset(
        {
            "correctness_passed",
            "oracle_semantic_sha256",
            "quality_passed",
            "reviewed_real_document_count",
            "reviewed_real_document_ids",
            "synthetic_controls_passed",
        }
    ),
    "production_security": frozenset(
        {
            "fail_closed_passed",
            "hosted_cost_usd",
            "hosted_requests",
            "hosted_tokens",
            "malformed_input_passed",
            "security_passed",
        }
    ),
    "resource_timeout_output": frozenset(
        {
            "allocation_passed",
            "deadline_passed",
            "memory_passed",
            "output_bounds_passed",
            "resource_passed",
            "timeout_passed",
        }
    ),
    "api_schema_serializer_compatibility": frozenset(
        {
            "api_passed",
            "backward_compatibility_passed",
            "schema_passed",
            "serializer_passed",
        }
    ),
    "frontend_compatibility": frozenset(
        {
            "build_passed",
            "bundle_passed",
            "lint_passed",
            "responsive_check_count",
            "responsive_passed",
            "typecheck_passed",
            "unit_passed",
            "unit_test_count",
        }
    ),
    "paired_latency_rss": frozenset(
        {
            "case_results",
            "p03_attempt48_exception",
            "p03_regression_gates",
            "phase04_pair_count",
            "phase04_peak_rss_passed",
            "phase04_table_stage_latency_passed",
        }
    ),
    "rollback_default_off": frozenset(
        {
            "default_off_passed",
            "phase04_flags",
            "rollback_passed",
            "running_region_default_off_passed",
        }
    ),
    "dependency_custody": frozenset(
        {
            "code_custody_passed",
            "dependency_changes_observed",
            "dependency_custody_sha256",
            "dependency_integrity_passed",
            "input_and_fixture_custody_passed",
        }
    ),
}
_SEMANTIC_ISOLATION_US01_COMMAND_COVERAGE = {
    "product_correctness_quality": frozenset(
        {"correctness", "real_quality", "synthetic_controls"}
    ),
    "production_security": frozenset(
        {"fail_closed", "hosted_zero", "malformed_input", "security"}
    ),
    "resource_timeout_output": frozenset(
        {"allocation", "deadline", "memory", "output", "resource", "timeout"}
    ),
    "api_schema_serializer_compatibility": frozenset(
        {"api", "backward_compatibility", "schema", "serializer"}
    ),
    "frontend_compatibility": frozenset(
        {"build", "bundle", "lint", "responsive", "typecheck", "unit"}
    ),
    "paired_latency_rss": frozenset(
        {
            "p03_active_exception_regression",
            "paired_parser_regression",
            "phase04_paired_latency_rss",
            "source_extraction_regression",
            "uber_projection_regression",
        }
    ),
    "rollback_default_off": frozenset(
        {"phase04_default_off", "rollback", "running_region_default_off"}
    ),
    "dependency_custody": frozenset(
        {
            "code_input_fixture_custody",
            "frontend_dependency_integrity",
            "python_dependency_integrity",
        }
    ),
}
_SEMANTIC_ISOLATION_US01_PERFORMANCE_CASES = frozenset(
    {"finance-10k", "ny-timetable", "postal-10k"}
)
_SEMANTIC_ISOLATION_US01_QUALITY_CASES = (
    "catastrophe-recap",
    "finance-10k",
    "postal-10k",
    "clinical-study",
    "ny-timetable",
    "insurance-acord",
)
_SEMANTIC_ISOLATION_US01_ORACLE_SEMANTIC_SHA256 = (
    "b0506a443e7275f911be1b5d43d28a994f68203cd42ae4f194c8c88bd89690d1"
)
_SEMANTIC_ISOLATION_US01_MAXIMUM_UNIQUE_ARTIFACTS = 64
_SEMANTIC_ISOLATION_US01_MAXIMUM_ARTIFACT_BYTES = 2 * 1024 * 1024
_SEMANTIC_ISOLATION_US01_MAXIMUM_TOTAL_ARTIFACT_BYTES = 32 * 1024 * 1024
_SEMANTIC_ISOLATION_US01_MAXIMUM_GATE_INPUTS = 128
_SEMANTIC_ISOLATION_US01_MAXIMUM_GATE_INPUT_BYTES = 4 * 1024 * 1024
_SEMANTIC_ISOLATION_US01_MAXIMUM_TOTAL_GATE_INPUT_BYTES = 64 * 1024 * 1024
_SEMANTIC_ISOLATION_P04_US01_ADMINISTRATIVE_FREEZE_EXCLUDED_PATHS = frozenset(
    {
        str(SEMANTIC_ISOLATION_GUARD_PATH),
        str(SEMANTIC_ISOLATION_FOCUSED_TEST_PATH),
    }
)
EXPECTED_SEMANTIC_ISOLATION_P04_US01_ADMINISTRATIVE_FREEZE = {
    "gate_input_count": 59,
    "gate_input_manifest_sha256": (
        "fd49b22916ffa677ccaf3c50431e8ea896fee6facf848e7435c3c36d86c8d862"
    ),
    "gate_input_total_bytes": 4_292_724,
}
_SEMANTIC_ISOLATION_DEPENDENCY_BRIDGE_PYPROJECT_DEV_LINE = (
    b'    "psutil==7.2.2",\n'
)
_SEMANTIC_ISOLATION_DEPENDENCY_BRIDGE_LOCK_DEV_BLOCK = (
    b"[package.optional-dependencies]\n"
    b"dev = [\n"
    b'    { name = "httpx" },\n'
    b'    { name = "psutil" },\n'
    b'    { name = "pytest" },\n'
    b"]\n"
)
_SEMANTIC_ISOLATION_DEPENDENCY_BRIDGE_HISTORICAL_LOCK_DEV_BLOCK = (
    b"[package.optional-dependencies]\n"
    b"dev = [\n"
    b'    { name = "httpx" },\n'
    b'    { name = "pytest" },\n'
    b"]\n"
)
_SEMANTIC_ISOLATION_DEPENDENCY_BRIDGE_LOCK_METADATA_LINE = (
    b'    { name = "psutil", marker = "extra == \'dev\'", '
    b'specifier = "==7.2.2" },\n'
)
EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE = {
    "change_scope": (
        "exact direct dev declaration of the already-resolved psutil 7.2.2 "
        "for P04-US01 current-process RSS measurement only"
    ),
    "claims": {
        "compatibility_gate_waived": False,
        "dependency_custody_gate_waived": False,
        "further_manifest_change_authorized": False,
        "new_resolved_package_authorized": False,
        "runtime_or_production_dependency_change_authorized": False,
    },
    "current_dependency_custody_sha256": (
        "0ce1630f9a0f64c6bb80b04a04c995ff91dc8ed6bb112fc53bcbfe628a6f70e7"
    ),
    "current_manifest_identities": {
        "frontend/package-lock.json": {
            "path": "frontend/package-lock.json",
            "sha256": (
                "9df758a5fef8b3d6ed33bafb2129c7f710373e261ec744516dd6d597a985796e"
            ),
            "size_bytes": 346_488,
        },
        "frontend/package.json": {
            "path": "frontend/package.json",
            "sha256": (
                "40b23bd6c3c4ed51c01d10cccc41e02575467046df23462444f5b0273b7c8c5c"
            ),
            "size_bytes": 1_522,
        },
        "pyproject.toml": {
            "path": "pyproject.toml",
            "sha256": (
                "a9c66f17d92ea9fae623a7d6d953c91b103fbbe96b8fa98d122651d87cfb2cd8"
            ),
            "size_bytes": 755,
        },
        "uv.lock": {
            "path": "uv.lock",
            "sha256": (
                "acd97c526138e247c54272b250c784b311de17b05ef3a28990b86b548f205b11"
            ),
            "size_bytes": 606_213,
        },
    },
    "historical_dependency_custody_sha256": (
        "2f5711a6e13f3b47d3b76c0960f8b3de0387cc0ad6f8e6610d1116b3c024f2ab"
    ),
    "historical_manifest_identities": {
        "frontend/package-lock.json": {
            "path": "frontend/package-lock.json",
            "sha256": (
                "9df758a5fef8b3d6ed33bafb2129c7f710373e261ec744516dd6d597a985796e"
            ),
            "size_bytes": 346_488,
        },
        "frontend/package.json": {
            "path": "frontend/package.json",
            "sha256": (
                "40b23bd6c3c4ed51c01d10cccc41e02575467046df23462444f5b0273b7c8c5c"
            ),
            "size_bytes": 1_522,
        },
        "pyproject.toml": {
            "path": "pyproject.toml",
            "sha256": (
                "b6c8be31b559b398be337ce2443ccd97b72dc40598431cb8c767f9bf31a02fe7"
            ),
            "size_bytes": 734,
        },
        "uv.lock": {
            "path": "uv.lock",
            "sha256": (
                "3af8f8a282f1dd631b1eeaa0b4c897ae5b83a1d7ced29e24d62b8bbdadb1b316"
            ),
            "size_bytes": 606_113,
        },
    },
    "pyproject_semantic": {
        "allowed_dev_requirement": "psutil==7.2.2",
        "current_toml_semantic_sha256": (
            "9a02539d5ac7e93c81ab5f09f902fb9840fab990bb382fce28fe9c79a0710757"
        ),
        "historical_toml_semantic_sha256": (
            "a0d11bd00d4d8d4349860328413ae856573182a8100304611c6fb24c084ac320"
        ),
        "production_dependencies_unchanged": True,
        "removing_allowed_record_reconstructs_historical_bytes": True,
        "section": "project.optional-dependencies.dev",
    },
    "runtime_import_policy": {
        "direct_app_psutil_imports": [],
        "scanner_authorization_effect": "none",
    },
    "schema_id": (
        "p03-us08-phase04-us01-dev-only-dependency-custody-bridge-v1"
    ),
    "unchanged_custody_sections": [
        "local_tools",
        "offline_environment",
        "python_packages",
        "runtime",
    ],
    "unchanged_manifest_paths": [
        "frontend/package-lock.json",
        "frontend/package.json",
    ],
    "uv_lock_semantic": {
        "allowed_root_records": [
            {
                "record": {"name": "psutil"},
                "section": (
                    "package[document-parse-api].optional-dependencies.dev"
                ),
            },
            {
                "record": {
                    "marker": "extra == 'dev'",
                    "name": "psutil",
                    "specifier": "==7.2.2",
                },
                "section": "package[document-parse-api].metadata.requires-dist",
            },
        ],
        "current_toml_semantic_sha256": (
            "aa5879a4be72e3e887a010f89eb145e9ec4519422645aa428953d479cdc96078"
        ),
        "historical_toml_semantic_sha256": (
            "8850737812725ecff0625ecd1e0b0f76d68f2f40407c9fb11dac07c8954956e1"
        ),
        "package_artifact_projection_sha256": (
            "0113789f41dc371ea589378cc166c85d11a05bbc30e8326e42f5f6d11d013f64"
        ),
        "package_count": 140,
        "preexisting_transitive_parent": {
            "dependency_record": {"name": "psutil"},
            "name": "accelerate",
            "version": "1.14.0",
        },
        "psutil_artifact_sha256": (
            "88ad59c6147332d9fb977b681c3483f2d44e2bcc8ece4c627ea37f0a3f3d8d33"
        ),
        "removing_allowed_records_reconstructs_historical_bytes": True,
        "resolved_package_set_unchanged": True,
        "root_production_dependency_projection_sha256": (
            "434266ab649ec9181fb8f72c561ae636515e2df9aa7474b18b087a187c063de6"
        ),
    },
}
WAIVER_MAXIMUM_BYTES = 64 * 1024
DECISION_MAXIMUM_BYTES = 32 * 1024
MAXIMUM_AUTHORIZED_OVERRUN_FRACTION = 0.05
EXPECTED_CODE_DIFFERENCES = (
    "tests/benchmarks/running_region_metrics.py",
    "tests/performance/test_p03_us08_running_region_metrics_contract.py",
)
EXPECTED_RENEWAL_CODE_DIFFERENCES = (
    "frontend/lib/running-regions.ts",
    "frontend/tests/p03-us08-running-regions.test.mts",
)
EXPECTED_RENEWED_COMPANION_CODE_DIFFERENCES = tuple(
    sorted((*EXPECTED_CODE_DIFFERENCES, *EXPECTED_RENEWAL_CODE_DIFFERENCES))
)
EXPECTED_RENEWAL_APPROVAL_STATEMENT = (
    "I approve renewing the P03-US08 latency exception for this frontend-only "
    "bbox compatibility fix, retaining the same 1.8935% latency exception, "
    "2026-09-02 review date, default-off rollback, and no other waivers."
)
EXPECTED_RENEWAL_FILE_IDENTITIES = {
    "frontend/lib/running-regions.ts": {
        "path": "frontend/lib/running-regions.ts",
        "sha256": (
            "1dfac1d71e34136267e2a1432261510b5785ac06a1c001da737eda27129be7af"
        ),
        "size_bytes": 50_738,
    },
    "frontend/tests/p03-us08-running-regions.test.mts": {
        "path": "frontend/tests/p03-us08-running-regions.test.mts",
        "sha256": (
            "f6ab8b7c2ebaf6a8dd2cd58febb90b0647a7223017481042e6ba7d20fbb93ffc"
        ),
        "size_bytes": 34_495,
    },
}
EXPECTED_RENEWAL_CODE_MANIFEST_SHA256 = (
    "b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc"
)
EXPECTED_PHASE04_RENEWAL_WAIVER_IDENTITY = {
    "raw_sha256": (
        "5abc6cac91184bbd515ea855f49d168c614b53299f4415a29517e38441b9e02b"
    ),
    "semantic_sha256": (
        "84e95a5992ff45df073eaab500fde1185a6fd65affb3445989c2fc7adee32675"
    ),
    "size_bytes": 6_007,
}
EXPECTED_PHASE04_RENEWAL_DECISION_IDENTITY = {
    "path": (
        "tracker/phase-03-layout/decisions/"
        "P03-US08-phase04-tables-latency-exception-renewal.md"
    ),
    "raw_sha256": (
        "951f9e2a73fecdb6fa591a807af882fec334b26d9c63fdbcee16d92b96b42aad"
    ),
    "size_bytes": 4_242,
}
EXPECTED_HARDENED_PHASE04_RENEWAL_WAIVER_IDENTITY = {
    "raw_sha256": (
        "5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655"
    ),
    "semantic_sha256": (
        "a8e38c8269e5faf1e03f5bff942dd97b74bea87f6ae26f9c6c175e50ed6eba87"
    ),
    "size_bytes": 22_113,
}
EXPECTED_HARDENED_PHASE04_RENEWAL_DECISION_IDENTITY = {
    "path": (
        "tracker/phase-03-layout/decisions/"
        "P03-US08-phase04-tables-latency-exception-hardened-renewal.md"
    ),
    "raw_sha256": (
        "bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682"
    ),
    "size_bytes": 25_343,
}
EXPECTED_SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_IDENTITY = {
    "raw_sha256": (
        "1482ceab7c557c2be73fb39e018b498b799225d8eebb8dc89548812fad81db65"
    ),
    "semantic_sha256": (
        "4c41e162cb395a7d07dce79e417c21f17f2c0ef39fd0bef8cee3f8fdb8755a61"
    ),
    "size_bytes": 47_973,
}
EXPECTED_SEMANTIC_ISOLATION_PHASE04_RENEWAL_DECISION_IDENTITY = {
    "path": (
        "tracker/phase-03-layout/decisions/"
        "P03-US08-phase04-tables-latency-exception-"
        "semantic-isolation-renewal.md"
    ),
    "raw_sha256": (
        "36e8fd988135130b995c4462d4e1edd020aa302ddf407515c05ed845d5f3f798"
    ),
    "size_bytes": 32_689,
}
EXPECTED_FAILED_PHASE04_AUDIT_IDENTITY = {
    "path": (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-phase04-tables-renewal-independent-audit.md"
    ),
    "raw_sha256": (
        "4aa0f7e8c26e2f64775a5635d1b6a367045de960222e3fcbb3e57b56e2e48e9d"
    ),
    "size_bytes": 6_082,
}
EXPECTED_HARDENED_PHASE04_RED_TEAM_IDENTITY = {
    "path": (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-phase04-tables-hardened-renewal-red-team-blocked-review.md"
    ),
    "raw_sha256": (
        "4af6a45c8b2137b16629845cd1a02475b87ccde147057b017ed460394903784c"
    ),
    "size_bytes": 3_462,
}
EXPECTED_HARDENED_PHASE04_REVIEW_02_IDENTITY = {
    "path": (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-phase04-tables-hardened-renewal-independent-review-02-blocked.md"
    ),
    "raw_sha256": (
        "81b0dbb97f52814d574928045993f18ebb62a4b38ad6669e07b5bc4830ab1b7c"
    ),
    "size_bytes": 2_416,
}
EXPECTED_PHASE04_APPROVAL_STATEMENT = (
    "I also authorize the narrow administrative renewal of the existing "
    "P03-US08 latency exception required to permit unrelated Phase 04 table "
    "changes."
)
EXPECTED_HARDENED_PHASE04_EXPIRY = {
    "expired_effect": (
        "P03-US08 returns to In Progress and dependent exit claims are blocked"
    ),
    "expires_before": [
        "production enablement",
        "running-region semantic or runtime behavior change",
        "relevant running-region custody change",
        "authorized Phase 04 scope or path expansion",
        "hardened grammar or scanner relaxation",
    ],
    "review_due_on": "2026-09-02",
}
EXPECTED_SEMANTIC_ISOLATION_PHASE04_EXPIRY = {
    **EXPECTED_HARDENED_PHASE04_EXPIRY,
    "expires_before": [
        "production enablement",
        "running-region semantic or runtime behavior change",
        "relevant running-region custody change",
        "relevant runtime dependency or lockfile custody change",
        "authorized Phase 04 scope or path expansion",
        "hardened grammar or scanner relaxation",
    ],
}
EXPECTED_PHASE04_EXISTING_PATHS = (
    "app/config.py",
    "app/services/pipeline.py",
    "app/services/tables.py",
    "frontend/app/clearleaf-workspace.tsx",
)
EXPECTED_PHASE04_ADDED_PATHS = (
    "app/services/table_semantics.py",
    "frontend/lib/table-semantics.ts",
    "frontend/tests/p04-tables.test.mts",
)
EXPECTED_HARDENED_PHASE04_ADDED_PATHS = (
    "app/services/table_semantics.py",
    "frontend/lib/table-semantics.ts",
    "frontend/tests/p04-us01-table-readiness.test.mts",
    "frontend/tests/p04-us01-table-span-fidelity.test.mts",
    "frontend/tests/p04-tables.test.mts",
)
EXPECTED_HARDENED_PHASE04_READINESS_TEST_IDENTITY = {
    "path": "frontend/tests/p04-us01-table-readiness.test.mts",
    "sha256": "ffc15e1ed0511b20a34bdead5342345b521f25e644b705806e2d9060a7d1f817",
    "size_bytes": 2_156,
}
EXPECTED_PHASE04_SETTING_NAMES = frozenset(
    {
        "table_span_fidelity_enabled",
        "table_evidence_reconciliation_enabled",
        "table_candidate_gate_enabled",
        "table_multi_page_merge_enabled",
    }
)
EXPECTED_PHASE04_PIPELINE_FUNCTIONS = frozenset(
    {
        "_analyze_shared_pages",
        "_docling_table_item",
        "_merge_body_items",
        "_merge_tables",
        "_normalize_docling_body",
        "_vector_table_item",
    }
)
EXPECTED_HARDENED_PHASE04_PIPELINE_FUNCTIONS = frozenset(
    {
        "_analyze_shared_pages",
        "_docling_table_item",
        "_merge_tables",
        "_normalize_docling_body",
        "_vector_table_item",
    }
)
EXPECTED_HARDENED_PHASE04_PIPELINE_EXACT_FUNCTIONS = frozenset(
    {"_parse_loaded_document"}
)
EXPECTED_HARDENED_PIPELINE_SIGNATURE_FLAGS = {
    "_analyze_shared_pages": frozenset(),
    "_docling_table_item": frozenset({"table_span_fidelity_enabled"}),
    "_merge_tables": frozenset(
        {
            "table_evidence_reconciliation_enabled",
            "table_span_fidelity_enabled",
        }
    ),
    "_normalize_docling_body": frozenset({"table_span_fidelity_enabled"}),
    "_vector_table_item": frozenset({"table_span_fidelity_enabled"}),
}
EXPECTED_HARDENED_PIPELINE_HELPER_CALLS = {
    "_analyze_shared_pages": {
        "gate_table_candidates": {
            "form": "assign",
            "positional_paths": (
                ("tables",),
                ("body_items",),
                ("context", "image_regions"),
                ("context", "raw_docling"),
                ("context", "source_document_identity"),
            ),
            "settings": (
                "table_span_fidelity_enabled",
                "table_evidence_reconciliation_enabled",
                "table_candidate_gate_enabled",
            ),
        },
        "merge_continued_tables": {
            "form": "expr",
            "positional_paths": (
                ("context", "pages"),
                ("context", "source_document_identity"),
            ),
            "settings": (
                "table_span_fidelity_enabled",
                "table_evidence_reconciliation_enabled",
                "table_candidate_gate_enabled",
                "table_multi_page_merge_enabled",
            ),
        },
        "seal_table_pages": {
            "form": "expr",
            "positional_paths": (
                ("context", "pages"),
                ("context", "source_document_identity"),
                ("context", "native_texts"),
            ),
            "settings": (
                "table_span_fidelity_enabled",
                "table_evidence_reconciliation_enabled",
                "table_candidate_gate_enabled",
                "table_multi_page_merge_enabled",
            ),
        },
    },
    "_docling_table_item": {
        "prepare_docling_table": {
            "form": "assign",
            "positional_paths": (("item",), ("raw_item",)),
            "settings": ("table_span_fidelity_enabled",),
        },
        "prepare_docling_table_input": {
            "form": "assign",
            "positional_paths": (
                ("raw_item",),
                ("page_heights",),
                ("page_words_by_page",),
            ),
            "settings": ("table_span_fidelity_enabled",),
        },
    },
    "_merge_tables": {
        "reconcile_table_candidates": {
            "form": "assign",
            "positional_paths": (
                ("merged",),
                ("docling_tables",),
                ("vector_tables",),
            ),
            "settings": (
                "table_span_fidelity_enabled",
                "table_evidence_reconciliation_enabled",
            ),
        },
    },
    "_normalize_docling_body": {},
    "_vector_table_item": {
        "prepare_vector_table": {
            "form": "assign",
            "positional_paths": (("item",), ("table",)),
            "settings": ("table_span_fidelity_enabled",),
        },
    },
}
EXPECTED_HARDENED_PIPELINE_FORWARDING_CALLS = {
    "_analyze_shared_pages": {
        "_merge_tables": frozenset(
            {
                "table_evidence_reconciliation_enabled",
                "table_span_fidelity_enabled",
            }
        ),
        "_normalize_docling_body": frozenset({"table_span_fidelity_enabled"}),
    },
    "_docling_table_item": {},
    "_merge_tables": {
        "_vector_table_item": frozenset({"table_span_fidelity_enabled"})
    },
    "_normalize_docling_body": {
        "_docling_table_item": frozenset({"table_span_fidelity_enabled"})
    },
    "_vector_table_item": {},
}
EXPECTED_HARDENED_PIPELINE_FUNCTION_AST_SHA256 = {
    "_analyze_shared_pages": (
        "945801e819f0e17c3fcd560ce724747733e824322f613a05093f61fc46437454"
    ),
    "_docling_table_item": (
        "b1130f3359567d58ef1144ea02a616ef83f7d9b6915ce1316441d344ea38da6b"
    ),
    "_merge_tables": (
        "95d79f23a98a54b1cb9b90c697c17d504f97c04bc0a650c65db2fc7199205849"
    ),
    "_normalize_docling_body": (
        "072cb98250b39b37b307d9db016130b38b5dcbd10cb16e8fae914cdbd0d01a9d"
    ),
    "_vector_table_item": (
        "dad67619729d8910f21681a7e81c7b0a7a170f9a96a86106402047b500fd44ce"
    ),
}
EXPECTED_HARDENED_PIPELINE_MODULE_AST_SHA256 = (
    "c213dad6f3c7474674ad68878586dd7c78f86843b4aa2de44d38e7410f7194f7"
)
# Exact reviewed final P04-US01 pipeline AST.  This candidate-specific pair is
# additive to the sealed predecessor and authorizes no future syntax.
EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_FUNCTION_AST_SHA256: dict[
    str, str
] = {
    "_analyze_shared_pages": (
        "e334454e5131c017439166abbf0ed117c4940eac0982b779ad29ebacdcc95d14"
    ),
    "_docling_table_item": (
        "a3dd4e138bdf69176f7751791e4e6ce34a4373eb63d04a2797b3a4ad75db8d0d"
    ),
    "_merge_tables": (
        "019b78d522665d1c10a13de11c0b93f8b87f2e002e99a54f19b48a91678cf338"
    ),
    "_normalize_docling_body": (
        "bc74e26b1249c78e7829eb38e9beeab2c15f9c5a3e737357ebe399f7beced43d"
    ),
    "_vector_table_item": (
        "721ccfe574bb24d9afe42d4f1a44e7eb2a4ba2e4ff3d571908dde5fd4a13eb76"
    ),
}
EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_MODULE_AST_SHA256 = (
    "9ccb2276ed46dcf1975d7a654e927ba675a1b18a4d3ed45b2387f08090365798"
)
EXPECTED_HARDENED_PIPELINE_VECTOR_BASELINE_TRY_SOURCE = (
    "try:\n"
    "    vector_tables = (\n"
    "        extract_vector_tables(loaded.processing_bytes)\n"
    "        if loaded.kind is InputKind.PDF\n"
    "        else {}\n"
    "    )\n"
    "except Exception as exc:\n"
    "    vector_tables = {}\n"
    "    processing_warnings.append(\n"
    "        f\"Supplemental vector table extraction failed: "
    "{type(exc).__name__}.\"\n"
    "    )\n"
)
EXPECTED_HARDENED_PIPELINE_VECTOR_GEOMETRY_TRY_SOURCE = (
    "try:\n"
    "    vector_tables = (\n"
    "        (\n"
    "            extract_vector_tables(\n"
    "                loaded.processing_bytes,\n"
    "                preserve_cell_geometry=True,\n"
    "            )\n"
    "            if settings.table_span_fidelity_enabled\n"
    "            else extract_vector_tables(loaded.processing_bytes)\n"
    "        )\n"
    "        if loaded.kind is InputKind.PDF\n"
    "        else {}\n"
    "    )\n"
    "except Exception as exc:\n"
    "    vector_tables = {}\n"
    "    processing_warnings.append(\n"
    "        f\"Supplemental vector table extraction failed: "
    "{type(exc).__name__}.\"\n"
    "    )\n"
)
EXPECTED_HARDENED_PIPELINE_VECTOR_BASELINE_TRY_AST_SHA256 = (
    "4c53a0a571ca739bd9e9f55aa2a4004e744aaf243fb90e191e4a318ad8b5dc0c"
)
EXPECTED_HARDENED_PIPELINE_VECTOR_GEOMETRY_TRY_AST_SHA256 = (
    "dc4e92d5e81d80feed41f2c5a2885c1c1ecd3445a6e8d1896518946851909335"
)
EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_PAGE_INDEX_SOURCE = '''def _table_repair_page_indexes(
    raw: Mapping[str, Any],
) -> set[int]:
    page_indexes: set[int] = set()
    for table in raw.get("tables") or []:
        if not isinstance(table, Mapping):
            continue
        cells_by_row: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        for cell in (table.get("data") or {}).get("table_cells") or []:
            if isinstance(cell, Mapping):
                cells_by_row[int(cell.get("start_row_offset_idx") or 0)].append(cell)
        has_mixed_row = any(
            any(bool(cell.get("column_header")) for cell in row_cells)
            and any(not bool(cell.get("column_header")) for cell in row_cells)
            for row_cells in cells_by_row.values()
        )
        if not has_mixed_row:
            continue
        provenance = table.get("prov") or []
        if not provenance:
            continue
        try:
            page_indexes.add(int(provenance[0].get("page_no") or 1))
        except (AttributeError, TypeError, ValueError):
            continue
    return page_indexes
'''
EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_EXTRACT_SOURCE = '''def _extract_table_repair_words(
    pdf_bytes: bytes,
    raw: Mapping[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    """Extract word geometry only for pages with a potentially mixed row."""

    page_indexes = _table_repair_page_indexes(raw)
    if not page_indexes:
        return {}

    import pdfplumber

    words_by_page: dict[int, list[dict[str, Any]]] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        for page_index in sorted(page_indexes):
            if not 1 <= page_index <= len(document.pages):
                continue
            words = document.pages[page_index - 1].extract_words(
                x_tolerance=2,
                y_tolerance=2,
                keep_blank_chars=False,
                use_text_flow=False,
            )
            words_by_page[page_index] = [
                {
                    "text": str(word.get("text") or ""),
                    "x0": float(word["x0"]),
                    "x1": float(word["x1"]),
                    "top": float(word["top"]),
                    "bottom": float(word["bottom"]),
                }
                for word in words
                if str(word.get("text") or "").strip()
            ]
    return words_by_page
'''
EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_TRY_SOURCE = (
    "try:\n"
    "    table_repair_words = (\n"
    "        _extract_table_repair_words(\n"
    "            loaded.processing_bytes,\n"
    "            raw_docling,\n"
    "        )\n"
    "        if loaded.kind is InputKind.PDF\n"
    "        else {}\n"
    "    )\n"
    "except Exception as exc:\n"
    "    table_repair_words = {}\n"
    "    processing_warnings.append(\n"
    "        f\"Table word-geometry repair was unavailable: "
    "{type(exc).__name__}.\"\n"
    "    )\n"
)
EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_TRY_SOURCE = (
    "try:\n"
    "    table_repair_words = (\n"
    "        _extract_table_repair_words(\n"
    "            loaded.processing_bytes,\n"
    "            raw_docling,\n"
    "            table_span_fidelity_enabled="
    "settings.table_span_fidelity_enabled,\n"
    "        )\n"
    "        if loaded.kind is InputKind.PDF\n"
    "        else {}\n"
    "    )\n"
    "except Exception as exc:\n"
    "    table_repair_words = {}\n"
    "    processing_warnings.append(\n"
    "        f\"Table word-geometry repair was unavailable: "
    "{type(exc).__name__}.\"\n"
    "    )\n"
)
EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_AST_SHA256 = {
    "_table_repair_page_indexes": (
        "a385d83f123b7ec08e8abc6cabb65383388a8441826053032220d250e90fc0ea"
    ),
    "_extract_table_repair_words": (
        "7e4f2a92912be80d1f48b734030a2e5943b36e94d1f2d7320566f395e13087d2"
    ),
    "_parse_loaded_document.table_repair_words": (
        "6f6bb7e8f9441b37a098e647c7822e65d6f73ea586fa4f613a371ba984750c29"
    ),
}
EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_AST_SHA256 = {
    "_table_repair_page_indexes": (
        "34f041477ed512904fd07dcb83bc40b2f9f881d4e60c0a69b4c42bb0a1df78f7"
    ),
    "_extract_table_repair_words": (
        "ae612114c5c64d9781267748a957b87615965b54843be534263f1bd84af5cbf5"
    ),
    "_parse_loaded_document.table_repair_words": (
        "b64e9e17c9c30631a5e29f11691154dc4ab133d49b79fbde811cb447c758b1e9"
    ),
}
# The independently sealed candidate vector above remains immutable.  P04-US01
# additionally needs native typography reduced to a bounded boolean before the
# first table story can preserve independently supported header ownership.  The
# second additive vector is atomic and is normalized to the same predecessor;
# mixed states remain invalid.
EXPECTED_SECOND_ADDITIVE_PIPELINE_TABLE_REPAIR_AST_SHA256 = {
    "_table_repair_page_indexes": (
        "34f041477ed512904fd07dcb83bc40b2f9f881d4e60c0a69b4c42bb0a1df78f7"
    ),
    "_extract_table_repair_words": (
        "cd9e83111c3fe398727d9d913f431b9ee0dbf0b8c89ad2315fb09e5520133b38"
    ),
    "_parse_loaded_document.table_repair_words": (
        "b64e9e17c9c30631a5e29f11691154dc4ab133d49b79fbde811cb447c758b1e9"
    ),
}
EXPECTED_HARDENED_SOURCE_ALIGNMENT_IDENTITY = {
    "path": "app/services/source_text_alignment.py",
    "sha256": "8294ca5258db5f8dfb6d70f87e4ccefc132bb3b60eb6c979490533758d62976b",
    "size_bytes": 137_284,
}
EXPECTED_HARDENED_SOURCE_ALIGNMENT_MODULE_AST_SHA256 = (
    "c907b27fdd3f57839b15e102e9cdfb17250615267072fad9e5135687a7bf43ba"
)
EXPECTED_HARDENED_SOURCE_ALIGNMENT_REFRESH_AST_SHA256 = (
    "a150d4d3451ec3863d0c09359df388762fe946b9ebacb3bef8331c5b0732cabf"
)
EXPECTED_HARDENED_SOURCE_ALIGNMENT_HOOK = (
    '    table_evidence = table.get("table_evidence")\n'
    "    if isinstance(table_evidence, Mapping):\n"
    "        from app.services.table_semantics import replay_table_semantics\n"
    "\n"
    "        replay_table_semantics(table, table_evidence)\n"
)
EXPECTED_HARDENED_TEXT_RECONCILIATION_IDENTITY = {
    "path": "app/services/text_reconciliation.py",
    "sha256": "58d2d3275827d10681b0075d8c6572ca56a290a249276fec27c138245ae9b479",
    "size_bytes": 179_657,
}
EXPECTED_HARDENED_TEXT_RECONCILIATION_MODULE_AST_SHA256 = (
    "b532f37de146ccf0c37f6e32e847c97d4885f3535e27351c2ac1f15ffbe942e9"
)
EXPECTED_HARDENED_TEXT_RECONCILIATION_FUNCTION_AST_SHA256 = (
    "98fa8019f38a0ed189a4aec1c5e27adcd6bd9cd0ac453fff6a44281c5f35947d"
)
EXPECTED_HARDENED_TEXT_RECONCILIATION_HOOK = (
    '    legacy = owner.properties.get("legacy_item")\n'
    "    if isinstance(legacy, Mapping) and isinstance(\n"
    '        legacy.get("table_evidence"), Mapping\n'
    "    ):\n"
    "        from app.services.table_semantics import replace_marked_table_text\n"
    "\n"
    "        replace_marked_table_text(\n"
    "            owner,\n"
    "            selected_text=selected_text,\n"
    "            replacement_mode=replacement_mode,\n"
    "            original_text=original_text,\n"
    "        )\n"
    "        return\n"
)
EXPECTED_HARDENED_PHASE04_SETTING_ORDER = (
    "table_span_fidelity_enabled",
    "table_evidence_reconciliation_enabled",
    "table_candidate_gate_enabled",
    "table_multi_page_merge_enabled",
)
EXPECTED_HARDENED_PHASE04_SETTING_NAMES = frozenset(
    EXPECTED_HARDENED_PHASE04_SETTING_ORDER
)
EXPECTED_HARDENED_EXISTING_PATHS = (
    ".env.example",
    "app/config.py",
    "app/services/pipeline.py",
    "app/services/source_text_alignment.py",
    "app/services/tables.py",
    "app/services/text_reconciliation.py",
    "frontend/app/clearleaf-workspace.tsx",
    "tests/performance/test_p03_us08_running_region_metrics_contract.py",
)
EXPECTED_HARDENED_SEALED_PATHS: dict[str, dict[str, Any]] = {}
EXPECTED_HARDENED_METRICS_CONTRACT_BASELINE_IDENTITY = {
    "path": "tests/performance/test_p03_us08_running_region_metrics_contract.py",
    "sha256": "3604bf403b900970414ce8cc86d40bf806958cb0b1cb2d17e776ee404c2b408e",
    "size_bytes": 162_944,
}
EXPECTED_HARDENED_METRICS_CONTRACT_CANDIDATE_IDENTITY = {
    "path": "tests/performance/test_p03_us08_running_region_metrics_contract.py",
    "sha256": "3862f5d386f0bf4440da646d1cc7603dedb7f14cf694d275da49a6d9d0c97e75",
    "size_bytes": 165_157,
}
EXPECTED_HARDENED_ENV_EXAMPLE_IDENTITY = {
    "path": ".env.example",
    "sha256": "75025300b1c04355bde352327dae7352461991c09fc5b3c05908dafa1cb6e886",
    "size_bytes": 4_696,
}
EXPECTED_HARDENED_ENV_EXAMPLE_PHASE04_SUFFIX = (
    "PARSER_TABLES_SPAN_FIDELITY_ENABLED=false\n"
    "PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED=false\n"
    "PARSER_TABLES_CANDIDATE_GATE_ENABLED=false\n"
    "PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED=false\n"
)
EXPECTED_HARDENED_TABLES_ALLOWED_NODES = (
    "RawTable",
    "_clean_table",
    "_page_candidates",
    "extract_vector_tables",
)
EXPECTED_HARDENED_TABLES_BASELINE_IDENTITY = {
    "path": "app/services/tables.py",
    "sha256": "dc889c00eea03ee3506093c6e806966e16f76f02ff941e6476e61c32545d0d42",
    "size_bytes": 18_319,
}
EXPECTED_HARDENED_TABLES_RETAINED_MODULE_AST_SHA256 = (
    "d7caf061838240af598fcb2f91108410324d776d2a9a5fe22718402c65638372"
)
EXPECTED_HARDENED_TABLES_BASELINE_NODE_AST_SHA256 = {
    "RawTable": "a2f2ccec51154c76644cb370b79950cf6ad67f64c4ac0b53e57c9d92a0dd8ead",
    "_clean_table": "38ca877fb4ab0a6192c86dd478065a6eb7349bbc34e8f6561f85329f78085c39",
    "_page_candidates": "df82e25d10e8dd676a8243f4da922ba8a37002ecb6053dfed0e8a24118ce30a2",
    "extract_vector_tables": (
        "db346da36f00e93a1c7cfabb75e11407d2a9988c56f6a3ba6d9c5303c817d525"
    ),
}
# Filled from the independently reviewable in-memory candidate constructed by
# the hardened renewal tests.  The complete vector is atomic: mixed baseline
# and candidate nodes are never accepted.
EXPECTED_HARDENED_TABLES_GEOMETRY_NODE_AST_SHA256 = {
    "RawTable": "0dafc1586a131a11131db4e0894ea61caa732c522a37c6f48defc57173fd21c8",
    "_clean_table": "9932b9fe544463ad1f445440f28469706b10eb6b1f665cd876727e5543804adf",
    "_page_candidates": "0b66c2f7d400731baca041eb1c8ffd8bf8d63f424706647f289035b3218a5624",
    "extract_vector_tables": (
        "e916c77211e82794ff99c6577821bd32921c4aaca0b642a7a3fac230febbfe00"
    ),
}
EXPECTED_TABLE_SEMANTICS_IMPORTS = {
    "__future__": ("annotations",),
    "app.services.tables": ("RawTable",),
    "collections": ("defaultdict",),
    "collections.abc": ("Mapping", "Sequence"),
    "copy": ("deepcopy",),
    "csv": ("writer",),
    "decimal": ("Decimal", "InvalidOperation"),
    "io": ("StringIO",),
    "hashlib": ("sha256",),
    "html": ("escape",),
    "json": ("dumps",),
    "math": ("isfinite",),
    "re": ("fullmatch", "search", "sub"),
    "time": ("perf_counter",),
    "typing": ("Any", "Final", "Literal", "TypeAlias", "TypeGuard", "cast"),
    "unicodedata": ("normalize",),
}
EXPECTED_TABLE_SEMANTICS_STDLIB_ROOTS = frozenset(
    module.split(".", 1)[0]
    for module in EXPECTED_TABLE_SEMANTICS_IMPORTS
    if not module.startswith("app.")
)
EXPECTED_TABLE_SEMANTICS_CALLABLE_IMPORTS = frozenset(
    {
        "Decimal",
        "InvalidOperation",
        "StringIO",
        "cast",
        "defaultdict",
        "deepcopy",
        "dumps",
        "escape",
        "fullmatch",
        "isfinite",
        "normalize",
        "perf_counter",
        "search",
        "sha256",
        "sub",
        "writer",
    }
)
EXPECTED_TABLE_SEMANTICS_SAFE_BUILTIN_CALLS = frozenset(
    {
        "ArithmeticError",
        "AssertionError",
        "KeyError",
        "RuntimeError",
        "TimeoutError",
        "TypeError",
        "ValueError",
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "dict",
        "enumerate",
        "float",
        "id",
        "int",
        "isinstance",
        "len",
        "list",
        "max",
        "min",
        "range",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
        "zip",
    }
)
EXPECTED_TABLE_SEMANTICS_DIAGNOSTIC_EXCEPTIONS = frozenset(
    {
        "ArithmeticError",
        "AssertionError",
        "KeyError",
        "RuntimeError",
        "TimeoutError",
        "TypeError",
        "ValueError",
    }
)
EXPECTED_TABLE_SEMANTICS_SAFE_METHOD_CALLS = frozenset(
    {
        "add",
        "append",
        "bit_length",
        "casefold",
        "decode",
        "digest",
        "encode",
        "endswith",
        "get",
        "getvalue",
        "hexdigest",
        "items",
        "join",
        "keys",
        "pop",
        "replace",
        "setdefault",
        "sort",
        "split",
        "splitlines",
        "startswith",
        "strip",
        "values",
        "writerow",
    }
)
FORBIDDEN_TABLE_SEMANTICS_BULK_METHODS = frozenset(
    {"extend", "update", "write", "writerows"}
)
FORBIDDEN_TABLE_SEMANTICS_UNBOUNDED_GROWING_METHODS = frozenset(
    {"add", "setdefault", "writerow"}
)
FORBIDDEN_TABLE_SEMANTICS_NONFROZEN_RESOURCE_CALLS = frozenset(
    {"deepcopy", "dumps", "sha256"}
)
FORBIDDEN_TABLE_SEMANTICS_LOOP_RESOURCE_CALLS = frozenset(
    {
        "StringIO",
        "_batch_table_sha256",
        "_assert_canonical_table_json",
        "_assert_plain_table_value",
        "_assert_source_sha256",
        "_bounded_table_sha256",
        "_canonical_table_json_bytes",
        "_canonical_table_sha256",
        "_copy_raw_table_graph",
        "_copy_table_mapping",
        "_plain_table_length",
        "_validate_plain_table_value",
        "dict",
        "set",
        "sorted",
    }
)
EXPECTED_TABLE_SEMANTICS_DEADLINE_ARGUMENT_INDEX = {
    "_batch_table_sha256": 2,
    "_assert_canonical_table_json": 2,
    "_assert_plain_table_value": 1,
    "_assert_source_sha256": 1,
    "_bounded_table_sha256": 2,
    "_canonical_table_json_bytes": 2,
    "_canonical_table_sha256": 2,
    "_check_table_deadline": 0,
    "_copy_raw_table_graph": 1,
    "_copy_table_mapping": 1,
    "_plain_table_length": 1,
    "_validate_plain_table_value": 1,
}
EXPECTED_TABLE_SEMANTICS_BOUNDED_ITERABLE_SOURCE = (
    "def _bounded_table_iterable(value, limit):\n"
    "    if type(limit) is not int or limit < 0 or limit > 65536:\n"
    "        raise ValueError(\"invalid table iteration limit\")\n"
    "    if type(value) not in (dict, list, range, tuple):\n"
    "        raise TypeError(\"table iteration input must be bounded\")\n"
    "    if len(value) > limit:\n"
    "        raise ValueError(\"table iteration limit exceeded\")\n"
    "    return tuple(value)\n"
)
EXPECTED_TABLE_SEMANTICS_BOUNDED_TEXT_SOURCE = (
    "def _bounded_table_text(value):\n"
    "    if type(value) is not str:\n"
    "        raise TypeError(\"table regex input must be exact text\")\n"
    "    try:\n"
    "        encoded = value.encode(\"utf-8\")\n"
    "    except UnicodeEncodeError:\n"
    "        raise ValueError(\"table text must be valid UTF-8\") from None\n"
    "    if len(encoded) > 65536:\n"
    "        raise ValueError(\"table regex input limit exceeded\")\n"
    "    return value\n"
)
EXPECTED_TABLE_SEMANTICS_DEADLINE_CHECK_SOURCE = (
    "def _check_table_deadline(deadline):\n"
    "    if type(deadline) not in (int, float) or not isfinite(float(deadline)):\n"
    "        raise ValueError(\"invalid table deadline\")\n"
    "    if perf_counter() > float(deadline):\n"
    "        raise TimeoutError(\"table operation deadline exceeded\")\n"
)
EXPECTED_TABLE_SEMANTICS_PLAIN_ASSERT_SOURCE = (
    "def _assert_plain_table_value(value, deadline, json_only=False):\n"
    "    if type(json_only) is not bool:\n"
    "        raise TypeError(\"invalid JSON-only table policy\")\n"
    "    _check_table_deadline(deadline)\n"
    "    pending = [(value, 0, False)]\n"
    "    active = {}\n"
    "    node_count = 0\n"
    "    aggregate_bytes = 0\n"
    "    for _chunk_index in _bounded_table_iterable(range(128), 128):\n"
    "        _check_table_deadline(deadline)\n"
    "        for _node_index in _bounded_table_iterable(range(65536), 65536):\n"
    "            _check_table_deadline(deadline)\n"
    "            if not pending:\n"
    "                return value\n"
    "            current, depth, leaving = pending.pop()\n"
    "            if leaving:\n"
    "                identity = id(current)\n"
    "                active.pop(identity)\n"
    "                continue\n"
    "            node_count += 1\n"
    "            if node_count > 4194304:\n"
    "                raise ValueError(\"table node limit exceeded\")\n"
    "            current_type = type(current)\n"
    "            if current is None or current_type is bool:\n"
    "                aggregate_bytes += 16\n"
    "                if aggregate_bytes > 67108864:\n"
    "                    raise ValueError(\"table aggregate byte limit exceeded\")\n"
    "                continue\n"
    "            if current_type is int:\n"
    "                aggregate_bytes += 32 + (current.bit_length() + 7) // 8\n"
    "                if aggregate_bytes > 67108864:\n"
    "                    raise ValueError(\"table aggregate byte limit exceeded\")\n"
    "                continue\n"
    "            if current_type is float:\n"
    "                if not isfinite(current):\n"
    "                    raise ValueError(\"non-finite table value\")\n"
    "                aggregate_bytes += 32\n"
    "                if aggregate_bytes > 67108864:\n"
    "                    raise ValueError(\"table aggregate byte limit exceeded\")\n"
    "                continue\n"
    "            if current_type is str:\n"
    "                try:\n"
    "                    encoded = current.encode(\"utf-8\")\n"
    "                except UnicodeEncodeError:\n"
    "                    raise ValueError(\"table text must be valid UTF-8\") from None\n"
    "                if len(encoded) > 1048576:\n"
    "                    raise ValueError(\"table string limit exceeded\")\n"
    "                aggregate_bytes += 64 + len(encoded)\n"
    "                if aggregate_bytes > 67108864:\n"
    "                    raise ValueError(\"table aggregate byte limit exceeded\")\n"
    "                continue\n"
    "            if current_type is bytes:\n"
    "                if json_only:\n"
    "                    raise TypeError(\"canonical table JSON must not contain bytes\")\n"
    "                if len(current) > 1048576:\n"
    "                    raise ValueError(\"table string limit exceeded\")\n"
    "                aggregate_bytes += 64 + len(current)\n"
    "                if aggregate_bytes > 67108864:\n"
    "                    raise ValueError(\"table aggregate byte limit exceeded\")\n"
    "                continue\n"
    "            if current_type not in (dict, list, tuple):\n"
    "                raise TypeError(\"table value must be exact plain data\")\n"
    "            if json_only and current_type is tuple:\n"
    "                raise TypeError(\"canonical table JSON must use lists\")\n"
    "            if depth >= 32:\n"
    "                raise ValueError(\"table nesting limit exceeded\")\n"
    "            identity = id(current)\n"
    "            if identity in active:\n"
    "                raise ValueError(\"cyclic table value\")\n"
    "            active[identity] = True\n"
    "            container_limit = 4096 if current_type is dict else 65536\n"
    "            if len(current) > container_limit:\n"
    "                raise ValueError(\"table container limit exceeded\")\n"
    "            aggregate_bytes += 64 + len(current) * (\n"
    "                32 if current_type is dict else 16\n"
    "            )\n"
    "            if aggregate_bytes > 67108864:\n"
    "                raise ValueError(\"table aggregate byte limit exceeded\")\n"
    "            pending.append((current, depth, True))\n"
    "            if current_type is dict:\n"
    "                entries = tuple(current.items())\n"
    "                aggregate_bytes += 64 + len(entries) * 16\n"
    "                if aggregate_bytes > 67108864:\n"
    "                    raise ValueError(\"table aggregate byte limit exceeded\")\n"
    "                for entry in _bounded_table_iterable(entries, 4096):\n"
    "                    _check_table_deadline(deadline)\n"
    "                    key, item = entry\n"
    "                    if json_only and type(key) is not str:\n"
    "                        raise TypeError(\"canonical table JSON keys must be text\")\n"
    "                    pending.append((key, depth + 1, False))\n"
    "                    pending.append((item, depth + 1, False))\n"
    "            else:\n"
    "                for item in _bounded_table_iterable(current, 65536):\n"
    "                    _check_table_deadline(deadline)\n"
    "                    pending.append((item, depth + 1, False))\n"
    "    raise ValueError(\"table traversal limit exceeded\")\n"
)
EXPECTED_TABLE_SEMANTICS_PLAIN_VALUE_SOURCE = (
    "def _validate_plain_table_value(value, deadline):\n"
    "    _assert_plain_table_value(value, deadline)\n"
    "    _check_table_deadline(deadline)\n"
    "    return deepcopy(value)\n"
)
EXPECTED_TABLE_SEMANTICS_MAPPING_COPY_SOURCE = (
    "def _copy_table_mapping(value, deadline):\n"
    "    if type(value) not in (dict, defaultdict):\n"
    "        raise TypeError(\"table mapping must be exact dict/defaultdict\")\n"
    "    _check_table_deadline(deadline)\n"
    "    entries = tuple(value.items())\n"
    "    if len(entries) > 4096:\n"
    "        raise ValueError(\"table mapping limit exceeded\")\n"
    "    copied = {}\n"
    "    for entry in _bounded_table_iterable(entries, 4096):\n"
    "        _check_table_deadline(deadline)\n"
    "        key, item = entry\n"
    "        _assert_plain_table_value(key, deadline)\n"
    "        _assert_plain_table_value(item, deadline)\n"
    "        copied[key] = item\n"
    "    return _validate_plain_table_value(copied, deadline)\n"
)
EXPECTED_TABLE_SEMANTICS_RAW_TABLE_GRAPH_SOURCE = (
    "def _copy_raw_table_graph(vector_tables, deadline):\n"
    "    if type(vector_tables) not in (dict, defaultdict):\n"
    "        raise TypeError(\"vector table graph must be exact dict/defaultdict\")\n"
    "    _check_table_deadline(deadline)\n"
    "    page_entries = tuple(vector_tables.items())\n"
    "    if len(page_entries) > 4096:\n"
    "        raise ValueError(\"vector table page limit exceeded\")\n"
    "    copied = {}\n"
    "    candidate_count = 0\n"
    "    for page_entry in _bounded_table_iterable(page_entries, 4096):\n"
    "        _check_table_deadline(deadline)\n"
    "        page_index, raw_tables = page_entry\n"
    "        if type(page_index) is not int or page_index < 1:\n"
    "            raise TypeError(\"vector table page index differs\")\n"
    "        if type(raw_tables) is not list:\n"
    "            raise TypeError(\"vector table candidates must be exact list\")\n"
    "        candidate_count = candidate_count + len(raw_tables)\n"
    "        if candidate_count > 65536:\n"
    "            raise ValueError(\"vector table candidate limit exceeded\")\n"
    "    for page_entry in _bounded_table_iterable(page_entries, 4096):\n"
    "        _check_table_deadline(deadline)\n"
    "        page_index, raw_tables = page_entry\n"
    "        copied_candidates = []\n"
    "        for raw_table in _bounded_table_iterable(raw_tables, 4096):\n"
    "            _check_table_deadline(deadline)\n"
    "            if type(raw_table) is RawTable:\n"
    "                candidate = _validate_plain_table_value(\n"
    "                    {\n"
    "                        \"page_index\": raw_table.page_index,\n"
    "                        \"bbox\": raw_table.bbox,\n"
    "                        \"rows\": raw_table.rows,\n"
    "                        \"row_bboxes\": raw_table.row_bboxes,\n"
    "                        \"parse_concerns\": raw_table.parse_concerns,\n"
    "                        \"cell_bboxes\": raw_table.cell_bboxes,\n"
    "                        \"geometry_inferred\": raw_table.geometry_inferred,\n"
    "                    },\n"
    "                    deadline,\n"
    "                )\n"
    "            elif type(raw_table) in (dict, defaultdict):\n"
    "                candidate = _copy_table_mapping(raw_table, deadline)\n"
    "                candidate_keys = set(candidate)\n"
    "                predecessor_keys = {\n"
    "                    \"page_index\", \"bbox\", \"rows\", \"row_bboxes\",\n"
    "                    \"parse_concerns\",\n"
    "                }\n"
    "                geometry_keys = predecessor_keys | {\n"
    "                    \"cell_bboxes\", \"geometry_inferred\",\n"
    "                }\n"
    "                if candidate_keys == predecessor_keys:\n"
    "                    candidate[\"cell_bboxes\"] = ()\n"
    "                    candidate[\"geometry_inferred\"] = None\n"
    "                elif candidate_keys != geometry_keys:\n"
    "                    raise ValueError(\"raw table mapping fields differ\")\n"
    "            else:\n"
    "                raise TypeError(\"raw table candidate type differs\")\n"
    "            copied_candidates.append(candidate)\n"
    "        copied[page_index] = copied_candidates\n"
    "    _assert_plain_table_value(copied, deadline)\n"
    "    return copied\n"
)
EXPECTED_TABLE_SEMANTICS_SOURCE_SHA_SOURCE = (
    "def _assert_source_sha256(value, deadline):\n"
    "    _check_table_deadline(deadline)\n"
    "    if (\n"
    "        type(value) is not str\n"
    "        or len(value) != 64\n"
    "        or fullmatch(r\"[0-9a-f]{64}\", value) is None\n"
    "    ):\n"
    "        raise ValueError(\"source SHA-256 differs\")\n"
    "    return value\n"
)
EXPECTED_TABLE_SEMANTICS_CANONICAL_JSON_SOURCE = (
    "def _canonical_table_json_bytes(value, maximum_bytes, deadline):\n"
    "    if type(maximum_bytes) is not int or maximum_bytes not in (8388608, 67108864):\n"
    "        raise ValueError(\"canonical table JSON limit differs\")\n"
    "    _assert_plain_table_value(value, deadline, True)\n"
    "    _check_table_deadline(deadline)\n"
    "    try:\n"
    "        canonical = dumps(\n"
    "            value,\n"
    "            allow_nan=False,\n"
    "            ensure_ascii=False,\n"
    "            separators=(\",\", \":\"),\n"
    "            sort_keys=True,\n"
    "        )\n"
    "    except (TypeError, ValueError):\n"
    "        raise ValueError(\"canonical table JSON serialization failed\") from None\n"
    "    _check_table_deadline(deadline)\n"
    "    try:\n"
    "        encoded = canonical.encode(\"utf-8\")\n"
    "    except UnicodeEncodeError:\n"
    "        raise ValueError(\"canonical table JSON must be valid UTF-8\") from None\n"
    "    if len(encoded) > maximum_bytes:\n"
    "        raise ValueError(\"canonical table JSON limit exceeded\")\n"
    "    _check_table_deadline(deadline)\n"
    "    return encoded\n"
)
EXPECTED_TABLE_SEMANTICS_BOUNDED_SHA_SOURCE = (
    "def _bounded_table_sha256(value, maximum_bytes, deadline):\n"
    "    if type(maximum_bytes) is not int or maximum_bytes not in (8388608, 67108864):\n"
    "        raise ValueError(\"table SHA-256 limit differs\")\n"
    "    if type(value) is not bytes:\n"
    "        raise TypeError(\"table SHA-256 input must be exact bytes\")\n"
    "    if len(value) > maximum_bytes:\n"
    "        raise ValueError(\"table SHA-256 input limit exceeded\")\n"
    "    _check_table_deadline(deadline)\n"
    "    digest = sha256(value).hexdigest()\n"
    "    _check_table_deadline(deadline)\n"
    "    return digest\n"
)
EXPECTED_TABLE_SEMANTICS_CANONICAL_SHA_SOURCE = (
    "def _canonical_table_sha256(value, maximum_bytes, deadline):\n"
    "    encoded = _canonical_table_json_bytes(value, maximum_bytes, deadline)\n"
    "    return _bounded_table_sha256(encoded, maximum_bytes, deadline)\n"
)
EXPECTED_TABLE_SEMANTICS_BATCH_SHA_SOURCE = (
    "def _batch_table_sha256(values, maximum_bytes, deadline):\n"
    "    if type(maximum_bytes) is not int or maximum_bytes not in (8388608, 67108864):\n"
    "        raise ValueError(\"table batch SHA-256 limit differs\")\n"
    "    if type(values) is not list:\n"
    "        raise TypeError(\"table batch SHA-256 input must be exact list\")\n"
    "    if len(values) > 65536:\n"
    "        raise ValueError(\"table batch SHA-256 count exceeded\")\n"
    "    _assert_plain_table_value(values, deadline, True)\n"
    "    total_bytes = 0\n"
    "    digests = []\n"
    "    for value in _bounded_table_iterable(values, 65536):\n"
    "        _check_table_deadline(deadline)\n"
    "        try:\n"
    "            canonical = dumps(\n"
    "                value,\n"
    "                allow_nan=False,\n"
    "                ensure_ascii=False,\n"
    "                separators=(\",\", \":\"),\n"
    "                sort_keys=True,\n"
    "            )\n"
    "        except (TypeError, ValueError):\n"
    "            raise ValueError(\n"
    "                \"table batch SHA-256 serialization failed\"\n"
    "            ) from None\n"
    "        _check_table_deadline(deadline)\n"
    "        try:\n"
    "            encoded = canonical.encode(\"utf-8\")\n"
    "        except UnicodeEncodeError:\n"
    "            raise ValueError(\n"
    "                \"table batch SHA-256 must be valid UTF-8\"\n"
    "            ) from None\n"
    "        total_bytes += len(encoded)\n"
    "        if total_bytes > maximum_bytes:\n"
    "            raise ValueError(\n"
    "                \"table batch SHA-256 aggregate limit exceeded\"\n"
    "            )\n"
    "        digest = _bounded_table_sha256(\n"
    "            encoded, maximum_bytes, deadline\n"
    "        )\n"
    "        digests.append(digest)\n"
    "    _check_table_deadline(deadline)\n"
    "    return digests\n"
)
EXPECTED_TABLE_SEMANTICS_CANONICAL_ASSERT_SOURCE = (
    "def _assert_canonical_table_json(value, maximum_bytes, deadline):\n"
    "    _canonical_table_json_bytes(value, maximum_bytes, deadline)\n"
    "    return None\n"
)
EXPECTED_TABLE_SEMANTICS_PLAIN_LENGTH_SOURCE = (
    "def _plain_table_length(value, deadline):\n"
    "    _assert_plain_table_value(value, deadline)\n"
    "    if type(value) not in (bytes, dict, list, str, tuple):\n"
    "        raise TypeError(\"table length input differs\")\n"
    "    return len(value)\n"
)
EXPECTED_TABLE_SEMANTICS_PUBLIC_SIGNATURES = {
    "prepare_docling_table_input": {
        "positional": ("raw_item", "page_heights", "page_words_by_page"),
        "keyword_only": ("table_span_fidelity_enabled",),
        "required_keyword_only": (),
    },
    "prepare_docling_table": {
        "positional": ("item", "raw_item"),
        "keyword_only": ("table_span_fidelity_enabled",),
        "required_keyword_only": (),
    },
    "prepare_vector_table": {
        "positional": ("item", "raw_table"),
        "keyword_only": ("table_span_fidelity_enabled",),
        "required_keyword_only": (),
    },
    "reconcile_table_candidates": {
        "positional": ("merged", "docling_tables", "vector_tables"),
        "keyword_only": (
            "table_span_fidelity_enabled",
            "table_evidence_reconciliation_enabled",
        ),
        "required_keyword_only": (),
    },
    "gate_table_candidates": {
        "positional": (
            "tables",
            "body_items",
            "image_regions",
            "raw_docling",
            "source_document_identity",
        ),
        "keyword_only": (
            "table_span_fidelity_enabled",
            "table_evidence_reconciliation_enabled",
            "table_candidate_gate_enabled",
        ),
        "required_keyword_only": (),
    },
    "seal_table_pages": {
        "positional": ("pages", "source_sha256", "native_texts"),
        "keyword_only": (
            "table_span_fidelity_enabled",
            "table_evidence_reconciliation_enabled",
            "table_candidate_gate_enabled",
            "table_multi_page_merge_enabled",
        ),
        "required_keyword_only": (),
    },
    "merge_continued_tables": {
        "positional": ("pages", "source_sha256"),
        "keyword_only": (
            "table_span_fidelity_enabled",
            "table_evidence_reconciliation_enabled",
            "table_candidate_gate_enabled",
            "table_multi_page_merge_enabled",
        ),
        "required_keyword_only": (),
    },
    "replay_table_semantics": {
        "positional": ("table", "table_evidence"),
        "keyword_only": (),
        "required_keyword_only": (),
    },
    "replace_marked_table_text": {
        "positional": ("owner",),
        "keyword_only": (
            "selected_text",
            "replacement_mode",
            "original_text",
        ),
        "required_keyword_only": (
            "selected_text",
            "replacement_mode",
            "original_text",
        ),
    },
}
EXPECTED_TABLE_SEMANTICS_ARGUMENT_VALIDATORS = {
    "prepare_docling_table_input": {
        "raw_item": "_validate_plain_table_value",
        "page_heights": "_validate_plain_table_value",
        "page_words_by_page": "_validate_plain_table_value",
    },
    "prepare_docling_table": {
        "item": "_validate_plain_table_value",
        "raw_item": "_validate_plain_table_value",
    },
    "prepare_vector_table": {"item": "_validate_plain_table_value"},
    "reconcile_table_candidates": {
        "merged": "_copy_table_mapping",
        "docling_tables": "_copy_table_mapping",
        "vector_tables": "_copy_raw_table_graph",
    },
    "gate_table_candidates": {
        "tables": "_copy_table_mapping",
        "body_items": "_copy_table_mapping",
        "raw_docling": "_validate_plain_table_value",
        "source_document_identity": "_assert_source_sha256",
    },
    "seal_table_pages": {
        "pages": "_assert_plain_table_value",
        "source_sha256": "_assert_source_sha256",
        "native_texts": "_validate_plain_table_value",
    },
    "merge_continued_tables": {
        "pages": "_assert_plain_table_value",
        "source_sha256": "_assert_source_sha256",
    },
    "replay_table_semantics": {
        "table": "_assert_plain_table_value",
        "table_evidence": "_validate_plain_table_value",
    },
    "replace_marked_table_text": {
        "selected_text": "_validate_plain_table_value",
        "replacement_mode": "_validate_plain_table_value",
        "original_text": "_validate_plain_table_value",
    },
}
EXPECTED_TABLE_SEMANTICS_ARGUMENT_VALIDATION_POLICIES = {
    function_name: {
        argument: (
            "in_place"
            if (function_name, argument)
            in {
                ("merge_continued_tables", "pages"),
                ("replay_table_semantics", "table"),
                ("seal_table_pages", "pages"),
            }
            else "rebind"
        )
        for argument in validators
    }
    for function_name, validators in (
        EXPECTED_TABLE_SEMANTICS_ARGUMENT_VALIDATORS.items()
    )
}
EXPECTED_TABLE_SEMANTICS_OPAQUE_ATTRIBUTES = {
    "owner": frozenset({"markdown", "properties", "value"}),
    "raw_table": frozenset(
        {
            "bbox",
            "cell_bboxes",
            "geometry_inferred",
            "page_index",
            "parse_concerns",
            "row_bboxes",
            "rows",
        }
    ),
}
EXPECTED_TABLE_SEMANTICS_DEFAULT_OFF_GUARDS = {
    "prepare_docling_table_input": (
        "if not table_span_fidelity_enabled:\n"
        "    return raw_item\n"
    ),
    "prepare_docling_table": (
        "if not table_span_fidelity_enabled:\n"
        "    return item\n"
    ),
    "prepare_vector_table": (
        "if not table_span_fidelity_enabled:\n"
        "    return item\n"
    ),
    "reconcile_table_candidates": (
        "if not table_span_fidelity_enabled:\n"
        "    return merged\n"
    ),
    "gate_table_candidates": (
        "if not (\n"
        "    table_span_fidelity_enabled\n"
        "    and table_evidence_reconciliation_enabled\n"
        "    and table_candidate_gate_enabled\n"
        "):\n"
        "    return tables\n"
    ),
    "seal_table_pages": (
        "if not table_span_fidelity_enabled:\n"
        "    return\n"
    ),
    "merge_continued_tables": (
        "if not (\n"
        "    table_span_fidelity_enabled\n"
        "    and table_evidence_reconciliation_enabled\n"
        "    and table_candidate_gate_enabled\n"
        "    and table_multi_page_merge_enabled\n"
        "):\n"
        "    return\n"
    ),
}
EXPECTED_TABLE_SEMANTICS_RECONCILIATION_DISABLED_BRANCH = (
    "if not table_evidence_reconciliation_enabled:\n"
    "    return merged\n"
)
EXPECTED_TABLE_SEMANTICS_RECONCILIATION_PREAMBLE = (
    EXPECTED_TABLE_SEMANTICS_DEFAULT_OFF_GUARDS["reconcile_table_candidates"]
    + EXPECTED_TABLE_SEMANTICS_RECONCILIATION_DISABLED_BRANCH
    + "deadline = perf_counter() + 0.25\n"
    + "merged = _copy_table_mapping(merged, deadline)\n"
    + "docling_tables = _copy_table_mapping(docling_tables, deadline)\n"
    + "vector_tables = _copy_raw_table_graph(vector_tables, deadline)\n"
)
EXPECTED_TABLE_SEMANTICS_PUBLIC_DEADLINE_SECONDS = {
    name: 5.0 if name == "seal_table_pages" else 0.25
    for name in EXPECTED_TABLE_SEMANTICS_PUBLIC_SIGNATURES
}
# Populated from the reviewed final P04-US01 implementation.  These nodes are
# additive alongside the admitted scaffold; any changed vector fails closed.
EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_AST_SHA256: dict[str, str] = {
 '_apply_table_grid_serialization': '879b8863a1de593e814258ec606194399266b6519f3609598237dcf73ffe5e14',
 '_assert_table_page_container': '650681554590bcfa8b97d6556099fc80ded75a54cd6c20f208761e0466c028d0',
 '_bounded_table_output_bytes': '203dec4c905de0348f2a5ba7129ce7c184b98faa587d0edf750f3f9453981892',
 '_build_table_slots': 'c6df42d3da294bc1bb8e78ed9583db8bb65e06bd83bf1e305499dadedbd9bd82',
 '_canonical_table_json_size': '707b85155828cd3ccc5b647f14886ed5ad174a2991814f0db74ca319d6da6e15',
 '_canonical_table_sha256_and_size': 'acb0a2bdd0aae8668ddc22af46a894e95586cd18736bd3041c5edd28fe80bc78',
 '_complete_table_page_segment': 'ac0b693176eaa2188d96ed5809afe02318e595dea6eefcf2f68f0ba60da27654',
 '_diagnostic_table_evidence_graph_is_closed': 'f1d28e523523213ffa147f20167dfb2bed4e7cc1870f3f1c1efe2f781685ae09',
 '_diagnostic_table_sidecar': 'e2d57f530d2cf0f16f500eee1d09ce620da65895aeeea40b13b412be47c74c36',
 '_docling_cell_record': '16303941519ec06bf7bfa4d5e1d6e2879a3d6d8885a80355170e55ab835bbe95',
 '_docling_cell_reference': '23972de5c3bff8bf70d03eb5e830e83aeaee4669eb8c4e0c057bca8a764ccc37',
 '_docling_table_bbox': 'd2dbc3937f6db983b3d8be992a342c8ff6b4aa75205e93c896b9ac0a52c619f5',
 '_docling_table_page': '0e7e3bef6e1337a9403ee06da654aa9205cc64dbf9677441d89014a1800117c2',
 '_admit_owned_canonical_table_root': '2c67595c94bec7b4316de6cadbfff6df429f51a2ccc97b0a8b8e797f8f9c09d5',
 '_assert_owned_canonical_table_json': '75d5f302e8e4e4aedeca7773e2b76cb204fad1aba7e8a68b20ab6617e1f17915',
 '_assert_owned_table_root_state': '02a6020111a513998378d13be0dd8c2fc8b9ed4c7d53f766bea035e663d867d9',
 '_inspect_plain_table_value': 'a3027227e98073f4074e7bb4fd9b7b77f532d770449d258e435d3b38b42dfa11',
 '_install_owned_table_recovery_plan': '1aff7acafa68b4521251dcf7fd8037d6f1ba0bf1b16a9d630d7520b27b4c6a48',
 '_install_supported_table_recovery_plan': 'b53bea86321636681bd1cc1934a545ca08dd313c40f28936c8e6217bef157002',
 '_is_table_sha256': 'f3d9fde7cd10af64622e400541c05b395e58f717c25a4775e3cb8ca9c7671403',
 '_normalized_docling_cells': 'deb58238018e591d232c50c803c80bb82ac0b11ea06193781f18fa7066844f84',
 '_normalized_table_recovery_words': 'a97cfae22c67fc003ab9efd9ca53c0779334ec5ea5968a628aa06cabde399fd6',
 '_orchestrate_docling_table_projection': '078895edc8d529c20f4e752ba865354382255e3493b92939cab4f81762db6688',
 '_ordered_table_hashes_are_valid': 'b71e1ecea797dc3f332843b7c8428fd44d591fa2e7ab14382560ddd1a4d2cc15',
 '_ordered_table_ids': 'e243f066c79eac39801628e7be06cfe127a269c90f29ec6e1c022ed0814062c7',
 '_prepare_docling_table_inputs': '1db2a39c8da1e950ad817824c7c1e09d946e7a09000a79b334551e6f7aa53826',
 '_project_docling_table': '9a06bc7ca52f15a2949626b2634e4acca42af62b5d300928cf72900b60dd5707',
 '_recover_supported_bottom_row': 'fe8a5111f07e201b47a7e8e8c47b4ed2db31142970e861d7645e48b575eeb791',
 '_recover_supported_header_ownership': 'e69abaa138b58bcef0bf31b2abe631f31865cb369d3f31d9d8d2a88d19574ca1',
 '_reject_table_overlay': '9c95fec5c54b499202e8956b6a073bbc1654b169b361f72c39e75d2782cda20b',
 '_replay_table_overlay': 'e71d27a84353e7a48c010eb4033e1a33962fdee0fb960e58babc8ce9207fd73e',
 '_resolve_table_document_deadline': 'bb277d986f49d888f767efc117a0ed06582eb2b40f9227746bb4d4721af7d2d0',
 '_resolve_table_page_deadline': 'f265a167b151d4aee96d0e9d42725e52903826e1a490d9b71c158680dd4bc981',
 '_restore_all_table_predecessors': 'ac40ce8db6910a91f19ee32b4c869e2ba4ba0aced6a3a4b18abca299535bcd52',
 '_restore_table_predecessor_exact': '1386cbf2c323d1b782709f4233e68f0f5f49ae06ed5d80fcef90537bb92b8e93',
 '_scoped_table_recovery_mapping': 'aed7d3b39124535ef1e133112068e5cbfcf09087c29385020e0f31ee81c4a136',
 '_seal_table_page_overlay': '52eb0a0b2ded26d3346742f24567453e60f639ed028dd9f24ed1afdef21c5cb4',
 '_seal_table_page_overlays': '37620221a07c14cf410964fcd7104e998a9dc28b63dc69b128eec9c713066505',
 '_serialize_table_grid': '723b7600316eee2bb02e90fc9fccdb88f8b7c279f6559a7ad1574fc600adace2',
 '_owned_canonical_table_root_value': '7b456ae57144454176a87bfb8788fd39f61837bb12b2e1006185a88a79ea4f39',
 '_owned_table_root_shape': '6a9c65aad4623fff259ab88a404d84452ef8ea987d0688157a43bdde6d42806a',
 '_stream_accounted_canonical_table_json': '537c683d37b1af02e5a98b7b1f7ede90f88375a165c0a74f349d8d4386b71320',
 '_stream_canonical_table_json': '351d17fe5f8f56c5b0fb173302b5196c94a2f73f539dcab5844915928fe4c1d7',
 '_supported_table_recovery_plan': '1fed67a2b27dcb4321bde9c18bc7a58e8547f0d88c9a6c222bd7ff3472b7a9cd',
 '_table_authoritative_projection_matches': '7bf10fca5f0d056e1c75ce906b167763effbe27bb980890d76ae3aafebc4c2dc',
 '_table_bbox_fits_page': 'fe3799e5537873e1941d82dfed26ae9c5ab6e1ca40951f723be51aa09600a5ed',
 '_table_bbox_is_valid': '66372e6658d4b4068447f7c9b5ed37474040fdbbd6a42e59924b463559678480',
 '_table_cell_evidence_is_valid': '827ab4f0925efe7929ff7f7b2e56c90412f3186d65ed712135b8b5aa18458ca7',
 '_table_exact_keys': '5d6b6295bda2204bfdef8326f1b23008b53cb0c1227a3bb294f28c56c0272893',
 '_table_font_name_is_safe': '071ac75ff9cde155ed4eab14bdcbceab6801d790a0a7e08f5f018629dfb5ccd8',
 '_table_overlay_is_well_formed': 'd28c7dd67ba1aabd90a0b3a3e3bcc8c61d2fef07e7feb912d597243203920cb1',
 '_table_pdf_recovery_sources_are_exact': '2a5be1c88f455f327910a2c147253399f52d0cabb45468327bb97698137c72d6',
 '_table_pdf_word_source_objects': 'e4619b39b1fb5baea6b1292f7a25e4ee9cc1056f5e6b39b26bc75270c95f0a2f',
 '_table_predecessor_snapshot': '6bdfc19e9a8076db4e3b3aff297f0e7cbaa8f2683273b915f7beeb7b1dced123',
 '_table_projection_matches_grid': 'd93c5eef1e4b6974ab1fb723091a74656a517ed6991bbe657ee1ddaf43eda4f0',
 '_table_record_bbox': '860b56c11f9ebd3c6875fc9965a02816799c70780783c77db6168e04f6a6971c',
 '_table_recovered_header_evidence': '67d750060c9a7844f60b58656ec1a051bdcce71837af87b520c1a1c0f4fba2df',
 '_table_recovered_structure_evidence': '0f56bb601fe51a9cedf38ec783d8e6b5a21205d199f08f78e40ba38b27ec053b',
 '_table_recovery_cell_bbox': 'f1cabd8ec0ded514c4d19b404f39d6099c2d9ffaadcc5aa558ab51f48e3266d0',
 '_table_recovery_word_bbox': 'f80067b17de83609e74ceda7333e5f2c6065e98589cc7f03adc4f97899f3602f',
 '_table_recovery_word_geometry': '47a037b912545a8860c16b2527c1bdb7ac0afceb0d49db8f969c1e1fb7f123ae',
 '_table_recovery_words_fit_bbox': '43c55a6063859c9e469b2eb713573ec1329cfc0ee4fab617320508bb6696999a',
 '_table_reference_is_safe': '8631204891980d2b2eb4d56cc2c0c2eb6ea9921894450f28d5ff9bf2bb0eebc5',
 '_table_representation_custody': '8be506d53e12ca57a40a4b1a0bed36dc50bdcc399f0809a0f672c538e6bf6c54',
 '_table_representation_sha256': 'd2896f4073d64108c81c89fdb76f4bd3216cef89ac03392d15c5508a4e4b11d4',
 '_table_required_reference': '96efdf3d0145ebfa3ffbd5b48b0332c7f1e076c871c56899ba2d16144fa0359b',
 '_table_shared_page_deadline': '1f26954f7e11b5e18654cbcb26a8aa32859aef6782a86ce4d793ccc8e6697732',
 '_table_slot_topology_is_valid': '723edbc96a7951192178a8d1832916dd27b7c91c8a107998f5dd6433093e895f',
 '_table_snapshot_is_structurally_restorable': '917405cfff0962568e385383ec59ad6054931fa3cd98c81c423078c530d3ae3c',
 '_table_snapshot_with_current_unrelated_fields': '7dfa0bb35eb4bf4f5fa64b3dd33e300bef4c6316adf7513c7cb1efab22953aed',
 '_table_source_bound_identity_is_valid': 'e080e515a6947896109133d362c12589fcb5c60ed6fe2de284ceee015bf30f43',
 '_table_structure_source_content': '55e55ba66d2ae5033135f4a5aa6d5fe3bee4b521351ee66b491cb308d0f2176e',
 '_table_text_has_unsafe_control': 'd7c56d84b1987ba0e7f3dd317d758071b76a6f2254c5e379bcc48323ca759ab2',
 '_table_valid_cells_are_source_bound': '0054f2f6cad914a55ab0b5595bb784bda66dfb9d295dd897da1b648e6c2cfcb7',
 '_table_without_snapshot': '23227371c1b8f012d769373e45da09acbbeec46847c964c1848b7a542192ec05',
 '_unique_ordered_table_records': 'f396586d5e5776b17436ad249af620d154c77935d897cecd4573941b7de7b854',
 '_valid_table_evidence_graph_is_closed': '5259c77679b043758f216a1bf36c8a225918acb8b20709ae5e83950fa8315bc3',
 '_validate_docling_table_source': '8b218775008f4601bdf761ffd7fb5668d11203d8de157c78f6694f8dcfd5842d',
 '_validate_docling_table_source_fields': '52313279b4facbce10ca75b1e8fd67d845b269e39ecc02faa8614a8fb5d20274',
 '_validated_table_recovery_projection': '9d7770db57bd5c41af3fcf44e8b487b0f71305e24da78c78552fdd10b3e3390f',
 'prepare_docling_table': '183f0140d5b3b4b3ff2b93498d821e314980973e75398cc56afa04f91b8cd91f',
 'prepare_docling_table_input': '1a668463259d9afb13fb6370b53f942852f0842e7aeda9ac23dfb6954bbe8774',
 'prepare_docling_table_inputs': '8b0c31a9f54a647e3eaeed3c6734676b6b69d9456102554abecdcafd56b7da5f',
 'prepare_vector_table': 'e89e6ffed6f2b33e55c5fa98329225f63c78b1c365cdd9337ddb3f5ad3284a72',
 'replace_marked_table_text': '851043e72fdd6c91a158b39a0f0eec0c272232234260905e85f001581b124b51',
 'replay_table_semantics': '49f292d800caba3a276a7ee637cb9d539a44fa361559befbde71bfebe8a5013e',
 'seal_table_pages': 'f74f77484ed86d933d2099010857cdc0c9d474ee8bfb074f709825ad12da7eb3'}
# Preserve the historical second-additive vector while admitting the later
# exact Optimization C freeze through its own whole-module/function vector.
EXPECTED_CURRENT_FROZEN_P04_US01_TABLE_SEMANTICS_AST_SHA256 = dict(
    EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_AST_SHA256
)
for _current_only_table_helper in (
    "_admit_owned_canonical_table_root",
    "_assert_owned_canonical_table_json",
    "_assert_owned_table_root_state",
    "_inspect_plain_table_value",
    "_install_owned_table_recovery_plan",
    "_owned_canonical_table_root_value",
    "_owned_table_root_shape",
    "_stream_accounted_canonical_table_json",
    "_supported_table_recovery_plan",
):
    EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_AST_SHA256.pop(
        _current_only_table_helper
    )
EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_AST_SHA256.update(
    {
        "_install_supported_table_recovery_plan": (
            "7f3a87f8226a35d42e0d76c663a3c9a91b189e94bd871b31548f658429a5ce34"
        ),
        "_orchestrate_docling_table_projection": (
            "69531cfd286836c118aea189e876c16698b404f1ab53df8fb6e9038fe493c0e5"
        ),
        "_stream_canonical_table_json": (
            "a2fa59e2b1c8c012308991d0811203dc43ea0398de97675189382ea7a59fcd0e"
        ),
    }
)
del _current_only_table_helper
EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_IDENTITY: dict[str, Any] = {
    "ast_sha256": (
        "8234069ac08f7ea8ef1bcfdca25ffe2678dd38f17b60e3d9b8fe2b6be539a6e6"
    ),
    "path": "app/services/table_semantics.py",
    "raw_sha256": (
        "2c8d7e9976ad25686dd760ad101c65eaae4e25229a2366cf559efa6dbd4daf86"
    ),
    "size_bytes": 241_003,
}
EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_IDENTITY: dict[str, Any] = {
    "ast_sha256": (
        "9ccb2276ed46dcf1975d7a654e927ba675a1b18a4d3ed45b2387f08090365798"
    ),
    "path": "app/services/pipeline.py",
    "raw_sha256": (
        "51322ed757b2824dc4cd2a29a3b57989280dbd57d7ce8ad32f646cb7bea7d94d"
    ),
    "size_bytes": 307_034,
}
EXPECTED_CURRENT_FROZEN_P04_US01_TABLE_SEMANTICS_IDENTITY: dict[str, Any] = {
    "ast_sha256": (
        "1cc29d32acab1ed73b1479b3fb7e03b9cbb05045b460f63df7a190b21f99fb65"
    ),
    "path": "app/services/table_semantics.py",
    "raw_sha256": (
        "e9b67d23fd7146b92f348f6423cf36754ebb7976d55e88e9f06e710f7d74268f"
    ),
    "size_bytes": 250_308,
}
EXPECTED_CURRENT_FROZEN_P04_US01_PIPELINE_IDENTITY: dict[str, Any] = {
    "ast_sha256": (
        "e285f0b301f7d76ec1be6cdd0dc23865b7557d58e2b0cd377011b68cd2b395cd"
    ),
    "path": "app/services/pipeline.py",
    "raw_sha256": (
        "a79a22b0324d17e28ede2d31c76a67bbbe89f859110521beae48fd9f1b03f6a8"
    ),
    "size_bytes": 311_099,
}
EXPECTED_OWNED_TABLE_ROOT_SEAL_ASSIGNMENT_AST_SHA256 = (
    "e9b5388a33fb49cc43a5f4a0dd3cc4d5c2ede9f9c6876110c7df28b65ff5fb0e"
)
EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_ROOTS = frozenset(
    {
        "_orchestrate_docling_table_projection",
        "prepare_docling_table",
        "prepare_docling_table_input",
        "prepare_vector_table",
        "replace_marked_table_text",
        "replay_table_semantics",
        "seal_table_pages",
    }
)
EXPECTED_TABLE_SEMANTICS_PREEXISTING_EXACT_HELPERS = frozenset(
    {
        "_assert_canonical_table_json",
        "_assert_plain_table_value",
        "_assert_source_sha256",
        "_batch_table_sha256",
        "_bounded_table_iterable",
        "_bounded_table_sha256",
        "_bounded_table_text",
        "_canonical_table_json_bytes",
        "_canonical_table_sha256",
        "_check_table_deadline",
        "_copy_raw_table_graph",
        "_copy_table_mapping",
        "_plain_table_length",
        "_validate_plain_table_value",
    }
)
EXPECTED_TABLE_SEMANTICS_OUTPUT_ROOTS = {
    "prepare_docling_table_input": "raw_item",
    "prepare_docling_table": "item",
    "prepare_vector_table": "item",
    "reconcile_table_candidates": "merged",
    "gate_table_candidates": "tables",
    "seal_table_pages": "pages",
    "merge_continued_tables": "pages",
    "replay_table_semantics": "table",
    "replace_marked_table_text": None,
}
EXPECTED_TABLE_SEMANTICS_OUTPUT_JSON_LIMITS = {
    "prepare_docling_table_input": 8_388_608,
    "prepare_docling_table": 8_388_608,
    "prepare_vector_table": 8_388_608,
    "reconcile_table_candidates": 67_108_864,
    "gate_table_candidates": 67_108_864,
    "seal_table_pages": 67_108_864,
    "merge_continued_tables": 67_108_864,
    "replay_table_semantics": 8_388_608,
}
EXPECTED_TABLE_SEMANTICS_RETURN_ROOTS = {
    "prepare_docling_table_input": "raw_item",
    "prepare_docling_table": "item",
    "prepare_vector_table": "item",
    "reconcile_table_candidates": "merged",
    "gate_table_candidates": "tables",
    "seal_table_pages": None,
    "merge_continued_tables": None,
    "replay_table_semantics": "table",
    "replace_marked_table_text": None,
}
EXPECTED_PHASE04_CONFIG_GUARD_SOURCES = (
    "if self.table_span_fidelity_enabled and (\n"
    "    not self.shared_ir_enabled\n"
    "    or not self.shared_ir_normalization_enabled\n"
    "    or not self.canonical_serialization_enabled\n"
    "):\n"
    "    raise ValueError(\"PARSER_TABLES_SPAN_FIDELITY_ENABLED requires "
    "PARSER_SHARED_IR_ENABLED, PARSER_SHARED_IR_NORMALIZATION_ENABLED, and "
    "PARSER_CANONICAL_SERIALIZATION_ENABLED\")\n",
    "if self.table_evidence_reconciliation_enabled and not "
    "self.table_span_fidelity_enabled:\n"
    "    raise ValueError(\"PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED "
    "requires PARSER_TABLES_SPAN_FIDELITY_ENABLED\")\n",
    "if self.table_candidate_gate_enabled and not "
    "self.table_evidence_reconciliation_enabled:\n"
    "    raise ValueError(\"PARSER_TABLES_CANDIDATE_GATE_ENABLED requires "
    "PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED\")\n",
    "if self.table_multi_page_merge_enabled and not "
    "self.table_candidate_gate_enabled:\n"
    "    raise ValueError(\"PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED requires "
    "PARSER_TABLES_CANDIDATE_GATE_ENABLED\")\n",
)
FORBIDDEN_PHASE04_SCOPE_TOKENS = (
    "running_region",
    "running-region",
    "running region",
    "runningregion",
    "runningregions",
    "phase05",
    "phase_05",
    "phase 05",
    "p05",
    "p_0_5",
)
FORBIDDEN_TABLE_SEMANTICS_SCOPE_TOKENS = (
    *FORBIDDEN_PHASE04_SCOPE_TOKENS,
    "source_text_alignment",
    "source-text-alignment",
    "source text alignment",
)
FORBIDDEN_DYNAMIC_CALL_NAMES = frozenset(
    {"__import__", "compile", "eval", "exec"}
)
FORBIDDEN_REFLECTION_IDENTIFIERS = frozenset(
    {
        "__bases__",
        "__builtins__",
        "__dict__",
        "__getattribute__",
        "__globals__",
        "__mro__",
        "__subclasses__",
        "attrgetter",
        "breakpoint",
        "delattr",
        "dir",
        "getattr",
        "get_data",
        "globals",
        "hasattr",
        "help",
        "input",
        "itemgetter",
        "load_module",
        "locals",
        "methodcaller",
        "setattr",
        "vars",
    }
)
FORBIDDEN_EXTERNAL_CALL_NAMES = frozenset(
    {
        "open",
        "popen",
        "run",
        "sleep",
        "system",
        "urlopen",
    }
)
FORBIDDEN_EXTERNAL_MODULE_ROOTS = frozenset(
    {
        "aiohttp",
        "asyncio",
        "ftplib",
        "http",
        "httpx",
        "multiprocessing",
        "os",
        "pathlib",
        "requests",
        "shlex",
        "shutil",
        "smtplib",
        "socket",
        "subprocess",
        "urllib",
    }
)
EXPECTED_PHASE04_BASELINE_FILES = {
    "app/config.py": {
        "path": "app/config.py",
        "sha256": (
            "3903a634160e5c48f54092f820dbc7129ed941a39d6984212dd635415d0292f3"
        ),
        "size_bytes": 16_344,
    },
    "app/services/pipeline.py": {
        "path": "app/services/pipeline.py",
        "sha256": (
            "b6223e52746e334bbd58cafcaedb1462f44e9a037339daacc88736b305078a76"
        ),
        "size_bytes": 171_536,
    },
    "app/services/tables.py": {
        "path": "app/services/tables.py",
        "sha256": (
            "dc889c00eea03ee3506093c6e806966e16f76f02ff941e6476e61c32545d0d42"
        ),
        "size_bytes": 18_319,
    },
    "frontend/app/clearleaf-workspace.tsx": {
        "path": "frontend/app/clearleaf-workspace.tsx",
        "sha256": (
            "260c00eda83f115695da08aa4294824689fc99cb377f947814e3f4c1cc5f1d94"
        ),
        "size_bytes": 66_939,
    },
}
EXPECTED_PHASE04_CONFIG_NORMALIZED_AST_SHA256 = (
    "5066fbcff36b5b90ce35080bf1d386da73e8e28b0c01d956147258f81aa30be0"
)
EXPECTED_PHASE04_PIPELINE_NORMALIZED_AST_SHA256 = (
    "eaf196df6b9eba2b1fa8b2c264dafdd850245ee0ad169cff1b3237a3d92a2131"
)
EXPECTED_PHASE04_FRONTEND_NORMALIZED_SHA256 = (
    "5a4c2eb5f692f4cf30725d14d055b78c40fd60fbdd97c5fd906ed1ddbd02e116"
)
EXPECTED_PHASE04_FRONTEND_IMPORT = (
    'import { readTableSemantics } from "@/lib/table-semantics";\n'
)
EXPECTED_PHASE04_CANONICAL_FALLBACK = "        return canonicalFallback;\n"
EXPECTED_PHASE04_CANONICAL_FORM_BRANCH = (
    "        if (formSemantics) {\n"
    "          const semanticView = renderValidatedFormSemantics(formSemantics, {\n"
    "            overlay: formSemantics.relationships.some(\n"
    '              (relationship) => relationship.type === "form_overlay_of",\n'
    "            ),\n"
    "          });\n"
    "          return (\n"
    "            <div\n"
    '              className="canonical-form-block"\n'
    "              data-form-canonical-mode={formSemantics.group.canonical_mode}\n"
    "              key={block.id}\n"
    "            >\n"
    '              {formSemantics.group.canonical_mode === "inert"\n'
    "                ? canonicalFallback\n"
    "                : null}\n"
    "              {semanticView}\n"
    "            </div>\n"
    "          );\n"
    "        }\n\n"
)
EXPECTED_PHASE04_CANONICAL_TABLE_DELEGATION = (
    "        const matchingPrimaryItems = sourcePage.items.filter(\n"
    "          (item) => item.id === block.primary_element_id,\n"
    "        );\n"
    "        if (matchingPrimaryItems.length !== 1) return canonicalFallback;\n"
    "        const primaryItem = matchingPrimaryItems[0];\n"
    "        if (\n"
    '          typeof primaryItem.type !== "string" ||\n'
    '          primaryItem.type.toLowerCase() !== "table" ||\n'
    '          !Object.hasOwn(primaryItem, "table_evidence")\n'
    "        ) {\n"
    "          return canonicalFallback;\n"
    "        }\n"
    "        return <ContentItemView key={block.id} item={primaryItem} />;\n"
)
EXPECTED_PHASE04_BASELINE_TABLE_BLOCK_SHA256 = (
    "d162df6ae3ab1b8a9b8aca47598fca3e58510a5bf3599eef1ed4a82ba5937715"
)
EXPECTED_RENEWAL_DECISION_IDENTITY = {
    "path": (
        "tracker/phase-03-layout/decisions/"
        "P03-US08-frontend-bbox-latency-exception-renewal.md"
    ),
    "raw_sha256": (
        "6c1ac4c74a97f847122dd38877c6e44466795eddf1b73b26c84850ef775137e0"
    ),
    "size_bytes": 3_456,
}
EXPECTED_ORIGINAL_WAIVER_IDENTITY = {
    "path": str(WAIVER_PATH),
    "raw_sha256": (
        "1fe75bc3d749730938653030052d463340eb2e856b810e0586e9afb12e9a72c8"
    ),
    "semantic_sha256": (
        "0d3cd13942dd465c537dd7075baf0d2e8b30bc5dd891af55622c07f493610554"
    ),
    "size_bytes": 4_873,
    "waiver_id": "P03-US08-LATENCY-EXCEPTION-20260803",
}
EXPECTED_RENEWAL_WAIVER_IDENTITY = {
    "raw_sha256": (
        "9e5761d53c8769daca3c2c59f37bfc99b1db12f89f28410e2b8667583a4e58d1"
    ),
    "semantic_sha256": (
        "c650af287d8010d5a94c4c572f41538e3249c4acf4653531f2e37eab208d39e8"
    ),
    "size_bytes": 5_236,
}
EXPECTED_PRIMARY_IDENTITY = {
    "code_manifest_sha256": (
        "30e6025c3d5f02f2797476cb56ecbdb2349ddc0a57b730fc01e35a9667ce1e3f"
    ),
    "generated_at": "2026-08-03T13:02:11+05:30",
    "internal_retained_path": (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-48-failed.json"
    ),
    "physical_path": (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-48-failed.json"
    ),
    "raw_sha256": (
        "1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123"
    ),
    "semantic_sha256": (
        "51433843638d69a2d09ced0d96a44a34323b1f5ece9c890c7c91088bac2df2e5"
    ),
    "size_bytes": 158_921,
    "status": "failed_measurement_candidate",
}
EXPECTED_COMPANION_IDENTITY = {
    "code_manifest_sha256": (
        "5212a1f27a70053ab93b5c6475cbc87e0dd8c6288a0a7f84e3ef40c0d2c1e436"
    ),
    "generated_at": "2026-08-03T05:12:44+05:30",
    "internal_retained_path": (
        "tracker/phase-03-layout/evidence/P03-US08-running-region-metrics.json"
    ),
    "paired_worker_count": 20,
    "physical_path": (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-31-post-seal-invalid.json"
    ),
    "raw_sha256": (
        "925f16fcff8bfe54bf20ec40d19e7395ca2fae2e68f8694b49e5c08b65a9ad50"
    ),
    "semantic_sha256": (
        "59fe4439b0afbcd99b37c4a19fc006ad436ad623772d007e859ef117561f4fe4"
    ),
    "size_bytes": 230_069,
    "status": "final_measurement_candidate",
}
EXPECTED_FAILED_HISTORY = {
    "artifact_count": 55,
    "first_path": (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-01-failed.json"
    ),
    "last_path": (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-55-failed.json"
    ),
    "manifest_sha256": (
        "bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff"
    ),
}
EXPECTED_DECISION_IDENTITY = {
    "path": (
        "tracker/phase-03-layout/decisions/"
        "P03-US08-provisional-latency-exception.md"
    ),
    "raw_sha256": (
        "7bea63acad8403e442362edd8aabe0f4db084e6abd0cdd59e2b148b40a8b0d25"
    ),
    "size_bytes": 3_476,
}
EXPECTED_FALSE_AGGREGATES = frozenset(
    {
        "all_pass",
        "failure_free",
        "output_sizes",
        "paired_parser",
        "running_region_projection",
    }
)
EXPECTED_APPROVAL_STATEMENTS = (
    "latency alone can be fine at the moment - we can work that up later",
    (
        "Latency alone can be worked updated later - atleast if it is close "
        "then fine- not rquired to be precisely within borders at the moment "
        "- even of it is very close beyond borders - that should be fine"
    ),
)
EXPECTED_TOP_LEVEL_FIELDS = frozenset(
    {
        "approval",
        "complete_companion",
        "custody_bridge",
        "decision_identity",
        "decision_path",
        "deferred_work",
        "exception_scope",
        "expiry",
        "failed_history",
        "hosted_usage",
        "not_waived",
        "operational_constraints",
        "primary_candidate",
        "record_kind",
        "schema_version",
        "semantic_sha256",
        "status",
        "story",
        "waiver_id",
    }
)
EXPECTED_RENEWAL_TOP_LEVEL_FIELDS = frozenset(
    {
        "approval",
        "authorized_change",
        "decision_identity",
        "deferred_work",
        "exception_scope",
        "expiry",
        "failed_history",
        "hosted_usage",
        "not_waived",
        "operational_constraints",
        "original_decision_identity",
        "original_waiver_identity",
        "record_kind",
        "renewal_id",
        "renews_waiver_id",
        "schema_version",
        "semantic_sha256",
        "status",
        "story",
    }
)
EXPECTED_NOT_WAIVED = (
    "allocation",
    "api_schema_compatibility",
    "code_dependency_input_and_fixture_custody",
    "correctness_and_quality",
    "deadlines_and_resource_boundaries",
    "hosted_usage",
    "output_sizes",
    "paired_parser_latency",
    "peak_rss",
    "rollback",
    "security",
    "source_extraction_latency",
    "uber_projection_latency",
)
EXPECTED_SECOND_ADDITIVE_P04_US01_AUTHORIZATION = {
    "approval_source": "active Codex thread",
    "difference_scope": (
        "exact default-off P04-US01 table span-fidelity implementation only"
    ),
    "exception_scope": {
        "candidate_specific": True,
        "maximum_overrun_fraction": 0.05,
        "metric": "latency_p95_seconds",
        "observed_seconds": 0.050946750,
        "overrun_fraction": 0.018935,
        "overrun_seconds": 0.000946750,
        "stage": "running_region_projection",
        "strict_ceiling_seconds": 0.050000000,
        "target_id": "ny-timetable",
    },
    "failed_history": dict(EXPECTED_FAILED_HISTORY),
    "hosted_usage": {
        "hosted_cost_usd": 0,
        "hosted_requests": 0,
        "hosted_tokens": 0,
    },
    "not_waived": list(EXPECTED_NOT_WAIVED),
    "operational_constraints": {
        "canonical_strict_final_artifact_present": False,
        "feature_flag": "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED",
        "feature_flag_default": False,
        "rollback": (
            "disable the flag to skip US08 work and return the exact configured "
            "predecessor"
        ),
    },
    "prior_amendment_approval_identity": {
        "path": (
            "tracker/phase-03-layout/evidence/"
            "P03-US08-phase04-tables-hardened-renewal-"
            "implementation-state-amendment-approval.md"
        ),
        "raw_sha256": (
            "2c820a0e8c0027dcf986473a974a3db69002c0fd1f5aed2e3f62dba1acc3d389"
        ),
        "size_bytes": 6_026,
    },
    "prior_amendment_identity": {
        "path": (
            "tracker/phase-03-layout/evidence/"
            "P03-US08-phase04-tables-hardened-renewal-"
            "implementation-state-amendment.md"
        ),
        "raw_sha256": (
            "4a411bad9e605c3c4644c826c05d497474ce7c45c52b546b8c6e97eda9f841bc"
        ),
        "size_bytes": 6_672,
    },
    "prior_focused_guard_identity": {
        "path": "tests/performance/test_p03_us08_provisional_latency_exception.py",
        "raw_sha256": (
            "2e6713fde8d91d48e08e402ec0f6f9c0ee80f62496f72137692e60573134d100"
        ),
        "size_bytes": 202_100,
    },
    "prior_guard_identity": {
        "path": (
            "tests/fixtures/phase_03/running_regions/performance_exception.py"
        ),
        "raw_sha256": (
            "d749ea7a0713dbd35d2323b54dda4b1652c1077d501601b04e9b30135230f2bd"
        ),
        "size_bytes": 389_880,
    },
    "review_due_on": "2026-09-02",
}
EXPECTED_EXCEPTION_SCOPE_FIELDS = frozenset(
    {
        "candidate_specific",
        "maximum_overrun_fraction",
        "metric",
        "observed_seconds",
        "overrun_fraction",
        "overrun_seconds",
        "stage",
        "strict_ceiling_seconds",
        "target_id",
    }
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def waiver_semantic_sha256(value: Mapping[str, Any]) -> str:
    detached = dict(value)
    detached.pop("semantic_sha256", None)
    return hashlib.sha256(_canonical_json(detached).encode("utf-8")).hexdigest()


def _phase04_baseline_code(
    original_code: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Reconstruct the exact code map accepted by the frontend-bbox renewal."""

    baseline = {path: dict(identity) for path, identity in original_code.items()}
    baseline.update(
        {
            path: dict(identity)
            for path, identity in EXPECTED_RENEWAL_FILE_IDENTITIES.items()
        }
    )
    if metrics._sha256_json(baseline) != EXPECTED_RENEWAL_CODE_MANIFEST_SHA256:
        raise readiness.ReadinessContractError(
            "latency renewal baseline manifest differs"
        )
    return baseline


def _ast_digest(tree: ast.AST) -> str:
    return hashlib.sha256(
        ast.dump(tree, annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest()


def _validate_hardened_metrics_contract_surface(raw: bytes) -> str:
    """Accept only the frozen P03 contract or exact Phase 04 custody bridge."""

    observed = {
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    identities = (
        EXPECTED_HARDENED_METRICS_CONTRACT_BASELINE_IDENTITY,
        EXPECTED_HARDENED_METRICS_CONTRACT_CANDIDATE_IDENTITY,
    )
    if not any(
        observed
        == {
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        }
        for identity in identities
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 administrative custody bridge changed"
        )
    return observed["sha256"]


def _validate_hardened_phase04_env_example(raw: bytes) -> str:
    """Accept only the baseline env example or four exact default-off lines."""

    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 env example custody differs"
        ) from exc
    suffix = EXPECTED_HARDENED_ENV_EXAMPLE_PHASE04_SUFFIX
    if source.endswith(suffix):
        source = source[: -len(suffix)]
    normalized = source.encode("utf-8")
    baseline = EXPECTED_HARDENED_ENV_EXAMPLE_IDENTITY
    if (
        len(normalized) != baseline["size_bytes"]
        or hashlib.sha256(normalized).hexdigest() != baseline["sha256"]
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 env example surface changed"
        )
    return hashlib.sha256(normalized).hexdigest()


def _validate_phase04_config_guard(statement: ast.stmt) -> set[str]:
    expected = [ast.parse(source).body[0] for source in EXPECTED_PHASE04_CONFIG_GUARD_SOURCES]
    observed_dump = ast.dump(statement, annotate_fields=True, include_attributes=False)
    if observed_dump not in {
        ast.dump(value, annotate_fields=True, include_attributes=False)
        for value in expected
    }:
        raise readiness.ReadinessContractError(
            "Phase 04 config dependency guard differs"
        )
    return {
        node.attr
        for node in ast.walk(statement.test)
        if isinstance(node, ast.Attribute)
        and node.attr in EXPECTED_HARDENED_PHASE04_SETTING_NAMES
    }


def _phase04_config_normalized_digest(raw: bytes) -> str:
    """Strip only the four additive table settings from the config AST."""

    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise readiness.ReadinessContractError(
            "Phase 04 config custody differs"
        ) from exc
    settings = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Settings"
        ),
        None,
    )
    if settings is None:
        raise readiness.ReadinessContractError("Phase 04 config custody differs")

    field_positions: list[int] = []
    observed_fields: list[str] = []
    observed_guards: list[str] = []
    observed_env: list[str] = []
    normalized_body: list[ast.stmt] = []
    post_init_position = next(
        (
            index
            for index, node in enumerate(settings.body)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "__post_init__"
        ),
        -1,
    )
    for node_index, node in enumerate(settings.body):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in EXPECTED_PHASE04_SETTING_NAMES
        ):
            if (
                not isinstance(node.annotation, ast.Name)
                or node.annotation.id != "bool"
                or not isinstance(node.value, ast.Constant)
                or node.value.value is not False
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 config flag default differs"
                )
            observed_fields.append(node.target.id)
            field_positions.append(node_index)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "__post_init__",
            "from_env",
        }:
            copied = ast.parse(ast.unparse(node)).body[0]
            assert isinstance(copied, (ast.FunctionDef, ast.AsyncFunctionDef))
            if copied.name == "__post_init__":
                table_positions = [
                    index
                    for index, statement in enumerate(copied.body)
                    if any(
                        isinstance(value, ast.Attribute)
                        and value.attr in EXPECTED_HARDENED_PHASE04_SETTING_NAMES
                        for value in ast.walk(statement)
                    )
                ]
                if table_positions:
                    expected_start = len(copied.body) - len(
                        EXPECTED_PHASE04_CONFIG_GUARD_SOURCES
                    )
                    if table_positions != list(
                        range(expected_start, len(copied.body))
                    ):
                        raise readiness.ReadinessContractError(
                            "Phase 04 config dependency guard position differs"
                        )
                    expected_dumps = [
                        ast.dump(
                            ast.parse(source).body[0],
                            annotate_fields=True,
                            include_attributes=False,
                        )
                        for source in EXPECTED_PHASE04_CONFIG_GUARD_SOURCES
                    ]
                    actual = copied.body[expected_start:]
                    if [
                        ast.dump(
                            statement,
                            annotate_fields=True,
                            include_attributes=False,
                        )
                        for statement in actual
                    ] != expected_dumps:
                        raise readiness.ReadinessContractError(
                            "Phase 04 config dependency guard differs"
                        )
                    for statement in actual:
                        phase04 = _validate_phase04_config_guard(statement)
                        observed_guards.extend(
                            name
                            for name in EXPECTED_HARDENED_PHASE04_SETTING_ORDER
                            if name in phase04
                        )
                    copied.body = copied.body[:expected_start]
            else:
                returns = [
                    statement
                    for statement in copied.body
                    if isinstance(statement, ast.Return)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Name)
                    and statement.value.func.id == "cls"
                ]
                if len(returns) != 1:
                    raise readiness.ReadinessContractError(
                        "Phase 04 config environment binding differs"
                    )
                call = returns[0].value
                assert isinstance(call, ast.Call)
                table_keywords = [
                    keyword
                    for keyword in call.keywords
                    if keyword.arg in EXPECTED_HARDENED_PHASE04_SETTING_NAMES
                ]
                if table_keywords:
                    if (
                        call.keywords[-len(table_keywords) :] != table_keywords
                        or [keyword.arg for keyword in table_keywords]
                        != list(EXPECTED_HARDENED_PHASE04_SETTING_ORDER)
                    ):
                        raise readiness.ReadinessContractError(
                            "Phase 04 config environment binding position differs"
                        )
                    for keyword in table_keywords:
                        field = str(keyword.arg)
                        expected_env = (
                            "PARSER_TABLES_"
                            + field.removeprefix("table_")
                            .removesuffix("_enabled")
                            .upper()
                            + "_ENABLED"
                        )
                        value = keyword.value
                        if (
                            not isinstance(value, ast.Call)
                            or not isinstance(value.func, ast.Name)
                            or value.func.id != "_read_bool"
                            or len(value.args) != 2
                            or value.keywords
                            or not isinstance(value.args[0], ast.Constant)
                            or value.args[0].value != expected_env
                            or not isinstance(value.args[1], ast.Constant)
                            or value.args[1].value is not False
                        ):
                            raise readiness.ReadinessContractError(
                                "Phase 04 config environment binding differs"
                            )
                        observed_env.append(field)
                    call.keywords = call.keywords[: -len(table_keywords)]
                if any(
                    isinstance(value, ast.keyword)
                    and value.arg in EXPECTED_HARDENED_PHASE04_SETTING_NAMES
                    for value in ast.walk(copied)
                ):
                    raise readiness.ReadinessContractError(
                        "Phase 04 config environment binding differs"
                    )
            normalized_body.append(copied)
            continue
        normalized_body.append(node)
    settings.body = normalized_body
    expected_fields = list(EXPECTED_HARDENED_PHASE04_SETTING_ORDER)
    expected_guards = [
        "table_span_fidelity_enabled",
        "table_span_fidelity_enabled",
        "table_evidence_reconciliation_enabled",
        "table_evidence_reconciliation_enabled",
        "table_candidate_gate_enabled",
        "table_candidate_gate_enabled",
        "table_multi_page_merge_enabled",
    ]
    empty_surface = not observed_fields and not observed_guards and not observed_env
    complete_surface = (
        observed_fields == expected_fields
        and field_positions
        == list(range(post_init_position - len(expected_fields), post_init_position))
        and observed_guards == expected_guards
        and observed_env == expected_fields
    )
    if not (empty_surface or complete_surface):
        raise readiness.ReadinessContractError("Phase 04 config surface differs")
    ast.fix_missing_locations(tree)
    return _ast_digest(tree)


def _phase04_pipeline_normalized_digest(raw: bytes) -> str:
    """Remove only named table functions and freeze the rest of the module."""

    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline custody differs"
        ) from exc
    _normalize_hardened_pipeline_table_repair(tree)
    _normalize_hardened_pipeline_vector_extraction(tree)
    observed: set[str] = set()
    retained: list[ast.stmt] = []
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name in EXPECTED_PHASE04_PIPELINE_FUNCTIONS
        ):
            observed.add(node.name)
            continue
        retained.append(node)
    if observed != set(EXPECTED_PHASE04_PIPELINE_FUNCTIONS):
        raise readiness.ReadinessContractError("Phase 04 pipeline surface differs")
    return _ast_digest(ast.Module(body=retained, type_ignores=[]))


def _phase04_frontend_normalized_digest(raw: bytes) -> str:
    """Freeze the frontend outside three exact, independently bounded surfaces."""

    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise readiness.ReadinessContractError(
            "Phase 04 frontend custody differs"
        ) from exc
    import_count = source.count(EXPECTED_PHASE04_FRONTEND_IMPORT)
    if import_count not in {0, 1}:
        raise readiness.ReadinessContractError("Phase 04 frontend import differs")
    source = source.replace(EXPECTED_PHASE04_FRONTEND_IMPORT, "")
    delegation_count = source.count(EXPECTED_PHASE04_CANONICAL_TABLE_DELEGATION)
    if delegation_count not in {0, 1}:
        raise readiness.ReadinessContractError(
            "Phase 04 canonical table delegation differs"
        )
    fallback_context = (
        EXPECTED_PHASE04_CANONICAL_FORM_BRANCH
        + EXPECTED_PHASE04_CANONICAL_FALLBACK
    )
    delegation_context = (
        EXPECTED_PHASE04_CANONICAL_FORM_BRANCH
        + EXPECTED_PHASE04_CANONICAL_TABLE_DELEGATION
    )
    if delegation_count == 1:
        if source.count(delegation_context) != 1:
            raise readiness.ReadinessContractError(
                "Phase 04 canonical table delegation precedence differs"
            )
        source = source.replace(delegation_context, fallback_context, 1)
    elif source.count(fallback_context) != 1:
        raise readiness.ReadinessContractError(
            "Phase 04 canonical table fallback differs"
        )
    start_marker = '  if (type === "table") {'
    end_marker = '  if (type === "list") {'
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise readiness.ReadinessContractError("Phase 04 frontend table block differs")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    normalized = source[:start] + "  /* PHASE04_TABLE_BLOCK */\n" + source[end:]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _phase04_scope_text(node: ast.AST) -> str:
    return "\n".join(_phase04_scope_values(node)).casefold()


def _phase04_scope_literal_fragments(
    node: ast.AST,
    *,
    depth: int = 0,
) -> str | None:
    if depth > 64:
        raise readiness.ReadinessContractError(
            "Phase 04 scope expression differs"
        )

    def bounded_join(values: list[str], separator: str = "") -> str:
        if len(values) > 256:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        total = max(0, len(values) - 1) * _phase04_scope_utf8_size(separator)
        for value in values:
            total += _phase04_scope_utf8_size(value)
            if total > 65_536:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
        return separator.join(values)

    def collect_fragments(values: Iterable[ast.AST | None]) -> list[str]:
        fragments: list[str] = []
        total = 0
        for index, value in enumerate(values):
            if index >= 256:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            if value is None:
                continue
            fragment = _phase04_scope_literal_fragments(
                value,
                depth=depth + 1,
            )
            if not fragment:
                continue
            fragment_bytes = _phase04_scope_utf8_size(fragment)
            if len(fragments) >= 256 or total + fragment_bytes > 65_536:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            total += fragment_bytes
            fragments.append(fragment)
        return fragments

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        result: str | None = node.value
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _phase04_scope_literal_fragments(node.left, depth=depth + 1)
        right = _phase04_scope_literal_fragments(node.right, depth=depth + 1)
        joined = bounded_join([value for value in (left, right) if value])
        result = joined or None
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        if (
            isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
            and isinstance(node.right, ast.Constant)
            and type(node.right.value) is int
            and 0 <= node.right.value <= 65_536
        ):
            if (
                _phase04_scope_utf8_size(node.left.value) * node.right.value
                > 65_536
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            result = node.left.value * node.right.value
        elif (
            isinstance(node.right, ast.Constant)
            and isinstance(node.right.value, str)
            and isinstance(node.left, ast.Constant)
            and type(node.left.value) is int
            and 0 <= node.left.value <= 65_536
        ):
            if (
                _phase04_scope_utf8_size(node.right.value) * node.left.value
                > 65_536
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            result = node.right.value * node.left.value
        else:
            nested = [
                _phase04_scope_literal_fragments(child, depth=depth + 1)
                for child in (node.left, node.right)
            ]
            if any(fragment is not None for fragment in nested):
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            return None
    elif isinstance(node, (ast.List, ast.Tuple)):
        fragments = collect_fragments(node.elts)
        result = bounded_join(fragments) or None
    elif isinstance(node, ast.Set):
        fragments = collect_fragments(node.elts)
        forward = bounded_join(fragments)
        backward = bounded_join(list(reversed(fragments)))
        alternatives = [value for value in (forward, backward) if value]
        result = bounded_join(alternatives, "\n") or None
    elif isinstance(node, ast.Dict):
        key_fragments = collect_fragments(node.keys)
        value_fragments = collect_fragments(node.values)
        keys = bounded_join(key_fragments)
        values = bounded_join(value_fragments)
        alternatives = [value for value in (keys, values) if value]
        result = bounded_join(alternatives, "\n") or None
    elif isinstance(node, ast.JoinedStr):
        fragments = collect_fragments(node.values)
        result = bounded_join(fragments) or None
    else:
        return None
    if result is not None and _phase04_scope_utf8_size(result) > 65_536:
        raise readiness.ReadinessContractError(
            "Phase 04 scope expression differs"
        )
    return result


def _phase04_scope_static_bindings(
    node: ast.AST,
) -> dict[str, tuple[ast.AST, ...]]:
    collected: dict[str, list[ast.AST]] = {}

    def bind(target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, ast.Name):
            candidates = collected.setdefault(target.id, [])
            if len(candidates) >= 256:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            candidates.append(value)
        elif (
            isinstance(target, (ast.List, ast.Tuple))
            and isinstance(value, (ast.List, ast.Tuple))
            and len(target.elts) == len(value.elts)
        ):
            for nested_target, nested_value in zip(
                target.elts, value.elts, strict=True
            ):
                bind(nested_target, nested_value)

    for value in ast.walk(node):
        if isinstance(value, ast.Assign):
            for target in value.targets:
                bind(target, value.value)
        elif isinstance(value, ast.AnnAssign) and value.value is not None:
            bind(value.target, value.value)
        elif isinstance(value, ast.NamedExpr):
            bind(value.target, value.value)
    return {name: tuple(values) for name, values in collected.items()}


def _phase04_scope_utf8_size(value: str) -> int:
    total = 0
    for character in value:
        codepoint = ord(character)
        if codepoint <= 0x7F:
            total += 1
        elif codepoint <= 0x7FF:
            total += 2
        elif 0xD800 <= codepoint <= 0xDFFF:
            # Preserve later terminal plain-data validation for malformed text
            # while keeping this preflight allocation-free and conservative.
            total += 4
        elif codepoint <= 0xFFFF:
            total += 3
        else:
            total += 4
    return total


def _phase04_scope_nfkc_bounded(value: str) -> str:
    projected = 0
    for character in value:
        projected += _phase04_scope_utf8_size(
            unicodedata.normalize("NFKC", character)
        )
        if projected > 65_536:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
    normalized = unicodedata.normalize("NFKC", value)
    if _phase04_scope_utf8_size(normalized) > 65_536:
        raise readiness.ReadinessContractError(
            "Phase 04 scope expression differs"
        )
    return normalized


def _phase04_scope_compact_atom(value: str) -> str:
    normalized = _phase04_scope_nfkc_bounded(value)
    projected = 0
    folded_parts: list[str] = []
    for character in normalized:
        folded = character.casefold()
        projected += _phase04_scope_utf8_size(folded)
        if projected > 65_536:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        folded_parts.append(folded)
    return "".join(
        character
        for character in "".join(folded_parts)
        if "a" <= character <= "z" or "0" <= character <= "9"
    )


def _phase04_scope_relevant_atom(value: str) -> str | None:
    for target in _PHASE04_SCOPE_RECONSTRUCTION_TARGETS:
        if target in value:
            return target
    if value and any(
        len(value) <= len(target) and value in target
        for target in _PHASE04_SCOPE_RECONSTRUCTION_TARGETS
    ):
        return value
    return None


def _phase04_scope_bounded_strings(values: list[str]) -> tuple[str, ...]:
    unique: list[str] = []
    observed: set[str] = set()
    for value in values:
        if _phase04_scope_utf8_size(value) > 65_536:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        if value not in observed:
            observed.add(value)
            unique.append(value)
        if len(unique) > 256:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
    return tuple(unique)


def _phase04_scope_checked_product(*counts: int, limit: int = 256) -> int:
    """Return a bounded cartesian size without first materializing it."""

    product = 1
    for count in counts:
        if count < 0:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        if count == 0:
            product = 0
            continue
        if product > limit // count:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        product *= count
    return product


def _phase04_scope_bounded_scalar_text(
    value: Any,
    *,
    conversion: str = "str",
    depth: int = 0,
) -> str:
    """Convert an admitted scalar only after bounding its complete text."""

    if depth > 64 or conversion not in {"ascii", "repr", "str"}:
        raise readiness.ReadinessContractError(
            "Phase 04 scope expression differs"
        )
    if isinstance(value, tuple):
        _phase04_scope_checked_product(len(value))
        nested_conversion = "ascii" if conversion == "ascii" else "repr"
        parts: list[str] = []
        projected = 2 + max(0, len(value) - 1) * 2 + int(len(value) == 1)
        for item in value:
            part = _phase04_scope_bounded_scalar_text(
                item,
                conversion=nested_conversion,
                depth=depth + 1,
            )
            projected += _phase04_scope_utf8_size(part)
            if projected > 65_536:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            parts.append(part)
        text = "(" + ", ".join(parts) + ("," if len(parts) == 1 else "") + ")"
    elif isinstance(value, bytes):
        projected = 3
        for byte in value:
            if 0x20 <= byte <= 0x7E and byte not in {0x22, 0x27, 0x5C}:
                projected += 1
            elif byte in {0x09, 0x0A, 0x0D, 0x22, 0x27, 0x5C}:
                projected += 2
            else:
                projected += 4
            if projected > 65_536:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
        text = repr(value)
    elif isinstance(value, str):
        if conversion == "str":
            text = value
        else:
            projected = 2
            converter = ascii if conversion == "ascii" else repr
            for character in value:
                escaped = converter(character)
                projected += (
                    2
                    if character in {'"', "'"}
                    else _phase04_scope_utf8_size(escaped[1:-1])
                )
                if projected > 65_536:
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
            text = converter(value)
    elif type(value) in {bool, float, int, type(None)}:
        text = (
            ascii(value)
            if conversion == "ascii"
            else repr(value)
            if conversion == "repr"
            else str(value)
        )
    else:
        raise readiness.ReadinessContractError(
            "Phase 04 scope expression differs"
        )
    if _phase04_scope_utf8_size(text) > 65_536:
        raise readiness.ReadinessContractError(
            "Phase 04 scope expression differs"
        )
    return text


def _phase04_scope_format_is_bounded(value: str) -> bool:
    if (
        len(value) > 256
        or "*" in value
        or re.search(r"\{[^{}]*\{", value) is not None
    ):
        return False
    widths = re.findall(r"[0-9]+", value)
    if sum(int(digits) for digits in widths if len(digits) <= 5) > 65_536:
        return False
    for digits in widths:
        if len(digits) > 5 or int(digits) > 65_536:
            return False
    return True


_PHASE04_UNKNOWN_FORMATTED_SCOPE_MARKER = "\x00PHASE04_DYNAMIC_FORMATTED\x00"


def _phase04_scope_static_scalars(
    node: ast.AST,
    *,
    bindings: Mapping[str, tuple[ast.AST, ...]],
    active_names: frozenset[str] = frozenset(),
    depth: int = 0,
) -> tuple[Any, ...]:
    if depth > 64:
        raise readiness.ReadinessContractError("Phase 04 scope expression differs")
    values: list[Any] = []
    if isinstance(node, ast.Constant) and type(node.value) in {
        bool,
        bytes,
        float,
        int,
        str,
        type(None),
    }:
        if (
            isinstance(node.value, bytes)
            and len(node.value) > 65_536
            or isinstance(node.value, str)
            and _phase04_scope_utf8_size(node.value) > 65_536
            or type(node.value) is int
            and abs(node.value) > 1_000_000_000
            or type(node.value) is float
            and (
                not math.isfinite(node.value)
                or abs(node.value) > 1_000_000_000
            )
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        values.append(node.value)
    elif isinstance(node, ast.Name):
        if node.id in active_names:
            return ()
        for candidate in bindings.get(node.id, ()):
            candidate_values = _phase04_scope_static_scalars(
                candidate,
                bindings=bindings,
                active_names=active_names | {node.id},
                depth=depth + 1,
            )
            _phase04_scope_checked_product(
                len(values) + len(candidate_values)
            )
            values.extend(candidate_values)
    elif isinstance(node, ast.NamedExpr):
        values.extend(
            _phase04_scope_static_scalars(
                node.value,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            )
        )
    elif isinstance(node, ast.UnaryOp) and isinstance(
        node.op, (ast.UAdd, ast.USub)
    ):
        for value in _phase04_scope_static_scalars(
            node.operand,
            bindings=bindings,
            active_names=active_names,
            depth=depth + 1,
        ):
            if type(value) in {int, float}:
                values.append(value if isinstance(node.op, ast.UAdd) else -value)
    elif isinstance(node, ast.BinOp):
        left_values = _phase04_scope_static_scalars(
            node.left,
            bindings=bindings,
            active_names=active_names,
            depth=depth + 1,
        )
        right_values = _phase04_scope_static_scalars(
            node.right,
            bindings=bindings,
            active_names=active_names,
            depth=depth + 1,
        )
        _phase04_scope_checked_product(len(left_values), len(right_values))
        for left in left_values:
            for right in right_values:
                if type(left) not in {int, float} or type(right) not in {
                    int,
                    float,
                }:
                    continue
                if abs(left) > 1_000_000_000 or abs(right) > 1_000_000_000:
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
                try:
                    if isinstance(node.op, ast.Add):
                        result = left + right
                    elif isinstance(node.op, ast.Sub):
                        result = left - right
                    elif isinstance(node.op, ast.Mult):
                        result = left * right
                    elif isinstance(node.op, ast.Div):
                        result = left / right
                    elif isinstance(node.op, ast.FloorDiv):
                        result = left // right
                    elif isinstance(node.op, ast.Mod):
                        result = left % right
                    elif isinstance(node.op, ast.Pow):
                        if abs(right) > 16 or abs(left) > 1_000_000:
                            raise readiness.ReadinessContractError(
                                "Phase 04 scope expression differs"
                            )
                        result = left**right
                    elif isinstance(node.op, ast.LShift):
                        if (
                            type(left) is not int
                            or type(right) is not int
                            or not 0 <= right <= 30
                        ):
                            continue
                        result = left << right
                    elif isinstance(node.op, ast.RShift):
                        if (
                            type(left) is not int
                            or type(right) is not int
                            or not 0 <= right <= 30
                        ):
                            continue
                        result = left >> right
                    elif isinstance(node.op, ast.BitOr):
                        result = left | right
                    elif isinstance(node.op, ast.BitAnd):
                        result = left & right
                    elif isinstance(node.op, ast.BitXor):
                        result = left ^ right
                    else:
                        continue
                except (ArithmeticError, OverflowError, TypeError, ValueError):
                    continue
                if (
                    type(result) in {int, float}
                    and math.isfinite(result)
                    and abs(result) <= 1_000_000_000
                ):
                    values.append(result)
    elif isinstance(node, (ast.Tuple, ast.List)):
        _phase04_scope_checked_product(len(node.elts))
        rows: list[tuple[Any, ...]] = [()]
        for element in node.elts:
            element_values = _phase04_scope_static_scalars(
                element,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            )
            if len(rows) * len(element_values) > 256:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            rows = [
                (*row, value)
                for row in rows
                for value in element_values
            ]
            if len(rows) > 256:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
        values.extend(rows)
    unique: list[Any] = []
    observed: set[tuple[type[Any], Any]] = set()
    for value in values:
        key = (type(value), value)
        if key not in observed:
            observed.add(key)
            unique.append(value)
        if len(unique) > 256:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
    return tuple(unique)


def _phase04_scope_static_strings(
    node: ast.AST,
    *,
    bindings: Mapping[str, tuple[ast.AST, ...]],
    active_names: frozenset[str] = frozenset(),
    depth: int = 0,
) -> tuple[str, ...]:
    if depth > 64:
        raise readiness.ReadinessContractError("Phase 04 scope expression differs")

    def combine(
        left: tuple[str, ...], right: tuple[str, ...]
    ) -> tuple[str, ...]:
        left_values = left or ("",)
        right_values = right or ("",)
        if len(left_values) * len(right_values) > 256:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        combined: list[str] = []
        for left_value in left_values:
            left_bytes = _phase04_scope_utf8_size(left_value)
            for right_value in right_values:
                if left_bytes + _phase04_scope_utf8_size(right_value) > 65_536:
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
                combined.append(left_value + right_value)
        return _phase04_scope_bounded_strings(combined)

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if _phase04_scope_utf8_size(node.value) > 65_536:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        return (node.value,)
    if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
        if len(node.value) > 65_536:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        try:
            return (node.value.decode("utf-8"),)
        except UnicodeDecodeError:
            return ()
    if isinstance(node, ast.Name):
        if node.id in active_names:
            return ()
        results: list[str] = []
        for candidate in bindings.get(node.id, ()):
            candidate_values = _phase04_scope_static_strings(
                candidate,
                bindings=bindings,
                active_names=active_names | {node.id},
                depth=depth + 1,
            )
            _phase04_scope_checked_product(
                len(results) + len(candidate_values)
            )
            results.extend(candidate_values)
        return _phase04_scope_bounded_strings(results)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return combine(
            _phase04_scope_static_strings(
                node.left,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            ),
            _phase04_scope_static_strings(
                node.right,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            ),
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        pairs = ((node.left, node.right), (node.right, node.left))
        results: list[str] = []
        for text_node, count_node in pairs:
            texts = _phase04_scope_static_strings(
                text_node,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            )
            counts = _phase04_scope_static_scalars(
                count_node,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            )
            candidate_count = _phase04_scope_checked_product(
                len(texts), len(counts)
            )
            _phase04_scope_checked_product(len(results) + candidate_count)
            for text in texts:
                for count in counts:
                    if type(count) is int and 0 <= count <= 65_536:
                        if _phase04_scope_utf8_size(text) * count > 65_536:
                            raise readiness.ReadinessContractError(
                                "Phase 04 scope expression differs"
                            )
                        results.append(text * count)
        return _phase04_scope_bounded_strings(results)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        results = []
        templates = _phase04_scope_static_strings(
            node.left,
            bindings=bindings,
            active_names=active_names,
            depth=depth + 1,
        )
        scalars = _phase04_scope_static_scalars(
            node.right,
            bindings=bindings,
            active_names=active_names,
            depth=depth + 1,
        )
        _phase04_scope_checked_product(len(templates), len(scalars))
        for template in templates:
            if not _phase04_scope_format_is_bounded(template):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics allocation bound differs"
                )
            for scalar in scalars:
                scalar_items = scalar if isinstance(scalar, tuple) else (scalar,)
                projected = _phase04_scope_utf8_size(template) + 4 * sum(
                    _phase04_scope_utf8_size(
                        _phase04_scope_bounded_scalar_text(
                            item,
                            conversion="ascii",
                        )
                    )
                    for item in scalar_items
                ) * max(1, template.count("%") - 2 * template.count("%%"))
                projected += sum(
                    int(value) for value in re.findall(r"[0-9]+", template)
                )
                if projected > 65_536:
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics allocation bound differs"
                    )
                try:
                    value = template % scalar
                except (TypeError, ValueError, OverflowError):
                    continue
                if isinstance(value, str):
                    results.append(value)
        return _phase04_scope_bounded_strings(results)
    if isinstance(node, ast.FormattedValue):
        specifications = (
            _phase04_scope_static_strings(
                node.format_spec,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            )
            if node.format_spec is not None
            else ("",)
        )
        results = []
        scalars = _phase04_scope_static_scalars(
            node.value,
            bindings=bindings,
            active_names=active_names,
            depth=depth + 1,
        )
        for specification in specifications:
            if not _phase04_scope_format_is_bounded(specification):
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
        if not scalars:
            return (_PHASE04_UNKNOWN_FORMATTED_SCOPE_MARKER,)
        _phase04_scope_checked_product(len(scalars), len(specifications))
        for scalar in scalars:
            for specification in specifications:
                converted = (
                    _phase04_scope_bounded_scalar_text(
                        scalar,
                        conversion="ascii",
                    )
                    if node.conversion == ord("a")
                    else _phase04_scope_bounded_scalar_text(
                        scalar,
                        conversion="repr",
                    )
                    if node.conversion == ord("r")
                    else _phase04_scope_bounded_scalar_text(scalar)
                    if node.conversion == ord("s")
                    else scalar
                )
                converted_text = (
                    converted
                    if isinstance(converted, str)
                    else _phase04_scope_bounded_scalar_text(converted)
                )
                widths = [
                    int(value)
                    for value in re.findall(r"[0-9]+", specification)
                ]
                if (
                    _phase04_scope_utf8_size(converted_text) > 65_536
                    or _phase04_scope_utf8_size(converted_text) + sum(widths)
                    > 65_536
                ):
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
                try:
                    results.append(format(converted, specification))
                except (TypeError, ValueError, OverflowError):
                    fallback = _phase04_scope_bounded_scalar_text(scalar)
                    if (
                        _phase04_scope_utf8_size(fallback)
                        + _phase04_scope_utf8_size(specification)
                        > 65_536
                    ):
                        raise readiness.ReadinessContractError(
                            "Phase 04 scope expression differs"
                        )
                    results.append(fallback + specification)
        return _phase04_scope_bounded_strings(results)
    if isinstance(node, ast.JoinedStr):
        _phase04_scope_checked_product(len(node.values))
        values: tuple[str, ...] = ()
        for element in node.values:
            values = combine(
                values,
                _phase04_scope_static_strings(
                    element,
                    bindings=bindings,
                    active_names=active_names,
                    depth=depth + 1,
                ),
            )
        return values
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        _phase04_scope_checked_product(len(node.elts))
        forward: tuple[str, ...] = ()
        reverse: tuple[str, ...] = ()
        for element in node.elts:
            forward = combine(
                forward,
                _phase04_scope_static_strings(
                    element,
                    bindings=bindings,
                    active_names=active_names,
                    depth=depth + 1,
                ),
            )
        for element in reversed(node.elts):
            reverse = combine(
                reverse,
                _phase04_scope_static_strings(
                    element,
                    bindings=bindings,
                    active_names=active_names,
                    depth=depth + 1,
                ),
            )
        _phase04_scope_checked_product(len(forward) + len(reverse))
        return _phase04_scope_bounded_strings([*forward, *reverse])
    if isinstance(node, ast.Dict):
        _phase04_scope_checked_product(len(node.keys), limit=256)
        keys: tuple[str, ...] = ()
        values: tuple[str, ...] = ()
        for key in node.keys:
            if key is not None:
                keys = combine(
                    keys,
                    _phase04_scope_static_strings(
                        key,
                        bindings=bindings,
                        active_names=active_names,
                        depth=depth + 1,
                    ),
                )
        for value in node.values:
            values = combine(
                values,
                _phase04_scope_static_strings(
                    value,
                    bindings=bindings,
                    active_names=active_names,
                    depth=depth + 1,
                ),
            )
        _phase04_scope_checked_product(len(keys) + len(values))
        return _phase04_scope_bounded_strings([*keys, *values])
    if isinstance(node, (ast.IfExp, ast.BoolOp)):
        candidates = (
            (node.body, node.orelse)
            if isinstance(node, ast.IfExp)
            else tuple(node.values)
        )
        _phase04_scope_checked_product(len(candidates))
        results = []
        for candidate in candidates:
            candidate_values = _phase04_scope_static_strings(
                candidate,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            )
            _phase04_scope_checked_product(
                len(results) + len(candidate_values)
            )
            results.extend(candidate_values)
        return _phase04_scope_bounded_strings(results)
    if isinstance(node, ast.NamedExpr):
        return _phase04_scope_static_strings(
            node.value,
            bindings=bindings,
            active_names=active_names,
            depth=depth + 1,
        )
    if isinstance(node, ast.Subscript):
        receivers = _phase04_scope_static_strings(
            node.value,
            bindings=bindings,
            active_names=active_names,
            depth=depth + 1,
        )
        results: list[str] = []
        if isinstance(node.slice, ast.Slice):
            bounds: list[tuple[int | None, ...]] = []
            for bound in (node.slice.lower, node.slice.upper, node.slice.step):
                if bound is None:
                    bounds.append((None,))
                    continue
                exact = tuple(
                    value
                    for value in _phase04_scope_static_scalars(
                        bound,
                        bindings=bindings,
                        active_names=active_names,
                        depth=depth + 1,
                    )
                    if type(value) is int
                )
                if not exact:
                    return ()
                bounds.append(exact)
            _phase04_scope_checked_product(
                len(receivers),
                len(bounds[0]),
                len(bounds[1]),
                len(bounds[2]),
            )
            for receiver in receivers:
                for lower in bounds[0]:
                    for upper in bounds[1]:
                        for step in bounds[2]:
                            if step == 0:
                                continue
                            results.append(receiver[slice(lower, upper, step)])
        else:
            indexes = _phase04_scope_static_scalars(
                node.slice,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            )
            _phase04_scope_checked_product(len(receivers), len(indexes))
            for receiver in receivers:
                for index in indexes:
                    if type(index) is int and -len(receiver) <= index < len(receiver):
                        results.append(receiver[index])
        return _phase04_scope_bounded_strings(results)
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in {"reversed", "sorted"}
            and len(node.args) == 1
            and not node.keywords
        ):
            results = []
            for value in _phase04_scope_static_strings(
                node.args[0],
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            ):
                results.append(
                    "".join(reversed(value))
                    if node.func.id == "reversed"
                    else "".join(sorted(value))
                )
            return _phase04_scope_bounded_strings(results)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "bytes"
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], (ast.List, ast.Tuple))
        ):
            _phase04_scope_checked_product(len(node.args[0].elts))
            rows: list[tuple[int, ...]] = [()]
            for element in node.args[0].elts:
                integers = tuple(
                    value
                    for value in _phase04_scope_static_scalars(
                        element,
                        bindings=bindings,
                        active_names=active_names,
                        depth=depth + 1,
                    )
                    if type(value) is int and 0 <= value <= 255
                )
                if len(rows) * len(integers) > 256:
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
                rows = [(*row, value) for row in rows for value in integers]
                if len(rows) > 256:
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
            decoded: list[str] = []
            for row in rows:
                try:
                    decoded.append(bytes(row).decode("utf-8"))
                except UnicodeDecodeError:
                    continue
            return _phase04_scope_bounded_strings(decoded)
        if isinstance(node.func, ast.Name) and node.func.id in {"str", "chr"}:
            results = []
            if len(node.args) == 1 and not node.keywords:
                for scalar in _phase04_scope_static_scalars(
                    node.args[0],
                    bindings=bindings,
                    active_names=active_names,
                    depth=depth + 1,
                ):
                    if node.func.id == "str":
                        results.append(
                            _phase04_scope_bounded_scalar_text(scalar)
                        )
                    elif type(scalar) is int and 0 <= scalar <= 0x10FFFF:
                        results.append(chr(scalar))
            return _phase04_scope_bounded_strings(results)
        if isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "bytes"
                and node.func.attr == "fromhex"
                and len(node.args) == 1
                and not node.keywords
            ):
                decoded = []
                for value in _phase04_scope_static_strings(
                    node.args[0],
                    bindings=bindings,
                    active_names=active_names,
                    depth=depth + 1,
                ):
                    try:
                        decoded.append(bytes.fromhex(value).decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        continue
                return _phase04_scope_bounded_strings(decoded)
            receivers = _phase04_scope_static_strings(
                node.func.value,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            )
            method = node.func.attr
            if method == "decode" and not node.keywords and len(node.args) <= 1:
                return receivers
            if method == "join" and len(node.args) == 1 and not node.keywords:
                return _phase04_scope_static_strings(
                    node.args[0],
                    bindings=bindings,
                    active_names=active_names,
                    depth=depth + 1,
                )
            if method == "casefold" and not node.args and not node.keywords:
                for receiver in receivers:
                    projected = 0
                    for character in receiver:
                        projected += _phase04_scope_utf8_size(character.casefold())
                        if projected > 65_536:
                            raise readiness.ReadinessContractError(
                                "Phase 04 scope expression differs"
                            )
                return _phase04_scope_bounded_strings(
                    [receiver.casefold() for receiver in receivers]
                )
            if method == "strip" and len(node.args) <= 1 and not node.keywords:
                characters: tuple[str | None, ...] = (None,)
                if node.args:
                    characters = tuple(
                        _phase04_scope_static_strings(
                            node.args[0],
                            bindings=bindings,
                            active_names=active_names,
                            depth=depth + 1,
                        )
                    )
                _phase04_scope_checked_product(len(receivers), len(characters))
                return _phase04_scope_bounded_strings(
                    [
                        receiver.strip(character)
                        for receiver in receivers
                        for character in characters
                    ]
                )
            if method in {"split", "splitlines"} and len(node.args) <= 1:
                separators: tuple[str | None, ...] = (None,)
                if node.args:
                    separators = tuple(
                        _phase04_scope_static_strings(
                            node.args[0],
                            bindings=bindings,
                            active_names=active_names,
                            depth=depth + 1,
                        )
                    )
                pieces: list[str] = []
                pieces_bytes = 0
                for receiver in receivers:
                    receiver_bytes = _phase04_scope_utf8_size(receiver)
                    for separator in separators:
                        if method == "splitlines":
                            projected_count = 1 + sum(
                                character
                                in "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"
                                for character in receiver
                            )
                        elif separator is None:
                            projected_count = sum(
                                1 for _ in re.finditer(r"\S+", receiver)
                            )
                        elif not separator:
                            continue
                        else:
                            projected_count = receiver.count(separator) + 1
                        if (
                            projected_count > 256
                            or len(pieces) + projected_count + 2 > 256
                            or pieces_bytes + 3 * receiver_bytes > 65_536
                        ):
                            raise readiness.ReadinessContractError(
                                "Phase 04 scope expression differs"
                            )
                        values = (
                            receiver.splitlines()
                            if method == "splitlines"
                            else receiver.split(separator)
                        )
                        values_bytes = sum(
                            _phase04_scope_utf8_size(value) for value in values
                        )
                        if pieces_bytes + 3 * values_bytes > 65_536:
                            raise readiness.ReadinessContractError(
                                "Phase 04 scope expression differs"
                            )
                        forward = "".join(values)
                        reverse = "".join(reversed(values))
                        pieces.extend(values)
                        pieces.extend((forward, reverse))
                        pieces_bytes += (
                            values_bytes
                            + _phase04_scope_utf8_size(forward)
                            + _phase04_scope_utf8_size(reverse)
                        )
                return _phase04_scope_bounded_strings(pieces)
            if method == "replace" and len(node.args) in {2, 3} and not node.keywords:
                old_values = _phase04_scope_static_strings(
                    node.args[0],
                    bindings=bindings,
                    active_names=active_names,
                    depth=depth + 1,
                )
                new_values = _phase04_scope_static_strings(
                    node.args[1],
                    bindings=bindings,
                    active_names=active_names,
                    depth=depth + 1,
                )
                counts: tuple[Any, ...] = (-1,)
                if len(node.args) == 3:
                    counts = _phase04_scope_static_scalars(
                        node.args[2],
                        bindings=bindings,
                        active_names=active_names,
                        depth=depth + 1,
                    )
                counts = tuple(count for count in counts if type(count) is int)
                _phase04_scope_checked_product(
                    len(receivers),
                    len(old_values),
                    len(new_values),
                    len(counts),
                )
                replaced: list[str] = []
                for receiver in receivers:
                    receiver_bytes = _phase04_scope_utf8_size(receiver)
                    for old in old_values:
                        occurrences = (
                            receiver.count(old) if old else len(receiver) + 1
                        )
                        for new in new_values:
                            new_bytes = _phase04_scope_utf8_size(new)
                            for count in counts:
                                applied = (
                                    occurrences
                                    if count < 0
                                    else min(occurrences, count)
                                )
                                if receiver_bytes + applied * new_bytes > 65_536:
                                    raise readiness.ReadinessContractError(
                                        "Phase 04 scope expression differs"
                                    )
                                replaced.append(receiver.replace(old, new, count))
                return _phase04_scope_bounded_strings(replaced)
            if method == "format" and not node.keywords:
                _phase04_scope_checked_product(len(node.args))
                rows: list[tuple[Any, ...]] = [()]
                for argument in node.args:
                    scalars = _phase04_scope_static_scalars(
                        argument,
                        bindings=bindings,
                        active_names=active_names,
                        depth=depth + 1,
                    )
                    if len(rows) * len(scalars) > 256:
                        raise readiness.ReadinessContractError(
                            "Phase 04 scope expression differs"
                        )
                    rows = [(*row, scalar) for row in rows for scalar in scalars]
                    if len(rows) > 256:
                        raise readiness.ReadinessContractError(
                            "Phase 04 scope expression differs"
                        )
                results = []
                if len(receivers) * len(rows) > 256:
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
                for receiver in receivers:
                    if not _phase04_scope_format_is_bounded(receiver):
                        raise readiness.ReadinessContractError(
                            "Phase 04 scope expression differs"
                        )
                    for row in rows:
                        projected = _phase04_scope_utf8_size(receiver) + sum(
                            _phase04_scope_utf8_size(
                                _phase04_scope_bounded_scalar_text(
                                    value,
                                    conversion="ascii",
                                )
                            )
                            for value in row
                        ) * max(1, receiver.count("{"))
                        projected += sum(
                            int(value)
                            for value in re.findall(r"[0-9]+", receiver)
                        )
                        if projected > 65_536:
                            raise readiness.ReadinessContractError(
                                "Phase 04 scope expression differs"
                            )
                        try:
                            results.append(receiver.format(*row))
                        except (IndexError, KeyError, TypeError, ValueError):
                            pass
                return _phase04_scope_bounded_strings(results)
        nested: list[str] = []
        nested_bytes = 0
        _phase04_scope_checked_product(len(node.args) + len(node.keywords))
        for argument in (*node.args, *(item.value for item in node.keywords)):
            for value in _phase04_scope_static_strings(
                argument,
                bindings=bindings,
                active_names=active_names,
                depth=depth + 1,
            ):
                nested_bytes += _phase04_scope_utf8_size(value)
                if len(nested) >= 256 or nested_bytes > 65_536:
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
                nested.append(value)
        return _phase04_scope_bounded_strings(
            ["".join(nested), "".join(reversed(nested))] if nested else []
        )
    if isinstance(node, ast.Attribute):
        return _phase04_scope_static_strings(
            node.value,
            bindings=bindings,
            active_names=active_names,
            depth=depth + 1,
        )
    return ()


_PHASE04_SCOPE_RECONSTRUCTION_TARGETS = tuple(
    sorted(
        {
            f"{prefix}{core}{suffix}"
            for prefix in ("", "table")
            for core in (
                "p5",
                "p05",
                "phase5",
                "phase05",
                "runningregion",
                "runningregions",
            )
            for suffix in ("", "enabled")
        },
        key=lambda value: (len(value), value),
    )
)


def _phase04_scope_fragments_reconstruct_forbidden(node: ast.AST) -> bool:
    atom_counts: dict[str, int] = {}
    for value in ast.walk(node):
        raw: str | None = None
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            raw = value.value
        elif isinstance(value, ast.Constant) and isinstance(value.value, bytes):
            if len(value.value) > 65_536:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            try:
                raw = value.value.decode("utf-8")
            except UnicodeDecodeError:
                raw = None
        elif (
            isinstance(value, ast.Constant)
            and type(value.value) is int
            and value.value in {0, 5}
        ):
            raw = str(value.value)
        if raw is None:
            continue
        if _phase04_scope_utf8_size(raw) > 65_536:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        compact = _phase04_scope_relevant_atom(
            _phase04_scope_compact_atom(raw)
        )
        if compact:
            atom_counts[compact] = min(atom_counts.get(compact, 0) + 1, 64)
        if len(atom_counts) > 4_096:
            raise readiness.ReadinessContractError(
                "Phase 04 scope reconstruction differs"
            )
    for target in _PHASE04_SCOPE_RECONSTRUCTION_TARGETS:
        counts: dict[str, int] = {}
        for atom, available in atom_counts.items():
            if len(atom) <= len(target) and atom in target:
                counts[atom] = min(available, len(target))
        fragments = tuple(sorted(counts))
        initial = tuple(counts[value] for value in fragments)
        stack: list[tuple[int, tuple[int, ...], int]] = [(0, initial, 0)]
        observed: set[tuple[int, tuple[int, ...], int]] = set()
        while stack:
            position, remaining, pieces = stack.pop()
            state = (position, remaining, min(pieces, 2))
            if state in observed:
                continue
            observed.add(state)
            if len(observed) > 4_096:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope reconstruction differs"
                )
            if position == len(target):
                if pieces >= 2:
                    return True
                continue
            for index, fragment in enumerate(fragments):
                if remaining[index] and target.startswith(fragment, position):
                    updated = list(remaining)
                    updated[index] -= 1
                    stack.append(
                        (position + len(fragment), tuple(updated), pieces + 1)
                    )
    return False


_PHASE04_SCOPE_TRANSFORM_CALLS = frozenset(
    {
        "casefold",
        "decode",
        "encode",
        "format",
        "join",
        "normalize",
        "pop",
        "replace",
        "reversed",
        "sort",
        "sorted",
        "split",
        "splitlines",
        "strip",
        "sub",
    }
)


def _phase04_scope_transform_reconstructs_forbidden(node: ast.AST) -> bool:
    bindings = _phase04_scope_static_bindings(node)
    transform_count = 0
    for value in ast.walk(node):
        if not isinstance(value, ast.Call):
            continue
        call_name = (
            value.func.id
            if isinstance(value.func, ast.Name)
            else value.func.attr
            if isinstance(value.func, ast.Attribute)
            else None
        )
        if call_name not in _PHASE04_SCOPE_TRANSFORM_CALLS:
            continue
        transform_count += 1
        if transform_count > 256:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        atoms: list[str] = []
        nested_count = 0
        for nested in ast.walk(value):
            nested_count += 1
            if nested_count > 256:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            raw: str | None = None
            if isinstance(nested, ast.Constant) and isinstance(nested.value, str):
                raw = nested.value
            elif isinstance(nested, ast.Constant) and isinstance(nested.value, bytes):
                if len(nested.value) > 65_536:
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
                try:
                    raw = nested.value.decode("utf-8")
                except UnicodeDecodeError:
                    raw = None
            if raw is None:
                continue
            if _phase04_scope_utf8_size(raw) > 65_536:
                raise readiness.ReadinessContractError(
                    "Phase 04 scope expression differs"
                )
            compact = _phase04_scope_relevant_atom(
                _phase04_scope_compact_atom(raw)
            )
            if compact:
                if len(atoms) >= 256:
                    raise readiness.ReadinessContractError(
                        "Phase 04 scope expression differs"
                    )
                atoms.append(compact)
        _phase04_scope_checked_product(
            len(value.args)
            + len(value.keywords)
            + int(isinstance(value.func, ast.Attribute))
        )
        argument_nodes: list[ast.AST] = [
            *value.args,
            *(keyword.value for keyword in value.keywords),
        ]
        if isinstance(value.func, ast.Attribute):
            argument_nodes.append(value.func.value)
        for argument in argument_nodes:
            for raw in _phase04_scope_static_strings(
                argument,
                bindings=bindings,
            ):
                compact = _phase04_scope_relevant_atom(
                    _phase04_scope_compact_atom(raw)
                )
                if compact:
                    if len(atoms) >= 256:
                        raise readiness.ReadinessContractError(
                            "Phase 04 scope expression differs"
                        )
                    atoms.append(compact)
        if any(
            target in atom
            for atom in atoms
            for target in _PHASE04_SCOPE_RECONSTRUCTION_TARGETS
        ):
            return True
        if call_name in {"pop", "reversed", "sort", "sorted", "split", "sub"}:
            available: dict[str, int] = {}
            for atom in atoms:
                for character in atom:
                    available[character] = min(
                        available.get(character, 0) + 1,
                        65_536,
                    )
            for target in _PHASE04_SCOPE_RECONSTRUCTION_TARGETS:
                required = {
                    character: target.count(character)
                    for character in set(target)
                }
                if required and all(
                    available.get(character, 0) >= count
                    for character, count in required.items()
                ):
                    return True
    return False


def _phase04_unknown_formatted_scope_is_forbidden(value: str) -> bool:
    if _PHASE04_UNKNOWN_FORMATTED_SCOPE_MARKER not in value:
        return False
    if value.count(_PHASE04_UNKNOWN_FORMATTED_SCOPE_MARKER) + 1 > 256:
        raise readiness.ReadinessContractError(
            "Phase 04 scope expression differs"
        )
    chunks = tuple(
        _phase04_scope_compact_atom(part)
        for part in value.split(_PHASE04_UNKNOWN_FORMATTED_SCOPE_MARKER)
    )
    if not any(chunks):
        return False
    for target in _PHASE04_SCOPE_RECONSTRUCTION_TARGETS:
        position = 0
        for chunk in chunks:
            if not chunk:
                continue
            found = target.find(chunk, position)
            if found < 0:
                break
            position = found + len(chunk)
        else:
            return True
    return False


def _phase04_scope_values(node: ast.AST) -> list[str]:
    values: list[str] = []
    values_bytes = 0

    def append_value(value: str) -> None:
        nonlocal values_bytes
        value_bytes = _phase04_scope_utf8_size(value)
        if (
            value_bytes > 65_536
            or len(values) >= 16_384
            or values_bytes + value_bytes > 2 * 1024 * 1024
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
        values_bytes += value_bytes
        values.append(value)

    walked: list[ast.AST] = []
    for value in ast.walk(node):
        walked.append(value)
        if len(walked) > 8_192:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics syntax resource differs"
            )
        if isinstance(value, ast.Name):
            append_value(value.id)
        elif isinstance(value, ast.arg):
            append_value(value.arg)
        elif isinstance(value, ast.keyword) and value.arg is not None:
            append_value(value.arg)
        elif isinstance(value, ast.alias):
            append_value(value.name)
            if value.asname is not None:
                append_value(value.asname)
        elif isinstance(value, ast.ImportFrom) and value.module is not None:
            append_value(value.module)
        elif isinstance(value, ast.Attribute):
            append_value(value.attr)
        elif isinstance(value, ast.Constant) and isinstance(value.value, str):
            append_value(value.value)
        elif isinstance(
            value,
            (
                ast.BinOp,
                ast.BoolOp,
                ast.Call,
                ast.Dict,
                ast.FormattedValue,
                ast.IfExp,
                ast.JoinedStr,
                ast.List,
                ast.NamedExpr,
                ast.Set,
                ast.Tuple,
            ),
        ):
            reconstructed = _phase04_scope_literal_fragments(value)
            if reconstructed is not None:
                append_value(reconstructed)
    bindings = _phase04_scope_static_bindings(node)
    roots: list[ast.AST] = []
    for value in walked:
        candidate: ast.AST | None = None
        if isinstance(value, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            candidate = value.value
        elif isinstance(value, (ast.Return, ast.Yield, ast.YieldFrom)):
            candidate = value.value
        elif isinstance(value, ast.Call):
            call_name = (
                value.func.id
                if isinstance(value.func, ast.Name)
                else value.func.attr
                if isinstance(value.func, ast.Attribute)
                else None
            )
            if call_name in _PHASE04_SCOPE_TRANSFORM_CALLS:
                candidate = value
        if candidate is not None and not (
            isinstance(candidate, ast.Constant)
            and not isinstance(candidate.value, (bytes, str))
        ):
            roots.append(candidate)
        if len(roots) > 8_192:
            raise readiness.ReadinessContractError(
                "Phase 04 scope expression differs"
            )
    for root in roots:
        for value in _phase04_scope_static_strings(root, bindings=bindings):
            append_value(value)
    return values


_PHASE04_SCOPE_PHASE05_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:phase|p)[\W_]*(?:0[\W_]*)?5"
    r"(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
_PHASE04_SCOPE_RUNNING_REGION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])running[\W_]*regions?(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)


def _phase04_scope_normalized_value(value: str) -> str:
    value = _phase04_scope_nfkc_bounded(value)
    normalized = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])|(?<=[0-9])(?=[A-Za-z])",
        "_",
        value,
    )
    compact_token = (
        r"(?:(?:phase|p)[\W_]*(?:0[\W_]*)?5|"
        r"running[\W_]*regions?)"
    )
    normalized = re.sub(
        rf"(?i)(table)(?={compact_token})",
        r"\1_",
        normalized,
    )
    return re.sub(
        rf"(?i)({compact_token})(?=enabled(?:\b|_))",
        r"\1_",
        normalized,
    )


def _phase04_scope_token_pattern(token: str) -> re.Pattern[str]:
    parts = [
        part
        for part in re.split(r"[\W_]+", token.casefold())
        if part
    ]
    body = r"[\W_]*".join(re.escape(part) for part in parts)
    return re.compile(
        rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])",
        flags=re.IGNORECASE,
    )


def _phase04_scope_value_is_forbidden(
    value: str,
    *,
    tokens: tuple[str, ...],
    token_patterns: tuple[re.Pattern[str], ...] | None = None,
) -> bool:
    normalized = _phase04_scope_normalized_value(value)
    if (
        _PHASE04_SCOPE_PHASE05_PATTERN.search(normalized)
        or _PHASE04_SCOPE_RUNNING_REGION_PATTERN.search(normalized)
    ):
        return True
    patterns = token_patterns or tuple(
        _phase04_scope_token_pattern(token) for token in tokens
    )
    return any(pattern.search(normalized) for pattern in patterns)


def _reject_phase04_scope_tokens(
    node: ast.AST,
    *,
    tokens: tuple[str, ...],
    label: str,
) -> None:
    node_count = 0
    for _ in ast.walk(node):
        node_count += 1
        if node_count > 8_192:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics syntax resource differs"
            )
    token_patterns = tuple(
        _phase04_scope_token_pattern(token) for token in tokens
    )
    scope_values = _phase04_scope_values(node)
    if (
        _phase04_scope_fragments_reconstruct_forbidden(node)
        or _phase04_scope_transform_reconstructs_forbidden(node)
        or any(
        _phase04_unknown_formatted_scope_is_forbidden(value)
        or
        _phase04_scope_value_is_forbidden(
            value,
            tokens=tokens,
            token_patterns=token_patterns,
        )
        for value in scope_values
        )
    ):
        raise readiness.ReadinessContractError(f"{label} scope differs")


def _hardened_phase04_tables_digests(raw: bytes) -> dict[str, str]:
    """Return the closed four-node vector for the table extraction surface."""

    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 table extraction custody differs"
        ) from exc
    allowed = set(EXPECTED_HARDENED_TABLES_ALLOWED_NODES)
    nodes: dict[str, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef] = {}
    retained: list[ast.stmt] = []
    for node in tree.body:
        name = getattr(node, "name", None)
        if name not in allowed:
            retained.append(node)
            continue
        if name in nodes or not isinstance(
            node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            raise readiness.ReadinessContractError(
                "hardened Phase 04 table extraction node set differs"
            )
        nodes[str(name)] = node
    if set(nodes) != allowed or not isinstance(nodes["RawTable"], ast.ClassDef):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 table extraction node set differs"
        )
    if any(
        isinstance(value, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and value is not node
        for node in nodes.values()
        for value in ast.walk(node)
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 table extraction nested definition differs"
        )
    retained_digest = _ast_digest(ast.Module(body=retained, type_ignores=[]))
    if retained_digest != EXPECTED_HARDENED_TABLES_RETAINED_MODULE_AST_SHA256:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 table extraction retained surface changed"
        )
    return {
        name: _ast_digest(nodes[name])
        for name in EXPECTED_HARDENED_TABLES_ALLOWED_NODES
    }


def _validate_hardened_phase04_tables_surface(raw: bytes) -> str:
    """Accept the atomic predecessor or reviewed geometry extraction vector."""

    digests = _hardened_phase04_tables_digests(raw)
    if digests == EXPECTED_HARDENED_TABLES_BASELINE_NODE_AST_SHA256:
        return "baseline"
    if digests != EXPECTED_HARDENED_TABLES_GEOMETRY_NODE_AST_SHA256:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 table extraction surface changed"
        )
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover - first pass
        raise readiness.ReadinessContractError(
            "hardened Phase 04 table extraction custody differs"
        ) from exc
    nodes = {
        str(getattr(node, "name")): node
        for node in tree.body
        if getattr(node, "name", None) in EXPECTED_HARDENED_TABLES_ALLOWED_NODES
    }
    for node in nodes.values():
        _reject_phase04_scope_tokens(
            node,
            tokens=FORBIDDEN_PHASE04_SCOPE_TOKENS,
            label="hardened Phase 04 table extraction",
        )
    return "geometry"


def _phase04_attribute_path(node: ast.AST) -> tuple[str, ...] | None:
    values: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        values.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    values.append(current.id)
    return tuple(reversed(values))


def _safe_phase04_table_binding(name: str, node: ast.AST) -> bool:
    if name not in EXPECTED_HARDENED_PHASE04_SETTING_NAMES:
        return False
    if isinstance(node, ast.Name):
        return node.id == name
    path = _phase04_attribute_path(node)
    return path in {("context", "settings", name), ("settings", name)}


def _phase04_call_name(node: ast.expr) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _validate_phase04_helper_call(
    call: ast.Call,
    *,
    function_name: str,
) -> str:
    name = _phase04_call_name(call.func)
    helpers = EXPECTED_HARDENED_PIPELINE_HELPER_CALLS[function_name]
    if name not in helpers:
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline helper call differs"
        )
    assert name is not None
    specification = helpers[name]
    positional_paths = tuple(_phase04_attribute_path(value) for value in call.args)
    if positional_paths != specification["positional_paths"]:
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline helper argument differs"
        )
    settings = tuple(str(value) for value in specification["settings"])
    if [keyword.arg for keyword in call.keywords] != list(settings):
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline helper argument differs"
        )
    for keyword, setting in zip(call.keywords, settings, strict=True):
        expected_binding = (
            ("context", "settings", setting)
            if function_name == "_analyze_shared_pages"
            else (setting,)
        )
        if _phase04_attribute_path(keyword.value) != expected_binding:
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper argument differs"
            )
    _reject_phase04_scope_tokens(
        call,
        tokens=FORBIDDEN_PHASE04_SCOPE_TOKENS,
        label="Phase 04 pipeline helper",
    )
    return name


def _normalize_phase04_helper_statement(
    statement: ast.stmt,
    *,
    function_name: str,
) -> ast.stmt | None:
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
        name = _validate_phase04_helper_call(
            statement.value, function_name=function_name
        )
        if EXPECTED_HARDENED_PIPELINE_HELPER_CALLS[function_name][name][
            "form"
        ] != "expr":
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper statement differs"
            )
        return None
    if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call):
        if len(statement.targets) != 1 or not isinstance(
            statement.targets[0], ast.Name
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper assignment differs"
            )
        target = statement.targets[0].id
        name = _validate_phase04_helper_call(
            statement.value, function_name=function_name
        )
        if EXPECTED_HARDENED_PIPELINE_HELPER_CALLS[function_name][name][
            "form"
        ] != "assign":
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper statement differs"
            )
        if (
            not statement.value.args
            or not isinstance(statement.value.args[0], ast.Name)
            or statement.value.args[0].id != target
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper assignment differs"
            )
        return None
    return statement


class _StripPhase04TableKeywords(ast.NodeTransformer):
    def __init__(self, function_name: str) -> None:
        self.function_name = function_name
        self.observed: set[str] = set()

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        retained: list[ast.keyword] = []
        target = _phase04_call_name(node.func)
        allowed = EXPECTED_HARDENED_PIPELINE_FORWARDING_CALLS[
            self.function_name
        ].get(str(target), frozenset())
        for keyword in node.keywords:
            if keyword.arg not in EXPECTED_HARDENED_PHASE04_SETTING_NAMES:
                retained.append(keyword)
                continue
            expected_binding = (
                ("context", "settings", keyword.arg)
                if self.function_name == "_analyze_shared_pages"
                else (keyword.arg,)
            )
            if (
                keyword.arg not in allowed
                or _phase04_attribute_path(keyword.value) != expected_binding
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 pipeline keyword argument differs"
                )
            self.observed.add(keyword.arg)
        node.keywords = retained
        return node


def _normalize_hardened_phase04_pipeline_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    direct_imports = {
        id(statement) for statement in node.body if isinstance(statement, ast.ImportFrom)
    }
    if any(
        id(value) not in direct_imports
        for value in ast.walk(node)
        if isinstance(value, (ast.Import, ast.ImportFrom))
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline nested import differs"
        )

    allowed_helpers = EXPECTED_HARDENED_PIPELINE_HELPER_CALLS[node.name]
    import_positions = [
        index
        for index, statement in enumerate(node.body)
        if isinstance(statement, (ast.Import, ast.ImportFrom))
    ]
    prefix = 1 if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ) else 0
    if import_positions and import_positions != list(
        range(prefix, prefix + len(import_positions))
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline import position differs"
        )

    helper_names: list[str] = []
    retained_body: list[ast.stmt] = []
    for statement in node.body:
        if isinstance(statement, ast.Import):
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline import differs"
            )
        if isinstance(statement, ast.ImportFrom):
            if (
                statement.level != 0
                or statement.module != "app.services.table_semantics"
                or not statement.names
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 pipeline import differs"
                )
            for alias in statement.names:
                name = alias.name
                if (
                    alias.asname is not None
                    or name not in allowed_helpers
                    or name in helper_names
                ):
                    raise readiness.ReadinessContractError(
                        "Phase 04 pipeline helper import differs"
                    )
                helper_names.append(name)
            _reject_phase04_scope_tokens(
                statement,
                tokens=FORBIDDEN_PHASE04_SCOPE_TOKENS,
                label="Phase 04 pipeline import",
            )
            continue
        retained_body.append(statement)

    if any(
        argument.arg in EXPECTED_HARDENED_PHASE04_SETTING_NAMES
        for argument in (*node.args.posonlyargs, *node.args.args)
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline signature differs"
        )
    signature_positions = [
        index
        for index, argument in enumerate(node.args.kwonlyargs)
        if argument.arg in EXPECTED_HARDENED_PHASE04_SETTING_NAMES
    ]
    observed_signature_flags = [
        node.args.kwonlyargs[index].arg for index in signature_positions
    ]
    expected_signature_order = [
        name
        for name in EXPECTED_HARDENED_PHASE04_SETTING_ORDER
        if name in EXPECTED_HARDENED_PIPELINE_SIGNATURE_FLAGS[node.name]
        and name in observed_signature_flags
    ]
    if (
        observed_signature_flags != expected_signature_order
        or signature_positions
        and signature_positions
        != list(
            range(
                len(node.args.kwonlyargs) - len(signature_positions),
                len(node.args.kwonlyargs),
            )
        )
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline signature position differs"
        )
    required_helper_flags = {
        str(setting)
        for name in helper_names
        for setting in allowed_helpers[name]["settings"]
    }
    if node.name != "_analyze_shared_pages" and not required_helper_flags <= set(
        observed_signature_flags
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline helper flag binding differs"
        )

    kwonlyargs: list[ast.arg] = []
    kw_defaults: list[ast.expr | None] = []
    for argument, default in zip(
        node.args.kwonlyargs,
        node.args.kw_defaults,
        strict=True,
    ):
        if argument.arg not in EXPECTED_HARDENED_PHASE04_SETTING_NAMES:
            kwonlyargs.append(argument)
            kw_defaults.append(default)
            continue
        if (
            argument.arg
            not in EXPECTED_HARDENED_PIPELINE_SIGNATURE_FLAGS[node.name]
            or
            not isinstance(argument.annotation, ast.Name)
            or argument.annotation.id != "bool"
            or not isinstance(default, ast.Constant)
            or default.value is not False
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline signature differs"
            )
    node.args.kwonlyargs = kwonlyargs
    node.args.kw_defaults = kw_defaults

    normalized_body: list[ast.stmt] = []
    observed_helpers: list[str] = []
    helper_positions: dict[str, int] = {}
    for statement_index, statement in enumerate(retained_body):
        called_names = {
            name
            for value in ast.walk(statement)
            if isinstance(value, ast.Call)
            and (name := _phase04_call_name(value.func)) in set(helper_names)
        }
        if called_names:
            if len(called_names) != 1:
                raise readiness.ReadinessContractError(
                    "Phase 04 pipeline helper statement differs"
                )
            normalized = _normalize_phase04_helper_statement(
                statement,
                function_name=node.name,
            )
            name = next(iter(called_names))
            if name in helper_positions:
                raise readiness.ReadinessContractError(
                    "Phase 04 pipeline helper usage differs"
                )
            helper_positions[name] = statement_index
            observed_helpers.append(name)
            if normalized is not None:
                normalized_body.append(normalized)
            continue
        normalized_body.append(statement)
    if set(observed_helpers) != set(helper_names):
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline helper usage differs"
        )
    if node.name == "_docling_table_item":
        if "prepare_docling_table_input" in helper_positions and (
            helper_positions["prepare_docling_table_input"] != 0
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper position differs"
            )
        if "prepare_docling_table" in helper_positions and (
            helper_positions["prepare_docling_table"] != len(retained_body) - 2
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper position differs"
            )
    elif node.name == "_vector_table_item":
        if "prepare_vector_table" in helper_positions and (
            helper_positions["prepare_vector_table"] != len(retained_body) - 2
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper position differs"
            )
    elif node.name == "_merge_tables":
        if "reconcile_table_candidates" in helper_positions and (
            helper_positions["reconcile_table_candidates"]
            != len(retained_body) - 2
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper position differs"
            )
    elif node.name == "_analyze_shared_pages":
        merge_position = next(
            (
                index
                for index, statement in enumerate(retained_body)
                if isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == "tables"
                and isinstance(statement.value, ast.Call)
                and _phase04_call_name(statement.value.func) == "_merge_tables"
            ),
            -1,
        )
        if "gate_table_candidates" in helper_positions and (
            helper_positions["gate_table_candidates"] != merge_position + 1
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 pipeline helper position differs"
            )
        suffix = [
            name
            for name in ("seal_table_pages", "merge_continued_tables")
            if name in helper_positions
        ]
        if suffix:
            suffix_positions = [helper_positions[name] for name in suffix]
            if suffix_positions != list(
                range(len(retained_body) - len(suffix), len(retained_body))
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 pipeline helper position differs"
                )
    node.body = normalized_body
    keyword_stripper = _StripPhase04TableKeywords(node.name)
    node = keyword_stripper.visit(node)
    if node.name != "_analyze_shared_pages" and not keyword_stripper.observed <= set(
        observed_signature_flags
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 pipeline forwarding flag binding differs"
        )
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ast.fix_missing_locations(node)
    return node


def _normalize_hardened_pipeline_table_repair(tree: ast.Module) -> str:
    """Restore one complete reviewed table-word vector to its predecessor AST."""

    if _ast_digest(tree) == EXPECTED_CURRENT_FROZEN_P04_US01_PIPELINE_IDENTITY.get(
        "ast_sha256"
    ):
        return "second_additive"
    if _ast_digest(tree) == EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_IDENTITY.get(
        "ast_sha256"
    ):
        # The final partitioned recovery implementation is admitted only as
        # the complete reviewed module AST.  It is never reconstructed from a
        # partial helper/block match, so mixed or mutated partitions fall
        # through to the older closed vectors and fail there.
        return "second_additive"

    repair_names = {
        "_table_repair_page_indexes",
        "_extract_table_repair_words",
    }
    top_level_repairs = {
        str(node.name): node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in repair_names
    }
    all_repairs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in repair_names
    ]
    if (
        set(top_level_repairs) != repair_names
        or len(all_repairs) != len(repair_names)
        or any(
            top_level_repairs.get(str(node.name)) is not node
            for node in all_repairs
        )
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline table repair node set differs"
        )

    parse_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_parse_loaded_document"
    ]
    if (
        len(parse_functions) != 1
        or parse_functions[0] not in tree.body
        or not isinstance(parse_functions[0], ast.FunctionDef)
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline table repair function differs"
        )
    parse_function = parse_functions[0]
    repair_tries = [
        statement
        for statement in ast.walk(parse_function)
        if isinstance(statement, ast.Try)
        and any(
            isinstance(value, ast.Name)
            and isinstance(value.ctx, ast.Store)
            and value.id == "table_repair_words"
            for value in ast.walk(statement)
        )
    ]
    if len(repair_tries) != 1 or repair_tries[0] not in parse_function.body:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline table repair block differs"
        )
    repair_try = repair_tries[0]
    observed = {
        "_table_repair_page_indexes": _ast_digest(
            top_level_repairs["_table_repair_page_indexes"]
        ),
        "_extract_table_repair_words": _ast_digest(
            top_level_repairs["_extract_table_repair_words"]
        ),
        "_parse_loaded_document.table_repair_words": _ast_digest(repair_try),
    }
    baseline_sources = {
        "_table_repair_page_indexes": (
            EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_PAGE_INDEX_SOURCE
        ),
        "_extract_table_repair_words": (
            EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_EXTRACT_SOURCE
        ),
    }
    baseline_nodes = {
        name: ast.parse(source).body[0]
        for name, source in baseline_sources.items()
    }
    baseline_try = ast.parse(
        EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_TRY_SOURCE
    ).body[0]
    reconstructed_baseline = {
        name: _ast_digest(node) for name, node in baseline_nodes.items()
    }
    reconstructed_baseline[
        "_parse_loaded_document.table_repair_words"
    ] = _ast_digest(baseline_try)
    if (
        reconstructed_baseline
        != EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_AST_SHA256
        or _ast_digest(
            ast.parse(
                EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_TRY_SOURCE
            ).body[0]
        )
        != EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_AST_SHA256[
            "_parse_loaded_document.table_repair_words"
        ]
        or set(EXPECTED_SECOND_ADDITIVE_PIPELINE_TABLE_REPAIR_AST_SHA256)
        != set(EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_AST_SHA256)
        or EXPECTED_SECOND_ADDITIVE_PIPELINE_TABLE_REPAIR_AST_SHA256[
            "_table_repair_page_indexes"
        ]
        != EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_AST_SHA256[
            "_table_repair_page_indexes"
        ]
        or EXPECTED_SECOND_ADDITIVE_PIPELINE_TABLE_REPAIR_AST_SHA256[
            "_parse_loaded_document.table_repair_words"
        ]
        != EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_AST_SHA256[
            "_parse_loaded_document.table_repair_words"
        ]
        or EXPECTED_SECOND_ADDITIVE_PIPELINE_TABLE_REPAIR_AST_SHA256[
            "_extract_table_repair_words"
        ]
        == EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_AST_SHA256[
            "_extract_table_repair_words"
        ]
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline table repair contract differs"
        )
    if observed == EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_AST_SHA256:
        return "baseline"
    if observed == EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_AST_SHA256:
        state = "bounded"
    elif observed == EXPECTED_SECOND_ADDITIVE_PIPELINE_TABLE_REPAIR_AST_SHA256:
        state = "second_additive"
    else:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline table repair surface changed"
        )

    for name, baseline_node in baseline_nodes.items():
        candidate = top_level_repairs[name]
        tree.body[tree.body.index(candidate)] = baseline_node
    parse_function.body[parse_function.body.index(repair_try)] = baseline_try
    ast.fix_missing_locations(tree)
    return state


def _normalize_hardened_pipeline_vector_extraction(tree: ast.Module) -> None:
    """Restore the one reviewed geometry-threading try to its predecessor AST."""

    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_parse_loaded_document"
    ]
    if len(functions) != 1:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline vector extraction function differs"
        )
    function = functions[0]
    candidates = [
        statement
        for statement in function.body
        if isinstance(statement, ast.Try)
        and any(
            isinstance(value, ast.Name)
            and isinstance(value.ctx, ast.Store)
            and value.id == "vector_tables"
            for value in ast.walk(statement)
        )
    ]
    if len(candidates) != 1:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline vector extraction block differs"
        )
    candidate = candidates[0]
    baseline = ast.parse(
        EXPECTED_HARDENED_PIPELINE_VECTOR_BASELINE_TRY_SOURCE
    ).body[0]
    geometry = ast.parse(
        EXPECTED_HARDENED_PIPELINE_VECTOR_GEOMETRY_TRY_SOURCE
    ).body[0]
    candidate_digest = _ast_digest(candidate)
    if (
        _ast_digest(baseline)
        != EXPECTED_HARDENED_PIPELINE_VECTOR_BASELINE_TRY_AST_SHA256
        or _ast_digest(geometry)
        != EXPECTED_HARDENED_PIPELINE_VECTOR_GEOMETRY_TRY_AST_SHA256
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline vector extraction contract differs"
        )
    if candidate_digest == (
        EXPECTED_HARDENED_PIPELINE_VECTOR_BASELINE_TRY_AST_SHA256
    ):
        return
    if candidate_digest != (
        EXPECTED_HARDENED_PIPELINE_VECTOR_GEOMETRY_TRY_AST_SHA256
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline vector extraction block differs"
        )
    function.body[function.body.index(candidate)] = baseline
    ast.fix_missing_locations(tree)


def _hardened_phase04_pipeline_digests(
    raw: bytes,
) -> tuple[str, dict[str, str]]:
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline custody differs"
        ) from exc
    current_identity = EXPECTED_CURRENT_FROZEN_P04_US01_PIPELINE_IDENTITY
    if _ast_digest(tree) == current_identity["ast_sha256"]:
        if (
            len(raw) != current_identity["size_bytes"]
            or hashlib.sha256(raw).hexdigest() != current_identity["raw_sha256"]
        ):
            raise readiness.ReadinessContractError(
                "current-frozen P04-US01 pipeline custody differs"
            )
        return (
            EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_MODULE_AST_SHA256,
            dict(EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_FUNCTION_AST_SHA256),
        )
    if _ast_digest(tree) == EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_IDENTITY.get(
        "ast_sha256"
    ):
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in EXPECTED_HARDENED_PHASE04_PIPELINE_FUNCTIONS
        }
        observed = {name: _ast_digest(node) for name, node in functions.items()}
        if (
            set(functions) != set(EXPECTED_HARDENED_PHASE04_PIPELINE_FUNCTIONS)
            or observed
            != EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_FUNCTION_AST_SHA256
            or EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_MODULE_AST_SHA256
            != EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_IDENTITY["ast_sha256"]
        ):
            raise readiness.ReadinessContractError(
                "second-additive P04-US01 pipeline contract differs"
            )
        return (
            EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_MODULE_AST_SHA256,
            observed,
        )
    _normalize_hardened_pipeline_table_repair(tree)
    _normalize_hardened_pipeline_vector_extraction(tree)
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    retained: list[ast.stmt] = []
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in EXPECTED_HARDENED_PHASE04_PIPELINE_FUNCTIONS
        ):
            if node.name in functions:
                raise readiness.ReadinessContractError(
                    "hardened Phase 04 pipeline function set differs"
                )
            functions[node.name] = node
            continue
        retained.append(node)
    if set(functions) != set(EXPECTED_HARDENED_PHASE04_PIPELINE_FUNCTIONS):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 pipeline function set differs"
        )
    module_digest = _ast_digest(ast.Module(body=retained, type_ignores=[]))
    function_digests = {
        name: _ast_digest(_normalize_hardened_phase04_pipeline_function(node))
        for name, node in functions.items()
    }
    return module_digest, function_digests


def _validate_hardened_phase04_pipeline_surface(raw: bytes) -> str:
    module_digest, function_digests = _hardened_phase04_pipeline_digests(raw)
    additive_module = (
        EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_MODULE_AST_SHA256
    )
    additive_functions = (
        EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_FUNCTION_AST_SHA256
    )
    if additive_module or additive_functions:
        if (
            not additive_module
            or not additive_functions
            or set(additive_functions)
            != set(EXPECTED_HARDENED_PIPELINE_FUNCTION_AST_SHA256)
            or additive_module
            != EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_IDENTITY.get(
                "ast_sha256"
            )
            or additive_module == EXPECTED_HARDENED_PIPELINE_MODULE_AST_SHA256
            or any(
                type(digest) is not str
                or len(digest) != 64
                or set(digest) - set("0123456789abcdef")
                for digest in (additive_module, *additive_functions.values())
            )
        ):
            raise readiness.ReadinessContractError(
                "second-additive P04-US01 pipeline contract differs"
            )
    if (
        module_digest == EXPECTED_HARDENED_PIPELINE_MODULE_AST_SHA256
        and function_digests == EXPECTED_HARDENED_PIPELINE_FUNCTION_AST_SHA256
    ):
        return "baseline"
    if (
        additive_module
        and module_digest == additive_module
        and function_digests == additive_functions
    ):
        return "second_additive"

    raise readiness.ReadinessContractError(
        "hardened Phase 04 pipeline surface changed"
    )


def _normalize_exact_phase04_hook(
    raw: bytes,
    *,
    baseline: Mapping[str, Any],
    hook: str,
    function_name: str,
    expected_module_ast_sha256: str,
    expected_function_ast_sha256: str,
    insertion_offset: int,
    label: str,
) -> tuple[str, str]:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise readiness.ReadinessContractError(f"{label} custody differs") from exc
    if source.count(hook) not in {0, 1}:
        raise readiness.ReadinessContractError(f"{label} hook differs")
    if hook in source and source.index(hook) != insertion_offset:
        raise readiness.ReadinessContractError(f"{label} hook differs")
    normalized = source.replace(hook, "", 1)
    normalized_raw = normalized.encode("utf-8")
    if (
        len(normalized_raw) != baseline["size_bytes"]
        or hashlib.sha256(normalized_raw).hexdigest() != baseline["sha256"]
    ):
        raise readiness.ReadinessContractError(f"{label} custody differs")
    try:
        ast.parse(source)
        tree = ast.parse(normalized)
    except SyntaxError as exc:
        raise readiness.ReadinessContractError(f"{label} AST differs") from exc
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if (
        len(functions) != 1
        or _ast_digest(tree) != expected_module_ast_sha256
        or _ast_digest(functions[0]) != expected_function_ast_sha256
    ):
        raise readiness.ReadinessContractError(f"{label} AST differs")
    return hashlib.sha256(normalized_raw).hexdigest(), _ast_digest(functions[0])


def _hardened_source_alignment_digests(raw: bytes) -> tuple[str, str]:
    baseline_path = Path(EXPECTED_HARDENED_SOURCE_ALIGNMENT_IDENTITY["path"])
    baseline_source = None
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise readiness.ReadinessContractError(
            "hardened source alignment custody differs"
        ) from exc
    marker = '    table["csv"] = _table_csv(rows)\n'
    function_start = source.find("def _refresh_table(")
    marker_index = source.find(marker, function_start)
    if function_start < 0 or marker_index < 0:
        raise readiness.ReadinessContractError(
            "hardened source alignment hook differs"
        )
    insertion_offset = marker_index + len(marker)
    return _normalize_exact_phase04_hook(
        raw,
        baseline={
            **EXPECTED_HARDENED_SOURCE_ALIGNMENT_IDENTITY,
            "path": str(baseline_path),
        },
        hook=EXPECTED_HARDENED_SOURCE_ALIGNMENT_HOOK,
        function_name="_refresh_table",
        expected_module_ast_sha256=(
            EXPECTED_HARDENED_SOURCE_ALIGNMENT_MODULE_AST_SHA256
        ),
        expected_function_ast_sha256=(
            EXPECTED_HARDENED_SOURCE_ALIGNMENT_REFRESH_AST_SHA256
        ),
        insertion_offset=insertion_offset,
        label="hardened source alignment",
    )


def _hardened_text_reconciliation_digests(raw: bytes) -> tuple[str, str]:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise readiness.ReadinessContractError(
            "hardened text reconciliation custody differs"
        ) from exc
    function_start = source.find("def _ir_replace_owner_text(")
    signature_end = source.find(") -> None:\n", function_start)
    if function_start < 0 or signature_end < 0:
        raise readiness.ReadinessContractError(
            "hardened text reconciliation hook differs"
        )
    insertion_offset = signature_end + len(") -> None:\n")
    return _normalize_exact_phase04_hook(
        raw,
        baseline=EXPECTED_HARDENED_TEXT_RECONCILIATION_IDENTITY,
        hook=EXPECTED_HARDENED_TEXT_RECONCILIATION_HOOK,
        function_name="_ir_replace_owner_text",
        expected_module_ast_sha256=(
            EXPECTED_HARDENED_TEXT_RECONCILIATION_MODULE_AST_SHA256
        ),
        expected_function_ast_sha256=(
            EXPECTED_HARDENED_TEXT_RECONCILIATION_FUNCTION_AST_SHA256
        ),
        insertion_offset=insertion_offset,
        label="hardened text reconciliation",
    )


def _phase04_static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _phase04_static_string(node.left)
        right = _phase04_static_string(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        values: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            values.append(value.value)
        return "".join(values)
    return None


def _phase04_bounded_loop_iter(node: ast.AST, integer_limits: Mapping[str, int]) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "_bounded_table_iterable":
            if len(node.args) != 2 or node.keywords:
                return False
            limit = node.args[1]
            if isinstance(limit, ast.Constant) and type(limit.value) is int:
                return 0 <= limit.value <= 65_536
            return isinstance(limit, ast.Name) and (
                0 <= integer_limits.get(limit.id, -1) <= 65_536
            )
        if node.func.id == "enumerate":
            return len(node.args) in {1, 2} and not node.keywords and (
                _phase04_bounded_loop_iter(node.args[0], integer_limits)
            )
        if node.func.id == "zip":
            return bool(node.args) and not node.keywords and all(
                _phase04_bounded_loop_iter(value, integer_limits)
                for value in node.args
            )
    return False


def _phase04_loop_iteration_ceiling(
    node: ast.AST,
    integer_limits: Mapping[str, int],
) -> int | None:
    """Return a conservative maximum iteration count for an accepted loop."""

    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    if node.func.id == "_bounded_table_iterable":
        if len(node.args) != 2 or node.keywords:
            return None
        limit = _phase04_static_integer(node.args[1], integer_limits)
        return limit if limit is not None and 0 <= limit <= 65_536 else None
    if node.func.id == "enumerate":
        if len(node.args) not in {1, 2} or node.keywords:
            return None
        return _phase04_loop_iteration_ceiling(node.args[0], integer_limits)
    if node.func.id == "zip":
        if not node.args or node.keywords:
            return None
        ceilings = [
            _phase04_loop_iteration_ceiling(argument, integer_limits)
            for argument in node.args
        ]
        if any(ceiling is None for ceiling in ceilings):
            return None
        return min(int(ceiling) for ceiling in ceilings if ceiling is not None)
    return None


def _phase04_literal_only(node: ast.AST | None) -> bool:
    if node is None:
        return True
    count = 0
    for value in ast.walk(node):
        count += 1
        if count > 32_768:
            return False
        if isinstance(value, ast.Constant):
            continue
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            continue
        if isinstance(value, ast.Dict):
            if any(key is None for key in value.keys):
                return False
            continue
        if isinstance(value, ast.UnaryOp) and isinstance(
            value.op, (ast.UAdd, ast.USub)
        ):
            continue
        if isinstance(value, ast.BinOp) and isinstance(
            value.op, (ast.Add, ast.Sub)
        ):
            continue
        if isinstance(
            value,
            (ast.Add, ast.Load, ast.Sub, ast.UAdd, ast.USub),
        ):
            continue
        return False
    return True


def _phase04_static_integer(
    node: ast.AST,
    integer_limits: Mapping[str, int],
) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Name):
        return integer_limits.get(node.id)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return (
            node.operand.value
            if isinstance(node.op, ast.UAdd)
            else -node.operand.value
        )
    return None


def _phase04_range_size_bound(
    node: ast.Call,
    integer_limits: Mapping[str, int],
) -> int | None:
    if node.keywords or not 1 <= len(node.args) <= 3:
        return None
    values = [
        _phase04_static_integer(argument, integer_limits)
        for argument in node.args
    ]
    if any(value is None for value in values):
        return None
    concrete = [int(value) for value in values if value is not None]
    if len(concrete) == 1:
        start, stop, step = 0, concrete[0], 1
    elif len(concrete) == 2:
        start, stop, step = concrete[0], concrete[1], 1
    else:
        start, stop, step = concrete
    if step == 0:
        return None
    if step > 0:
        if stop <= start:
            return 0
        return (stop - start + step - 1) // step
    if stop >= start:
        return 0
    positive_step = -step
    return (start - stop + positive_step - 1) // positive_step


def _phase04_sequence_size_bound(
    node: ast.AST,
    *,
    integer_limits: Mapping[str, int],
    sequence_limits: Mapping[str, int],
) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) in (str, bytes):
        return len(node.value)
    if isinstance(node, (ast.List, ast.Tuple)):
        return len(node.elts)
    if isinstance(node, ast.Name):
        return sequence_limits.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _phase04_sequence_size_bound(
            node.left,
            integer_limits=integer_limits,
            sequence_limits=sequence_limits,
        )
        right = _phase04_sequence_size_bound(
            node.right,
            integer_limits=integer_limits,
            sequence_limits=sequence_limits,
        )
        if left is not None and right is not None:
            return left + right
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _phase04_sequence_size_bound(
            node.left,
            integer_limits=integer_limits,
            sequence_limits=sequence_limits,
        )
        right = _phase04_static_integer(node.right, integer_limits)
        if left is not None and right is not None and right >= 0:
            return left * right
        right_sequence = _phase04_sequence_size_bound(
            node.right,
            integer_limits=integer_limits,
            sequence_limits=sequence_limits,
        )
        left_integer = _phase04_static_integer(node.left, integer_limits)
        if (
            right_sequence is not None
            and left_integer is not None
            and left_integer >= 0
        ):
            return right_sequence * left_integer
        return None
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    if node.func.id == "_bounded_table_iterable":
        if len(node.args) != 2 or node.keywords:
            return None
        limit = _phase04_static_integer(node.args[1], integer_limits)
        return limit if limit is not None and 0 <= limit <= 65_536 else None
    if node.func.id == "range":
        return _phase04_range_size_bound(node, integer_limits)
    if node.func.id in {"list", "tuple"}:
        if node.keywords or len(node.args) > 1:
            return None
        if not node.args:
            return 0
        return _phase04_sequence_size_bound(
            node.args[0],
            integer_limits=integer_limits,
            sequence_limits=sequence_limits,
        )
    if node.func.id == "bytes":
        if node.keywords or len(node.args) > 1:
            return None
        if not node.args:
            return 0
        size = _phase04_static_integer(node.args[0], integer_limits)
        if size is not None:
            return size if size >= 0 else None
        return _phase04_sequence_size_bound(
            node.args[0],
            integer_limits=integer_limits,
            sequence_limits=sequence_limits,
        )
    return None


def _phase04_bounded_plain_string(
    node: ast.AST,
    *,
    proven: set[str],
    local_callables: set[str],
) -> bool:
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return len(node.value) <= 65_536
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_bounded_table_text"
        and len(node.args) == 1
        and not node.keywords
        and _phase04_expression_is_plain(
            node.args[0],
            proven=proven,
            local_callables=local_callables,
        )
    )


def _phase04_literal_number(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return type(node.value) in {int, float}
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) in {int, float}
    )


def _phase04_proved_numeric(
    node: ast.AST,
    numeric_names: set[str],
) -> bool:
    if _phase04_literal_number(node):
        return True
    if isinstance(node, ast.Name):
        return node.id in numeric_names
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.UAdd, ast.USub)) and (
            _phase04_proved_numeric(node.operand, numeric_names)
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "perf_counter":
            return not node.args and not node.keywords
        if node.func.id == "len":
            return len(node.args) == 1 and not node.keywords
        if node.func.id in {"Decimal", "float", "int"}:
            return all(
                _phase04_literal_only(argument) for argument in node.args
            ) and all(
                keyword.arg is not None
                and _phase04_literal_only(keyword.value)
                for keyword in node.keywords
            )
    if isinstance(node, ast.BinOp) and isinstance(
        node.op,
        (ast.Add, ast.Div, ast.FloorDiv, ast.Mod, ast.Mult, ast.Sub),
    ):
        return _phase04_proved_numeric(
            node.left, numeric_names
        ) and _phase04_proved_numeric(node.right, numeric_names)
    return False


def _validate_phase04_operational_inputs(
    node: ast.FunctionDef,
    *,
    proven: set[str],
    local_callables: set[str],
) -> None:
    values = (
        value
        for statement in node.body
        for value in ast.walk(statement)
    )
    for value in values:
        if (
            isinstance(value, ast.Attribute)
            and value.attr in FORBIDDEN_TABLE_SEMANTICS_BULK_METHODS
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics bulk mutation differs"
            )
        if (
            isinstance(value, ast.Subscript)
            and not isinstance(value.ctx, ast.Store)
            and not (
                isinstance(value.slice, ast.Constant)
                and type(value.slice.value) in {int, str}
            )
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics operational subscript differs"
            )
        if isinstance(value, ast.FormattedValue) and (
            value.format_spec is not None
            and _phase04_static_string(value.format_spec) is None
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics format specification differs"
            )
        if not isinstance(value, ast.Call):
            continue
        if (
            isinstance(value.func, ast.Name)
            and value.func.id in {"Decimal", "float", "int"}
            and (
                any(not _phase04_literal_only(argument) for argument in value.args)
                or any(
                    keyword.arg is None
                    or not _phase04_literal_only(keyword.value)
                    for keyword in value.keywords
                )
            )
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics numeric conversion differs"
            )
        if not isinstance(value.func, ast.Attribute):
            continue
        if value.func.attr == "decode" and not (
            isinstance(value.func.value, ast.Constant)
            and type(value.func.value.value) is bytes
            and not value.keywords
            and (
                not value.args
                or (
                    len(value.args) == 1
                    and isinstance(value.args[0], ast.Constant)
                    and value.args[0].value == "utf-8"
                )
            )
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics text decoding differs"
            )
        if value.func.attr == "encode":
            receiver = value.func.value
            if not (
                isinstance(receiver, ast.Call)
                and isinstance(receiver.func, ast.Name)
                and receiver.func.id == "_bounded_table_text"
                and len(receiver.args) == 1
                and not receiver.keywords
                and _phase04_expression_is_plain(
                    receiver.args[0],
                    proven=proven,
                    local_callables=local_callables,
                )
                and len(value.args) == 1
                and isinstance(value.args[0], ast.Constant)
                and value.args[0].value == "utf-8"
                and not value.keywords
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics text encoding differs"
                )


def _validate_phase04_incremental_mutations(
    node: ast.FunctionDef,
    *,
    integer_limits: Mapping[str, int],
    local_callables: set[str],
    proven: set[str],
) -> int:
    """Admit only empty, local, statically bounded growing accumulators."""

    parents = {
        child: parent
        for parent in ast.walk(node)
        for child in ast.iter_child_nodes(parent)
    }
    top_level_positions = {
        statement: index for index, statement in enumerate(node.body)
    }
    top_level_loops = {
        statement
        for statement in node.body
        if isinstance(statement, ast.For)
    }
    if any(isinstance(value, ast.AugAssign) for value in ast.walk(node)):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics incremental mutation differs"
        )
    boundary_validation_positions = (
        _phase04_plain_validation_positions(node)
        if not node.name.startswith("_")
        else {}
    )
    validated_inputs = set(boundary_validation_positions)

    initializers: dict[str, tuple[str, int]] = {}
    for index, statement in enumerate(node.body):
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not isinstance(statement.targets[0], ast.Name)
        ):
            continue
        target = statement.targets[0].id
        if isinstance(statement.value, ast.List) and not statement.value.elts:
            initializers[target] = ("list", index)
        elif isinstance(statement.value, ast.Dict) and not statement.value.keys:
            initializers[target] = ("dict", index)

    store_counts: dict[str, int] = {}
    for value in ast.walk(node):
        if isinstance(value, ast.Name) and isinstance(value.ctx, ast.Store):
            store_counts[value.id] = store_counts.get(value.id, 0) + 1
    initializers = {
        name: specification
        for name, specification in initializers.items()
        if store_counts.get(name) == 1
    }

    def owning_loop(statement: ast.stmt) -> ast.For | None:
        parent = parents.get(statement)
        if (
            isinstance(parent, ast.For)
            and parent in top_level_loops
            and statement in parent.body
        ):
            return parent
        return None

    def enclosing_loop(value: ast.AST) -> ast.For | None:
        current: ast.AST | None = value
        while current is not None:
            current = parents.get(current)
            if isinstance(current, ast.For):
                return current
        return None

    def top_level_statement(value: ast.AST) -> ast.stmt | None:
        current: ast.AST = value
        parent = parents.get(current)
        while parent is not None and parent is not node:
            current = parent
            parent = parents.get(current)
        return current if isinstance(current, ast.stmt) else None

    growth_by_accumulator: dict[str, int] = {}
    for value in ast.walk(node):
        if (
            isinstance(value, ast.Attribute)
            and value.attr in FORBIDDEN_TABLE_SEMANTICS_UNBOUNDED_GROWING_METHODS
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics incremental mutation differs"
            )
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "append"
        ):
            continue
        receiver = value.func.value
        statement = parents.get(value)
        if (
            not isinstance(receiver, ast.Name)
            or initializers.get(receiver.id, (None, -1))[0] != "list"
            or not isinstance(statement, ast.Expr)
            or statement.value is not value
            or len(value.args) != 1
            or value.keywords
            or not _phase04_expression_is_plain(
                value.args[0],
                proven=proven,
                local_callables=local_callables,
            )
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics incremental mutation differs"
            )
        loop = owning_loop(statement)
        if loop is None:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics incremental mutation differs"
            )
        ceiling = _phase04_loop_iteration_ceiling(loop.iter, integer_limits)
        initializer_position = initializers[receiver.id][1]
        if (
            ceiling is None
            or initializer_position >= top_level_positions[loop]
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics incremental mutation differs"
            )
        total = growth_by_accumulator.get(receiver.id, 0) + ceiling
        if total > 65_536:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics incremental mutation differs"
            )
        growth_by_accumulator[receiver.id] = total

    dictionary_growth: dict[str, int] = {}
    for value in ast.walk(node):
        if not isinstance(value, ast.Subscript) or not isinstance(
            value.ctx, ast.Store
        ):
            continue
        literal_key = (
            isinstance(value.slice, ast.Constant)
            and type(value.slice.value) in {int, str}
        )
        if literal_key:
            if enclosing_loop(value) is not None:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics incremental mutation differs"
                )
            if not isinstance(value.value, ast.Name) or (
                initializers.get(value.value.id, (None, -1))[0] != "dict"
                and value.value.id not in validated_inputs
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics incremental mutation differs"
                )
            owner_statement = top_level_statement(value)
            owner_position = top_level_positions.get(owner_statement, -1)
            required_position = (
                initializers[value.value.id][1]
                if value.value.id in initializers
                else boundary_validation_positions[value.value.id][0]
            )
            if owner_position <= required_position:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics incremental mutation differs"
                )
            if (
                initializers.get(value.value.id, (None, -1))[0] == "dict"
                or value.value.id in validated_inputs
            ):
                initial_cardinality = (
                    4_096 if value.value.id in validated_inputs else 0
                )
                total = dictionary_growth.get(
                    value.value.id,
                    initial_cardinality,
                ) + 1
                if total > 65_536:
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics incremental mutation differs"
                    )
                dictionary_growth[value.value.id] = total
            continue

        statement = parents.get(value)
        receiver = value.value
        if (
            not isinstance(receiver, ast.Name)
            or initializers.get(receiver.id, (None, -1))[0] != "dict"
            or not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or statement.targets[0] is not value
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics incremental mutation differs"
            )
        loop = owning_loop(statement)
        if loop is None:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics incremental mutation differs"
            )
        ceiling = _phase04_loop_iteration_ceiling(loop.iter, integer_limits)
        initializer_position = initializers[receiver.id][1]
        if (
            ceiling is None
            or initializer_position >= top_level_positions[loop]
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics incremental mutation differs"
            )
        total = dictionary_growth.get(receiver.id, 0) + ceiling
        if total > 65_536:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics incremental mutation differs"
            )
        dictionary_growth[receiver.id] = total

    accumulator_names = set(growth_by_accumulator) | set(dictionary_growth)
    for statement in ast.walk(node):
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        assigned = statement.value
        if assigned is None:
            continue
        loaded_accumulators = {
            candidate.id
            for candidate in ast.walk(assigned)
            if isinstance(candidate, ast.Name)
            and isinstance(candidate.ctx, ast.Load)
            and candidate.id in accumulator_names
        }
        if not loaded_accumulators:
            continue
        terminal_validation = (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "_assert_plain_table_value"
            and len(statement.value.args) == 2
            and not statement.value.keywords
            and isinstance(statement.value.args[0], ast.Name)
            and isinstance(statement.value.args[1], ast.Name)
            and statement.value.args[1].id == "deadline"
            and loaded_accumulators == {statement.value.args[0].id}
            and statement.targets[0].id
            == f"validated_{statement.value.args[0].id}_output"
        )
        if terminal_validation:
            continue
        alias_breaking_call = (
            isinstance(assigned, ast.Call)
            and isinstance(assigned.func, ast.Name)
            and assigned.func.id
            in {
                "_assert_source_sha256",
                "_batch_table_sha256",
                "_bounded_table_sha256",
                "_canonical_table_json_bytes",
                "_canonical_table_sha256",
                "_copy_raw_table_graph",
                "_copy_table_mapping",
                "_plain_table_length",
                "_validate_plain_table_value",
            }
            and not assigned.keywords
            and assigned.func.id
            in EXPECTED_TABLE_SEMANTICS_DEADLINE_ARGUMENT_INDEX
            and len(assigned.args)
            > EXPECTED_TABLE_SEMANTICS_DEADLINE_ARGUMENT_INDEX[assigned.func.id]
            and isinstance(
                assigned.args[
                    EXPECTED_TABLE_SEMANTICS_DEADLINE_ARGUMENT_INDEX[
                        assigned.func.id
                    ]
                ],
                ast.Name,
            )
            and assigned.args[
                EXPECTED_TABLE_SEMANTICS_DEADLINE_ARGUMENT_INDEX[
                    assigned.func.id
                ]
            ].id
            == "deadline"
        )
        if alias_breaking_call:
            continue
        targets = _phase04_assignment_targets(statement)
        if any(target not in loaded_accumulators for target in targets):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics accumulator alias differs"
            )

    def is_explicit_allocation(value: ast.AST) -> bool:
        if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
            return True
        if isinstance(value, ast.BinOp):
            return _phase04_sequence_size_bound(
                value,
                integer_limits=integer_limits,
                sequence_limits={},
            ) is not None
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"bytes", "list", "tuple"}
        )

    def allocation_bytes(value: ast.AST) -> int | None:
        if isinstance(value, (ast.List, ast.Tuple)):
            total = 64 + 8 * len(value.elts)
            for element in value.elts:
                if is_explicit_allocation(element):
                    nested = allocation_bytes(element)
                    if nested is None:
                        return None
                    total += nested
            return total
        if isinstance(value, ast.Set):
            total = 224 + 64 * len(value.elts)
            for element in value.elts:
                if is_explicit_allocation(element):
                    nested = allocation_bytes(element)
                    if nested is None:
                        return None
                    total += nested
            return total
        if isinstance(value, ast.Dict):
            if any(key is None for key in value.keys):
                return None
            total = 64 + 32 * len(value.keys)
            for key, element in zip(value.keys, value.values, strict=True):
                for candidate in (key, element):
                    if is_explicit_allocation(candidate):
                        nested = allocation_bytes(candidate)
                        if nested is None:
                            return None
                        total += nested
            return total
        if isinstance(value, ast.BinOp):
            bound = _phase04_sequence_size_bound(
                value,
                integer_limits=integer_limits,
                sequence_limits={},
            )
            if bound is None:
                return None
            total = 64 + 8 * bound
            for candidate in (value.left, value.right):
                if is_explicit_allocation(candidate):
                    nested = allocation_bytes(candidate)
                    if nested is None:
                        return None
                    total += nested
            return total
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"bytes", "list", "tuple"}
        ):
            bound = _phase04_sequence_size_bound(
                value,
                integer_limits=integer_limits,
                sequence_limits={},
            )
            if bound is None:
                return None
            if value.func.id == "bytes":
                total = 64 + bound
            else:
                from_range = (
                    bool(value.args)
                    and isinstance(value.args[0], ast.Call)
                    and isinstance(value.args[0].func, ast.Name)
                    and value.args[0].func.id == "range"
                )
                total = 64 + bound * (40 if from_range else 8)
            for argument in value.args:
                if is_explicit_allocation(argument):
                    nested = allocation_bytes(argument)
                    if nested is None:
                        return None
                    total += nested
            return total
        return None

    allocation_total = 0
    for value in ast.walk(node):
        if not is_explicit_allocation(value):
            continue
        ancestor = parents.get(value)
        nested_allocation = False
        loop_multiplier = 1
        while ancestor is not None and ancestor is not node:
            if is_explicit_allocation(ancestor):
                nested_allocation = True
                break
            if isinstance(ancestor, ast.For):
                ceiling = _phase04_loop_iteration_ceiling(
                    ancestor.iter,
                    integer_limits,
                )
                if ceiling is None:
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics cumulative allocation differs"
                    )
                loop_multiplier *= ceiling
            ancestor = parents.get(ancestor)
        if nested_allocation:
            continue
        estimated_bytes = allocation_bytes(value)
        if estimated_bytes is None:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics cumulative allocation differs"
            )
        allocation_total += estimated_bytes * loop_multiplier
        if allocation_total > 67_108_864:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics cumulative allocation differs"
            )
    allocation_total += 8 * sum(growth_by_accumulator.values())
    allocation_total += 32 * sum(dictionary_growth.values())
    if allocation_total > 67_108_864:
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics cumulative allocation differs"
        )
    return allocation_total


def _validate_phase04_acyclic_call_graph(
    functions: Mapping[str, ast.FunctionDef],
) -> None:
    """Reject direct or mutual recursion across table-semantics helpers."""

    graph: dict[str, set[str]] = {name: set() for name in functions}
    for name, function in functions.items():
        for statement in function.body:
            for call in ast.walk(statement):
                if not isinstance(call, ast.Call):
                    continue
                if (
                    isinstance(call.func, ast.Name)
                    and call.func.id in functions
                ):
                    graph[name].add(call.func.id)
                arguments = [
                    *call.args,
                    *(keyword.value for keyword in call.keywords),
                ]
                for argument in arguments:
                    graph[name].update(
                        value.id
                        for value in ast.walk(argument)
                        if isinstance(value, ast.Name)
                        and value.id in functions
                    )

    incoming = {name: 0 for name in graph}
    for callees in graph.values():
        for callee in callees:
            incoming[callee] += 1
    ready = [name for name, count in incoming.items() if count == 0]
    visited = 0
    while ready:
        caller = ready.pop()
        visited += 1
        for callee in graph[caller]:
            incoming[callee] -= 1
            if incoming[callee] == 0:
                ready.append(callee)
    if visited != len(graph):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics call graph cycle differs"
        )


def _validate_phase04_method_callback_arguments(
    functions: Mapping[str, ast.FunctionDef],
    *,
    exact_helpers: frozenset[str],
) -> None:
    """Reject method callbacks whose repeated cost cannot be proved."""

    for function in functions.values():
        if function.name in exact_helpers:
            continue
        for call in ast.walk(function):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
            ):
                continue
            arguments = [
                *call.args,
                *(keyword.value for keyword in call.keywords),
            ]
            callback_names: set[str] = set()
            unvalidated_call_argument = False
            for argument in arguments:
                pending = [argument]
                while pending:
                    value = pending.pop()
                    if (
                        isinstance(value, ast.Name)
                        and value.id in functions
                    ):
                        callback_names.add(value.id)
                        continue
                    if isinstance(value, ast.Call):
                        if not (
                            isinstance(value.func, ast.Name)
                            and value.func.id
                            in {
                                "_assert_plain_table_value",
                                "_validate_plain_table_value",
                            }
                        ):
                            unvalidated_call_argument = True
                            continue
                        pending.extend(value.args)
                        pending.extend(
                            keyword.value for keyword in value.keywords
                        )
                        continue
                    pending.extend(ast.iter_child_nodes(value))
            if callback_names or unvalidated_call_argument:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics method callback differs"
                )


def _validate_phase04_deadline_provenance(
    function: ast.FunctionDef,
    loops: list[ast.For],
    *,
    public_function: bool,
) -> None:
    expected_seconds = EXPECTED_TABLE_SEMANTICS_PUBLIC_DEADLINE_SECONDS.get(
        function.name,
        0.25,
    )
    deadline_arguments = [
        argument.arg == "deadline"
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    ]
    deadline_stores = [
        value
        for value in ast.walk(function)
        if isinstance(value, ast.Name)
        and isinstance(value.ctx, ast.Store)
        and value.id == "deadline"
    ]
    initializers = [
        statement
        for statement in function.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "deadline"
        and isinstance(statement.value, ast.BinOp)
        and isinstance(statement.value.op, ast.Add)
        and isinstance(statement.value.left, ast.Call)
        and isinstance(statement.value.left.func, ast.Name)
        and statement.value.left.func.id == "perf_counter"
        and not statement.value.left.args
        and not statement.value.left.keywords
        and isinstance(statement.value.right, ast.Constant)
        and type(statement.value.right.value) in {int, float}
        and float(statement.value.right.value) == expected_seconds
    ]
    if public_function:
        invalid = (
            any(deadline_arguments)
            or len(deadline_stores) != 1
            or len(initializers) != 1
            or (
                bool(loops)
                and initializers[0].lineno >= min(loop.lineno for loop in loops)
            )
        )
    else:
        invalid = (
            sum(deadline_arguments) != 1
            or bool(deadline_stores)
            or bool(initializers)
        )
    if invalid:
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics deadline provenance differs"
        )


def _validate_phase04_deadline_call_graph(
    functions: Mapping[str, ast.FunctionDef],
    *,
    exact_helpers: frozenset[str],
) -> None:
    public_functions = set(EXPECTED_TABLE_SEMANTICS_PUBLIC_SIGNATURES)
    for function in functions.values():
        if function.name in exact_helpers:
            continue
        arguments = [
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        ]
        argument_names = [argument.arg for argument in arguments]
        if function.name.startswith("_") and any(
            isinstance(value, ast.Name)
            and isinstance(value.ctx, ast.Store)
            and value.id == "deadline"
            for value in ast.walk(function)
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics deadline reset differs"
            )
        loops = [value for value in ast.walk(function) if isinstance(value, ast.For)]
        if loops and function.name.startswith("_"):
            _validate_phase04_deadline_provenance(
                function,
                loops,
                public_function=False,
            )
        for call in ast.walk(function):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            callee = call.func.id
            if callee in public_functions:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics public deadline reset differs"
                )
            deadline_index = EXPECTED_TABLE_SEMANTICS_DEADLINE_ARGUMENT_INDEX.get(
                callee
            )
            local_callee = functions.get(callee)
            if deadline_index is None and local_callee is not None:
                callee_arguments = [
                    *local_callee.args.posonlyargs,
                    *local_callee.args.args,
                    *local_callee.args.kwonlyargs,
                ]
                callee_names = [argument.arg for argument in callee_arguments]
                if "deadline" in callee_names:
                    deadline_index = callee_names.index("deadline")
            if deadline_index is None:
                continue
            if (
                len(call.args) <= deadline_index
                or call.keywords
                or not isinstance(call.args[deadline_index], ast.Name)
                or call.args[deadline_index].id != "deadline"
                or "deadline" not in argument_names
                and function.name.startswith("_")
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics deadline forwarding differs"
                )


def _validate_phase04_resource_call_graph(
    functions: Mapping[str, ast.FunctionDef],
    *,
    exact_helpers: frozenset[str],
) -> None:
    resource_bearing: set[str] = set()
    for function in functions.values():
        if function.name in exact_helpers:
            continue
        for call in ast.walk(function):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            if call.func.id in FORBIDDEN_TABLE_SEMANTICS_NONFROZEN_RESOURCE_CALLS:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics frozen resource call differs"
                )
            if call.func.id in FORBIDDEN_TABLE_SEMANTICS_LOOP_RESOURCE_CALLS:
                resource_bearing.add(function.name)

    changed = True
    while changed:
        changed = False
        for function in functions.values():
            if function.name in exact_helpers or function.name in resource_bearing:
                continue
            if any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id in resource_bearing
                for call in ast.walk(function)
            ):
                resource_bearing.add(function.name)
                changed = True

    for function in functions.values():
        if function.name in exact_helpers:
            continue
        parents = {
            child: parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        for call in ast.walk(function):
            if not isinstance(call, ast.Call):
                continue
            ancestor = parents.get(call)
            in_loop = False
            while ancestor is not None and ancestor is not function:
                if isinstance(ancestor, ast.For):
                    in_loop = True
                    break
                ancestor = parents.get(ancestor)
            if not in_loop:
                continue
            if isinstance(call.func, ast.Name) and (
                call.func.id in FORBIDDEN_TABLE_SEMANTICS_LOOP_RESOURCE_CALLS
                or call.func.id in resource_bearing
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics loop resource amplification differs"
                )
            if isinstance(call.func, ast.Attribute) and call.func.attr == "sort":
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics loop resource amplification differs"
                )


def _validate_table_semantics_public_signature(node: ast.FunctionDef) -> None:
    specification = EXPECTED_TABLE_SEMANTICS_PUBLIC_SIGNATURES.get(node.name)
    if specification is None:
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics public surface differs"
        )
    if (
        node.args.posonlyargs
        or node.args.vararg is not None
        or node.args.kwarg is not None
        or node.args.defaults
        or [argument.arg for argument in node.args.args]
        != list(specification["positional"])
        or [argument.arg for argument in node.args.kwonlyargs]
        != list(specification["keyword_only"])
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics public signature differs"
        )
    required = set(specification["required_keyword_only"])
    for argument, default in zip(
        node.args.kwonlyargs,
        node.args.kw_defaults,
        strict=True,
    ):
        if argument.arg in required:
            if default is not None:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics public signature differs"
                )
        elif (
            not isinstance(default, ast.Constant)
            or type(default.value) is not bool
            or default.value is not False
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics public signature differs"
            )

    guard_source = EXPECTED_TABLE_SEMANTICS_DEFAULT_OFF_GUARDS.get(node.name)
    if guard_source is not None:
        prefix = 1 if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ) else 0
        expected_guard = ast.parse(guard_source).body[0]
        if (
            len(node.body) <= prefix
            or _ast_digest(node.body[prefix]) != _ast_digest(expected_guard)
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics default-off guard differs"
            )


def _phase04_plain_validation_positions(
    node: ast.FunctionDef,
) -> dict[str, tuple[int, str, str]]:
    positions: dict[str, tuple[int, str, str]] = {}
    allowed_validators = {
        "_assert_plain_table_value",
        "_assert_source_sha256",
        "_copy_raw_table_graph",
        "_copy_table_mapping",
        "_validate_plain_table_value",
    }
    for index, statement in enumerate(node.body):
        call: ast.Call | None = None
        target: ast.Name | None = None
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Call)
        ):
            target = statement.targets[0]
            call = statement.value
        if (
            call is None
            or not isinstance(call.func, ast.Name)
            or call.func.id not in allowed_validators
            or len(call.args) != 2
            or call.keywords
            or not isinstance(call.args[0], ast.Name)
            or not isinstance(call.args[1], ast.Name)
            or call.args[1].id != "deadline"
            or (target is not None and target.id != call.args[0].id)
        ):
            continue
        name = call.args[0].id
        if name in positions:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics boundary validation differs"
            )
        positions[name] = (
            index,
            call.func.id,
            "rebind" if target is not None else "in_place",
        )
    return positions


def _phase04_assignment_targets(node: ast.AST) -> set[str]:
    return {
        value.id
        for value in ast.walk(node)
        if isinstance(value, ast.Name) and isinstance(value.ctx, ast.Store)
    }


def _phase04_expression_is_plain(
    node: ast.AST,
    *,
    proven: set[str],
    local_callables: set[str],
) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return node.id in proven
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return all(
            _phase04_expression_is_plain(
                value,
                proven=proven,
                local_callables=local_callables,
            )
            for value in node.elts
        )
    if isinstance(node, ast.Dict):
        return all(
            key is None
            or _phase04_expression_is_plain(
                key,
                proven=proven,
                local_callables=local_callables,
            )
            for key in node.keys
        ) and all(
            _phase04_expression_is_plain(
                value,
                proven=proven,
                local_callables=local_callables,
            )
            for value in node.values
        )
    if isinstance(node, ast.Subscript):
        return _phase04_expression_is_plain(
            node.value,
            proven=proven,
            local_callables=local_callables,
        )
    if isinstance(node, ast.Attribute):
        return _phase04_expression_is_plain(
            node.value,
            proven=proven,
            local_callables=local_callables,
        )
    if isinstance(node, (ast.BinOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.UnaryOp)):
        return all(
            _phase04_expression_is_plain(
                value,
                proven=proven,
                local_callables=local_callables,
            )
            for value in ast.iter_child_nodes(node)
            if isinstance(value, ast.expr)
        )
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            if node.func.id in {
                "_assert_plain_table_value",
                "_assert_source_sha256",
                "_copy_raw_table_graph",
                "_copy_table_mapping",
                "_plain_table_length",
                "_validate_plain_table_value",
            }:
                return (
                    len(node.args) == 2
                    and not node.keywords
                    and isinstance(node.args[1], ast.Name)
                    and node.args[1].id == "deadline"
                )
            if node.func.id in {
                "_assert_canonical_table_json",
                "_batch_table_sha256",
                "_bounded_table_sha256",
                "_canonical_table_json_bytes",
                "_canonical_table_sha256",
            }:
                return (
                    len(node.args) == 3
                    and not node.keywords
                    and isinstance(node.args[2], ast.Name)
                    and node.args[2].id == "deadline"
                )
            if node.func.id in {
                "perf_counter",
                "StringIO",
                "sha256",
            }:
                return not node.args and not node.keywords
            if node.func.id in (
                EXPECTED_TABLE_SEMANTICS_SAFE_BUILTIN_CALLS
                | EXPECTED_TABLE_SEMANTICS_CALLABLE_IMPORTS
                | local_callables
            ):
                return all(
                    _phase04_expression_is_plain(
                        value,
                        proven=proven,
                        local_callables=local_callables,
                    )
                    for value in node.args
                ) and all(
                    _phase04_expression_is_plain(
                        keyword.value,
                        proven=proven,
                        local_callables=local_callables,
                    )
                    for keyword in node.keywords
                )
        if isinstance(node.func, ast.Attribute) and (
            node.func.attr in EXPECTED_TABLE_SEMANTICS_SAFE_METHOD_CALLS
            and _phase04_expression_is_plain(
                node.func.value,
                proven=proven,
                local_callables=local_callables,
            )
        ):
            return all(
                _phase04_expression_is_plain(
                    value,
                    proven=proven,
                    local_callables=local_callables,
                )
                for value in node.args
            ) and all(
                _phase04_expression_is_plain(
                    keyword.value,
                    proven=proven,
                    local_callables=local_callables,
                )
                for keyword in node.keywords
            )
    return False


def _phase04_safe_regex_pattern(pattern: str) -> bool:
    """Accept a flat, bounded-width regex grammar without backtracking nests."""

    if not pattern or len(pattern) > 256:
        return False
    index = 0
    maximum_width = 0
    while index < len(pattern):
        character = pattern[index]
        token_width = 1
        if character in "^$":
            token_width = 0
            index += 1
        elif character == "\\":
            index += 1
            if index >= len(pattern) or pattern[index].isdigit():
                return False
            if pattern[index] in "AbBZ":
                token_width = 0
            index += 1
        elif character == "[":
            index += 1
            if index < len(pattern) and pattern[index] == "^":
                index += 1
            members = 0
            while index < len(pattern) and pattern[index] != "]":
                if pattern[index] == "[":
                    return False
                if pattern[index] == "\\":
                    index += 1
                    if index >= len(pattern) or pattern[index].isdigit():
                        return False
                members += 1
                index += 1
            if index >= len(pattern) or members == 0:
                return False
            index += 1
        elif character in "()|*+?{}":
            return False
        else:
            index += 1

        maximum_repetitions = 1
        if index < len(pattern) and pattern[index] == "?":
            index += 1
        elif index < len(pattern) and pattern[index] == "{":
            end = pattern.find("}", index + 1)
            if end < 0:
                return False
            bounds = pattern[index + 1 : end].split(",")
            if (
                len(bounds) not in {1, 2}
                or any(not bound.isdigit() for bound in bounds)
            ):
                return False
            minimum = int(bounds[0])
            maximum = int(bounds[-1])
            if minimum > maximum or maximum > 64:
                return False
            maximum_repetitions = maximum
            index = end + 1
        maximum_width += token_width * maximum_repetitions
        if maximum_width > 256:
            return False
    return True


def _validate_phase04_regex_and_allocations(
    node: ast.FunctionDef,
    *,
    proven: set[str],
    integer_limits: Mapping[str, int],
    local_callables: set[str],
) -> None:
    local_integer_limits = dict(integer_limits)
    stores: dict[str, list[ast.AST]] = {}
    for value in ast.walk(node):
        if isinstance(value, (ast.Assign, ast.AnnAssign)):
            assigned = value.value
            if assigned is None:
                continue
            for target in _phase04_assignment_targets(value):
                stores.setdefault(target, []).append(assigned)
                integer = _phase04_static_integer(
                    assigned,
                    local_integer_limits,
                )
                if integer is not None:
                    local_integer_limits[target] = integer

    sequence_limits: dict[str, int] = {}
    numeric_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, assignments in stores.items():
            if len(assignments) != 1:
                continue
            assignment = assignments[0]
            bound = _phase04_sequence_size_bound(
                assignment,
                integer_limits=local_integer_limits,
                sequence_limits=sequence_limits,
            )
            if (
                bound is not None
                and 0 <= bound <= 65_536
                and sequence_limits.get(name) != bound
            ):
                sequence_limits[name] = bound
                changed = True
            if (
                name not in numeric_names
                and _phase04_proved_numeric(assignment, numeric_names)
            ):
                numeric_names.add(name)
                changed = True

    for value in ast.walk(node):
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id in {"bytes", "list", "range", "tuple"}:
                bound = _phase04_sequence_size_bound(
                    value,
                    integer_limits=local_integer_limits,
                    sequence_limits=sequence_limits,
                )
                if bound is None or not 0 <= bound <= 65_536:
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics allocation bound differs"
                    )
            if value.func.id in {"fullmatch", "search", "sub"}:
                expected_arguments = 3 if value.func.id == "sub" else 2
                if (
                    len(value.args) != expected_arguments
                    or value.keywords
                    or not isinstance(value.args[0], ast.Constant)
                    or type(value.args[0].value) is not str
                    or not _phase04_safe_regex_pattern(value.args[0].value)
                ):
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics regex pattern differs"
                    )
                if value.func.id == "sub" and (
                    not isinstance(value.args[1], ast.Constant)
                    or type(value.args[1].value) is not str
                    or len(value.args[1].value) > 16
                ):
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics regex input bound differs"
                    )
                string_arguments = (
                    value.args[2:3]
                    if value.func.id == "sub"
                    else value.args[1:2]
                )
                if any(
                    not _phase04_bounded_plain_string(
                        argument,
                        proven=proven,
                        local_callables=local_callables,
                    )
                    for argument in string_arguments
                ):
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics regex input bound differs"
                    )
        if isinstance(value, ast.BinOp) and isinstance(
            value.op,
            (ast.LShift, ast.Pow),
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics allocation bound differs"
            )
        if isinstance(value, ast.BinOp) and not isinstance(
            value.op,
            (ast.Add, ast.Div, ast.FloorDiv, ast.Mod, ast.Mult, ast.Sub),
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics allocation bound differs"
            )
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
            bound = _phase04_sequence_size_bound(
                value,
                integer_limits=local_integer_limits,
                sequence_limits=sequence_limits,
            )
            if bound is not None:
                if 0 <= bound <= 65_536:
                    continue
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics allocation bound differs"
                )
            if not (
                _phase04_proved_numeric(value.left, numeric_names)
                and _phase04_proved_numeric(value.right, numeric_names)
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics allocation bound differs"
                )
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mod):
            if not (
                _phase04_proved_numeric(value.left, numeric_names)
                and _phase04_proved_numeric(value.right, numeric_names)
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics allocation bound differs"
                )
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mult):
            bound = _phase04_sequence_size_bound(
                value,
                integer_limits=local_integer_limits,
                sequence_limits=sequence_limits,
            )
            if bound is not None:
                if not 0 <= bound <= 65_536:
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics allocation bound differs"
                    )
                continue
            if not (
                _phase04_literal_number(value.left)
                and _phase04_literal_number(value.right)
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics allocation bound differs"
                )


def _validate_table_semantics_function_provenance(
    node: ast.FunctionDef,
    *,
    integer_limits: Mapping[str, int],
    local_callables: set[str],
) -> int:
    validations = _phase04_plain_validation_positions(node)
    reconciliation_disabled_statement: ast.stmt | None = None
    if not node.name.startswith("_"):
        _validate_phase04_deadline_provenance(
            node,
            [value for value in ast.walk(node) if isinstance(value, ast.For)],
            public_function=True,
        )
        deadline_position = (
            2
            if node.name == "reconcile_table_candidates"
            else 1
            if node.name in EXPECTED_TABLE_SEMANTICS_DEFAULT_OFF_GUARDS
            else 0
        )
        deadline_seconds = EXPECTED_TABLE_SEMANTICS_PUBLIC_DEADLINE_SECONDS[
            node.name
        ]
        deadline_initializer = ast.parse(
            f"deadline = perf_counter() + {deadline_seconds!r}\n"
        ).body[0]
        if (
            len(node.body) <= deadline_position
            or _ast_digest(node.body[deadline_position])
            != _ast_digest(deadline_initializer)
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics public deadline differs"
            )
        if node.name == "reconcile_table_candidates":
            expected_preamble = ast.parse(
                EXPECTED_TABLE_SEMANTICS_RECONCILIATION_PREAMBLE
            ).body
            if (
                len(node.body) < len(expected_preamble)
                or [
                    _ast_digest(statement)
                    for statement in node.body[: len(expected_preamble)]
                ]
                != [_ast_digest(statement) for statement in expected_preamble]
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics reconciliation preamble differs"
                )
            reconciliation_disabled_statement = node.body[1]
        required = EXPECTED_TABLE_SEMANTICS_ARGUMENT_VALIDATORS[node.name]
        policies = EXPECTED_TABLE_SEMANTICS_ARGUMENT_VALIDATION_POLICIES[
            node.name
        ]
        if (
            set(validations) != set(required)
            or any(
                validations[name][1] != validator
                for name, validator in required.items()
            )
            or any(
                validations[name][2] != policy
                for name, policy in policies.items()
            )
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics boundary validation differs"
            )
        for argument, (position, _validator, _policy) in validations.items():
            if any(
                isinstance(value, ast.Name)
                and isinstance(value.ctx, ast.Load)
                and value.id == argument
                for statement in node.body[:position]
                for value in ast.walk(statement)
                if not (
                    statement is node.body[0]
                    and node.name in EXPECTED_TABLE_SEMANTICS_DEFAULT_OFF_GUARDS
                    or statement is reconciliation_disabled_statement
                    and argument == "merged"
                )
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics boundary validation position differs"
                )
        for argument, policy in policies.items():
            expected_stores = 1 if policy == "rebind" else 0
            observed_stores = sum(
                1
                for value in ast.walk(node)
                if isinstance(value, ast.Name)
                and isinstance(value.ctx, ast.Store)
                and value.id == argument
            )
            handler_rebind = any(
                isinstance(value, ast.ExceptHandler)
                and value.name == argument
                for value in ast.walk(node)
            )
            if observed_stores != expected_stores or handler_rebind:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics boundary binding differs"
                )
    if node.name == "gate_table_candidates" and any(
        isinstance(value, ast.Name)
        and isinstance(value.ctx, ast.Load)
        and value.id == "image_regions"
        for statement in node.body
        for value in ast.walk(statement)
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics image-region input use differs"
        )

    if not node.name.startswith("_"):
        return_root = EXPECTED_TABLE_SEMANTICS_RETURN_ROOTS[node.name]
        expected_return = ast.Return(
            value=(
                ast.Name(id=return_root, ctx=ast.Load())
                if return_root
                else ast.Constant(value=None)
            )
        )
        top_level_returns = [
            statement
            for statement in node.body
            if isinstance(statement, ast.Return)
        ]
        guard_returns = (
            {
                value
                for value in ast.walk(node.body[0])
                if isinstance(value, ast.Return)
            }
            if node.name in EXPECTED_TABLE_SEMANTICS_DEFAULT_OFF_GUARDS
            else set()
        )
        if reconciliation_disabled_statement is not None:
            guard_returns.update(
                value
                for value in ast.walk(reconciliation_disabled_statement)
                if isinstance(value, ast.Return)
            )
        all_returns = {
            value for value in ast.walk(node) if isinstance(value, ast.Return)
        }
        if (
            len(top_level_returns) != 1
            or node.body[-1] is not top_level_returns[0]
            or _ast_digest(top_level_returns[0]) != _ast_digest(expected_return)
            or all_returns != guard_returns | {top_level_returns[0]}
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics terminal return differs"
            )

        output_root = EXPECTED_TABLE_SEMANTICS_OUTPUT_ROOTS[node.name]
        if output_root is not None:
            expected_validation = ast.parse(
                f"validated_{output_root}_output = "
                f"_assert_plain_table_value({output_root}, deadline)\n"
            ).body[0]
            expected_canonical = ast.parse(
                f"_assert_canonical_table_json("
                f"{output_root}, "
                f"{EXPECTED_TABLE_SEMANTICS_OUTPUT_JSON_LIMITS[node.name]}, "
                f"deadline)\n"
            ).body[0]
            if (
                len(node.body) < 3
                or _ast_digest(node.body[-2]) != _ast_digest(expected_validation)
                or _ast_digest(node.body[-3]) != _ast_digest(expected_canonical)
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics terminal validation differs"
                )

    proven = set(validations)
    for statement in node.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value = statement.value
            if value is not None and _phase04_expression_is_plain(
                value,
                proven=proven,
                local_callables=local_callables,
            ):
                proven.update(_phase04_assignment_targets(statement))
    changed = True
    while changed:
        changed = False
        for statement in ast.walk(node):
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            value = statement.value
            targets = _phase04_assignment_targets(statement)
            if value is not None and targets - proven and _phase04_expression_is_plain(
                value,
                proven=proven,
                local_callables=local_callables,
            ):
                proven.update(targets)
                changed = True
        for loop in ast.walk(node):
            if not isinstance(loop, ast.For):
                continue
            if _phase04_expression_is_plain(
                loop.iter,
                proven=proven,
                local_callables=local_callables,
            ):
                targets = _phase04_assignment_targets(loop.target)
                if targets - proven:
                    proven.update(targets)
                    changed = True

    _validate_phase04_regex_and_allocations(
        node,
        proven=proven,
        integer_limits=integer_limits,
        local_callables=local_callables,
    )
    _validate_phase04_operational_inputs(
        node,
        proven=proven,
        local_callables=local_callables,
    )
    allocation_total = _validate_phase04_incremental_mutations(
        node,
        integer_limits=integer_limits,
        local_callables=local_callables,
        proven=proven,
    )

    opaque = set(EXPECTED_TABLE_SEMANTICS_OPAQUE_ATTRIBUTES)
    parents = {
        child: parent
        for parent in ast.walk(node)
        for child in ast.iter_child_nodes(parent)
    }
    for value in ast.walk(node):
        if (
            isinstance(value, ast.Name)
            and isinstance(value.ctx, ast.Load)
            and value.id in opaque
        ):
            parent = parents.get(value)
            allowed_direct = (
                isinstance(parent, ast.Attribute)
                and parent.value is value
                and parent.attr
                in EXPECTED_TABLE_SEMANTICS_OPAQUE_ATTRIBUTES[value.id]
            ) or (
                isinstance(parent, ast.Call)
                and isinstance(parent.func, ast.Name)
                and parent.func.id in {"id", "isinstance", "type"}
                and value in parent.args
            )
            if not allowed_direct:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics opaque value dispatch differs"
                )
        if isinstance(value, ast.Attribute):
            path = _phase04_attribute_path(value)
            if path and path[0] in opaque:
                if len(path) != 2 or path[1] not in (
                    EXPECTED_TABLE_SEMANTICS_OPAQUE_ATTRIBUTES[path[0]]
                ):
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics opaque attribute differs"
                    )
                parent = parents.get(value)
                allowed_load = (
                    isinstance(value.ctx, ast.Load)
                    and isinstance(parent, ast.Call)
                    and isinstance(parent.func, ast.Name)
                    and parent.func.id
                    in {
                        "_assert_plain_table_value",
                        "_validate_plain_table_value",
                        "id",
                        "isinstance",
                        "type",
                    }
                    and value in parent.args
                )
                allowed_store = (
                    isinstance(value.ctx, ast.Store)
                    and path[0] == "owner"
                )
                if not (allowed_load or allowed_store):
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics opaque attribute use differs"
                    )
        if isinstance(value, ast.Subscript):
            path = _phase04_attribute_path(value.value)
            if path and path[0] in opaque:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics opaque traversal differs"
                )
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
            receiver = value.func.value
            if not _phase04_expression_is_plain(
                receiver,
                proven=proven,
                local_callables=local_callables,
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics method receiver differs"
                )
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id
            not in {
                "_assert_plain_table_value",
                "_bounded_table_iterable",
                "_copy_raw_table_graph",
                "_copy_table_mapping",
                "_validate_plain_table_value",
                "id",
                "isinstance",
                "type",
                *local_callables,
            }
            and not all(
                _phase04_expression_is_plain(
                    argument,
                    proven=proven,
                    local_callables=local_callables,
                )
                for argument in value.args
            )
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics callable argument differs"
            )
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and any(
                keyword.arg is None
                or not _phase04_expression_is_plain(
                    keyword.value,
                    proven=proven,
                    local_callables=local_callables,
                )
                for keyword in value.keywords
            )
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics callable argument differs"
            )
    return allocation_total


def _second_additive_p04_us01_table_semantics_nodes(
    tree: ast.Module,
) -> frozenset[str]:
    """Return the exact all-or-none P04-US01 implementation node vector."""

    expected = EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_AST_SHA256
    expected_names = frozenset(expected)
    if not expected_names:
        return frozenset()
    final_ast_sha256 = EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_IDENTITY[
        "ast_sha256"
    ]
    if _ast_digest(tree) != final_ast_sha256:
        candidate_private_names = expected_names - frozenset(
            EXPECTED_TABLE_SEMANTICS_PUBLIC_SIGNATURES
        )
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in candidate_private_names
            for node in ast.walk(tree)
        ):
            raise readiness.ReadinessContractError(
                "second-additive P04-US01 table semantics vector differs"
            )
        return frozenset()
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    reachable: set[str] = set()
    pending = list(EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_ROOTS)
    while pending:
        name = pending.pop()
        if name in reachable or name not in functions:
            continue
        reachable.add(name)
        pending.extend(
            value.func.id
            for value in ast.walk(functions[name])
            if isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in functions
        )
    required_names = frozenset(
        reachable - EXPECTED_TABLE_SEMANTICS_PREEXISTING_EXACT_HELPERS
    )
    if expected_names != required_names:
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 table semantics contract differs"
        )
    observed = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in expected_names
    ]
    if not observed:
        return frozenset()
    top_level = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in expected_names
    }
    if (
        len(observed) != len(expected_names)
        or set(top_level) != set(expected_names)
        or any(top_level.get(node.name) is not node for node in observed)
        or any(
            _ast_digest(top_level[name]) != expected[name]
            for name in expected_names
        )
    ):
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 table semantics vector differs"
        )
    return expected_names


def _current_frozen_p04_us01_table_semantics_nodes(
    tree: ast.Module,
) -> frozenset[str]:
    """Validate the exact later A+B table-semantics freeze as one vector."""

    expected = EXPECTED_CURRENT_FROZEN_P04_US01_TABLE_SEMANTICS_AST_SHA256
    expected_names = frozenset(expected)
    if _ast_digest(tree) != (
        EXPECTED_CURRENT_FROZEN_P04_US01_TABLE_SEMANTICS_IDENTITY["ast_sha256"]
    ):
        return frozenset()
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    reachable: set[str] = set()
    pending = list(EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_ROOTS)
    while pending:
        name = pending.pop()
        if name in reachable or name not in functions:
            continue
        reachable.add(name)
        pending.extend(
            value.func.id
            for value in ast.walk(functions[name])
            if isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in functions
        )
    required_names = frozenset(
        reachable - EXPECTED_TABLE_SEMANTICS_PREEXISTING_EXACT_HELPERS
    )
    observed = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in expected_names
    ]
    top_level = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in expected_names
    }
    if (
        expected_names != required_names
        or len(observed) != len(expected_names)
        or set(top_level) != set(expected_names)
        or any(top_level.get(node.name) is not node for node in observed)
        or any(
            _ast_digest(top_level[name]) != expected[name]
            for name in expected_names
        )
    ):
        raise readiness.ReadinessContractError(
            "current-frozen P04-US01 table semantics vector differs"
        )
    return expected_names


EXPECTED_TABLE_SEMANTICS_MAX_AST_NODES = 40_000


def _validate_table_semantics_module(raw: bytes) -> None:
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics module differs"
        ) from exc
    if (
        sum(1 for _value in ast.walk(tree))
        > EXPECTED_TABLE_SEMANTICS_MAX_AST_NODES
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics syntax resource differs"
        )
    current_frozen_nodes = _current_frozen_p04_us01_table_semantics_nodes(tree)
    if current_frozen_nodes:
        current_identity = (
            EXPECTED_CURRENT_FROZEN_P04_US01_TABLE_SEMANTICS_IDENTITY
        )
        if (
            len(raw) != current_identity["size_bytes"]
            or hashlib.sha256(raw).hexdigest() != current_identity["raw_sha256"]
        ):
            raise readiness.ReadinessContractError(
                "current-frozen P04-US01 table semantics custody differs"
            )
        return
    second_additive_nodes = _second_additive_p04_us01_table_semantics_nodes(tree)
    if second_additive_nodes:
        # The final P04-US01 module is admitted only through its complete,
        # exact module/function AST vector.  Its reviewed imports and grammar
        # are candidate-specific pins; the legacy synthetic scanner below
        # remains unchanged for all non-candidate modules.
        return
    if _phase04_scope_fragments_reconstruct_forbidden(tree):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics module scope differs"
        )
    for statement in tree.body:
        if (
            isinstance(statement, ast.FunctionDef)
            and statement.name in second_additive_nodes
        ):
            continue
        _reject_phase04_scope_tokens(
            statement,
            tokens=FORBIDDEN_TABLE_SEMANTICS_SCOPE_TOKENS,
            label="Phase 04 table semantics module",
        )

    import_positions = [
        index
        for index, statement in enumerate(tree.body)
        if isinstance(statement, (ast.Import, ast.ImportFrom))
    ]
    prefix = 1 if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ) else 0
    if import_positions and import_positions != list(
        range(prefix, prefix + len(import_positions))
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics import position differs"
        )

    imported_bindings: set[str] = set()
    imported_callables: set[str] = set()
    observed_modules: list[str] = []
    module_order = list(EXPECTED_TABLE_SEMANTICS_IMPORTS)
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics import form differs"
            )
        if not isinstance(statement, ast.ImportFrom):
            continue
        if (
            statement.level
            or statement.module not in EXPECTED_TABLE_SEMANTICS_IMPORTS
            or statement.module in observed_modules
            or not statement.names
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics import differs"
            )
        observed_modules.append(str(statement.module))
        allowed_names = EXPECTED_TABLE_SEMANTICS_IMPORTS[str(statement.module)]
        names = [alias.name for alias in statement.names]
        if (
            any(alias.asname is not None for alias in statement.names)
            or len(names) != len(set(names))
            or any(name not in allowed_names for name in names)
            or names != [name for name in allowed_names if name in names]
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics import symbol differs"
            )
        imported_bindings.update(names)
        imported_callables.update(
            name for name in names if name in EXPECTED_TABLE_SEMANTICS_CALLABLE_IMPORTS
        )
    if observed_modules != [
        module for module in module_order if module in observed_modules
    ]:
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics import order differs"
        )
    if any(
        isinstance(value, (ast.Import, ast.ImportFrom))
        and value not in tree.body
        for value in ast.walk(tree)
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics nested import differs"
        )

    allowed_top_level = (ast.AnnAssign, ast.Assign, ast.FunctionDef)
    for index, statement in enumerate(tree.body):
        if isinstance(statement, ast.ImportFrom):
            continue
        if (
            index == 0
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if not isinstance(statement, allowed_top_level):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics module-level execution differs"
            )
        if isinstance(statement, ast.Assign):
            if (
                len(statement.targets) != 1
                or not isinstance(statement.targets[0], ast.Name)
                or not _phase04_literal_only(statement.value)
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics module initializer differs"
                )
        if isinstance(statement, ast.AnnAssign):
            if (
                not isinstance(statement.target, ast.Name)
                or not _phase04_literal_only(statement.value)
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics module initializer differs"
                )

    if any(
        isinstance(value, ast.ClassDef)
        or (
            isinstance(value, ast.FunctionDef)
            and value not in tree.body
        )
        for value in ast.walk(tree)
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics definition scope differs"
        )
    definitions = [
        value.name for value in tree.body if isinstance(value, ast.FunctionDef)
    ]
    if len(definitions) != len(set(definitions)):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics definition differs"
        )
    local_callables = set(definitions)
    allowed_name_calls = (
        EXPECTED_TABLE_SEMANTICS_SAFE_BUILTIN_CALLS
        | imported_callables
        | local_callables
    )

    functions = {
        value.name: value
        for value in tree.body
        if isinstance(value, ast.FunctionDef)
    }
    _validate_phase04_acyclic_call_graph(functions)
    public_functions = [name for name in functions if not name.startswith("_")]
    if set(public_functions) != set(EXPECTED_TABLE_SEMANTICS_PUBLIC_SIGNATURES):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics public function set differs"
        )
    for name in public_functions:
        _validate_table_semantics_public_signature(functions[name])
    exact_helpers = {
        "_batch_table_sha256": EXPECTED_TABLE_SEMANTICS_BATCH_SHA_SOURCE,
        "_assert_canonical_table_json": (
            EXPECTED_TABLE_SEMANTICS_CANONICAL_ASSERT_SOURCE
        ),
        "_bounded_table_iterable": EXPECTED_TABLE_SEMANTICS_BOUNDED_ITERABLE_SOURCE,
        "_bounded_table_sha256": EXPECTED_TABLE_SEMANTICS_BOUNDED_SHA_SOURCE,
        "_bounded_table_text": EXPECTED_TABLE_SEMANTICS_BOUNDED_TEXT_SOURCE,
        "_canonical_table_json_bytes": (
            EXPECTED_TABLE_SEMANTICS_CANONICAL_JSON_SOURCE
        ),
        "_canonical_table_sha256": EXPECTED_TABLE_SEMANTICS_CANONICAL_SHA_SOURCE,
        "_check_table_deadline": EXPECTED_TABLE_SEMANTICS_DEADLINE_CHECK_SOURCE,
        "_assert_plain_table_value": EXPECTED_TABLE_SEMANTICS_PLAIN_ASSERT_SOURCE,
        "_assert_source_sha256": EXPECTED_TABLE_SEMANTICS_SOURCE_SHA_SOURCE,
        "_validate_plain_table_value": EXPECTED_TABLE_SEMANTICS_PLAIN_VALUE_SOURCE,
        "_copy_table_mapping": EXPECTED_TABLE_SEMANTICS_MAPPING_COPY_SOURCE,
        "_copy_raw_table_graph": EXPECTED_TABLE_SEMANTICS_RAW_TABLE_GRAPH_SOURCE,
        "_plain_table_length": EXPECTED_TABLE_SEMANTICS_PLAIN_LENGTH_SOURCE,
    }
    if frozenset(exact_helpers) != (
        EXPECTED_TABLE_SEMANTICS_PREEXISTING_EXACT_HELPERS
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics exact helper contract differs"
        )
    exact_helper_names = frozenset(exact_helpers) | second_additive_nodes
    for function in functions.values():
        if (
            function.name not in exact_helper_names
            and sum(1 for _value in ast.walk(function)) > 4_096
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics syntax resource differs"
            )
    loops = [
        value
        for value in ast.walk(tree)
        if isinstance(value, ast.For)
    ]
    if any(
        isinstance(value, (ast.DictComp, ast.GeneratorExp, ast.ListComp, ast.SetComp))
        for value in ast.walk(tree)
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics comprehension differs"
        )
    if loops:
        for name, source_text in exact_helpers.items():
            observed = functions.get(name)
            expected = ast.parse(source_text).body[0]
            if observed is None or _ast_digest(observed) != _ast_digest(expected):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics bounded execution helper differs"
                )
    elif public_functions:
        observed_plain = functions.get("_validate_plain_table_value")
        expected_plain = ast.parse(EXPECTED_TABLE_SEMANTICS_PLAIN_VALUE_SOURCE).body[0]
        if (
            observed_plain is None
            or _ast_digest(observed_plain) != _ast_digest(expected_plain)
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics plain-data boundary differs"
            )
    integer_limits = {
        target.id: value.value
        for statement in tree.body
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        for target in (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        if isinstance(target, ast.Name)
        for value in [statement.value]
        if isinstance(value, ast.Constant) and type(value.value) is int
    }
    for loop in loops:
        iterator = loop.iter
        deadline_check = ast.parse(
            "_check_table_deadline(deadline)\n"
        ).body[0]
        if (
            not _phase04_bounded_loop_iter(iterator, integer_limits)
            or not loop.body
            or _ast_digest(loop.body[0]) != _ast_digest(deadline_check)
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics iteration bound or deadline differs"
            )

    for function in functions.values():
        function_loops = [
            value for value in ast.walk(function) if isinstance(value, ast.For)
        ]
        if function_loops and function.name not in exact_helper_names:
            if any(
                isinstance(value, (ast.Try, ast.TryStar))
                for value in ast.walk(function)
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics deadline propagation differs"
                )
    _validate_phase04_deadline_call_graph(
        functions,
        exact_helpers=exact_helper_names,
    )
    _validate_phase04_resource_call_graph(
        functions,
        exact_helpers=exact_helper_names,
    )

    deferred_nodes = {
        child
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef)
        for statement in function.body
        for child in ast.walk(statement)
    }
    if any(
        value.decorator_list
        for value in ast.walk(tree)
        if isinstance(value, ast.FunctionDef)
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 table semantics decorator differs"
        )
    future_annotations = "annotations" in imported_bindings
    for function in functions.values():
        defaults = [
            *function.args.defaults,
            *(value for value in function.args.kw_defaults if value is not None),
        ]
        if any(not _phase04_literal_only(value) for value in defaults):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics function default differs"
            )
        annotations = [
            argument.annotation
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            )
            if argument.annotation is not None
        ]
        if function.returns is not None:
            annotations.append(function.returns)
        if annotations and not future_annotations:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics annotation evaluation differs"
            )
    forbidden_identifiers = (
        FORBIDDEN_DYNAMIC_CALL_NAMES
        | FORBIDDEN_EXTERNAL_CALL_NAMES
        | FORBIDDEN_REFLECTION_IDENTIFIERS
    )
    protected_bindings = allowed_name_calls | imported_bindings
    suppressed_context_raises = {
        value
        for helper_name in {
            "_canonical_table_json_bytes",
            "_assert_plain_table_value",
            "_batch_table_sha256",
            "_bounded_table_text",
            "_validate_plain_table_value",
        }
        for value in ast.walk(functions[helper_name])
        if isinstance(value, ast.Raise)
        and isinstance(value.cause, ast.Constant)
        and value.cause.value is None
    }
    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.AsyncFor,
                ast.AsyncFunctionDef,
                ast.AsyncWith,
                ast.Await,
                ast.Delete,
                ast.Global,
                ast.Lambda,
                ast.Match,
                ast.NamedExpr,
                ast.Nonlocal,
                ast.While,
                ast.With,
                ast.Yield,
                ast.YieldFrom,
            ),
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics control or resource scope differs"
            )
        if isinstance(node, ast.Assert) and (
            node.msg is not None and not _phase04_literal_only(node.msg)
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics diagnostic payload differs"
            )
        if (
            isinstance(node, ast.Attribute)
            and node.attr in FORBIDDEN_TABLE_SEMANTICS_BULK_METHODS
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics bulk mutation differs"
            )
        if isinstance(node, ast.Raise):
            if (
                (node.cause is not None and node not in suppressed_context_raises)
                or not isinstance(node.exc, ast.Call)
                or not isinstance(node.exc.func, ast.Name)
                or node.exc.func.id
                not in EXPECTED_TABLE_SEMANTICS_DIAGNOSTIC_EXCEPTIONS
                or node.exc.keywords
                or any(not _phase04_literal_only(value) for value in node.exc.args)
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics diagnostic payload differs"
                )
        identifier = None
        if isinstance(node, ast.Name):
            identifier = node.id
        elif isinstance(node, ast.arg):
            identifier = node.arg
        elif isinstance(node, ast.Attribute):
            identifier = node.attr
        if identifier is not None and (
            identifier in forbidden_identifiers or "__" in identifier
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics reflection or external access differs"
            )
        if isinstance(node, ast.arg) and node.arg in protected_bindings:
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics callable binding differs"
            )
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id in protected_bindings
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 table semantics callable binding differs"
            )
        static_string = _phase04_static_string(node)
        if static_string is not None:
            lowered = static_string.casefold()
            if "__" in static_string or any(
                token in lowered
                for token in (
                    "file://",
                    "ftp://",
                    "http://",
                    "https://",
                    "socket",
                    "subprocess",
                )
            ):
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics constructed name differs"
                )
        if isinstance(node, ast.Call):
            if node not in deferred_nodes:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics module-level call differs"
                )
            if isinstance(node.func, ast.Name):
                if node.func.id not in allowed_name_calls:
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics callable target differs"
                    )
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in FORBIDDEN_TABLE_SEMANTICS_BULK_METHODS:
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics bulk mutation differs"
                    )
                if (
                    node.func.attr not in EXPECTED_TABLE_SEMANTICS_SAFE_METHOD_CALLS
                    or not isinstance(
                        node.func.value, (ast.Name, ast.Constant, ast.Call)
                    )
                ):
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics method target differs"
                    )
            else:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics dynamic call target differs"
                )
    allocation_costs: dict[str, int] = {}
    for function in functions.values():
        if function.name not in exact_helper_names:
            allocation_costs[function.name] = (
                _validate_table_semantics_function_provenance(
                    function,
                    integer_limits=integer_limits,
                    local_callables=local_callables,
                )
            )

    _validate_phase04_method_callback_arguments(
        functions,
        exact_helpers=exact_helper_names,
    )
    expanded_costs: dict[str, int] = {}

    def expanded_allocation_cost(name: str) -> int:
        retained = expanded_costs.get(name)
        if retained is not None:
            return retained
        function = functions[name]
        parents = {
            child: parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        total = allocation_costs[name]
        for call in ast.walk(function):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_batch_table_sha256"
            ):
                total += 9_437_248
                if total > 67_108_864:
                    raise readiness.ReadinessContractError(
                        "Phase 04 table semantics cumulative allocation differs"
                    )
                continue
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id in allocation_costs
            ):
                continue
            multiplier = 1
            ancestor = parents.get(call)
            while ancestor is not None and ancestor is not function:
                if isinstance(ancestor, ast.For):
                    ceiling = _phase04_loop_iteration_ceiling(
                        ancestor.iter,
                        integer_limits,
                    )
                    if ceiling is None:
                        raise readiness.ReadinessContractError(
                            "Phase 04 table semantics cumulative allocation differs"
                        )
                    multiplier *= ceiling
                ancestor = parents.get(ancestor)
            total += multiplier * expanded_allocation_cost(call.func.id)
            if total > 67_108_864:
                raise readiness.ReadinessContractError(
                    "Phase 04 table semantics cumulative allocation differs"
                )
        expanded_costs[name] = total
        return total

    for name in allocation_costs:
        expanded_allocation_cost(name)


def _phase04_frontend_fragment_pattern(value: str) -> str:
    separator = r"[^A-Za-z0-9_$]*"
    return (
        r"(?<![A-Za-z0-9_$])"
        + separator.join(re.escape(character) for character in value)
        + r"(?![A-Za-z0-9_$])"
    )


def _phase04_frontend_source_preflight(source: str) -> None:
    if (
        len(source) > 2 * 1024 * 1024
        or _phase04_scope_utf8_size(source) > 2 * 1024 * 1024
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 frontend scope differs"
        )


def _phase04_frontend_casefold_bounded(source: str) -> str:
    parts: list[str] = []
    total = 0
    for character in source:
        folded = character.casefold()
        total += _phase04_scope_utf8_size(folded)
        if total > 2 * 1024 * 1024:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )
        parts.append(folded)
    return "".join(parts)


_PHASE04_FRONTEND_MAX_JSX_LOOKAHEAD_STEPS = 262_144


def _phase04_frontend_literal_values(
    source: str,
    *,
    allow_jsx: bool = False,
) -> tuple[str, ...]:
    _phase04_frontend_source_preflight(source)
    values: list[str] = []
    total_bytes = 0
    index = 0
    can_end_expression = False
    control_parens: list[bool] = []
    jsx_tags: list[str] = []
    jsx_self_closing_slashes: set[int] = set()
    jsx_lookahead_steps = 0
    jsx_opening_count = 0
    control_pending = False
    last_token = ""
    control_keywords = frozenset({"catch", "for", "if", "switch", "while", "with"})
    operand_keywords = frozenset(
        {
            "as",
            "await",
            "break",
            "case",
            "continue",
            "debugger",
            "delete",
            "do",
            "else",
            "extends",
            "finally",
            "in",
            "instanceof",
            "new",
            "of",
            "return",
            "satisfies",
            "throw",
            "try",
            "typeof",
            "void",
            "yield",
        }
    )
    escapes = {
        "'": "'",
        '"': '"',
        "\\": "\\",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
    }

    def consume_jsx_lookahead() -> None:
        nonlocal jsx_lookahead_steps
        jsx_lookahead_steps += 1
        if jsx_lookahead_steps > _PHASE04_FRONTEND_MAX_JSX_LOOKAHEAD_STEPS:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )

    def jsx_opening_tag(start: int) -> tuple[str, int | None] | None:
        nonlocal jsx_opening_count
        if not allow_jsx or can_end_expression or source[start] != "<":
            return None
        cursor = start + 1
        while cursor < len(source) and source[cursor].isspace():
            consume_jsx_lookahead()
            cursor += 1
        name_start = cursor
        while cursor < len(source) and (
            source[cursor].isalnum() or source[cursor] in "._:-"
        ):
            consume_jsx_lookahead()
            cursor += 1
            if cursor - name_start > 64:
                raise readiness.ReadinessContractError(
                    "Phase 04 frontend scope differs"
                )
        tag = source[name_start:cursor]
        if tag not in {"div", "span", "table", "tbody", "td", "th", "thead", "tr"}:
            return None
        jsx_opening_count += 1
        if jsx_opening_count > 4_096:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )
        quote: str | None = None
        escaped = False
        brace_depth = 0
        previous_significant = -1
        while cursor < len(source) and cursor - start <= 4_096:
            consume_jsx_lookahead()
            character = source[cursor]
            if quote is not None:
                if character == quote and not escaped:
                    quote = None
                escaped = character == "\\" and not escaped
                if character != "\\":
                    escaped = False
                cursor += 1
                continue
            if character in {'"', "'", "`"}:
                quote = character
            elif character == "{":
                brace_depth += 1
                if brace_depth > 256:
                    raise readiness.ReadinessContractError(
                        "Phase 04 frontend scope differs"
                    )
            elif character == "}" and brace_depth:
                brace_depth -= 1
            elif character == "<" and brace_depth == 0:
                raise readiness.ReadinessContractError(
                    "Phase 04 frontend scope differs"
                )
            elif character == ">" and brace_depth == 0:
                self_closing = (
                    previous_significant
                    if previous_significant >= name_start
                    and source[previous_significant] == "/"
                    else None
                )
                return tag, self_closing
            if not character.isspace():
                previous_significant = cursor
            cursor += 1
        raise readiness.ReadinessContractError(
            "Phase 04 frontend scope differs"
        )

    def closes_proven_jsx(start: int) -> bool:
        if (
            not allow_jsx
            or start == 0
            or source[start - 1] != "<"
            or not jsx_tags
        ):
            return False
        cursor = start + 1
        name_start = cursor
        while cursor < len(source) and (
            source[cursor].isalnum() or source[cursor] in "._:-"
        ):
            consume_jsx_lookahead()
            cursor += 1
            if cursor - name_start > 64:
                return False
        tag = source[name_start:cursor]
        while cursor < len(source) and source[cursor].isspace():
            consume_jsx_lookahead()
            cursor += 1
        if cursor >= len(source) or source[cursor] != ">" or jsx_tags[-1] != tag:
            return False
        jsx_tags.pop()
        return True

    while index < len(source):
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            index = len(source) if end < 0 else end + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise readiness.ReadinessContractError(
                    "Phase 04 frontend scope differs"
                )
            index = end + 2
            continue
        character = source[index]
        if character.isspace():
            index += 1
            continue
        if character == "/":
            jsx_closing = closes_proven_jsx(index)
            jsx_self_closing = index in jsx_self_closing_slashes
            if not jsx_closing and not jsx_self_closing and not can_end_expression:
                # Regex literals are outside the exact inert frontend grammar.
                # Reject at the opener before a comment marker inside a regex
                # character class can hide later source text.
                raise readiness.ReadinessContractError(
                    "Phase 04 frontend scope differs"
                )
            can_end_expression = False
            control_pending = False
            last_token = "/"
            index += 1
            continue
        if character == "<":
            opening = jsx_opening_tag(index)
            if opening is not None:
                tag, self_closing_slash = opening
                if self_closing_slash is None:
                    if len(jsx_tags) >= 256:
                        raise readiness.ReadinessContractError(
                            "Phase 04 frontend scope differs"
                        )
                    jsx_tags.append(tag)
                else:
                    if len(jsx_self_closing_slashes) >= 4_096:
                        raise readiness.ReadinessContractError(
                            "Phase 04 frontend scope differs"
                        )
                    jsx_self_closing_slashes.add(self_closing_slash)
        if character.isalpha() or character in "_$":
            end = index + 1
            while end < len(source) and (
                source[end].isalnum() or source[end] in "_$"
            ):
                end += 1
                if end - index > 256:
                    raise readiness.ReadinessContractError(
                        "Phase 04 frontend scope differs"
                    )
            identifier = source[index:end]
            member_name = last_token == "."
            control_pending = not member_name and identifier in control_keywords
            can_end_expression = member_name or identifier not in (
                control_keywords | operand_keywords
            )
            last_token = identifier
            index = end
            continue
        if character.isdigit():
            end = index + 1
            while end < len(source) and (
                source[end].isalnum() or source[end] in "._"
            ):
                end += 1
            can_end_expression = True
            control_pending = False
            last_token = "number"
            index = end
            continue
        if character not in {'"', "'", "`"}:
            if character == "(":
                if len(control_parens) >= 8_192:
                    raise readiness.ReadinessContractError(
                        "Phase 04 frontend scope differs"
                    )
                control_parens.append(control_pending)
                can_end_expression = False
            elif character == ")":
                control = control_parens.pop() if control_parens else False
                can_end_expression = not control
            elif character == "]":
                can_end_expression = True
            elif character == "}":
                can_end_expression = False
            elif (
                character in "+-"
                and source.startswith(character * 2, index)
                and can_end_expression
            ):
                index += 1
                can_end_expression = True
            else:
                can_end_expression = False
            control_pending = False
            last_token = character
            index += 1
            continue
        quote = character
        if len(values) >= 4_096:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )
        index += 1
        decoded: list[str] = []
        decoded_bytes = 0
        closed = False
        while index < len(source):
            character = source[index]
            if character == quote:
                index += 1
                closed = True
                break
            if character in {"\n", "\r"} and quote != "`":
                raise readiness.ReadinessContractError(
                    "Phase 04 frontend scope differs"
                )
            if character != "\\":
                decoded_bytes += _phase04_scope_utf8_size(character)
                if total_bytes + decoded_bytes > 262_144:
                    raise readiness.ReadinessContractError(
                        "Phase 04 frontend scope differs"
                    )
                decoded.append(character)
                index += 1
                continue
            index += 1
            if index >= len(source) or source[index] in {"\n", "\r"}:
                raise readiness.ReadinessContractError(
                    "Phase 04 frontend scope differs"
                )
            escaped = source[index]
            if escaped == "0":
                if index + 1 < len(source) and source[index + 1].isdigit():
                    raise readiness.ReadinessContractError(
                        "Phase 04 frontend scope differs"
                    )
                decoded_value = "\0"
            elif escaped in escapes:
                decoded_value = escapes[escaped]
            else:
                # Unknown, hexadecimal, Unicode, and legacy-octal escapes are
                # intentionally fail-closed; none is needed by the inert helper.
                raise readiness.ReadinessContractError(
                    "Phase 04 frontend scope differs"
                )
            decoded_bytes += _phase04_scope_utf8_size(decoded_value)
            if total_bytes + decoded_bytes > 262_144:
                raise readiness.ReadinessContractError(
                    "Phase 04 frontend scope differs"
                )
            decoded.append(decoded_value)
            index += 1
        if not closed:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )
        value = "".join(decoded)
        total_bytes += decoded_bytes
        values.append(value)
        can_end_expression = True
        control_pending = False
        last_token = "literal"
        if len(values) > 4_096 or total_bytes > 262_144:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )
    if control_parens or jsx_tags or last_token == "/":
        raise readiness.ReadinessContractError(
            "Phase 04 frontend scope differs"
        )
    return tuple(values)


_PHASE04_FRONTEND_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_$\.])(?:"
    r"0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*|"
    r"0[bB][01](?:_?[01])*|"
    r"0[oO][0-7](?:_?[0-7])*|"
    r"(?:[0-9](?:_?[0-9])*)?\.[0-9](?:_?[0-9])*"
    r"(?:[eE][+-]?[0-9](?:_?[0-9])*)?|"
    r"[0-9](?:_?[0-9])*(?:[eE][+-]?[0-9](?:_?[0-9])*)?|"
    r"[0-9](?:_?[0-9])*"
    r")(?:n)?(?![A-Za-z0-9_$\.])"
)


def _phase04_frontend_numeric_scope_fragments(source: str) -> tuple[str, ...]:
    fragments: list[str] = []
    for match in _PHASE04_FRONTEND_NUMBER_PATTERN.finditer(
        _phase04_mask_frontend_code(source)
    ):
        matched = match.group(0)
        if len(matched) > 256:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )
        raw = matched.replace("_", "")
        bigint = raw.endswith("n")
        if bigint:
            raw = raw[:-1]
        try:
            if raw.casefold().startswith("0x"):
                value: int | float = int(raw, 16)
            elif raw.casefold().startswith("0b"):
                value = int(raw, 2)
            elif raw.casefold().startswith("0o"):
                value = int(raw, 8)
            elif bigint or ("." not in raw and "e" not in raw.casefold()):
                value = int(raw, 10)
            else:
                value = float(raw)
        except ValueError:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            ) from None
        if value == 0:
            fragments.append("0")
        elif value == 5:
            fragments.append("5")
        if len(fragments) > 4_096:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )
    return tuple(fragments)


def _phase04_frontend_fragments_form_target(
    fragments: tuple[str, ...],
    target: str,
) -> bool:
    counts: dict[str, int] = {}
    for fragment in fragments:
        if fragment and len(fragment) <= len(target) and fragment in target:
            counts[fragment] = min(counts.get(fragment, 0) + 1, len(target))
    names = tuple(sorted(counts))
    initial = tuple(counts[name] for name in names)
    stack: list[tuple[int, tuple[int, ...], int]] = [(0, initial, 0)]
    observed: set[tuple[int, tuple[int, ...], int]] = set()
    while stack:
        position, remaining, pieces = stack.pop()
        state = (position, remaining, min(pieces, 2))
        if state in observed:
            continue
        observed.add(state)
        if len(observed) > 4_096:
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )
        if position == len(target):
            if pieces >= 2:
                return True
            continue
        for item, fragment in enumerate(names):
            if remaining[item] and target.startswith(fragment, position):
                updated = list(remaining)
                updated[item] -= 1
                stack.append(
                    (position + len(fragment), tuple(updated), pieces + 1)
                )
    return False


def _phase04_frontend_has_reconstructed_scope(
    source: str,
    *,
    allow_jsx: bool = False,
) -> bool:
    def is_subsequence(target: str, value: str) -> bool:
        candidates = iter(value)
        return all(
            any(candidate == character for candidate in candidates)
            for character in target
        )

    def contains_character_multiset(target: str, value: str) -> bool:
        available: dict[str, int] = {}
        for character in value:
            available[character] = available.get(character, 0) + 1
        required: dict[str, int] = {}
        for character in target:
            required[character] = required.get(character, 0) + 1
        return all(available.get(character, 0) >= count for character, count in required.items())

    literals = _phase04_frontend_literal_values(source, allow_jsx=allow_jsx)
    if any(
        _phase04_scope_value_is_forbidden(
            value,
            tokens=FORBIDDEN_PHASE04_SCOPE_TOKENS,
        )
        for value in literals
    ):
        return True
    compact_values: list[str] = []
    compact_bytes = 0
    for literal in literals:
        value = _phase04_scope_compact_atom(literal)
        if not value:
            continue
        value_bytes = _phase04_scope_utf8_size(value)
        if (
            len(compact_values) >= 4_096
            or compact_bytes + value_bytes > 262_144
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 frontend scope differs"
            )
        compact_bytes += value_bytes
        compact_values.append(value)
    compact = tuple(compact_values)
    numeric_fragments = _phase04_frontend_numeric_scope_fragments(source)
    if len(compact) + len(numeric_fragments) > 4_096:
        raise readiness.ReadinessContractError("Phase 04 frontend scope differs")
    fragments = (*compact, *numeric_fragments)
    if any(
        _phase04_frontend_fragments_form_target(fragments, target)
        for target in _PHASE04_SCOPE_RECONSTRUCTION_TARGETS
    ):
        return True

    code = _phase04_mask_frontend_code(source)
    core_targets = (
        "p5",
        "p05",
        "phase5",
        "phase05",
        "runningregion",
        "runningregions",
    )
    reordering = re.search(
        r"(?:\[\s*[0-9]+\s*\]|\.(?:at|replace|slice|substring|substr)\s*\()",
        code,
    )
    if reordering:
        for value in compact:
            if any(
                target in value
                or (
                    len(value) <= len(target) + 16
                    and (
                        is_subsequence(target, value)
                        or contains_character_multiset(target, value)
                    )
                )
                for target in core_targets
            ):
                return True
        for target in core_targets:
            characters: list[str] = []
            for value in compact:
                for character in value:
                    if character not in target:
                        continue
                    if len(characters) >= 4_096:
                        raise readiness.ReadinessContractError(
                            "Phase 04 frontend scope differs"
                        )
                    characters.append(character)
            if _phase04_frontend_fragments_form_target(
                tuple(characters), target
            ):
                return True
    arithmetic = re.search(
        r"(?:\*\*|\+\+|--|[+\-*/%])",
        code,
    )
    return bool(
        arithmetic
        and any(
            value in target and value not in {target, "table", "enabled"}
            for value in compact
            for target in core_targets
        )
    )


def _phase04_mask_frontend_code(source: str) -> str:
    _phase04_frontend_source_preflight(source)
    output = list(source)
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            for position in range(index, end):
                output[position] = " "
            index = end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = len(source) if end < 0 else end + 2
            for position in range(index, end):
                if output[position] != "\n":
                    output[position] = " "
            index = end
            continue
        if source[index] in {'"', "'", "`"}:
            quote = source[index]
            position = index
            escaped = False
            while position < len(source):
                character = source[position]
                if character == "\n" and quote != "`":
                    break
                if position > index and character == quote and not escaped:
                    position += 1
                    break
                escaped = character == "\\" and not escaped
                if character != "\\":
                    escaped = False
                position += 1
            for masked in range(index, position):
                if output[masked] != "\n":
                    output[masked] = " "
            if quote == "`":
                output[index] = "`"
                if position > index + 1 and source[position - 1] == "`":
                    output[position - 1] = "`"
            index = position
            continue
        index += 1
    return "".join(output)


def _phase04_frontend_has_forbidden_scope(
    source: str,
    *,
    allow_jsx: bool = False,
) -> bool:
    masked = _phase04_mask_frontend_code(source)
    return bool(
        _phase04_frontend_has_reconstructed_scope(
            source,
            allow_jsx=allow_jsx,
        )
        or _phase04_scope_value_is_forbidden(
            source,
            tokens=FORBIDDEN_PHASE04_SCOPE_TOKENS,
        )
        or _phase04_scope_value_is_forbidden(
            masked,
            tokens=FORBIDDEN_PHASE04_SCOPE_TOKENS,
        )
    )


_PHASE04_FRONTEND_PROTECTED_DIRECT_CALLS = frozenset(
    {
        "Boolean",
        "Number",
        "String",
        "gateTableCandidates",
        "readTableSemantics",
        "renderValidatedTextRunOverlay",
    }
)
_PHASE04_FRONTEND_PROTECTED_STATIC_ROOTS = frozenset(
    {"Array", "JSON", "Object"}
)
_PHASE04_FRONTEND_SAFE_STATIC_METHODS = {
    "Array": frozenset({"isArray"}),
    "JSON": frozenset({"stringify"}),
    "Number": frozenset({"isFinite"}),
    "Object": frozenset({"entries", "keys", "values"}),
}
_PHASE04_FRONTEND_MAIN_BINDINGS = frozenset(
    {
        "item",
        "textRunSemantics",
        "type",
        "value",
    }
)
_PHASE04_FRONTEND_ASSIGNMENT_OPERATOR = (
    r"(?:(?:\*\*|>>>|>>|<<|&&|\|\||\?\?|[+\-*/%&|^])?=(?!=|>))"
)
_PHASE04_FRONTEND_CALLBACK_METHODS = frozenset(
    {
        "every",
        "filter",
        "find",
        "flatMap",
        "forEach",
        "map",
        "reduce",
        "some",
        "sort",
    }
)
def _phase04_frontend_matching_delimiter(
    source: str,
    start: int,
    opening: str,
    closing: str,
) -> int:
    if start >= len(source) or source[start] != opening:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend delimiter differs"
        )
    depth = 0
    for index in range(start, len(source)):
        character = source[index]
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
    raise readiness.ReadinessContractError(
        "hardened Phase 04 frontend delimiter differs"
    )


def _phase04_frontend_call_arguments(code: str, opening: int) -> list[str]:
    closing = _phase04_frontend_matching_delimiter(code, opening, "(", ")")
    body = code[opening + 1 : closing]
    if not body.strip():
        return []
    arguments: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0}
    closing_for = {")": "(", "]": "[", "}": "{"}
    for index, character in enumerate(body):
        if character in depths:
            depths[character] += 1
        elif character in closing_for:
            opening_character = closing_for[character]
            depths[opening_character] -= 1
            if depths[opening_character] < 0:
                raise readiness.ReadinessContractError(
                    "hardened Phase 04 frontend call arguments differ"
                )
        elif character == "," and all(depth == 0 for depth in depths.values()):
            arguments.append(body[start:index].strip())
            start = index + 1
    if any(depth != 0 for depth in depths.values()):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend call arguments differ"
        )
    arguments.append(body[start:].strip())
    return arguments


def _phase04_frontend_parameter_bindings(parameters: str) -> set[str]:
    bindings: set[str] = set()
    for parameter in parameters.split(","):
        value = parameter.strip().lstrip(".")
        if not value:
            continue
        if value.startswith(("{", "[")):
            bindings.update(
                match.group(0)
                for match in re.finditer(r"[A-Za-z_$][\w$]*", value)
            )
            continue
        match = re.match(r"[A-Za-z_$][\w$]*", value)
        if match is not None:
            bindings.add(match.group(0))
    return bindings


def _phase04_frontend_callable_records(
    code: str,
) -> list[tuple[str, set[str], str, bool]]:
    records: list[tuple[str, set[str], str, bool]] = []
    occupied: list[tuple[int, int]] = []
    function_pattern = re.compile(
        r"(?P<export>\bexport\s+)?\bfunction\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*\("
    )
    for match in function_pattern.finditer(code):
        parameter_start = code.find("(", match.start())
        parameter_end = _phase04_frontend_matching_delimiter(
            code, parameter_start, "(", ")"
        )
        body_start = code.find("{", parameter_end + 1)
        if body_start < 0:
            raise readiness.ReadinessContractError(
                "hardened Phase 04 frontend callable declaration differs"
            )
        body_end = _phase04_frontend_matching_delimiter(
            code, body_start, "{", "}"
        )
        parameter_source = code[parameter_start + 1 : parameter_end]
        records.append(
            (
                match.group("name"),
                _phase04_frontend_parameter_bindings(
                    parameter_source
                ),
                parameter_source + "\n" + code[body_start + 1 : body_end],
                match.group("export") is not None,
            )
        )
        occupied.append((match.start(), body_end + 1))

    arrow_pattern = re.compile(
        r"\bconst\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
        r"(?::[^=;\n]+)?=\s*"
        r"(?P<parameters>\([^)]*\)|[A-Za-z_$][\w$]*"
        r"(?:\s*:\s*[^=;\n]+)?)\s*"
        r"(?::\s*[^=;\n]+)?=>"
    )
    for match in arrow_pattern.finditer(code):
        if any(start <= match.start() < end for start, end in occupied):
            # A nested const-arrow is still a callable record. The occupied
            # ranges only prevent a function signature from being mistaken
            # for an arrow signature; they do not exclude its body.
            pass
        parameters = match.group("parameters").strip()
        if parameters.startswith("("):
            parameters = parameters[1:-1]
        else:
            parameters = parameters.split(":", 1)[0]
        body_start = match.end()
        while body_start < len(code) and code[body_start].isspace():
            body_start += 1
        if body_start < len(code) and code[body_start] == "{":
            body_end = _phase04_frontend_matching_delimiter(
                code, body_start, "{", "}"
            )
            body = code[body_start + 1 : body_end]
        else:
            semicolon = code.find(";", body_start)
            newline = code.find("\n", body_start)
            candidates = [
                value for value in (semicolon, newline) if value >= 0
            ]
            body_end = min(candidates) if candidates else len(code)
            body = code[body_start:body_end]
        records.append(
            (
                match.group("name"),
                _phase04_frontend_parameter_bindings(parameters),
                parameters + "\n" + body,
                False,
            )
        )
    return records


def _validate_phase04_frontend_callable_graph(
    records: list[tuple[str, set[str], str, bool]],
    *,
    label: str,
) -> set[str]:
    names = [name for name, _parameters, _body, _exported in records]
    if len(names) != len(set(names)):
        raise readiness.ReadinessContractError(
            f"{label} callable binding differs"
        )
    local_names = set(names)
    edges: dict[str, set[str]] = {name: set() for name in local_names}
    for name, _parameters, body, _exported in records:
        for match in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", body):
            prefix = body[: match.start(1)].rstrip()
            if prefix.endswith("."):
                continue
            callee = match.group(1)
            if callee in local_names:
                edges[name].add(callee)
        callback_pattern = re.compile(
            r"\.\s*(?:"
            + "|".join(sorted(_PHASE04_FRONTEND_CALLBACK_METHODS))
            + r")\s*\("
        )
        for match in callback_pattern.finditer(body):
            opening = body.find("(", match.start(), match.end())
            arguments = _phase04_frontend_call_arguments(body, opening)
            callback = arguments[0].strip() if arguments else ""
            if callback in local_names:
                edges[name].add(callback)

    states: dict[str, int] = {}

    def visit(name: str) -> None:
        state = states.get(name, 0)
        if state == 1:
            raise readiness.ReadinessContractError(
                f"{label} callable graph differs"
            )
        if state == 2:
            return
        states[name] = 1
        for callee in edges[name]:
            visit(callee)
        states[name] = 2

    for name in local_names:
        visit(name)
    return local_names


def _validate_phase04_frontend_jsx(source: str, *, label: str) -> None:
    allowed_tags = {"div", "span", "table", "tbody", "td", "th", "thead", "tr"}
    allowed_properties = {
        "className",
        "colSpan",
        "key",
        "rowSpan",
        "scope",
    }
    jsx_source = _phase04_mask_frontend_code(source)
    for match in re.finditer(
        r"<\s*(?!/)([A-Za-z][A-Za-z0-9._:-]*)\b([^<>]*)>",
        jsx_source,
        flags=re.DOTALL,
    ):
        tag = match.group(1)
        body = match.group(2)
        compact_body = re.sub(r"\s+", "", body)
        if tag not in allowed_tags or "{..." in compact_body:
            raise readiness.ReadinessContractError(f"{label} JSX scope differs")
        for attribute in re.findall(
            r"\b([A-Za-z_:][A-Za-z0-9_:.-]*)\s*=",
            body,
        ):
            if attribute not in allowed_properties and not attribute.startswith(
                "data-"
            ):
                raise readiness.ReadinessContractError(
                    f"{label} JSX property differs"
                )


def _validate_phase04_frontend_type_only_remainder(
    code: str,
) -> None:
    index = 0
    while index < len(code):
        while index < len(code) and (code[index].isspace() or code[index] == ";"):
            index += 1
        if index >= len(code):
            return
        type_match = re.match(r"type\s+[A-Za-z_$][\w$]*\b", code[index:])
        if type_match is not None:
            cursor = index + type_match.end()
            depths = {"(": 0, "[": 0, "{": 0, "<": 0}
            closing_for = {")": "(", "]": "[", "}": "{", ">": "<"}
            while cursor < len(code):
                character = code[cursor]
                if character in depths:
                    depths[character] += 1
                elif character in closing_for:
                    opening_character = closing_for[character]
                    if depths[opening_character] > 0:
                        depths[opening_character] -= 1
                elif character == "\n" and all(
                    depth == 0 for depth in depths.values()
                ):
                    raise readiness.ReadinessContractError(
                        "hardened Phase 04 frontend helper module scope differs"
                    )
                elif character == ";" and all(
                    depth == 0 for depth in depths.values()
                ):
                    index = cursor + 1
                    break
                cursor += 1
            else:
                raise readiness.ReadinessContractError(
                    "hardened Phase 04 frontend helper module scope differs"
                )
            continue
        interface_match = re.match(
            r"interface\s+[A-Za-z_$][\w$]*\b",
            code[index:],
        )
        if interface_match is not None:
            body_start = code.find("{", index + interface_match.end())
            if body_start < 0:
                raise readiness.ReadinessContractError(
                    "hardened Phase 04 frontend helper module scope differs"
                )
            body_end = _phase04_frontend_matching_delimiter(
                code, body_start, "{", "}"
            )
            index = body_end + 1
            continue
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend helper module scope differs"
        )


def _validate_phase04_frontend_helper_surface(source: str) -> None:
    if _phase04_frontend_has_forbidden_scope(source):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend helper scope differs"
        )
    code = _phase04_mask_frontend_code(source)
    export_tokens = list(re.finditer(r"\bexport\b", code))
    exported_functions = list(
        re.finditer(
            r"\bexport\s+function\s+"
            r"([A-Za-z_$][\w$]*)\s*\(([^)]*)\)",
            code,
        )
    )
    if (
        len(export_tokens) != 1
        or len(exported_functions) != 1
        or export_tokens[0].start() != exported_functions[0].start()
        or exported_functions[0].group(1) != "readTableSemantics"
        or re.search(r"\b(?:exports|module)\b", code)
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend helper public surface differs"
        )
    arguments = [
        value.strip()
        for value in exported_functions[0].group(2).split(",")
        if value.strip()
    ]
    if (
        len(arguments) != 1
        or arguments[0].split(":", 1)[0].strip() != "item"
        or "=" in arguments[0]
        or "..." in arguments[0]
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend helper public surface differs"
        )
    parameter_start = code.find("(", exported_functions[0].start())
    parameter_end = _phase04_frontend_matching_delimiter(
        code, parameter_start, "(", ")"
    )
    body_start = code.find("{", parameter_end + 1)
    if body_start < 0:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend helper public surface differs"
        )
    body_end = _phase04_frontend_matching_delimiter(
        code, body_start, "{", "}"
    )
    remainder = (
        code[: exported_functions[0].start()]
        + code[body_end + 1 :]
    )
    _validate_phase04_frontend_type_only_remainder(remainder)


def _validate_phase04_frontend_protected_bindings(
    code: str,
    *,
    label: str,
    records: list[tuple[str, set[str], str, bool]],
    local_functions: set[str],
) -> set[str]:
    parameter_bindings: set[str] = set()
    for _name, parameters, _body, _exported in records:
        parameter_bindings.update(parameters)
    for match in re.finditer(
        r"\(([^()]*)\)\s*(?::[^=;\n]+)?=>",
        code,
    ):
        parameter_bindings.update(
            _phase04_frontend_parameter_bindings(match.group(1))
        )
    for match in re.finditer(
        r"(?<![A-Za-z0-9_$])([A-Za-z_$][\w$]*)\s*"
        r"(?::[^=;\n]+)?=>",
        code,
    ):
        parameter_bindings.add(match.group(1))
    protected_bindings = (
        _PHASE04_FRONTEND_PROTECTED_DIRECT_CALLS
        | _PHASE04_FRONTEND_PROTECTED_STATIC_ROOTS
    )
    if parameter_bindings & (protected_bindings | local_functions):
        raise readiness.ReadinessContractError(
            f"{label} protected callable binding differs"
        )

    for name, _parameters, _body, exported in records:
        if name not in protected_bindings:
            continue
        if not (
            label == "hardened Phase 04 frontend helper"
            and name == "readTableSemantics"
            and exported
        ):
            raise readiness.ReadinessContractError(
                f"{label} protected callable binding differs"
            )

    for name in protected_bindings:
        escaped = re.escape(name)
        if re.search(
            rf"(?:\b(?:const|let|var)\s+|,)\s*{escaped}\b\s*"
            r"(?::[^=,;\n]+)?(?:=|,|;|\n)",
            code,
        ) or re.search(
            rf"\b(?:const|let|var)\s*[{{[][^;\n]*\b{escaped}\b",
            code,
        ):
            raise readiness.ReadinessContractError(
                f"{label} protected callable binding differs"
            )
        if re.search(
            rf"(?<![A-Za-z0-9_$.]){escaped}\s*"
            rf"(?:\+\+|--|{_PHASE04_FRONTEND_ASSIGNMENT_OPERATOR})",
            code,
        ) or re.search(
            rf"(?:\+\+|--)\s*{escaped}(?![A-Za-z0-9_$])",
            code,
        ) or re.search(
            rf"[{{[][^;\n]*\b{escaped}\b[^;\n]*[}}\]]\s*"
            rf"{_PHASE04_FRONTEND_ASSIGNMENT_OPERATOR}",
            code,
        ):
            raise readiness.ReadinessContractError(
                f"{label} protected callable binding differs"
            )

    declared_bindings = set(
        re.findall(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b",
            code,
        )
    )
    declared_bindings.update(parameter_bindings)
    declared_bindings.update(name for name, *_rest in records)
    if label == "hardened Phase 04 frontend table branch":
        declared_bindings.update(_PHASE04_FRONTEND_MAIN_BINDINGS)
    return declared_bindings


def _validate_phase04_frontend_static_roots(
    code: str,
    *,
    label: str,
) -> None:
    """Allow built-in static roots only as exact reviewed method calls."""

    roots = "|".join(sorted(_PHASE04_FRONTEND_PROTECTED_STATIC_ROOTS))
    for match in re.finditer(
        rf"(?<![A-Za-z0-9_$])(?P<root>{roots})(?![A-Za-z0-9_$])",
        code,
    ):
        root = match.group("root")
        methods = "|".join(
            sorted(_PHASE04_FRONTEND_SAFE_STATIC_METHODS[root])
        )
        if re.match(
            rf"\s*\.\s*(?:{methods})\s*\(",
            code[match.end() :],
        ) is None:
            raise readiness.ReadinessContractError(
                f"{label} static root differs"
            )


def _validate_phase04_frontend_object_literal_hooks(
    source: str,
    code: str,
    *,
    label: str,
) -> None:
    hook_names = r"(?:toString|valueOf|toJSON)"
    if (
        re.search(
            rf"[{{,]\s*(?:(?:get|set|async)\s+)?\*?\s*{hook_names}\s*"
            r"(?::|\(|(?=[,}]))",
            code,
        )
        or re.search(
            rf"[{{,]\s*['\"]{hook_names}['\"]\s*(?::|\()",
            source,
        )
        or re.search(
            r"[{{,]\s*(?:get|set)\s+"
            r"(?:[A-Za-z_$][\w$]*|['\"][^'\"]+['\"])\s*\(",
            code,
        )
        or re.search(
            r"[{{,]\s*(?:(?:get|set|async)\s+)?\*?\s*"
            r"\[[^\]\n]*\]\s*(?::|\()",
            code,
        )
        or re.search(
            r"[{{,]\s*\[\s*Symbol\s*\.\s*"
            r"(?:asyncIterator|hasInstance|iterator|match|replace|search|"
            r"species|split|toPrimitive|toStringTag)\s*\]",
            code,
        )
    ):
        raise readiness.ReadinessContractError(
            f"{label} implicit coercion hook differs"
        )


def _phase04_frontend_owned_local_bindings(
    code: str,
    *,
    records: list[tuple[str, set[str], str, bool]],
    safe_methods: set[str],
) -> set[str]:
    """Prove method receivers originate from locally owned values."""

    parameter_bindings: set[str] = set()
    for _name, parameters, _body, _exported in records:
        parameter_bindings.update(parameters)
    for match in re.finditer(r"\(([^()]*)\)\s*(?::[^=;\n]+)?=>", code):
        parameter_bindings.update(
            _phase04_frontend_parameter_bindings(match.group(1))
        )
    for match in re.finditer(
        r"(?<![A-Za-z0-9_$])([A-Za-z_$][\w$]*)\s*"
        r"(?::[^=;\n]+)?=>",
        code,
    ):
        parameter_bindings.add(match.group(1))

    declarations = [
        (match.group("name"), match.group("value").strip())
        for match in re.finditer(
            r"\bconst\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
            r"(?::[^=;\n]+)?=\s*(?P<value>[^;\n]+)",
            code,
        )
    ]
    owned: set[str] = set()
    owned_result_methods = safe_methods - {"at", "find", "reduce"}

    def complete_call(value: str, opening: int) -> bool:
        try:
            closing = _phase04_frontend_matching_delimiter(
                value, opening, "(", ")"
            )
        except readiness.ReadinessContractError:
            return False
        return not value[closing + 1 :].strip()

    def initializer_is_owned(value: str) -> bool:
        if not value or re.match(
            r"(?:\([^)]*\)|[A-Za-z_$][\w$]*(?:\s*:[^=;\n]+)?)\s*"
            r"(?::\s*[^=;\n]+)?=>",
            value,
        ):
            return False
        if value.startswith("["):
            try:
                closing = _phase04_frontend_matching_delimiter(
                    value, 0, "[", "]"
                )
            except readiness.ReadinessContractError:
                return False
            return not value[closing + 1 :].strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", value):
            return value in owned
        direct = re.match(r"(?:Boolean|Number|String)\s*\(", value)
        if direct is not None:
            return complete_call(value, value.find("(", direct.start()))
        static = re.match(
            r"(?:Array\.isArray|JSON\.stringify|Number\.isFinite|"
            r"Object\.(?:entries|keys|values))\s*\(",
            value,
        )
        if static is not None:
            return complete_call(value, value.find("(", static.start()))
        method = re.match(
            r"(?P<receiver>[A-Za-z_$][\w$]*)\."
            r"(?P<method>[A-Za-z_$][\w$]*)\s*\(",
            value,
        )
        return bool(
            method is not None
            and method.group("receiver") in owned
            and method.group("method") in owned_result_methods
            and complete_call(value, value.find("(", method.start()))
        )

    for name, initializer in declarations:
        if name in parameter_bindings:
            continue
        if initializer_is_owned(initializer):
            owned.add(name)
    for name in owned:
        assignments = len(
            re.findall(
                rf"(?<![A-Za-z0-9_$.]){re.escape(name)}\s*"
                r"(?::[^=;\n]+)?"
                rf"(?:\+\+|--|{_PHASE04_FRONTEND_ASSIGNMENT_OPERATOR})",
                code,
            )
        )
        destructuring_rebind = re.search(
            rf"[{{[][^;\n]*\b{re.escape(name)}\b[^;\n]*[}}\]]\s*"
            rf"{_PHASE04_FRONTEND_ASSIGNMENT_OPERATOR}",
            code,
        )
        if assignments != 1 or destructuring_rebind is not None:
            raise readiness.ReadinessContractError(
                "hardened Phase 04 frontend method target differs"
            )
    return owned


def _validate_phase04_frontend_text(
    source: str,
    *,
    label: str,
    baseline_sha256: str | None = None,
) -> None:
    allow_jsx = label == "hardened Phase 04 frontend table branch"
    try:
        _phase04_frontend_source_preflight(source)
    except readiness.ReadinessContractError as exc:
        raise readiness.ReadinessContractError(f"{label} scope differs") from exc
    if (
        baseline_sha256 is not None
        and hashlib.sha256(source.encode("utf-8")).hexdigest() == baseline_sha256
    ):
        return
    lowered = _phase04_frontend_casefold_bounded(source)
    compacted = re.sub(r"\s+", "", lowered)
    forbidden_literals = (
        "running_region",
        "running-region",
        "dangerouslysetinnerhtml",
        ".innerhtml",
        ".outerhtml",
        "<script",
        "file://",
        "ftp://",
        "http://",
        "https://",
        "__proto__",
        "${",
        ".href",
        ".src",
    )
    sensitive_names = (
        "apply",
        "bind",
        "browser",
        "broadcastchannel",
        "bun",
        "caches",
        "call",
        "chrome",
        "constructor",
        "cookiestore",
        "createelement",
        "crypto",
        "deno",
        "defineproperty",
        "document",
        "eval",
        "eventsource",
        "fetch",
        "fs",
        "frames",
        "getownpropertydescriptor",
        "getownpropertydescriptors",
        "getownpropertynames",
        "global",
        "globalthis",
        "history",
        "import",
        "indexeddb",
        "location",
        "localstorage",
        "navigator",
        "opener",
        "parent",
        "performance",
        "process",
        "prototype",
        "proxy",
        "reflect",
        "require",
        "screen",
        "sendbeacon",
        "self",
        "sessionstorage",
        "setinterval",
        "settimeout",
        "sharedworker",
        "top",
        "visualviewport",
        "webassembly",
        "websocket",
        "window",
        "worker",
        "xmlhttprequest",
    )
    if (
        re.search(
            r"\\(?:u[0-9a-fA-F]{4}|u\{[0-9a-fA-F]{1,6}\}|x[0-9a-fA-F]{2})",
            source,
        )
        or any(value in compacted for value in forbidden_literals)
        or _phase04_frontend_has_forbidden_scope(
            source,
            allow_jsx=allow_jsx,
        )
        or any(
        re.search(
            _phase04_frontend_fragment_pattern(value),
            source,
            flags=re.IGNORECASE,
        )
        for value in sensitive_names
        )
    ):
        raise readiness.ReadinessContractError(f"{label} scope differs")
    code = _phase04_mask_frontend_code(source)
    _validate_phase04_frontend_object_literal_hooks(
        source,
        code,
        label=label,
    )
    structural = re.sub(r"\s+", "", code)
    tagged_template = re.search(
        r"(?P<target>[A-Za-z_$][\w$]*|\)|\])\s*`",
        code,
    )
    if (
        re.search(r"\bfunction\s*\(", code, flags=re.IGNORECASE)
        or "?." in structural
        or re.search(
            r"(?:[A-Za-z_$][\w$]*|\)|\]|\})!(?:\.|\[|\()",
            structural,
        )
        or re.search(r"(?<![A-Za-z0-9_$])Function(?![A-Za-z0-9_$])", code)
        or re.search(r"\basync\b", code)
        or re.search(r"\)(?:\?\.)?\(", structural)
        or re.search(r"\]\s*\(", code)
        or re.search(r"\)(?:\?\.|\.)(?:[A-Za-z_$][\w$]*|\[)", structural)
        or re.search(
            r"(?:[A-Za-z_$][\w$]*|\)|\])<[^;{}]*>\(",
            structural,
        )
        or (
            tagged_template is not None
            and tagged_template.group("target")
            not in {"case", "delete", "return", "throw", "typeof", "void", "yield"}
        )
        or re.search(r"\bnew\b", code, flags=re.IGNORECASE)
        or re.search(r"\b(?:module|exports)\b", code)
        or re.search(r"\busing\b", code)
        or "..." in code
        or "@" in code
    ):
        raise readiness.ReadinessContractError(f"{label} callable target differs")
    property_assignment = (
        rf"(?:{_PHASE04_FRONTEND_ASSIGNMENT_OPERATOR}|\+\+|--)"
    )
    if re.search(
        r"(?:[A-Za-z_$][\w$]*|\]|\))"
        r"(?:\.[A-Za-z_$][\w$]*|\[[0-9]+\])+"
        rf"{property_assignment}",
        structural,
    ) or re.search(
        r"(?:\+\+|--)"
        r"(?:[A-Za-z_$][\w$]*|\]|\))"
        r"(?:\.[A-Za-z_$][\w$]*|\[[0-9]+\])+",
        structural,
    ):
        raise readiness.ReadinessContractError(
            f"{label} property mutation differs"
        )
    if re.search(
        r"[\[{][^;\n]*(?:[A-Za-z_$][\w$]*|\])"
        r"(?:\.[A-Za-z_$][\w$]*|\[[0-9]+\])+[^;\n]*[\]}]"
        rf"{_PHASE04_FRONTEND_ASSIGNMENT_OPERATOR}",
        structural,
    ):
        raise readiness.ReadinessContractError(
            f"{label} property mutation differs"
        )
    computed_member = re.compile(
        r"(?P<receiver>[A-Za-z_$][\w$]*|\)|\]|\})"
        r"(?:\?\.)?\[(?P<member>[^\]]*)\]"
    )
    for match in computed_member.finditer(structural):
        member = match.group("member")
        receiver_start = match.start("receiver")
        type_array_suffix = (
            not member
            and receiver_start > 0
            and structural[receiver_start - 1] in {":", "|", "&"}
        )
        if not type_array_suffix and re.fullmatch(r"[0-9]+", member) is None:
            raise readiness.ReadinessContractError(
                f"{label} computed member differs"
            )

    records = _phase04_frontend_callable_records(code)
    local_functions = _validate_phase04_frontend_callable_graph(
        records,
        label=label,
    )
    _validate_phase04_frontend_protected_bindings(
        code,
        label=label,
        records=records,
        local_functions=local_functions,
    )
    _validate_phase04_frontend_static_roots(code, label=label)
    for name in local_functions:
        assignments = len(
            re.findall(
                rf"(?<![A-Za-z0-9_$.]){re.escape(name)}\s*"
                rf"(?:\+\+|--|{_PHASE04_FRONTEND_ASSIGNMENT_OPERATOR})",
                code,
            )
        )
        is_const_arrow = bool(
            re.search(
                rf"\bconst\s+{re.escape(name)}\s*(?::[^=;\n]+)?=\s*"
                r"(?:\([^)]*\)|[A-Za-z_$][\w$]*(?:\s*:[^=;\n]+)?)\s*"
                r"(?::\s*[^=;\n]+)?=>",
                code,
            )
        )
        destructuring_rebind = bool(
            re.search(
                rf"[{{[][^;\n]*\b{re.escape(name)}\b[^;\n]*[}}\]]\s*"
                rf"{_PHASE04_FRONTEND_ASSIGNMENT_OPERATOR}",
                code,
            )
        )
        if assignments != int(is_const_arrow) or destructuring_rebind:
            raise readiness.ReadinessContractError(
                f"{label} callable binding differs"
            )
    safe_methods = {
        "at",
        "entries",
        "every",
        "filter",
        "find",
        "flatMap",
        "forEach",
        "includes",
        "join",
        "keys",
        "map",
        "reduce",
        "slice",
        "some",
        "startsWith",
        "toLowerCase",
        "trim",
        "values",
    }
    safe_direct = {
        "Boolean",
        "Number",
        "String",
        "gateTableCandidates",
        "if",
        "readTableSemantics",
        "renderValidatedTextRunOverlay",
        *local_functions,
    }
    owned_bindings = _phase04_frontend_owned_local_bindings(
        code,
        records=records,
        safe_methods=safe_methods,
    )
    frozen_safe_callbacks = {"Boolean", "Number", "String"}
    for match in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", code):
        name = match.group(1)
        prefix = code[: match.start(1)].rstrip()
        if prefix.endswith("."):
            receiver_match = re.search(
                r"(?P<root>[A-Za-z_$][\w$]*)"
                r"(?P<path>(?:\s*(?:\.\s*[A-Za-z_$][\w$]*"
                r"|\[\s*[0-9]+\s*\]))*)"
                r"\s*\.\s*$",
                prefix,
            )
            receiver = (
                receiver_match.group("root") if receiver_match else None
            )
            receiver_path = (
                receiver_match.group("path").strip()
                if receiver_match
                else None
            )
            static_allowed = (
                receiver is not None
                and name
                in _PHASE04_FRONTEND_SAFE_STATIC_METHODS.get(
                    receiver,
                    frozenset(),
                )
            )
            bound_allowed = (
                receiver is not None
                and receiver in owned_bindings
                and not receiver_path
                and name in safe_methods
            )
            if not (static_allowed or bound_allowed):
                raise readiness.ReadinessContractError(
                    f"{label} method target differs"
                )
            opening = code.rfind("(", match.start(), match.end())
            arguments = _phase04_frontend_call_arguments(code, opening)
            if receiver == "JSON" and name == "stringify" and len(arguments) != 1:
                raise readiness.ReadinessContractError(
                    f"{label} static call arguments differ"
                )
            if name in _PHASE04_FRONTEND_CALLBACK_METHODS:
                callback = arguments[0].strip() if arguments else ""
                inline_arrow = re.match(
                    r"^(?:\([^)]*\)|[A-Za-z_$][\w$]*"
                    r"(?:\s*:\s*[^=]+)?)\s*(?::[^=]+)?=>",
                    callback,
                )
                if (
                    callback not in local_functions
                    and callback not in frozen_safe_callbacks
                    and inline_arrow is None
                ):
                    raise readiness.ReadinessContractError(
                        f"{label} callback provenance differs"
                    )
            continue
        if name not in safe_direct:
            raise readiness.ReadinessContractError(
                f"{label} callable target differs"
            )
    _validate_phase04_frontend_jsx(source, label=label)


def _validate_hardened_phase04_frontend(
    raw: bytes,
    *,
    helper_raw: bytes | None,
) -> None:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend custody differs"
        ) from exc
    start_marker = '  if (type === "table") {'
    end_marker = '  if (type === "list") {'
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend table branch differs"
        )
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    _validate_phase04_frontend_text(
        source[start:end],
        label="hardened Phase 04 frontend table branch",
        baseline_sha256=EXPECTED_PHASE04_BASELINE_TABLE_BLOCK_SHA256,
    )
    if (
        _phase04_frontend_normalized_digest(raw)
        != EXPECTED_PHASE04_FRONTEND_NORMALIZED_SHA256
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 frontend custody differs"
        )
    if helper_raw is not None:
        try:
            helper = helper_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise readiness.ReadinessContractError(
                "hardened Phase 04 frontend helper differs"
            ) from exc
        _validate_phase04_frontend_text(
            helper,
            label="hardened Phase 04 frontend helper",
        )
        _validate_phase04_frontend_helper_surface(helper)


def _validate_phase04_renewal(
    root: Path,
    *,
    current_code: Mapping[str, Mapping[str, Any]],
    phase04_baseline_code: Mapping[str, Mapping[str, Any]],
    expected_history: Mapping[str, Any],
    frontend_renewal: Mapping[str, Any],
    original_waiver: Mapping[str, Any],
    today: date | None,
    ancestry_only: bool = False,
) -> tuple[
    dict[str, Any],
    bytes,
    tuple[
        tuple[int, int, int, int, int, int, int],
        tuple[tuple[int, int, int, int, int, int, int], ...],
    ],
    list[
        tuple[
            str,
            int,
            str,
            bytes,
            tuple[
                tuple[int, int, int, int, int, int, int],
                tuple[tuple[int, int, int, int, int, int, int], ...],
            ],
        ]
    ],
]:
    """Validate the table-only bridge without broadening P03-US08."""

    raw, binding = _read_bound_file(
        root,
        str(PHASE04_RENEWAL_WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label="Phase 04 latency renewal waiver",
    )
    if (
        len(raw) != EXPECTED_PHASE04_RENEWAL_WAIVER_IDENTITY["size_bytes"]
        or hashlib.sha256(raw).hexdigest()
        != EXPECTED_PHASE04_RENEWAL_WAIVER_IDENTITY["raw_sha256"]
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal waiver differs"
        )
    renewal = _strict_json(raw, "Phase 04 latency renewal waiver")
    if raw != _pretty_json_bytes(renewal):
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal waiver bytes differ"
        )
    if (
        renewal.get("semantic_sha256")
        != EXPECTED_PHASE04_RENEWAL_WAIVER_IDENTITY["semantic_sha256"]
        or renewal.get("semantic_sha256") != waiver_semantic_sha256(renewal)
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal waiver digest differs"
        )
    expected_top_level = frozenset(
        {
            "approval",
            "authorized_change",
            "decision_identity",
            "deferred_work",
            "exception_scope",
            "expiry",
            "failed_history",
            "hosted_usage",
            "not_waived",
            "operational_constraints",
            "prior_renewal_identity",
            "record_kind",
            "renewal_id",
            "renews_renewal_id",
            "schema_version",
            "semantic_sha256",
            "status",
            "story",
        }
    )
    _exact_keys(renewal, expected_top_level, "Phase 04 latency renewal waiver")
    if {
        key: renewal[key]
        for key in (
            "schema_version",
            "record_kind",
            "story",
            "renewal_id",
            "renews_renewal_id",
            "status",
        )
    } != {
        "schema_version": "1.0",
        "record_kind": "p03_us08_phase04_tables_latency_exception_renewal",
        "story": "P03-US08",
        "renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES"
        ),
        "renews_renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX"
        ),
        "status": "accepted_with_time_bounded_metrics_exception_renewal",
    }:
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal identity differs"
        )
    if renewal["approval"] != {
        "authorized_on": "2026-08-03",
        "owner": "project owner/requester",
        "source": "active Codex thread",
        "statement": EXPECTED_PHASE04_APPROVAL_STATEMENT,
    }:
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal approval differs"
        )
    if (
        renewal["exception_scope"] != frontend_renewal["exception_scope"]
        or renewal["exception_scope"] != original_waiver["exception_scope"]
        or renewal["failed_history"] != expected_history
        or renewal["failed_history"] != EXPECTED_FAILED_HISTORY
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal observation differs"
        )
    for field in (
        "deferred_work",
        "hosted_usage",
        "not_waived",
        "operational_constraints",
    ):
        if renewal[field] != original_waiver[field]:
            raise readiness.ReadinessContractError(
                f"Phase 04 latency renewal {field.replace('_', ' ')} differs"
            )
    if renewal["prior_renewal_identity"] != {
        "path": str(RENEWAL_WAIVER_PATH),
        **EXPECTED_RENEWAL_WAIVER_IDENTITY,
    }:
        raise readiness.ReadinessContractError(
            "Phase 04 prior renewal identity differs"
        )

    expiry = renewal["expiry"]
    expected_expiry = {
        "expired_effect": (
            "P03-US08 returns to In Progress and dependent exit claims are blocked"
        ),
        "expires_before": [
            "production enablement of running regions",
            "running-region semantic or runtime behavior change",
            "relevant running-region custody change",
            "authorized Phase 04 scope expansion",
        ],
        "review_due_on": "2026-09-02",
    }
    try:
        review_due = date.fromisoformat(expiry["review_due_on"])
    except (KeyError, TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal expiry differs"
        ) from exc
    if expiry != expected_expiry or (today or datetime.now(tz=UTC).date()) > review_due:
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal expired"
        )

    authorized = renewal["authorized_change"]
    if not isinstance(authorized, Mapping) or set(authorized) != {
        "added_phase04_paths",
        "allowed_existing_paths",
        "baseline_code_manifest_sha256",
        "baseline_files",
        "difference_scope",
        "phase04_only",
        "protected_surfaces",
        "running_region_behavior_changed",
        "running_region_custody_changed",
    }:
        raise readiness.ReadinessContractError(
            "Phase 04 authorized change differs"
        )
    if (
        tuple(authorized["allowed_existing_paths"])
        != EXPECTED_PHASE04_EXISTING_PATHS
        or tuple(authorized["added_phase04_paths"]) != EXPECTED_PHASE04_ADDED_PATHS
        or authorized["baseline_code_manifest_sha256"]
        != EXPECTED_RENEWAL_CODE_MANIFEST_SHA256
        or authorized["baseline_files"] != EXPECTED_PHASE04_BASELINE_FILES
        or authorized["phase04_only"] is not True
        or authorized["running_region_behavior_changed"] is not False
        or authorized["running_region_custody_changed"] is not False
        or authorized["difference_scope"]
        != "unrelated default-off Phase 04 table implementation, tests, and rendering only"
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 authorized change differs"
        )
    protected = authorized["protected_surfaces"]
    if not isinstance(protected, Mapping) or set(protected) != {
        "app/config.py",
        "app/services/pipeline.py",
        "frontend/app/clearleaf-workspace.tsx",
    }:
        raise readiness.ReadinessContractError(
            "Phase 04 protected surface differs"
        )
    if (
        protected["app/config.py"].get("normalized_ast_sha256")
        != EXPECTED_PHASE04_CONFIG_NORMALIZED_AST_SHA256
        or frozenset(
            protected["app/services/pipeline.py"].get(
                "allowed_function_names", []
            )
        )
        != EXPECTED_PHASE04_PIPELINE_FUNCTIONS
        or protected["app/services/pipeline.py"].get("normalized_ast_sha256")
        != EXPECTED_PHASE04_PIPELINE_NORMALIZED_AST_SHA256
        or protected["frontend/app/clearleaf-workspace.tsx"].get(
            "allowed_helper_import"
        )
        != EXPECTED_PHASE04_FRONTEND_IMPORT
        or protected["frontend/app/clearleaf-workspace.tsx"].get(
            "normalized_source_sha256"
        )
        != EXPECTED_PHASE04_FRONTEND_NORMALIZED_SHA256
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 protected surface contract differs"
        )

    if ancestry_only:
        decision = renewal["decision_identity"]
        if decision != EXPECTED_PHASE04_RENEWAL_DECISION_IDENTITY:
            raise readiness.ReadinessContractError(
                "Phase 04 latency renewal decision identity differs"
            )
        decision_raw, decision_binding = _read_bound_file(
            root,
            decision["path"],
            maximum_bytes=DECISION_MAXIMUM_BYTES,
            label="Phase 04 latency renewal decision",
        )
        if (
            len(decision_raw) != decision["size_bytes"]
            or hashlib.sha256(decision_raw).hexdigest() != decision["raw_sha256"]
            or renewal["renewal_id"].encode("utf-8") not in decision_raw
            or renewal["renews_renewal_id"].encode("utf-8") not in decision_raw
        ):
            raise readiness.ReadinessContractError(
                "Phase 04 latency renewal decision differs"
            )
        return renewal, raw, binding, [
            (
                decision["path"],
                DECISION_MAXIMUM_BYTES,
                "Phase 04 latency renewal decision",
                decision_raw,
                decision_binding,
            )
        ]

    if set(current_code) != set(phase04_baseline_code):
        raise readiness.ReadinessContractError(
            "Phase 04 required-code path set differs"
        )
    changed_paths = {
        path
        for path in current_code
        if current_code[path] != phase04_baseline_code[path]
    }
    if not changed_paths <= set(EXPECTED_PHASE04_EXISTING_PATHS):
        raise readiness.ReadinessContractError(
            "running-region protected code changed"
        )

    tracks: list[
        tuple[
            str,
            int,
            str,
            bytes,
            tuple[
                tuple[int, int, int, int, int, int, int],
                tuple[tuple[int, int, int, int, int, int, int], ...],
            ],
        ]
    ] = []
    observed_raw: dict[str, bytes] = {}
    for path in (*EXPECTED_PHASE04_EXISTING_PATHS, *EXPECTED_PHASE04_ADDED_PATHS):
        candidate = root.joinpath(*PurePosixPath(path).parts)
        if path in EXPECTED_PHASE04_ADDED_PATHS and not (
            candidate.exists() or candidate.is_symlink()
        ):
            continue
        code_raw, code_binding = _read_bound_file(
            root,
            path,
            maximum_bytes=2 * 1024 * 1024,
            label="Phase 04 code",
        )
        observed_raw[path] = code_raw
        tracks.append((path, 2 * 1024 * 1024, "Phase 04 code", code_raw, code_binding))
    if (
        _phase04_config_normalized_digest(observed_raw["app/config.py"])
        != EXPECTED_PHASE04_CONFIG_NORMALIZED_AST_SHA256
        or _phase04_pipeline_normalized_digest(observed_raw["app/services/pipeline.py"])
        != EXPECTED_PHASE04_PIPELINE_NORMALIZED_AST_SHA256
        or _phase04_frontend_normalized_digest(
            observed_raw["frontend/app/clearleaf-workspace.tsx"]
        )
        != EXPECTED_PHASE04_FRONTEND_NORMALIZED_SHA256
    ):
        raise readiness.ReadinessContractError(
            "running-region shared surface changed"
        )

    decision = renewal["decision_identity"]
    if decision != EXPECTED_PHASE04_RENEWAL_DECISION_IDENTITY:
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal decision identity differs"
        )
    decision_raw, decision_binding = _read_bound_file(
        root,
        decision["path"],
        maximum_bytes=DECISION_MAXIMUM_BYTES,
        label="Phase 04 latency renewal decision",
    )
    if (
        len(decision_raw) != decision["size_bytes"]
        or hashlib.sha256(decision_raw).hexdigest() != decision["raw_sha256"]
        or renewal["renewal_id"].encode("utf-8") not in decision_raw
        or renewal["renews_renewal_id"].encode("utf-8") not in decision_raw
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal decision differs"
        )
    tracks.append(
        (
            decision["path"],
            DECISION_MAXIMUM_BYTES,
            "Phase 04 latency renewal decision",
            decision_raw,
            decision_binding,
        )
    )
    return renewal, raw, binding, tracks


def _expected_hardened_phase04_authorized_change() -> dict[str, Any]:
    baseline_files = {
        path: dict(EXPECTED_PHASE04_BASELINE_FILES[path])
        for path in (
            "app/config.py",
            "app/services/pipeline.py",
            "app/services/tables.py",
            "frontend/app/clearleaf-workspace.tsx",
        )
    }
    baseline_files[".env.example"] = dict(
        EXPECTED_HARDENED_ENV_EXAMPLE_IDENTITY
    )
    baseline_files["app/services/source_text_alignment.py"] = dict(
        EXPECTED_HARDENED_SOURCE_ALIGNMENT_IDENTITY
    )
    baseline_files["app/services/text_reconciliation.py"] = dict(
        EXPECTED_HARDENED_TEXT_RECONCILIATION_IDENTITY
    )
    baseline_files[
        "tests/performance/test_p03_us08_running_region_metrics_contract.py"
    ] = dict(EXPECTED_HARDENED_METRICS_CONTRACT_BASELINE_IDENTITY)
    return {
        "added_phase04_paths": list(EXPECTED_HARDENED_PHASE04_ADDED_PATHS),
        "allowed_existing_paths": list(EXPECTED_HARDENED_EXISTING_PATHS),
        "baseline_code_manifest_sha256": EXPECTED_RENEWAL_CODE_MANIFEST_SHA256,
        "baseline_files": baseline_files,
        "difference_scope": (
            "unrelated default-off Phase 04 table implementation, tests, "
            "rendering, exact replay hooks, source cell geometry extraction, "
            "and exact default-off environment examples only"
        ),
        "phase04_only": True,
        "protected_surfaces": {
            ".env.example": {
                "exact_phase04_suffix": (
                    EXPECTED_HARDENED_ENV_EXAMPLE_PHASE04_SUFFIX
                ),
                "normalization": (
                    "remove only four unique ordered default-false Phase 04 "
                    "table lines appended immediately after the unchanged "
                    "running-region line at end of file"
                ),
                "normalized_raw_sha256": (
                    EXPECTED_HARDENED_ENV_EXAMPLE_IDENTITY["sha256"]
                ),
            },
            "app/config.py": {
                "exact_dependency_guard_ast_sha256": [
                    _ast_digest(ast.parse(source).body[0])
                    for source in EXPECTED_PHASE04_CONFIG_GUARD_SOURCES
                ],
                "normalization": (
                    "remove only the four default-false table Settings fields, "
                    "four exact ordered dependency guard ASTs, and four exact "
                    "default-false environment bindings"
                ),
                "normalized_ast_sha256": (
                    EXPECTED_PHASE04_CONFIG_NORMALIZED_AST_SHA256
                ),
            },
            "app/services/pipeline.py": {
                "allowed_function_names": sorted(
                    EXPECTED_HARDENED_PHASE04_PIPELINE_FUNCTIONS
                    | EXPECTED_HARDENED_PHASE04_PIPELINE_EXACT_FUNCTIONS
                ),
                "broad_helper_function_names": sorted(
                    EXPECTED_HARDENED_PHASE04_PIPELINE_FUNCTIONS
                ),
                "exact_vector_geometry_function_name": "_parse_loaded_document",
                "exact_vector_geometry_try_ast_sha256": (
                    EXPECTED_HARDENED_PIPELINE_VECTOR_GEOMETRY_TRY_AST_SHA256
                ),
                "allowed_import_module": "app.services.table_semantics",
                "allowed_signature_keywords": sorted(
                    EXPECTED_HARDENED_PHASE04_SETTING_NAMES
                ),
                "baseline_function_ast_sha256": dict(
                    sorted(EXPECTED_HARDENED_PIPELINE_FUNCTION_AST_SHA256.items())
                ),
                "exact_helper_call_graph_sha256": metrics._sha256_json(
                    EXPECTED_HARDENED_PIPELINE_HELPER_CALLS
                ),
                "exact_forwarding_call_graph_sha256": metrics._sha256_json(
                    {
                        function_name: {
                            callee: sorted(settings)
                            for callee, settings in calls.items()
                        }
                        for function_name, calls in (
                            EXPECTED_HARDENED_PIPELINE_FORWARDING_CALLS.items()
                        )
                    }
                ),
                "glue_contract": (
                    "exact local table_semantics imports, exact helper call "
                    "counts and positions, exact assignment forms, exact local "
                    "or enumerated context-field positional arguments, and exact "
                    "default-false table flag forwarding only; unrelated table "
                    "keywords are never normalized away"
                ),
                "normalized_module_ast_sha256": (
                    EXPECTED_HARDENED_PIPELINE_MODULE_AST_SHA256
                ),
            },
            "app/services/source_text_alignment.py": {
                "allowed_function_name": "_refresh_table",
                "exact_hook": EXPECTED_HARDENED_SOURCE_ALIGNMENT_HOOK,
                "normalized_function_ast_sha256": (
                    EXPECTED_HARDENED_SOURCE_ALIGNMENT_REFRESH_AST_SHA256
                ),
                "normalized_module_ast_sha256": (
                    EXPECTED_HARDENED_SOURCE_ALIGNMENT_MODULE_AST_SHA256
                ),
                "normalized_raw_sha256": (
                    EXPECTED_HARDENED_SOURCE_ALIGNMENT_IDENTITY["sha256"]
                ),
            },
            "app/services/tables.py": {
                "allowed_top_level_nodes": list(
                    EXPECTED_HARDENED_TABLES_ALLOWED_NODES
                ),
                "atomic_baseline_node_ast_sha256": dict(
                    EXPECTED_HARDENED_TABLES_BASELINE_NODE_AST_SHA256
                ),
                "atomic_geometry_node_ast_sha256": dict(
                    EXPECTED_HARDENED_TABLES_GEOMETRY_NODE_AST_SHA256
                ),
                "baseline_raw_sha256": (
                    EXPECTED_HARDENED_TABLES_BASELINE_IDENTITY["sha256"]
                ),
                "normalization": (
                    "freeze the retained module and accept only the complete "
                    "predecessor or complete reviewed geometry node vector; "
                    "mixed states and whole-function wildcards are rejected"
                ),
                "retained_module_ast_sha256": (
                    EXPECTED_HARDENED_TABLES_RETAINED_MODULE_AST_SHA256
                ),
            },
            "app/services/text_reconciliation.py": {
                "allowed_function_name": "_ir_replace_owner_text",
                "exact_hook": EXPECTED_HARDENED_TEXT_RECONCILIATION_HOOK,
                "normalized_function_ast_sha256": (
                    EXPECTED_HARDENED_TEXT_RECONCILIATION_FUNCTION_AST_SHA256
                ),
                "normalized_module_ast_sha256": (
                    EXPECTED_HARDENED_TEXT_RECONCILIATION_MODULE_AST_SHA256
                ),
                "normalized_raw_sha256": (
                    EXPECTED_HARDENED_TEXT_RECONCILIATION_IDENTITY["sha256"]
                ),
            },
            "app/services/table_semantics.py": {
                "allowed_standard_library_symbols": {
                    module: list(symbols)
                    for module, symbols in EXPECTED_TABLE_SEMANTICS_IMPORTS.items()
                },
                "exact_bounded_helper_ast_sha256": {
                    "_assert_canonical_table_json": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_CANONICAL_ASSERT_SOURCE
                        ).body[0]
                    ),
                    "_bounded_table_iterable": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_BOUNDED_ITERABLE_SOURCE
                        ).body[0]
                    ),
                    "_bounded_table_text": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_BOUNDED_TEXT_SOURCE
                        ).body[0]
                    ),
                    "_check_table_deadline": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_DEADLINE_CHECK_SOURCE
                        ).body[0]
                    ),
                    "_assert_plain_table_value": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_PLAIN_ASSERT_SOURCE
                        ).body[0]
                    ),
                    "_validate_plain_table_value": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_PLAIN_VALUE_SOURCE
                        ).body[0]
                    ),
                    "_copy_table_mapping": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_MAPPING_COPY_SOURCE
                        ).body[0]
                    ),
                    "_copy_raw_table_graph": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_RAW_TABLE_GRAPH_SOURCE
                        ).body[0]
                    ),
                    "_assert_source_sha256": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_SOURCE_SHA_SOURCE
                        ).body[0]
                    ),
                    "_bounded_table_sha256": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_BOUNDED_SHA_SOURCE
                        ).body[0]
                    ),
                    "_canonical_table_json_bytes": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_CANONICAL_JSON_SOURCE
                        ).body[0]
                    ),
                    "_canonical_table_sha256": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_CANONICAL_SHA_SOURCE
                        ).body[0]
                    ),
                    "_plain_table_length": _ast_digest(
                        ast.parse(
                            EXPECTED_TABLE_SEMANTICS_PLAIN_LENGTH_SOURCE
                        ).body[0]
                    ),
                },
                "exact_default_off_guard_ast_sha256": {
                    name: _ast_digest(ast.parse(source).body[0])
                    for name, source in (
                        EXPECTED_TABLE_SEMANTICS_DEFAULT_OFF_GUARDS.items()
                    )
                },
                "exact_argument_validators_sha256": metrics._sha256_json(
                    EXPECTED_TABLE_SEMANTICS_ARGUMENT_VALIDATORS
                ),
                "exact_argument_validation_policies_sha256": metrics._sha256_json(
                    EXPECTED_TABLE_SEMANTICS_ARGUMENT_VALIDATION_POLICIES
                ),
                "exact_public_function_set": sorted(
                    EXPECTED_TABLE_SEMANTICS_PUBLIC_SIGNATURES
                ),
                "exact_public_signatures_sha256": metrics._sha256_json(
                    EXPECTED_TABLE_SEMANTICS_PUBLIC_SIGNATURES
                ),
                "opaque_attribute_allowlist": {
                    name: sorted(attributes)
                    for name, attributes in (
                        EXPECTED_TABLE_SEMANTICS_OPAQUE_ATTRIBUTES.items()
                    )
                },
                "project_imports_allowed": [
                    "from app.services.tables import RawTable"
                ],
                "scan_contract": (
                    "all nine exact public functions and default-off returns; "
                    "copy-return stages rebind validated copies while enumerated "
                    "in-place stages validate originals, with story-level atomicity "
                    "and exact canonical JSON serializer gates remaining non-waived; "
                    "one shared 250ms deadline per public operation; literal-only "
                    "module state; no borrowed aliases, decorators, classes, nested "
                    "definitions, comprehensions, reflection, dynamic execution, "
                    "project imports except the exact RawTable type, network, "
                    "subprocess, filesystem, or unknown method receivers/callbacks; "
                    "plain-data copying has depth/node/string/container/cycle/"
                    "deadline caps, resource-bearing work cannot amplify beneath "
                    "loops, explicit allocations and growth are cumulative-bounded, "
                    "and every loop is bounded"
                ),
            },
            "frontend/app/clearleaf-workspace.tsx": {
                "allowed_canonical_table_delegation": (
                    EXPECTED_PHASE04_CANONICAL_TABLE_DELEGATION
                ),
                "allowed_helper_import": EXPECTED_PHASE04_FRONTEND_IMPORT,
                "canonical_table_delegation_contract": (
                    "after the exact formSemantics branch only; select exactly "
                    "one sourcePage item by primary_element_id; require string "
                    "table type and an own table_evidence property; delegate "
                    "only that item to ContentItemView; otherwise return the "
                    "same canonicalFallback"
                ),
                "normalized_source_sha256": (
                    EXPECTED_PHASE04_FRONTEND_NORMALIZED_SHA256
                ),
                "table_block_end": '  if (type === "list") {',
                "table_block_start": '  if (type === "table") {',
            },
            "frontend/lib/table-semantics.ts": {
                "exact_exported_runtime_function": (
                    "non-async export function readTableSemantics(item)"
                ),
                "scan_contract": (
                    "forbid running-region coupling, computed or optional calls "
                    "and members, member dispatch on call/parenthesized results, "
                    "dynamic execution/import, CommonJS module/exports, browser/network/"
                    "storage/resource APIs, constructors, unsafe HTML, resource "
                    "or event JSX, JSX spreads, and additional runtime exports"
                ),
            },
            "frontend/tests/p04-us01-table-readiness.test.mts": {
                "exact_identity": dict(
                    EXPECTED_HARDENED_PHASE04_READINESS_TEST_IDENTITY
                ),
                "scope": (
                    "required pre-implementation Phase 04 readiness test; "
                    "identity-pinned and not a frozen P03 manifest member"
                ),
            },
            "tests/performance/test_p03_us08_running_region_metrics_contract.py": {
                "baseline_identity": dict(
                    EXPECTED_HARDENED_METRICS_CONTRACT_BASELINE_IDENTITY
                ),
                "candidate_identity": dict(
                    EXPECTED_HARDENED_METRICS_CONTRACT_CANDIDATE_IDENTITY
                ),
                "normalization": (
                    "accept only the exact frozen 86-path P03 contract or the "
                    "identity-bound administrative candidate that keeps that "
                    "manifest unchanged and separately closes exactly five "
                    "Phase 04 table-only paths with sixth-path negatives"
                ),
            },
        },
        "running_region_behavior_changed": False,
        "running_region_custody_changed": False,
        "sealed_exact_paths": {
            path: dict(identity)
            for path, identity in EXPECTED_HARDENED_SEALED_PATHS.items()
        },
    }


def _validate_second_additive_p04_us01_code_identity(
    raw: bytes,
    expected: Mapping[str, Any],
    *,
    path: str,
) -> None:
    identity = _exact_keys(
        expected,
        frozenset({"ast_sha256", "path", "raw_sha256", "size_bytes"}),
        "second-additive P04-US01 code identity",
    )
    if (
        identity["path"] != path
        or type(identity["size_bytes"]) is not int
        or len(raw) != identity["size_bytes"]
        or hashlib.sha256(raw).hexdigest() != identity["raw_sha256"]
    ):
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 code identity differs"
        )
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 code identity differs"
        ) from exc
    if _ast_digest(tree) != identity["ast_sha256"]:
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 code identity differs"
        )


def _validate_second_additive_p04_us01_authorization(
    root: Path,
    *,
    expected_history: Mapping[str, Any],
    hardened_renewal: Mapping[str, Any],
    original_waiver: Mapping[str, Any],
    pipeline_raw: bytes,
    table_semantics_raw: bytes,
    today: date | None,
) -> list[tuple[str, int, str, bytes, Any]]:
    """Bind final US01 code to the unchanged latency-exception facts."""

    authorization = _exact_keys(
        EXPECTED_SECOND_ADDITIVE_P04_US01_AUTHORIZATION,
        frozenset(
            {
                "approval_source",
                "difference_scope",
                "exception_scope",
                "failed_history",
                "hosted_usage",
                "not_waived",
                "operational_constraints",
                "prior_amendment_approval_identity",
                "prior_amendment_identity",
                "prior_focused_guard_identity",
                "prior_guard_identity",
                "review_due_on",
            }
        ),
        "second-additive P04-US01 authorization",
    )
    if (
        authorization["approval_source"] != "active Codex thread"
        or authorization["difference_scope"]
        != "exact default-off P04-US01 table span-fidelity implementation only"
        or authorization["exception_scope"] != original_waiver["exception_scope"]
        or authorization["exception_scope"] != hardened_renewal["exception_scope"]
        or authorization["failed_history"] != expected_history
        or authorization["failed_history"] != EXPECTED_FAILED_HISTORY
        or authorization["hosted_usage"] != original_waiver["hosted_usage"]
        or authorization["hosted_usage"] != hardened_renewal["hosted_usage"]
        or authorization["not_waived"] != list(EXPECTED_NOT_WAIVED)
        or authorization["not_waived"] != original_waiver["not_waived"]
        or authorization["not_waived"] != hardened_renewal["not_waived"]
        or authorization["operational_constraints"]
        != original_waiver["operational_constraints"]
        or authorization["operational_constraints"]
        != hardened_renewal["operational_constraints"]
        or original_waiver["primary_candidate"] != EXPECTED_PRIMARY_IDENTITY
        or hardened_renewal["expiry"] != EXPECTED_HARDENED_PHASE04_EXPIRY
        or authorization["review_due_on"] != "2026-09-02"
        or authorization["prior_guard_identity"]
        != {
            "path": (
                "tests/fixtures/phase_03/running_regions/performance_exception.py"
            ),
            "raw_sha256": (
                "d749ea7a0713dbd35d2323b54dda4b1652c1077d501601b04e9b30135230f2bd"
            ),
            "size_bytes": 389_880,
        }
        or authorization["prior_focused_guard_identity"]
        != {
            "path": "tests/performance/test_p03_us08_provisional_latency_exception.py",
            "raw_sha256": (
                "2e6713fde8d91d48e08e402ec0f6f9c0ee80f62496f72137692e60573134d100"
            ),
            "size_bytes": 202_100,
        }
    ):
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 authorization differs"
        )
    try:
        review_due = date.fromisoformat(authorization["review_due_on"])
    except (TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 authorization differs"
        ) from exc
    if (today or datetime.now(tz=UTC).date()) > review_due:
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 authorization expired"
        )

    _validate_second_additive_p04_us01_code_identity(
        pipeline_raw,
        EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_IDENTITY,
        path="app/services/pipeline.py",
    )
    _validate_second_additive_p04_us01_code_identity(
        table_semantics_raw,
        EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_IDENTITY,
        path="app/services/table_semantics.py",
    )
    try:
        pipeline_tree = ast.parse(pipeline_raw.decode("utf-8"))
        table_tree = ast.parse(table_semantics_raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover - identity
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 code identity differs"
        ) from exc
    if (
        _normalize_hardened_pipeline_table_repair(pipeline_tree)
        != "second_additive"
        or _validate_hardened_phase04_pipeline_surface(pipeline_raw)
        != "second_additive"
        or not EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_AST_SHA256
        or _second_additive_p04_us01_table_semantics_nodes(table_tree)
        != frozenset(
            EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_AST_SHA256
        )
    ):
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 production vector differs"
        )

    tracks: list[tuple[str, int, str, bytes, Any]] = []
    for field in ("prior_amendment_identity", "prior_amendment_approval_identity"):
        identity = _exact_keys(
            authorization[field],
            frozenset({"path", "raw_sha256", "size_bytes"}),
            "second-additive P04-US01 prior amendment identity",
        )
        raw, binding = _read_bound_file(
            root,
            identity["path"],
            maximum_bytes=DECISION_MAXIMUM_BYTES,
            label="second-additive P04-US01 prior amendment",
        )
        if (
            type(identity["size_bytes"]) is not int
            or len(raw) != identity["size_bytes"]
            or hashlib.sha256(raw).hexdigest() != identity["raw_sha256"]
        ):
            raise readiness.ReadinessContractError(
                "second-additive P04-US01 prior amendment differs"
            )
        tracks.append(
            (
                identity["path"],
                DECISION_MAXIMUM_BYTES,
                "second-additive P04-US01 prior amendment",
                raw,
                binding,
            )
        )
    return tracks


def _validate_hardened_phase04_renewal(
    root: Path,
    *,
    current_code: Mapping[str, Mapping[str, Any]],
    phase04_baseline_code: Mapping[str, Mapping[str, Any]],
    expected_history: Mapping[str, Any],
    phase04_renewal: Mapping[str, Any],
    original_waiver: Mapping[str, Any],
    today: date | None,
    ancestry_only: bool = False,
) -> tuple[
    dict[str, Any],
    bytes,
    tuple[
        tuple[int, int, int, int, int, int, int],
        tuple[tuple[int, int, int, int, int, int, int], ...],
    ],
    list[
        tuple[
            str,
            int,
            str,
            bytes,
            tuple[
                tuple[int, int, int, int, int, int, int],
                tuple[tuple[int, int, int, int, int, int, int], ...],
            ],
        ]
    ],
]:
    """Validate the reissued closed Phase 04 table-only custody boundary."""

    raw, binding = _read_bound_file(
        root,
        str(HARDENED_PHASE04_RENEWAL_WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label="hardened Phase 04 latency renewal waiver",
    )
    if (
        len(raw)
        != EXPECTED_HARDENED_PHASE04_RENEWAL_WAIVER_IDENTITY["size_bytes"]
        or hashlib.sha256(raw).hexdigest()
        != EXPECTED_HARDENED_PHASE04_RENEWAL_WAIVER_IDENTITY["raw_sha256"]
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal waiver differs"
        )
    renewal = _strict_json(raw, "hardened Phase 04 latency renewal waiver")
    if raw != _pretty_json_bytes(renewal):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal waiver bytes differ"
        )
    if (
        renewal.get("semantic_sha256")
        != EXPECTED_HARDENED_PHASE04_RENEWAL_WAIVER_IDENTITY["semantic_sha256"]
        or renewal.get("semantic_sha256") != waiver_semantic_sha256(renewal)
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal waiver digest differs"
        )
    _exact_keys(
        renewal,
        frozenset(
            {
                "approval",
                "authorized_change",
                "decision_identity",
                "deferred_work",
                "exception_scope",
                "expiry",
                "failed_audit_identity",
                "failed_history",
                "hosted_usage",
                "independent_review_02_identity",
                "not_waived",
                "operational_constraints",
                "prior_renewal_identity",
                "record_kind",
                "red_team_blocked_review_identity",
                "renewal_id",
                "renews_renewal_id",
                "schema_version",
                "semantic_sha256",
                "status",
                "story",
            }
        ),
        "hardened Phase 04 latency renewal waiver",
    )
    if {
        key: renewal[key]
        for key in (
            "schema_version",
            "record_kind",
            "story",
            "renewal_id",
            "renews_renewal_id",
            "status",
        )
    } != {
        "schema_version": "1.0",
        "record_kind": "p03_us08_hardened_phase04_tables_latency_exception_renewal",
        "story": "P03-US08",
        "renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-"
            "PHASE04-TABLES-HARDENED"
        ),
        "renews_renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES"
        ),
        "status": "accepted_with_time_bounded_metrics_exception_renewal",
    }:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal identity differs"
        )
    if renewal["approval"] != {
        "authorized_on": "2026-08-03",
        "owner": "project owner/requester",
        "source": "active Codex thread",
        "statement": EXPECTED_PHASE04_APPROVAL_STATEMENT,
    }:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal approval differs"
        )
    if (
        renewal["exception_scope"] != original_waiver["exception_scope"]
        or renewal["exception_scope"] != phase04_renewal["exception_scope"]
        or renewal["failed_history"] != expected_history
        or renewal["failed_history"] != EXPECTED_FAILED_HISTORY
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal observation differs"
        )
    for field in (
        "deferred_work",
        "hosted_usage",
        "not_waived",
        "operational_constraints",
    ):
        if renewal[field] != original_waiver[field]:
            raise readiness.ReadinessContractError(
                f"hardened Phase 04 latency renewal {field.replace('_', ' ')} differs"
            )
    if renewal["prior_renewal_identity"] != {
        "path": str(PHASE04_RENEWAL_WAIVER_PATH),
        **EXPECTED_PHASE04_RENEWAL_WAIVER_IDENTITY,
    }:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 prior renewal identity differs"
        )
    if renewal["failed_audit_identity"] != EXPECTED_FAILED_PHASE04_AUDIT_IDENTITY:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 failed audit identity differs"
        )
    if renewal["red_team_blocked_review_identity"] != (
        EXPECTED_HARDENED_PHASE04_RED_TEAM_IDENTITY
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 red-team review identity differs"
        )
    if renewal["independent_review_02_identity"] != (
        EXPECTED_HARDENED_PHASE04_REVIEW_02_IDENTITY
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 independent review 02 identity differs"
        )

    expiry = renewal["expiry"]
    expected_expiry = EXPECTED_HARDENED_PHASE04_EXPIRY
    try:
        review_due = date.fromisoformat(expiry["review_due_on"])
    except (KeyError, TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal expiry differs"
        ) from exc
    if expiry != expected_expiry or (today or datetime.now(tz=UTC).date()) > review_due:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal expired"
        )

    expected_authorized = _expected_hardened_phase04_authorized_change()
    if not ancestry_only and renewal["authorized_change"] != expected_authorized:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 authorized change differs"
        )
    if ancestry_only:
        decision = renewal["decision_identity"]
        if decision != EXPECTED_HARDENED_PHASE04_RENEWAL_DECISION_IDENTITY:
            raise readiness.ReadinessContractError(
                "hardened Phase 04 latency renewal decision identity differs"
            )
        decision_raw, decision_binding = _read_bound_file(
            root,
            decision["path"],
            maximum_bytes=DECISION_MAXIMUM_BYTES,
            label="hardened Phase 04 latency renewal decision",
        )
        if (
            len(decision_raw) != decision["size_bytes"]
            or hashlib.sha256(decision_raw).hexdigest() != decision["raw_sha256"]
            or renewal["renewal_id"].encode("utf-8") not in decision_raw
            or renewal["renews_renewal_id"].encode("utf-8") not in decision_raw
        ):
            raise readiness.ReadinessContractError(
                "hardened Phase 04 latency renewal decision differs"
            )
        return renewal, raw, binding, [
            (
                decision["path"],
                DECISION_MAXIMUM_BYTES,
                "hardened Phase 04 latency renewal decision",
                decision_raw,
                decision_binding,
            )
        ]
    if set(current_code) != set(phase04_baseline_code):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 required-code path set differs"
        )
    changed_paths = {
        path
        for path in current_code
        if current_code[path] != phase04_baseline_code[path]
    }
    if not changed_paths <= set(EXPECTED_HARDENED_EXISTING_PATHS):
        raise readiness.ReadinessContractError(
            "hardened running-region protected code changed"
        )

    tracks: list[
        tuple[
            str,
            int,
            str,
            bytes,
            tuple[
                tuple[int, int, int, int, int, int, int],
                tuple[tuple[int, int, int, int, int, int, int], ...],
            ],
        ]
    ] = []
    observed_raw: dict[str, bytes] = {}
    observed_paths = (
        *EXPECTED_HARDENED_EXISTING_PATHS,
        *EXPECTED_HARDENED_SEALED_PATHS,
        *EXPECTED_HARDENED_PHASE04_ADDED_PATHS,
    )
    for path in observed_paths:
        candidate = root.joinpath(*PurePosixPath(path).parts)
        if path in EXPECTED_HARDENED_PHASE04_ADDED_PATHS and not (
            candidate.exists() or candidate.is_symlink()
        ):
            if path == EXPECTED_HARDENED_PHASE04_READINESS_TEST_IDENTITY["path"]:
                raise readiness.ReadinessContractError(
                    "hardened Phase 04 readiness custody is absent"
                )
            continue
        code_raw, code_binding = _read_bound_file(
            root,
            path,
            maximum_bytes=2 * 1024 * 1024,
            label="hardened Phase 04 code",
        )
        observed_raw[path] = code_raw
        tracks.append(
            (path, 2 * 1024 * 1024, "hardened Phase 04 code", code_raw, code_binding)
        )

    _validate_hardened_phase04_env_example(observed_raw[".env.example"])
    _validate_hardened_metrics_contract_surface(
        observed_raw[
            "tests/performance/test_p03_us08_running_region_metrics_contract.py"
        ]
    )
    readiness_test = observed_raw[
        EXPECTED_HARDENED_PHASE04_READINESS_TEST_IDENTITY["path"]
    ]
    if (
        len(readiness_test)
        != EXPECTED_HARDENED_PHASE04_READINESS_TEST_IDENTITY["size_bytes"]
        or hashlib.sha256(readiness_test).hexdigest()
        != EXPECTED_HARDENED_PHASE04_READINESS_TEST_IDENTITY["sha256"]
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 readiness custody changed"
        )
    _validate_hardened_phase04_tables_surface(
        observed_raw["app/services/tables.py"]
    )
    if (
        _phase04_config_normalized_digest(observed_raw["app/config.py"])
        != EXPECTED_PHASE04_CONFIG_NORMALIZED_AST_SHA256
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 config surface changed"
        )
    _validate_hardened_phase04_pipeline_surface(
        observed_raw["app/services/pipeline.py"]
    )
    _hardened_source_alignment_digests(
        observed_raw["app/services/source_text_alignment.py"]
    )
    _hardened_text_reconciliation_digests(
        observed_raw["app/services/text_reconciliation.py"]
    )
    table_semantics_raw = observed_raw.get("app/services/table_semantics.py")
    if table_semantics_raw is not None:
        _validate_table_semantics_module(table_semantics_raw)
    helper_raw = observed_raw.get("frontend/lib/table-semantics.ts")
    _validate_hardened_phase04_frontend(
        observed_raw["frontend/app/clearleaf-workspace.tsx"],
        helper_raw=helper_raw,
    )
    runtime_changed_paths = changed_paths - {
        "tests/performance/test_p03_us08_running_region_metrics_contract.py"
    }
    baseline_changed = bool(runtime_changed_paths) or (
        EXPECTED_PHASE04_FRONTEND_IMPORT.encode("utf-8")
        in observed_raw["frontend/app/clearleaf-workspace.tsx"]
    )
    if baseline_changed and table_semantics_raw is None:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 table semantics dependency is absent"
        )
    if table_semantics_raw is None:  # pragma: no cover - dependency check above
        raise readiness.ReadinessContractError(
            "second-additive P04-US01 table semantics dependency is absent"
        )
    tracks.extend(
        _validate_second_additive_p04_us01_authorization(
            root,
            expected_history=expected_history,
            hardened_renewal=renewal,
            original_waiver=original_waiver,
            pipeline_raw=observed_raw["app/services/pipeline.py"],
            table_semantics_raw=table_semantics_raw,
            today=today,
        )
    )

    decision = renewal["decision_identity"]
    if decision != EXPECTED_HARDENED_PHASE04_RENEWAL_DECISION_IDENTITY:
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal decision identity differs"
        )
    decision_raw, decision_binding = _read_bound_file(
        root,
        decision["path"],
        maximum_bytes=DECISION_MAXIMUM_BYTES,
        label="hardened Phase 04 latency renewal decision",
    )
    if (
        len(decision_raw) != decision["size_bytes"]
        or hashlib.sha256(decision_raw).hexdigest() != decision["raw_sha256"]
        or renewal["renewal_id"].encode("utf-8") not in decision_raw
        or renewal["renews_renewal_id"].encode("utf-8") not in decision_raw
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal decision differs"
        )
    tracks.append(
        (
            decision["path"],
            DECISION_MAXIMUM_BYTES,
            "hardened Phase 04 latency renewal decision",
            decision_raw,
            decision_binding,
        )
    )
    audit = renewal["failed_audit_identity"]
    audit_raw, audit_binding = _read_bound_file(
        root,
        audit["path"],
        maximum_bytes=DECISION_MAXIMUM_BYTES,
        label="failed Phase 04 renewal audit",
    )
    if (
        len(audit_raw) != audit["size_bytes"]
        or hashlib.sha256(audit_raw).hexdigest() != audit["raw_sha256"]
        or b"Blocked" not in audit_raw
    ):
        raise readiness.ReadinessContractError(
            "failed Phase 04 renewal audit differs"
        )
    tracks.append(
        (
            audit["path"],
            DECISION_MAXIMUM_BYTES,
            "failed Phase 04 renewal audit",
            audit_raw,
            audit_binding,
        )
    )
    red_team = renewal["red_team_blocked_review_identity"]
    red_team_raw, red_team_binding = _read_bound_file(
        root,
        red_team["path"],
        maximum_bytes=DECISION_MAXIMUM_BYTES,
        label="blocked hardened Phase 04 red-team review",
    )
    if (
        len(red_team_raw) != red_team["size_bytes"]
        or hashlib.sha256(red_team_raw).hexdigest() != red_team["raw_sha256"]
        or b"BLOCKED" not in red_team_raw
        or b"FE-12" not in red_team_raw
        or b"TS-06" not in red_team_raw
    ):
        raise readiness.ReadinessContractError(
            "blocked hardened Phase 04 red-team review differs"
        )
    tracks.append(
        (
            red_team["path"],
            DECISION_MAXIMUM_BYTES,
            "blocked hardened Phase 04 red-team review",
            red_team_raw,
            red_team_binding,
        )
    )
    review_02 = renewal["independent_review_02_identity"]
    review_02_raw, review_02_binding = _read_bound_file(
        root,
        review_02["path"],
        maximum_bytes=DECISION_MAXIMUM_BYTES,
        label="blocked hardened Phase 04 independent review 02",
    )
    if (
        len(review_02_raw) != review_02["size_bytes"]
        or hashlib.sha256(review_02_raw).hexdigest()
        != review_02["raw_sha256"]
        or b"BLOCKED" not in review_02_raw
        or b"nine-function" not in review_02_raw
        or b"CommonJS" not in review_02_raw
    ):
        raise readiness.ReadinessContractError(
            "blocked hardened Phase 04 independent review 02 differs"
        )
    tracks.append(
        (
            review_02["path"],
            DECISION_MAXIMUM_BYTES,
            "blocked hardened Phase 04 independent review 02",
            review_02_raw,
            review_02_binding,
        )
    )
    return renewal, raw, binding, tracks


_SEMANTIC_ISOLATION_TABLE_FLAGS = frozenset(
    {
        "table_span_fidelity_enabled",
        "table_evidence_reconciliation_enabled",
        "table_candidate_gate_enabled",
        "table_multi_page_merge_enabled",
    }
)
_SEMANTIC_ISOLATION_SAFE_IMPORT_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "copy",
        "csv",
        "dataclasses",
        "hashlib",
        "html",
        "io",
        "json",
        "math",
        "pdfplumber",
        "re",
        "statistics",
        "struct",
        "time",
        "typing",
    }
)
_SEMANTIC_ISOLATION_FORBIDDEN_CALLS = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "input",
        "open",
    }
)
_SEMANTIC_ISOLATION_FORBIDDEN_ROOTS = frozenset(
    {
        "aiohttp",
        "builtins",
        "ctypes",
        "ftplib",
        "glob",
        "http",
        "httpx",
        "importlib",
        "os",
        "pathlib",
        "requests",
        "shutil",
        "socket",
        "ssl",
        "subprocess",
        "sys",
        "tempfile",
        "urllib",
    }
)
_SEMANTIC_ISOLATION_TABLE_PUBLIC_ROOTS = frozenset(
    {
        "detach_table_overlays_for_phase03",
        "finalize_table_pages",
        "gate_table_candidates",
        "merge_continued_tables",
        "prepare_docling_table",
        "prepare_docling_table_input",
        "prepare_docling_table_inputs",
        "prepare_vector_table",
        "rebind_table_overlays_after_phase03",
        "reconcile_table_candidates",
        "replace_marked_table_text",
        "replay_table_semantics",
        "seal_table_pages",
        "table_span_fidelity_document_deadline",
        "table_span_fidelity_page_deadline",
        "validate_table_semantics",
    }
)
_SEMANTIC_ISOLATION_OPAQUE_PUBLIC_ROOTS = frozenset(
    {
        "capture_opaque_group_edges",
        "detach_opaque_group_edges",
        "empty_group_content_sha256",
        "has_literal_table_marker",
        "member_content_sha256",
        "record_id",
        "records_sha256",
        "restore_diagnostic_group_edges",
        "seal_diagnostic_custody",
        "stable_id",
    }
)
_SEMANTIC_ISOLATION_TABLES_PUBLIC_ROOTS = frozenset({"extract_vector_tables"})
_SEMANTIC_ISOLATION_PUBLIC_CLASSES = {
    "app/services/table_semantics.py": frozenset(),
    "app/services/opaque_group_custody.py": frozenset(
        {
            "DetachedOpaqueGroupEdges",
            "FrozenRawAssertion",
            "FrozenRawDefinition",
            "FrozenRelevantRawClosure",
            "OpaqueGroupCustodyIntegrityError",
            "OpaqueGroupCustodyResourceError",
            "OpaqueGroupCustodyTimeoutError",
        }
    ),
    "app/services/tables.py": frozenset({"RawTable"}),
}
_SEMANTIC_ISOLATION_PUBLIC_CONSTANTS = {
    "app/services/table_semantics.py": frozenset(),
    "app/services/opaque_group_custody.py": frozenset(
        {
            "AUTHORITY",
            "MAX_CONTENT_DOCUMENT_BYTES",
            "MAX_CONTENT_ITEM_BYTES",
            "MAX_RAW_DEFINITIONS_SCANNED",
            "MAX_RECORDS",
            "POLICY_ID",
            "ROOT_SINGLETON_POLICY",
            "SCHEMA_VERSION",
        }
    ),
    "app/services/tables.py": frozenset(),
}
_SEMANTIC_ISOLATION_EXISTING_PUBLIC_APP_IMPORTS = {
    "app/services/table_semantics.py": frozenset(
        {("app.services.tables", "RawTable", None)}
    ),
    "app/services/opaque_group_custody.py": frozenset(),
    "app/services/tables.py": frozenset(),
}
_SEMANTIC_ISOLATION_ALLOWED_APP_IMPORTS = {
    "app/services/table_semantics.py": frozenset(
        {
            (
                "app.services.pipeline",
                "_build_docling_table_predecessor",
                None,
            ),
            ("app.services.tables", "RawTable", None),
        }
    ),
    "app/services/opaque_group_custody.py": frozenset(
        {
            ("app.models", "CanonicalSourceCustody", None),
            ("app.services.ir", "DocumentIR", None),
            ("app.services.ir", "ElementRecord", None),
            ("app.services.ir", "RelationshipRecord", None),
        }
    ),
    "app/services/tables.py": frozenset(),
}
_SEMANTIC_ISOLATION_DEDICATED_EXACT_NON_APP_IMPORTS = {
    "app/services/table_semantics.py": frozenset(),
    "app/services/opaque_group_custody.py": frozenset(
        {("array", "array", None)}
    ),
    "app/services/tables.py": frozenset(),
}
_SEMANTIC_ISOLATION_DEDICATED_GETATTR_FIELDS = {
    "app/services/table_semantics.py": frozenset(),
    "app/services/opaque_group_custody.py": frozenset(),
    "app/services/tables.py": frozenset({"bbox", "cells", "rows"}),
}
_SEMANTIC_ISOLATION_DANGEROUS_DUNDER_FUNCTIONS = frozenset(
    {
        "__dir__",
        "__getattr__",
        "__getattribute__",
        "__reduce__",
        "__reduce_ex__",
        "__setattr__",
    }
)
_SEMANTIC_ISOLATION_SHARED_SAFE_IMPORT_ROOTS = frozenset(
    {"app", "docling", "pdfplumber"}
)
_SEMANTIC_ISOLATION_SHARED_SAFE_METHOD_CALLS = {
    "app/models.py": frozenset(
        {
            "_validate_table_evidence_custody_impl",
            "__getitem__",
            "add",
            "append",
            "bit_length",
            "capitalize",
            "casefold",
            "dumps",
            "encode",
            "extend",
            "fullmatch",
            "generate_inner",
            "get",
            "hexdigest",
            "insert",
            "intersection",
            "isfinite",
            "issubset",
            "items",
            "join",
            "keys",
            "model_copy",
            "model_dump",
            "model_validate",
            "pop",
            "remove",
            "rstrip",
            "setdefault",
            "sha256",
            "sort",
            "split",
            "startswith",
            "strip",
            "sub",
            "update",
            "values",
        }
    ),
    "app/services/ir.py": frozenset(
        {"append", "casefold", "get", "model_validate", "startswith"}
    ),
    "app/services/pipeline.py": frozenset(
        {
            "BytesIO",
            "StringIO",
            "add",
            "append",
            "casefold",
            "count",
            "encode",
            "escape",
            "extend",
            "extract_words",
            "get",
            "getvalue",
            "hexdigest",
            "intersection",
            "isfinite",
            "items",
            "iterencode",
            "join",
            "match",
            "model_copy",
            "model_dump",
            "model_validate",
            "open",
            "perf_counter",
            "pop",
            "replace",
            "rstrip",
            "setdefault",
            "sha256",
            "split",
            "splitlines",
            "startswith",
            "strip",
            "table_span_fidelity_page_deadline",
            "update",
            "values",
            "writer",
            "writerows",
        }
    ),
    "app/services/presentation.py": frozenset(
        {
            "add",
            "append",
            "casefold",
            "get",
            "is_integer",
            "join",
            "replace",
            "setdefault",
            "startswith",
            "values",
        }
    ),
    "app/services/source_text_alignment.py": frozenset(
        {
            "StringIO",
            "add",
            "append",
            "deepcopy",
            "escape",
            "extend",
            "get",
            "getvalue",
            "items",
            "join",
            "replace",
            "rstrip",
            "search",
            "startswith",
            "to_dict",
            "values",
            "writer",
            "writerows",
        }
    ),
    "app/services/text_reconciliation.py": frozenset({"get"}),
    "synthetic.py": frozenset(
        {
            "BytesIO",
            "StringIO",
            "add",
            "append",
            "casefold",
            "encode",
            "extend",
            "get",
            "items",
            "join",
            "model_dump",
            "model_validate",
            "open",
            "pop",
            "replace",
            "rstrip",
            "split",
            "startswith",
            "strip",
            "update",
            "values",
        }
    ),
}
_SEMANTIC_ISOLATION_SHARED_MODULE_CALLS = {
    "app/models.py": frozenset(
        {
            ("CanonicalPresentation", "app", "model_validate"),
            ("PublicFormGroup", "app", "model_validate"),
            ("PublicOutlineContinuation", "app", "model_validate"),
            ("PublicOutlineGroup", "app", "model_validate"),
            ("PublicOutlineItem", "app", "model_validate"),
            ("hashlib", "hashlib", "sha256"),
            ("json", "json", "dumps"),
            ("math", "math", "isfinite"),
            ("re", "re", "fullmatch"),
            ("re", "re", "sub"),
        }
    ),
    "app/services/ir.py": frozenset(
        {("RunningRegionDescriptor", "app", "model_validate")}
    ),
    "app/services/pipeline.py": frozenset(
        {
            ("CanonicalSourceCustody", "app", "model_validate"),
            ("DocumentIR", "app", "model_validate"),
            ("ParseResult", "app", "model_validate"),
            ("csv", "csv", "writer"),
            ("hashlib", "hashlib", "sha256"),
            ("html", "html", "escape"),
            ("io", "io", "BytesIO"),
            ("io", "io", "StringIO"),
            ("json", "json", "JSONEncoder"),
            ("math", "math", "isfinite"),
            ("pdfplumber", "pdfplumber", "open"),
            ("table_semantics", "app", "perf_counter"),
            (
                "table_semantics",
                "app",
                "table_span_fidelity_page_deadline",
            ),
            ("time", "time", "perf_counter"),
        }
    ),
    "app/services/presentation.py": frozenset(),
    "app/services/source_text_alignment.py": frozenset(
        {
            ("copy", "copy", "deepcopy"),
            ("csv", "csv", "writer"),
            ("html", "html", "escape"),
            ("io", "io", "StringIO"),
            ("re", "re", "search"),
        }
    ),
    "app/services/text_reconciliation.py": frozenset(),
    "synthetic.py": frozenset(
        {
            ("io", "io", "BytesIO"),
            ("io", "io", "StringIO"),
            ("pdfplumber", "pdfplumber", "open"),
            ("time", "time", "perf_counter"),
        }
    ),
}
_SEMANTIC_ISOLATION_SHARED_DIRECT_IMPORTED_CALLS = {
    "app/models.py": frozenset(
        {
            ("Field", "pydantic"),
            ("_external_caption_geometry", "app"),
            ("_grounded_primary_ocr", "app"),
            ("_render_outline", "app"),
            ("_table_output_from_selected_children", "app"),
            ("build_canonical_presentation", "app"),
            ("build_document_ir", "app"),
            ("empty_group_content_sha256", "app"),
            ("field_validator", "pydantic"),
            ("member_content_sha256", "app"),
            ("model_serializer", "pydantic"),
            ("model_validator", "pydantic"),
            ("render_form_group_semantics", "app"),
            ("stable_form_id", "app"),
            ("stable_id", "app"),
            ("validate_public_outline_anchor", "app"),
            ("validate_table_semantics", "app"),
        }
    ),
    "app/services/ir.py": frozenset(
        {
            ("deepcopy", "copy"),
            ("detach_opaque_group_edges", "app"),
            ("has_literal_table_marker", "app"),
            ("restore_diagnostic_group_edges", "app"),
        }
    ),
    "app/services/pipeline.py": frozenset(
        {
            ("OpaqueGroupCustodyIntegrityError", "app"),
            ("OpaqueGroupCustodyResourceError", "app"),
            ("OpaqueGroupCustodyTimeoutError", "app"),
            ("_canonical_document_views", "app"),
            ("_canonical_views_from_blocks", "app"),
            ("_restore_all_table_predecessors", "app"),
            ("_trusted_table_validation_context", "app"),
            ("build_canonical_presentation", "app"),
            ("build_document_ir", "app"),
            ("capture_opaque_group_edges", "app"),
            ("deepcopy", "copy"),
            ("defaultdict", "collections"),
            ("detach_table_overlays_for_phase03", "app"),
            ("finalize_table_pages", "app"),
            ("has_literal_table_marker", "app"),
            ("prepare_docling_table", "app"),
            ("prepare_docling_table_input", "app"),
            ("prepare_docling_table_inputs", "app"),
            ("prepare_vector_table", "app"),
            ("rebind_table_overlays_after_phase03", "app"),
            ("reconcile_table_candidates", "app"),
            ("round_trip_document", "app"),
            ("seal_diagnostic_custody", "app"),
            ("seal_table_pages", "app"),
            ("table_span_fidelity_document_deadline", "app"),
            ("table_span_fidelity_page_deadline", "app"),
        }
    ),
    "app/services/presentation.py": frozenset({("escape", "html")}),
    "app/services/source_text_alignment.py": frozenset(
        {("replay_table_semantics", "app")}
    ),
    "app/services/text_reconciliation.py": frozenset(
        {("replace_marked_table_text", "app")}
    ),
    "synthetic.py": frozenset(),
}
_SEMANTIC_ISOLATION_SHARED_EXACT_METHOD_CALL_DIGESTS = {
    "app/models.py": frozenset(
        {"beae14b424c9eb7299c2af8ba92c7be368ea78923e9655941b9211ca3c79a980"}
    ),
    "app/services/pipeline.py": frozenset(
        {"d41a6f1c05cdd38af7d58363706eeb523f01c59ceace2689a9c2e4764140ab10"}
    ),
}
_SEMANTIC_ISOLATION_SHARED_EXACT_DIRECT_IMPORTED_CALL_DIGESTS = {
    "app/models.py": frozenset(
        {
            "fc5ea89f39da7d0207d3ed8da9073c3d4b888408083029a22819465f52dac467",
        }
    ),
    "app/services/pipeline.py": frozenset(
        {
            "20b00b2591cfefa4502ae3272e3b5095240dfc88769eabc57f6b41a3b64c28bc",
            "5a243337a7a1b10fcd1e063b2a027f54c257b2a9ce72ddf19480e646457bf0b6",
            "ed50f90768b1987c5ef6dc1d61345fa63ebcbc1d169e7953267086c4e53a9fc3",
        }
    ),
}
_SEMANTIC_ISOLATION_SHARED_ALLOWED_WHILE_DIGESTS = {
    "app/services/pipeline.py": frozenset(
        {"ebc5a036d781a6590b190454d46dd83fe7fdfd479225701ce08c56d9c2c90c73"}
    ),
}
_SEMANTIC_ISOLATION_SHARED_ALLOWED_DUNDER_ATTRIBUTES = {
    "app/models.py": frozenset(
        {
            "TableCell.__pydantic_core_schema__",
            "dict.__getitem__",
            "predecessor_primary_rank.__getitem__",
        }
    ),
    "app/services/pipeline.py": frozenset(
        {"type(exc).__name__", "type(predecessor_failure).__name__"}
    ),
}
_SEMANTIC_ISOLATION_RUNTIME_SUFFIXES = frozenset(
    {".cjs", ".css", ".js", ".jsx", ".mjs", ".py", ".ts", ".tsx"}
)
_SEMANTIC_ISOLATION_RUNTIME_ROOTS = (
    "app",
    "frontend/app",
    "frontend/build",
    "frontend/lib",
    "frontend/public",
    "frontend/worker",
)
_SEMANTIC_ISOLATION_RUNTIME_ENTRY_LIMIT = 2_048
_SEMANTIC_ISOLATION_NONPRODUCTION_ROOTS = frozenset(
    {
        ".models",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "analysis",
        "benchmark-expertmodeldata",
        "document_parse_api.egg-info",
        "tests",
        "tmp",
        "tracker",
    }
)
_SEMANTIC_ISOLATION_FRONTEND_NONPRODUCTION_ROOTS = frozenset(
    {
        ".git",
        ".openai",
        ".vinext",
        ".wrangler",
        "dist",
        "examples",
        "node_modules",
        "tests",
    }
)
_SEMANTIC_ISOLATION_PHASE05_BOUNDARY_ROOT = (
    "tracker/phase-05-charts-diagrams"
)
_SEMANTIC_ISOLATION_PHASE05_BOUNDARY_PATHS = frozenset(
    {
        "tracker/phase-05-charts-diagrams/README.md",
        "tracker/phase-05-charts-diagrams/backlog.md",
        "tracker/phase-05-charts-diagrams/metrics.md",
        "tracker/phase-05-charts-diagrams/phase-regression.md",
        *(
            f"tracker/phase-05-charts-diagrams/stories/P05-US{index:02d}.md"
            for index in range(1, 11)
        ),
    }
)
_SEMANTIC_ISOLATION_PHASE05_BOUNDARY_ENTRY_LIMIT = 64
_SEMANTIC_ISOLATION_EXACT_RUNNING_REGION_PATHS = frozenset(
    {
        "app/services/running_regions.py",
        "frontend/lib/running-regions.ts",
        "frontend/tests/p03-us08-running-regions.test.mts",
        "tests/benchmarks/running_region_metrics.py",
        "tests/fixtures/phase_03/running_regions/contract.py",
        "tests/fixtures/phase_03/running_regions/oracle.py",
        "tests/performance/test_p03_us08_running_region_metrics_contract.py",
    }
)
_SEMANTIC_ISOLATION_FORBIDDEN_CAPABILITIES = (
    "running-region import, call, alias, flag, or mutation",
    "Phase 05 reference",
    "dynamic import, eval, exec, or compilation",
    "filesystem, network, browser storage, or subprocess access",
    "new dependency or production path",
    "default-on or forced-on table execution",
    "unbounded output, resource growth, or deadline reset",
    "canonical authority for diagnostic-only opaque custody",
)

# The protected running-region projection stays frozen at the renewal's
# original digest.  The separately reviewed exact Optimization C projections
# are one-way-normalized to that predecessor; any other digest is returned
# unchanged and therefore fails custody.
_SEMANTIC_ISOLATION_PROTECTED_PIPELINE_PROJECTION_SHA256 = (
    "31e3284e822a736a514ce008e4c1764c9a5dabc70cf71795ebec90fc4b8abd62"
)
_SEMANTIC_ISOLATION_FINAL_US01_TABLE_PROJECTION_SHA256 = (
    "6b07a35782d59988f1b3516e19b8085aae1e74997ba5cb73de2a459a098eecbc"
)
_SEMANTIC_ISOLATION_PROTECTED_MODELS_PROJECTION_SHA256 = (
    "1976ba6f20ea6be8c8a7179a8500e442f5e62f31f8a3516ab429fa220f8275a5"
)
_SEMANTIC_ISOLATION_FINAL_US01_MODELS_PROJECTION_SHA256 = (
    "8b2163ca9e758c7690bc442ed85b578bb2fbccfb6acff72232caec1052f1ff1d"
)
_SEMANTIC_ISOLATION_FINAL_US01_MODELS_IDENTITY = {
    "ast_sha256": (
        "2d66bed0e4481fa8319bb9c917993081556fe5d4a92e3701517493c375f0e622"
    ),
    "path": "app/models.py",
    "raw_sha256": (
        "0dd48d41018de2e225ff10bf5c1f926685ada4032368d8d76e33d4482a8f0493"
    ),
    "size_bytes": 354_120,
}
_SEMANTIC_ISOLATION_FINAL_US01_MODELS_VALIDATOR_VECTOR = {
    "call_ast_sha256": (
        "a04960e4bc2b20abaa15a0ba41379bd29bc2bb98bd30774a69541101fa404404"
    ),
    "call_count": 2,
    "call_sites": [
        {
            "enclosing_class": "ParseResult",
            "enclosing_functions": ["_validate_table_evidence_custody_impl"],
            "parent_ast_sha256": (
                "d5d7705f04a00dda4daeecedc7858e482d8da18eb9f2db4bc141436b23e33281"
            ),
            "predicate_ast_sha256": (
                "11c345f912e62315ca6b40b8ee082b6ee0fd689605fc83915c7928cf847c31fe"
            ),
        },
        {
            "enclosing_class": "ParseResult",
            "enclosing_functions": [
                "inert_raw_group_remnant_record",
                "_validate_table_evidence_custody_impl",
            ],
            "parent_ast_sha256": (
                "d5d7705f04a00dda4daeecedc7858e482d8da18eb9f2db4bc141436b23e33281"
            ),
            "predicate_ast_sha256": (
                "126ab6c9add8fa2c5f7a1761414b8d2d7b598e2e983f17a5dc81cd96f15584e9"
            ),
        },
    ],
    "helper_ast_sha256": (
        "793cad12b5fdf027856c00d3bd2b489e976b139be9145779d5313b8cd187a2fa"
    ),
    "helper_name": "_context_free_inert_raw_group_owner_is_closed",
    "helper_reference_load_count": 2,
}
_SEMANTIC_ISOLATION_FINAL_US01_MODELS_DELTA = {
    "candidate_identity": dict(_SEMANTIC_ISOLATION_FINAL_US01_MODELS_IDENTITY),
    "candidate_projection_sha256": (
        _SEMANTIC_ISOLATION_FINAL_US01_MODELS_PROJECTION_SHA256
    ),
    "normalization_direction": "exact_candidate_to_unchanged_protected_only",
    "protected_projection_sha256": (
        _SEMANTIC_ISOLATION_PROTECTED_MODELS_PROJECTION_SHA256
    ),
    "validator_vector": _SEMANTIC_ISOLATION_FINAL_US01_MODELS_VALIDATOR_VECTOR,
}


def _semantic_isolation_atom(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _semantic_isolation_is_table_atom(value: str) -> bool:
    atom = _semantic_isolation_atom(value)
    pieces = tuple(piece for piece in atom.split("_") if piece)
    return bool(
        atom.startswith(("table", "p04_"))
        or "table" in pieces
        or "p04" in pieces
        or "opaque_group" in atom
        or "canonical_source_custody" in atom
    )


def _semantic_isolation_is_running_atom(value: str) -> bool:
    atom = _semantic_isolation_atom(value)
    return bool(
        "running_region" in atom
        or "runningregion" in atom
        or "page_identity" in atom
        or "pageidentity" in atom
        or "p03_running_regions_page_identity" in atom
    )


def _semantic_isolation_is_running_region_atom(value: str) -> bool:
    atom = _semantic_isolation_atom(value)
    return bool(
        "running_region" in atom
        or "runningregion" in atom
        or "p03_running_regions_page_identity" in atom
    )


def _semantic_isolation_is_phase05_atom(value: str) -> bool:
    atom = _semantic_isolation_atom(value)
    return bool(re.search(r"(?:^|_)(?:phase|p)_?0?5(?:_|$)", atom))


def _semantic_isolation_is_page_identity_atom(value: str) -> bool:
    atom = _semantic_isolation_atom(value)
    return bool("page_identity" in atom or "pageidentity" in atom)


def _semantic_isolation_static_string(
    node: ast.AST,
    *,
    depth: int = 0,
) -> tuple[str, int] | None:
    if depth > 8:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if len(node.value.encode("utf-8")) > 1_024:
            return None
        return node.value, 1
    if (
        isinstance(node, ast.FormattedValue)
        and node.conversion == -1
        and node.format_spec is None
    ):
        return _semantic_isolation_static_string(node.value, depth=depth + 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _semantic_isolation_static_string(node.left, depth=depth + 1)
        right = _semantic_isolation_static_string(node.right, depth=depth + 1)
        if left is None or right is None or left[1] + right[1] > 16:
            return None
        value = left[0] + right[0]
        if len(value.encode("utf-8")) > 1_024:
            return None
        return value, left[1] + right[1]
    if isinstance(node, ast.JoinedStr):
        values = [
            _semantic_isolation_static_string(value, depth=depth + 1)
            for value in node.values
        ]
        if not values or any(value is None for value in values):
            return None
        concrete = [value for value in values if value is not None]
        if sum(value[1] for value in concrete) > 16:
            return None
        result = "".join(value[0] for value in concrete)
        if len(result.encode("utf-8")) > 1_024:
            return None
        return result, sum(value[1] for value in concrete)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and not node.keywords
        and len(node.args) == 1
        and isinstance(node.args[0], (ast.List, ast.Tuple))
    ):
        separator = _semantic_isolation_static_string(
            node.func.value,
            depth=depth + 1,
        )
        values = [
            _semantic_isolation_static_string(value, depth=depth + 1)
            for value in node.args[0].elts
        ]
        if (
            separator is None
            or not values
            or any(value is None for value in values)
        ):
            return None
        concrete = [value for value in values if value is not None]
        pieces = separator[1] + sum(value[1] for value in concrete)
        if pieces > 16:
            return None
        result = separator[0].join(value[0] for value in concrete)
        if len(result.encode("utf-8")) > 1_024:
            return None
        return result, pieces
    return None


def _semantic_isolation_reconstructs_protected_scope(node: ast.AST) -> bool:
    reconstructed = _semantic_isolation_static_string(node)
    if reconstructed is None or reconstructed[1] < 2:
        return False
    value = reconstructed[0]
    return bool(
        _semantic_isolation_is_running_region_atom(value)
        or _semantic_isolation_is_phase05_atom(value)
        or _semantic_isolation_is_page_identity_atom(value)
    )


def _semantic_isolation_node_has(
    node: ast.AST,
    predicate: Any,
) -> bool:
    for value in ast.walk(node):
        candidates: list[str] = []
        if isinstance(value, (ast.Name, ast.Attribute)):
            candidates.append(value.id if isinstance(value, ast.Name) else value.attr)
        elif isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            candidates.append(value.name)
        elif isinstance(value, (ast.Import, ast.ImportFrom)):
            if isinstance(value, ast.ImportFrom) and value.module:
                candidates.append(value.module)
            candidates.extend(alias.name for alias in value.names)
            candidates.extend(alias.asname or "" for alias in value.names)
        elif isinstance(value, ast.Constant) and isinstance(value.value, str):
            candidates.append(value.value)
        if any(candidate and predicate(candidate) for candidate in candidates):
            return True
    return False


def _semantic_isolation_nonempty_body(body: list[ast.stmt]) -> list[ast.stmt]:
    return body or [ast.Pass()]


class _SemanticIsolationTableStripper(ast.NodeTransformer):
    """Remove only table-owned syntax while rejecting mixed P03/P04 nodes."""

    @staticmethod
    def _mixed(node: ast.AST) -> bool:
        return _semantic_isolation_node_has(
            node, _semantic_isolation_is_table_atom
        ) and _semantic_isolation_node_has(
            node, _semantic_isolation_is_running_atom
        )

    @classmethod
    def _remove_table_node(cls, node: ast.AST) -> bool:
        if not _semantic_isolation_node_has(
            node, _semantic_isolation_is_table_atom
        ):
            return False
        if cls._mixed(node):
            # Existing fail-closed bridge nodes intentionally mention both
            # partitions. They stay in the protected projection byte-for-byte;
            # they are never treated as mutable table syntax.
            return False
        return True

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST | None:
        if _semantic_isolation_is_table_atom(node.name):
            if _semantic_isolation_node_has(
                node, _semantic_isolation_is_running_atom
            ):
                return node
            return None
        node.body = _semantic_isolation_nonempty_body(
            [
                value
                for statement in node.body
                if (value := self.visit(statement)) is not None
                and isinstance(value, ast.stmt)
            ]
        )
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST | None:
        if _semantic_isolation_is_table_atom(node.name):
            if _semantic_isolation_node_has(
                node, _semantic_isolation_is_running_atom
            ):
                return node
            return None
        node.body = _semantic_isolation_nonempty_body(
            [
                value
                for statement in node.body
                if (value := self.visit(statement)) is not None
                and isinstance(value, ast.stmt)
            ]
        )
        return node

    def visit_If(self, node: ast.If) -> ast.AST | None:
        if _semantic_isolation_node_has(node.test, _semantic_isolation_is_table_atom):
            if _semantic_isolation_node_has(
                node, _semantic_isolation_is_running_atom
            ):
                return node
            return None
        node.body = _semantic_isolation_nonempty_body(
            [
                value
                for statement in node.body
                if (value := self.visit(statement)) is not None
                and isinstance(value, ast.stmt)
            ]
        )
        node.orelse = [
            value
            for statement in node.orelse
            if (value := self.visit(statement)) is not None
            and isinstance(value, ast.stmt)
        ]
        return node

    def visit_For(self, node: ast.For) -> ast.AST | None:
        if self._remove_table_node(ast.Tuple(elts=[node.target, node.iter])):
            return None
        node.body = _semantic_isolation_nonempty_body(
            [
                value
                for statement in node.body
                if (value := self.visit(statement)) is not None
                and isinstance(value, ast.stmt)
            ]
        )
        node.orelse = [
            value
            for statement in node.orelse
            if (value := self.visit(statement)) is not None
            and isinstance(value, ast.stmt)
        ]
        return node

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> ast.AST | None:
        if self._remove_table_node(node.test):
            return None
        return self.generic_visit(node)

    def visit_With(self, node: ast.With) -> ast.AST | None:
        header = ast.Tuple(elts=[item.context_expr for item in node.items])
        if self._remove_table_node(header):
            return None
        return self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Try(self, node: ast.Try) -> ast.AST:
        node.body = _semantic_isolation_nonempty_body(
            [
                value
                for statement in node.body
                if (value := self.visit(statement)) is not None
                and isinstance(value, ast.stmt)
            ]
        )
        node.orelse = [
            value
            for statement in node.orelse
            if (value := self.visit(statement)) is not None
            and isinstance(value, ast.stmt)
        ]
        node.finalbody = [
            value
            for statement in node.finalbody
            if (value := self.visit(statement)) is not None
            and isinstance(value, ast.stmt)
        ]
        for handler in node.handlers:
            handler.body = _semantic_isolation_nonempty_body(
                [
                    value
                    for statement in handler.body
                    if (value := self.visit(statement)) is not None
                    and isinstance(value, ast.stmt)
                ]
            )
        return node

    visit_TryStar = visit_Try

    def visit_Match(self, node: ast.Match) -> ast.AST | None:
        if self._remove_table_node(node.subject):
            return None
        for case in node.cases:
            case.body = _semantic_isolation_nonempty_body(
                [
                    value
                    for statement in case.body
                    if (value := self.visit(statement)) is not None
                    and isinstance(value, ast.stmt)
                ]
            )
        return node

    def generic_visit(self, node: ast.AST) -> ast.AST | None:
        if isinstance(
            node,
            (
                ast.AnnAssign,
                ast.Assert,
                ast.Assign,
                ast.AugAssign,
                ast.Delete,
                ast.Expr,
                ast.Global,
                ast.Import,
                ast.ImportFrom,
                ast.Nonlocal,
                ast.Raise,
                ast.Return,
            ),
        ) and self._remove_table_node(node):
            return None
        return super().generic_visit(node)


def _semantic_isolation_models_validator_vector(
    raw: bytes,
    *,
    tree: ast.Module,
) -> dict[str, Any] | None:
    """Describe the retained validator vector in the exact reviewed candidate."""

    helper_name = _SEMANTIC_ISOLATION_FINAL_US01_MODELS_VALIDATOR_VECTOR[
        "helper_name"
    ]
    helpers = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == helper_name
    ]
    calls = sorted(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == helper_name
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    helper_loads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id == helper_name
    ]
    if len(helpers) != 1 or len(calls) != 2 or len(helper_loads) != 2:
        return None

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    call_sites: list[dict[str, Any]] = []
    for call in calls:
        cursor: ast.AST | None = call
        enclosing_class: str | None = None
        enclosing_functions: list[str] = []
        nearest_if: ast.If | None = None
        while cursor is not None and not isinstance(cursor, ast.Module):
            cursor = parents.get(cursor)
            if nearest_if is None and isinstance(cursor, ast.If):
                nearest_if = cursor
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                enclosing_functions.append(cursor.name)
            elif isinstance(cursor, ast.ClassDef) and enclosing_class is None:
                enclosing_class = cursor.name
        parent = parents.get(call)
        if nearest_if is None or parent is None or enclosing_class is None:
            return None
        call_sites.append(
            {
                "enclosing_class": enclosing_class,
                "enclosing_functions": enclosing_functions,
                "parent_ast_sha256": _ast_digest(parent),
                "predicate_ast_sha256": _ast_digest(nearest_if.test),
            }
        )

    return {
        "call_ast_sha256": _ast_digest(calls[0]),
        "call_count": len(calls),
        "call_sites": call_sites,
        "helper_ast_sha256": _ast_digest(helpers[0]),
        "helper_name": helper_name,
        "helper_reference_load_count": len(helper_loads),
    }


def _semantic_isolation_models_delta_matches(
    raw: bytes,
    *,
    tree: ast.Module,
    candidate_projection_sha256: str,
) -> bool:
    identity = {
        "ast_sha256": _ast_digest(tree),
        "path": "app/models.py",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    return _semantic_isolation_strict_equal(
        {
            "candidate_identity": identity,
            "candidate_projection_sha256": candidate_projection_sha256,
            "normalization_direction": (
                "exact_candidate_to_unchanged_protected_only"
            ),
            "protected_projection_sha256": (
                _SEMANTIC_ISOLATION_PROTECTED_MODELS_PROJECTION_SHA256
            ),
            "validator_vector": _semantic_isolation_models_validator_vector(
                raw,
                tree=tree,
            ),
        },
        _SEMANTIC_ISOLATION_FINAL_US01_MODELS_DELTA,
    )


def _semantic_isolation_python_projection(raw: bytes, *, path: str) -> str:
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise readiness.ReadinessContractError(
            f"semantic-isolation Python custody differs: {path}"
        ) from exc
    models_tree = (
        ast.parse(raw.decode("utf-8"))
        if path == "app/models.py"
        else None
    )
    transformed = _SemanticIsolationTableStripper().visit(tree)
    if not isinstance(transformed, ast.Module):  # pragma: no cover - structural
        raise readiness.ReadinessContractError(
            f"semantic-isolation Python projection differs: {path}"
        )
    ast.fix_missing_locations(transformed)
    observed = _ast_digest(transformed)
    if (
        path == "app/services/pipeline.py"
        and observed
        == _SEMANTIC_ISOLATION_FINAL_US01_TABLE_PROJECTION_SHA256
    ):
        return _SEMANTIC_ISOLATION_PROTECTED_PIPELINE_PROJECTION_SHA256
    if (
        path == "app/models.py"
        and observed == _SEMANTIC_ISOLATION_FINAL_US01_MODELS_PROJECTION_SHA256
        and _semantic_isolation_models_delta_matches(
            raw,
            tree=models_tree,
            candidate_projection_sha256=observed,
        )
    ):
        return _SEMANTIC_ISOLATION_PROTECTED_MODELS_PROJECTION_SHA256
    return observed


def _semantic_isolation_in_shared_table_partition(
    node: ast.AST,
    *,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    cursor: ast.AST | None = node
    while cursor is not None and not isinstance(cursor, ast.Module):
        if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _semantic_isolation_is_table_atom(cursor.name):
                return True
        elif isinstance(cursor, ast.If):
            if _semantic_isolation_node_has(
                cursor.test,
                _semantic_isolation_is_table_atom,
            ):
                return True
        elif isinstance(cursor, (ast.For, ast.AsyncFor)):
            if _semantic_isolation_node_has(
                ast.Tuple(elts=[cursor.target, cursor.iter]),
                _semantic_isolation_is_table_atom,
            ):
                return True
        elif isinstance(cursor, ast.While):
            if _semantic_isolation_node_has(
                cursor.test,
                _semantic_isolation_is_table_atom,
            ):
                return True
        elif isinstance(cursor, (ast.With, ast.AsyncWith)):
            if any(
                _semantic_isolation_node_has(
                    item.context_expr,
                    _semantic_isolation_is_table_atom,
                )
                for item in cursor.items
            ):
                return True
        elif isinstance(cursor, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = (
                cursor.targets
                if isinstance(cursor, ast.Assign)
                else [cursor.target]
            )
            if any(
                _semantic_isolation_node_has(
                    target,
                    _semantic_isolation_is_table_atom,
                )
                for target in targets
            ):
                return True
        elif isinstance(cursor, (ast.Import, ast.ImportFrom, ast.Call)):
            if _semantic_isolation_node_has(
                cursor,
                _semantic_isolation_is_table_atom,
            ):
                return True
        cursor = parents.get(cursor)
    return False


def _semantic_isolation_import_roots(tree: ast.AST) -> dict[str, str]:
    roots: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots[alias.asname or alias.name.split(".", 1)[0]] = (
                    alias.name.split(".", 1)[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".", 1)[0]
            for alias in node.names:
                roots[alias.asname or alias.name] = root
    return roots


def _semantic_isolation_has_positive_flag_guard(
    node: ast.AST,
    *,
    flag: str,
) -> bool:
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = node.id if isinstance(node, ast.Name) else node.attr
        return name == flag
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        return any(
            _semantic_isolation_has_positive_flag_guard(value, flag=flag)
            for value in node.values
        )
    if (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], (ast.Eq, ast.Is))
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value is True
    ):
        return _semantic_isolation_has_positive_flag_guard(
            node.left,
            flag=flag,
        )
    return False


def _semantic_isolation_flag_assignment_is_guarded(
    node: ast.Assign | ast.AnnAssign,
    *,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    if len(targets) != 1 or not isinstance(targets[0], ast.Subscript):
        return False
    key = _semantic_isolation_static_string(targets[0].slice)
    if key is None or key[1] != 1 or key[0] not in _SEMANTIC_ISOLATION_TABLE_FLAGS:
        return False
    cursor = parents.get(node)
    while cursor is not None:
        if isinstance(cursor, ast.If) and _semantic_isolation_has_positive_flag_guard(
            cursor.test,
            flag=key[0],
        ):
            return True
        if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            break
        cursor = parents.get(cursor)
    return False


def _semantic_isolation_shared_binding_reconstructs_scope(
    tree: ast.AST,
    *,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    owners = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _semantic_isolation_in_shared_table_partition(node, parents=parents)
    ]
    for owner in owners:
        if _SemanticIsolationTableStripper._mixed(owner):
            # Mixed P03/P04 owners are retained in the protected projection
            # byte-for-byte and are not part of the mutable table partition.
            continue
        bindings = _phase04_scope_static_bindings(owner)
        for node in ast.walk(owner):
            if not isinstance(
                node,
                (ast.BinOp, ast.Call, ast.JoinedStr, ast.Name, ast.Subscript),
            ):
                continue
            if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
                continue
            values = _phase04_scope_static_strings(node, bindings=bindings)
            if any(
                _semantic_isolation_is_running_region_atom(value)
                or _semantic_isolation_is_page_identity_atom(value)
                or _semantic_isolation_is_phase05_atom(value)
                for value in values
            ):
                return True
    return False


def _semantic_isolation_attribute_call_identity(
    node: ast.Attribute,
) -> tuple[str | None, str]:
    attributes: list[str] = []
    cursor: ast.AST = node
    while isinstance(cursor, ast.Attribute):
        attributes.append(cursor.attr)
        cursor = cursor.value
    return (
        cursor.id if isinstance(cursor, ast.Name) else None,
        ".".join(reversed(attributes)),
    )


def _semantic_isolation_shared_reflection_is_exact_table_custody(
    call: ast.AST | None,
    *,
    path: str,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    if (
        path != "app/services/pipeline.py"
        or not isinstance(call, ast.Call)
        or not isinstance(call.func, ast.Name)
        or call.keywords
    ):
        return False
    exact_getattr = (
        call.func.id == "getattr"
        and len(call.args) == 3
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id in {"element", "relationship"}
        and isinstance(call.args[1], ast.Constant)
        and call.args[1].value == "id"
        and isinstance(call.args[2], ast.Constant)
        and call.args[2].value is None
    )
    exact_hasattr = (
        call.func.id == "hasattr"
        and len(call.args) == 2
        and ast.unparse(call.args[0]) == "value[1]"
        and isinstance(call.args[1], ast.Constant)
        and call.args[1].value == "model_dump"
    )
    if not exact_getattr and not exact_hasattr:
        return False
    current: ast.AST | None = call
    while current is not None and not isinstance(
        current,
        (ast.FunctionDef, ast.AsyncFunctionDef),
    ):
        current = parents.get(current)
    return (
        isinstance(current, ast.FunctionDef)
        and current.name == "_terminal_table_custody_closure_identity"
    )


def _semantic_isolation_validate_shared_python_table_scope(
    raw: bytes,
    *,
    path: str,
) -> None:
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise readiness.ReadinessContractError(
            f"semantic-isolation shared Python custody differs: {path}"
        ) from exc
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    import_roots = _semantic_isolation_import_roots(tree)
    if _semantic_isolation_shared_binding_reconstructs_scope(
        tree,
        parents=parents,
    ):
        raise readiness.ReadinessContractError(
            f"semantic-isolation reconstructed scope differs: {path}"
        )
    safe_methods = _SEMANTIC_ISOLATION_SHARED_SAFE_METHOD_CALLS.get(path)
    safe_module_calls = _SEMANTIC_ISOLATION_SHARED_MODULE_CALLS.get(path)
    safe_direct_imported_calls = (
        _SEMANTIC_ISOLATION_SHARED_DIRECT_IMPORTED_CALLS.get(path)
    )
    if (
        safe_methods is None
        or safe_module_calls is None
        or safe_direct_imported_calls is None
    ):
        raise readiness.ReadinessContractError(
            f"semantic-isolation shared Python path differs: {path}"
        )

    for node in ast.walk(tree):
        if not _semantic_isolation_in_shared_table_partition(
            node,
            parents=parents,
        ):
            continue
        if _semantic_isolation_reconstructs_protected_scope(node):
            raise readiness.ReadinessContractError(
                f"semantic-isolation reconstructed scope differs: {path}"
            )
        if _semantic_isolation_node_has(
            node,
            _semantic_isolation_is_phase05_atom,
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation Phase 05 scope differs: {path}"
            )
        if isinstance(node, ast.Name) and node.id in {
            "__builtins__",
            "builtins",
            "delattr",
            "getattr",
            "globals",
            "hasattr",
            "locals",
            "setattr",
            "vars",
        } and not (
            node.id in {"getattr", "hasattr"}
            and _semantic_isolation_shared_reflection_is_exact_table_custody(
                parents.get(node),
                path=path,
                parents=parents,
            )
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation dynamic capability differs: {path}"
            )
        if (
            isinstance(node, ast.Attribute)
            and "__" in node.attr
            and ast.unparse(node)
            not in _SEMANTIC_ISOLATION_SHARED_ALLOWED_DUNDER_ATTRIBUTES.get(
                path,
                frozenset(),
            )
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation reflection capability differs: {path}"
            )
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in _SEMANTIC_ISOLATION_TABLE_FLAGS:
                if isinstance(node.ctx, ast.Store):
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation table flag flow differs: {path}"
                    )
                parent = parents.get(node)
                if (
                    isinstance(parent, ast.BoolOp)
                    and isinstance(parent.op, ast.Or)
                    and any(
                        isinstance(value, ast.Constant) and value.value is True
                        for value in parent.values
                    )
                ):
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation table flag flow differs: {path}"
                    )
        if isinstance(node, ast.While) and (
            isinstance(node.test, ast.Constant) and node.test.value is True
        ) and _ast_digest(node) not in (
            _SEMANTIC_ISOLATION_SHARED_ALLOWED_WHILE_DIGESTS.get(
                path,
                frozenset(),
            )
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation resource grammar differs: {path}"
            )
        if isinstance(node, ast.Name) and node.id in (
            _SEMANTIC_ISOLATION_FORBIDDEN_CALLS
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation dynamic capability differs: {path}"
            )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if node.module else [])
            )
            if any(
                module.split(".", 1)[0]
                not in _SEMANTIC_ISOLATION_SHARED_SAFE_IMPORT_ROOTS
                for module in modules
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation external capability differs: {path}"
                )
        if not isinstance(node, ast.Call):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else [node.target]
                )
                if (
                    isinstance(node.value, ast.Constant)
                    and node.value.value is True
                    and any(
                        _semantic_isolation_node_has(
                            target,
                            lambda value: value in _SEMANTIC_ISOLATION_TABLE_FLAGS,
                        )
                        for target in targets
                    )
                    and not _semantic_isolation_flag_assignment_is_guarded(
                        node,
                        parents=parents,
                    )
                ):
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation forced-on table flag differs: {path}"
                    )
            continue
        if isinstance(node.func, ast.Name):
            direct_import_root = import_roots.get(node.func.id)
            if (
                direct_import_root is not None
                and (node.func.id, direct_import_root)
                not in safe_direct_imported_calls
                and _ast_digest(node)
                not in _SEMANTIC_ISOLATION_SHARED_EXACT_DIRECT_IMPORTED_CALL_DIGESTS.get(
                    path,
                    frozenset(),
                )
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation external capability differs: {path}"
                )
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and not _semantic_isolation_shared_reflection_is_exact_table_custody(
                node,
                path=path,
                parents=parents,
            )
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation dynamic capability differs: {path}"
            )
        root: ast.AST = node.func
        while isinstance(root, ast.Attribute):
            root = root.value
        if (
            isinstance(root, ast.Name)
            and import_roots.get(root.id) in _SEMANTIC_ISOLATION_FORBIDDEN_ROOTS
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation external capability differs: {path}"
            )
        imported_root = import_roots.get(root.id) if isinstance(root, ast.Name) else None
        if isinstance(node.func, ast.Attribute):
            receiver, attribute_path = _semantic_isolation_attribute_call_identity(
                node.func
            )
            if (
                node.func.attr.startswith("__")
                and ast.unparse(node.func)
                not in _SEMANTIC_ISOLATION_SHARED_ALLOWED_DUNDER_ATTRIBUTES.get(
                    path,
                    frozenset(),
                )
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation reflection capability differs: {path}"
                )
            if imported_root is not None:
                identity = (receiver, imported_root, attribute_path)
                if identity not in safe_module_calls:
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation external capability differs: {path}"
                    )
            elif (
                node.func.attr not in safe_methods
                and _ast_digest(node)
                not in _SEMANTIC_ISOLATION_SHARED_EXACT_METHOD_CALL_DIGESTS.get(
                    path,
                    frozenset(),
                )
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation method capability differs: {path}"
                )
        if imported_root == "time":
            allowed = (
                isinstance(node.func, ast.Name)
                and node.func.id == "perf_counter"
            ) or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "perf_counter"
            )
            if not allowed:
                raise readiness.ReadinessContractError(
                    f"semantic-isolation external capability differs: {path}"
                )
        if imported_root == "io":
            allowed = (
                isinstance(node.func, ast.Name)
                and node.func.id in {"BytesIO", "StringIO"}
            ) or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"BytesIO", "StringIO"}
            )
            if not allowed:
                raise readiness.ReadinessContractError(
                    f"semantic-isolation external capability differs: {path}"
                )
        if imported_root == "pdfplumber":
            payload = node.args[0] if len(node.args) == 1 else None
            if (
                not isinstance(node.func, ast.Attribute)
                or node.func.attr != "open"
                or node.keywords
                or not isinstance(payload, ast.Call)
                or not isinstance(payload.func, ast.Attribute)
                or not isinstance(payload.func.value, ast.Name)
                or import_roots.get(payload.func.value.id) != "io"
                or payload.func.attr != "BytesIO"
                or len(payload.args) != 1
                or payload.keywords
                or not isinstance(payload.args[0], ast.Name)
                or payload.args[0].id != "pdf_bytes"
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation pdf input custody differs: {path}"
                )


def _semantic_isolation_static_int(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.BinOp):
        left = _semantic_isolation_static_int(node.left)
        right = _semantic_isolation_static_int(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Pow) and 0 <= right <= 16 and abs(left) <= 65_536:
            try:
                return left**right
            except (ArithmeticError, OverflowError):
                return None
    return None


def _semantic_isolation_flag_is_direct_guard_read(
    node: ast.Name | ast.Attribute,
    *,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    cursor: ast.AST = node
    parent = parents.get(cursor)
    while parent is not None:
        if isinstance(parent, ast.If) and parent.test is cursor:
            return True
        if (
            isinstance(parent, ast.UnaryOp)
            and isinstance(parent.op, ast.Not)
            and parent.operand is cursor
        ):
            cursor = parent
        elif (
            isinstance(parent, ast.BoolOp)
            and isinstance(parent.op, ast.And)
            and cursor in parent.values
        ):
            cursor = parent
        elif (
            isinstance(parent, ast.Compare)
            and parent.left is cursor
            and len(parent.ops) == 1
            and isinstance(parent.ops[0], (ast.Eq, ast.Is, ast.IsNot))
            and len(parent.comparators) == 1
            and isinstance(parent.comparators[0], ast.Constant)
            and type(parent.comparators[0].value) is bool
        ):
            cursor = parent
        else:
            return False
        parent = parents.get(cursor)
    return False


def _semantic_isolation_validate_tables_resource_graph(tree: ast.Module) -> None:
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    roots = {name for name in functions if not name.startswith("_")}
    if roots != {"extract_vector_tables"}:
        raise readiness.ReadinessContractError(
            "semantic-isolation vector table root differs"
        )
    graph = {
        name: {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in functions
        }
        for name, function in functions.items()
    }
    reachable: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(graph[name] - reachable)
    if reachable != set(functions):
        raise readiness.ReadinessContractError(
            "semantic-isolation vector table helper reachability differs"
        )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise readiness.ReadinessContractError(
                "semantic-isolation vector table call graph differs"
            )
        if name in visited:
            return
        visiting.add(name)
        for target in graph[name]:
            visit(target)
        visiting.remove(name)
        visited.add(name)

    for root in roots:
        visit(root)
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            test = node.test
            if (
                not isinstance(test, ast.BoolOp)
                or not isinstance(test.op, ast.And)
                or not test.values
                or not isinstance(test.values[0], ast.Compare)
                or len(test.values[0].ops) != 1
                or not isinstance(test.values[0].ops[0], (ast.Lt, ast.Gt))
                or not isinstance(test.values[0].left, ast.Name)
                or len(test.values[0].comparators) != 1
                or not isinstance(test.values[0].comparators[0], ast.Name)
                or len(node.body) != 1
                or not isinstance(node.body[0], ast.AugAssign)
                or not isinstance(node.body[0].target, ast.Name)
                or not isinstance(node.body[0].value, ast.Constant)
                or node.body[0].value.value != 1
                or node.body[0].target.id != test.values[0].left.id
                or (
                    isinstance(test.values[0].ops[0], ast.Lt)
                    and not isinstance(node.body[0].op, ast.Add)
                )
                or (
                    isinstance(test.values[0].ops[0], ast.Gt)
                    and not isinstance(node.body[0].op, ast.Sub)
                )
                or node.orelse
            ):
                raise readiness.ReadinessContractError(
                    "semantic-isolation vector table resource grammar differs"
                )
        if isinstance(
            node,
            (
                ast.AsyncFor,
                ast.AsyncFunctionDef,
                ast.AsyncWith,
                ast.Await,
                ast.Yield,
                ast.YieldFrom,
            ),
        ):
            raise readiness.ReadinessContractError(
                "semantic-isolation vector table resource grammar differs"
            )
        name = (
            node.id
            if isinstance(node, ast.Name)
            else node.attr
            if isinstance(node, ast.Attribute)
            else node.arg
            if isinstance(node, ast.arg)
            else ""
        )
        if "deadline" in name.casefold() or "perf_counter" in name.casefold():
            raise readiness.ReadinessContractError(
                "semantic-isolation vector table deadline flow differs"
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            collection: ast.AST | None = None
            count: ast.AST | None = None
            if isinstance(
                node.left,
                (ast.Constant, ast.List, ast.Set, ast.Tuple),
            ):
                collection, count = node.left, node.right
            elif isinstance(
                node.right,
                (ast.Constant, ast.List, ast.Set, ast.Tuple),
            ):
                collection, count = node.right, node.left
            static_count = (
                _semantic_isolation_static_int(count)
                if count is not None
                else None
            )
            if collection is not None and static_count is not None and (
                static_count < 0 or static_count > 65_536
            ):
                raise readiness.ReadinessContractError(
                    "semantic-isolation vector table allocation differs"
                )


def _semantic_isolation_is_exact_owned_table_root_seal_object(
    node: ast.AST,
    *,
    path: str,
    tree: ast.Module,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Admit only the frozen, module-level P04-US01 ownership seal site."""

    if (
        path != "app/services/table_semantics.py"
        or not isinstance(node, ast.Name)
        or node.id != "object"
        or not isinstance(node.ctx, ast.Load)
    ):
        return False
    call = parents.get(node)
    assignment = parents.get(call) if call is not None else None
    return (
        isinstance(call, ast.Call)
        and call.func is node
        and not call.args
        and not call.keywords
        and isinstance(assignment, ast.Assign)
        and parents.get(assignment) is tree
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Name)
        and assignment.targets[0].id == "_OWNED_CANONICAL_TABLE_ROOT_SEAL"
        and assignment.value is call
        and _ast_digest(assignment)
        == EXPECTED_OWNED_TABLE_ROOT_SEAL_ASSIGNMENT_AST_SHA256
    )


def _semantic_isolation_validate_dedicated_python(raw: bytes, *, path: str) -> None:
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise readiness.ReadinessContractError(
            f"semantic-isolation dedicated Python custody differs: {path}"
        ) from exc
    if _semantic_isolation_node_has(
        tree, _semantic_isolation_is_running_region_atom
    ):
        raise readiness.ReadinessContractError(
            f"semantic-isolation dedicated table code reaches P03: {path}"
        )
    if _semantic_isolation_node_has(tree, _semantic_isolation_is_phase05_atom):
        raise readiness.ReadinessContractError(
            f"semantic-isolation Phase 05 scope differs: {path}"
        )
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    exact_owned_seal_objects = frozenset(
        node
        for node in ast.walk(tree)
        if _semantic_isolation_is_exact_owned_table_root_seal_object(
            node,
            path=path,
            tree=tree,
            parents=parents,
        )
    )
    if path == "app/services/table_semantics.py" and (
        len(exact_owned_seal_objects) != 1
    ):
        raise readiness.ReadinessContractError(
            f"semantic-isolation table ownership seal differs: {path}"
        )
    import_roots = _semantic_isolation_import_roots(tree)
    observed_app_imports: set[tuple[str, str, str | None]] = set()
    observed_public_app_imports: set[tuple[str, str, str | None]] = set()
    observed_exact_non_app_imports: set[tuple[str, str, str | None]] = set()
    for node in ast.walk(tree):
        if _semantic_isolation_reconstructs_protected_scope(node):
            raise readiness.ReadinessContractError(
                f"semantic-isolation reconstructed scope differs: {path}"
            )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name in _SEMANTIC_ISOLATION_DANGEROUS_DUNDER_FUNCTIONS
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation module capability differs: {path}"
            )
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if _semantic_isolation_is_page_identity_atom(name):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation dedicated table code reaches P03: {path}"
                )
            if isinstance(node, ast.Attribute) and "__" in node.attr:
                raise readiness.ReadinessContractError(
                    f"semantic-isolation reflection capability differs: {path}"
                )
            if name in _SEMANTIC_ISOLATION_TABLE_FLAGS:
                if isinstance(node.ctx, ast.Store) or not (
                    isinstance(node.ctx, ast.Load)
                    and _semantic_isolation_flag_is_direct_guard_read(
                        node,
                        parents=parents,
                    )
                ):
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation table flag flow differs: {path}"
                    )
        if isinstance(node, ast.Name) and node.id in {
            "__builtins__",
            "builtins",
            "globals",
            "hasattr",
            "locals",
            "setattr",
            "delattr",
            "vars",
            "object",
        } and node not in exact_owned_seal_objects:
            raise readiness.ReadinessContractError(
                f"semantic-isolation dynamic capability differs: {path}"
            )
        if isinstance(node, ast.Name) and node.id == "getattr":
            parent = parents.get(node)
            if not isinstance(parent, ast.Call) or parent.func is not node:
                raise readiness.ReadinessContractError(
                    f"semantic-isolation dynamic capability differs: {path}"
                )
        if (
            isinstance(node, ast.Name)
            and node.id in _SEMANTIC_ISOLATION_FORBIDDEN_CALLS
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation dynamic capability differs: {path}"
            )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if node.module else [])
            )
            exact_app_imports = {
                (node.module, alias.name, alias.asname)
                for alias in node.names
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("app.")
            }
            for module in modules:
                if module in {
                    "app.models",
                    "app.services.ir",
                    "app.services.tables",
                }:
                    continue
                if exact_app_imports and exact_app_imports <= (
                    _SEMANTIC_ISOLATION_ALLOWED_APP_IMPORTS[path]
                ):
                    continue
                exact_non_app_imports = {
                    (node.module, alias.name, alias.asname)
                    for alias in node.names
                    if isinstance(node, ast.ImportFrom)
                }
                if (
                    module.split(".", 1)[0]
                    not in _SEMANTIC_ISOLATION_SAFE_IMPORT_ROOTS
                    and not (
                        exact_non_app_imports
                        and exact_non_app_imports
                        <= _SEMANTIC_ISOLATION_DEDICATED_EXACT_NON_APP_IMPORTS[
                            path
                        ]
                    )
                ):
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation dedicated import differs: {path}"
                    )
                observed_exact_non_app_imports.update(
                    exact_non_app_imports
                    & _SEMANTIC_ISOLATION_DEDICATED_EXACT_NON_APP_IMPORTS[path]
                )
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "app."
            ):
                for alias in node.names:
                    import_identity = (node.module, alias.name, alias.asname)
                    if import_identity not in (
                        _SEMANTIC_ISOLATION_ALLOWED_APP_IMPORTS[path]
                    ):
                        raise readiness.ReadinessContractError(
                            f"semantic-isolation dedicated import differs: {path}"
                        )
                    observed_app_imports.add(import_identity)
            elif isinstance(node, ast.Import) and any(
                alias.name.startswith("app.") for alias in node.names
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation dedicated import differs: {path}"
                )
            if isinstance(node, ast.ImportFrom):
                constrained_names = {
                    "io": frozenset({"BytesIO", "StringIO"}),
                    "time": frozenset({"perf_counter"}),
                }.get(node.module or "")
                if constrained_names is not None and any(
                    alias.name not in constrained_names for alias in node.names
                ):
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation dedicated import differs: {path}"
                    )
            owner: ast.AST | None = node
            module_level = True
            while owner is not None:
                if isinstance(
                    owner,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                ):
                    module_level = False
                    break
                if (
                    isinstance(owner, ast.If)
                    and isinstance(owner.test, ast.Name)
                    and owner.test.id == "TYPE_CHECKING"
                ):
                    module_level = False
                    break
                owner = parents.get(owner)
            if module_level:
                if isinstance(node, ast.ImportFrom) and (
                    node.module or ""
                ).startswith("app."):
                    for alias in node.names:
                        import_identity = (node.module, alias.name, alias.asname)
                        if import_identity in (
                            _SEMANTIC_ISOLATION_EXISTING_PUBLIC_APP_IMPORTS[path]
                        ):
                            observed_public_app_imports.add(import_identity)
                        elif not (alias.asname or "").startswith("_"):
                            raise readiness.ReadinessContractError(
                                "semantic-isolation public import capability "
                                f"differs: {path}"
                            )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("app.") and not (
                            alias.asname or ""
                        ).startswith("_"):
                            raise readiness.ReadinessContractError(
                                "semantic-isolation public import capability "
                                f"differs: {path}"
                            )
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "getattr":
                if (
                    len(node.args) not in {2, 3}
                    or node.keywords
                    or not isinstance(node.args[1], ast.Constant)
                    or not isinstance(node.args[1].value, str)
                    or node.args[1].value
                    not in _SEMANTIC_ISOLATION_DEDICATED_GETATTR_FIELDS[path]
                ):
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation dynamic capability differs: {path}"
                    )
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in _SEMANTIC_ISOLATION_FORBIDDEN_CALLS
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation dynamic capability differs: {path}"
                )
            root: ast.AST = node.func
            while isinstance(root, ast.Attribute):
                root = root.value
            imported_root = (
                import_roots.get(root.id) if isinstance(root, ast.Name) else None
            )
            if (
                isinstance(root, ast.Name)
                and (
                    root.id in _SEMANTIC_ISOLATION_FORBIDDEN_ROOTS
                    or imported_root in _SEMANTIC_ISOLATION_FORBIDDEN_ROOTS
                )
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation external capability differs: {path}"
                )
            if imported_root in {"io", "time"}:
                allowed_attributes = {
                    "io": frozenset({"BytesIO", "StringIO"}),
                    "time": frozenset({"perf_counter"}),
                }[imported_root]
                if (
                    not (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr in allowed_attributes
                    )
                    and not (
                        isinstance(node.func, ast.Name)
                        and node.func.id in allowed_attributes
                    )
                ):
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation external capability differs: {path}"
                    )
            if imported_root == "pdfplumber":
                payload = node.args[0] if len(node.args) == 1 else None
                if (
                    not isinstance(node.func, ast.Attribute)
                    or node.func.attr != "open"
                    or node.keywords
                    or not isinstance(payload, ast.Call)
                    or not isinstance(payload.func, ast.Attribute)
                    or not isinstance(payload.func.value, ast.Name)
                    or import_roots.get(payload.func.value.id) != "io"
                    or payload.func.attr != "BytesIO"
                    or len(payload.args) != 1
                    or payload.keywords
                    or not isinstance(payload.args[0], ast.Name)
                    or payload.args[0].id != "pdf_bytes"
                ):
                    raise readiness.ReadinessContractError(
                        f"semantic-isolation pdf input custody differs: {path}"
                    )
        if isinstance(node, (ast.Name, ast.Attribute, ast.arg)):
            name = (
                node.id
                if isinstance(node, ast.Name)
                else node.attr
                if isinstance(node, ast.Attribute)
                else node.arg
            )
            if (
                name.startswith("table_")
                and name.endswith("_enabled")
                and name not in _SEMANTIC_ISOLATION_TABLE_FLAGS
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation table flag scope differs: {path}"
                )
        if (
            isinstance(node, ast.keyword)
            and node.arg in _SEMANTIC_ISOLATION_TABLE_FLAGS
            and isinstance(node.value, ast.Constant)
            and node.value.value is True
        ):
            owner: ast.AST | None = node
            while owner is not None and not isinstance(
                owner,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                owner = parents.get(owner)
            owner_arguments = (
                {
                    argument.arg
                    for argument in (*owner.args.args, *owner.args.kwonlyargs)
                }
                if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef))
                else set()
            )
            if node.arg not in owner_arguments:
                raise readiness.ReadinessContractError(
                    f"semantic-isolation forced-on table flag differs: {path}"
                )
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and value.value is True
                and any(
                    _semantic_isolation_node_has(
                        target,
                        lambda value: value in _SEMANTIC_ISOLATION_TABLE_FLAGS,
                    )
                    for target in targets
                )
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation forced-on table flag differs: {path}"
                )
    public_functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    expected = {
        "app/services/table_semantics.py": _SEMANTIC_ISOLATION_TABLE_PUBLIC_ROOTS,
        "app/services/opaque_group_custody.py": _SEMANTIC_ISOLATION_OPAQUE_PUBLIC_ROOTS,
        "app/services/tables.py": _SEMANTIC_ISOLATION_TABLES_PUBLIC_ROOTS,
    }[path]
    if public_functions != set(expected):
        raise readiness.ReadinessContractError(
            f"semantic-isolation public table capability differs: {path}"
        )
    public_classes = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    }
    if public_classes != set(_SEMANTIC_ISOLATION_PUBLIC_CLASSES[path]):
        raise readiness.ReadinessContractError(
            f"semantic-isolation public table capability differs: {path}"
        )
    public_constants: set[str] = set()
    for node in tree.body:
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        public_constants.update(
            target.id
            for target in targets
            if isinstance(target, ast.Name) and not target.id.startswith("_")
        )
    if public_constants != set(_SEMANTIC_ISOLATION_PUBLIC_CONSTANTS[path]):
        raise readiness.ReadinessContractError(
            f"semantic-isolation public table capability differs: {path}"
        )
    if observed_public_app_imports != set(
        _SEMANTIC_ISOLATION_EXISTING_PUBLIC_APP_IMPORTS[path]
    ):
        raise readiness.ReadinessContractError(
            f"semantic-isolation public import capability differs: {path}"
        )
    if observed_app_imports != set(_SEMANTIC_ISOLATION_ALLOWED_APP_IMPORTS[path]):
        raise readiness.ReadinessContractError(
            f"semantic-isolation dedicated import differs: {path}"
        )
    if observed_exact_non_app_imports != set(
        _SEMANTIC_ISOLATION_DEDICATED_EXACT_NON_APP_IMPORTS[path]
    ):
        raise readiness.ReadinessContractError(
            f"semantic-isolation dedicated import differs: {path}"
        )
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        table_flag_arguments = {
            argument.arg
            for argument in (*node.args.args, *node.args.kwonlyargs)
            if argument.arg in _SEMANTIC_ISOLATION_TABLE_FLAGS
        }
        defaults = [
            *([None] * (len(node.args.args) - len(node.args.defaults))),
            *node.args.defaults,
        ]
        positional = {
            argument.arg: default
            for argument, default in zip(node.args.args, defaults, strict=True)
        }
        keyword = dict(zip(
            (argument.arg for argument in node.args.kwonlyargs),
            node.args.kw_defaults,
            strict=True,
        ))
        for name in table_flag_arguments:
            default = positional.get(name, keyword.get(name))
            if default is not None and (
                not isinstance(default, ast.Constant) or default.value is not False
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation table flag default differs: {path}"
                )
    if path == "app/services/opaque_group_custody.py":
        constant_nodes = {
            node.targets[0].id: node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        }
        authority = constant_nodes.get("AUTHORITY")
        policy_id = constant_nodes.get("POLICY_ID")
        schema_version = constant_nodes.get("SCHEMA_VERSION")
        root_singleton_policy = constant_nodes.get("ROOT_SINGLETON_POLICY")
        constants = {
            name: _semantic_isolation_static_int(constant_nodes[name])
            for name in (
                "MAX_RECORDS",
                "MAX_RAW_DEFINITIONS_SCANNED",
                "MAX_CONTENT_ITEM_BYTES",
                "MAX_CONTENT_DOCUMENT_BYTES",
            )
            if name in constant_nodes
        }
        if (
            not isinstance(authority, ast.Constant)
            or authority.value != "diagnostic_only"
            or not isinstance(policy_id, ast.Constant)
            or policy_id.value != "p04-opaque-raw-group-custody-v1"
            or not isinstance(schema_version, ast.Constant)
            or schema_version.value != "1.0"
            or not isinstance(root_singleton_policy, ast.Constant)
            or root_singleton_policy.value
            != "nonsemantic_placement_not_claimed"
            or constants.get("MAX_RECORDS", 65_537) > 65_536
            or constants.get("MAX_RAW_DEFINITIONS_SCANNED", 262_145) > 262_144
            or constants.get("MAX_CONTENT_ITEM_BYTES", 8_388_609) > 8_388_608
            or constants.get("MAX_CONTENT_DOCUMENT_BYTES", 67_108_865)
            > 67_108_864
        ):
            raise readiness.ReadinessContractError(
                "semantic-isolation opaque custody authority differs"
            )
    if path == "app/services/tables.py":
        _semantic_isolation_validate_tables_resource_graph(tree)


def _semantic_isolation_frontend_table_block(raw: bytes) -> tuple[str, str]:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation frontend custody differs"
        ) from exc
    table_import = 'import { readTableSemantics } from "@/lib/table-semantics";\n'
    if source.count(table_import) != 1:
        raise readiness.ReadinessContractError(
            "semantic-isolation frontend table import differs"
        )
    marker = '  if (type === "table") {'
    if source.count(marker) != 1:
        raise readiness.ReadinessContractError(
            "semantic-isolation frontend table branch differs"
        )
    start = source.index(marker)
    opening = source.index("{", start)
    end = _phase04_frontend_matching_delimiter(source, opening, "{", "}") + 1
    block = source[start:end]
    if _semantic_isolation_frontend_scope_is_forbidden(block):
        raise readiness.ReadinessContractError(
            "semantic-isolation frontend table branch scope differs"
        )
    normalized = source.replace(table_import, "", 1)
    normalized = normalized[: start - len(table_import)] + normalized[
        end - len(table_import) :
    ]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), block


def _semantic_isolation_frontend_literals(source: str) -> tuple[str, ...]:
    values: list[str] = []
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        if source[index] not in {'"', "'", "`"}:
            index += 1
            continue
        quote = source[index]
        cursor = index + 1
        escaped = False
        content: list[str] = []
        while cursor < len(source):
            character = source[cursor]
            if character == "\n" and quote != "`":
                break
            if character == quote and not escaped:
                cursor += 1
                break
            if len(content) >= 65_536:
                raise readiness.ReadinessContractError(
                    "semantic-isolation frontend literal resource differs"
                )
            content.append(character)
            escaped = character == "\\" and not escaped
            if character != "\\":
                escaped = False
            cursor += 1
        values.append("".join(content))
        if len(values) > 4_096:
            raise readiness.ReadinessContractError(
                "semantic-isolation frontend literal resource differs"
            )
        index = cursor
    return tuple(values)


def _semantic_isolation_frontend_value_is_forbidden(value: str) -> bool:
    atom = _semantic_isolation_atom(value)
    return bool(
        _semantic_isolation_is_running_region_atom(value)
        or _semantic_isolation_is_page_identity_atom(value)
        or _semantic_isolation_is_phase05_atom(value)
        or "node_fs" in atom
        or "node_child_process" in atom
        or "child_process" in atom
        or "fs_promises" in atom
        or atom in {
            "constructor",
            "fetch",
            "global_this",
            "globalthis",
            "prototype",
            "proto",
        }
    )


def _semantic_isolation_frontend_bindings_reconstruct_scope(
    source: str,
    masked: str,
) -> bool:
    declarations: list[tuple[str, str]] = []
    for match in re.finditer(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
        masked,
    ):
        end = masked.find(";", match.end())
        if end < 0:
            end = masked.find("\n", match.end())
        end = len(masked) if end < 0 else end
        if end - match.end() > 4_096 or len(declarations) >= 1_024:
            raise readiness.ReadinessContractError(
                "semantic-isolation frontend binding resource differs"
            )
        declarations.append((match.group(1), source[match.end() : end]))

    bindings: dict[str, str] = {}
    literal = r'(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')'
    token = re.compile(rf"\s*({literal}|[A-Za-z_$][\w$]*)\s*(?:\+|$)")
    for _ in range(16):
        changed = False
        for name, expression in declarations:
            position = 0
            pieces: list[str] = []
            while position < len(expression):
                match = token.match(expression, position)
                if match is None or match.end() == position:
                    pieces = []
                    break
                value = match.group(1)
                if value[:1] in {'"', "'"}:
                    pieces.append(value[1:-1])
                elif value in bindings:
                    pieces.append(bindings[value])
                else:
                    pieces = []
                    break
                position = match.end()
            if not pieces or position != len(expression):
                continue
            combined = "".join(pieces)
            if len(combined.encode("utf-8")) > 65_536:
                raise readiness.ReadinessContractError(
                    "semantic-isolation frontend binding resource differs"
                )
            if bindings.get(name) != combined:
                bindings[name] = combined
                changed = True
        if not changed:
            break
    return any(
        _semantic_isolation_frontend_value_is_forbidden(value)
        for value in bindings.values()
    )


def _semantic_isolation_frontend_scope_is_forbidden(source: str) -> bool:
    masked = _phase04_mask_frontend_code(source)
    literals = _semantic_isolation_frontend_literals(source)
    oversized_constructor = False
    for match in re.finditer(
        r"\b(?:new\s+)?(?:Array|BigInt64Array|BigUint64Array|Float32Array|"
        r"Float64Array|Int8Array|Int16Array|Int32Array|Uint8Array|"
        r"Uint8ClampedArray|Uint16Array|Uint32Array)\s*\(\s*"
        r"([0-9][0-9_]*(?:\.[0-9_]+)?(?:e[+-]?[0-9_]+)?)",
        masked,
        re.IGNORECASE,
    ):
        try:
            amount = float(match.group(1).replace("_", ""))
        except ValueError:
            oversized_constructor = True
            break
        if not math.isfinite(amount) or amount > 65_536:
            oversized_constructor = True
            break
    return bool(
        any(
            _semantic_isolation_frontend_value_is_forbidden(value)
            for value in literals
        )
        or _semantic_isolation_frontend_bindings_reconstruct_scope(
            source,
            masked,
        )
        or re.search(r"\bdocument\b", masked)
        or re.search(r"\bmodule\s*\.\s*exports\b", masked)
        or re.search(r"\bexports\s*(?:\.|\[)", masked)
        or re.search(r"\bwhile\s*\(\s*true\s*\)", masked, re.IGNORECASE)
        or oversized_constructor
        or re.search(
            r"(?<![A-Za-z0-9_$])<\s*(?:audio|embed|iframe|img|link|object|"
            r"script|source|video)\b",
            masked,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:action|formAction|href|poster|src|srcSet)\s*=",
            masked,
            re.IGNORECASE,
        )
        or re.search(
        r"(?:running[-_]?regions?|page[-_]?identity|phase[-_ ]?0?5|p0?5|"
        r"\b(?:eval|require|fetch|XMLHttpRequest|WebSocket|"
        r"localStorage|sessionStorage|indexedDB|Worker|SharedWorker|"
        r"EventSource|BroadcastChannel|sendBeacon|cookieStore|caches|"
        r"WebTransport|RTCPeerConnection|setTimeout|setInterval|"
        r"queueMicrotask|requestAnimationFrame)\b|"
        r"\b(?:globalThis|window|navigator|location|process|Deno|Bun|"
        r"Reflect|Proxy|WebAssembly|crypto)\b|"
        r"\b(?:console|performance)\s*(?:\.|\[)|"
        r"\b(?:Image|Audio|URL|FileReader)\s*\(|"
        r"(?:\.|\[\s*['\"])(?:constructor|prototype|__proto__)\b|"
        r"\b(?:top|parent|self|frames|opener|document)\s*(?:\.|\[)|"
        r"dangerouslySetInnerHTML|\bimport\s*\(|"
        r"\b(?:onClick|onLoad|onError)\s*=)",
            source,
            re.IGNORECASE,
        )
        or re.search(r"\bFunction\s*\(", source)
        or re.search(r"\bon[A-Z][A-Za-z0-9_$]*\s*=", source)
        or re.search(
            r"\\(?:x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|u\{[0-9A-Fa-f]{1,6}\})",
            source,
        )
    )


def _semantic_isolation_validate_frontend_helper(raw: bytes) -> None:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation frontend helper differs"
        ) from exc
    if _semantic_isolation_frontend_scope_is_forbidden(source):
        raise readiness.ReadinessContractError(
            "semantic-isolation frontend table helper scope differs"
        )
    exports = re.findall(
        r"(?m)^export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
        source,
    )
    export_statements = re.findall(r"(?m)^[ \t]*export\b[^\n]*", source)
    if (
        exports != ["readTableSemantics"]
        or len(export_statements) != 1
        or not re.match(
            r"^export\s+(?:async\s+)?function\s+readTableSemantics\s*\(",
            export_statements[0].lstrip(),
        )
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation frontend public capability differs"
        )


def _semantic_isolation_identity(raw: bytes) -> dict[str, Any]:
    return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _semantic_isolation_is_runtime_code_path(path: str) -> bool:
    relative = PurePosixPath(path)
    if relative.suffix not in _SEMANTIC_ISOLATION_RUNTIME_SUFFIXES:
        return False
    if any(
        path == root or path.startswith(f"{root}/")
        for root in _SEMANTIC_ISOLATION_RUNTIME_ROOTS
    ):
        return True
    return relative.parent == PurePosixPath("frontend")


def _semantic_isolation_discover_runtime_code(root: Path) -> frozenset[str]:
    observed: set[str] = set()
    entry_count = 0
    for relative_root in _SEMANTIC_ISOLATION_RUNTIME_ROOTS:
        directory = root / relative_root
        if not directory.is_dir() or directory.is_symlink():
            raise readiness.ReadinessContractError(
                "semantic-isolation runtime code root differs"
            )
        for entry in directory.rglob("*"):
            entry_count += 1
            if entry_count > _SEMANTIC_ISOLATION_RUNTIME_ENTRY_LIMIT:
                raise readiness.ReadinessContractError(
                    "semantic-isolation runtime path resource differs"
                )
            if entry.is_symlink():
                raise readiness.ReadinessContractError(
                    "semantic-isolation runtime path binding differs"
                )
            relative = entry.relative_to(root)
            if "__pycache__" in relative.parts or any(
                part.startswith(".") for part in relative.parts
            ):
                continue
            path = relative.as_posix()
            if entry.is_file() and _semantic_isolation_is_runtime_code_path(path):
                observed.add(path)
    frontend_root = root / "frontend"
    for entry in frontend_root.iterdir():
        if entry.is_symlink():
            raise readiness.ReadinessContractError(
                "semantic-isolation frontend root binding differs"
            )
        if not entry.is_file():
            continue
        path = entry.relative_to(root).as_posix()
        if _semantic_isolation_is_runtime_code_path(path):
            observed.add(path)
    known_frontend_roots = {
        PurePosixPath(path).parts[1]
        for path in _SEMANTIC_ISOLATION_RUNTIME_ROOTS
        if path.startswith("frontend/")
    }
    for entry in frontend_root.iterdir():
        if not entry.is_dir() or entry.name in (
            known_frontend_roots
            | _SEMANTIC_ISOLATION_FRONTEND_NONPRODUCTION_ROOTS
        ):
            continue
        for descendant in entry.rglob("*"):
            entry_count += 1
            if entry_count > _SEMANTIC_ISOLATION_RUNTIME_ENTRY_LIMIT:
                raise readiness.ReadinessContractError(
                    "semantic-isolation runtime path resource differs"
                )
            if descendant.is_symlink():
                raise readiness.ReadinessContractError(
                    "semantic-isolation frontend root binding differs"
                )
            if (
                descendant.is_file()
                and descendant.suffix in _SEMANTIC_ISOLATION_RUNTIME_SUFFIXES
            ):
                raise readiness.ReadinessContractError(
                    "semantic-isolation Phase 04 production path scope differs"
                )
    allowed_repository_roots = {
        PurePosixPath(path).parts[0]
        for path in _SEMANTIC_ISOLATION_RUNTIME_ROOTS
    }
    for entry in root.iterdir():
        if entry.is_symlink():
            if entry.name not in _SEMANTIC_ISOLATION_NONPRODUCTION_ROOTS:
                raise readiness.ReadinessContractError(
                    "semantic-isolation repository root binding differs"
                )
            continue
        if entry.is_file():
            if entry.suffix in _SEMANTIC_ISOLATION_RUNTIME_SUFFIXES:
                raise readiness.ReadinessContractError(
                    "semantic-isolation Phase 04 production path scope differs"
                )
            continue
        if (
            not entry.is_dir()
            or entry.name in allowed_repository_roots
            or entry.name in _SEMANTIC_ISOLATION_NONPRODUCTION_ROOTS
        ):
            continue
        for descendant in entry.rglob("*"):
            entry_count += 1
            if entry_count > _SEMANTIC_ISOLATION_RUNTIME_ENTRY_LIMIT:
                raise readiness.ReadinessContractError(
                    "semantic-isolation runtime path resource differs"
                )
            if descendant.is_symlink():
                raise readiness.ReadinessContractError(
                    "semantic-isolation repository root binding differs"
                )
            if (
                descendant.is_file()
                and descendant.suffix in _SEMANTIC_ISOLATION_RUNTIME_SUFFIXES
            ):
                raise readiness.ReadinessContractError(
                    "semantic-isolation Phase 04 production path scope differs"
                )
    return frozenset(observed)


def _semantic_isolation_discover_phase05_boundary(root: Path) -> frozenset[str]:
    boundary = root / _SEMANTIC_ISOLATION_PHASE05_BOUNDARY_ROOT
    if not boundary.is_dir() or boundary.is_symlink():
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 05 boundary differs"
        )
    observed: set[str] = set()
    for index, entry in enumerate(boundary.rglob("*"), start=1):
        if index > _SEMANTIC_ISOLATION_PHASE05_BOUNDARY_ENTRY_LIMIT:
            raise readiness.ReadinessContractError(
                "semantic-isolation Phase 05 boundary resource differs"
            )
        if entry.is_symlink():
            raise readiness.ReadinessContractError(
                "semantic-isolation Phase 05 boundary binding differs"
            )
        if entry.is_file():
            observed.add(entry.relative_to(root).as_posix())
    return frozenset(observed)


def _semantic_isolation_validate_phase05_boundary(
    root: Path,
    identities: Any,
) -> list[tuple[str, int, str, bytes, Any]]:
    records = _exact_keys(
        identities,
        _SEMANTIC_ISOLATION_PHASE05_BOUNDARY_PATHS,
        "semantic-isolation Phase 05 boundary",
    )
    if _semantic_isolation_discover_phase05_boundary(root) != (
        _SEMANTIC_ISOLATION_PHASE05_BOUNDARY_PATHS
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 05 boundary differs"
        )
    tracks: list[tuple[str, int, str, bytes, Any]] = []
    for path in sorted(_SEMANTIC_ISOLATION_PHASE05_BOUNDARY_PATHS):
        record = records[path]
        if not isinstance(record, Mapping) or record.get("path") != path:
            raise readiness.ReadinessContractError(
                "semantic-isolation Phase 05 boundary identity differs"
            )
        track = _semantic_isolation_validate_identity_file(
            root,
            record,
            label="semantic-isolation Phase 05 boundary",
            maximum_bytes=DECISION_MAXIMUM_BYTES,
        )
        raw = track[3]
        if (
            path.endswith("/README.md") or "/stories/" in path
        ) and (
            re.search(br"(?m)^Status: Proposed[ \t]*$", raw) is None
            or re.search(br"(?m)^Status: (?:Ready|In Progress)[ \t]*$", raw)
            is not None
        ):
            raise readiness.ReadinessContractError(
                "semantic-isolation Phase 05 story state differs"
            )
        tracks.append(track)
    return tracks


def _semantic_isolation_validate_protected_declarations(
    isolation: Mapping[str, Any],
) -> Mapping[str, Any]:
    if isolation.get("forbidden_capabilities") != list(
        _SEMANTIC_ISOLATION_FORBIDDEN_CAPABILITIES
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation forbidden capability set differs"
        )
    return _exact_keys(
        isolation.get("exact_running_region_paths"),
        _SEMANTIC_ISOLATION_EXACT_RUNNING_REGION_PATHS,
        "semantic-isolation exact running-region path set",
    )


def _semantic_isolation_validate_runtime_code_scope(
    root: Path,
    *,
    expected_paths: Iterable[str],
) -> None:
    expected = frozenset(expected_paths)
    if (
        not expected
        or not all(_semantic_isolation_is_runtime_code_path(path) for path in expected)
        or _semantic_isolation_discover_runtime_code(root) != expected
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 production path scope differs"
        )


def _semantic_isolation_validate_identity_file(
    root: Path,
    identity: Mapping[str, Any],
    *,
    label: str,
    maximum_bytes: int = 2 * 1024 * 1024,
) -> tuple[str, int, str, bytes, Any]:
    record = _exact_keys(
        identity,
        frozenset({"path", "raw_sha256", "size_bytes"}),
        label,
    )
    raw, binding = _read_bound_file(
        root,
        record["path"],
        maximum_bytes=maximum_bytes,
        label=label,
    )
    if (
        type(record["size_bytes"]) is not int
        or len(raw) != record["size_bytes"]
        or hashlib.sha256(raw).hexdigest() != record["raw_sha256"]
    ):
        raise readiness.ReadinessContractError(f"{label} differs")
    return record["path"], maximum_bytes, label, raw, binding


def _semantic_isolation_validate_expiry(
    expiry: Any,
    *,
    today: date | None,
) -> None:
    if not _semantic_isolation_strict_equal(
        expiry, EXPECTED_SEMANTIC_ISOLATION_PHASE04_EXPIRY
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 expiry differs"
        )
    try:
        review_due = date.fromisoformat(expiry["review_due_on"])
    except (KeyError, TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 expiry differs"
        ) from exc
    if (today or datetime.now(tz=UTC).date()) > review_due:
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 renewal expired"
        )


def _validate_semantic_isolation_phase04_renewal(
    root: Path,
    *,
    current_code: Mapping[str, Mapping[str, Any]],
    current_dependency_custody: Mapping[str, Any],
    expected_history: Mapping[str, Any],
    hardened_renewal: Mapping[str, Any],
    historical_dependency_custody: Mapping[str, Any],
    original_waiver: Mapping[str, Any],
    today: date | None,
) -> tuple[dict[str, Any], bytes, Any, list[tuple[str, int, str, bytes, Any]]]:
    """Validate the non-operative semantic-isolation renewal candidate."""

    raw, binding = _read_bound_file(
        root,
        str(SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label="semantic-isolation Phase 04 latency renewal waiver",
    )
    expected_identity = EXPECTED_SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_IDENTITY
    if (
        len(raw) != expected_identity["size_bytes"]
        or hashlib.sha256(raw).hexdigest() != expected_identity["raw_sha256"]
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 latency renewal waiver differs"
        )
    renewal = _strict_json(raw, "semantic-isolation Phase 04 latency renewal waiver")
    if (
        renewal.get("semantic_sha256") != expected_identity["semantic_sha256"]
        or renewal.get("semantic_sha256") != waiver_semantic_sha256(renewal)
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 latency renewal digest differs"
        )
    _exact_keys(
        renewal,
        frozenset(
            {
                "administrative_update",
                "approval",
                "closed_phase04_scope",
                "decision_identity",
                "deferred_work",
                "exception_scope",
                "expiry",
                "failed_history",
                "hosted_usage",
                "identity_dag",
                "not_waived",
                "operational_constraints",
                "prior_amendment_approval_identity",
                "prior_amendment_identity",
                "prior_hardened_decision_identity",
                "prior_hardened_renewal_identity",
                "prior_independent_approval_identity",
                "prior_verification_identity",
                "record_kind",
                "renewal_id",
                "renews_renewal_id",
                "schema_version",
                "semantic_isolation",
                "semantic_sha256",
                "status",
                "story",
                "verification_state",
            }
        ),
        "semantic-isolation Phase 04 latency renewal waiver",
    )
    if {
        field: renewal[field]
        for field in (
            "schema_version",
            "record_kind",
            "story",
            "renewal_id",
            "renews_renewal_id",
            "status",
        )
    } != {
        "schema_version": "1.1",
        "record_kind": (
            "p03_us08_phase04_tables_semantic_isolation_latency_exception_renewal"
        ),
        "story": "P03-US08",
        "renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260805-"
            "PHASE04-TABLES-SEMANTIC-ISOLATION"
        ),
        "renews_renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-"
            "PHASE04-TABLES-HARDENED"
        ),
        "status": "requester_authorized_pending_independent_approval",
    }:
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 renewal identity differs"
        )
    if renewal["approval"] != {
        "authorized_on": "2026-08-05",
        "owner": "project owner/requester",
        "source": "active Codex thread",
        "statements": [
            "I explicitly authorize autonomous execution of Phase 04 — Tables only.",
            (
                "I also authorize the narrow administrative renewal of the "
                "existing P03-US08 latency exception required to permit unrelated "
                "Phase 04 table changes."
            ),
        ],
    }:
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 approval differs"
        )
    if not _semantic_isolation_strict_equal(
        renewal["administrative_update"],
        {
            "authorized_on": "2026-08-06",
            "owner": "project owner/requester",
            "source": "active Codex thread",
            "scope": (
                "exact frozen P04-US01 external-controller measurement closure "
                "and acyclic gate-input identity refresh only; the dev-only "
                "dependency bridge is unchanged"
            ),
            "policy_effect": (
                "none; every inherited ceiling, non-waived gate, default-off "
                "rollback, expiry, and terminal approval requirement is unchanged"
            ),
            "superseded_record_identity": {
                "path": str(
                    SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
                ),
                "raw_sha256": (
                    "0b985e3c6a9f4a3142d1c61bb9f0ded5b2f659ae82f18eac45005de02ac85c03"
                ),
                "semantic_sha256": (
                    "2acfa68e610878a1411888f7aa76f22e92bd05c24cd4fe3673468d522d87c4e9"
                ),
                "size_bytes": 47_969,
            },
            "superseded_decision_identity": {
                "path": str(
                    EXPECTED_SEMANTIC_ISOLATION_PHASE04_RENEWAL_DECISION_IDENTITY[
                        "path"
                    ]
                ),
                "raw_sha256": (
                    "1d82cffae2d81ae1fb8ec3b803c1b72fe1aaba43be16552777f97437742ad11d"
                ),
                "size_bytes": 30_186,
            },
            "prior_guard_identity": {
                "path": str(SEMANTIC_ISOLATION_GUARD_PATH),
                "raw_sha256": (
                    "069ed24ac9cd01d379d9fa045633ce075413db07765cdab5e18b8b7e0645a528"
                ),
                "size_bytes": 679_965,
            },
            "prior_focused_test_identity": {
                "path": str(SEMANTIC_ISOLATION_FOCUSED_TEST_PATH),
                "raw_sha256": (
                    "b2f9b1ee319a0be1ac8168342177de4f2a2da77c98e45292d22d39c1b0359a43"
                ),
                "size_bytes": 351_684,
            },
        },
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 administrative update differs"
        )
    for field in (
        "exception_scope",
        "failed_history",
        "hosted_usage",
        "not_waived",
        "operational_constraints",
        "deferred_work",
    ):
        if (
            renewal[field] != original_waiver[field]
            or renewal[field] != hardened_renewal[field]
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation Phase 04 {field.replace('_', ' ')} differs"
            )
    if renewal["failed_history"] != expected_history or expected_history != (
        EXPECTED_FAILED_HISTORY
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 failed history differs"
        )
    _semantic_isolation_validate_expiry(renewal["expiry"], today=today)
    if not _semantic_isolation_strict_equal(renewal["verification_state"], {
        "state": "pending_final_code_and_test_identity",
        "independent_approval_required": True,
        "operative": False,
        "production_use_authorized": False,
        "phase05_authorized": False,
    }):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 verification state differs"
        )
    if not _semantic_isolation_strict_equal(renewal["identity_dag"], {
        "direction": (
            "prior evidence -> decision -> renewal JSON; preapproval US01 "
            "execution evidence -> P04-US01 final-code story gate; (renewal "
            "JSON + guard + focused tests + P04-US01 final-code story gate + "
            "focused gate execution) -> verification -> independent review "
            "artifacts -> terminal approval"
        ),
        "upstream_contains_downstream_digest": False,
        "terminal_independent_approval_present": False,
        "final_retained_metrics_evidence_is_downstream": True,
        "self_or_mutual_hash_authorized": False,
    }):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 identity DAG differs"
        )

    tracks: list[tuple[str, int, str, bytes, Any]] = []
    if renewal["decision_identity"] != (
        EXPECTED_SEMANTIC_ISOLATION_PHASE04_RENEWAL_DECISION_IDENTITY
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 decision identity differs"
        )
    for field, expected, label in (
        (
            "decision_identity",
            EXPECTED_SEMANTIC_ISOLATION_PHASE04_RENEWAL_DECISION_IDENTITY,
            "semantic-isolation Phase 04 decision",
        ),
        (
            "prior_hardened_decision_identity",
            EXPECTED_HARDENED_PHASE04_RENEWAL_DECISION_IDENTITY,
            "semantic-isolation prior hardened decision",
        ),
        (
            "prior_verification_identity",
            {
                "path": (
                    "tracker/phase-03-layout/evidence/"
                    "P03-US08-phase04-tables-hardened-renewal-verification.md"
                ),
                "raw_sha256": (
                    "90e7623f6868d413001208bbb037f7526008fa241937171d9d9d41025f5d5100"
                ),
                "size_bytes": 16_517,
            },
            "semantic-isolation prior verification",
        ),
        (
            "prior_independent_approval_identity",
            {
                "path": (
                    "tracker/phase-03-layout/evidence/"
                    "P03-US08-phase04-tables-hardened-renewal-"
                    "independent-approval.md"
                ),
                "raw_sha256": (
                    "a57f537c7636a5dc918e819f916ee4c9234af5bdee6b375fd1956bf1492e7715"
                ),
                "size_bytes": 5_573,
            },
            "semantic-isolation prior independent approval",
        ),
        (
            "prior_amendment_identity",
            {
                "path": (
                    "tracker/phase-03-layout/evidence/"
                    "P03-US08-phase04-tables-hardened-renewal-"
                    "implementation-state-amendment.md"
                ),
                "raw_sha256": (
                    "4a411bad9e605c3c4644c826c05d497474ce7c45c52b546b8c6e97eda9f841bc"
                ),
                "size_bytes": 6_672,
            },
            "semantic-isolation prior amendment",
        ),
        (
            "prior_amendment_approval_identity",
            {
                "path": (
                    "tracker/phase-03-layout/evidence/"
                    "P03-US08-phase04-tables-hardened-renewal-"
                    "implementation-state-amendment-approval.md"
                ),
                "raw_sha256": (
                    "2c820a0e8c0027dcf986473a974a3db69002c0fd1f5aed2e3f62dba1acc3d389"
                ),
                "size_bytes": 6_026,
            },
            "semantic-isolation prior amendment approval",
        ),
    ):
        if renewal[field] != expected:
            raise readiness.ReadinessContractError(f"{label} identity differs")
        tracks.append(
            _semantic_isolation_validate_identity_file(
                root,
                renewal[field],
                label=label,
                maximum_bytes=DECISION_MAXIMUM_BYTES,
            )
        )
    if renewal["prior_hardened_renewal_identity"] != {
        "path": str(HARDENED_PHASE04_RENEWAL_WAIVER_PATH),
        **EXPECTED_HARDENED_PHASE04_RENEWAL_WAIVER_IDENTITY,
    }:
        raise readiness.ReadinessContractError(
            "semantic-isolation prior hardened renewal identity differs"
        )

    scope = _exact_keys(
        renewal["closed_phase04_scope"],
        frozenset(
            {
                "administrative_candidate_paths",
                "allowed_nonproduction_patterns",
                "configuration_paths",
                "dedicated_frontend_paths",
                "dedicated_python_paths",
                "dependency_changes_authorized",
                "exact_protected_compatibility_paths",
                "new_production_paths_authorized",
                "phase04_only",
                "phase05_authorized",
                "public_capability_expansion_authorized",
                "scanner_relaxation_authorized",
                "shared_frontend_paths",
                "shared_python_paths",
                "stories_in_dependency_order",
            }
        ),
        "semantic-isolation closed Phase 04 scope",
    )
    expected_shared_python = (
        "app/models.py",
        "app/services/ir.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
        "app/services/source_text_alignment.py",
        "app/services/text_reconciliation.py",
    )
    expected_dedicated_python = (
        "app/services/opaque_group_custody.py",
        "app/services/table_semantics.py",
        "app/services/tables.py",
    )
    expected_protected_compatibility = (
        "app/api.py",
        "app/services/serializer.py",
        "frontend/lib/canonical-presentation.ts",
        "frontend/lib/document-api.ts",
        "frontend/lib/normalize-document-json.ts",
        "frontend/lib/page-results.ts",
        "frontend/lib/serialize-output.ts",
        "frontend/lib/types.ts",
    )
    expected_administrative_candidates = (
        str(SEMANTIC_ISOLATION_GUARD_PATH),
        str(SEMANTIC_ISOLATION_FOCUSED_TEST_PATH),
    )
    expected_nonproduction_patterns = (
        "tests/fixtures/phase_04/tables/**",
        "tests/contract/test_p04_us(01|02|04|03)_*.py",
        "tests/performance/test_p04_us(01|02|04|03)_*.py",
        "tests/regression/phase_04/test_p04_us(01|02|04|03)_*.py",
        "tests/stories/phase_04/test_p04_us(01|02|04|03)_*.py",
        "frontend/tests/p04-us(01|02|04|03)-*.test.mts",
        "tracker/phase-04-tables/**",
    )
    if (
        scope["phase04_only"] is not True
        or scope["phase05_authorized"] is not False
        or tuple(scope["stories_in_dependency_order"])
        != ("P04-US01", "P04-US02", "P04-US04", "P04-US03")
        or tuple(scope["configuration_paths"]) != (".env.example", "app/config.py")
        or tuple(scope["shared_python_paths"]) != expected_shared_python
        or tuple(scope["dedicated_python_paths"]) != expected_dedicated_python
        or tuple(scope["shared_frontend_paths"])
        != ("frontend/app/clearleaf-workspace.tsx",)
        or tuple(scope["dedicated_frontend_paths"])
        != ("frontend/lib/table-semantics.ts",)
        or tuple(scope["exact_protected_compatibility_paths"])
        != expected_protected_compatibility
        or tuple(scope["administrative_candidate_paths"])
        != expected_administrative_candidates
        or tuple(scope["allowed_nonproduction_patterns"])
        != expected_nonproduction_patterns
        or scope["new_production_paths_authorized"] is not False
        or scope["dependency_changes_authorized"] is not False
        or scope["public_capability_expansion_authorized"] is not False
        or scope["scanner_relaxation_authorized"] is not False
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation closed Phase 04 scope differs"
        )

    isolation = _exact_keys(
        renewal["semantic_isolation"],
        frozenset(
            {
                "activation_policy",
                "allowed_app_imports",
                "candidate_specific_table_projection_sha256",
                "closed_table_public_classes",
                "closed_table_public_constants",
                "closed_table_public_roots",
                "dependency_custody_bridge",
                "exact_running_region_paths",
                "existing_public_app_imports",
                "final_p04_us01_code_identities",
                "forbidden_capabilities",
                "models_validator_delta",
                "phase04_flags",
                "phase05_boundary_identities",
                "p04_us01_administrative_freeze",
                "protected_code_manifest_sha256",
                "protected_code_path_count",
                "runtime_code_roots",
                "runtime_code_suffixes",
                "scanner_assurance",
                "schema_id",
                "shared_frontend_projection_sha256",
                "shared_python_projection_sha256",
                "table_semantics_max_ast_nodes",
            }
        ),
        "semantic-isolation contract",
    )
    expected_activation_policy = {
        "mode": "terminal_exact_freeze",
        "future_syntax_authorized_by_scanner": False,
        "live_gate_date_policy": {
            "historical_fixed_dates_preserved": True,
            "live_override_supplied": False,
            "timezone": "UTC",
        },
        "reissue_after_each_story_or_code_freeze": True,
        "operative_between_freezes": False,
        "fixed_verification_path": str(
            SEMANTIC_ISOLATION_PHASE04_VERIFICATION_PATH
        ),
        "fixed_terminal_approval_path": str(
            SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH
        ),
        "fixed_focused_gate_path": str(
            SEMANTIC_ISOLATION_PHASE04_FOCUSED_GATE_PATH
        ),
        "fixed_us01_story_gate_path": str(
            SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH
        ),
        "us01_preapproval_evidence_root": str(
            SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT
        ),
        "fixed_review_paths": {
            "production_security": str(
                SEMANTIC_ISOLATION_PHASE04_PRODUCTION_SECURITY_REVIEW_PATH
            ),
            "metrics_custody": str(
                SEMANTIC_ISOLATION_PHASE04_METRICS_CUSTODY_REVIEW_PATH
            ),
        },
        "terminal_status_owner_paths": list(
            SEMANTIC_ISOLATION_STATUS_OWNER_PATHS
        ),
        "non_authoritative_status_summary_paths": list(
            EXPECTED_SEMANTIC_ISOLATION_NON_AUTHORITATIVE_STATUS_SUMMARY_PATHS
        ),
        "terminal_configuration_paths": list(
            SEMANTIC_ISOLATION_TERMINAL_CONFIGURATION_PATHS
        ),
        "terminal_identity_requirements": [
            "every current required code identity",
            (
                "every closed Phase 04 production, configuration, and "
                "frontend identity"
            ),
            "executable guard identity",
            "focused test identity",
            "P04-US01 final-code gate evidence identity",
            "P04-US01 exact gate-input identity manifest",
            "verification identity",
            "dependency custody",
            "exact current non-authoritative reconciliation summary identities",
            "protected P03 manifest",
            "Phase 05 Proposed-state boundary",
            "expiry and exact exception scope",
        ],
    }
    expected_scanner_assurance = {
        "role": "non_authorizing_best_effort_telemetry",
        "authorization_effect": "none",
        "sound_sandbox_claimed": False,
        "comprehensive_capability_detection_claimed": False,
        "comprehensive_resource_or_termination_detection_claimed": False,
        "missed_or_accepted_syntax_authorizes_bytes": False,
        "nonwaived_gate_authority": (
            "exact_pinned_execution_and_independent_review_only"
        ),
        "mutated_bytes_require_new_terminal_freeze": True,
    }
    if (
        isolation["schema_id"] != "p03-us08-phase04-table-semantic-isolation-v2"
        or not _semantic_isolation_strict_equal(
            isolation["activation_policy"], expected_activation_policy
        )
        or not _semantic_isolation_strict_equal(
            isolation["scanner_assurance"], expected_scanner_assurance
        )
        or not _semantic_isolation_strict_equal(
            isolation["phase04_flags"],
            {
                name: False
                for name in EXPECTED_HARDENED_PHASE04_SETTING_ORDER
            },
        )
        or not _semantic_isolation_strict_equal(
            isolation["candidate_specific_table_projection_sha256"],
            {
                "app/models.py": (
                    _SEMANTIC_ISOLATION_FINAL_US01_MODELS_PROJECTION_SHA256
                ),
                "app/services/pipeline.py": (
                    _SEMANTIC_ISOLATION_FINAL_US01_TABLE_PROJECTION_SHA256
                )
            },
        )
        or not _semantic_isolation_strict_equal(
            isolation["models_validator_delta"],
            _SEMANTIC_ISOLATION_FINAL_US01_MODELS_DELTA,
        )
        or not _semantic_isolation_strict_equal(
            isolation["final_p04_us01_code_identities"],
            {
                "app/models.py": dict(
                    _SEMANTIC_ISOLATION_FINAL_US01_MODELS_IDENTITY
                ),
                "app/services/pipeline.py": dict(
                    EXPECTED_CURRENT_FROZEN_P04_US01_PIPELINE_IDENTITY
                ),
                "app/services/table_semantics.py": dict(
                    EXPECTED_CURRENT_FROZEN_P04_US01_TABLE_SEMANTICS_IDENTITY
                ),
            },
        )
        or isolation["table_semantics_max_ast_nodes"]
        != EXPECTED_TABLE_SEMANTICS_MAX_AST_NODES
        or set(isolation["closed_table_public_roots"])
        != set(
            _SEMANTIC_ISOLATION_TABLE_PUBLIC_ROOTS
            | _SEMANTIC_ISOLATION_OPAQUE_PUBLIC_ROOTS
            | _SEMANTIC_ISOLATION_TABLES_PUBLIC_ROOTS
        )
        or isolation["closed_table_public_classes"]
        != {
            path: sorted(values)
            for path, values in _SEMANTIC_ISOLATION_PUBLIC_CLASSES.items()
        }
        or isolation["closed_table_public_constants"]
        != {
            path: sorted(values)
            for path, values in _SEMANTIC_ISOLATION_PUBLIC_CONSTANTS.items()
        }
        or isolation["existing_public_app_imports"]
        != {
            path: [
                {"module": module, "name": name, "asname": asname}
                for module, name, asname in sorted(values)
            ]
            for path, values in (
                _SEMANTIC_ISOLATION_EXISTING_PUBLIC_APP_IMPORTS.items()
            )
        }
        or isolation["allowed_app_imports"]
        != {
            path: [
                {"module": module, "name": name, "asname": asname}
                for module, name, asname in sorted(values)
            ]
            for path, values in _SEMANTIC_ISOLATION_ALLOWED_APP_IMPORTS.items()
        }
        or tuple(isolation["runtime_code_roots"])
        != _SEMANTIC_ISOLATION_RUNTIME_ROOTS
        or set(isolation["runtime_code_suffixes"])
        != set(_SEMANTIC_ISOLATION_RUNTIME_SUFFIXES)
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation table contract differs"
        )
    tracks.extend(
        _validate_semantic_isolation_dependency_custody_bridge(
            root,
            bridge=isolation["dependency_custody_bridge"],
            historical_dependency_custody=historical_dependency_custody,
            current_dependency_custody=current_dependency_custody,
        )
    )
    administrative_freeze = _exact_keys(
        isolation["p04_us01_administrative_freeze"],
        frozenset(
            {
                "excluded_administrative_paths",
                "gate_input_count",
                "gate_input_identities",
                "gate_input_manifest_sha256",
                "gate_input_total_bytes",
                "schema_id",
                "scope",
            }
        ),
        "semantic-isolation P04-US01 administrative freeze",
    )
    observed_gate_inputs = (
        _semantic_isolation_collect_p04_us01_administrative_freeze(
            root,
            tracks=tracks,
        )
    )
    expected_freeze = (
        EXPECTED_SEMANTIC_ISOLATION_P04_US01_ADMINISTRATIVE_FREEZE
    )
    if (
        administrative_freeze["schema_id"]
        != "p03-us08-phase04-p04-us01-administrative-freeze-v1"
        or administrative_freeze["scope"]
        != (
            "exact current P04-US01 required final-code gate inputs; the "
            "administrative guard and focused test are excluded to preserve "
            "an acyclic identity DAG"
        )
        or administrative_freeze["excluded_administrative_paths"]
        != sorted(
            _SEMANTIC_ISOLATION_P04_US01_ADMINISTRATIVE_FREEZE_EXCLUDED_PATHS
        )
        or not _semantic_isolation_strict_equal(
            administrative_freeze["gate_input_identities"],
            observed_gate_inputs,
        )
        or administrative_freeze["gate_input_count"]
        != expected_freeze["gate_input_count"]
        or administrative_freeze["gate_input_count"]
        != len(observed_gate_inputs)
        or administrative_freeze["gate_input_total_bytes"]
        != expected_freeze["gate_input_total_bytes"]
        or administrative_freeze["gate_input_total_bytes"]
        != sum(value["size_bytes"] for value in observed_gate_inputs.values())
        or administrative_freeze["gate_input_manifest_sha256"]
        != expected_freeze["gate_input_manifest_sha256"]
        or administrative_freeze["gate_input_manifest_sha256"]
        != metrics._sha256_json(observed_gate_inputs)
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 administrative freeze differs"
        )
    tracks.extend(
        _semantic_isolation_validate_us01_gate_inputs(
            root,
            administrative_freeze["gate_input_identities"],
        )
    )
    exact_running_regions = (
        _semantic_isolation_validate_protected_declarations(isolation)
    )

    tracks.extend(
        _semantic_isolation_validate_phase05_boundary(
            root,
            isolation["phase05_boundary_identities"],
        )
    )

    excluded_from_protected = set(
        (*scope["configuration_paths"], *scope["shared_python_paths"],
         *scope["dedicated_python_paths"], *scope["shared_frontend_paths"],
         *scope["dedicated_frontend_paths"], *scope["administrative_candidate_paths"])
    )
    protected_code = {
        path: dict(identity)
        for path, identity in current_code.items()
        if path not in excluded_from_protected
    }
    if (
        len(protected_code) != isolation["protected_code_path_count"]
        or metrics._sha256_json(protected_code)
        != isolation["protected_code_manifest_sha256"]
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation protected P03 code manifest differs"
        )

    observed_python_projection: dict[str, str] = {}
    for path in expected_shared_python:
        code_raw, code_binding = _read_bound_file(
            root,
            path,
            maximum_bytes=2 * 1024 * 1024,
            label="semantic-isolation shared Python code",
        )
        _semantic_isolation_validate_shared_python_table_scope(
            code_raw,
            path=path,
        )
        observed_python_projection[path] = _semantic_isolation_python_projection(
            code_raw,
            path=path,
        )
        tracks.append(
            (path, 2 * 1024 * 1024, "semantic-isolation shared Python code", code_raw, code_binding)
        )
    if observed_python_projection != isolation["shared_python_projection_sha256"]:
        raise readiness.ReadinessContractError(
            "semantic-isolation shared Python projection differs"
        )

    env_raw, env_binding = _read_bound_file(
        root,
        ".env.example",
        maximum_bytes=128 * 1024,
        label="semantic-isolation environment example",
    )
    _validate_hardened_phase04_env_example(env_raw)
    tracks.append(
        (".env.example", 128 * 1024, "semantic-isolation environment example", env_raw, env_binding)
    )
    config_raw, config_binding = _read_bound_file(
        root,
        "app/config.py",
        maximum_bytes=2 * 1024 * 1024,
        label="semantic-isolation configuration",
    )
    if _phase04_config_normalized_digest(config_raw) != (
        EXPECTED_PHASE04_CONFIG_NORMALIZED_AST_SHA256
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation configuration projection differs"
        )
    tracks.append(
        ("app/config.py", 2 * 1024 * 1024, "semantic-isolation configuration", config_raw, config_binding)
    )

    for path in expected_dedicated_python:
        code_raw, code_binding = _read_bound_file(
            root,
            path,
            maximum_bytes=2 * 1024 * 1024,
            label="semantic-isolation dedicated Python code",
        )
        _semantic_isolation_validate_dedicated_python(code_raw, path=path)
        tracks.append(
            (path, 2 * 1024 * 1024, "semantic-isolation dedicated Python code", code_raw, code_binding)
        )

    frontend_path = "frontend/app/clearleaf-workspace.tsx"
    frontend_raw, frontend_binding = _read_bound_file(
        root,
        frontend_path,
        maximum_bytes=2 * 1024 * 1024,
        label="semantic-isolation shared frontend code",
    )
    frontend_projection, _ = _semantic_isolation_frontend_table_block(frontend_raw)
    if isolation["shared_frontend_projection_sha256"] != {
        frontend_path: frontend_projection
    }:
        raise readiness.ReadinessContractError(
            "semantic-isolation shared frontend projection differs"
        )
    tracks.append(
        (frontend_path, 2 * 1024 * 1024, "semantic-isolation shared frontend code", frontend_raw, frontend_binding)
    )
    frontend_helper_path = "frontend/lib/table-semantics.ts"
    helper_raw, helper_binding = _read_bound_file(
        root,
        frontend_helper_path,
        maximum_bytes=2 * 1024 * 1024,
        label="semantic-isolation frontend table helper",
    )
    _semantic_isolation_validate_frontend_helper(helper_raw)
    tracks.append(
        (frontend_helper_path, 2 * 1024 * 1024, "semantic-isolation frontend table helper", helper_raw, helper_binding)
    )

    for path in sorted(_SEMANTIC_ISOLATION_EXACT_RUNNING_REGION_PATHS):
        expected = exact_running_regions[path]
        code_raw, code_binding = _read_bound_file(
            root,
            path,
            maximum_bytes=2 * 1024 * 1024,
            label="semantic-isolation exact running-region code",
        )
        if _semantic_isolation_identity(code_raw) != expected:
            raise readiness.ReadinessContractError(
                "semantic-isolation exact running-region custody differs"
            )
        tracks.append(
            (path, 2 * 1024 * 1024, "semantic-isolation exact running-region code", code_raw, code_binding)
        )

    repository_code = metrics.collect_code_file_identities(root)
    closed_production = set(
        (*scope["configuration_paths"], *scope["shared_python_paths"],
         *scope["dedicated_python_paths"], *scope["shared_frontend_paths"],
         *scope["dedicated_frontend_paths"], *scope["exact_protected_compatibility_paths"])
    )
    expected_runtime = {
        path
        for path in current_code
        if _semantic_isolation_is_runtime_code_path(path)
    } | {
        path
        for path in closed_production
        if _semantic_isolation_is_runtime_code_path(path)
    }
    _semantic_isolation_validate_runtime_code_scope(
        root,
        expected_paths=expected_runtime,
    )
    if any(re.search(r"(?:phase|p)[-_]?0?5\b", path, re.IGNORECASE) for path in repository_code):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 05 path scope differs"
        )
    return renewal, raw, binding, tracks


def _semantic_isolation_file_identity(path: str, raw: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _semantic_isolation_collect_p04_us01_administrative_freeze(
    root: Path,
    *,
    tracks: list[tuple[str, int, str, bytes, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Freeze the exact acyclic P04-US01 gate inputs admitted by this update."""

    try:
        required_paths = tuple(table_metrics.required_final_code_paths(root))
    except (OSError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation administrative freeze discovery differs"
        ) from exc
    excluded = _SEMANTIC_ISOLATION_P04_US01_ADMINISTRATIVE_FREEZE_EXCLUDED_PATHS
    if (
        not required_paths
        or not excluded <= set(required_paths)
        or len(required_paths) > _SEMANTIC_ISOLATION_US01_MAXIMUM_GATE_INPUTS
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation administrative freeze path set differs"
        )
    identities: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for path in sorted(set(required_paths) - excluded):
        label = "semantic-isolation administrative freeze input"
        raw, binding = _read_bound_file(
            root,
            path,
            maximum_bytes=_SEMANTIC_ISOLATION_US01_MAXIMUM_GATE_INPUT_BYTES,
            label=label,
        )
        if tracks is not None:
            tracks.append(
                (
                    path,
                    _SEMANTIC_ISOLATION_US01_MAXIMUM_GATE_INPUT_BYTES,
                    label,
                    raw,
                    binding,
                )
            )
        total_bytes += len(raw)
        if total_bytes > _SEMANTIC_ISOLATION_US01_MAXIMUM_TOTAL_GATE_INPUT_BYTES:
            raise readiness.ReadinessContractError(
                "semantic-isolation administrative freeze byte bound differs"
            )
        identities[path] = _semantic_isolation_file_identity(path, raw)
    return identities


def _semantic_isolation_strict_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, Mapping):
        return (
            isinstance(actual, Mapping)
            and set(actual) == set(expected)
            and all(
                _semantic_isolation_strict_equal(actual[key], expected[key])
                for key in expected
            )
        )
    if isinstance(expected, list):
        return (
            type(actual) is list
            and len(actual) == len(expected)
            and all(
                _semantic_isolation_strict_equal(left, right)
                for left, right in zip(actual, expected, strict=True)
            )
        )
    return type(actual) is type(expected) and actual == expected


def _semantic_isolation_dependency_bridge_toml_sha256(
    value: Mapping[str, Any],
) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _semantic_isolation_parse_dependency_bridge_toml(
    raw: bytes,
    *,
    label: str,
) -> dict[str, Any]:
    try:
        value = tomllib.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise readiness.ReadinessContractError(
            f"semantic-isolation dependency bridge {label} is not strict TOML"
        ) from exc
    if not isinstance(value, dict):
        raise readiness.ReadinessContractError(
            f"semantic-isolation dependency bridge {label} differs"
        )
    return value


def _semantic_isolation_dependency_bridge_manifest_identity(
    path: str,
    raw: bytes,
) -> dict[str, Any]:
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _semantic_isolation_dependency_bridge_package(
    lock: Mapping[str, Any],
    name: str,
) -> Mapping[str, Any]:
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency bridge lock package set differs"
        )
    matches = [
        package
        for package in packages
        if isinstance(package, Mapping) and package.get("name") == name
    ]
    if len(matches) != 1:
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency bridge lock package set differs"
        )
    return matches[0]


def _validate_semantic_isolation_dependency_custody_bridge(
    root: Path,
    *,
    bridge: Mapping[str, Any],
    historical_dependency_custody: Mapping[str, Any],
    current_dependency_custody: Mapping[str, Any],
) -> list[tuple[str, int, str, bytes, Any]]:
    """Validate the exact dev-only psutil declaration without waiving custody."""

    expected = EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE
    _exact_keys(
        bridge,
        frozenset(expected),
        "semantic-isolation dependency custody bridge",
    )
    if not _semantic_isolation_strict_equal(bridge, expected):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge record differs"
        )

    # Preserve the general schema validator for both the immutable historical
    # observation and the exact current observation.  Only their two manifest
    # identities are reconciled below; no general comparison is weakened.
    metrics.validate_dependency_custody(historical_dependency_custody)
    metrics.validate_dependency_custody(current_dependency_custody)
    if (
        metrics._sha256_json(historical_dependency_custody)
        != bridge["historical_dependency_custody_sha256"]
        or metrics._sha256_json(current_dependency_custody)
        != bridge["current_dependency_custody_sha256"]
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge digest differs"
        )

    historical_manifests = historical_dependency_custody["manifests"]
    current_manifests = current_dependency_custody["manifests"]
    if (
        not _semantic_isolation_strict_equal(
            historical_manifests,
            bridge["historical_manifest_identities"],
        )
        or not _semantic_isolation_strict_equal(
            current_manifests,
            bridge["current_manifest_identities"],
        )
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge manifest differs"
        )
    changed_manifest_paths = sorted(
        path
        for path in historical_manifests
        if historical_manifests[path] != current_manifests[path]
    )
    if changed_manifest_paths != ["pyproject.toml", "uv.lock"]:
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge manifest scope differs"
        )
    for path in bridge["unchanged_manifest_paths"]:
        if not _semantic_isolation_strict_equal(
            historical_manifests[path],
            current_manifests[path],
        ):
            raise readiness.ReadinessContractError(
                "semantic-isolation dependency custody bridge unchanged manifest differs"
            )
    for section in bridge["unchanged_custody_sections"]:
        if not _semantic_isolation_strict_equal(
            historical_dependency_custody[section],
            current_dependency_custody[section],
        ):
            raise readiness.ReadinessContractError(
                "semantic-isolation dependency custody bridge runtime differs"
            )

    tracks: list[tuple[str, int, str, bytes, Any]] = []
    manifest_bytes: dict[str, bytes] = {}
    for path in ("pyproject.toml", "uv.lock"):
        label = "semantic-isolation dependency custody bridge manifest"
        raw, binding = _read_bound_file(
            root,
            path,
            maximum_bytes=metrics.MAX_DEPENDENCY_MANIFEST_BYTES,
            label=label,
        )
        if not _semantic_isolation_strict_equal(
            _semantic_isolation_dependency_bridge_manifest_identity(path, raw),
            current_manifests[path],
        ):
            raise readiness.ReadinessContractError(
                "semantic-isolation dependency custody bridge current bytes differ"
            )
        manifest_bytes[path] = raw
        tracks.append(
            (
                path,
                metrics.MAX_DEPENDENCY_MANIFEST_BYTES,
                label,
                raw,
                binding,
            )
        )

    pyproject_raw = manifest_bytes["pyproject.toml"]
    pyproject_line = _SEMANTIC_ISOLATION_DEPENDENCY_BRIDGE_PYPROJECT_DEV_LINE
    if pyproject_raw.count(pyproject_line) != 1:
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge pyproject delta differs"
        )
    historical_pyproject_raw = pyproject_raw.replace(pyproject_line, b"", 1)
    if not _semantic_isolation_strict_equal(
        _semantic_isolation_dependency_bridge_manifest_identity(
            "pyproject.toml",
            historical_pyproject_raw,
        ),
        historical_manifests["pyproject.toml"],
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge pyproject ancestry differs"
        )
    current_pyproject = _semantic_isolation_parse_dependency_bridge_toml(
        pyproject_raw,
        label="current pyproject",
    )
    historical_pyproject = _semantic_isolation_parse_dependency_bridge_toml(
        historical_pyproject_raw,
        label="historical pyproject",
    )
    normalized_pyproject = _semantic_isolation_parse_dependency_bridge_toml(
        pyproject_raw,
        label="normalized pyproject",
    )
    try:
        current_dev = current_pyproject["project"]["optional-dependencies"]["dev"]
        normalized_dev = normalized_pyproject["project"][
            "optional-dependencies"
        ]["dev"]
        historical_dev = historical_pyproject["project"][
            "optional-dependencies"
        ]["dev"]
        current_production = current_pyproject["project"]["dependencies"]
        historical_production = historical_pyproject["project"]["dependencies"]
    except (KeyError, TypeError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge pyproject structure differs"
        ) from exc
    allowed_requirement = bridge["pyproject_semantic"]["allowed_dev_requirement"]
    if (
        not isinstance(current_dev, list)
        or not isinstance(normalized_dev, list)
        or not isinstance(historical_dev, list)
        or current_dev.count(allowed_requirement) != 1
        or normalized_dev.count(allowed_requirement) != 1
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge pyproject requirement differs"
        )
    normalized_dev.remove(allowed_requirement)
    if (
        not _semantic_isolation_strict_equal(
            normalized_pyproject,
            historical_pyproject,
        )
        or not _semantic_isolation_strict_equal(
            normalized_dev,
            historical_dev,
        )
        or not _semantic_isolation_strict_equal(
            current_production,
            historical_production,
        )
        or _semantic_isolation_dependency_bridge_toml_sha256(current_pyproject)
        != bridge["pyproject_semantic"]["current_toml_semantic_sha256"]
        or _semantic_isolation_dependency_bridge_toml_sha256(historical_pyproject)
        != bridge["pyproject_semantic"]["historical_toml_semantic_sha256"]
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge pyproject semantics differ"
        )

    lock_raw = manifest_bytes["uv.lock"]
    current_lock_dev_block = (
        _SEMANTIC_ISOLATION_DEPENDENCY_BRIDGE_LOCK_DEV_BLOCK
    )
    historical_lock_dev_block = (
        _SEMANTIC_ISOLATION_DEPENDENCY_BRIDGE_HISTORICAL_LOCK_DEV_BLOCK
    )
    lock_metadata_line = (
        _SEMANTIC_ISOLATION_DEPENDENCY_BRIDGE_LOCK_METADATA_LINE
    )
    if (
        lock_raw.count(current_lock_dev_block) != 1
        or lock_raw.count(lock_metadata_line) != 1
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge lock delta differs"
        )
    historical_lock_raw = lock_raw.replace(
        current_lock_dev_block,
        historical_lock_dev_block,
        1,
    ).replace(lock_metadata_line, b"", 1)
    if not _semantic_isolation_strict_equal(
        _semantic_isolation_dependency_bridge_manifest_identity(
            "uv.lock",
            historical_lock_raw,
        ),
        historical_manifests["uv.lock"],
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge lock ancestry differs"
        )
    current_lock = _semantic_isolation_parse_dependency_bridge_toml(
        lock_raw,
        label="current lock",
    )
    historical_lock = _semantic_isolation_parse_dependency_bridge_toml(
        historical_lock_raw,
        label="historical lock",
    )
    normalized_lock = _semantic_isolation_parse_dependency_bridge_toml(
        lock_raw,
        label="normalized lock",
    )
    allowed_lock_records = bridge["uv_lock_semantic"]["allowed_root_records"]
    normalized_root = _semantic_isolation_dependency_bridge_package(
        normalized_lock,
        "document-parse-api",
    )
    current_root = _semantic_isolation_dependency_bridge_package(
        current_lock,
        "document-parse-api",
    )
    historical_root = _semantic_isolation_dependency_bridge_package(
        historical_lock,
        "document-parse-api",
    )
    try:
        normalized_lock_dev = normalized_root["optional-dependencies"]["dev"]
        normalized_lock_requires = normalized_root["metadata"]["requires-dist"]
        current_lock_requires = current_root["metadata"]["requires-dist"]
        historical_lock_requires = historical_root["metadata"]["requires-dist"]
    except (KeyError, TypeError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge lock structure differs"
        ) from exc
    allowed_lock_dev = allowed_lock_records[0]["record"]
    allowed_lock_metadata = allowed_lock_records[1]["record"]
    if (
        not isinstance(normalized_lock_dev, list)
        or not isinstance(normalized_lock_requires, list)
        or normalized_lock_dev.count(allowed_lock_dev) != 1
        or normalized_lock_requires.count(allowed_lock_metadata) != 1
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge lock record differs"
        )
    normalized_lock_dev.remove(allowed_lock_dev)
    normalized_lock_requires.remove(allowed_lock_metadata)
    if not _semantic_isolation_strict_equal(normalized_lock, historical_lock):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge lock semantics differ"
        )

    packages = current_lock.get("package")
    if (
        not isinstance(packages, list)
        or len(packages) != bridge["uv_lock_semantic"]["package_count"]
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge package count differs"
        )
    package_artifacts: list[dict[str, Any]] = []
    for package in packages:
        if not isinstance(package, Mapping):
            raise readiness.ReadinessContractError(
                "semantic-isolation dependency custody bridge package record differs"
            )
        package_artifacts.append(
            {
                key: package[key]
                for key in ("name", "version", "source", "sdist", "wheels")
                if key in package
            }
        )
    package_artifacts.sort(
        key=lambda record: (
            record.get("name", ""),
            record.get("version", ""),
            _canonical_json(record.get("source", {})),
        )
    )
    current_root_production = {
        "dependencies": current_root.get("dependencies"),
        "requires_dist": [
            record
            for record in current_lock_requires
            if "extra == 'dev'" not in str(record.get("marker", ""))
        ],
    }
    historical_root_production = {
        "dependencies": historical_root.get("dependencies"),
        "requires_dist": [
            record
            for record in historical_lock_requires
            if "extra == 'dev'" not in str(record.get("marker", ""))
        ],
    }
    psutil_package = _semantic_isolation_dependency_bridge_package(
        current_lock,
        "psutil",
    )
    accelerate_package = _semantic_isolation_dependency_bridge_package(
        current_lock,
        "accelerate",
    )
    parent = bridge["uv_lock_semantic"]["preexisting_transitive_parent"]
    if (
        _semantic_isolation_dependency_bridge_toml_sha256(current_lock)
        != bridge["uv_lock_semantic"]["current_toml_semantic_sha256"]
        or _semantic_isolation_dependency_bridge_toml_sha256(historical_lock)
        != bridge["uv_lock_semantic"]["historical_toml_semantic_sha256"]
        or metrics._sha256_json(package_artifacts)
        != bridge["uv_lock_semantic"]["package_artifact_projection_sha256"]
        or not _semantic_isolation_strict_equal(
            current_root_production,
            historical_root_production,
        )
        or metrics._sha256_json(current_root_production)
        != bridge["uv_lock_semantic"][
            "root_production_dependency_projection_sha256"
        ]
        or metrics._sha256_json(psutil_package)
        != bridge["uv_lock_semantic"]["psutil_artifact_sha256"]
        or accelerate_package.get("version") != parent["version"]
        or parent["dependency_record"]
        not in accelerate_package.get("dependencies", [])
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge resolution differs"
        )

    app_root = root / "app"
    if not app_root.is_dir() or app_root.is_symlink():
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge app root differs"
        )
    app_entry_count = 0
    direct_app_imports: list[str] = []
    for entry in app_root.rglob("*"):
        app_entry_count += 1
        if app_entry_count > _SEMANTIC_ISOLATION_RUNTIME_ENTRY_LIMIT:
            raise readiness.ReadinessContractError(
                "semantic-isolation dependency custody bridge app resource differs"
            )
        if entry.is_symlink():
            raise readiness.ReadinessContractError(
                "semantic-isolation dependency custody bridge app binding differs"
            )
        if not entry.is_file() or entry.suffix != ".py" or "__pycache__" in entry.parts:
            continue
        path = entry.relative_to(root).as_posix()
        label = "semantic-isolation dependency custody bridge app source"
        raw, binding = _read_bound_file(
            root,
            path,
            maximum_bytes=2 * 1024 * 1024,
            label=label,
        )
        try:
            tree = ast.parse(raw, filename=path)
        except (SyntaxError, ValueError) as exc:
            raise readiness.ReadinessContractError(
                "semantic-isolation dependency custody bridge app syntax differs"
            ) from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                direct_app_imports.extend(
                    path
                    for alias in node.names
                    if alias.name.partition(".")[0] == "psutil"
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.partition(".")[0] == "psutil"
            ):
                direct_app_imports.append(path)
        tracks.append((path, 2 * 1024 * 1024, label, raw, binding))
    if direct_app_imports != bridge["runtime_import_policy"][
        "direct_app_psutil_imports"
    ]:
        raise readiness.ReadinessContractError(
            "semantic-isolation dependency custody bridge app import differs"
        )
    return tracks


def _semantic_isolation_collect_us01_gate_input_identities(
    root: Path,
) -> dict[str, dict[str, Any]]:
    try:
        paths = table_metrics.required_final_code_paths(root)
    except (OSError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 gate-input discovery differs"
        ) from exc
    paths = tuple(
        sorted(
            set(paths)
            | _semantic_isolation_discover_additional_us01_gate_inputs(root)
        )
    )
    if not paths or len(paths) > _SEMANTIC_ISOLATION_US01_MAXIMUM_GATE_INPUTS:
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 gate-input count differs"
        )
    identities: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for path in paths:
        raw, _ = _read_bound_file(
            root,
            path,
            maximum_bytes=_SEMANTIC_ISOLATION_US01_MAXIMUM_GATE_INPUT_BYTES,
            label="semantic-isolation P04-US01 gate input",
        )
        total_bytes += len(raw)
        if total_bytes > _SEMANTIC_ISOLATION_US01_MAXIMUM_TOTAL_GATE_INPUT_BYTES:
            raise readiness.ReadinessContractError(
                "semantic-isolation P04-US01 gate-input byte bound differs"
            )
        identities[path] = _semantic_isolation_file_identity(path, raw)
    return dict(sorted(identities.items()))


def _semantic_isolation_discover_additional_us01_gate_inputs(
    root: Path,
) -> set[str]:
    paths: set[str] = set()
    for base in (
        root / "tests/fixtures/phase_04/tables",
        root / "tracker/phase-04-tables/decisions",
    ):
        if not base.is_dir():
            raise readiness.ReadinessContractError(
                "semantic-isolation P04-US01 gate-input root differs"
            )
        for candidate in base.rglob("*"):
            relative = candidate.relative_to(root).as_posix()
            relative_parts = PurePosixPath(relative).parts
            if (
                candidate.is_file()
                and "__pycache__" not in relative_parts
                and candidate.suffix not in {".pyc", ".pyo"}
                and candidate.name != ".DS_Store"
                and not {".pytest_cache", ".ruff_cache"} & set(relative_parts)
            ):
                paths.add(relative)
    for pattern in (
        "frontend/tests/p04-us01-*.test.mts",
        "tests/contract/test_p04_us01_*.py",
        "tests/performance/test_p04_us01_*.py",
        "tests/regression/phase_04/test_p04_us01_*.py",
        "tests/stories/phase_04/test_p04_us01_*.py",
    ):
        for candidate in root.glob(pattern):
            if not candidate.is_file():
                raise readiness.ReadinessContractError(
                    "semantic-isolation P04-US01 test input differs"
                )
            paths.add(candidate.relative_to(root).as_posix())
    for path in (
        "tracker/phase-04-tables/README.md",
        "tracker/phase-04-tables/backlog.md",
        "tracker/phase-04-tables/metrics.md",
        "tracker/phase-04-tables/phase-regression.md",
        "tracker/phase-04-tables/stories/P04-US01.md",
    ):
        if not (root / path).is_file():
            raise readiness.ReadinessContractError(
                "semantic-isolation P04-US01 tracker input differs"
            )
        paths.add(path)
    return paths


def _semantic_isolation_validate_us01_gate_inputs(
    root: Path,
    identities: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, int, str, bytes, Any]]:
    if (
        not isinstance(identities, Mapping)
        or not identities
        or len(identities) > _SEMANTIC_ISOLATION_US01_MAXIMUM_GATE_INPUTS
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 gate-input manifest differs"
        )
    tracks: list[tuple[str, int, str, bytes, Any]] = []
    total_bytes = 0
    for path in sorted(identities):
        identity = identities[path]
        if (
            not isinstance(path, str)
            or str(PurePosixPath(path)) != path
            or ".." in PurePosixPath(path).parts
            or not isinstance(identity, Mapping)
            or identity.get("path") != path
        ):
            raise readiness.ReadinessContractError(
                "semantic-isolation P04-US01 gate-input identity differs"
            )
        track = _semantic_isolation_validate_identity_file(
            root,
            identity,
            label="semantic-isolation P04-US01 gate input",
            maximum_bytes=_SEMANTIC_ISOLATION_US01_MAXIMUM_GATE_INPUT_BYTES,
        )
        total_bytes += len(track[3])
        if total_bytes > _SEMANTIC_ISOLATION_US01_MAXIMUM_TOTAL_GATE_INPUT_BYTES:
            raise readiness.ReadinessContractError(
                "semantic-isolation P04-US01 gate-input byte bound differs"
            )
        tracks.append(track)
    return tracks


def _semantic_isolation_validate_command_tool(argv: list[str]) -> None:
    executable = PurePosixPath(argv[0]).name
    if re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable):
        valid = (
            len(argv) >= 3
            and argv[1] == "-m"
            and argv[2] in {"compileall", "pip", "py_compile", "pytest"}
        ) or (
            len(argv) >= 2
            and argv[1].startswith("tests/")
            and argv[1].endswith(".py")
        )
    elif executable == "pytest":
        valid = any(
            value.startswith("tests/") or value == "tests"
            for value in argv[1:]
        )
    elif executable == "npm":
        valid = len(argv) >= 2 and argv[1] in {"run", "test"}
    elif executable == "node":
        valid = "--test" in argv[1:]
    elif executable == "uv":
        valid = len(argv) >= 3 and argv[1:3] in (
            ["lock", "--check"],
            ["sync", "--locked"],
        )
    else:
        valid = False
    if not valid:
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 command tool differs"
        )


def _semantic_isolation_validate_count_reasons(
    reasons: Any,
    *,
    expected_count: int,
    label: str,
) -> None:
    if not isinstance(reasons, list) or len(reasons) > 64:
        raise readiness.ReadinessContractError(f"{label} differ")
    total = 0
    observed: set[str] = set()
    for reason in reasons:
        record = _exact_keys(
            reason,
            frozenset({"count", "reason"}),
            label,
        )
        count = record["count"]
        text = record["reason"]
        if (
            type(count) is not int
            or count <= 0
            or not isinstance(text, str)
            or not text.strip()
            or len(text.encode("utf-8")) > 1_024
            or text in observed
        ):
            raise readiness.ReadinessContractError(f"{label} differ")
        observed.add(text)
        total += count
    if total != expected_count:
        raise readiness.ReadinessContractError(f"{label} differ")


def _semantic_isolation_validate_us01_artifact_budget(
    gates: Mapping[str, Any],
) -> None:
    observed: dict[str, Mapping[str, Any]] = {}
    total_bytes = 0
    for category in _SEMANTIC_ISOLATION_US01_GATE_CATEGORIES:
        record = gates[category]
        artifacts = (
            record.get("artifact_identities")
            if isinstance(record, Mapping)
            else None
        )
        if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 32:
            raise readiness.ReadinessContractError(
                f"semantic-isolation P04-US01 {category} artifacts differ"
            )
        for identity in artifacts:
            path = identity.get("path") if isinstance(identity, Mapping) else None
            size_bytes = (
                identity.get("size_bytes")
                if isinstance(identity, Mapping)
                else None
            )
            if (
                not isinstance(path, str)
                or str(PurePosixPath(path)) != path
                or ".." in PurePosixPath(path).parts
                or not path.startswith(
                    f"{SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT}/"
                )
                or type(size_bytes) is not int
                or size_bytes <= 0
                or size_bytes
                > _SEMANTIC_ISOLATION_US01_MAXIMUM_ARTIFACT_BYTES
            ):
                raise readiness.ReadinessContractError(
                    "semantic-isolation P04-US01 artifact resource bound differs"
                )
            prior = observed.get(path)
            if prior is not None:
                if prior != identity:
                    raise readiness.ReadinessContractError(
                        "semantic-isolation P04-US01 reused artifact differs"
                    )
                continue
            observed[path] = identity
            total_bytes += size_bytes
            if (
                len(observed)
                > _SEMANTIC_ISOLATION_US01_MAXIMUM_UNIQUE_ARTIFACTS
                or total_bytes
                > _SEMANTIC_ISOLATION_US01_MAXIMUM_TOTAL_ARTIFACT_BYTES
            ):
                raise readiness.ReadinessContractError(
                    "semantic-isolation P04-US01 aggregate artifact bound differs"
                )


def _semantic_isolation_validate_us01_gate_results(
    category: str,
    results: Any,
    *,
    expected_dependency_custody: Mapping[str, Any],
) -> None:
    expected_keys = _SEMANTIC_ISOLATION_US01_GATE_RESULT_KEYS[category]
    values = _exact_keys(
        results,
        expected_keys,
        f"semantic-isolation P04-US01 {category} results",
    )
    if category == "product_correctness_quality":
        valid = (
            values["correctness_passed"] is True
            and values["quality_passed"] is True
            and type(values["reviewed_real_document_count"]) is int
            and values["reviewed_real_document_count"]
            == len(_SEMANTIC_ISOLATION_US01_QUALITY_CASES)
            and values["reviewed_real_document_ids"]
            == list(_SEMANTIC_ISOLATION_US01_QUALITY_CASES)
            and values["oracle_semantic_sha256"]
            == _SEMANTIC_ISOLATION_US01_ORACLE_SEMANTIC_SHA256
            and values["synthetic_controls_passed"] is True
        )
    elif category == "production_security":
        valid = (
            values["fail_closed_passed"] is True
            and values["malformed_input_passed"] is True
            and values["security_passed"] is True
            and values["hosted_requests"] == 0
            and type(values["hosted_requests"]) is int
            and values["hosted_tokens"] == 0
            and type(values["hosted_tokens"]) is int
            and values["hosted_cost_usd"] == 0
            and type(values["hosted_cost_usd"]) in {int, float}
        )
    elif category == "resource_timeout_output":
        valid = all(values[field] is True for field in expected_keys)
    elif category == "api_schema_serializer_compatibility":
        valid = all(values[field] is True for field in expected_keys)
    elif category == "frontend_compatibility":
        valid = all(
            values[field] is True
            for field in expected_keys
            if field not in {"responsive_check_count", "unit_test_count"}
        ) and (
            type(values["responsive_check_count"]) is int
            and values["responsive_check_count"] >= 22
            and type(values["unit_test_count"]) is int
            and values["unit_test_count"] >= 105
        )
    elif category == "paired_latency_rss":
        case_results = values["case_results"]
        valid = (
            values["phase04_pair_count"] == 5
            and type(values["phase04_pair_count"]) is int
            and values["phase04_table_stage_latency_passed"] is True
            and values["phase04_peak_rss_passed"] is True
            and _semantic_isolation_strict_equal(
                values["p03_attempt48_exception"],
                {
                "attempt_status": "FAILED",
                "canonical_strict_final_artifact_present": False,
                "maximum_candidate_specific_bound": 0.05,
                "metric": "latency_p95_seconds",
                "observed_seconds": 0.050946750,
                "overrun_fraction": 0.018935,
                "overrun_seconds": 0.000946750,
                "stage": "running_region_projection",
                "strict_ceiling_seconds": 0.05,
                "target_id": "ny-timetable",
                },
            )
            and _semantic_isolation_strict_equal(
                values["p03_regression_gates"],
                {
                "active_exception_gate_passed": True,
                "paired_parser_latency_regression_passed": True,
                "source_extraction_latency_regression_passed": True,
                "uber_projection_latency_regression_passed": True,
                },
            )
            and isinstance(case_results, Mapping)
            and set(case_results) == _SEMANTIC_ISOLATION_US01_PERFORMANCE_CASES
        )
        if valid:
            case_fields = frozenset(
                {
                    "phase04_peak_rss_ceiling_bytes",
                    "phase04_peak_rss_delta_bytes",
                    "phase04_table_stage_latency_ceiling_ratio",
                    "phase04_table_stage_p50_overhead_ratio",
                    "phase04_table_stage_p95_overhead_ratio",
                    "within_phase04_peak_rss_ceiling",
                    "within_phase04_table_stage_latency_ceiling",
                }
            )
            for case in _SEMANTIC_ISOLATION_US01_PERFORMANCE_CASES:
                record = _exact_keys(
                    case_results[case],
                    case_fields,
                    "semantic-isolation P04-US01 paired case result",
                )
                p50 = _strict_finite_number(
                    record["phase04_table_stage_p50_overhead_ratio"],
                    "semantic-isolation P04-US01 p50 ratio",
                )
                p95 = _strict_finite_number(
                    record["phase04_table_stage_p95_overhead_ratio"],
                    "semantic-isolation P04-US01 p95 ratio",
                )
                latency_ceiling = _strict_finite_number(
                    record["phase04_table_stage_latency_ceiling_ratio"],
                    "semantic-isolation P04-US01 latency ceiling",
                )
                rss_delta = record["phase04_peak_rss_delta_bytes"]
                rss_ceiling = record["phase04_peak_rss_ceiling_bytes"]
                if (
                    p50 < 0
                    or p95 < 0
                    or p50 > p95
                    or latency_ceiling != 0.10
                    or p50 > latency_ceiling
                    or p95 > latency_ceiling
                    or type(rss_delta) is not int
                    or rss_delta < 0
                    or type(rss_ceiling) is not int
                    or rss_ceiling != 67_108_864
                    or rss_delta > rss_ceiling
                    or record[
                        "within_phase04_table_stage_latency_ceiling"
                    ]
                    is not True
                    or record["within_phase04_peak_rss_ceiling"] is not True
                ):
                    valid = False
                    break
    elif category == "rollback_default_off":
        valid = (
            values["default_off_passed"] is True
            and values["rollback_passed"] is True
            and values["running_region_default_off_passed"] is True
            and _semantic_isolation_strict_equal(
                values["phase04_flags"],
                {
                    name: False
                    for name in EXPECTED_HARDENED_PHASE04_SETTING_ORDER
                },
            )
        )
    else:
        valid = (
            values["code_custody_passed"] is True
            and values["dependency_changes_observed"] is False
            and values["dependency_integrity_passed"] is True
            and values["input_and_fixture_custody_passed"] is True
            and values["dependency_custody_sha256"]
            == metrics._sha256_json(expected_dependency_custody)
        )
    if not valid:
        raise readiness.ReadinessContractError(
            f"semantic-isolation P04-US01 {category} results differ"
        )


def _semantic_isolation_validate_us01_story_gate(
    root: Path,
    gate: Mapping[str, Any],
    *,
    expected_dependency_custody: Mapping[str, Any],
    expected_production_code: Mapping[str, Mapping[str, Any]],
    expected_status_owners: Mapping[str, Mapping[str, Any]],
    expected_us01_gate_inputs: Mapping[str, Mapping[str, Any]],
    today: date | None,
) -> list[tuple[str, int, str, bytes, Any]]:
    _exact_keys(
        gate,
        frozenset(
            {
                "artifact_manifest_sha256",
                "environment",
                "gates",
                "generated_on",
                "phase05_authorized",
                "production_use_authorized",
                "record_kind",
                "renewal_id",
                "schema_version",
                "semantic_sha256",
                "status",
                "story_id",
            }
        ),
        "semantic-isolation P04-US01 story gate",
    )
    if not _semantic_isolation_strict_equal(
        {
            field: gate[field]
            for field in (
            "schema_version",
            "record_kind",
            "story_id",
            "renewal_id",
            "status",
            "production_use_authorized",
            "phase05_authorized",
            )
        },
        {
            "schema_version": "1.0",
            "record_kind": "p04_us01_final_code_gate_execution",
            "story_id": "P04-US01",
            "renewal_id": (
                "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260805-"
                "PHASE04-TABLES-SEMANTIC-ISOLATION"
            ),
            "status": "PASS",
            "production_use_authorized": False,
            "phase05_authorized": False,
        },
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 story gate state differs"
        )
    try:
        generated_on = date.fromisoformat(gate["generated_on"])
    except (TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 story gate date differs"
        ) from exc
    if (
        generated_on < _SEMANTIC_ISOLATION_AUTHORIZED_ON
        or generated_on > _SEMANTIC_ISOLATION_REVIEW_DUE_ON
        or generated_on > (today or datetime.now(tz=UTC).date())
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 story gate date differs"
        )
    if not _semantic_isolation_strict_equal(gate["environment"], {
        "dependency_custody_sha256": metrics._sha256_json(
            expected_dependency_custody
        ),
        "offline_environment": dict(metrics.OFFLINE_ENVIRONMENT),
        "phase04_flags": {
            name: False for name in EXPECTED_HARDENED_PHASE04_SETTING_ORDER
        },
        "production_code_manifest_sha256": metrics._sha256_json(
            expected_production_code
        ),
        "status_owner_manifest_sha256": metrics._sha256_json(
            expected_status_owners
        ),
        "us01_gate_input_identities": expected_us01_gate_inputs,
        "us01_gate_input_manifest_sha256": metrics._sha256_json(
            expected_us01_gate_inputs
        ),
    }):
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 story gate environment differs"
        )
    gate_input_tracks = _semantic_isolation_validate_us01_gate_inputs(
        root,
        expected_us01_gate_inputs,
    )
    gates = _exact_keys(
        gate["gates"],
        frozenset(_SEMANTIC_ISOLATION_US01_GATE_CATEGORIES),
        "semantic-isolation P04-US01 gate categories",
    )
    _semantic_isolation_validate_us01_artifact_budget(gates)
    identity_manifest: dict[str, list[Mapping[str, Any]]] = {}
    observed_identities: dict[str, Mapping[str, Any]] = {}
    total_artifact_bytes = 0
    tracks: list[tuple[str, int, str, bytes, Any]] = list(gate_input_tracks)
    for category in _SEMANTIC_ISOLATION_US01_GATE_CATEGORIES:
        record = _exact_keys(
            gates[category],
            frozenset(
                {
                    "artifact_identities",
                    "commands",
                    "findings",
                    "result",
                    "results",
                }
            ),
            f"semantic-isolation P04-US01 {category} gate",
        )
        if record["result"] != "PASS":
            raise readiness.ReadinessContractError(
                f"semantic-isolation P04-US01 {category} gate differs"
            )
        artifacts = record["artifact_identities"]
        if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 32:
            raise readiness.ReadinessContractError(
                f"semantic-isolation P04-US01 {category} artifacts differ"
            )
        category_paths: set[str] = set()
        identity_manifest[category] = []
        for identity in artifacts:
            if not isinstance(identity, Mapping):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation P04-US01 {category} artifact differs"
                )
            path = identity.get("path")
            if (
                not isinstance(path, str)
                or path in category_paths
                or str(PurePosixPath(path)) != path
                or ".." in PurePosixPath(path).parts
                or not path.startswith(
                    f"{SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT}/"
                )
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation P04-US01 {category} artifact differs"
                )
            category_paths.add(path)
            identity_manifest[category].append(dict(identity))
            prior = observed_identities.get(path)
            if prior is not None:
                if prior != identity:
                    raise readiness.ReadinessContractError(
                        "semantic-isolation P04-US01 reused artifact differs"
                    )
                continue
            size_bytes = identity.get("size_bytes")
            if (
                type(size_bytes) is not int
                or size_bytes <= 0
                or size_bytes
                > _SEMANTIC_ISOLATION_US01_MAXIMUM_ARTIFACT_BYTES
                or len(observed_identities)
                >= _SEMANTIC_ISOLATION_US01_MAXIMUM_UNIQUE_ARTIFACTS
                or total_artifact_bytes + size_bytes
                > _SEMANTIC_ISOLATION_US01_MAXIMUM_TOTAL_ARTIFACT_BYTES
            ):
                raise readiness.ReadinessContractError(
                    "semantic-isolation P04-US01 artifact resource bound differs"
                )
            track = _semantic_isolation_validate_identity_file(
                root,
                identity,
                label=f"semantic-isolation P04-US01 {category} artifact",
                maximum_bytes=_SEMANTIC_ISOLATION_US01_MAXIMUM_ARTIFACT_BYTES,
            )
            observed_identities[path] = dict(identity)
            total_artifact_bytes += size_bytes
            tracks.append(track)
        commands = record["commands"]
        if not isinstance(commands, list) or not 1 <= len(commands) <= 32:
            raise readiness.ReadinessContractError(
                f"semantic-isolation P04-US01 {category} commands differ"
            )
        observed_coverage: set[str] = set()
        for command in commands:
            _exact_keys(
                command,
                frozenset(
                    {
                        "argv",
                        "coverage_tags",
                        "documented_skips",
                        "documented_warnings",
                        "exit_code",
                        "output_artifact_identity",
                        "output_sha256",
                        "passed",
                        "skipped",
                        "warnings",
                    }
                ),
                f"semantic-isolation P04-US01 {category} command",
            )
            argv = command["argv"]
            coverage_tags = command["coverage_tags"]
            counts = tuple(
                command[field]
                for field in ("passed", "skipped", "warnings")
            )
            if (
                not isinstance(argv, list)
                or not 1 <= len(argv) <= 64
                or any(
                    not isinstance(value, str)
                    or not value
                    or len(value.encode("utf-8")) > 4_096
                    for value in argv
                )
                or command["exit_code"] != 0
                or type(command["exit_code"]) is not int
                or any(type(value) is not int or value < 0 for value in counts)
                or not isinstance(command["output_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", command["output_sha256"])
                is None
                or not isinstance(coverage_tags, list)
                or not 1 <= len(coverage_tags) <= 32
                or any(
                    not isinstance(tag, str) or not tag
                    for tag in coverage_tags
                )
                or len(set(coverage_tags)) != len(coverage_tags)
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation P04-US01 {category} command differs"
                )
            observed_coverage.update(coverage_tags)
            _semantic_isolation_validate_command_tool(argv)
            output_identity = command["output_artifact_identity"]
            output_path = (
                output_identity.get("path")
                if isinstance(output_identity, Mapping)
                else None
            )
            if (
                not isinstance(output_path, str)
                or output_path not in category_paths
                or observed_identities.get(output_path) != output_identity
                or command["output_sha256"]
                != output_identity.get("raw_sha256")
            ):
                raise readiness.ReadinessContractError(
                    f"semantic-isolation P04-US01 {category} command output differs"
                )
            _semantic_isolation_validate_count_reasons(
                command["documented_skips"],
                expected_count=command["skipped"],
                label=f"semantic-isolation P04-US01 {category} command skips",
            )
            _semantic_isolation_validate_count_reasons(
                command["documented_warnings"],
                expected_count=command["warnings"],
                label=f"semantic-isolation P04-US01 {category} command warnings",
            )
        if sum(command["passed"] for command in commands) <= 0:
            raise readiness.ReadinessContractError(
                f"semantic-isolation P04-US01 {category} command coverage differs"
            )
        if observed_coverage != _SEMANTIC_ISOLATION_US01_COMMAND_COVERAGE[
            category
        ]:
            raise readiness.ReadinessContractError(
                f"semantic-isolation P04-US01 {category} command coverage differs"
            )
        findings = _exact_keys(
            record["findings"],
            frozenset(_SEMANTIC_ISOLATION_FINDING_FIELDS),
            f"semantic-isolation P04-US01 {category} findings",
        )
        if any(
            findings[field] != []
            for field in _SEMANTIC_ISOLATION_FINDING_FIELDS
        ):
            raise readiness.ReadinessContractError(
                f"semantic-isolation P04-US01 {category} findings differ"
            )
        _semantic_isolation_validate_us01_gate_results(
            category,
            record["results"],
            expected_dependency_custody=expected_dependency_custody,
        )
    if gate["artifact_manifest_sha256"] != metrics._sha256_json(
        identity_manifest
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 artifact manifest differs"
        )
    if gate["semantic_sha256"] != waiver_semantic_sha256(gate):
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 story gate digest differs"
        )
    return tracks


def _semantic_isolation_validate_focused_gate_execution(
    execution: Mapping[str, Any],
    *,
    expected_dependency_custody: Mapping[str, Any],
    expected_production_code: Mapping[str, Mapping[str, Any]],
    expected_status_owners: Mapping[str, Mapping[str, Any]],
    today: date | None,
) -> None:
    _exact_keys(
        execution,
        frozenset(
            {
                "commands",
                "environment",
                "executed_on",
                "findings",
                "record_kind",
                "renewal_id",
                "schema_version",
                "semantic_sha256",
                "status",
            }
        ),
        "semantic-isolation focused gate execution",
    )
    if {
        field: execution[field]
        for field in (
            "schema_version",
            "record_kind",
            "renewal_id",
            "status",
        )
    } != {
        "schema_version": "1.0",
        "record_kind": (
            "p03_us08_phase04_tables_semantic_isolation_focused_gate"
        ),
        "renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260805-"
            "PHASE04-TABLES-SEMANTIC-ISOLATION"
        ),
        "status": "PASS",
    }:
        raise readiness.ReadinessContractError(
            "semantic-isolation focused gate state differs"
        )
    try:
        executed_on = date.fromisoformat(execution["executed_on"])
    except (TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation focused gate date differs"
        ) from exc
    if (
        executed_on < _SEMANTIC_ISOLATION_AUTHORIZED_ON
        or executed_on > _SEMANTIC_ISOLATION_REVIEW_DUE_ON
        or executed_on > (today or datetime.now(tz=UTC).date())
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation focused gate date differs"
        )
    commands = execution["commands"]
    if not isinstance(commands, list) or len(commands) != len(
        _SEMANTIC_ISOLATION_FOCUSED_COMMANDS
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation focused gate commands differ"
        )
    for index, (result, expected_argv) in enumerate(
        zip(commands, _SEMANTIC_ISOLATION_FOCUSED_COMMANDS, strict=True)
    ):
        _exact_keys(
            result,
            frozenset(
                {
                    "argv",
                    "exit_code",
                    "output_sha256",
                    "passed",
                    "skipped",
                    "warnings",
                }
            ),
            "semantic-isolation focused gate command",
        )
        counts = tuple(
            result[field] for field in ("passed", "skipped", "warnings")
        )
        if (
            result["argv"] != list(expected_argv)
            or type(result["exit_code"]) is not int
            or result["exit_code"] != 0
            or any(type(value) is not int or value < 0 for value in counts)
            or (index == 0 and counts != (0, 0, 0))
            or (index == 1 and result["passed"] <= 0)
            or not isinstance(result["output_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", result["output_sha256"])
            is None
        ):
            raise readiness.ReadinessContractError(
                "semantic-isolation focused gate command result differs"
            )
    if not _semantic_isolation_strict_equal(execution["environment"], {
        "dependency_custody_sha256": metrics._sha256_json(
            expected_dependency_custody
        ),
        "offline_environment": dict(metrics.OFFLINE_ENVIRONMENT),
        "phase04_flags": {
            name: False for name in EXPECTED_HARDENED_PHASE04_SETTING_ORDER
        },
        "production_code_manifest_sha256": metrics._sha256_json(
            expected_production_code
        ),
        "status_owner_manifest_sha256": metrics._sha256_json(
            expected_status_owners
        ),
    }):
        raise readiness.ReadinessContractError(
            "semantic-isolation focused gate environment differs"
        )
    findings = _exact_keys(
        execution["findings"],
        frozenset(_SEMANTIC_ISOLATION_FINDING_FIELDS),
        "semantic-isolation focused gate findings",
    )
    if any(findings[field] != [] for field in _SEMANTIC_ISOLATION_FINDING_FIELDS):
        raise readiness.ReadinessContractError(
            "semantic-isolation focused gate findings differ"
        )
    if execution["semantic_sha256"] != waiver_semantic_sha256(execution):
        raise readiness.ReadinessContractError(
            "semantic-isolation focused gate digest differs"
        )


def _semantic_isolation_validate_verification_state(
    verification: Mapping[str, Any],
    *,
    expected_upstream: Mapping[str, Any],
    expected_production_code: Mapping[str, Mapping[str, Any]],
    expected_dependency_custody: Mapping[str, Any],
    expected_protected_manifest_sha256: str,
    expected_protected_path_count: int,
    expected_status_owners: Mapping[str, Mapping[str, Any]],
    expected_us01_gate_inputs: Mapping[str, Mapping[str, Any]],
) -> None:
    _exact_keys(
        verification,
        frozenset(
            {
                "checks",
                "dependency_custody",
                "dependency_custody_sha256",
                "operative",
                "phase05_authorized",
                "production_code_identities",
                "production_code_manifest_sha256",
                "production_use_authorized",
                "protected_code_manifest_sha256",
                "protected_code_path_count",
                "record_kind",
                "renewal_id",
                "schema_version",
                "semantic_sha256",
                "status",
                "status_owner_identities",
                "status_owner_manifest_sha256",
                "upstream_identities",
                "us01_gate_input_identities",
                "us01_gate_input_manifest_sha256",
            }
        ),
        "semantic-isolation terminal verification",
    )
    if not _semantic_isolation_strict_equal(
        {
            field: verification[field]
            for field in (
            "schema_version",
            "record_kind",
            "renewal_id",
            "status",
            "operative",
            "production_use_authorized",
            "phase05_authorized",
            )
        },
        {
            "schema_version": "1.0",
            "record_kind": (
                "p03_us08_phase04_tables_semantic_isolation_verification"
            ),
            "renewal_id": (
                "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260805-"
                "PHASE04-TABLES-SEMANTIC-ISOLATION"
            ),
            "status": "VERIFIED_AWAITING_INDEPENDENT_APPROVAL",
            "operative": False,
            "production_use_authorized": False,
            "phase05_authorized": False,
        },
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal verification state differs"
        )
    if not _semantic_isolation_strict_equal(
        verification["upstream_identities"], expected_upstream
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal verification upstream differs"
        )
    if not _semantic_isolation_strict_equal(verification["checks"], {
        "all_nonwaived_gates_passed": True,
        "default_off_rollback_verified": True,
        "final_code_identified": True,
        "latency_observation_unchanged": True,
        "metrics_and_custody_review_required": True,
        "production_and_security_review_required": True,
        "p04_us01_gate_inputs_identified": True,
        "strict_final_artifact_present": False,
    }):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal verification checks differ"
        )
    if not _semantic_isolation_strict_equal(
        verification["production_code_identities"], expected_production_code
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal production identity differs"
        )
    if verification["production_code_manifest_sha256"] != metrics._sha256_json(
        expected_production_code
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal production manifest differs"
        )
    if (
        not _semantic_isolation_strict_equal(
            verification["dependency_custody"], expected_dependency_custody
        )
        or verification["dependency_custody_sha256"]
        != metrics._sha256_json(expected_dependency_custody)
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal dependency custody differs"
        )
    if (
        verification["protected_code_manifest_sha256"]
        != expected_protected_manifest_sha256
        or verification["protected_code_path_count"]
        != expected_protected_path_count
        or type(verification["protected_code_path_count"]) is not int
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal protected manifest differs"
        )
    if (
        not _semantic_isolation_strict_equal(
            verification["status_owner_identities"], expected_status_owners
        )
        or verification["status_owner_manifest_sha256"]
        != metrics._sha256_json(expected_status_owners)
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal status-owner identity differs"
        )
    if (
        not _semantic_isolation_strict_equal(
            verification["us01_gate_input_identities"],
            expected_us01_gate_inputs,
        )
        or verification["us01_gate_input_manifest_sha256"]
        != metrics._sha256_json(expected_us01_gate_inputs)
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal P04-US01 gate-input identity differs"
        )
    if (
        verification["semantic_sha256"]
        != waiver_semantic_sha256(verification)
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal verification digest differs"
        )


def _semantic_isolation_validate_review_artifact(
    review: Mapping[str, Any],
    *,
    expected_role: str,
    expected_upstream: Mapping[str, Any],
    focused_gate: Mapping[str, Any],
    us01_story_gate: Mapping[str, Any],
    us01_story_gate_identity: Mapping[str, Any],
    today: date | None,
) -> None:
    _exact_keys(
        review,
        frozenset(
            {
                "disposition",
                "evidence_reviewed",
                "findings",
                "focused_gate_commands_reviewed",
                "focused_gate_environment_reviewed",
                "independent",
                "record_kind",
                "review_role",
                "reviewed_on",
                "reviewer_id",
                "schema_version",
                "self_review",
                "semantic_sha256",
                "upstream_identities",
                "us01_gate_input_identities_reviewed",
                "us01_story_gate_identity_reviewed",
                "us01_story_gate_results_reviewed",
            }
        ),
        "semantic-isolation independent review artifact",
    )
    expected_evidence = {
        "production_security": [
            "compatibility",
            "correctness",
            "production_code",
            "resources",
            "rollback",
            "security",
        ],
        "metrics_custody": [
            "attempt_48_latency_observation",
            "custody",
            "failed_history",
            "hosted_usage",
            "latency",
            "metrics",
            "peak_rss",
        ],
    }
    try:
        reviewed_on = date.fromisoformat(review["reviewed_on"])
        story_gate_on = date.fromisoformat(us01_story_gate["generated_on"])
        focused_gate_on = date.fromisoformat(focused_gate["executed_on"])
    except (TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation independent review date differs"
        ) from exc
    reviewer_id = review["reviewer_id"]
    if (
        expected_role not in expected_evidence
        or review["schema_version"] != "1.0"
        or review["record_kind"]
        != "p03_us08_phase04_tables_semantic_isolation_independent_review"
        or review["review_role"] != expected_role
        or review["independent"] is not True
        or review["self_review"] is not False
        or review["disposition"] != "APPROVED"
        or not isinstance(reviewer_id, str)
        or re.fullmatch(r"[A-Za-z0-9._:@/-]{3,128}", reviewer_id) is None
        or reviewed_on < _SEMANTIC_ISOLATION_AUTHORIZED_ON
        or reviewed_on > _SEMANTIC_ISOLATION_REVIEW_DUE_ON
        or reviewed_on > (today or datetime.now(tz=UTC).date())
        or reviewed_on < story_gate_on
        or reviewed_on < focused_gate_on
        or not _semantic_isolation_strict_equal(
            review["upstream_identities"], expected_upstream
        )
        or review["evidence_reviewed"] != expected_evidence[expected_role]
        or not _semantic_isolation_strict_equal(
            review["focused_gate_commands_reviewed"],
            focused_gate["commands"],
        )
        or not _semantic_isolation_strict_equal(
            review["focused_gate_environment_reviewed"],
            focused_gate["environment"],
        )
        or not _semantic_isolation_strict_equal(
            review["us01_gate_input_identities_reviewed"],
            us01_story_gate["environment"]["us01_gate_input_identities"],
        )
        or not _semantic_isolation_strict_equal(
            review["us01_story_gate_identity_reviewed"],
            us01_story_gate_identity,
        )
        or not _semantic_isolation_strict_equal(
            review["us01_story_gate_results_reviewed"],
            us01_story_gate["gates"],
        )
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation independent review artifact differs"
        )
    findings = _exact_keys(
        review["findings"],
        frozenset(_SEMANTIC_ISOLATION_FINDING_FIELDS),
        "semantic-isolation independent review findings",
    )
    if any(findings[field] != [] for field in _SEMANTIC_ISOLATION_FINDING_FIELDS):
        raise readiness.ReadinessContractError(
            "semantic-isolation independent review findings differ"
        )
    if review["semantic_sha256"] != waiver_semantic_sha256(review):
        raise readiness.ReadinessContractError(
            "semantic-isolation independent review digest differs"
        )


def _semantic_isolation_validate_terminal_approval_state(
    approval: Mapping[str, Any] | None,
    *,
    expected_upstream: Mapping[str, Any],
    expected_review_identities: Mapping[str, Mapping[str, Any]],
    expected_reviewers: Mapping[str, str],
    expected_review_dates: Mapping[str, str],
    renewal: Mapping[str, Any],
    today: date | None,
) -> None:
    if approval is None:
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent approval is absent"
        )
    _exact_keys(
        approval,
        frozenset(
            {
                "approved_on",
                "operative",
                "phase05_authorized",
                "production_use_authorized",
                "record_kind",
                "renewal_id",
                "reviews",
                "schema_version",
                "scope_confirmation",
                "status",
                "upstream_identities",
            }
        ),
        "semantic-isolation terminal independent approval",
    )
    if not _semantic_isolation_strict_equal(
        {
            field: approval[field]
            for field in (
            "schema_version",
            "record_kind",
            "renewal_id",
            "status",
            "operative",
            "production_use_authorized",
            "phase05_authorized",
            )
        },
        {
            "schema_version": "1.0",
            "record_kind": (
                "p03_us08_phase04_tables_semantic_isolation_independent_approval"
            ),
            "renewal_id": renewal["renewal_id"],
            "status": "INDEPENDENTLY_APPROVED",
            "operative": True,
            "production_use_authorized": False,
            "phase05_authorized": False,
        },
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent approval state differs"
        )
    try:
        approved_on = date.fromisoformat(approval["approved_on"])
        review_due = date.fromisoformat(renewal["expiry"]["review_due_on"])
    except (TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent approval date differs"
        ) from exc
    if (
        approved_on < _SEMANTIC_ISOLATION_AUTHORIZED_ON
        or approved_on > _SEMANTIC_ISOLATION_REVIEW_DUE_ON
        or approved_on > review_due
        or approved_on > (today or datetime.now(tz=UTC).date())
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent approval date differs"
        )
    if set(expected_review_dates) != {
        "production_security",
        "metrics_custody",
    }:
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent review dates differ"
        )
    try:
        parsed_review_dates = {
            role: date.fromisoformat(value)
            for role, value in expected_review_dates.items()
        }
    except (TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent review dates differ"
        ) from exc
    if any(reviewed_on > approved_on for reviewed_on in parsed_review_dates.values()):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent approval chronology differs"
        )
    if not _semantic_isolation_strict_equal(
        approval["upstream_identities"], expected_upstream
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent approval upstream differs"
        )
    if not _semantic_isolation_strict_equal(approval["scope_confirmation"], {
        "exception_scope": renewal["exception_scope"],
        "expiry": renewal["expiry"],
        "not_waived": renewal["not_waived"],
        "operational_constraints": renewal["operational_constraints"],
        "phase05_authorized": False,
        "stories_in_dependency_order": renewal["closed_phase04_scope"][
            "stories_in_dependency_order"
        ],
        "strict_final_artifact_present": False,
    }):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent approval scope differs"
        )
    reviews = approval["reviews"]
    if not isinstance(reviews, list) or len(reviews) != 2:
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent reviews differ"
        )
    expected_evidence = {
        "production_security": [
            "compatibility",
            "correctness",
            "production_code",
            "resources",
            "rollback",
            "security",
        ],
        "metrics_custody": [
            "attempt_48_latency_observation",
            "custody",
            "failed_history",
            "hosted_usage",
            "latency",
            "metrics",
            "peak_rss",
        ],
    }
    reviewer_ids: set[str] = set()
    observed_roles: set[str] = set()
    finding_fields = (
        "blocking_findings",
        "compatibility_findings",
        "correctness_findings",
        "custody_findings",
        "major_findings",
        "performance_findings",
        "security_findings",
    )
    for review in reviews:
        _exact_keys(
            review,
            frozenset(
                {
                    "disposition",
                    "evidence_reviewed",
                    "independent",
                    "review_role",
                    "review_artifact_identity",
                    "reviewer_id",
                    "self_review",
                    *finding_fields,
                }
            ),
            "semantic-isolation terminal independent review",
        )
        reviewer_id = review["reviewer_id"]
        role = review["review_role"]
        if (
            not isinstance(reviewer_id, str)
            or re.fullmatch(r"[A-Za-z0-9._:@/-]{3,128}", reviewer_id) is None
            or reviewer_id in reviewer_ids
            or not isinstance(role, str)
            or role not in expected_evidence
            or role in observed_roles
            or review["independent"] is not True
            or review["self_review"] is not False
            or review["disposition"] != "APPROVED"
            or review["evidence_reviewed"] != expected_evidence[role]
            or not _semantic_isolation_strict_equal(
                review["review_artifact_identity"],
                expected_review_identities.get(role),
            )
            or reviewer_id != expected_reviewers.get(role)
            or any(review[field] != [] for field in finding_fields)
        ):
            raise readiness.ReadinessContractError(
                "semantic-isolation terminal independent review differs"
            )
        reviewer_ids.add(reviewer_id)
        observed_roles.add(role)
    if observed_roles != set(expected_evidence):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent reviews differ"
        )


def _validate_semantic_isolation_terminal_approval(
    root: Path,
    *,
    renewal: Mapping[str, Any],
    renewal_raw: bytes,
    current_code: Mapping[str, Mapping[str, Any]],
    current_dependency_custody: Mapping[str, Any],
    today: date | None,
) -> list[tuple[str, int, str, bytes, Any]]:
    tracks: list[tuple[str, int, str, bytes, Any]] = []
    guard_path = str(SEMANTIC_ISOLATION_GUARD_PATH)
    test_path = str(SEMANTIC_ISOLATION_FOCUSED_TEST_PATH)
    guard_raw, guard_binding = _read_bound_file(
        root,
        guard_path,
        maximum_bytes=2 * 1024 * 1024,
        label="semantic-isolation guard",
    )
    test_raw, test_binding = _read_bound_file(
        root,
        test_path,
        maximum_bytes=2 * 1024 * 1024,
        label="semantic-isolation focused test",
    )
    tracks.extend(
        (
            (
                guard_path,
                2 * 1024 * 1024,
                "semantic-isolation guard",
                guard_raw,
                guard_binding,
            ),
            (
                test_path,
                2 * 1024 * 1024,
                "semantic-isolation focused test",
                test_raw,
                test_binding,
            ),
        )
    )
    base_upstream = {
        "decision": renewal["decision_identity"],
        "focused_test": _semantic_isolation_file_identity(test_path, test_raw),
        "guard": _semantic_isolation_file_identity(guard_path, guard_raw),
        "renewal": {
            "path": str(SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH),
            "raw_sha256": hashlib.sha256(renewal_raw).hexdigest(),
            "semantic_sha256": renewal["semantic_sha256"],
            "size_bytes": len(renewal_raw),
        },
    }
    production_code = {
        path: dict(identity) for path, identity in current_code.items()
    }
    scope = renewal["closed_phase04_scope"]
    closed_paths = set(
        (
            *scope["configuration_paths"],
            *scope["shared_python_paths"],
            *scope["dedicated_python_paths"],
            *scope["shared_frontend_paths"],
            *scope["dedicated_frontend_paths"],
            *scope["exact_protected_compatibility_paths"],
            *SEMANTIC_ISOLATION_TERMINAL_CONFIGURATION_PATHS,
        )
    )
    for path in sorted(closed_paths - set(production_code)):
        raw, binding = _read_bound_file(
            root,
            path,
            maximum_bytes=2 * 1024 * 1024,
            label="semantic-isolation terminal production code",
        )
        production_code[path] = {
            "path": path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        tracks.append(
            (
                path,
                2 * 1024 * 1024,
                "semantic-isolation terminal production code",
                raw,
                binding,
            )
        )
    production_code = dict(sorted(production_code.items()))
    status_owners: dict[str, dict[str, Any]] = {}
    for path in SEMANTIC_ISOLATION_STATUS_OWNER_PATHS:
        raw, binding = _read_bound_file(
            root,
            path,
            maximum_bytes=DECISION_MAXIMUM_BYTES,
            label="semantic-isolation terminal status owner",
        )
        status_owners[path] = _semantic_isolation_file_identity(path, raw)
        tracks.append(
            (
                path,
                DECISION_MAXIMUM_BYTES,
                "semantic-isolation terminal status owner",
                raw,
                binding,
            )
        )
    status_owners = dict(sorted(status_owners.items()))
    us01_gate_inputs = _semantic_isolation_collect_us01_gate_input_identities(
        root
    )
    try:
        us01_story_gate_raw, us01_story_gate_binding = _read_bound_file(
            root,
            str(SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH),
            maximum_bytes=WAIVER_MAXIMUM_BYTES,
            label="semantic-isolation P04-US01 final-code story gate",
        )
    except (metrics.MetricsExecutionError, readiness.ReadinessContractError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 final-code story gate is absent or unreadable"
        ) from exc
    us01_story_gate = _strict_json(
        us01_story_gate_raw,
        "semantic-isolation P04-US01 final-code story gate",
    )
    if us01_story_gate_raw != _pretty_json_bytes(us01_story_gate):
        raise readiness.ReadinessContractError(
            "semantic-isolation P04-US01 final-code story gate bytes differ"
        )
    tracks.extend(
        _semantic_isolation_validate_us01_story_gate(
            root,
            us01_story_gate,
            expected_dependency_custody=current_dependency_custody,
            expected_production_code=production_code,
            expected_status_owners=status_owners,
            expected_us01_gate_inputs=us01_gate_inputs,
            today=today,
        )
    )
    tracks.append(
        (
            str(SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH),
            WAIVER_MAXIMUM_BYTES,
            "semantic-isolation P04-US01 final-code story gate",
            us01_story_gate_raw,
            us01_story_gate_binding,
        )
    )
    us01_story_gate_identity = {
        **_semantic_isolation_file_identity(
            str(SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH),
            us01_story_gate_raw,
        ),
        "semantic_sha256": us01_story_gate["semantic_sha256"],
    }
    try:
        focused_gate_raw, focused_gate_binding = _read_bound_file(
            root,
            str(SEMANTIC_ISOLATION_PHASE04_FOCUSED_GATE_PATH),
            maximum_bytes=WAIVER_MAXIMUM_BYTES,
            label="semantic-isolation focused gate execution",
        )
    except (metrics.MetricsExecutionError, readiness.ReadinessContractError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation focused gate execution is absent or unreadable"
        ) from exc
    focused_gate = _strict_json(
        focused_gate_raw,
        "semantic-isolation focused gate execution",
    )
    if focused_gate_raw != _pretty_json_bytes(focused_gate):
        raise readiness.ReadinessContractError(
            "semantic-isolation focused gate execution bytes differ"
        )
    _semantic_isolation_validate_focused_gate_execution(
        focused_gate,
        expected_dependency_custody=current_dependency_custody,
        expected_production_code=production_code,
        expected_status_owners=status_owners,
        today=today,
    )
    tracks.append(
        (
            str(SEMANTIC_ISOLATION_PHASE04_FOCUSED_GATE_PATH),
            WAIVER_MAXIMUM_BYTES,
            "semantic-isolation focused gate execution",
            focused_gate_raw,
            focused_gate_binding,
        )
    )
    expected_upstream = {
        **base_upstream,
        "p04_us01_story_gate": us01_story_gate_identity,
        "focused_gate_execution": {
            **_semantic_isolation_file_identity(
                str(SEMANTIC_ISOLATION_PHASE04_FOCUSED_GATE_PATH),
                focused_gate_raw,
            ),
            "semantic_sha256": focused_gate["semantic_sha256"],
        },
    }
    try:
        verification_raw, verification_binding = _read_bound_file(
            root,
            str(SEMANTIC_ISOLATION_PHASE04_VERIFICATION_PATH),
            maximum_bytes=WAIVER_MAXIMUM_BYTES,
            label="semantic-isolation terminal verification",
        )
    except (metrics.MetricsExecutionError, readiness.ReadinessContractError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal verification is absent or unreadable"
        ) from exc
    verification = _strict_json(
        verification_raw,
        "semantic-isolation terminal verification",
    )
    if verification_raw != _pretty_json_bytes(verification):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal verification bytes differ"
        )
    _semantic_isolation_validate_verification_state(
        verification,
        expected_upstream=expected_upstream,
        expected_production_code=production_code,
        expected_dependency_custody=current_dependency_custody,
        expected_protected_manifest_sha256=renewal["semantic_isolation"][
            "protected_code_manifest_sha256"
        ],
        expected_protected_path_count=renewal["semantic_isolation"][
            "protected_code_path_count"
        ],
        expected_status_owners=status_owners,
        expected_us01_gate_inputs=us01_gate_inputs,
    )
    tracks.append(
        (
            str(SEMANTIC_ISOLATION_PHASE04_VERIFICATION_PATH),
            WAIVER_MAXIMUM_BYTES,
            "semantic-isolation terminal verification",
            verification_raw,
            verification_binding,
        )
    )
    review_upstream = {
        **expected_upstream,
        "verification": {
            **_semantic_isolation_file_identity(
                str(SEMANTIC_ISOLATION_PHASE04_VERIFICATION_PATH),
                verification_raw,
            ),
            "semantic_sha256": verification["semantic_sha256"],
        },
    }
    review_paths = {
        "production_security": str(
            SEMANTIC_ISOLATION_PHASE04_PRODUCTION_SECURITY_REVIEW_PATH
        ),
        "metrics_custody": str(
            SEMANTIC_ISOLATION_PHASE04_METRICS_CUSTODY_REVIEW_PATH
        ),
    }
    review_identities: dict[str, dict[str, Any]] = {}
    review_records: dict[str, Mapping[str, Any]] = {}
    for role, path in review_paths.items():
        try:
            review_raw, review_binding = _read_bound_file(
                root,
                path,
                maximum_bytes=WAIVER_MAXIMUM_BYTES,
                label=f"semantic-isolation {role} review artifact",
            )
        except (
            metrics.MetricsExecutionError,
            readiness.ReadinessContractError,
        ) as exc:
            raise readiness.ReadinessContractError(
                f"semantic-isolation {role} review artifact is absent or unreadable"
            ) from exc
        review = _strict_json(
            review_raw,
            f"semantic-isolation {role} review artifact",
        )
        if review_raw != _pretty_json_bytes(review):
            raise readiness.ReadinessContractError(
                f"semantic-isolation {role} review artifact bytes differ"
            )
        _semantic_isolation_validate_review_artifact(
            review,
            expected_role=role,
            expected_upstream=review_upstream,
            focused_gate=focused_gate,
            us01_story_gate=us01_story_gate,
            us01_story_gate_identity=us01_story_gate_identity,
            today=today,
        )
        review_identities[role] = {
            **_semantic_isolation_file_identity(path, review_raw),
            "semantic_sha256": review["semantic_sha256"],
        }
        review_records[role] = review
        tracks.append(
            (
                path,
                WAIVER_MAXIMUM_BYTES,
                f"semantic-isolation {role} review artifact",
                review_raw,
                review_binding,
            )
        )
    approval_upstream = {
        **review_upstream,
        "production_security_review": review_identities[
            "production_security"
        ],
        "metrics_custody_review": review_identities["metrics_custody"],
    }
    try:
        approval_raw, approval_binding = _read_bound_file(
            root,
            str(SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH),
            maximum_bytes=WAIVER_MAXIMUM_BYTES,
            label="semantic-isolation terminal independent approval",
        )
    except (metrics.MetricsExecutionError, readiness.ReadinessContractError) as exc:
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent approval is absent or unreadable"
        ) from exc
    approval = _strict_json(
        approval_raw,
        "semantic-isolation terminal independent approval",
    )
    if approval_raw != _pretty_json_bytes(approval):
        raise readiness.ReadinessContractError(
            "semantic-isolation terminal independent approval bytes differ"
        )
    _semantic_isolation_validate_terminal_approval_state(
        approval,
        expected_upstream=approval_upstream,
        expected_review_identities=review_identities,
        expected_reviewers={
            role: record["reviewer_id"]
            for role, record in review_records.items()
        },
        expected_review_dates={
            role: record["reviewed_on"]
            for role, record in review_records.items()
        },
        renewal=renewal,
        today=today,
    )
    tracks.append(
        (
            str(SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH),
            WAIVER_MAXIMUM_BYTES,
            "semantic-isolation terminal independent approval",
            approval_raw,
            approval_binding,
        )
    )
    return tracks


def _exact_keys(value: Any, expected: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise readiness.ReadinessContractError(f"{label} keys differ")
    return value


def _strict_finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise readiness.ReadinessContractError(f"{label} type differs")
    number = float(value)
    if not math.isfinite(number):
        raise readiness.ReadinessContractError(f"{label} is not finite")
    return number


def _read_bound_file(
    root: Path,
    path: str,
    *,
    maximum_bytes: int,
    label: str,
) -> tuple[
    bytes,
    tuple[
        tuple[int, int, int, int, int, int, int],
        tuple[tuple[int, int, int, int, int, int, int], ...],
    ],
]:
    return metrics._read_bounded_regular_repository_file_with_binding(
        root,
        PurePosixPath(path),
        maximum_bytes=maximum_bytes,
        error=f"{label} custody differs",
    )


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    value = metrics._load_strict_json(raw, error=f"{label} is not strict JSON")
    if not isinstance(value, dict):
        raise readiness.ReadinessContractError(f"{label} is not an object")
    return value


def _validate_identity_record(
    root: Path,
    record: Mapping[str, Any],
    *,
    companion: bool,
) -> tuple[
    dict[str, Any],
    tuple[
        str,
        int,
        str,
        bytes,
        tuple[
            tuple[int, int, int, int, int, int, int],
            tuple[tuple[int, int, int, int, int, int, int], ...],
        ],
    ],
]:
    fields = {
        "code_manifest_sha256",
        "generated_at",
        "internal_retained_path",
        "physical_path",
        "raw_sha256",
        "semantic_sha256",
        "size_bytes",
        "status",
    }
    if companion:
        fields.add("paired_worker_count")
    _exact_keys(record, frozenset(fields), "waiver artifact identity")
    expected_identity = (
        EXPECTED_COMPANION_IDENTITY if companion else EXPECTED_PRIMARY_IDENTITY
    )
    if dict(record) != expected_identity:
        raise readiness.ReadinessContractError("waiver artifact identity differs")
    physical_path = record["physical_path"]
    size_bytes = record["size_bytes"]
    raw_sha256 = record["raw_sha256"]
    if (
        not isinstance(physical_path, str)
        or isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes <= 0
        or not isinstance(raw_sha256, str)
        or len(raw_sha256) != 64
        or (companion and type(record["paired_worker_count"]) is not int)
    ):
        raise readiness.ReadinessContractError("waiver artifact identity differs")
    raw, binding = _read_bound_file(
        root,
        physical_path,
        maximum_bytes=metrics.ARTIFACT_WRITE_CAP_BYTES,
        label="waiver artifact",
    )
    artifact = _strict_json(raw, "waiver artifact")
    if raw != metrics._artifact_bytes(artifact):
        raise readiness.ReadinessContractError("waiver artifact bytes differ")
    if (
        len(raw) != size_bytes
        or hashlib.sha256(raw).hexdigest() != raw_sha256
        or artifact.get("generated_at") != record["generated_at"]
        or artifact.get("retained_path") != record["internal_retained_path"]
        or artifact.get("status") != record["status"]
        or artifact.get("semantic_sha256") != record["semantic_sha256"]
        or artifact.get("semantic_sha256")
        != metrics._artifact_semantic_sha256(artifact)
        or artifact.get("code_sha256", {}).get("manifest_sha256")
        != record["code_manifest_sha256"]
    ):
        raise readiness.ReadinessContractError("waiver artifact binding differs")
    return artifact, (
        physical_path,
        metrics.ARTIFACT_WRITE_CAP_BYTES,
        "waiver artifact",
        raw,
        binding,
    )


def _validate_primary_candidate(
    artifact: Mapping[str, Any],
    scope: Mapping[str, Any],
) -> None:
    _exact_keys(scope, EXPECTED_EXCEPTION_SCOPE_FIELDS, "latency exception scope")
    if scope["candidate_specific"] is not True:
        raise readiness.ReadinessContractError("latency exception scope differs")
    numeric_scope = {
        key: _strict_finite_number(scope[key], f"latency exception scope {key}")
        for key in (
            "maximum_overrun_fraction",
            "observed_seconds",
            "overrun_fraction",
            "overrun_seconds",
            "strict_ceiling_seconds",
        )
    }
    if artifact["status"] != "failed_measurement_candidate" or artifact[
        "failures"
    ] != [
        {
            "pair_index": None,
            "stage": "running_region_projection",
            "state": None,
            "target_id": "ny-timetable",
            "type": "stage_failed",
        }
    ]:
        raise readiness.ReadinessContractError("waived primary failure differs")
    false_aggregates = {
        key for key, value in artifact["aggregate"].items() if value is False
    }
    if false_aggregates != EXPECTED_FALSE_AGGREGATES:
        raise readiness.ReadinessContractError("waived aggregate scope differs")
    if any(
        not target["summary"]["passed"]
        for target in artifact["source_extraction"]["targets"].values()
    ):
        raise readiness.ReadinessContractError("waived source latency differs")
    projection = artifact["running_region_projection"]
    targets = projection["targets"]
    if (
        targets["uber-earnings"]["summary"]["passed"] is not True
        or targets["ny-timetable"]["summary"]["passed"] is not False
        or projection["all_pass"] is not False
    ):
        raise readiness.ReadinessContractError("waived projection scope differs")
    ny_target = targets["ny-timetable"]
    observed = ny_target["summary"]["latency_p95_seconds"]
    ceiling = ny_target["protocol"]["latency_p95_ceiling_seconds"]
    overrun = observed - ceiling
    fraction = overrun / ceiling
    expected_scope = {
        "candidate_specific": True,
        "maximum_overrun_fraction": MAXIMUM_AUTHORIZED_OVERRUN_FRACTION,
        "metric": "latency_p95_seconds",
        "observed_seconds": observed,
        "overrun_fraction": fraction,
        "overrun_seconds": overrun,
        "stage": "running_region_projection",
        "strict_ceiling_seconds": ceiling,
        "target_id": "ny-timetable",
    }
    if any(
        not math.isclose(numeric_scope[key], float(value), rel_tol=0, abs_tol=1e-12)
        if isinstance(value, float)
        else scope[key] != value
        for key, value in expected_scope.items()
    ):
        raise readiness.ReadinessContractError("latency exception scope differs")
    if not 0 < fraction <= MAXIMUM_AUTHORIZED_OVERRUN_FRACTION:
        raise readiness.ReadinessContractError("latency exception is not close")
    if (
        artifact["paired_parser"]["worker_plan"]
        or artifact["paired_parser"]["workers"]
        or artifact["paired_parser"]["targets"]
        or artifact["output_sizes"]["paired_samples"]
    ):
        raise readiness.ReadinessContractError("waived fail-fast scope differs")
    if artifact["comparison_ledgers"]["all_pass"] is not True:
        raise readiness.ReadinessContractError("waived comparison ledger differs")


def _validate_complete_companion(artifact: Mapping[str, Any]) -> None:
    if (
        artifact["status"] != "final_measurement_candidate"
        or artifact["failures"] != []
        or any(value is not True for value in artifact["aggregate"].values())
        or len(artifact["paired_parser"]["worker_plan"])
        != metrics.PAIRED_WORKER_COUNT
        or len(artifact["paired_parser"]["workers"])
        != metrics.PAIRED_WORKER_COUNT
        or artifact["output_sizes"]["all_within_limits"] is not True
    ):
        raise readiness.ReadinessContractError("complete companion differs")
    if any(
        not target["summary"]["passed"]
        for stage in ("source_extraction", "running_region_projection")
        for target in artifact[stage]["targets"].values()
    ):
        raise readiness.ReadinessContractError("companion isolated gate differs")
    for target in artifact["paired_parser"]["targets"].values():
        if (
            target["passed"] is not True
            or target["overhead_p95_seconds"] > target["effective_ceiling_seconds"]
            or target["peak_rss_delta_bytes"]
            > metrics.PEAK_RSS_DELTA_CEILING_BYTES
        ):
            raise readiness.ReadinessContractError("companion paired gate differs")
    if {
        key: artifact[key]
        for key in ("hosted_requests", "hosted_tokens", "hosted_cost_usd")
    } != {
        "hosted_requests": 0,
        "hosted_tokens": 0,
        "hosted_cost_usd": 0,
    }:
        raise readiness.ReadinessContractError("companion hosted use differs")


def _validate_historical_artifact(
    artifact: Mapping[str, Any],
    *,
    current_code: Mapping[str, Mapping[str, Any]],
    current_dependency_custody: Mapping[str, Any],
    current_input_custody: Mapping[str, Any],
    current_m0_identity: Mapping[str, Any],
    current_predecessor_outputs: Mapping[str, Mapping[str, Any]],
    observed_history: Mapping[str, Mapping[str, Any]],
) -> None:
    prior_records = artifact.get("prior_failed_candidates")
    if not isinstance(prior_records, list):
        raise readiness.ReadinessContractError("historical prior custody differs")
    prior_paths: list[str] = []
    for record in prior_records:
        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
            raise readiness.ReadinessContractError("historical prior custody differs")
        prior_paths.append(record["path"])
    try:
        prior_identities = {path: observed_history[path] for path in prior_paths}
    except KeyError as exc:
        raise readiness.ReadinessContractError(
            "historical prior custody differs"
        ) from exc
    metrics._validate_metrics_artifact_with_observations(
        artifact,
        existing_paths=tuple(prior_paths),
        observed_code_files=current_code,
        observed_dependency_custody=current_dependency_custody,
        observed_input_custody=current_input_custody,
        observed_m0_identity=current_m0_identity,
        observed_predecessor_outputs=current_predecessor_outputs,
        observed_prior_artifacts=prior_identities,
        historical_custody=True,
    )


def _validate_frontend_renewal(
    root: Path,
    *,
    current_code: Mapping[str, Mapping[str, Any]],
    expected_history: Mapping[str, Any],
    original_waiver: Mapping[str, Any],
    primary: Mapping[str, Any],
    today: date | None,
) -> tuple[
    dict[str, Any],
    bytes,
    tuple[
        tuple[int, int, int, int, int, int, int],
        tuple[tuple[int, int, int, int, int, int, int], ...],
    ],
    tuple[
        str,
        int,
        str,
        bytes,
        tuple[
            tuple[int, int, int, int, int, int, int],
            tuple[tuple[int, int, int, int, int, int, int], ...],
        ],
    ],
]:
    """Validate the narrowly authorized frontend-only custody renewal."""

    raw, binding = _read_bound_file(
        root,
        str(RENEWAL_WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label="latency renewal waiver",
    )
    if (
        len(raw) != EXPECTED_RENEWAL_WAIVER_IDENTITY["size_bytes"]
        or hashlib.sha256(raw).hexdigest()
        != EXPECTED_RENEWAL_WAIVER_IDENTITY["raw_sha256"]
    ):
        raise readiness.ReadinessContractError("latency renewal waiver differs")
    renewal = _strict_json(raw, "latency renewal waiver")
    _exact_keys(
        renewal,
        EXPECTED_RENEWAL_TOP_LEVEL_FIELDS,
        "latency renewal waiver",
    )
    if raw != _pretty_json_bytes(renewal):
        raise readiness.ReadinessContractError("latency renewal waiver bytes differ")
    if (
        renewal.get("semantic_sha256")
        != EXPECTED_RENEWAL_WAIVER_IDENTITY["semantic_sha256"]
        or renewal.get("semantic_sha256") != waiver_semantic_sha256(renewal)
    ):
        raise readiness.ReadinessContractError("latency renewal waiver digest differs")
    if {
        key: renewal[key]
        for key in (
            "schema_version",
            "record_kind",
            "story",
            "renewal_id",
            "renews_waiver_id",
            "status",
        )
    } != {
        "schema_version": "1.0",
        "record_kind": "p03_us08_frontend_only_latency_exception_renewal",
        "story": "P03-US08",
        "renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX"
        ),
        "renews_waiver_id": "P03-US08-LATENCY-EXCEPTION-20260803",
        "status": "accepted_with_time_bounded_metrics_exception_renewal",
    }:
        raise readiness.ReadinessContractError("latency renewal identity differs")

    approval = _exact_keys(
        renewal["approval"],
        frozenset({"authorized_on", "owner", "source", "statement"}),
        "latency renewal approval",
    )
    if approval != {
        "authorized_on": "2026-08-03",
        "owner": "project owner/requester",
        "source": "active Codex thread",
        "statement": EXPECTED_RENEWAL_APPROVAL_STATEMENT,
    }:
        raise readiness.ReadinessContractError("latency renewal approval differs")

    original_code = primary["code_sha256"]["post"]
    phase04_baseline_code = _phase04_baseline_code(original_code)
    if set(phase04_baseline_code) != set(original_code):
        raise readiness.ReadinessContractError("latency renewal code paths differ")
    differing_paths = tuple(
        sorted(
            path
            for path in phase04_baseline_code
            if phase04_baseline_code[path] != original_code[path]
        )
    )
    if differing_paths != EXPECTED_RENEWAL_CODE_DIFFERENCES:
        raise readiness.ReadinessContractError("latency renewal scope differs")
    backend_parser_paths = tuple(
        sorted(path for path in original_code if path.startswith("app/"))
    )
    if not backend_parser_paths or any(
        phase04_baseline_code[path] != original_code[path]
        for path in backend_parser_paths
    ):
        raise readiness.ReadinessContractError(
            "latency renewal backend/parser custody differs"
        )
    original_files = {
        path: original_code[path] for path in EXPECTED_RENEWAL_CODE_DIFFERENCES
    }
    renewed_files = {
        path: phase04_baseline_code[path]
        for path in EXPECTED_RENEWAL_CODE_DIFFERENCES
    }
    authorized_change = _exact_keys(
        renewal["authorized_change"],
        frozenset(
            {
                "all_other_required_code_paths_match_original",
                "difference_scope",
                "differing_paths",
                "measured_backend_parser_runtime_paths_match_original",
                "original_code_manifest_sha256",
                "original_files",
                "renewed_code_manifest_sha256",
                "renewed_files",
                "required_code_path_count",
            }
        ),
        "latency renewal authorized change",
    )
    expected_authorized_change = {
        "all_other_required_code_paths_match_original": True,
        "difference_scope": "frontend-only bbox compatibility fix",
        "differing_paths": list(EXPECTED_RENEWAL_CODE_DIFFERENCES),
        "measured_backend_parser_runtime_paths_match_original": True,
        "original_code_manifest_sha256": EXPECTED_PRIMARY_IDENTITY[
            "code_manifest_sha256"
        ],
        "original_files": original_files,
        "renewed_code_manifest_sha256": EXPECTED_RENEWAL_CODE_MANIFEST_SHA256,
        "renewed_files": EXPECTED_RENEWAL_FILE_IDENTITIES,
        "required_code_path_count": len(metrics.REQUIRED_CODE_PATHS),
    }
    if (
        authorized_change != expected_authorized_change
        or authorized_change["all_other_required_code_paths_match_original"]
        is not True
        or authorized_change[
            "measured_backend_parser_runtime_paths_match_original"
        ]
        is not True
        or type(authorized_change["required_code_path_count"]) is not int
        or renewed_files != EXPECTED_RENEWAL_FILE_IDENTITIES
        or metrics._sha256_json(phase04_baseline_code)
        != EXPECTED_RENEWAL_CODE_MANIFEST_SHA256
        or metrics._sha256_json(original_code)
        != EXPECTED_PRIMARY_IDENTITY["code_manifest_sha256"]
    ):
        raise readiness.ReadinessContractError(
            "latency renewal authorized change differs"
        )

    if renewal["original_waiver_identity"] != EXPECTED_ORIGINAL_WAIVER_IDENTITY:
        raise readiness.ReadinessContractError(
            "latency renewal original waiver identity differs"
        )
    if renewal["original_decision_identity"] != EXPECTED_DECISION_IDENTITY:
        raise readiness.ReadinessContractError(
            "latency renewal original decision identity differs"
        )
    if renewal["exception_scope"] != original_waiver["exception_scope"]:
        raise readiness.ReadinessContractError(
            "latency renewal exception scope differs"
        )
    _validate_primary_candidate(primary, renewal["exception_scope"])
    if (
        renewal["failed_history"] != expected_history
        or renewal["failed_history"] != EXPECTED_FAILED_HISTORY
    ):
        raise readiness.ReadinessContractError("latency renewal history differs")
    for field in (
        "deferred_work",
        "hosted_usage",
        "not_waived",
        "operational_constraints",
    ):
        if renewal[field] != original_waiver[field]:
            raise readiness.ReadinessContractError(
                f"latency renewal {field.replace('_', ' ')} differs"
            )

    expiry = _exact_keys(
        renewal["expiry"],
        frozenset(
            {
                "expired_effect",
                "expires_before",
                "expires_on_any_further_required_code_change",
                "review_due_on",
            }
        ),
        "latency renewal expiry",
    )
    try:
        review_due = date.fromisoformat(expiry["review_due_on"])
    except (TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "latency renewal expiry differs"
        ) from exc
    if (
        expiry
        != {
            "expired_effect": (
                "P03-US08 returns to In Progress and dependent exit claims are "
                "blocked"
            ),
            "expires_before": ["production enablement", "Phase 04 exit"],
            "expires_on_any_further_required_code_change": True,
            "review_due_on": "2026-09-02",
        }
        or (today or datetime.now(tz=UTC).date()) > review_due
    ):
        raise readiness.ReadinessContractError("latency renewal expired")

    decision = _exact_keys(
        renewal["decision_identity"],
        frozenset({"path", "raw_sha256", "size_bytes"}),
        "latency renewal decision identity",
    )
    if (
        dict(decision) != EXPECTED_RENEWAL_DECISION_IDENTITY
        or type(decision["size_bytes"]) is not int
    ):
        raise readiness.ReadinessContractError(
            "latency renewal decision identity differs"
        )
    decision_raw, decision_binding = _read_bound_file(
        root,
        decision["path"],
        maximum_bytes=DECISION_MAXIMUM_BYTES,
        label="latency renewal decision",
    )
    if (
        len(decision_raw) != decision["size_bytes"]
        or hashlib.sha256(decision_raw).hexdigest() != decision["raw_sha256"]
        or renewal["renewal_id"].encode("utf-8") not in decision_raw
        or renewal["renews_waiver_id"].encode("utf-8") not in decision_raw
    ):
        raise readiness.ReadinessContractError("latency renewal decision differs")
    decision_track = (
        decision["path"],
        DECISION_MAXIMUM_BYTES,
        "latency renewal decision",
        decision_raw,
        decision_binding,
    )
    return renewal, raw, binding, decision_track


def validate_performance_exception(
    repository_root: Path,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Validate the sealed exception and every repository-bound dependency."""

    root = metrics._resolve_repository_root(repository_root)
    waiver_raw, waiver_binding = _read_bound_file(
        root,
        str(WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label="latency waiver",
    )
    waiver = _strict_json(waiver_raw, "latency waiver")
    _exact_keys(waiver, EXPECTED_TOP_LEVEL_FIELDS, "latency waiver")
    if waiver_raw != _pretty_json_bytes(waiver):
        raise readiness.ReadinessContractError("latency waiver bytes differ")
    if waiver.get("semantic_sha256") != waiver_semantic_sha256(waiver):
        raise readiness.ReadinessContractError("latency waiver digest differs")
    if {
        key: waiver[key]
        for key in (
            "schema_version",
            "record_kind",
            "story",
            "waiver_id",
            "status",
        )
    } != {
        "schema_version": "1.0",
        "record_kind": "p03_us08_user_authorized_latency_exception",
        "story": "P03-US08",
        "waiver_id": "P03-US08-LATENCY-EXCEPTION-20260803",
        "status": "accepted_with_time_bounded_metrics_exception",
    }:
        raise readiness.ReadinessContractError("latency waiver identity differs")

    approval = _exact_keys(
        waiver["approval"],
        frozenset({"authorized_on", "owner", "source", "statements"}),
        "latency waiver approval",
    )
    if (
        approval["authorized_on"] != "2026-08-03"
        or approval["owner"] != "project owner/requester"
        or approval["source"] != "active Codex thread"
        or tuple(approval["statements"]) != EXPECTED_APPROVAL_STATEMENTS
    ):
        raise readiness.ReadinessContractError("latency waiver approval differs")

    tracked: list[
        tuple[
            str,
            int,
            str,
            bytes,
            tuple[
                tuple[int, int, int, int, int, int, int],
                tuple[tuple[int, int, int, int, int, int, int], ...],
            ],
        ]
    ] = []
    primary, primary_track = _validate_identity_record(
        root,
        waiver["primary_candidate"],
        companion=False,
    )
    companion, companion_track = _validate_identity_record(
        root,
        waiver["complete_companion"],
        companion=True,
    )
    tracked.extend((primary_track, companion_track))
    if waiver["complete_companion"]["paired_worker_count"] != 20:
        raise readiness.ReadinessContractError("companion worker claim differs")
    _validate_primary_candidate(primary, waiver["exception_scope"])
    _validate_complete_companion(companion)

    expected_existing_paths = tuple(
        EXPECTED_FAILED_HISTORY["first_path"]
        if attempt == 1
        else (
            "tracker/phase-03-layout/evidence/"
            f"P03-US08-running-region-metrics-attempt-{attempt:02d}-failed.json"
        )
        for attempt in range(1, EXPECTED_FAILED_HISTORY["artifact_count"] + 1)
    )
    (
        observed_root,
        existing_paths,
        current_input_custody,
        current_m0_identity,
        current_predecessor_outputs,
        current_code,
        current_dependency_custody,
        observed_history,
    ) = metrics._collect_repository_custody(
        root,
        code_paths=tuple(sorted(metrics.REQUIRED_CODE_PATHS)),
        expected_existing_paths=expected_existing_paths,
    )
    if observed_root != root:
        raise readiness.ReadinessContractError("waiver repository root differs")
    if str(metrics.FINAL_ARTIFACT_RELATIVE_PATH) in existing_paths:
        raise readiness.ReadinessContractError("strict final conflicts with waiver")
    history_records = [
        {"path": path, **observed_history[path]} for path in existing_paths
    ]
    history_manifest = hashlib.sha256(
        _canonical_json(history_records).encode("utf-8")
    ).hexdigest()
    expected_history = {
        "artifact_count": len(existing_paths),
        "first_path": existing_paths[0],
        "last_path": existing_paths[-1],
        "manifest_sha256": history_manifest,
    }
    if (
        waiver["failed_history"] != expected_history
        or waiver["failed_history"] != EXPECTED_FAILED_HISTORY
        or type(waiver["failed_history"].get("artifact_count")) is not int
    ):
        raise readiness.ReadinessContractError("waived history differs")

    _validate_historical_artifact(
        primary,
        current_code=current_code,
        current_dependency_custody=current_dependency_custody,
        current_input_custody=current_input_custody,
        current_m0_identity=current_m0_identity,
        current_predecessor_outputs=current_predecessor_outputs,
        observed_history=observed_history,
    )
    _validate_historical_artifact(
        companion,
        current_code=current_code,
        current_dependency_custody=current_dependency_custody,
        current_input_custody=current_input_custody,
        current_m0_identity=current_m0_identity,
        current_predecessor_outputs=current_predecessor_outputs,
        observed_history=observed_history,
    )
    metrics.validate_dependency_custody(
        primary["dependency_custody"],
    )
    if companion["dependency_custody"] != primary["dependency_custody"]:
        raise readiness.ReadinessContractError("companion dependency bridge differs")
    original_code = primary["code_sha256"]["post"]
    phase04_baseline_code = _phase04_baseline_code(original_code)
    if set(original_code) != set(companion["code_sha256"]["post"]):
        raise readiness.ReadinessContractError("waived code bridge path set differs")
    differing_paths = tuple(
        sorted(
            path
            for path in original_code
            if original_code[path] != companion["code_sha256"]["post"][path]
        )
    )
    bridge = waiver["custody_bridge"]
    expected_bridge = {
        "all_other_code_paths_match": True,
        "current_code_manifest_sha256": metrics._sha256_json(original_code),
        "difference_scope": "retained-artifact validator and its contract test only",
        "differing_paths": list(EXPECTED_CODE_DIFFERENCES),
        "product_runtime_paths_match": True,
    }
    if (
        not isinstance(bridge, Mapping)
        or bridge != expected_bridge
        or bridge.get("all_other_code_paths_match") is not True
        or bridge.get("product_runtime_paths_match") is not True
        or differing_paths != EXPECTED_CODE_DIFFERENCES
    ):
        raise readiness.ReadinessContractError("waived code bridge differs")
    if set(phase04_baseline_code) != set(companion["code_sha256"]["post"]):
        raise readiness.ReadinessContractError(
            "renewed companion code bridge path set differs"
        )
    renewed_companion_differences = tuple(
        sorted(
            path
            for path in phase04_baseline_code
            if phase04_baseline_code[path]
            != companion["code_sha256"]["post"][path]
        )
    )
    if renewed_companion_differences != (
        EXPECTED_RENEWED_COMPANION_CODE_DIFFERENCES
    ):
        raise readiness.ReadinessContractError(
            "renewed companion code bridge differs"
        )

    decision = _exact_keys(
        waiver["decision_identity"],
        frozenset({"path", "raw_sha256", "size_bytes"}),
        "latency waiver decision identity",
    )
    if (
        dict(decision) != EXPECTED_DECISION_IDENTITY
        or type(decision["size_bytes"]) is not int
        or waiver["decision_path"] != decision["path"]
    ):
        raise readiness.ReadinessContractError("latency waiver decision path differs")
    decision_raw, decision_binding = _read_bound_file(
        root,
        decision["path"],
        maximum_bytes=DECISION_MAXIMUM_BYTES,
        label="latency waiver decision",
    )
    if (
        len(decision_raw) != decision["size_bytes"]
        or hashlib.sha256(decision_raw).hexdigest() != decision["raw_sha256"]
        or waiver["waiver_id"].encode("utf-8") not in decision_raw
    ):
        raise readiness.ReadinessContractError("latency waiver decision differs")
    tracked.append(
        (
            decision["path"],
            DECISION_MAXIMUM_BYTES,
            "latency waiver decision",
            decision_raw,
            decision_binding,
        )
    )

    expiry = _exact_keys(
        waiver["expiry"],
        frozenset(
            {
                "expired_effect",
                "expires_before",
                "expires_on_runtime_code_change",
                "review_due_on",
            }
        ),
        "latency waiver expiry",
    )
    try:
        review_due = date.fromisoformat(expiry["review_due_on"])
    except (TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError("latency waiver expiry differs") from exc
    if (
        expiry["review_due_on"] != "2026-09-02"
        or (today or datetime.now(tz=UTC).date()) > review_due
        or expiry["expires_on_runtime_code_change"] is not True
        or expiry["expires_before"] != ["production enablement", "Phase 04 exit"]
        or expiry["expired_effect"]
        != "P03-US08 returns to In Progress and dependent exit claims are blocked"
    ):
        raise readiness.ReadinessContractError("latency waiver expired")
    deferred_work = _exact_keys(
        waiver["deferred_work"],
        frozenset({"required_outcome", "scope"}),
        "latency waiver deferred work",
    )
    if deferred_work != {
        "required_outcome": (
            "replace this exception with a strict current-code final campaign or "
            "explicitly renew it"
        ),
        "scope": [
            "near-boundary projection latency",
            "fresh-process RSS measurement stability",
        ],
    }:
        raise readiness.ReadinessContractError("latency waiver deferred work differs")
    if (
        not isinstance(waiver["not_waived"], list)
        or waiver["not_waived"] != list(EXPECTED_NOT_WAIVED)
    ):
        raise readiness.ReadinessContractError("latency waiver exclusions differ")
    hosted_usage = _exact_keys(
        waiver["hosted_usage"],
        frozenset({"hosted_cost_usd", "hosted_requests", "hosted_tokens"}),
        "latency waiver hosted use",
    )
    if hosted_usage != {
        "hosted_cost_usd": 0,
        "hosted_requests": 0,
        "hosted_tokens": 0,
    } or any(type(hosted_usage.get(field)) is not int for field in hosted_usage):
        raise readiness.ReadinessContractError("latency waiver hosted use differs")
    operational_constraints = _exact_keys(
        waiver["operational_constraints"],
        frozenset(
            {
                "canonical_strict_final_artifact_present",
                "feature_flag",
                "feature_flag_default",
                "rollback",
            }
        ),
        "latency waiver rollback",
    )
    if operational_constraints != {
        "canonical_strict_final_artifact_present": False,
        "feature_flag": "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED",
        "feature_flag_default": False,
        "rollback": (
            "disable the flag to skip US08 work and return the exact configured "
            "predecessor"
        ),
    } or any(
        operational_constraints.get(field) is not False
        for field in (
            "canonical_strict_final_artifact_present",
            "feature_flag_default",
        )
    ):
        raise readiness.ReadinessContractError("latency waiver rollback differs")
    if (
        len(waiver_raw) != EXPECTED_ORIGINAL_WAIVER_IDENTITY["size_bytes"]
        or hashlib.sha256(waiver_raw).hexdigest()
        != EXPECTED_ORIGINAL_WAIVER_IDENTITY["raw_sha256"]
    ):
        raise readiness.ReadinessContractError("original latency waiver differs")

    (
        frontend_renewal,
        renewal_raw,
        renewal_binding,
        renewal_decision_track,
    ) = _validate_frontend_renewal(
        root,
        current_code=current_code,
        expected_history=expected_history,
        original_waiver=waiver,
        primary=primary,
        today=today,
    )
    tracked.append(renewal_decision_track)
    (
        phase04_renewal,
        phase04_renewal_raw,
        phase04_renewal_binding,
        phase04_tracks,
    ) = _validate_phase04_renewal(
        root,
        current_code=phase04_baseline_code,
        phase04_baseline_code=phase04_baseline_code,
        expected_history=expected_history,
        frontend_renewal=frontend_renewal,
        original_waiver=waiver,
        today=today,
        ancestry_only=True,
    )
    tracked.extend(phase04_tracks)
    (
        hardened_phase04_renewal,
        hardened_phase04_renewal_raw,
        hardened_phase04_renewal_binding,
        hardened_phase04_tracks,
    ) = _validate_hardened_phase04_renewal(
        root,
        current_code=current_code,
        phase04_baseline_code=phase04_baseline_code,
        expected_history=expected_history,
        phase04_renewal=phase04_renewal,
        original_waiver=waiver,
        today=today,
        ancestry_only=True,
    )
    tracked.extend(hardened_phase04_tracks)
    (
        semantic_isolation_phase04_renewal,
        semantic_isolation_phase04_renewal_raw,
        semantic_isolation_phase04_renewal_binding,
        semantic_isolation_phase04_tracks,
    ) = _validate_semantic_isolation_phase04_renewal(
        root,
        current_code=current_code,
        current_dependency_custody=current_dependency_custody,
        expected_history=expected_history,
        hardened_renewal=hardened_phase04_renewal,
        historical_dependency_custody=primary["dependency_custody"],
        original_waiver=waiver,
        today=today,
    )
    tracked.extend(semantic_isolation_phase04_tracks)
    tracked.extend(
        _validate_semantic_isolation_terminal_approval(
            root,
            renewal=semantic_isolation_phase04_renewal,
            renewal_raw=semantic_isolation_phase04_renewal_raw,
            current_code=current_code,
            current_dependency_custody=current_dependency_custody,
            today=today,
        )
    )

    final_repository_observation = metrics._collect_repository_custody(
        root,
        code_paths=tuple(sorted(metrics.REQUIRED_CODE_PATHS)),
        expected_existing_paths=existing_paths,
    )
    initial_repository_observation = (
        root,
        existing_paths,
        current_input_custody,
        current_m0_identity,
        current_predecessor_outputs,
        current_code,
        current_dependency_custody,
        observed_history,
    )
    if final_repository_observation != initial_repository_observation:
        raise readiness.ReadinessContractError(
            "waiver repository custody changed during validation"
        )

    for path, maximum_bytes, label, raw, binding in tracked:
        final_raw, final_binding = _read_bound_file(
            root,
            path,
            maximum_bytes=maximum_bytes,
            label=f"{label} changed during validation",
        )
        if final_raw != raw or final_binding != binding:
            raise readiness.ReadinessContractError(
                f"{label} changed during validation"
            )
    final_waiver_raw, final_waiver_binding = _read_bound_file(
        root,
        str(WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label="latency waiver changed during validation",
    )
    if final_waiver_raw != waiver_raw or final_waiver_binding != waiver_binding:
        raise readiness.ReadinessContractError(
            "latency waiver changed during validation"
        )
    final_renewal_raw, final_renewal_binding = _read_bound_file(
        root,
        str(RENEWAL_WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label="latency renewal waiver changed during validation",
    )
    if (
        final_renewal_raw != renewal_raw
        or final_renewal_binding != renewal_binding
    ):
        raise readiness.ReadinessContractError(
            "latency renewal waiver changed during validation"
        )
    final_phase04_renewal_raw, final_phase04_renewal_binding = _read_bound_file(
        root,
        str(PHASE04_RENEWAL_WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label="Phase 04 latency renewal waiver changed during validation",
    )
    if (
        final_phase04_renewal_raw != phase04_renewal_raw
        or final_phase04_renewal_binding != phase04_renewal_binding
    ):
        raise readiness.ReadinessContractError(
            "Phase 04 latency renewal waiver changed during validation"
        )
    (
        final_hardened_phase04_renewal_raw,
        final_hardened_phase04_renewal_binding,
    ) = _read_bound_file(
        root,
        str(HARDENED_PHASE04_RENEWAL_WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label="hardened Phase 04 latency renewal waiver changed during validation",
    )
    if (
        final_hardened_phase04_renewal_raw != hardened_phase04_renewal_raw
        or final_hardened_phase04_renewal_binding
        != hardened_phase04_renewal_binding
    ):
        raise readiness.ReadinessContractError(
            "hardened Phase 04 latency renewal waiver changed during validation"
        )
    (
        final_semantic_isolation_phase04_renewal_raw,
        final_semantic_isolation_phase04_renewal_binding,
    ) = _read_bound_file(
        root,
        str(SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH),
        maximum_bytes=WAIVER_MAXIMUM_BYTES,
        label=(
            "semantic-isolation Phase 04 latency renewal waiver changed during "
            "validation"
        ),
    )
    if (
        final_semantic_isolation_phase04_renewal_raw
        != semantic_isolation_phase04_renewal_raw
        or final_semantic_isolation_phase04_renewal_binding
        != semantic_isolation_phase04_renewal_binding
    ):
        raise readiness.ReadinessContractError(
            "semantic-isolation Phase 04 latency renewal waiver changed during "
            "validation"
        )
    return waiver


__all__ = [
    "EXPECTED_APPROVAL_STATEMENTS",
    "EXPECTED_CODE_DIFFERENCES",
    "EXPECTED_RENEWAL_APPROVAL_STATEMENT",
    "EXPECTED_RENEWAL_CODE_DIFFERENCES",
    "EXPECTED_RENEWED_COMPANION_CODE_DIFFERENCES",
    "HARDENED_PHASE04_RENEWAL_WAIVER_PATH",
    "MAXIMUM_AUTHORIZED_OVERRUN_FRACTION",
    "PHASE04_RENEWAL_WAIVER_PATH",
    "RENEWAL_WAIVER_PATH",
    "SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH",
    "WAIVER_PATH",
    "validate_performance_exception",
    "waiver_semantic_sha256",
]
