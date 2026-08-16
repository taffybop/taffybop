"""Digest-pinned release entry point used by the production container."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from app.services.artifact_manifest import (
    STARTUP_MANIFEST_PATH_ENV,
    STARTUP_MANIFEST_SHA256_ENV,
)


def main() -> None:
    digest_path = Path(
        os.environ.get(
            "PARSER_RELEASE_ARTIFACT_MANIFEST_DIGEST_PATH",
            "/app/release/shipped-artifacts.sha256",
        )
    )
    if digest_path.is_symlink() or not digest_path.is_file():
        raise RuntimeError("release artifact digest file is unavailable or unsafe")
    digest = digest_path.read_text(encoding="ascii").strip()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeError("release artifact digest file is invalid")
    configured = os.environ.get(STARTUP_MANIFEST_SHA256_ENV)
    if configured is not None and configured != digest:
        raise RuntimeError("configured release digest differs from the image digest")
    os.environ[STARTUP_MANIFEST_SHA256_ENV] = digest
    if not os.environ.get(STARTUP_MANIFEST_PATH_ENV):
        raise RuntimeError("release artifact manifest path is not configured")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, workers=1)


if __name__ == "__main__":
    main()
