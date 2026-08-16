#!/usr/bin/env python3
"""Capture raw HTTP JSON and Markdown for the LlamaParse-15 corpus."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import httpx


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _write_json(path: Path, value: Any) -> None:
    _write_bytes(
        path,
        (
            json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n"
        ).encode("utf-8"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()

    corpus = args.corpus.resolve()
    output = args.output.resolve()
    selected = set(args.cases or ())
    sources = sorted(corpus.glob("*.pdf"))
    if selected:
        sources = [source for source in sources if source.stem in selected]
        missing = selected - {source.stem for source in sources}
        if missing:
            raise SystemExit(f"unknown cases: {', '.join(sorted(missing))}")
    if not sources:
        raise SystemExit("no PDF sources selected")

    started_at = _utc_now()
    cases: list[dict[str, Any]] = []
    profile: Any = None
    if args.profile:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
    run = {
        "schema_version": "functional-fidelity-service-run-v1",
        "started_at_utc": started_at,
        "completed_at_utc": None,
        "base_url": args.base_url,
        "corpus": str(corpus),
        "profile": profile,
        "cases": cases,
    }
    _write_json(output / "run.json", run)

    timeout = httpx.Timeout(330.0)
    exit_code = 0
    with httpx.Client(timeout=timeout) as client:
        for index, source in enumerate(sources, start=1):
            record: dict[str, Any] = {
                "case_id": source.stem,
                "order": index,
                "source_path": str(source),
                "source_size_bytes": source.stat().st_size,
                "source_sha256": _sha256(source.read_bytes()),
                "started_at_utc": _utc_now(),
                "outputs": {},
            }
            case_dir = output / source.stem
            for output_format, filename in (
                ("json", "response.json"),
                ("markdown", "response.md"),
            ):
                try:
                    with source.open("rb") as stream:
                        response = client.post(
                            f"{args.base_url.rstrip('/')}/v1/parse",
                            params={"output_format": output_format},
                            headers={"accept": (
                                "application/json"
                                if output_format == "json"
                                else "text/markdown"
                            )},
                            files={
                                "file": (
                                    source.name,
                                    stream,
                                    "application/pdf",
                                )
                            },
                        )
                    payload = response.content
                    _write_bytes(case_dir / filename, payload)
                    record["outputs"][output_format] = {
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "size_bytes": len(payload),
                        "sha256": _sha256(payload),
                    }
                    if response.status_code != 200:
                        exit_code = 1
                except Exception as exc:  # noqa: BLE001 - retain all failures.
                    exit_code = 1
                    record["outputs"][output_format] = {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
            record["completed_at_utc"] = _utc_now()
            cases.append(record)
            run["cases"] = cases
            _write_json(output / "run.json", run)
            print(
                json.dumps(
                    {
                        "case_id": source.stem,
                        "completed": index,
                        "total": len(sources),
                        "outputs": record["outputs"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    run["completed_at_utc"] = _utc_now()
    run["status"] = "success" if exit_code == 0 else "completed_with_errors"
    _write_json(output / "run.json", run)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
