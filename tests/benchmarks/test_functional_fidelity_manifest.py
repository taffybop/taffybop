from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


WORKSPACE = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    WORKSPACE
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "tools"
    / "build_functional_fidelity_manifest.py"
)
SPEC = importlib.util.spec_from_file_location("functional_fidelity_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
manifest_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = manifest_tool
SPEC.loader.exec_module(manifest_tool)


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path, *, status: str = "COMPLETED") -> tuple[Path, Path, Path]:
    run = tmp_path / "run"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    cases = []
    service_cases = []
    for index in range(15):
        case_id = f"case-{index:02d}"
        (corpus / f"{case_id}.pdf").write_bytes(b"%PDF-1.7 fixture")
        cases.append({"case_id": case_id, "source": {"page_count": 1}})
        reference = run / "llamaparse" / case_id
        candidate = run / "service" / case_id
        reference.mkdir(parents=True)
        candidate.mkdir(parents=True)
        _json(
            reference / "job.json",
            {
                "job": {
                    "id": f"job-{index}",
                    "project_id": manifest_tool.EXPECTED_PROJECT_ID,
                    "status": status,
                    "tier": "agentic",
                },
                "page_count": 1,
            },
        )
        (reference / "reference.md").write_text("Body", encoding="utf-8")
        _json(reference / "reference.json", {"markdown": {"pages": []}})
        _json(reference / "pages/page-1/rendered-dom.json", {"page_number": 1})
        (reference / "pages/page-1/rendered.png").write_bytes(b"png")
        response = {
            "document": {"page_count": 1},
            "pages": [{}],
            "canonical_presentation": {"full": {"markdown": "Body"}},
        }
        _json(candidate / "response.json", response)
        (candidate / "response.md").write_text("Body", encoding="utf-8")
        _json(candidate / "pages/page-1/rendered-dom.json", {"page_number": 1})
        _json(
            candidate / "rendered-capture.json",
            {
                "page_count": 1,
                "source_response_sha256": manifest_tool._sha256(
                    candidate / "response.json"
                ),
            },
        )
        service_cases.append(
            {
                "case_id": case_id,
                "outputs": {
                    "json": {
                        "status_code": 200,
                        "sha256": manifest_tool._sha256(candidate / "response.json"),
                    },
                    "markdown": {
                        "status_code": 200,
                        "sha256": manifest_tool._sha256(candidate / "response.md"),
                    },
                },
            }
        )
    corpus_manifest = tmp_path / "manifest.json"
    _json(corpus_manifest, {"cases": cases})
    _json(run / "service/run.json", {"cases": service_cases})
    _json(run / "service-profile.json", {"profile_id": "fixture"})
    return run, corpus, corpus_manifest


def test_manifest_binds_all_required_surfaces(tmp_path: Path) -> None:
    run, corpus, corpus_manifest = _fixture(tmp_path)

    result = manifest_tool.build_manifest(
        run,
        corpus_dir=corpus,
        corpus_manifest=corpus_manifest,
        service_dir=run / "service",
    )

    assert result["case_count"] == 15
    assert result["source_page_count"] == 15
    assert result["reference_rendered_dom_count"] == 15
    assert result["reference_rendered_png_count"] == 15
    assert result["service_rendered_dom_count"] == 15
    assert result["service_http_200_output_count"] == 30
    assert result["upload_limit_bytes"] == 20 * 1024 * 1024
    assert result["all_sources_within_upload_limit"] is True
    assert all(
        row["service"]["markdown_matches_canonical_json_exactly"]
        for row in result["cases"]
    )


def test_manifest_fails_closed_on_incomplete_reference_job(tmp_path: Path) -> None:
    run, corpus, corpus_manifest = _fixture(tmp_path, status="FAILED")

    with pytest.raises(ValueError, match="not COMPLETED"):
        manifest_tool.build_manifest(
            run,
            corpus_dir=corpus,
            corpus_manifest=corpus_manifest,
            service_dir=run / "service",
        )


def test_manifest_selects_hash_bound_reference_override(tmp_path: Path) -> None:
    run, corpus, corpus_manifest = _fixture(tmp_path)
    case_id = "case-00"
    original = run / "llamaparse" / case_id
    override = run / "llamaparse-rerun" / case_id
    override.parent.mkdir(parents=True)
    original.rename(override)

    result = manifest_tool.build_manifest(
        run,
        corpus_dir=corpus,
        corpus_manifest=corpus_manifest,
        service_dir=run / "service",
        reference_roots={case_id: "llamaparse-rerun"},
    )

    selected = next(row for row in result["cases"] if row["case_id"] == case_id)
    assert selected["llamaparse"]["artifact_root"] == "llamaparse-rerun"


def test_reference_selection_rejects_escape(tmp_path: Path) -> None:
    path = tmp_path / "selection.json"
    _json(path, {"cases": {"case-00": "../outside"}})

    with pytest.raises(ValueError, match="stay within the run"):
        manifest_tool._load_reference_roots(path)


def test_snapshot_payload_type_is_detected_independently_of_extension(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "rendered.png"
    snapshot.write_bytes(b"\xff\xd8\xff\xe0JFIF\x00fixture")

    assert manifest_tool._detected_image_media_type(snapshot) == "image/jpeg"
