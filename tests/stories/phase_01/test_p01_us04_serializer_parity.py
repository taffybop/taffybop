from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.services.ir import build_document_ir
from app.services.presentation import build_canonical_presentation
from app.services.serializer import to_markdown


WORKSPACE = Path(__file__).resolve().parents[3]
FROZEN_CORPUS_ROOT = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "p00-us10-corpus-20260729-03"
)
FRONTEND_PROJECTION = (
    WORKSPACE / "tests" / "benchmarks" / "frontend_projection.mts"
)
CASE_IDS = (
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


@dataclass(frozen=True)
class ParityBundle:
    canonical_contracts: dict[str, dict[str, Any]]
    canonical_payloads: dict[str, dict[str, Any]]
    frozen_markdown: dict[str, bytes]
    frozen_unchanged: bool
    legacy_payloads: dict[str, dict[str, Any]]
    projections: dict[str, dict[str, Any]]
    runtime_version: str
    synthetic_payloads: dict[str, dict[str, Any]]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_frozen_payload(case_id: str) -> dict[str, Any]:
    return json.loads(
        (FROZEN_CORPUS_ROOT / case_id / "our-output.json").read_text(
            encoding="utf-8"
        )
    )


def _frozen_artifacts() -> dict[Path, bytes]:
    paths = [
        path
        for case_id in CASE_IDS
        for path in (
            FROZEN_CORPUS_ROOT / case_id / "our-output.json",
            FROZEN_CORPUS_ROOT / case_id / "our-output.md",
        )
    ]
    return {path: path.read_bytes() for path in paths}


def _node_binary() -> Path:
    configured = os.environ.get("PARSER_NODE_BINARY")
    candidates = [
        Path(configured) if configured else None,
        Path("/opt/homebrew/opt/node@24/bin/node"),
        Path(shutil.which("node")) if shutil.which("node") else None,
    ]
    diagnostics: list[str] = []
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        completed = subprocess.run(
            [str(candidate), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        version = completed.stdout.strip()
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
        if completed.returncode == 0 and match:
            parsed = tuple(int(part) for part in match.groups())
            if parsed >= (22, 13, 0):
                return candidate
        diagnostics.append(
            f"{candidate}: exit={completed.returncode}, version={version!r}"
        )
    pytest.fail(
        "P01-US04 requires Node >=22.13.0; checked "
        + (", ".join(diagnostics) or "no Node executables")
    )


def _synthetic_document(
    items: list[dict[str, Any]],
    *,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "document": {
            "filename": "p01-us04-synthetic.pdf",
            "mime_type": "application/pdf",
            "sha256": "4" * 64,
            "page_count": 1,
            "future_document_evidence": {"preserve": ["exactly", 1]},
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612,
                "page_height": 792,
                "unit": "pt",
                "success": True,
                "items": items,
                "warnings": [],
                "future_page_evidence": {"nested": True},
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "fixture",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
            "future_processing_evidence": "retained",
        },
        "warnings": [],
    }
    if extra_fields:
        document.update(extra_fields)
    return document


def _legacy_additive_payload() -> dict[str, Any]:
    return _synthetic_document(
        [
            {
                "id": "future-markdown",
                "type": "future_widget",
                "reading_order": 2,
                "md": "  *Opaque Markdown*  ",
                "future_item_evidence": {"source": "vNext"},
            },
            {
                "id": "future-scalar",
                "type": "future_scalar",
                "reading_order": 1,
                "value": 73,
                "future_item_evidence": ["kept", False],
            },
        ],
        extra_fields={
            "future_top_level_evidence": {
                "confidence_vector": [0.25, 0.75],
            }
        },
    )


def _ok(outcome: dict[str, Any], operation: str) -> Any:
    assert outcome["ok"] is True, (
        f"{operation} unexpectedly failed: {outcome.get('error')}"
    )
    assert "value" in outcome
    return outcome["value"]


def _assert_failed(
    outcome: dict[str, Any],
    operation: str,
) -> None:
    assert outcome["ok"] is False, (
        f"{operation} silently accepted an invalid canonical contract"
    )
    error = outcome.get("error")
    assert isinstance(error, dict)
    assert error.get("name") in {
        "CanonicalPresentationError",
        "Error",
        "TypeError",
    }
    assert "canonical_presentation" in str(error.get("message", ""))


@pytest.fixture(scope="module")
def parity_bundle(
    tmp_path_factory: pytest.TempPathFactory,
) -> ParityBundle:
    before = _frozen_artifacts()
    legacy_payloads = {
        case_id: _load_frozen_payload(case_id) for case_id in CASE_IDS
    }
    assert all(
        "canonical_presentation" not in payload
        for payload in legacy_payloads.values()
    )

    canonical_contracts: dict[str, dict[str, Any]] = {}
    canonical_payloads: dict[str, dict[str, Any]] = {}
    manifest_cases: list[dict[str, Any]] = []
    for case_id in CASE_IDS:
        legacy = legacy_payloads[case_id]
        contract = build_canonical_presentation(
            build_document_ir(deepcopy(legacy))
        ).model_dump(mode="json", exclude_none=True)
        canonical = deepcopy(legacy)
        canonical["canonical_presentation"] = contract
        canonical_contracts[case_id] = contract
        canonical_payloads[case_id] = canonical
        manifest_cases.append(
            {"id": f"canonical/{case_id}", "payload": canonical}
        )
        manifest_cases.append(
            {"id": f"legacy/{case_id}", "payload": legacy}
        )

    additive = _legacy_additive_payload()
    malformed = deepcopy(canonical_payloads["settlement-agreement"])
    malformed["canonical_presentation"] = {"schema_version": "1.0"}
    unsupported = deepcopy(canonical_payloads["settlement-agreement"])
    unsupported["canonical_presentation"]["schema_version"] = "2.0"
    synthetic_payloads = {
        "legacy-additive": additive,
        "malformed-canonical": malformed,
        "unsupported-canonical": unsupported,
    }
    manifest_cases.extend(
        {"id": f"synthetic/{case_id}", "payload": payload}
        for case_id, payload in synthetic_payloads.items()
    )

    temporary_root = tmp_path_factory.mktemp("p01-us04-parity")
    input_path = temporary_root / "batch-input.json"
    output_path = temporary_root / "batch-output.json"
    input_path.write_text(
        json.dumps(
            {"schema_version": "1.0", "cases": manifest_cases},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            str(_node_binary()),
            "--experimental-strip-types",
            str(FRONTEND_PROJECTION),
            "--batch",
            str(input_path),
            str(output_path),
        ],
        cwd=WORKSPACE,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, (
        "supported-Node frontend batch projection failed\n"
        f"stdout:\n{completed.stdout[-2000:]}\n"
        f"stderr:\n{completed.stderr[-4000:]}"
    )
    metadata = json.loads(completed.stdout)
    output_bytes = output_path.read_bytes()
    output = json.loads(output_bytes)
    assert metadata == {
        "case_count": len(manifest_cases),
        "mode": "batch",
        "node": output["node"],
        "output_sha256": _sha256(output_bytes),
        "output_size_bytes": len(output_bytes),
    }
    assert output["schema_version"] == "1.0"
    assert len(output["cases"]) == len(manifest_cases)
    projections = {
        entry["id"]: entry["projection"] for entry in output["cases"]
    }
    assert set(projections) == {
        entry["id"] for entry in manifest_cases
    }

    after = _frozen_artifacts()
    return ParityBundle(
        canonical_contracts=canonical_contracts,
        canonical_payloads=canonical_payloads,
        frozen_markdown={
            case_id: before[
                FROZEN_CORPUS_ROOT / case_id / "our-output.md"
            ]
            for case_id in CASE_IDS
        },
        frozen_unchanged=after == before,
        legacy_payloads=legacy_payloads,
        projections=projections,
        runtime_version=output["node"],
        synthetic_payloads=synthetic_payloads,
    )


def test_batch_gate_uses_supported_node_and_leaves_frozen_corpus_immutable(
    parity_bundle: ParityBundle,
) -> None:
    version = re.fullmatch(
        r"v(\d+)\.(\d+)\.(\d+)", parity_bundle.runtime_version
    )
    assert version is not None
    assert tuple(int(part) for part in version.groups()) >= (22, 13, 0)
    assert parity_bundle.frozen_unchanged
    assert tuple(parity_bundle.legacy_payloads) == CASE_IDS
    assert tuple(parity_bundle.canonical_contracts) == CASE_IDS


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_all_fifteen_canonical_documents_have_exact_frontend_markdown_and_text(
    case_id: str,
    parity_bundle: ParityBundle,
) -> None:
    contract = parity_bundle.canonical_contracts[case_id]
    payload = parity_bundle.canonical_payloads[case_id]
    projection = parity_bundle.projections[f"canonical/{case_id}"]

    assert projection["input_unchanged"] is True
    assert _ok(
        projection["document_json_preserved"],
        f"{case_id} document JSON",
    ) is True
    assert _ok(
        projection["canonical"], f"{case_id} canonical reader"
    ) == contract
    assert _ok(
        projection["canonical_pages"], f"{case_id} canonical page lookup"
    ) == [page["page_index"] for page in contract["pages"]]

    expected_document_markdown = contract["full"]["markdown"]
    frontend_document_markdown = _ok(
        projection["document_markdown"],
        f"{case_id} document Markdown",
    )
    assert (
        frontend_document_markdown.encode("utf-8")
        == expected_document_markdown.encode("utf-8")
    )
    assert (
        to_markdown(payload).encode("utf-8")
        == expected_document_markdown.encode("utf-8")
    )

    expected_page_markdown = [
        page["full"]["markdown"] for page in contract["pages"]
    ]
    frontend_page_markdown = _ok(
        projection["page_markdown"], f"{case_id} page Markdown"
    )
    frontend_page_output = _ok(
        projection["page_output_markdown"],
        f"{case_id} page Markdown output",
    )
    assert [value.encode("utf-8") for value in frontend_page_markdown] == [
        value.encode("utf-8") for value in expected_page_markdown
    ]
    assert frontend_page_output == expected_page_markdown

    normalized_result = _ok(
        projection["normalized"], f"{case_id} normalization"
    )
    assert normalized_result["serialized_matches_value"] is True
    normalized = normalized_result["value"]
    assert normalized["markdown_full"].encode("utf-8") == (
        expected_document_markdown.encode("utf-8")
    )
    assert normalized["text_full"] == contract["full"]["text"]
    assert [
        page["markdown"] for page in normalized["markdown"]["pages"]
    ] == expected_page_markdown
    assert [page["text"] for page in normalized["text"]["pages"]] == [
        page["full"]["text"] for page in contract["pages"]
    ]


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_all_fifteen_canonical_normalizations_preserve_json_and_page_views(
    case_id: str,
    parity_bundle: ParityBundle,
) -> None:
    contract = parity_bundle.canonical_contracts[case_id]
    payload = parity_bundle.canonical_payloads[case_id]
    projection = parity_bundle.projections[f"canonical/{case_id}"]
    normalized_result = _ok(
        projection["normalized"], f"{case_id} normalization"
    )
    normalized = normalized_result["value"]

    assert normalized["canonical_presentation"] == contract
    assert normalized["items"]["pages"] == sorted(
        payload["pages"], key=lambda page: page["page_index"]
    )
    assert normalized["metadata"]["schema_version"] == payload[
        "schema_version"
    ]
    assert normalized["metadata"]["document"] == payload["document"]
    assert normalized["metadata"]["processing"] == payload["processing"]
    assert normalized["metadata"]["warnings"] == payload["warnings"]
    assert "canonical_presentation" not in (
        normalized["metadata"]["additional_top_level_fields"]
    )

    for raw_page, canonical_page, markdown_page, text_page in zip(
        sorted(payload["pages"], key=lambda page: page["page_index"]),
        contract["pages"],
        normalized["markdown"]["pages"],
        normalized["text"]["pages"],
        strict=True,
    ):
        assert markdown_page["page_number"] == raw_page["page_number"]
        assert markdown_page["success"] == raw_page["success"]
        assert markdown_page["header"] == (
            canonical_page["header"]["markdown"] or None
        )
        assert markdown_page["footer"] == (
            canonical_page["footer"]["markdown"] or None
        )
        assert text_page["page_number"] == raw_page["page_number"]


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_all_fifteen_flag_off_documents_keep_frozen_legacy_markdown(
    case_id: str,
    parity_bundle: ParityBundle,
) -> None:
    payload = parity_bundle.legacy_payloads[case_id]
    expected = parity_bundle.frozen_markdown[case_id]
    projection = parity_bundle.projections[f"legacy/{case_id}"]

    assert "canonical_presentation" not in payload
    assert projection["input_unchanged"] is True
    assert _ok(
        projection["document_json_preserved"],
        f"{case_id} legacy document JSON",
    ) is True
    assert _ok(
        projection["canonical"], f"{case_id} missing canonical reader"
    ) is None
    assert _ok(
        projection["canonical_pages"],
        f"{case_id} missing canonical page lookup",
    ) == [None] * len(payload["pages"])
    assert _ok(
        projection["document_markdown"],
        f"{case_id} legacy document Markdown",
    ).encode("utf-8") == expected
    assert to_markdown(payload).encode("utf-8") == expected
    normalized = _ok(
        projection["normalized"], f"{case_id} legacy normalization"
    )["value"]
    assert "canonical_presentation" not in normalized


def test_unknown_additive_legacy_types_use_md_then_scalar_without_data_loss(
    parity_bundle: ParityBundle,
) -> None:
    payload = parity_bundle.synthetic_payloads["legacy-additive"]
    projection = parity_bundle.projections["synthetic/legacy-additive"]

    assert projection["input_unchanged"] is True
    assert _ok(projection["canonical"], "additive canonical reader") is None
    assert _ok(
        projection["document_json_preserved"], "additive document JSON"
    ) is True
    expected = "73\n\n*Opaque Markdown*\n"
    assert _ok(
        projection["document_markdown"], "additive document Markdown"
    ) == expected
    assert _ok(projection["page_markdown"], "additive page Markdown") == [
        expected
    ]
    assert _ok(
        projection["page_output_markdown"], "additive page output"
    ) == [expected]

    normalized = _ok(
        projection["normalized"], "additive normalization"
    )["value"]
    assert normalized["items"]["pages"] == payload["pages"]
    assert normalized["metadata"]["document"] == payload["document"]
    assert normalized["metadata"]["processing"] == payload["processing"]
    assert normalized["metadata"]["additional_top_level_fields"][
        "future_top_level_evidence"
    ] == payload["future_top_level_evidence"]
    assert normalized["markdown_full"] == expected
    assert normalized["text_full"] == "73\n\n*Opaque Markdown*"


@pytest.mark.parametrize(
    "case_id",
    ("malformed-canonical", "unsupported-canonical"),
)
def test_present_invalid_canonical_contracts_fail_closed_across_frontend_views(
    case_id: str,
    parity_bundle: ParityBundle,
) -> None:
    projection = parity_bundle.projections[f"synthetic/{case_id}"]

    assert projection["input_unchanged"] is True
    assert _ok(
        projection["document_json_preserved"],
        f"{case_id} raw JSON preservation",
    ) is True
    for key in (
        "canonical",
        "canonical_pages",
        "document_markdown",
        "page_markdown",
        "page_output_markdown",
        "normalized",
    ):
        _assert_failed(projection[key], f"{case_id} {key}")
