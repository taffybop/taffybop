"""Fail-closed custody guard for the P03-US08 phase-latency renewal.

This is a successor-owned guard.  It deliberately does not change the sealed
P03 exception validator or any historical P04 renewal.  Instead, it proves the
new administrative renewal, the exact failed observation on which it rests,
and the narrow additive repository delta needed by phase-latency.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from tests.benchmarks import running_region_metrics as metrics
from tests.fixtures.phase_03.running_regions import contract as readiness
from tests.fixtures.phase_03.running_regions import performance_exception as historical


RENEWAL_DECISION_PATH = PurePosixPath(
    "tracker/phase-latency/decisions/"
    "LAT-P03-US08-latency-continuity-renewal.md"
)
RENEWAL_RECORD_PATH = PurePosixPath(
    "tracker/phase-latency/evidence/"
    "LAT-P03-US08-latency-continuity-renewal.json"
)
CUSTODY_RECORD_PATH = PurePosixPath(
    "tracker/phase-latency/evidence/"
    "LAT-P03-US08-live-custody-reconciliation.json"
)
ATTEMPT_48_PATH = PurePosixPath(
    "tracker/phase-03-layout/evidence/"
    "P03-US08-running-region-metrics-attempt-48-failed.json"
)

EXPECTED_RENEWAL_DECISION_IDENTITY = {
    "path": str(RENEWAL_DECISION_PATH),
    "sha256": "d8736778b84ca9b96c6eee6bd18e3d3e324fa79dab77ceb902c9ad756f97b128",
    "size_bytes": 7_050,
}
EXPECTED_RENEWAL_RECORD_IDENTITY = {
    "path": str(RENEWAL_RECORD_PATH),
    "sha256": "176e2472e6379c7079416f6c887938bbdc2b8b3382c43e566fc24582e08ac2c6",
    "size_bytes": 3_425,
}
# Filled only from the separately retained successor-owned record.  Keeping
# this identity in executable code means the record cannot authorize its own
# mutation.
EXPECTED_CUSTODY_RECORD_IDENTITY = {
    "path": str(CUSTODY_RECORD_PATH),
    "sha256": "47c2e104c3aab52f68026c0826182993211c55b84a8f3386c1a01c8660249564",
    "size_bytes": 3_216,
}
EXPECTED_ATTEMPT_48_IDENTITY = {
    "path": str(ATTEMPT_48_PATH),
    "sha256": "1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123",
    "size_bytes": 158_921,
    "semantic_sha256": "51433843638d69a2d09ced0d96a44a34323b1f5ece9c890c7c91088bac2df2e5",
}
EXPECTED_FAILED_HISTORY = {
    "through_attempt": 55,
    "artifact_count": 55,
    "manifest_sha256": "bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff",
}
EXPECTED_ATTEMPT_FACTS = {
    "case": "ny-timetable",
    "stage": "running_region_projection",
    "metric": "latency_p95_seconds",
    "observed_seconds": "0.050946750",
    "strict_ceiling_seconds": "0.050000000",
    "overrun_seconds": "0.000946750",
    "overrun_fraction": "0.018935",
    "maximum_candidate_specific_bound": "0.05",
    "status": "failed",
    "raw_sha256": EXPECTED_ATTEMPT_48_IDENTITY["sha256"],
    "raw_size_bytes": EXPECTED_ATTEMPT_48_IDENTITY["size_bytes"],
    "semantic_sha256": EXPECTED_ATTEMPT_48_IDENTITY["semantic_sha256"],
}
EXPECTED_CEILINGS = {
    "running_region_projection_p95_seconds": "0.050000000",
    "source_extraction_p95_seconds": "0.250000000",
    "ny_timetable_paired_parser_seconds": "2.338000000",
    "uber_earnings_paired_parser_seconds": "1.457500000",
    "allocation_delta_bytes": 67_108_864,
    "peak_rss_delta_bytes": 67_108_864,
    "source_report_size_bytes": 8_388_608,
}
EXPECTED_NON_WAIVED_GATES = [
    "rss",
    "allocation",
    "cpu_gpu_and_resources",
    "paired_parser_latency",
    "source_extraction_latency",
    "llamaparse_paired_latency",
    "correctness",
    "quality_and_source_fidelity",
    "non_fabrication_and_alternative_evidence",
    "security_and_privacy",
    "malformed_input_timeout_and_fail_closed",
    "api_schema_serializer_frontend_compatibility",
    "code_dependency_fixture_benchmark_input_evidence_model_custody",
    "hosted_use",
    "output_cost_and_egress",
    "determinism",
    "default_off_and_rollback",
    "independent_review",
    "prior_phase_and_latency_exit_gates",
]
EXPECTED_EXPIRES_BEFORE = [
    "production_enablement_or_reliance",
    "relevant_running_region_semantic_runtime_reachability_output_dependency_evidence_or_custody_change",
    "ceiling_bound_default_off_rollback_or_non_waived_gate_change",
    "work_outside_lat_us01_through_lat_us08",
    "phase_04_behavior_change_while_paused",
    "phase_05_work_or_status_transition",
    "classifier_ambiguity_or_gate_bypass",
    "rollback_failure",
]
EXPECTED_P04_PYPROJECT_IDENTITY = {
    "path": "pyproject.toml",
    "sha256": "a9c66f17d92ea9fae623a7d6d953c91b103fbbe96b8fa98d122651d87cfb2cd8",
    "size_bytes": 755,
}
EXPECTED_CURRENT_PYPROJECT_IDENTITY = {
    "path": "pyproject.toml",
    "sha256": "975f9d5cde7e3c618bc201c2ef0df26e6a9ebda73a3322a0bf0d0bd12f36bfe7",
    "size_bytes": 944,
}
EXPECTED_UV_LOCK_IDENTITY = {
    "path": "uv.lock",
    "sha256": "acd97c526138e247c54272b250c784b311de17b05ef3a28990b86b548f205b11",
    "size_bytes": 606_213,
}
PYTEST_MARKER_DELTA = (
    b"markers = [\n"
    b'    "real_metrics: opt-in governed observer/current-RSS sampling or '
    b"PREPARE and reviewed-corpus campaign controls; excludes deterministic "
    b'subprocess lifecycle/cleanup units",\n'
    b"]\n"
)
PROTECTED_RUNNING_REGION_MODULE_IDENTITY = {
    "path": "app/services/running_regions.py",
    "sha256": "1824d3eaa9a9e1ee7545164dce0712e95f695d23c73d1a16ca5a9cc565714b62",
    "size_bytes": 375_077,
}
HISTORICAL_VALIDATOR_IDENTITY = {
    "path": "tests/fixtures/phase_03/running_regions/performance_exception.py",
    "sha256": "e1bbb0f83c8a08d1b8093c755601fa3f5fa280d7de34f4053ef8a720f64d4c58",
    "size_bytes": 679_969,
}
EXPECTED_PREDECESSOR_SOURCE_IDENTITIES = [
    {
        "path": "app/api.py",
        "sha256": "253eda64be75df1d22ad57db9db62b6c92dcc283575b791be8ddadd976e9b72d",
        "size_bytes": 5_774,
    },
    {
        "path": "app/config.py",
        "sha256": "863695112bace175f12ae5e0e4294c9292a5b9c884b140e4a6a6cb506284f85d",
        "size_bytes": 18_195,
    },
    {
        "path": "app/services/pipeline.py",
        "sha256": "a79a22b0324d17e28ede2d31c76a67bbbe89f859110521beae48fd9f1b03f6a8",
        "size_bytes": 311_099,
    },
]
# Finalized from the deterministic projection after exact predecessor restoration.
EXPECTED_RUNNING_REGION_INTEGRATION_PROJECTION = {
    "entry_count": 92,
    "sha256": "f0ea5e8124eaa9928a4b7e7f47186883ae01ff0fc78792a5b73739448ce80af1",
}

_MAXIMUM_RECORD_BYTES = 64 * 1024
_MAXIMUM_SOURCE_BYTES = 2 * 1024 * 1024
_MAXIMUM_APP_FILES = 256
_MAXIMUM_APP_ENTRIES = 2_048
_PROTECTED_ATOM = re.compile(
    r"(?:running[_-]?regions?|layout[_-]?running[_-]?regions?|"
    r"parser[_-]?layout[_-]?running[_-]?regions[_-]?enabled)",
    flags=re.IGNORECASE,
)
_PRODUCTION_LATENCY_MODULE = re.compile(
    r"latency",
    flags=re.IGNORECASE,
)
_PRODUCTION_LATENCY_BINDING = re.compile(
    r"(?:parser[_-]?)?latency(?:[_-]|$)",
    flags=re.IGNORECASE,
)


def _identity(path: str, raw: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _strict_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return set(left) == set(right) and all(
            _strict_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _validated_app_python_paths(app_root: Path) -> tuple[Path, ...]:
    """Enumerate app sources without following an unreviewed filesystem edge."""

    if not app_root.is_dir() or app_root.is_symlink():
        raise readiness.ReadinessContractError("latency continuity app root differs")
    pending = [app_root]
    python_paths: list[Path] = []
    entry_count = 0
    while pending:
        directory = pending.pop()
        try:
            children: list[Path] = []
            for child in directory.iterdir():
                entry_count += 1
                if entry_count > _MAXIMUM_APP_ENTRIES:
                    raise readiness.ReadinessContractError(
                        "latency continuity app entry count differs"
                    )
                children.append(child)
            children.sort(key=lambda path: path.name)
        except OSError as exc:
            raise readiness.ReadinessContractError(
                "latency continuity app binding differs"
            ) from exc
        for child in children:
            if child.is_symlink():
                raise readiness.ReadinessContractError(
                    "latency continuity app binding differs"
                )
            relative_parts = child.relative_to(app_root).parts
            if any(
                _PRODUCTION_LATENCY_MODULE.search(part)
                for part in relative_parts
            ):
                raise readiness.ReadinessContractError(
                    "latency continuity production latency module differs"
                )
            if child.is_dir():
                pending.append(child)
                continue
            if not child.is_file():
                raise readiness.ReadinessContractError(
                    "latency continuity app binding differs"
                )
            if child.suffix == ".py":
                python_paths.append(child)
    paths = tuple(sorted(python_paths))
    if len(paths) > _MAXIMUM_APP_FILES:
        raise readiness.ReadinessContractError("latency continuity app file count differs")
    return paths


def _bound_read(root: Path, path: PurePosixPath, *, label: str) -> bytes:
    raw, _ = historical._read_bound_file(
        root,
        str(path),
        maximum_bytes=_MAXIMUM_SOURCE_BYTES,
        label=label,
    )
    return raw


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = metrics._load_strict_json(raw, error=f"{label} strict JSON differs")
    except metrics.MetricsExecutionError as exc:
        raise readiness.ReadinessContractError(str(exc)) from exc
    if not isinstance(value, dict):
        raise readiness.ReadinessContractError(f"{label} JSON object differs")
    return value


def _validate_exact_file(
    root: Path,
    expected: Mapping[str, Any],
    *,
    label: str,
    maximum_bytes: int = _MAXIMUM_RECORD_BYTES,
) -> bytes:
    raw, _ = historical._read_bound_file(
        root,
        expected["path"],
        maximum_bytes=maximum_bytes,
        label=label,
    )
    expected_identity = {
        key: expected[key] for key in ("path", "sha256", "size_bytes")
    }
    if not _strict_equal(_identity(expected["path"], raw), expected_identity):
        raise readiness.ReadinessContractError(f"{label} identity differs")
    return raw


def _validate_renewal_record(record: Mapping[str, Any]) -> None:
    expected_keys = {
        "schema_version",
        "decision_id",
        "status",
        "date",
        "scope",
        "immutable_attempt_48",
        "sealed_failed_history",
        "unchanged_ceilings",
        "strict_final_artifact",
        "complete_companion",
        "default_off_rollback",
        "non_waived_gates",
        "review_due_no_later_than",
        "hard_expiry",
        "expires_before",
        "claims",
    }
    if set(record) != expected_keys:
        raise readiness.ReadinessContractError("latency continuity renewal keys differ")
    if (
        record["schema_version"] != "1.0"
        or record["decision_id"]
        != "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260808-PHASE-LATENCY-CONTINUITY"
        or record["status"]
        != "accepted_by_explicit_sponsor_authorization_pending_exact_independent_review_before_story_done"
        or record["date"] != "2026-08-08"
    ):
        raise readiness.ReadinessContractError("latency continuity renewal identity differs")
    if not _strict_equal(
        record["scope"],
        {
            "included_story_ids": [f"LAT-US{index:02d}" for index in range(1, 9)],
            "default_off_only": True,
            "maximum_in_progress_stories": 1,
            "production_enablement": False,
            "phase_04_behavior_change": False,
            "phase_05_authority": False,
        },
    ):
        raise readiness.ReadinessContractError("latency continuity renewal scope differs")
    if not _strict_equal(record["immutable_attempt_48"], EXPECTED_ATTEMPT_FACTS):
        raise readiness.ReadinessContractError("latency continuity attempt-48 facts differ")
    if not _strict_equal(record["sealed_failed_history"], EXPECTED_FAILED_HISTORY):
        raise readiness.ReadinessContractError("latency continuity failed history differs")
    if not _strict_equal(record["unchanged_ceilings"], EXPECTED_CEILINGS):
        raise readiness.ReadinessContractError("latency continuity ceilings differ")
    if (
        record["strict_final_artifact"] != "absent"
        or record["complete_companion"] != "quarantined"
    ):
        raise readiness.ReadinessContractError("latency continuity strict-final state differs")
    if not _strict_equal(
        record["default_off_rollback"],
        {
            "latency_flag_prefix": "PARSER_LATENCY_",
            "disable_order": "reverse_dependency_order",
            "running_region_flag": "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED",
            "running_region_default": False,
            "exact_predecessor_required": True,
        },
    ):
        raise readiness.ReadinessContractError("latency continuity rollback differs")
    if not _strict_equal(record["non_waived_gates"], EXPECTED_NON_WAIVED_GATES):
        raise readiness.ReadinessContractError("latency continuity non-waived gates differ")
    if (
        record["review_due_no_later_than"] != "2026-09-02"
        or record["hard_expiry"] != "2026-09-02T23:59:59Z"
        or not _strict_equal(record["expires_before"], EXPECTED_EXPIRES_BEFORE)
    ):
        raise readiness.ReadinessContractError("latency continuity expiry differs")
    if not _strict_equal(
        record["claims"],
        {
            "strict_current_artifact_pass": False,
            "story_completion": False,
            "phase_exit": False,
            "production_approval": False,
        },
    ):
        raise readiness.ReadinessContractError("latency continuity claims differ")


def _validate_attempt_and_history(root: Path) -> None:
    raw = _validate_exact_file(
        root,
        EXPECTED_ATTEMPT_48_IDENTITY,
        label="latency continuity attempt 48",
        maximum_bytes=metrics.PRIOR_ARTIFACT_READ_CAP_BYTES,
    )
    attempt = _strict_json(raw, label="latency continuity attempt 48")
    if (
        attempt.get("status") != "failed_measurement_candidate"
        or attempt.get("semantic_sha256")
        != EXPECTED_ATTEMPT_48_IDENTITY["semantic_sha256"]
        or metrics._artifact_semantic_sha256(attempt)
        != EXPECTED_ATTEMPT_48_IDENTITY["semantic_sha256"]
        or attempt.get("running_region_projection", {})
        .get("targets", {})
        .get("ny-timetable", {})
        .get("summary", {})
        .get("latency_p95_seconds")
        != 0.05094675
    ):
        raise readiness.ReadinessContractError("latency continuity attempt 48 differs")

    paths = metrics.discover_existing_metrics_artifact_paths(root)
    failed = tuple(
        path for path in paths if metrics.FAILED_ARTIFACT_PATTERN.fullmatch(path)
    )
    expected_paths = tuple(
        "tracker/phase-03-layout/evidence/"
        f"P03-US08-running-region-metrics-attempt-{attempt_number:02d}-failed.json"
        for attempt_number in range(1, 56)
    )
    if failed != expected_paths or str(metrics.FINAL_ARTIFACT_RELATIVE_PATH) in paths:
        raise readiness.ReadinessContractError("latency continuity artifact set differs")
    records: list[dict[str, Any]] = []
    for path in failed:
        artifact_raw = _bound_read(root, PurePosixPath(path), label="failed history")
        artifact = _strict_json(artifact_raw, label="failed history")
        if (
            artifact.get("status") != "failed_measurement_candidate"
            or artifact.get("retained_path") != path
            or artifact.get("semantic_sha256")
            != metrics._artifact_semantic_sha256(artifact)
        ):
            raise readiness.ReadinessContractError("latency continuity history differs")
        records.append(
            {
                "path": path,
                "size_bytes": len(artifact_raw),
                "sha256": hashlib.sha256(artifact_raw).hexdigest(),
                "status": "failed_measurement_candidate",
                "semantic_sha256": artifact["semantic_sha256"],
            }
        )
    manifest = hashlib.sha256(
        json.dumps(
            records,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if manifest != EXPECTED_FAILED_HISTORY["manifest_sha256"]:
        raise readiness.ReadinessContractError("latency continuity history manifest differs")


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        values = [_static_string(value) for value in node.values]
        return "".join(values) if all(value is not None for value in values) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        return left + right if left is not None and right is not None else None
    return None


def _node_has_protected_atom(node: ast.AST) -> bool:
    for descendant in ast.walk(node):
        values: list[str] = []
        if isinstance(descendant, ast.Name):
            values.append(descendant.id)
        elif isinstance(descendant, ast.Attribute):
            values.append(descendant.attr)
        elif isinstance(descendant, ast.alias):
            values.append(descendant.name)
            if descendant.asname is not None:
                values.append(descendant.asname)
        elif isinstance(descendant, ast.ImportFrom):
            if descendant.module is not None:
                values.append(descendant.module)
        elif isinstance(descendant, ast.keyword) and descendant.arg is not None:
            values.append(descendant.arg)
        elif isinstance(descendant, (ast.Constant, ast.JoinedStr, ast.BinOp)):
            value = _static_string(descendant)
            if value is not None:
                values.append(value)
        elif isinstance(descendant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            values.append(descendant.name)
        if any(_PROTECTED_ATOM.search(value) for value in values):
            return True
    return False


def _node_has_production_latency_binding(node: ast.AST) -> bool:
    """Recognize direct or statically reconstructed PARSER_LATENCY bindings."""

    for descendant in ast.walk(node):
        values: list[str] = []
        if isinstance(descendant, ast.Name):
            values.append(descendant.id)
        elif isinstance(descendant, ast.Attribute):
            values.append(descendant.attr)
        elif isinstance(descendant, ast.alias):
            values.append(descendant.name)
            if descendant.asname is not None:
                values.append(descendant.asname)
        elif isinstance(descendant, ast.ImportFrom):
            if descendant.module is not None:
                values.append(descendant.module)
        elif isinstance(descendant, ast.keyword) and descendant.arg is not None:
            values.append(descendant.arg)
        elif isinstance(descendant, (ast.Constant, ast.JoinedStr, ast.BinOp)):
            value = _static_string(descendant)
            if value is not None:
                values.append(value)
        elif isinstance(descendant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            values.append(descendant.name)
        if any(_PRODUCTION_LATENCY_BINDING.search(value) for value in values):
            return True
    return False


def _statement_header_nodes(statement: ast.stmt) -> tuple[ast.AST, ...]:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return tuple(statement.decorator_list) + (ast.Constant(statement.name),)
    if isinstance(statement, (ast.If, ast.While)):
        return (statement.test,)
    if isinstance(statement, (ast.For, ast.AsyncFor)):
        return (statement.target, statement.iter)
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return tuple(item.context_expr for item in statement.items)
    if isinstance(statement, ast.Try):
        return ()
    if isinstance(statement, ast.Match):
        return (statement.subject,)
    return (statement,)


def _statement_bodies(statement: ast.stmt) -> tuple[list[ast.stmt], ...]:
    bodies: list[list[ast.stmt]] = []
    for field_name in ("body", "orelse", "finalbody"):
        value = getattr(statement, field_name, None)
        if isinstance(value, list):
            bodies.append(value)
    if isinstance(statement, ast.Try):
        bodies.extend(handler.body for handler in statement.handlers)
    if isinstance(statement, ast.Match):
        bodies.extend(case.body for case in statement.cases)
    return tuple(bodies)


def _control_context(statement: ast.stmt) -> str | None:
    """Return a body-free control descriptor for protected reachability."""

    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        descriptor = {
            "kind": type(statement).__name__,
            "name": statement.name,
            "args": ast.dump(
                statement.args,
                annotate_fields=True,
                include_attributes=False,
            ),
            "decorators": [
                ast.dump(value, annotate_fields=True, include_attributes=False)
                for value in statement.decorator_list
            ],
            "returns": (
                ast.dump(
                    statement.returns,
                    annotate_fields=True,
                    include_attributes=False,
                )
                if statement.returns is not None
                else None
            ),
            "type_comment": statement.type_comment,
        }
        return json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    if isinstance(statement, ast.ClassDef):
        descriptor = {
            "kind": "ClassDef",
            "name": statement.name,
            "bases": [
                ast.dump(value, annotate_fields=True, include_attributes=False)
                for value in statement.bases
            ],
            "keywords": [
                ast.dump(value, annotate_fields=True, include_attributes=False)
                for value in statement.keywords
            ],
            "decorators": [
                ast.dump(value, annotate_fields=True, include_attributes=False)
                for value in statement.decorator_list
            ],
        }
        return json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    if isinstance(statement, (ast.If, ast.While)):
        return ast.dump(statement.test, annotate_fields=True, include_attributes=False)
    if isinstance(statement, (ast.For, ast.AsyncFor)):
        return ast.dump(
            ast.Tuple(elts=[statement.target, statement.iter], ctx=ast.Load()),
            annotate_fields=True,
            include_attributes=False,
        )
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return ast.dump(
            ast.Tuple(
                elts=[item.context_expr for item in statement.items],
                ctx=ast.Load(),
            ),
            annotate_fields=True,
            include_attributes=False,
        )
    if isinstance(statement, ast.Try):
        descriptor = {
            "kind": "Try",
            "handlers": [
                {
                    "type": (
                        ast.dump(
                            handler.type,
                            annotate_fields=True,
                            include_attributes=False,
                        )
                        if handler.type is not None
                        else None
                    ),
                    "name": handler.name,
                }
                for handler in statement.handlers
            ],
            "has_orelse": bool(statement.orelse),
            "has_finally": bool(statement.finalbody),
        }
        return json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    if isinstance(statement, ast.Match):
        return ast.dump(
            statement.subject,
            annotate_fields=True,
            include_attributes=False,
        )
    return None


def running_region_integration_projection(root: Path) -> dict[str, Any]:
    """Project only direct protected integration statements across app code."""

    app_root = root / "app"
    entries: list[dict[str, Any]] = []
    paths = _validated_app_python_paths(app_root)

    def collect(
        statements: list[ast.stmt],
        *,
        path: str,
        contexts: tuple[str, ...] = (),
    ) -> None:
        for statement in statements:
            headers = _statement_header_nodes(statement)
            if headers and any(_node_has_protected_atom(node) for node in headers):
                entries.append(
                    {
                        "path": path,
                        "kind": type(statement).__name__,
                        "contexts": list(contexts),
                        "ast": ast.dump(statement, annotate_fields=True, include_attributes=False),
                    }
                )
                continue
            context = _control_context(statement)
            next_contexts = contexts + ((context,) if context is not None else ())
            for body in _statement_bodies(statement):
                collect(body, path=path, contexts=next_contexts)

    for source_path in paths:
        if source_path.is_symlink() or not source_path.is_file():
            raise readiness.ReadinessContractError("latency continuity app binding differs")
        relative = source_path.relative_to(root).as_posix()
        raw = _bound_read(
            root,
            PurePosixPath(relative),
            label="latency continuity app source",
        )
        if relative == PROTECTED_RUNNING_REGION_MODULE_IDENTITY["path"]:
            # The implementation module is byte-pinned separately.  This
            # projection covers only its integration surface in shared files.
            continue
        try:
            tree = ast.parse(raw, filename=relative)
        except (SyntaxError, ValueError) as exc:
            raise readiness.ReadinessContractError(
                "latency continuity app syntax differs"
            ) from exc
        collect(tree.body, path=relative)
    projection_raw = json.dumps(
        entries,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "entry_count": len(entries),
        "sha256": hashlib.sha256(projection_raw).hexdigest(),
    }


def _validate_dependency_delta(root: Path, custody: Mapping[str, Any]) -> None:
    pyproject_raw = _validate_exact_file(
        root,
        EXPECTED_CURRENT_PYPROJECT_IDENTITY,
        label="latency continuity pyproject",
        maximum_bytes=metrics.MAX_DEPENDENCY_MANIFEST_BYTES,
    )
    uv_raw = _validate_exact_file(
        root,
        EXPECTED_UV_LOCK_IDENTITY,
        label="latency continuity uv lock",
        maximum_bytes=metrics.MAX_DEPENDENCY_MANIFEST_BYTES,
    )
    if pyproject_raw.count(PYTEST_MARKER_DELTA) != 1:
        raise readiness.ReadinessContractError("latency continuity pyproject delta differs")
    predecessor_raw = pyproject_raw.replace(PYTEST_MARKER_DELTA, b"", 1)
    if not _strict_equal(
        _identity("pyproject.toml", predecessor_raw),
        EXPECTED_P04_PYPROJECT_IDENTITY,
    ):
        raise readiness.ReadinessContractError("latency continuity pyproject ancestry differs")
    try:
        current = tomllib.loads(pyproject_raw.decode("utf-8"))
        predecessor = tomllib.loads(predecessor_raw.decode("utf-8"))
        lock = tomllib.loads(uv_raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise readiness.ReadinessContractError("latency continuity manifest syntax differs") from exc
    current_without_pytest = dict(current)
    current_without_pytest.pop("tool", None)
    predecessor_without_pytest = dict(predecessor)
    predecessor_without_pytest.pop("tool", None)
    if not _strict_equal(current_without_pytest, predecessor_without_pytest):
        raise readiness.ReadinessContractError("latency continuity dependency semantics differ")
    root_packages = [
        package
        for package in lock.get("package", [])
        if isinstance(package, Mapping) and package.get("name") == "document-parse-api"
    ]
    if len(root_packages) != 1:
        raise readiness.ReadinessContractError("latency continuity lock root differs")
    if not _strict_equal(
        custody.get("dependency_manifest_identities"),
        {
            "pyproject_predecessor": EXPECTED_P04_PYPROJECT_IDENTITY,
            "pyproject_current": EXPECTED_CURRENT_PYPROJECT_IDENTITY,
            "uv_lock_predecessor_and_current": EXPECTED_UV_LOCK_IDENTITY,
        },
    ):
        raise readiness.ReadinessContractError("latency continuity custody manifest record differs")


def _validate_predecessor_source_identities(
    root: Path,
    custody: Mapping[str, Any],
) -> None:
    if not _strict_equal(
        custody.get("exact_predecessor_source_identities"),
        EXPECTED_PREDECESSOR_SOURCE_IDENTITIES,
    ):
        raise readiness.ReadinessContractError(
            "latency continuity predecessor source record differs"
        )
    for expected in EXPECTED_PREDECESSOR_SOURCE_IDENTITIES:
        _validate_exact_file(
            root,
            expected,
            label="latency continuity predecessor source",
            maximum_bytes=_MAXIMUM_SOURCE_BYTES,
        )


def _validate_production_latency_isolation(root: Path) -> None:
    """Fail closed unless LAT-US01 attribution remains outside production."""

    app_root = root / "app"
    paths = _validated_app_python_paths(app_root)
    for source_path in paths:
        if source_path.is_symlink() or not source_path.is_file():
            raise readiness.ReadinessContractError(
                "latency continuity production source binding differs"
            )
        relative = source_path.relative_to(root).as_posix()
        raw = _bound_read(
            root,
            PurePosixPath(relative),
            label="latency continuity production source",
        )
        try:
            tree = ast.parse(raw, filename=relative)
        except (SyntaxError, ValueError) as exc:
            raise readiness.ReadinessContractError(
                "latency continuity production source syntax differs"
            ) from exc
        if _node_has_production_latency_binding(tree):
            raise readiness.ReadinessContractError(
                "latency continuity production latency binding differs"
            )


def _validate_custody_record(root: Path, record: Mapping[str, Any]) -> None:
    expected_keys = {
        "schema_version",
        "record_kind",
        "renewal_decision_identity",
        "renewal_record_identity",
        "historical_validator_policy",
        "historical_validator_identity",
        "dependency_manifest_identities",
        "additive_dependency_delta",
        "exact_predecessor_source_identities",
        "protected_running_region_module_identity",
        "running_region_integration_projection",
        "default_off_observation",
        "claims",
    }
    if set(record) != expected_keys:
        raise readiness.ReadinessContractError("latency continuity custody keys differ")
    if (
        record["schema_version"] != "1.0"
        or record["record_kind"]
        != "p03_us08_phase_latency_live_custody_reconciliation"
        or not _strict_equal(
            record["renewal_decision_identity"], EXPECTED_RENEWAL_DECISION_IDENTITY
        )
        or not _strict_equal(
            record["renewal_record_identity"], EXPECTED_RENEWAL_RECORD_IDENTITY
        )
        or record["historical_validator_policy"]
        != {
            "sealed_records_modified": False,
            "historical_validators_weakened": False,
            "successor_owned_additive_guard": True,
        }
        or not _strict_equal(
            record["historical_validator_identity"], HISTORICAL_VALIDATOR_IDENTITY
        )
        or record["additive_dependency_delta"]
        != {
            "scope": "pytest marker registration only",
            "runtime_dependency_change": False,
            "resolved_package_change": False,
            "uv_lock_change": False,
            "gate_waived": False,
        }
        or not _strict_equal(
            record["protected_running_region_module_identity"],
            PROTECTED_RUNNING_REGION_MODULE_IDENTITY,
        )
        or not _strict_equal(
            record["running_region_integration_projection"],
            EXPECTED_RUNNING_REGION_INTEGRATION_PROJECTION,
        )
        or record["default_off_observation"]
        != {
            "production_latency_flags": [],
            "production_latency_modules": [],
            "production_latency_runtime_hooks": False,
            "attribution_scope": "disposable_benchmark_worker_only",
            "rollback_action": "stop_disposable_benchmark_worker",
            "running_region_flag": "layout_running_regions_enabled",
            "running_region_default": False,
        }
        or record["claims"]
        != {
            "strict_current_artifact_pass": False,
            "production_enablement": False,
            "phase_04_behavior_change": False,
            "phase_05_authority": False,
            "non_waived_gate_removed": False,
        }
    ):
        raise readiness.ReadinessContractError("latency continuity custody record differs")
    _validate_dependency_delta(root, record)
    _validate_predecessor_source_identities(root, record)
    _validate_production_latency_isolation(root)


def _current_utc_date() -> date:
    """Return the non-overridable live UTC date used by the custody gate."""

    return datetime.now(tz=UTC).date()


def validate_latency_continuity_renewal(
    repository_root: Path,
) -> dict[str, Any]:
    """Validate the narrow live phase-latency successor custody chain."""

    root = metrics._resolve_repository_root(repository_root)
    decision_raw = _validate_exact_file(
        root,
        EXPECTED_RENEWAL_DECISION_IDENTITY,
        label="latency continuity decision",
    )
    renewal_raw = _validate_exact_file(
        root,
        EXPECTED_RENEWAL_RECORD_IDENTITY,
        label="latency continuity renewal",
    )
    custody_raw = _validate_exact_file(
        root,
        EXPECTED_CUSTODY_RECORD_IDENTITY,
        label="latency continuity custody",
    )
    renewal = _strict_json(renewal_raw, label="latency continuity renewal")
    custody = _strict_json(custody_raw, label="latency continuity custody")
    if renewal_raw != (json.dumps(renewal, indent=2) + "\n\n").encode("utf-8"):
        raise readiness.ReadinessContractError("latency continuity renewal bytes differ")
    if custody_raw != (json.dumps(custody, indent=2) + "\n").encode("utf-8"):
        raise readiness.ReadinessContractError("latency continuity custody bytes differ")
    if renewal["decision_id"].encode("utf-8") not in decision_raw:
        raise readiness.ReadinessContractError("latency continuity decision binding differs")
    _validate_renewal_record(renewal)
    _validate_custody_record(root, custody)
    _validate_attempt_and_history(root)

    if _current_utc_date() > date(2026, 9, 2):
        raise readiness.ReadinessContractError("latency continuity renewal expired")

    protected_raw = _validate_exact_file(
        root,
        PROTECTED_RUNNING_REGION_MODULE_IDENTITY,
        label="protected running-region implementation",
        maximum_bytes=_MAXIMUM_SOURCE_BYTES,
    )
    del protected_raw
    _validate_exact_file(
        root,
        HISTORICAL_VALIDATOR_IDENTITY,
        label="historical P03 exception validator",
        maximum_bytes=_MAXIMUM_SOURCE_BYTES,
    )
    projection = running_region_integration_projection(root)
    if not _strict_equal(projection, EXPECTED_RUNNING_REGION_INTEGRATION_PROJECTION):
        raise readiness.ReadinessContractError(
            "protected running-region semantic/runtime projection differs"
        )
    return {
        "decision_id": renewal["decision_id"],
        "attempt_48": dict(EXPECTED_ATTEMPT_FACTS),
        "failed_history": dict(EXPECTED_FAILED_HISTORY),
        "unchanged_ceilings": dict(EXPECTED_CEILINGS),
        "production_latency_flags": [],
        "production_latency_modules": [],
        "rollback_action": "stop_disposable_benchmark_worker",
        "review_due_no_later_than": renewal["review_due_no_later_than"],
        "strict_current_artifact_pass": False,
        "production_approval": False,
    }


__all__ = [
    "ATTEMPT_48_PATH",
    "CUSTODY_RECORD_PATH",
    "EXPECTED_ATTEMPT_48_IDENTITY",
    "EXPECTED_ATTEMPT_FACTS",
    "EXPECTED_CEILINGS",
    "EXPECTED_CUSTODY_RECORD_IDENTITY",
    "EXPECTED_FAILED_HISTORY",
    "EXPECTED_NON_WAIVED_GATES",
    "EXPECTED_PREDECESSOR_SOURCE_IDENTITIES",
    "EXPECTED_RENEWAL_DECISION_IDENTITY",
    "EXPECTED_RENEWAL_RECORD_IDENTITY",
    "EXPECTED_RUNNING_REGION_INTEGRATION_PROJECTION",
    "PROTECTED_RUNNING_REGION_MODULE_IDENTITY",
    "PYTEST_MARKER_DELTA",
    "RENEWAL_DECISION_PATH",
    "RENEWAL_RECORD_PATH",
    "running_region_integration_projection",
    "validate_latency_continuity_renewal",
]
