#!/usr/bin/env python3
"""Finalize the immutable four-case HTTP capture manifest."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[5]
CASES = (
    "finance-10k",
    "ny-timetable",
    "postal-10k",
    "purchase-agreement",
)


def digest(path: Path) -> dict[str, object]:
    value = path.read_bytes()
    return {"size_bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}


profile = json.loads(
    (
        ROOT.parent / "service-profile.json"
    ).read_text(encoding="utf-8")
)
records = []
for order, case in enumerate(CASES, start=1):
    source = WORKSPACE / "benchmark-expertmodeldata" / f"{case}.pdf"
    records.append(
        {
            "case_id": case,
            "order": order,
            "source_path": str(source),
            "source_size_bytes": source.stat().st_size,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "outputs": {
                "json": {
                    "status_code": 200,
                    "content_type": "application/json",
                    **digest(ROOT / case / "response.json"),
                },
                "markdown": {
                    "status_code": 200,
                    "content_type": "text/markdown; charset=utf-8",
                    **digest(ROOT / case / "response.md"),
                },
            },
        }
    )

payload = {
    "schema_version": "functional-fidelity-service-run-v1",
    "capture_mode": "fresh_server_per_http_output",
    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    "base_url": "http://127.0.0.1:8027",
    "corpus": str(WORKSPACE / "benchmark-expertmodeldata"),
    "profile": profile,
    "status": "success",
    "cases": records,
}
(ROOT / "run.json").write_text(
    json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    encoding="utf-8",
)
