#!/usr/bin/env python3
"""Run the current parser reproducibly into a new immutable run directory."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import subprocess
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SETTINGS: dict[str, Any] = {
    "max_upload_bytes": 25 * 1024 * 1024,
    "max_pages": 100,
    "max_image_pixels": 50_000_000,
    "max_image_total_pixels": 100_000_000,
    "document_timeout_seconds": 300.0,
    "ocr_languages": ("eng",),
    "tesseract_cmd": "tesseract",
    "tesseract_data_path": None,
    "targeted_ocr_timeout_seconds": 30.0,
    "targeted_ocr_scale": 5.0,
    "targeted_ocr_max_pixels": 16_000_000,
    "docling_artifacts_path": None,
    "image_primary_ocr_min_confidence": 0.45,
    "image_low_confidence_min_alnum_chars": 8,
    "image_heading_min_confidence": 0.75,
    "image_heading_height_ratio": 1.8,
    "image_heading_min_page_height_ratio": 0.025,
    "image_picture_classification_threshold": 0.6,
    "image_captioning_enabled": False,
    "image_captioning_prompt": (
        "Describe this visible image faithfully in one concise sentence. "
        "Do not infer hidden text, values, or relationships."
    ),
    "pdf_visual_analysis_enabled": True,
    "pdf_render_ocr_min_native_alnum_chars": 24,
    "pdf_render_ocr_min_layout_coverage": 0.55,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_tree_hash() -> str:
    digest = hashlib.sha256()
    paths = sorted((REPO_ROOT / "app").rglob("*.py"))
    paths.extend(
        path
        for path in (REPO_ROOT / "pyproject.toml", REPO_ROOT / "README.md")
        if path.is_file()
    )
    for path in paths:
        relative = path.relative_to(REPO_ROOT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def tesseract_version(command: str) -> str | None:
    try:
        completed = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first_line = (completed.stdout or completed.stderr).splitlines()
    return first_line[0].strip() if first_line else None


def normalized_peak_rss_bytes() -> int:
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux reports KiB.
    return raw if sys.platform == "darwin" else raw * 1024


def summarize_result(payload: dict[str, Any]) -> dict[str, Any]:
    pages = payload.get("pages") or []
    type_counts: Counter[str] = Counter()
    page_summaries: list[dict[str, Any]] = []
    total_items = 0
    total_detected_images = 0
    for page in pages:
        items = page.get("items") or []
        total_items += len(items)
        for item in items:
            type_counts[str(item.get("type") or "unknown")] += 1
        detected_images = page.get("detected_images") or []
        total_detected_images += len(detected_images)
        page_summaries.append(
            {
                "page_index": page.get("page_index"),
                "page_number": page.get("page_number"),
                "success": page.get("success"),
                "item_count": len(items),
                "detected_image_count": len(detected_images),
                "warnings": page.get("warnings") or [],
                "item_type_counts": dict(
                    Counter(
                        str(item.get("type") or "unknown") for item in items
                    )
                ),
            }
        )
    return {
        "page_count": len(pages),
        "total_item_count": total_items,
        "item_type_counts": dict(sorted(type_counts.items())),
        "detected_image_count": total_detected_images,
        "document_warnings": payload.get("warnings") or [],
        "processing": payload.get("processing"),
        "pages": page_summaries,
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_worker(source: Path, output_dir: Path) -> int:
    from app.config import Settings
    from app.services.pipeline import parse_document
    from app.services.serializer import to_markdown

    output_dir.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    settings = Settings(**DEFAULT_SETTINGS)
    started_at = utc_now()
    started_perf = time.perf_counter()
    started_process = time.process_time()
    status = "success"
    error: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    markdown: str | None = None
    try:
        result = parse_document(source_bytes, source.name, settings)
        payload = result.model_dump(mode="json")
        markdown = to_markdown(result)
        write_json(output_dir / "our-output.json", payload)
        (output_dir / "our-output.md").write_text(markdown, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - benchmark must record all failures.
        status = "error"
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    elapsed_seconds = time.perf_counter() - started_perf
    cpu_seconds = time.process_time() - started_process
    diagnostics: dict[str, Any] = {
        "schema_version": "1.0",
        "case_id": source.stem,
        "source_filename": source.name,
        "source_size_bytes": len(source_bytes),
        "source_sha256": sha256_bytes(source_bytes),
        "status": status,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "elapsed_seconds": elapsed_seconds,
        "process_cpu_seconds": cpu_seconds,
        "peak_rss_bytes": normalized_peak_rss_bytes(),
        "settings": dataclasses.asdict(settings),
        "operating_mode": {
            "parser_invocation": "direct app.services.pipeline.parse_document",
            "network_services_enabled": False,
            "image_captioning_enabled": settings.image_captioning_enabled,
            "pdf_visual_analysis_enabled": settings.pdf_visual_analysis_enabled,
            "optional_model_configuration": None,
        },
        "versions": {
            "application": package_version("document-parse-api"),
            "source_tree_sha256": source_tree_hash(),
            "python": sys.version,
            "platform": platform.platform(),
            "docling": package_version("docling"),
            "docling-core": package_version("docling-core"),
            "pdfplumber": package_version("pdfplumber"),
            "pypdfium2": package_version("pypdfium2"),
            "pillow": package_version("Pillow"),
            "tesseract": tesseract_version(settings.tesseract_cmd),
        },
        "error": error,
    }
    if payload is not None and markdown is not None:
        output_json_bytes = (output_dir / "our-output.json").read_bytes()
        diagnostics["output"] = {
            **summarize_result(payload),
            "json_size_bytes": len(output_json_bytes),
            "json_sha256": sha256_bytes(output_json_bytes),
            "markdown_size_bytes": len(markdown.encode("utf-8")),
            "markdown_sha256": sha256_bytes(markdown.encode("utf-8")),
        }
    write_json(output_dir / "diagnostics.json", diagnostics)
    return 0 if status == "success" else 1


def system_metadata() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    return {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "total_memory_bytes": int(memory.total),
        "application_version": package_version("document-parse-api"),
        "source_tree_sha256": source_tree_hash(),
        "packages": {
            name: package_version(name)
            for name in (
                "docling",
                "docling-core",
                "pdfplumber",
                "pypdfium2",
                "Pillow",
                "pydantic",
                "torch",
                "torchvision",
            )
        },
        "tesseract": tesseract_version(DEFAULT_SETTINGS["tesseract_cmd"]),
    }


def run_all(
    corpus_root: Path,
    run_dir: Path,
    selected_cases: list[str] | None,
) -> int:
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise SystemExit(
            "refusing to overwrite existing immutable run directory: "
            f"{run_dir}"
        ) from exc
    all_sources = sorted(corpus_root.glob("*.pdf"))
    if selected_cases:
        selected = set(selected_cases)
        sources = [source for source in all_sources if source.stem in selected]
        missing = selected - {source.stem for source in sources}
        if missing:
            raise SystemExit(f"unknown cases: {', '.join(sorted(missing))}")
    else:
        sources = all_sources
    run_started = utc_now()
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        str(corpus_root.resolve()),
        "--run-dir",
        str(run_dir.resolve()),
    ]
    if selected_cases:
        command.extend(["--cases", *selected_cases])
    (run_dir / "command.txt").write_text(
        " ".join(command) + "\n", encoding="utf-8"
    )
    write_json(
        run_dir / "run-metadata.json",
        {
            "schema_version": "1.0",
            "run_started_at_utc": run_started,
            "run_completed_at_utc": None,
            "status": "running",
            "corpus_root": str(corpus_root.resolve()),
            "run_dir": str(run_dir.resolve()),
            "case_ids": [source.stem for source in sources],
            "case_count": len(sources),
            "execution": "sequential isolated worker process per case",
            "settings": {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in DEFAULT_SETTINGS.items()
            },
            "operating_mode": (
                "local deterministic core; PDF visual analysis enabled; "
                "image captioning and optional models disabled"
            ),
            "environment": system_metadata(),
            "cases": [],
        },
    )
    results: list[dict[str, Any]] = []
    overall_status = 0
    for index, source in enumerate(sources, start=1):
        case_dir = run_dir / source.stem
        case_dir.mkdir(parents=True, exist_ok=True)
        started = utc_now()
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker-source",
                str(source.resolve()),
                "--worker-output",
                str(case_dir.resolve()),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=DEFAULT_SETTINGS["document_timeout_seconds"] + 120,
        )
        (case_dir / "stdout.log").write_text(
            completed.stdout, encoding="utf-8"
        )
        (case_dir / "stderr.log").write_text(
            completed.stderr, encoding="utf-8"
        )
        result = {
            "case_id": source.stem,
            "order": index,
            "started_at_utc": started,
            "completed_at_utc": utc_now(),
            "worker_exit_code": completed.returncode,
        }
        diagnostics_path = case_dir / "diagnostics.json"
        if diagnostics_path.is_file():
            diagnostics = json.loads(
                diagnostics_path.read_text(encoding="utf-8")
            )
            result.update(
                {
                    "status": diagnostics.get("status"),
                    "elapsed_seconds": diagnostics.get("elapsed_seconds"),
                    "peak_rss_bytes": diagnostics.get("peak_rss_bytes"),
                    "error": diagnostics.get("error"),
                }
            )
        else:
            result.update(
                {
                    "status": "worker_failed_without_diagnostics",
                    "elapsed_seconds": None,
                    "peak_rss_bytes": None,
                    "error": {
                        "stderr": completed.stderr[-4000:],
                    },
                }
            )
        results.append(result)
        if completed.returncode != 0:
            overall_status = 1
        metadata_path = run_dir / "run-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["cases"] = results
        write_json(metadata_path, metadata)
    metadata_path = run_dir / "run-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        {
            "run_completed_at_utc": utc_now(),
            "status": "success" if overall_status == 0 else "completed_with_errors",
            "cases": results,
        }
    )
    write_json(metadata_path, metadata)
    return overall_status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_root", nargs="?", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--worker-source", type=Path)
    parser.add_argument("--worker-output", type=Path)
    args = parser.parse_args()
    if args.worker_source is not None:
        if args.worker_output is None:
            parser.error("--worker-output is required with --worker-source")
        raise SystemExit(run_worker(args.worker_source, args.worker_output))
    if args.corpus_root is None or args.run_dir is None:
        parser.error("corpus_root and --run-dir are required")
    raise SystemExit(
        run_all(args.corpus_root.resolve(), args.run_dir.resolve(), args.cases)
    )


if __name__ == "__main__":
    main()
