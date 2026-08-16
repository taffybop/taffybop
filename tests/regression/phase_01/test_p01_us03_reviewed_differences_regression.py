from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.services.ir import build_document_ir
from app.services.presentation import build_canonical_presentation


WORKSPACE = Path(__file__).resolve().parents[3]
EXPECTED_FROZEN_CORPUS_ROOT = (
    "tracker/phase-00-baseline/evidence/"
    "p00-us10-corpus-20260729-03"
)
MANIFEST_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-01-shared-ir"
    / "evidence"
    / "P01-US03-reviewed-differences.json"
)
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
RUN_RECORD_PATH = (
    WORKSPACE / EXPECTED_FROZEN_CORPUS_ROOT / "run-record.json"
)
RUN_RECORD_BYTES = RUN_RECORD_PATH.read_bytes()
RUN_RECORD = json.loads(RUN_RECORD_BYTES)
RUN_CASES = {
    case_record["case_id"]: case_record
    for case_record in RUN_RECORD["cases"]
}
CASE_ENTRIES = tuple(MANIFEST["cases"])
CASE_IDS = tuple(entry["case_id"] for entry in CASE_ENTRIES)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _artifact_pin(value: bytes) -> dict[str, Any]:
    return {
        "sha256": _sha256(value),
        "size_bytes": len(value),
    }


def _json_pin(value: bytes) -> dict[str, Any]:
    return {
        "sha256": _sha256(value),
        "json_size_bytes": len(value),
    }


def _assert_portable_relative_path(value: str) -> Path:
    path = Path(value)
    assert not path.is_absolute()
    assert ".." not in path.parts
    assert path.as_posix() == value
    return path


def _assert_frozen_artifact(
    artifact: dict[str, Any],
    *,
    expected_path: str,
) -> bytes:
    path = _assert_portable_relative_path(artifact["path"])
    assert path.as_posix() == expected_path
    value = (WORKSPACE / path).read_bytes()
    assert _sha256(value) == artifact["sha256"]
    assert len(value) == artifact["size_bytes"]
    return value


def _source_record(case_id: str) -> dict[str, Any]:
    return next(
        artifact
        for artifact in RUN_CASES[case_id]["source_triplet"]
        if artifact["role"] == "source"
    )


def _derive_case(case_id: str) -> dict[str, Any]:
    case_record = RUN_CASES[case_id]
    assert case_record["status"] == "success"
    raw_json_record = case_record["output"]["raw_json"]
    markdown_record = case_record["output"]["markdown"]
    legacy_json = _assert_frozen_artifact(
        raw_json_record,
        expected_path=(
            f"{EXPECTED_FROZEN_CORPUS_ROOT}/{case_id}/our-output.json"
        ),
    )
    legacy_markdown = _assert_frozen_artifact(
        markdown_record,
        expected_path=(
            f"{EXPECTED_FROZEN_CORPUS_ROOT}/{case_id}/our-output.md"
        ),
    )
    document = json.loads(legacy_json)
    source_record = _source_record(case_id)
    source_path = _assert_portable_relative_path(source_record["path"])
    source_bytes = (WORKSPACE / source_path).read_bytes()
    assert _sha256(source_bytes) == source_record["sha256"]
    assert len(source_bytes) == source_record["size_bytes"]

    ir = build_document_ir(document)
    presentation = build_canonical_presentation(ir)
    ir_payload = ir.model_dump(mode="json", exclude_none=True)
    contract_payload = presentation.model_dump(
        mode="json",
        exclude_none=True,
    )
    ir_json = _canonical_json_bytes(ir_payload)
    contract_json = _canonical_json_bytes(contract_payload)
    canonical_markdown = presentation.full.markdown.encode("utf-8")
    canonical_text = presentation.full.text.encode("utf-8")
    blocks = [
        block
        for page in presentation.pages
        for block in page.blocks
    ]
    disposition = (
        "byte-stable"
        if canonical_markdown == legacy_markdown
        else "reviewed-flag-only"
    )

    return {
        "record": {
            "case_id": case_id,
            "source_sha256": source_record["sha256"],
            "legacy_markdown": _artifact_pin(legacy_markdown),
            "canonical_document_ir": _json_pin(ir_json),
            "canonical_contract": _json_pin(contract_json),
            "canonical_markdown": _artifact_pin(canonical_markdown),
            "canonical_text": _artifact_pin(canonical_text),
            "blocks": {
                "total": len(blocks),
                "included": sum(
                    block.omission_reason is None for block in blocks
                ),
            },
            "omissions": [
                {
                    "primary_element_id": block.primary_element_id,
                    "reason": block.omission_reason,
                    "suppressed_by_element_id": (
                        block.suppressed_by_element_id
                    ),
                }
                for block in blocks
                if block.omission_reason is not None
            ],
            "disposition": disposition,
        },
        "ir_payload": ir_payload,
        "contract_payload": contract_payload,
        "legacy_markdown": legacy_markdown,
        "canonical_markdown": canonical_markdown,
        "presentation": presentation,
    }


@pytest.fixture(scope="module")
def derived_cases() -> dict[str, dict[str, Any]]:
    return {case_id: _derive_case(case_id) for case_id in CASE_IDS}


