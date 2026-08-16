"""Retained quality and resource metrics for P03-US03."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as importlib_metadata
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.config import Settings
from app.services.ir import round_trip_document
from app.services.layout import apply_layout_projection
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
from tests.stories.phase_03.test_p03_us03_source_notes import (
    _box,
    _document,
    _graph,
    _item,
    _table,
    _text,
)


CASES = (
    "catastrophe-recap",
    "clinical-study",
    "health-report",
    "finance-10k",
)
PERFORMANCE_CASES = ("catastrophe-recap", "clinical-study")
PHASE_02_PERFORMANCE_BASELINES = {
    "catastrophe-recap": {
        "wall_seconds": 8.50,
        "peak_rss_mib": 1427.5,
    },
    "clinical-study": {
        "wall_seconds": 13.96,
        "peak_rss_mib": 1561.9,
    },
}
EXPECTED_INPUTS = {
    "catastrophe-recap": {
        "sha256": (
            "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
        ),
        "size_bytes": 58779,
    },
    "clinical-study": {
        "sha256": (
            "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2"
        ),
        "size_bytes": 750004,
    },
    "health-report": {
        "sha256": (
            "fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181"
        ),
        "size_bytes": 222282,
    },
    "finance-10k": {
        "sha256": (
            "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086"
        ),
        "size_bytes": 87105,
    },
}
AON_NOTE = "Data: Aon Catastrophe Insight"
CLINICAL_REVIEWED_NOTES = (
    "1 At least 4 out of 5 SbS sessions completed.",
    "2 Less than 4 SbS sessions completed.",
    "3 Highest education level started.",
    "1 Pooled descriptive statistics across all imputed datasets.",
    (
        "2 As covariates the models included: baseline score, gender, age, "
        "marital status, education, occupation, and postmigration living "
        "difficulties."
    ),
    (
        "3 Treatment effects were pooled based on multiple imputations (100), "
        "assuming missing at random, using progressive mean matching (PMM)."
    ),
    (
        "4 Hedges' g effect sizes were derived by combining multiple "
        "imputation estimates using Rubin's rules."
    ),
)
HEALTH_REVIEWED_NOTE = (
    "Note: The EU average is weighted. Data for the United Kingdom refer to "
    "2020 and have been calculated by the OECD. Source: Eurostat "
    "(hlth_cd_asdr2)."
)
CLINICAL_LINK_TARGETS = (
    "https://doi.org/10.1371/journal.pmed.1004460.t001",
    "https://doi.org/10.1371/journal.pmed.1004460.g001",
    "https://doi.org/10.1371/journal.pmed.1004460.t002",
)
HEALTH_LINK_TARGETS = (
    "https://stat.link/hufsd5",
    "https://stat.link/styxji",
)
EXPECTED_REVIEWED_NOTES = {
    "catastrophe-recap": (AON_NOTE,),
    "clinical-study": CLINICAL_REVIEWED_NOTES,
    "health-report": (),
    "finance-10k": (),
}
EXPECTED_LINK_TARGETS = {
    "catastrophe-recap": (),
    "clinical-study": CLINICAL_LINK_TARGETS,
    "health-report": HEALTH_LINK_TARGETS,
    "finance-10k": (),
}
EXPECTED_EMITTED_NOTE_SIGNATURES = {
    "catastrophe-recap": (
        (1, "source_note", AON_NOTE, "p1-i5", "chart"),
    ),
    "clinical-study": (
        *(
            (2, "footnote", value, "p2-i2", "table")
            for value in CLINICAL_REVIEWED_NOTES[:3]
        ),
        (
            2,
            "footnote",
            CLINICAL_LINK_TARGETS[0],
            "p2-i2",
            "table",
        ),
        (
            3,
            "footnote",
            CLINICAL_LINK_TARGETS[1],
            "p3-i2",
            "diagram",
        ),
        *(
            (4, "footnote", value, "p4-i2", "table")
            for value in CLINICAL_REVIEWED_NOTES[3:]
        ),
        (
            4,
            "footnote",
            CLINICAL_LINK_TARGETS[2],
            "p4-i2",
            "table",
        ),
    ),
    "health-report": (
        (1, "footnote", HEALTH_REVIEWED_NOTE, "p1-i2", "chart"),
        (
            1,
            "footnote",
            f"StatLink 2 {HEALTH_LINK_TARGETS[0]}",
            "p1-i2",
            "chart",
        ),
        (
            1,
            "footnote",
            f"StatLink 2 {HEALTH_LINK_TARGETS[1]}",
            "p1-i5",
            "chart",
        ),
    ),
    "finance-10k": (),
}
CODE_PATHS = (
    ".env.example",
    "README.md",
    "app/config.py",
    "app/services/ir.py",
    "app/services/layout.py",
    "app/services/layout_source_notes.py",
    "app/services/ocr.py",
    "app/services/pipeline.py",
    "app/services/presentation.py",
    "app/services/serializer.py",
    "frontend/app/clearleaf-workspace.tsx",
    "frontend/app/globals.css",
    "frontend/lib/layout-relationships.ts",
    "frontend/lib/types.ts",
    "frontend/tests/p03-us03-source-notes.test.mts",
    "tests/benchmarks/layout_source_note_metrics.py",
    "tests/contract/test_p03_us03_source_note_contract.py",
    "tests/performance/test_p03_us03_source_note_performance.py",
    "tests/regression/phase_03/test_p03_us03_real_source_notes.py",
    "tests/stories/phase_03/test_p03_us03_source_note_evidence.py",
    "tests/stories/phase_03/test_p03_us03_source_notes.py",
    "tracker/phase-03-layout/decisions/"
    "P03-source-note-association-policy.md",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _artifact_semantic_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(_canonical_json(value))
    detached.pop("generated_at", None)
    detached.pop("semantic_sha256", None)
    return detached


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _dependency_custody() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for package in (
        "docling",
        "docling-core",
        "pydantic",
        "pdfplumber",
    ):
        packages[package] = importlib_metadata.version(package)
    tesseract_path_value = shutil.which(Settings().tesseract_cmd)
    if tesseract_path_value is None:
        raise RuntimeError("tesseract executable is unavailable")
    tesseract_path = Path(tesseract_path_value).resolve()
    completed = subprocess.run(
        [str(tesseract_path), "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("tesseract version query failed")
    return {
        "python_packages": packages,
        "tesseract": {
            "path": str(tesseract_path),
            "version": completed.stdout.splitlines()[0].strip(),
            "sha256": _sha256_file(tesseract_path),
            "size_bytes": tesseract_path.stat().st_size,
        },
    }


def _settings(enabled: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=enabled,
    )


def _semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(_canonical_json(payload))
    detached.get("processing", {}).pop("duration_ms", None)
    return detached


def _intersection_area(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    left = max(float(first["x"]), float(second["x"]))
    top = max(float(first["y"]), float(second["y"]))
    right = min(
        float(first["x"]) + float(first["width"]),
        float(second["x"]) + float(second["width"]),
    )
    bottom = min(
        float(first["y"]) + float(first["height"]),
        float(second["y"]) + float(second["height"]),
    )
    return max(right - left, 0.0) * max(bottom - top, 0.0)


def _horizontal_overlap(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    left = max(float(first["x"]), float(second["x"]))
    right = min(
        float(first["x"]) + float(first["width"]),
        float(second["x"]) + float(second["width"]),
    )
    denominator = min(
        float(first["width"]),
        float(second["width"]),
    )
    return (
        max(right - left, 0.0) / denominator
        if denominator > 0
        else 0.0
    )


def _positive_bbox(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    try:
        return (
            float(value["width"]) > 0
            and float(value["height"]) > 0
            and str(value["unit"]) == "pt"
        )
    except (KeyError, TypeError, ValueError):
        return False


def _note_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    canonical_pages = {
        page["page_index"]: page
        for page in (
            payload.get("canonical_presentation", {}).get("pages") or []
        )
    }
    for page in payload["pages"]:
        items = page["items"]
        by_id = {str(item.get("id")): item for item in items}
        positions = {
            str(item.get("id")): index
            for index, item in enumerate(items)
        }
        canonical_blocks = list(
            canonical_pages.get(
                page["page_index"], {}
            ).get("blocks", [])
        )
        for note in items:
            note_type = str(note.get("type") or "")
            if note_type not in {"source_note", "footnote"}:
                continue
            owner_field = (
                "source_note_of"
                if note_type == "source_note"
                else "footnote_of"
            )
            backlink_field = (
                "source_note_ids"
                if note_type == "source_note"
                else "footnote_ids"
            )
            expected_relationship_type = (
                "source_note_of"
                if note_type == "source_note"
                else "footnote_of"
            )
            owner_id = str(note.get(owner_field) or "")
            owner = by_id.get(owner_id)
            owner_backlinks = (
                owner.get(backlink_field) or []
                if owner is not None
                else []
            )
            descriptor_matches = (
                [
                    relationship
                    for relationship in owner.get("relationships") or []
                    if isinstance(relationship, Mapping)
                    and relationship.get("id")
                    == note.get("relationship_id")
                    and relationship.get("type")
                    == note.get("relationship_type")
                    and relationship.get("source_id") == note.get("id")
                    and relationship.get("target_id") == owner_id
                ]
                if owner is not None
                else []
            )
            links = [
                {
                    "kind": str(link.get("kind") or ""),
                    "target": str(link.get("target") or ""),
                }
                for link in note.get("links") or []
                if isinstance(link, Mapping)
            ]
            note_id = str(note.get("id") or "")
            relationship_id = str(note.get("relationship_id") or "")
            canonical_note_blocks = [
                block
                for block in canonical_blocks
                if block.get("omission_reason") is None
                and block.get("primary_element_type") == note_type
                and block.get("text") == note.get("value")
                and relationship_id
                in (block.get("relationship_ids") or [])
            ]
            canonical_owner_blocks = [
                block
                for block in canonical_blocks
                if owner is not None
                and block.get("omission_reason") is None
                and block.get("primary_element_type")
                == owner.get("type")
                and relationship_id
                in (block.get("relationship_ids") or [])
            ]
            output.append(
                {
                    "page_index": page["page_index"],
                    "id": note_id,
                    "type": note_type,
                    "value": note.get("value"),
                    "bbox": note.get("bbox"),
                    "source": note.get("source"),
                    "confidence": note.get("confidence"),
                    "owner_id": owner_id,
                    "owner_type": (
                        owner.get("type") if owner is not None else None
                    ),
                    "owner_bbox": (
                        owner.get("bbox") if owner is not None else None
                    ),
                    "relationship_id": relationship_id,
                    "relationship_type": note.get("relationship_type"),
                    "relationship_basis": note.get(
                        "relationship_basis"
                    ),
                    "links": links,
                    "owner_resolved": owner is not None,
                    "owner_linked_back": bool(
                        owner is not None
                        and owner_backlinks.count(note_id) == 1
                    ),
                    "descriptor_exact": len(descriptor_matches) == 1,
                    "relationship_type_exact": bool(
                        note.get("relationship_type")
                        == expected_relationship_type
                        and note.get(owner_field) == owner_id
                    ),
                    "order_after_owner": bool(
                        owner is not None
                        and positions.get(owner_id, sys.maxsize)
                        < positions.get(note_id, -1)
                    ),
                    "bbox_external": bool(
                        owner is not None
                        and isinstance(note.get("bbox"), Mapping)
                        and isinstance(owner.get("bbox"), Mapping)
                        and note["bbox"].get("unit")
                        == owner["bbox"].get("unit")
                        and _intersection_area(
                            note["bbox"], owner["bbox"]
                        )
                        == 0
                    ),
                    "bbox_positive": bool(
                        _positive_bbox(note.get("bbox"))
                        and (
                            owner is not None
                            and _positive_bbox(owner.get("bbox"))
                        )
                    ),
                    "bbox_below_aligned_within_gap": bool(
                        owner is not None
                        and isinstance(note.get("bbox"), Mapping)
                        and isinstance(owner.get("bbox"), Mapping)
                        and float(note["bbox"]["y"])
                        >= (
                            float(owner["bbox"]["y"])
                            + float(owner["bbox"]["height"])
                        )
                        and (
                            float(note["bbox"]["y"])
                            - (
                                float(owner["bbox"]["y"])
                                + float(owner["bbox"]["height"])
                            )
                        )
                        <= 72.0
                        and _horizontal_overlap(
                            note["bbox"],
                            owner["bbox"],
                        )
                        >= 0.20
                    ),
                    "links_grounded": all(
                        link["target"]
                        and link["target"].startswith(("http://", "https://"))
                        and link["target"] in str(note.get("value") or "")
                        for link in links
                    ),
                    "canonical_block_present": bool(
                        len(canonical_note_blocks) == 1
                    ),
                    "canonical_owner_block_present": bool(
                        len(canonical_owner_blocks) == 1
                    ),
                    "canonical_relationship_block_count": (
                        len(
                            [
                                block
                                for block in canonical_blocks
                                if block.get("omission_reason") is None
                                and relationship_id
                                in (block.get("relationship_ids") or [])
                            ]
                        )
                    ),
                }
            )
    return output


def _note_signature(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(record["page_index"]),
        str(record["type"]),
        str(record["value"]),
        str(record["owner_id"]),
        str(record["owner_type"]),
    )


def _public_note_graph_valid(
    payload: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> bool:
    items = [
        item
        for page in payload["pages"]
        for item in page["items"]
    ]
    item_ids = [str(item.get("id") or "") for item in items]
    relationship_ids = [
        str(record.get("relationship_id") or "") for record in records
    ]
    if (
        not all(item_ids)
        or len(item_ids) != len(set(item_ids))
        or not all(relationship_ids)
        or len(relationship_ids) != len(set(relationship_ids))
    ):
        return False

    notes_by_id = {
        str(item["id"]): item
        for item in items
        if item.get("type") in {"source_note", "footnote"}
    }
    if len(notes_by_id) != len(records):
        return False
    expected_descriptors = {
        str(record["relationship_id"]): (
            str(record["relationship_type"]),
            str(record["id"]),
            str(record["owner_id"]),
        )
        for record in records
    }
    observed_descriptors: dict[str, tuple[str, str, str]] = {}
    for owner in items:
        owner_id = str(owner["id"])
        for field_name, note_type, owner_field in (
            ("source_note_ids", "source_note", "source_note_of"),
            ("footnote_ids", "footnote", "footnote_of"),
        ):
            backlinks = owner.get(field_name) or []
            if len(backlinks) != len(set(backlinks)):
                return False
            for note_id in backlinks:
                note = notes_by_id.get(str(note_id))
                if (
                    note is None
                    or note.get("type") != note_type
                    or note.get(owner_field) != owner_id
                ):
                    return False
        for descriptor in owner.get("relationships") or []:
            if (
                not isinstance(descriptor, Mapping)
                or descriptor.get("type")
                not in {"source_note_of", "footnote_of"}
            ):
                continue
            relationship_id = str(descriptor.get("id") or "")
            if relationship_id in observed_descriptors:
                return False
            observed_descriptors[relationship_id] = (
                str(descriptor.get("type") or ""),
                str(descriptor.get("source_id") or ""),
                str(descriptor.get("target_id") or ""),
            )
    return observed_descriptors == expected_descriptors


def _snapshot(case: str, enabled: bool, workspace: Path) -> dict[str, Any]:
    source_path = workspace / "benchmark-expertmodeldata" / f"{case}.pdf"
    source_bytes = source_path.read_bytes()
    expected_input = EXPECTED_INPUTS[case]
    observed_input_sha256 = _sha256_bytes(source_bytes)
    if (
        len(source_bytes) != expected_input["size_bytes"]
        or observed_input_sha256 != expected_input["sha256"]
    ):
        raise ValueError(f"immutable benchmark input mismatch: {case}")
    started = time.perf_counter()
    result = parse_document(
        source_bytes,
        source_path.name,
        _settings(enabled),
    )
    wall_seconds = time.perf_counter() - started
    payload = result.model_dump(mode="json", exclude_none=False)
    serialized_json = _canonical_json(payload).encode("utf-8")
    semantic_json = _canonical_json(
        _semantic_payload(payload)
    ).encode("utf-8")
    markdown = to_markdown(payload)
    markdown_bytes = markdown.encode("utf-8")
    records = _note_records(payload)
    canonical_text = str(
        payload.get("canonical_presentation", {})
        .get("full", {})
        .get("text")
        or ""
    )
    observed_links = sorted(
        link["target"]
        for record in records
        for link in record["links"]
    )
    expected_values = EXPECTED_REVIEWED_NOTES[case]
    expected_emitted_signatures = Counter(
        EXPECTED_EMITTED_NOTE_SIGNATURES[case]
    )
    observed_emitted_signatures = Counter(
        _note_signature(record) for record in records
    )
    missing_emitted_signatures = (
        expected_emitted_signatures - observed_emitted_signatures
    )
    unexpected_emitted_signatures = (
        observed_emitted_signatures - expected_emitted_signatures
    )
    expected_link_counts = Counter(EXPECTED_LINK_TARGETS[case])
    observed_link_counts = Counter(observed_links)
    missing_link_counts = expected_link_counts - observed_link_counts
    unexpected_link_counts = observed_link_counts - expected_link_counts
    expected_emitted_values = tuple(
        signature[2]
        for signature in EXPECTED_EMITTED_NOTE_SIGNATURES[case]
    )
    all_items = [
        item
        for page in payload["pages"]
        for item in page["items"]
    ]
    layout_note_projection_absent = bool(
        not records
        and all(
            not item.get("source_note_ids")
            and not item.get("footnote_ids")
            and not item.get("source_note_of")
            and not item.get("footnote_of")
            and not [
                relationship
                for relationship in item.get("relationships") or []
                if isinstance(relationship, Mapping)
                and relationship.get("type")
                in {"source_note_of", "footnote_of"}
            ]
            for item in all_items
        )
    )
    return {
        "enabled": enabled,
        "wall_seconds": round(wall_seconds, 6),
        "processing_duration_ms": payload["processing"]["duration_ms"],
        "peak_rss_bytes": _rss_bytes(),
        "json_size_bytes": len(serialized_json),
        "json_sha256": _sha256_bytes(serialized_json),
        "semantic_json_size_bytes": len(semantic_json),
        "semantic_json_sha256": _sha256_bytes(semantic_json),
        "markdown_size_bytes": len(markdown_bytes),
        "markdown_sha256": _sha256_bytes(markdown_bytes),
        "json_round_trip_equal": (
            json.loads(serialized_json) == payload
        ),
        "markdown_serialized": isinstance(markdown, str),
        "note_records": records,
        "layout_note_projection_absent": (
            layout_note_projection_absent
        ),
        "reviewed_note_occurrences": {
            value: sum(record["value"] == value for record in records)
            for value in expected_values
        },
        "markdown_reviewed_occurrences": {
            value: markdown.count(value) for value in expected_values
        },
        "canonical_reviewed_occurrences": {
            value: canonical_text.count(value) for value in expected_values
        },
        "markdown_expected_emitted_occurrences": {
            value: markdown.count(value)
            for value in expected_emitted_values
        },
        "canonical_expected_emitted_occurrences": {
            value: canonical_text.count(value)
            for value in expected_emitted_values
        },
        "markdown_link_target_occurrences": {
            target: markdown.count(target)
            for target in EXPECTED_LINK_TARGETS[case]
        },
        "canonical_link_target_occurrences": {
            target: canonical_text.count(target)
            for target in EXPECTED_LINK_TARGETS[case]
        },
        "expected_emitted_note_count": sum(
            expected_emitted_signatures.values()
        ),
        "classified_emitted_note_count": (
            len(records) - sum(unexpected_emitted_signatures.values())
        ),
        "missing_expected_note_count": sum(
            missing_emitted_signatures.values()
        ),
        "unexpected_note_count": sum(
            unexpected_emitted_signatures.values()
        ),
        "all_emitted_notes_exactly_classified": not (
            missing_emitted_signatures
            or unexpected_emitted_signatures
        ),
        "observed_link_targets": observed_links,
        "missing_expected_link_count": sum(
            missing_link_counts.values()
        ),
        "unexpected_link_count": sum(
            unexpected_link_counts.values()
        ),
        "expected_link_targets_present": not missing_link_counts,
        "all_emitted_links_exactly_classified": not (
            missing_link_counts or unexpected_link_counts
        ),
        "all_relationships_valid": all(
            record["owner_resolved"]
            and record["owner_linked_back"]
            and record["descriptor_exact"]
            and record["relationship_type_exact"]
            and record["order_after_owner"]
            and record["bbox_external"]
            and record["bbox_positive"]
            and record["bbox_below_aligned_within_gap"]
            and record["links_grounded"]
            and record["canonical_block_present"]
            and record["canonical_owner_block_present"]
            and record["canonical_relationship_block_count"] == 2
            for record in records
        )
        and _public_note_graph_valid(payload, records),
    }


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _fresh_snapshot(
    workspace: Path,
    case: str,
    enabled: bool,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix=f"p03-us03-{case}-",
    ) as temporary_directory:
        output = Path(temporary_directory) / "snapshot.json"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.benchmarks.layout_source_note_metrics",
                "--worker-case",
                case,
                "--worker-enabled",
                "true" if enabled else "false",
                "--workspace",
                str(workspace),
                "--output",
                str(output),
            ],
            cwd=workspace,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=330,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "fresh US03 metrics worker failed for "
                f"{case}/{enabled}: {completed.stderr[-4000:]}"
            )
        return json.loads(output.read_text(encoding="utf-8"))


def _percentile95(samples: Sequence[float]) -> float:
    if len(samples) < 2:
        return float(samples[0])
    return statistics.quantiles(
        samples,
        n=100,
        method="inclusive",
    )[94]


def _paired_performance_summary(
    off_samples: Sequence[Mapping[str, Any]],
    on_samples: Sequence[Mapping[str, Any]],
    *,
    baseline_seconds: float,
) -> dict[str, Any]:
    signed_deltas = [
        float(on_sample["wall_seconds"])
        - float(off_sample["wall_seconds"])
        for off_sample, on_sample in zip(
            off_samples,
            on_samples,
            strict=True,
        )
    ]
    if len(signed_deltas) < 5:
        raise ValueError("paired performance requires at least 5 samples")
    nonnegative_overheads = [
        max(delta, 0.0) for delta in signed_deltas
    ]
    ceiling = baseline_seconds * 0.05
    p95_signed_delta = _percentile95(signed_deltas)
    p95_nonnegative_overhead = _percentile95(
        nonnegative_overheads
    )
    return {
        "pair_count": len(signed_deltas),
        "execution_order_alternated": True,
        "process_model": "fresh_process_per_flag_state",
        "cache_state": (
            "operating-system caches were not explicitly flushed"
        ),
        "quantile_method": "empirical_p95_inclusive",
        "flag_off_wall_seconds": [
            float(sample["wall_seconds"]) for sample in off_samples
        ],
        "flag_on_wall_seconds": [
            float(sample["wall_seconds"]) for sample in on_samples
        ],
        "paired_signed_wall_seconds_deltas": [
            round(delta, 6) for delta in signed_deltas
        ],
        "paired_nonnegative_overhead_seconds": [
            round(overhead, 6) for overhead in nonnegative_overheads
        ],
        "p50_signed_delta_seconds": round(
            statistics.median(signed_deltas),
            6,
        ),
        "p95_signed_delta_seconds": round(
            p95_signed_delta,
            6,
        ),
        "max_signed_delta_seconds": round(
            max(signed_deltas),
            6,
        ),
        "p50_nonnegative_overhead_seconds": round(
            statistics.median(nonnegative_overheads),
            6,
        ),
        "p95_nonnegative_overhead_seconds": round(
            p95_nonnegative_overhead,
            6,
        ),
        "max_nonnegative_overhead_seconds": round(
            max(nonnegative_overheads),
            6,
        ),
        "five_percent_ceiling_seconds": ceiling,
        "p95_overhead_percent_of_baseline": round(
            p95_nonnegative_overhead
            / baseline_seconds
            * 100,
            4,
        ),
        "within_five_percent_ceiling": (
            p95_nonnegative_overhead <= ceiling
        ),
    }


def generate_stage_metrics() -> dict[str, Any]:
    table = _item(
        "p1-table",
        "table",
        y=10.0,
        height=20.0,
        value=[["A"]],
    )
    notes = [
        _text(
            f"#/texts/{index}",
            f"{index + 1} Reviewed note.",
            _box(10, 32 + index * 6, 70, 36 + index * 6),
        )
        for index in range(8)
    ]
    graph = _graph(
        texts=notes,
        tables=[
            _table(
                "#/tables/0",
                _box(10, 10, 80, 30),
                footnotes=tuple(note["self_ref"] for note in notes),
            )
        ],
    )
    _public, ir = round_trip_document(
        _document(table),
        raw_graph=graph,
        native_texts=(" ".join(note["text"] for note in notes),),
    )
    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        layout_source_notes_enabled=True,
    )
    projected = apply_layout_projection(ir, settings)
    projected_elements = {
        element.id: element for element in projected.elements
    }
    note_count = sum(
        str(
            projected_elements[element_id]
            .properties.get("legacy_item", {})
            .get("type")
            or ""
        )
        in {"source_note", "footnote"}
        for page in projected.pages
        for element_id in page.presentation_element_ids
    )
    projected_size_bytes = len(
        projected.model_dump_json().encode("utf-8")
    )
    for _ in range(5):
        apply_layout_projection(ir, settings)
    samples: list[float] = []
    tracemalloc.start()
    for _ in range(100):
        started = time.perf_counter()
        apply_layout_projection(ir, settings)
        samples.append(time.perf_counter() - started)
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    p95_seconds = _percentile95(samples)
    ceiling = min(
        baseline["wall_seconds"] * 0.05
        for baseline in PHASE_02_PERFORMANCE_BASELINES.values()
    )
    return {
        "warmup_count": 5,
        "sample_count": 100,
        "note_count": note_count,
        "p50_seconds": round(statistics.median(samples), 9),
        "p95_seconds": round(p95_seconds, 9),
        "max_seconds": round(max(samples), 9),
        "min_seconds": round(min(samples), 9),
        "peak_allocated_bytes": peak_bytes,
        "projected_ir_size_bytes": projected_size_bytes,
        "five_percent_ceiling_seconds": ceiling,
        "within_five_percent_ceiling": p95_seconds <= ceiling,
    }


def generate_artifact(
    workspace: Path,
    *,
    repeats: int,
) -> dict[str, Any]:
    if repeats < 5:
        raise ValueError("paired real performance requires at least 5 repeats")
    cases: dict[str, Any] = {}
    for case in CASES:
        pair_count = repeats if case in PERFORMANCE_CASES else 1
        off_samples: list[dict[str, Any]] = []
        on_samples: list[dict[str, Any]] = []
        for pair_index in range(pair_count):
            states = (
                (False, True)
                if pair_index % 2 == 0
                else (True, False)
            )
            results: dict[bool, dict[str, Any]] = {}
            for state in states:
                results[state] = _fresh_snapshot(
                    workspace,
                    case,
                    state,
                )
            off_samples.append(results[False])
            on_samples.append(results[True])

        off = off_samples[0]
        on = on_samples[0]
        reviewed_expected = EXPECTED_REVIEWED_NOTES[case]
        reviewed_matched = sum(
            on["reviewed_note_occurrences"].get(value) == 1
            for value in reviewed_expected
        )
        case_record: dict[str, Any] = {
            "input_path": f"benchmark-expertmodeldata/{case}.pdf",
            "input_size_bytes": (
                workspace
                / "benchmark-expertmodeldata"
                / f"{case}.pdf"
            ).stat().st_size,
            "input_sha256": _sha256_file(
                workspace
                / "benchmark-expertmodeldata"
                / f"{case}.pdf"
            ),
            "reviewed_note_expected": len(reviewed_expected),
            "reviewed_note_matched": reviewed_matched,
            "reviewed_note_recall": (
                reviewed_matched / len(reviewed_expected)
                if reviewed_expected
                else 1.0
            ),
            "expected_link_targets": list(
                EXPECTED_LINK_TARGETS[case]
            ),
            "expected_emitted_note_count": len(
                EXPECTED_EMITTED_NOTE_SIGNATURES[case]
            ),
            "flag_off": off,
            "flag_on": on,
            "flag_off_note_count": len(off["note_records"]),
            "flag_on_note_count": len(on["note_records"]),
            "semantic_flag_on_off_equal": (
                on["semantic_json_sha256"]
                == off["semantic_json_sha256"]
            ),
            "markdown_flag_on_off_equal": (
                on["markdown_sha256"] == off["markdown_sha256"]
            ),
            "json_size_bytes_delta": (
                on["json_size_bytes"] - off["json_size_bytes"]
            ),
            "peak_rss_bytes_delta": (
                on["peak_rss_bytes"] - off["peak_rss_bytes"]
            ),
            "all_flag_on_samples_quality_consistent": all(
                sample["all_emitted_notes_exactly_classified"]
                and sample["all_emitted_links_exactly_classified"]
                and sample["all_relationships_valid"]
                and sample["json_round_trip_equal"]
                and sample["markdown_serialized"]
                for sample in on_samples
            ),
            "all_flag_off_samples_projection_absent": all(
                sample["layout_note_projection_absent"]
                and sample["json_round_trip_equal"]
                and sample["markdown_serialized"]
                for sample in off_samples
            ),
            "resource_samples": {
                "flag_off_peak_rss_bytes": [
                    sample["peak_rss_bytes"] for sample in off_samples
                ],
                "flag_on_peak_rss_bytes": [
                    sample["peak_rss_bytes"] for sample in on_samples
                ],
                "paired_peak_rss_bytes_deltas": [
                    on_sample["peak_rss_bytes"]
                    - off_sample["peak_rss_bytes"]
                    for off_sample, on_sample in zip(
                        off_samples,
                        on_samples,
                        strict=True,
                    )
                ],
                "max_flag_on_peak_rss_bytes": max(
                    sample["peak_rss_bytes"] for sample in on_samples
                ),
                "max_flag_on_peak_rss_percent_of_phase_02_baseline": round(
                    max(
                        sample["peak_rss_bytes"]
                        for sample in on_samples
                    )
                    / (
                        PHASE_02_PERFORMANCE_BASELINES.get(
                            case,
                            {"peak_rss_mib": 1.0},
                        )["peak_rss_mib"]
                        * 1024
                        * 1024
                    )
                    * 100,
                    4,
                )
                if case in PHASE_02_PERFORMANCE_BASELINES
                else None,
                "flag_off_semantic_json_size_bytes": [
                    sample["semantic_json_size_bytes"]
                    for sample in off_samples
                ],
                "flag_on_semantic_json_size_bytes": [
                    sample["semantic_json_size_bytes"]
                    for sample in on_samples
                ],
                "flag_off_markdown_size_bytes": [
                    sample["markdown_size_bytes"]
                    for sample in off_samples
                ],
                "flag_on_markdown_size_bytes": [
                    sample["markdown_size_bytes"]
                    for sample in on_samples
                ],
            },
        }
        if case in PERFORMANCE_CASES:
            case_record["paired_performance"] = (
                _paired_performance_summary(
                    off_samples,
                    on_samples,
                    baseline_seconds=(
                        PHASE_02_PERFORMANCE_BASELINES[case][
                            "wall_seconds"
                        ]
                    ),
                )
            )
        cases[case] = case_record

    code_sha256 = {
        relative: {
            "path": relative,
            "sha256": _sha256_file(workspace / relative),
            "size_bytes": (workspace / relative).stat().st_size,
        }
        for relative in CODE_PATHS
    }
    expected_count = sum(
        len(values) for values in EXPECTED_REVIEWED_NOTES.values()
    )
    matched_count = sum(
        case["reviewed_note_matched"] for case in cases.values()
    )
    artifact: dict[str, Any] = {
        "schema_version": "1.0",
        "story": "P03-US03",
        "generated_at": datetime.now(UTC).isoformat(),
        "measurement": {
            "full_parser_process_model": (
                "one fresh subprocess per case and flag state"
            ),
            "performance_case_pair_count": repeats,
            "performance_cases": list(PERFORMANCE_CASES),
            "quality_only_case_snapshot_count_per_flag": 1,
            "performance_execution_order": (
                "alternating off/on then on/off within paired indexes"
            ),
            "performance_quantile": (
                "empirical p95, statistics.quantiles inclusive method"
            ),
            "performance_gate_value": (
                "p95 of max(flag_on - flag_off, 0) paired overhead"
            ),
            "cache_disclaimer": (
                "operating-system caches were not explicitly flushed; "
                "no cold-cache claim is made"
            ),
            "peak_rss_semantics": (
                "per-worker parse-and-snapshot high-water mark"
            ),
            "layout_stage_isolated_from_full_parser": True,
            "hosted_requests": 0,
        },
        "policy": {
            "feature_flag": "PARSER_LAYOUT_SOURCE_NOTES_ENABLED",
            "default_enabled": False,
            "eligible_owner_types": [
                "table",
                "image",
                "chart",
                "diagram",
            ],
            "relationship_types": [
                "source_note_of",
                "footnote_of",
            ],
            "maximum_gap_points": 72.0,
            "maximum_references_per_owner": 64,
            "maximum_owners_per_page": 256,
            "maximum_candidates_per_page": 512,
            "maximum_same_text_candidates_per_page": 128,
            "maximum_note_bytes": 16 * 1024,
            "maximum_uri_bytes": 2 * 1024,
            "maximum_annotations_per_page": 256,
            "maximum_annotations_per_document": 1024,
            "maximum_render_bands_per_page": 16,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "dependency_custody": _dependency_custody(),
        "phase_02_performance_baselines": (
            PHASE_02_PERFORMANCE_BASELINES
        ),
        "code_sha256": code_sha256,
        "cases": cases,
        "layout_stage": generate_stage_metrics(),
        "aggregate": {
            "reviewed_note_expected": expected_count,
            "reviewed_note_matched": matched_count,
            "reviewed_note_recall": (
                matched_count / expected_count
                if expected_count
                else 1.0
            ),
            "false_association_count": sum(
                case["flag_on"]["unexpected_note_count"]
                + case["flag_on"]["unexpected_link_count"]
                for case in cases.values()
            ),
            "missing_expected_control_count": sum(
                case["flag_on"]["missing_expected_note_count"]
                + case["flag_on"]["missing_expected_link_count"]
                for case in cases.values()
            ),
            "all_emitted_notes_exactly_classified": all(
                case["flag_on"][
                    "all_emitted_notes_exactly_classified"
                ]
                for case in cases.values()
            ),
            "all_emitted_links_exactly_classified": all(
                case["flag_on"][
                    "all_emitted_links_exactly_classified"
                ]
                for case in cases.values()
            ),
            "all_relationships_valid": all(
                case["flag_on"]["all_relationships_valid"]
                for case in cases.values()
            ),
            "all_performance_sample_quality_consistent": all(
                case["all_flag_on_samples_quality_consistent"]
                for case in cases.values()
            ),
            "all_flag_off_samples_projection_absent": all(
                case["all_flag_off_samples_projection_absent"]
                for case in cases.values()
            ),
            "all_reviewed_markdown_once": all(
                all(count == 1 for count in case["flag_on"][
                    "markdown_reviewed_occurrences"
                ].values())
                for case in cases.values()
            ),
            "all_reviewed_canonical_once": all(
                all(count == 1 for count in case["flag_on"][
                    "canonical_reviewed_occurrences"
                ].values())
                for case in cases.values()
            ),
            "health_link_targets_once_in_output": all(
                cases["health-report"]["flag_on"][
                    occurrence_field
                ][target]
                == 1
                for occurrence_field in (
                    "markdown_link_target_occurrences",
                    "canonical_link_target_occurrences",
                )
                for target in HEALTH_LINK_TARGETS
            ),
            "performance_p95_within_five_percent": all(
                cases[case]["paired_performance"][
                    "within_five_percent_ceiling"
                ]
                for case in PERFORMANCE_CASES
            ),
            "finance_semantic_flag_parity": cases["finance-10k"][
                "semantic_flag_on_off_equal"
            ],
            "finance_markdown_flag_parity": cases["finance-10k"][
                "markdown_flag_on_off_equal"
            ],
        },
    }
    artifact["semantic_sha256"] = _sha256_bytes(
        _canonical_json(
            _artifact_semantic_payload(artifact)
        ).encode("utf-8")
    )
    return artifact


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--worker-case", choices=CASES)
    parser.add_argument(
        "--worker-enabled",
        choices=("true", "false"),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    workspace = args.workspace.resolve()
    if args.worker_case is not None:
        if args.worker_enabled is None:
            raise SystemExit("--worker-enabled is required for workers")
        output = _snapshot(
            args.worker_case,
            args.worker_enabled == "true",
            workspace,
        )
    else:
        output = generate_artifact(
            workspace,
            repeats=args.repeats,
        )
    _write_json_atomic(args.output, output)


if __name__ == "__main__":
    main()
