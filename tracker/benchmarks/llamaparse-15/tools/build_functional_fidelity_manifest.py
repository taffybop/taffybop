#!/usr/bin/env python3
"""Build and verify the retained functional-fidelity artifact manifest.

This tool is deliberately read-only apart from its explicit output file.  It
binds the source PDFs, fresh LlamaParse jobs/raw outputs/UI captures, public
service HTTP outputs, and Clearleaf rendered-DOM captures by SHA-256.  A
manifest is emitted only when all required artifacts validate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "functional-fidelity-artifact-manifest-v1"
EXPECTED_PROJECT_ID = "ec7edb70-8bec-4b1b-9a17-451533884780"
DEFAULT_UPLOAD_LIMIT_BYTES = 20 * 1024 * 1024
DEFAULT_REFERENCE_ROOT = "llamaparse"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required artifact is missing: {path}")
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _detected_image_media_type(path: Path) -> str | None:
    header = path.read_bytes()[:12]
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"RIFF",)) and header[8:12] == b"WEBP":
        return "image/webp"
    return None


def _load_reference_roots(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    payload = _read_json(path)
    cases = payload.get("cases") if isinstance(payload, Mapping) else None
    if not isinstance(cases, Mapping):
        raise ValueError("reference selection must contain a cases object")
    roots: dict[str, str] = {}
    for case_id, value in cases.items():
        root = value.get("root") if isinstance(value, Mapping) else value
        if not isinstance(root, str) or not root.strip():
            raise ValueError(f"{case_id}: invalid reference root")
        relative = Path(root)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"{case_id}: reference root must stay within the run")
        roots[str(case_id)] = relative.as_posix()
    return roots


def _reference_dir(
    run_dir: Path,
    case_id: str,
    reference_roots: Mapping[str, str],
) -> Path:
    root = Path(reference_roots.get(case_id, DEFAULT_REFERENCE_ROOT))
    selected = (run_dir / root / case_id).resolve()
    if not selected.is_relative_to(run_dir):
        raise ValueError(f"{case_id}: selected reference escapes the run")
    return selected


def _page_artifacts(
    case_dir: Path,
    root: Path,
    *,
    filename: str,
    page_count: int,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for page_number in range(1, page_count + 1):
        path = case_dir / "pages" / f"page-{page_number}" / filename
        record = {"page_number": page_number, **_artifact(path, root)}
        if filename == "rendered.png":
            media_type = _detected_image_media_type(path)
            record.update(
                {
                    "detected_media_type": media_type,
                    "extension_matches_payload": media_type == "image/png",
                }
            )
        artifacts.append(record)
    return artifacts


def _canonical_markdown(payload: Mapping[str, Any]) -> str | None:
    canonical = payload.get("canonical_presentation")
    if not isinstance(canonical, Mapping):
        return None
    full = canonical.get("full")
    if not isinstance(full, Mapping):
        return None
    value = full.get("markdown")
    return value if isinstance(value, str) else None


def _case_record(
    *,
    run_dir: Path,
    corpus_dir: Path,
    service_dir: Path,
    case_id: str,
    source_page_count: int,
    service_http: Mapping[str, Any],
    expected_project_id: str,
    reference_roots: Mapping[str, str],
) -> dict[str, Any]:
    source_path = corpus_dir / f"{case_id}.pdf"
    reference_dir = _reference_dir(run_dir, case_id, reference_roots)
    candidate_dir = service_dir / case_id

    job_payload = _read_json(reference_dir / "job.json")
    job = job_payload.get("job") if isinstance(job_payload, Mapping) else None
    if not isinstance(job, Mapping):
        raise ValueError(f"{case_id}: job.json has no job object")
    if job.get("project_id") != expected_project_id:
        raise ValueError(f"{case_id}: unexpected LlamaParse project")
    if job.get("status") != "COMPLETED":
        raise ValueError(f"{case_id}: LlamaParse job is not COMPLETED")
    if str(job.get("tier", "")).casefold() != "agentic":
        raise ValueError(f"{case_id}: LlamaParse tier is not Agentic")
    if int(job_payload.get("page_count") or 0) != source_page_count:
        raise ValueError(f"{case_id}: LlamaParse page count mismatch")

    reference_dom = _page_artifacts(
        reference_dir,
        run_dir,
        filename="rendered-dom.json",
        page_count=source_page_count,
    )
    reference_png = _page_artifacts(
        reference_dir,
        run_dir,
        filename="rendered.png",
        page_count=source_page_count,
    )
    candidate_dom = _page_artifacts(
        candidate_dir,
        run_dir,
        filename="rendered-dom.json",
        page_count=source_page_count,
    )

    response_json_path = candidate_dir / "response.json"
    response_md_path = candidate_dir / "response.md"
    response_payload = _read_json(response_json_path)
    pages = response_payload.get("pages") if isinstance(response_payload, Mapping) else None
    if not isinstance(pages, list) or len(pages) != source_page_count:
        raise ValueError(f"{case_id}: service response page count mismatch")
    canonical_markdown = _canonical_markdown(response_payload)
    response_markdown = response_md_path.read_text(encoding="utf-8")
    if canonical_markdown is None or response_markdown != canonical_markdown:
        raise ValueError(f"{case_id}: service Markdown/canonical JSON parity failed")

    outputs = service_http.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError(f"{case_id}: no service HTTP output record")
    for output_name, response_path in (
        ("json", response_json_path),
        ("markdown", response_md_path),
    ):
        output = outputs.get(output_name)
        if not isinstance(output, Mapping) or output.get("status_code") != 200:
            raise ValueError(f"{case_id}: {output_name} HTTP status is not 200")
        if output.get("sha256") != _sha256(response_path):
            raise ValueError(f"{case_id}: {output_name} HTTP hash mismatch")

    rendered_capture = _read_json(candidate_dir / "rendered-capture.json")
    if int(rendered_capture.get("page_count") or 0) != source_page_count:
        raise ValueError(f"{case_id}: rendered capture page count mismatch")
    if rendered_capture.get("source_response_sha256") != _sha256(response_json_path):
        raise ValueError(f"{case_id}: rendered capture is not bound to response.json")

    return {
        "case_id": case_id,
        "source": {
            "page_count": source_page_count,
            **_artifact(source_path, run_dir.parent.parent.parent.parent.parent),
        },
        "llamaparse": {
            "artifact_root": reference_dir.parent.relative_to(run_dir).as_posix(),
            "job_id": job.get("id"),
            "project_id": job.get("project_id"),
            "status": job.get("status"),
            "tier": job.get("tier"),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
            "job_record": _artifact(reference_dir / "job.json", run_dir),
            "raw_markdown": _artifact(reference_dir / "reference.md", run_dir),
            "full_json": _artifact(reference_dir / "reference.json", run_dir),
            "rendered_dom": reference_dom,
            "rendered_png": reference_png,
        },
        "service": {
            "http": outputs,
            "raw_markdown": _artifact(response_md_path, run_dir),
            "full_json": _artifact(response_json_path, run_dir),
            "rendered_capture_manifest": _artifact(
                candidate_dir / "rendered-capture.json", run_dir
            ),
            "rendered_dom": candidate_dom,
            "markdown_matches_canonical_json_exactly": True,
        },
    }


def build_manifest(
    run_dir: Path,
    *,
    corpus_dir: Path,
    corpus_manifest: Path,
    service_dir: Path,
    expected_project_id: str = EXPECTED_PROJECT_ID,
    upload_limit_bytes: int = DEFAULT_UPLOAD_LIMIT_BYTES,
    reference_roots: Mapping[str, str] | None = None,
    reference_selection_path: Path | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    corpus_dir = corpus_dir.resolve()
    corpus_manifest = corpus_manifest.resolve()
    service_dir = service_dir.resolve()
    selected_roots = dict(reference_roots or {})
    corpus_payload = _read_json(corpus_manifest)
    manifest_cases = corpus_payload.get("cases")
    if not isinstance(manifest_cases, list) or len(manifest_cases) != 15:
        raise ValueError("the benchmark manifest must contain exactly 15 cases")
    service_run = _read_json(service_dir / "run.json")
    service_cases = {
        str(row.get("case_id")): row
        for row in service_run.get("cases") or []
        if isinstance(row, Mapping) and row.get("case_id")
    }
    if len(service_cases) != 15:
        raise ValueError("the service run must contain exactly 15 cases")

    cases: list[dict[str, Any]] = []
    for case in manifest_cases:
        case_id = str(case["case_id"])
        source = case.get("source") or {}
        page_count = int(source.get("page_count") or 0)
        if page_count < 1:
            raise ValueError(f"{case_id}: invalid source page count")
        cases.append(
            _case_record(
                run_dir=run_dir,
                corpus_dir=corpus_dir,
                service_dir=service_dir,
                case_id=case_id,
                source_page_count=page_count,
                service_http=service_cases.get(case_id) or {},
                expected_project_id=expected_project_id,
                reference_roots=selected_roots,
            )
        )

    largest_source = max(cases, key=lambda row: row["source"]["size_bytes"])
    if largest_source["source"]["size_bytes"] > upload_limit_bytes:
        raise ValueError("a benchmark PDF exceeds the configured upload limit")

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_dir.name,
        "project_id": expected_project_id,
        "reference_tier": "agentic",
        "reference_selection": (
            _artifact(reference_selection_path.resolve(), run_dir)
            if reference_selection_path is not None
            else None
        ),
        "case_count": len(cases),
        "source_page_count": sum(row["source"]["page_count"] for row in cases),
        "upload_limit_bytes": upload_limit_bytes,
        "all_sources_within_upload_limit": True,
        "largest_source": {
            "case_id": largest_source["case_id"],
            "size_bytes": largest_source["source"]["size_bytes"],
        },
        "reference_raw_markdown_count": len(cases),
        "reference_full_json_count": len(cases),
        "reference_rendered_dom_count": sum(
            len(row["llamaparse"]["rendered_dom"]) for row in cases
        ),
        "reference_rendered_png_count": sum(
            len(row["llamaparse"]["rendered_png"]) for row in cases
        ),
        "service_raw_markdown_count": len(cases),
        "service_full_json_count": len(cases),
        "service_rendered_dom_count": sum(
            len(row["service"]["rendered_dom"]) for row in cases
        ),
        "service_http_200_output_count": sum(
            len(row["service"]["http"]) for row in cases
        ),
        "service_profile": _artifact(run_dir / "service-profile.json", run_dir),
        "service_run": _artifact(service_dir / "run.json", run_dir),
        "corpus_manifest": _artifact(corpus_manifest, corpus_manifest.parent),
        "cases": cases,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--corpus", type=Path, default=Path("benchmark-expertmodeldata"))
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        default=Path("tracker/benchmarks/llamaparse-15/manifest.json"),
    )
    parser.add_argument("--service-dir", type=Path, default=Path("service-post-fix"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--project-id", default=EXPECTED_PROJECT_ID)
    parser.add_argument(
        "--reference-selection",
        type=Path,
        help="JSON mapping case IDs to immutable reference artifact roots within RUN_DIR.",
    )
    parser.add_argument(
        "--upload-limit-bytes", type=int, default=DEFAULT_UPLOAD_LIMIT_BYTES
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    run_dir = args.run_dir.resolve()
    service_dir = args.service_dir
    if not service_dir.is_absolute() and len(service_dir.parts) == 1:
        service_dir = run_dir / service_dir
    output = (args.output or run_dir / "artifact-manifest.json").resolve()
    reference_selection = (
        args.reference_selection.resolve() if args.reference_selection else None
    )
    manifest = build_manifest(
        run_dir,
        corpus_dir=args.corpus,
        corpus_manifest=args.corpus_manifest,
        service_dir=service_dir,
        expected_project_id=args.project_id,
        upload_limit_bytes=args.upload_limit_bytes,
        reference_roots=_load_reference_roots(reference_selection),
        reference_selection_path=reference_selection,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "case_count": manifest["case_count"],
                "source_page_count": manifest["source_page_count"],
                "reference_rendered_dom_count": manifest[
                    "reference_rendered_dom_count"
                ],
                "service_rendered_dom_count": manifest[
                    "service_rendered_dom_count"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
