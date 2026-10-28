"""Optional, explicitly allowlisted UI hosting beside the parsing API."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import Response


_PUBLIC_FILES = {
    "/": ("index.html", "text/html"),
    "/studio": ("studio/index.html", "text/html"),
    "/knowledge": ("knowledge/index.html", "text/html"),
    "/privacy": ("privacy/index.html", "text/html"),
    "/parse": ("parse/index.html", "text/html"),
    "/extract": ("extract/index.html", "text/html"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/pdf.worker.min.mjs": ("pdf.worker.min.mjs", "text/javascript"),
    "/og-knowledge.svg": ("og-knowledge.svg", "image/svg+xml"),
    "/robots.txt": ("robots.txt", "text/plain"),
    "/samples/customer-support-handbook.pdf": (
        "samples/customer-support-handbook.pdf",
        "application/pdf",
    ),
}
# Vite emits direct, content-hashed JS/CSS files. Do not expose source maps,
# arbitrary extensions, nested directories, or the whole configured directory.
_ASSET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*-[A-Za-z0-9_-]{8,}\.(js|css)")
_MAX_PUBLIC_FILE_BYTES = 16 * 1024 * 1024
_MAX_PUBLIC_TOTAL_BYTES = 64 * 1024 * 1024


def _open_directory(path: Path) -> int:
    """Walk every component without following even an ancestor symlink."""

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child_fd = os.open(part, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        return directory_fd
    except BaseException:
        os.close(directory_fd)
        raise


def _read_public_file(directory_fd: int, relative_path: str) -> bytes | None:
    """Read a regular file through directory descriptors, never symlinks."""

    current_fd = os.dup(directory_fd)
    file_fd = None
    try:
        parts = relative_path.split("/")
        for part in parts[:-1]:
            child_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = child_fd
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=current_fd,
        )
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            return None
        if metadata.st_size > _MAX_PUBLIC_FILE_BYTES:
            raise RuntimeError("A public UI file exceeds the 16 MiB hosting limit.")
        with os.fdopen(file_fd, "rb") as source:
            file_fd = None
            content = source.read(_MAX_PUBLIC_FILE_BYTES + 1)
        if len(content) > _MAX_PUBLIC_FILE_BYTES:
            raise RuntimeError("A public UI file exceeds the 16 MiB hosting limit.")
        return content
    except OSError:
        # Missing files and symlinks are not public routes. There is no SPA
        # fallback that could turn missing API or private paths into HTML.
        return None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(current_fd)


def _asset_names(directory_fd: int) -> list[str]:
    try:
        assets_fd = os.open(
            "assets",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
    except OSError:
        return []
    try:
        return sorted(name for name in os.listdir(assets_fd) if _ASSET_NAME.fullmatch(name))
    finally:
        os.close(assets_fd)


def _static_response(content: bytes, media_type: str, *, immutable: bool) -> Callable:
    async def serve() -> Response:
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Cache-Control": (
                    "public, max-age=31536000, immutable" if immutable else "no-cache"
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    return serve


def register_public_routes(application: FastAPI) -> None:
    """Register process health and opt-in public assets after API routes.

    Snapshot the small approved build at startup. Requests never read arbitrary
    filesystem paths, and replacing a file with a symlink cannot expose it.
    A new UI build takes effect when the application restarts.
    """

    @application.get("/healthz", include_in_schema=False)
    async def process_health() -> dict[str, str]:
        return {"status": "ok", "check": "process"}

    configured_path = os.environ.get("PARSER_UI_DIST_PATH", "").strip()
    if not configured_path:
        return
    root = Path(os.path.abspath(configured_path))
    try:
        directory_fd = _open_directory(root)
    except OSError as exc:
        raise RuntimeError(
            "PARSER_UI_DIST_PATH must be an existing directory without symlinks."
        ) from exc

    public_files = dict(_PUBLIC_FILES)
    snapshots: list[tuple[str, bytes, str]] = []
    try:
        for name in _asset_names(directory_fd):
            media_type = "text/css" if name.endswith(".css") else "text/javascript"
            public_files[f"/assets/{name}"] = (f"assets/{name}", media_type)
        total_bytes = 0
        for route, (relative_path, media_type) in public_files.items():
            content = _read_public_file(directory_fd, relative_path)
            if content is None:
                if route == "/":
                    raise RuntimeError(
                        "PARSER_UI_DIST_PATH must contain a regular index.html file."
                    )
                continue
            total_bytes += len(content)
            if total_bytes > _MAX_PUBLIC_TOTAL_BYTES:
                raise RuntimeError("The public UI exceeds the 64 MiB hosting limit.")
            snapshots.append((route, content, media_type))
    finally:
        os.close(directory_fd)

    for route, content, media_type in snapshots:
        application.add_api_route(
            route,
            _static_response(content, media_type, immutable=route.startswith("/assets/")),
            methods=["GET", "HEAD"],
            include_in_schema=False,
            name=f"public-ui:{route}",
        )
