"""Focused HTTP smoke for the built container; uses only Python's standard library.

Response JSON files contain the exact received bytes. This is deployment and
source-fidelity evidence for two public samples, not an extraction benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        candidate = values.get("src") if tag == "script" else values.get("href") if tag == "link" else None
        if candidate and candidate.startswith("/assets/") and candidate.endswith((".js", ".css")):
            self.assets.add(candidate)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def response(base: str, route: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 240) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(base + route, data=data, headers=headers or {})
    try:
        result = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        result = error
    with result:
        return result.status, dict(result.headers.items()), result.read()


def wait_until_healthy(base: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _, body = response(base, "/healthz", timeout=5)
            if status == 200 and json.loads(body).get("status") == "ok":
                return
        except (OSError, ValueError):
            pass
        time.sleep(3)
    raise RuntimeError(f"Container did not pass /healthz within {timeout}s")


def extracted_text(value: object) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"value", "text", "ocr_text", "md"} and isinstance(child, str):
                parts.append(child)
            elif isinstance(child, (dict, list)):
                parts.append(extracted_text(child))
    elif isinstance(value, list):
        parts.extend(extracted_text(child) for child in value)
    return "\n".join(parts)


def parse_sample(base: str, source: Path, mime: str, expected_pages: int, expected_text: str, output: Path, label: str) -> dict[str, object]:
    original = source.read_bytes()
    boundary = f"taffybop-{uuid.uuid4().hex}"
    multipart = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{source.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + original + f"\r\n--{boundary}--\r\n".encode()
    started = time.monotonic()
    status, headers, body = response(base, "/v1/parse?output_format=json", multipart, {
        "Accept": "application/json", "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    elapsed = round(time.monotonic() - started, 3)
    (output / f"{label}-response.body").write_bytes(body)
    (output / f"{label}-headers.json").write_text(json.dumps({"status": status, "headers": headers}, indent=2) + "\n")
    parsed = json.loads(body)
    (output / f"{label}-response.json").write_bytes(body)
    require(status == 200, f"{label} parse returned HTTP {status}; see retained response")
    require(isinstance(parsed, dict) and "error" not in parsed, f"{label} returned an error envelope")
    document = parsed.get("document", {})
    source_hash = hashlib.sha256(original).hexdigest()
    require(document.get("filename") == source.name, f"{label} filename identity differs")
    require(document.get("sha256") == source_hash, f"{label} source byte identity differs")
    require(document.get("page_count") == expected_pages, f"{label} document page count differs")
    pages = parsed.get("pages", [])
    require(len(pages) == expected_pages, f"{label} page count differs")
    require([page.get("page_index") for page in pages] == list(range(1, expected_pages + 1)), f"{label} physical page indices differ")
    require(all(page.get("success") is True and page.get("items") for page in pages), f"{label} contains failed or empty pages")
    require(isinstance(parsed.get("processing"), dict), f"{label} processing metadata absent")
    require(isinstance(parsed.get("canonical_presentation"), dict), f"{label} deployment feature settings did not produce canonical output")
    require(expected_text.casefold() in extracted_text(pages).casefold(), f"{label} expected source text absent")
    return {
        "sample": label, "status": status, "elapsed_seconds": elapsed,
        "source_sha256": source_hash, "response_sha256": hashlib.sha256(body).hexdigest(),
        "response_bytes": len(body), "pages": len(pages),
        "warnings": parsed.get("warnings", []), "processing": parsed["processing"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18042")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--png", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-timeout", type=int, default=300)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {"status": "running", "checks": [], "samples": []}
    try:
        wait_until_healthy(args.base_url, args.startup_timeout)
        summary["checks"].append("process health")
        status, _, html = response(args.base_url, "/studio")
        (args.output / "studio.html").write_bytes(html)
        require(status == 200 and b'id="root"' in html, "Studio HTML is unavailable")
        assets = AssetParser()
        assets.feed(html.decode("utf-8"))
        require(any(path.endswith(".js") for path in assets.assets), "Studio has no JavaScript asset")
        require(any(path.endswith(".css") for path in assets.assets), "Studio has no stylesheet")
        for path in [*sorted(assets.assets), "/pdf.worker.min.mjs"]:
            status, _, content = response(args.base_url, path)
            require(status == 200 and bool(content), f"Public asset failed: {path}")
        summary["checks"].append("studio HTML, JavaScript, CSS, and PDF worker")
        for path in ["/.env", "/app/main.py", "/frontend/package.json", "/v1/unknown"]:
            status, _, _ = response(args.base_url, path)
            require(status == 404, f"Unexpected public route: {path} returned {status}")
        summary["checks"].append("private and unknown API paths return 404")
        summary["samples"].append(parse_sample(args.base_url, args.pdf, "application/pdf", 3, "30 calendar days", args.output, "handbook"))
        summary["samples"].append(parse_sample(args.base_url, args.png, "image/png", 1, "SMOKE TEST", args.output, "image"))
        summary["status"] = "passed"
    except Exception as error:
        summary["status"] = "failed"
        summary["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"status": summary["status"], "checks": summary["checks"]}))


if __name__ == "__main__":
    main()