def test_reviewed_difference_manifest_authority_and_summary() -> None:
    assert set(MANIFEST) == {
        "schema_version",
        "story_id",
        "policy_id",
        "frozen_corpus_root",
        "authority",
        "derivation",
        "summary",
        "cases",
    }
    assert MANIFEST["schema_version"] == "1.0"
    assert MANIFEST["story_id"] == "P01-US03"
    assert MANIFEST["policy_id"] == "canonical-presentation-v1"
    assert MANIFEST["frozen_corpus_root"] == EXPECTED_FROZEN_CORPUS_ROOT
    assert MANIFEST["authority"] == {
        "run_record": {
            "path": (
                f"{EXPECTED_FROZEN_CORPUS_ROOT}/run-record.json"
            ),
            **_artifact_pin(RUN_RECORD_BYTES),
        },
        "corpus_registry": {
            "path": (
                "tracker/phase-00-baseline/evidence/"
                "P00-US04-corpus-registry.json"
            ),
            **_artifact_pin(
                (
                    WORKSPACE
                    / "tracker"
                    / "phase-00-baseline"
                    / "evidence"
                    / "P00-US04-corpus-registry.json"
                ).read_bytes()
            ),
        },
    }
    assert RUN_RECORD["run_id"] == "p00-us10-corpus-20260729-03"
    assert RUN_RECORD["status"] == "success"
    assert RUN_RECORD["requested_case_count"] == 15
    assert RUN_RECORD["success_count"] == 15
    assert MANIFEST["derivation"] == {
        "source_run_id": "p00-us10-corpus-20260729-03",
        "input_contract": (
            "Frozen normalized v1 our-output.json files; Phase 0 retained "
            "no raw Docling graph."
        ),
        "canonical_json_encoding": (
            "UTF-8, sorted object keys, compact separators, "
            "ensure_ascii=false, allow_nan=false, exclude_none=true"
        ),
    }
    assert CASE_IDS == tuple(RUN_RECORD["selected_case_ids"])
    assert len(CASE_IDS) == len(set(CASE_IDS)) == 15

    dispositions = [entry["disposition"] for entry in CASE_ENTRIES]
    assert MANIFEST["summary"] == {
        "case_count": 15,
        "changed_case_count": 10,
        "byte_stable_case_count": 5,
        "unreviewed_difference_count": 0,
        "hash_scope": (
            "Canonical contract hashes cover ordered block IDs, "
            "relationship IDs, and contributing element IDs; canonical "
            "DocumentIR hashes cover the complete ordered IR graph."
        ),
    }
    assert dispositions.count("reviewed-flag-only") == 10
    assert dispositions.count("byte-stable") == 5


@pytest.mark.parametrize(
    "manifest_entry",
    CASE_ENTRIES,
    ids=CASE_IDS,
)
def test_every_reviewed_difference_field_matches_current_derivation(
    manifest_entry: dict[str, Any],
    derived_cases: dict[str, dict[str, Any]],
) -> None:
    derived = derived_cases[manifest_entry["case_id"]]

    # Whole-record equality pins every per-case field, including the exact
    # ordered omission primary/reason/suppressor records.
    assert derived["record"] == manifest_entry

    observed_changed = (
        derived["canonical_markdown"] != derived["legacy_markdown"]
    )
    assert observed_changed is (
        manifest_entry["disposition"] == "reviewed-flag-only"
    )

    contributions = [
        element_id
        for page in derived["presentation"].pages
        for block in page.blocks
        if block.omission_reason is None
        for element_id in block.contributing_element_ids
    ]
    assert len(contributions) == len(set(contributions))


def test_observed_dispositions_leave_no_unreviewed_difference(
    derived_cases: dict[str, dict[str, Any]],
) -> None:
    unreviewed = [
        entry["case_id"]
        for entry in CASE_ENTRIES
        if derived_cases[entry["case_id"]]["record"] != entry
    ]

    assert unreviewed == []
    assert MANIFEST["summary"]["unreviewed_difference_count"] == len(
        unreviewed
    )


def test_canonical_contract_hash_covers_ordered_identity_lists(
    derived_cases: dict[str, dict[str, Any]],
) -> None:
    contract = derived_cases["catastrophe-recap"]["contract_payload"]
    expected_hash = _sha256(_canonical_json_bytes(contract))
    manifest_entry = next(
        entry
        for entry in CASE_ENTRIES
        if entry["case_id"] == "catastrophe-recap"
    )
    assert expected_hash == manifest_entry["canonical_contract"]["sha256"]
    blocks = [
        block
        for page in contract["pages"]
        for block in page["blocks"]
    ]
    relationship_block = next(
        block for block in blocks if block["relationship_ids"]
    )
    contribution_block = next(
        block for block in blocks if block["contributing_element_ids"]
    )

    mutations = []

    changed_block_id = deepcopy(contract)
    changed_block_id["pages"][0]["blocks"][0]["id"] += "-changed"
    mutations.append(changed_block_id)

    changed_relationship_id = deepcopy(contract)
    target = next(
        block
        for page in changed_relationship_id["pages"]
        for block in page["blocks"]
        if block["id"] == relationship_block["id"]
    )
    target["relationship_ids"][0] += "-changed"
    mutations.append(changed_relationship_id)

    changed_contribution_id = deepcopy(contract)
    target = next(
        block
        for page in changed_contribution_id["pages"]
        for block in page["blocks"]
        if block["id"] == contribution_block["id"]
    )
    target["contributing_element_ids"][0] += "-changed"
    mutations.append(changed_contribution_id)

    assert all(
        _sha256(_canonical_json_bytes(mutation)) != expected_hash
        for mutation in mutations
    )
